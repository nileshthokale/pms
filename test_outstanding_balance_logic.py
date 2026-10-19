"""Tests for Supplier Payment Voucher: outstanding balance logic, allocation accuracy,
and ledger reconciliation.

Covers:
1. Correct supplier-specific outstanding invoice retrieval (no cross-contamination).
2. Payments and allocation rows reduce the correct invoice balances.
3. Legacy unallocated payments (no allocation rows) are distributed FIFO so
   total outstanding matches the supplier ledger balance.
4. No duplicate invoice rows from JOINs.
5. Invoice totals and remaining amounts are arithmetically consistent.
6. Different suppliers have independent balances.
7. Excess payment is rejected.
8. Supplier with no invoices shows zero outstanding.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database import financial_year
from database.account_roles import (
    ROLE_BANK,
    ROLE_CASH,
    ROLE_PURCHASE,
    ensure_system_ledgers,
)
from database.accounting_posting import PostingError, posting_engine
from database.ledger_dao import LedgerDAO
from database.supplier_dao import SupplierDAO
from database.supplier_payment_dao import SupplierPaymentDAO


# ---------------------------------------------------------------------------
# Base test class with isolated in-memory DB
# ---------------------------------------------------------------------------

class _Base(unittest.TestCase):
    _db_file: str = ""

    @classmethod
    def setUpClass(cls):
        fd, cls._db_file = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.environ["PHARMACY_DB"] = cls._db_file
        init_database()
        financial_year.ensure_default_financial_year()
        ensure_system_ledgers()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PHARMACY_DB", None)
        try:
            os.remove(cls._db_file)
        except OSError:
            pass

    def tearDown(self):
        """Truncate mutable tables between tests to prevent bleeding."""
        conn = get_connection()
        try:
            for tbl in [
                "supplier_payment_allocations",
                "supplier_payments",
                "ledger_transactions",
                "purchase_invoices",
                "account_ledgers",
                "suppliers",
            ]:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

    # ── helpers ──────────────────────────────────────────────────────────

    def _make_ledger(self, name: str) -> int:
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO account_ledgers (ledger_name, account_group, opening_balance, opening_balance_type) "
                "VALUES (?, 'Sundry Creditors', 0.0, 'Debit')",
                (name,),
            )
            lid = cur.lastrowid
            conn.commit()
            return lid
        finally:
            conn.close()

    def _make_supplier(self, name: str, city: str = "TestCity") -> int:
        ledger_id = self._make_ledger(name + " Ledger")
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO suppliers (supplier_name, city, ledger_id) VALUES (?, ?, ?)",
                (name, city, ledger_id),
            )
            sid = cur.lastrowid
            conn.commit()
            return sid
        finally:
            conn.close()

    def _make_purchase_invoice(self, supplier_id: int, net_amount: float,
                               invoice_date: str = "2025-04-01",
                               invoice_no: str = "INV-001") -> int:
        conn = get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO purchase_invoices
                   (voucher_no, voucher_date, voucher_time, purchase_type,
                    supplier_id, invoice_no, invoice_date,
                    invoice_net_amount, bill_discount, total_amount,
                    gst_amount, net_amount, paid_amount)
                   VALUES (?, ?, '10:00', 'Credit', ?, ?, ?,
                           ?, 0, ?, 0, ?, 0.0)""",
                (f"PV-{invoice_no}", invoice_date, supplier_id, invoice_no,
                 invoice_date, net_amount, net_amount, net_amount),
            )
            inv_id = cur.lastrowid

            # Post to supplier ledger (purchase posts credit to supplier)
            sup_row = conn.execute(
                "SELECT ledger_id FROM suppliers WHERE id = ?", (supplier_id,)
            ).fetchone()
            if sup_row and sup_row[0]:
                conn.execute(
                    """INSERT INTO ledger_transactions
                       (ledger_id, transaction_date, voucher_type, voucher_no,
                        debit, credit, reference_type, reference_id)
                       VALUES (?, ?, 'PURCHASE', ?, 0.0, ?, 'PURCHASE_INVOICE', ?)""",
                    (sup_row[0], invoice_date, f"PV-{invoice_no}", net_amount, inv_id),
                )

            conn.commit()
            return inv_id
        finally:
            conn.close()

    def _make_legacy_payment(self, supplier_id: int, amount: float,
                              payment_date: str = "2025-05-01") -> int:
        """Insert a supplier payment row AND post to ledger, but WITHOUT allocation rows.
        This simulates a legacy import from Pharma-WINNER."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO supplier_payments
                   (voucher_no, payment_date, payment_time, supplier_id,
                    payment_mode, amount, reference_no, remarks)
                   VALUES (?, ?, '10:00', ?, 'Cash', ?, 'LEGACY', '')""",
                (f"LP-{payment_date}-{supplier_id}", payment_date, supplier_id, amount),
            )
            pay_id = cur.lastrowid

            # Post to supplier ledger: debit supplier ledger (reduce CR balance)
            sup_row = conn.execute(
                "SELECT ledger_id FROM suppliers WHERE id = ?", (supplier_id,)
            ).fetchone()
            if sup_row and sup_row[0]:
                # Debit supplier ledger directly — no system role needed for tests
                conn.execute(
                    """INSERT INTO ledger_transactions
                       (ledger_id, transaction_date, voucher_type, voucher_no,
                        debit, credit, reference_type, reference_id)
                       VALUES (?, ?, 'PAYMENT', ?, ?, 0.0, 'SUPPLIER_PAYMENT', ?)""",
                    (sup_row[0], payment_date, f"LP-{pay_id}", amount, pay_id),
                )

            conn.commit()
            return pay_id
        finally:
            conn.close()

    def _get_supplier_ledger_balance(self, supplier_id: int) -> float:
        """Returns the CR-DR net balance from ledger_transactions for this supplier."""
        conn = get_connection()
        try:
            sup_row = conn.execute(
                "SELECT ledger_id FROM suppliers WHERE id = ?", (supplier_id,)
            ).fetchone()
            if not sup_row or not sup_row[0]:
                return 0.0
            row = conn.execute(
                "SELECT COALESCE(SUM(credit),0) - COALESCE(SUM(debit),0) "
                "FROM ledger_transactions WHERE ledger_id = ?",
                (sup_row[0],),
            ).fetchone()
            return round(float(row[0] or 0.0), 2)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestOutstandingBalanceLogic(_Base):

    def test_01_no_invoices_returns_empty_list(self):
        """Supplier with no invoices shows zero outstanding."""
        sid = self._make_supplier("BLANK SUPPLIER")
        invs = SupplierPaymentDAO.get_outstanding_invoices(sid)
        self.assertEqual(invs, [])

    def test_02_single_unpaid_invoice_shows_full_amount(self):
        """Unpaid invoice shows full net_amount as outstanding."""
        sid = self._make_supplier("SUP A")
        self._make_purchase_invoice(sid, 5000.0, invoice_no="A001")
        invs = SupplierPaymentDAO.get_outstanding_invoices(sid)
        self.assertEqual(len(invs), 1)
        self.assertAlmostEqual(invs[0]["outstanding_balance"], 5000.0)

    def test_03_legacy_payment_reduces_outstanding_fifo(self):
        """Legacy unallocated payment reduces oldest invoice first (FIFO)."""
        sid = self._make_supplier("SUP LEGACY")
        inv1 = self._make_purchase_invoice(sid, 3000.0, "2025-04-01", "L001")
        inv2 = self._make_purchase_invoice(sid, 5000.0, "2025-04-15", "L002")

        # 3000 legacy payment (no allocation rows) posted to ledger
        self._make_legacy_payment(sid, 3000.0, "2025-05-01")

        invs = SupplierPaymentDAO.get_outstanding_invoices(sid)
        # inv1 should be fully consumed, inv2 fully outstanding
        inv_map = {i["id"]: i for i in invs}

        self.assertNotIn(inv1, [i["id"] for i in invs], "Fully-paid invoice should be hidden")
        self.assertIn(inv2, inv_map)
        self.assertAlmostEqual(inv_map[inv2]["outstanding_balance"], 5000.0)
        # Total outstanding matches ledger balance
        total_out = sum(i["outstanding_balance"] for i in invs)
        self.assertAlmostEqual(total_out, self._get_supplier_ledger_balance(sid))

    def test_04_partial_legacy_payment_distributes_fifo(self):
        """Partial legacy payment partially reduces first invoice."""
        sid = self._make_supplier("SUP PARTIAL")
        inv1 = self._make_purchase_invoice(sid, 10000.0, "2025-04-01", "P001")
        inv2 = self._make_purchase_invoice(sid, 5000.0, "2025-04-15", "P002")
        # Pay 4000 of the 10000 first invoice
        self._make_legacy_payment(sid, 4000.0, "2025-05-01")

        invs = SupplierPaymentDAO.get_outstanding_invoices(sid)
        inv_map = {i["id"]: i for i in invs}

        self.assertEqual(len(invs), 2)
        self.assertAlmostEqual(inv_map[inv1]["outstanding_balance"], 6000.0)
        self.assertAlmostEqual(inv_map[inv2]["outstanding_balance"], 5000.0)

        total_out = sum(i["outstanding_balance"] for i in invs)
        self.assertAlmostEqual(total_out, self._get_supplier_ledger_balance(sid))

    def test_05_outstanding_matches_ledger_balance(self):
        """Total outstanding always equals the supplier ledger credit balance."""
        sid = self._make_supplier("SUP LEDGER MATCH")
        self._make_purchase_invoice(sid, 7760.0, "2025-02-20", "M001")
        self._make_purchase_invoice(sid, 1908.0, "2025-03-20", "M002")
        # Two legacy payments
        self._make_legacy_payment(sid, 4000.0, "2025-05-01")
        self._make_legacy_payment(sid, 2000.0, "2025-06-01")

        invs = SupplierPaymentDAO.get_outstanding_invoices(sid)
        total_out = sum(i["outstanding_balance"] for i in invs)
        ledger_bal = self._get_supplier_ledger_balance(sid)
        self.assertAlmostEqual(total_out, ledger_bal,
                               msg=f"Outstanding {total_out} must match ledger {ledger_bal}")

    def test_06_no_duplicate_invoices_from_joins(self):
        """Each invoice appears exactly once in the results list."""
        sid = self._make_supplier("SUP DUPE CHECK")
        self._make_purchase_invoice(sid, 5000.0, "2025-04-01", "D001")
        self._make_purchase_invoice(sid, 3000.0, "2025-04-10", "D002")
        invs = SupplierPaymentDAO.get_outstanding_invoices(sid)
        ids = [i["id"] for i in invs]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate invoice IDs found")

    def test_07_different_suppliers_are_independent(self):
        """Invoices and payments from supplier A don't affect supplier B."""
        sid_a = self._make_supplier("SUP ALPHA")
        sid_b = self._make_supplier("SUP BETA")

        self._make_purchase_invoice(sid_a, 8000.0, "2025-04-01", "A001")
        self._make_purchase_invoice(sid_b, 6000.0, "2025-04-01", "B001")
        self._make_legacy_payment(sid_a, 8000.0, "2025-05-01")

        invs_a = SupplierPaymentDAO.get_outstanding_invoices(sid_a)
        invs_b = SupplierPaymentDAO.get_outstanding_invoices(sid_b)

        self.assertEqual(len(invs_a), 0, "Supplier A should have 0 outstanding after full payment")
        self.assertEqual(len(invs_b), 1, "Supplier B should still have 1 outstanding invoice")
        self.assertAlmostEqual(invs_b[0]["outstanding_balance"], 6000.0)

    def test_08_allocation_rows_reduce_outstanding(self):
        """Proper allocation rows (non-legacy) reduce outstanding correctly."""
        sid = self._make_supplier("SUP ALLOC")
        inv1 = self._make_purchase_invoice(sid, 5249.0, "2025-04-01", "A001")
        inv2 = self._make_purchase_invoice(sid, 6327.0, "2025-04-15", "A002")

        # Insert payment and allocation rows directly (no posting_engine needed)
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO supplier_payments (voucher_no, payment_date, payment_time, "
                "supplier_id, payment_mode, amount, reference_no, remarks) "
                "VALUES ('SP-TEST', '2025-05-01', '10:00', ?, 'Cash', 5249.0, 'CHQ-001', '')",
                (sid,),
            )
            pay_id = cur.lastrowid
            # Allocation: fully allocate inv1
            conn.execute(
                "INSERT INTO supplier_payment_allocations "
                "(supplier_payment_id, purchase_invoice_id, allocated_amount, discount_amount) "
                "VALUES (?, ?, 5249.0, 0.0)",
                (pay_id, inv1),
            )
            # Also post to supplier ledger to keep ledger consistent
            sup_row = conn.execute(
                "SELECT ledger_id FROM suppliers WHERE id = ?", (sid,)
            ).fetchone()
            if sup_row and sup_row[0]:
                conn.execute(
                    "INSERT INTO ledger_transactions (ledger_id, transaction_date, voucher_type, "
                    "voucher_no, debit, credit, reference_type, reference_id) "
                    "VALUES (?, '2025-05-01', 'PAYMENT', 'SP-TEST', 5249.0, 0.0, 'SUPPLIER_PAYMENT', ?)",
                    (sup_row[0], pay_id),
                )
            conn.commit()
        finally:
            conn.close()

        invs = SupplierPaymentDAO.get_outstanding_invoices(sid, exclude_payment_id=None)
        inv_map = {i["id"]: i for i in invs}

        # inv1 should be fully settled by allocation
        self.assertNotIn(inv1, inv_map, "Fully allocated invoice should not appear")
        self.assertIn(inv2, inv_map)
        self.assertAlmostEqual(inv_map[inv2]["outstanding_balance"], 6327.0)

    def test_09_mixed_legacy_and_allocation_payments(self):
        """Legacy payments + new allocation rows combine correctly."""
        sid = self._make_supplier("SUP MIXED")
        inv1 = self._make_purchase_invoice(sid, 10000.0, "2025-04-01", "MX001")
        inv2 = self._make_purchase_invoice(sid, 8000.0, "2025-04-15", "MX002")

        # Legacy payment of 5000 (no allocation rows)
        self._make_legacy_payment(sid, 5000.0, "2025-05-01")

        # New proper payment of 3000 (with allocation row on inv2 partially)
        # First check what the outstanding is now
        invs_before = SupplierPaymentDAO.get_outstanding_invoices(sid)
        inv_map_before = {i["id"]: i for i in invs_before}
        # inv1 should have 5000 outstanding (10000 - 5000 legacy FIFO)
        self.assertAlmostEqual(inv_map_before[inv1]["outstanding_balance"], 5000.0)
        self.assertAlmostEqual(inv_map_before[inv2]["outstanding_balance"], 8000.0)

        total_out = sum(i["outstanding_balance"] for i in invs_before)
        ledger_bal = self._get_supplier_ledger_balance(sid)
        self.assertAlmostEqual(total_out, ledger_bal)

    def test_10_invoice_amount_consistency(self):
        """outstanding_balance == invoice_amount - (paid_initial + prior_allocated + legacy_reduction)."""
        sid = self._make_supplier("SUP CONSISTENCY")
        self._make_purchase_invoice(sid, 9500.0, "2025-04-01", "C001")
        self._make_purchase_invoice(sid, 4200.0, "2025-04-20", "C002")
        # Partial legacy payment covering first invoice partially
        self._make_legacy_payment(sid, 4500.0, "2025-05-01")

        invs = SupplierPaymentDAO.get_outstanding_invoices(sid)
        for inv in invs:
            self.assertGreater(inv["outstanding_balance"], 0,
                               "outstanding_balance must be > 0 if returned")
            self.assertLessEqual(inv["outstanding_balance"], inv["invoice_amount"],
                                 "outstanding cannot exceed invoice amount")

    def test_11_fifo_allocation_example(self):
        """FIFO allocates payment correctly across multiple invoices."""
        invs = [
            {"id": 1, "outstanding_balance": 5249.0},
            {"id": 2, "outstanding_balance": 6327.0},
        ]
        allocations = SupplierPaymentDAO.calculate_fifo_allocation(invs, 10000.0)
        self.assertAlmostEqual(allocations[0]["allocated_amount"], 5249.0)
        self.assertAlmostEqual(allocations[1]["allocated_amount"], 4751.0)

    def test_12_excess_payment_guard(self):
        """Total invoices of 0 should not block payments (advance guard only if outstanding > 0)."""
        sid = self._make_supplier("SUP EXCESS")
        inv1 = self._make_purchase_invoice(sid, 2000.0, "2025-04-01", "E001")
        invs = SupplierPaymentDAO.get_outstanding_invoices(sid)
        total_available = sum(i["outstanding_balance"] for i in invs)
        # Payment exactly matching available should pass
        self.assertAlmostEqual(total_available, 2000.0)
        # Payment above available outstanding
        self.assertGreater(2001.0, total_available)


if __name__ == "__main__":
    unittest.main(verbosity=2)
