"""Automated tests for Detailed Ledger Reports:
- Supplier Ledger
- Customer Ledger
- Itemwise Ledger
- LedgerReportDAO calculations & edge cases
- UI Screens & Menu wiring
"""

import os
import sys
import tempfile
import unittest
from datetime import date

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers
from database.ledger_dao import LedgerDAO
from database.supplier_dao import SupplierDAO
from database.customer_dao import CustomerDAO
from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO
from database.ledger_report_dao import LedgerReportDAO, LedgerReportError
from ui.menu_data import MENUS


class _BaseLedgerTest(unittest.TestCase):
    """Isolated throwaway SQLite database for detailed ledger tests."""

    @classmethod
    def setUpClass(cls):
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix="_test_detailed_ledgers.db")
        os.close(cls.db_fd)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except OSError:
                pass

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in [
                "ledger_transactions", "customer_receipts", "supplier_payments",
                "debit_note_items", "debit_notes", "credit_note_items", "credit_notes",
                "sales_invoice_items", "sales_invoices", "purchase_invoice_items", "purchase_invoices",
                "stock_batches", "items", "customers", "suppliers", "account_ledgers",
                "units", "companies",
            ]:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()

        # Seed master data
        self.unit_id = UnitDAO.insert("Tablets")
        self.company_id = CompanyDAO.insert("Cipla Ltd", "CIPLA")

        # Item 1: Pack of 10
        self.item_id = ItemDAO.insert(
            item_name="Paracetamol 500mg",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            reorder_stock_level=50,
        )

        # Supplier with linked ledger
        self.supplier_id = SupplierDAO.insert(
            supplier_name="Alpha Pharmaceuticals",
            city="Mumbai",
            contact_no="9876543210",
            opening_balance=1000.0,
        )

        # Customer with linked ledger
        self.customer_id = CustomerDAO.insert(
            customer_name="John Doe",
            city="Pune",
            contact_no="9123456789",
            opening_balance=500.0,
        )

        conn = get_connection()
        s_row = conn.execute("SELECT ledger_id FROM suppliers WHERE id = ?", (self.supplier_id,)).fetchone()
        self.supplier_ledger_id = s_row["ledger_id"] if s_row else None
        c_row = conn.execute("SELECT ledger_id FROM customers WHERE id = ?", (self.customer_id,)).fetchone()
        self.customer_ledger_id = c_row["ledger_id"] if c_row else None
        conn.close()

    def _create_purchase(self, voucher_no, voucher_date, supplier_id, total_amount, items):
        norm_items = []
        for it in items:
            d = dict(it)
            d.setdefault("free_qty", 0.0)
            d.setdefault("discount", 0.0)
            d.setdefault("gst_percent", 0.0)
            d.setdefault("gst_amount", 0.0)
            d.setdefault("purchase_rate", d.get("rate", 0.0))
            d.setdefault("net_rate", d.get("rate", 0.0))
            d.setdefault("pp", d.get("rate", 0.0))
            d.setdefault("pack_size", "10")
            d.setdefault("expiry", "12/28")
            norm_items.append(d)
        return PurchaseDAO.insert_invoice(
            voucher_no=voucher_no,
            voucher_date=voucher_date,
            voucher_time="10:00:00",
            purchase_type="Credit",
            supplier_id=supplier_id,
            invoice_no=f"INV-{voucher_no}",
            invoice_date=voucher_date,
            invoice_net_amount=total_amount,
            bill_discount=0.0,
            due_date="",
            total_amount=total_amount,
            gst_amount=0.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=0.0,
            net_amount=total_amount,
            remarks="",
            items=norm_items,
        )

    def _create_sale(self, bill_no, sale_date, customer_id, total_amount, items):
        norm_items = []
        for it in items:
            d = dict(it)
            d.setdefault("pack_size", "10")
            d.setdefault("location", "")
            d.setdefault("discount_amount", 0.0)
            norm_items.append(d)
        return SalesDAO.insert_invoice(
            bill_no=bill_no,
            sale_date=sale_date,
            sale_time="11:00:00",
            sale_type="Credit",
            customer_id=customer_id,
            patient_name="Test Patient",
            doctor_id=None,
            discount=0.0,
            paid_amount=0.0,
            total_amount=total_amount,
            round_off=0.0,
            net_amount=total_amount,
            remarks="",
            items=norm_items,
        )

    def _create_payment(self, voucher_no, payment_date, supplier_id, amount, mode="Cash"):
        return SupplierPaymentDAO.insert_payment({
            "voucher_no": voucher_no,
            "payment_date": payment_date,
            "payment_time": "12:00:00",
            "supplier_id": supplier_id,
            "payment_mode": mode,
            "amount": amount,
            "reference_no": "",
            "remarks": "",
        })

    def _create_receipt(self, voucher_no, receipt_date, customer_id, amount, mode="Cash"):
        return CustomerReceiptDAO.insert_receipt({
            "voucher_no": voucher_no,
            "receipt_date": receipt_date,
            "receipt_time": "12:00:00",
            "customer_id": customer_id,
            "receipt_mode": mode,
            "amount": amount,
            "reference_no": "",
            "remarks": "",
        })


# ======================================================================
# 1. Supplier Ledger Calculations & Edge Cases
# ======================================================================
class TestSupplierLedgerDAO(_BaseLedgerTest):

    def test_01_empty_period_returns_opening_balance(self):
        """Supplier with no transactions shows opening balance as closing balance."""
        report = LedgerReportDAO.get_supplier_ledger(
            supplier_id=self.supplier_id,
            from_date="2026-04-01",
            to_date="2026-04-30",
        )
        self.assertEqual(report["opening_balance"], 1000.0)
        self.assertEqual(report["opening_balance_type"], "CR")
        self.assertEqual(report["closing_balance"], 1000.0)
        self.assertEqual(report["closing_balance_type"], "CR")
        self.assertEqual(report["total_debit"], 0.0)
        self.assertEqual(report["total_credit"], 0.0)
        self.assertEqual(len(report["rows"]), 0)
        self.assertIsNone(report["warning"])

    def test_02_supplier_purchase_and_payment_in_period(self):
        """Purchase increases CR balance, payment reduces it (debit)."""
        # 1. Purchase invoice of 2,500 on 2026-04-10 (Credit purchase)
        self._create_purchase(
            voucher_no="PUR-001",
            voucher_date="2026-04-10",
            supplier_id=self.supplier_id,
            total_amount=2500.0,
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 25.0,
                "free_qty": 0.0,
                "batch_no": "B101",
                "expiry": "12/28",
                "rate": 100.0,
                "mrp": 120.0,
                "amount": 2500.0,
            }],
        )

        # 2. Supplier payment of 1,500 on 2026-04-15
        self._create_payment(
            voucher_no="SP-001",
            payment_date="2026-04-15",
            supplier_id=self.supplier_id,
            amount=1500.0,
        )

        # 3. Debit note (return) of 200 on 2026-04-20
        dn_hdr = {
            "voucher_no": "DN-001",
            "voucher_date": "2026-04-20",
            "supplier_id": self.supplier_id,
            "total_amount": 200.0,
            "ledger_amount": 200.0,
            "remarks": "Damaged pack",
        }
        # Find stock batch id for B101
        conn = get_connection()
        batch_row = conn.execute("SELECT id FROM stock_batches WHERE batch_no = 'B101'").fetchone()
        conn.close()
        dn_items = [{
            "item_id": self.item_id,
            "stock_batch_id": batch_row["id"],
            "batch_no": "B101",
            "expiry": "12/28",
            "pack_size": "10",
            "rate": 10.0,
            "mrp": 12.0,
            "return_qty": 20.0,
            "less_amount": 0.0,
            "amount": 200.0,
            "return_reason": "Damaged",
        }]
        DebitNoteDAO.insert_debit_note(dn_hdr, dn_items)

        report = LedgerReportDAO.get_supplier_ledger(
            supplier_id=self.supplier_id,
            from_date="2026-04-01",
            to_date="2026-04-30",
        )

        self.assertEqual(report["opening_balance"], 1000.0)
        self.assertEqual(report["opening_balance_type"], "CR")

        # Total debit = 1,500 (payment) + 200 (debit note) = 1,700
        # Total credit = 2,500 (purchase)
        self.assertEqual(report["total_debit"], 1700.0)
        self.assertEqual(report["total_credit"], 2500.0)

        # Closing balance: 1,000 CR + 2,500 CR - 1,700 DR = 1,800 CR
        self.assertEqual(report["closing_balance"], 1800.0)
        self.assertEqual(report["closing_balance_type"], "CR")

        self.assertEqual(len(report["rows"]), 3)

        # Row 1: Purchase
        r1 = report["rows"][0]
        self.assertEqual(r1["transaction_date"], "2026-04-10")
        self.assertEqual(r1["credit"], 2500.0)
        self.assertEqual(r1["debit"], 0.0)
        self.assertEqual(r1["running_balance"], 3500.0)
        self.assertEqual(r1["running_balance_type"], "CR")

        # Row 2: Payment
        r2 = report["rows"][1]
        self.assertEqual(r2["transaction_date"], "2026-04-15")
        self.assertEqual(r2["debit"], 1500.0)
        self.assertEqual(r2["credit"], 0.0)
        self.assertEqual(r2["running_balance"], 2000.0)
        self.assertEqual(r2["running_balance_type"], "CR")

        # Row 3: Debit Note
        r3 = report["rows"][2]
        self.assertEqual(r3["transaction_date"], "2026-04-20")
        self.assertEqual(r3["debit"], 200.0)
        self.assertEqual(r3["credit"], 0.0)
        self.assertEqual(r3["running_balance"], 1800.0)
        self.assertEqual(r3["running_balance_type"], "CR")

    def test_03_prior_transactions_flow_into_opening_balance(self):
        """Transactions before from_date accurately become part of opening_balance."""
        # Insert a purchase on 2026-03-15 of 500
        self._create_purchase(
            voucher_no="PUR-002",
            voucher_date="2026-03-15",
            supplier_id=self.supplier_id,
            total_amount=500.0,
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 5.0,
                "free_qty": 0.0,
                "batch_no": "B099",
                "expiry": "12/28",
                "rate": 100.0,
                "mrp": 120.0,
                "amount": 500.0,
            }],
        )

        # Report for April: opening balance must include the 500 purchase (1000 + 500 = 1500 CR)
        report = LedgerReportDAO.get_supplier_ledger(
            supplier_id=self.supplier_id,
            from_date="2026-04-01",
            to_date="2026-04-30",
        )
        self.assertEqual(report["opening_balance"], 1500.0)
        self.assertEqual(report["opening_balance_type"], "CR")
        self.assertEqual(len(report["rows"]), 0)

    def test_04_supplier_overpayment_turns_to_debit(self):
        """Overpaying supplier results in DR balance (advance paid)."""
        # Supplier OB is 1000 CR. Pay 3,000 -> balance becomes 2000 DR
        self._create_payment(
            voucher_no="SP-002",
            payment_date="2026-05-01",
            supplier_id=self.supplier_id,
            amount=3000.0,
        )

        report = LedgerReportDAO.get_supplier_ledger(
            supplier_id=self.supplier_id,
            from_date="2026-05-01",
            to_date="2026-05-31",
        )
        self.assertEqual(report["opening_balance"], 1000.0)
        self.assertEqual(report["opening_balance_type"], "CR")
        self.assertEqual(report["closing_balance"], 2000.0)
        self.assertEqual(report["closing_balance_type"], "DR")
    def test_05_supplier_without_ledger(self):
        """Supplier without linked ledger returns graceful warning and empty report."""
        unlinked_id = SupplierDAO.insert(supplier_name="Unlinked Supplier")
        conn = get_connection()
        conn.cursor().execute("UPDATE suppliers SET ledger_id = NULL WHERE id = ?", (unlinked_id,))
        conn.commit()
        conn.close()
        report = LedgerReportDAO.get_supplier_ledger(
            supplier_id=unlinked_id,
            from_date="2026-04-01",
            to_date="2026-04-30",
        )
        self.assertEqual(report["opening_balance"], 0.0)
        self.assertEqual(report["closing_balance"], 0.0)
        self.assertIn("no linked Account Ledger", report["warning"])


# ======================================================================
# 2. Customer Ledger Calculations & Edge Cases
# ======================================================================
class TestCustomerLedgerDAO(_BaseLedgerTest):

    def test_06_empty_customer_period_returns_opening_balance(self):
        """Customer with no transactions shows opening balance as closing balance."""
        report = LedgerReportDAO.get_customer_ledger(
            customer_id=self.customer_id,
            from_date="2026-04-01",
            to_date="2026-04-30",
        )
        self.assertEqual(report["opening_balance"], 500.0)
        self.assertEqual(report["opening_balance_type"], "DR")
        self.assertEqual(report["closing_balance"], 500.0)
        self.assertEqual(report["closing_balance_type"], "DR")
        self.assertEqual(report["total_debit"], 0.0)
        self.assertEqual(report["total_credit"], 0.0)
        self.assertEqual(len(report["rows"]), 0)

    def test_07_customer_sale_and_receipt_in_period(self):
        """Sale increases DR balance, receipt reduces it (credit)."""
        # First put some stock in for the item
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
            VALUES (?, 'B201', '12/28', '10', 10.0, 100.0)
            """,
            (self.item_id,),
        )
        conn.commit()
        batch_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        # 1. Counter sale on credit for 800 on 2026-04-05
        self._create_sale(
            bill_no="BILL-001",
            sale_date="2026-04-05",
            customer_id=self.customer_id,
            total_amount=800.0,
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": batch_id,
                "batch_no": "B201",
                "expiry": "12/28",
                "pack_size": "10",
                "mrp": 10.0,
                "sale_qty": 80.0,
                "discount_amount": 0.0,
                "amount": 800.0,
            }],
        )

        # 2. Customer receipt of 600 on 2026-04-12
        self._create_receipt(
            voucher_no="CR-001",
            receipt_date="2026-04-12",
            customer_id=self.customer_id,
            amount=600.0,
        )

        # 3. Credit note (sales return) of 100 on 2026-04-18
        cn_hdr = {
            "voucher_no": "CN-001",
            "voucher_date": "2026-04-18",
            "customer_id": self.customer_id,
            "total_amount": 100.0,
            "ledger_amount": 100.0,
            "remarks": "Returned goods",
        }
        cn_items = [{
            "item_id": self.item_id,
            "stock_batch_id": batch_id,
            "batch_no": "B201",
            "expiry": "12/28",
            "pack_size": "10",
            "rate": 10.0,
            "mrp": 10.0,
            "return_qty": 10.0,
            "less_amount": 0.0,
            "amount": 100.0,
        }]
        CreditNoteDAO.insert_credit_note(cn_hdr, cn_items)

        report = LedgerReportDAO.get_customer_ledger(
            customer_id=self.customer_id,
            from_date="2026-04-01",
            to_date="2026-04-30",
        )

        self.assertEqual(report["opening_balance"], 500.0)
        self.assertEqual(report["opening_balance_type"], "DR")

        # Total debit = 800 (sale)
        # Total credit = 600 (receipt) + 100 (credit note) = 700
        self.assertEqual(report["total_debit"], 800.0)
        self.assertEqual(report["total_credit"], 700.0)

        # Closing balance: 500 DR + 800 DR - 700 CR = 600 DR
        self.assertEqual(report["closing_balance"], 600.0)
        self.assertEqual(report["closing_balance_type"], "DR")

        self.assertEqual(len(report["rows"]), 3)

        # Check running balances
        self.assertEqual(report["rows"][0]["running_balance"], 1300.0)
        self.assertEqual(report["rows"][0]["running_balance_type"], "DR")
        self.assertEqual(report["rows"][1]["running_balance"], 700.0)
        self.assertEqual(report["rows"][1]["running_balance_type"], "DR")
        self.assertEqual(report["rows"][2]["running_balance"], 600.0)
        self.assertEqual(report["rows"][2]["running_balance_type"], "DR")

    def test_08_customer_overpayment_turns_to_credit(self):
        """Overpaying customer results in CR balance (advance received)."""
        # Customer OB is 500 DR. Receipt of 1,200 -> balance becomes 700 CR
        self._create_receipt(
            voucher_no="CR-002",
            receipt_date="2026-05-02",
            customer_id=self.customer_id,
            amount=1200.0,
            mode="Bank",
        )

        report = LedgerReportDAO.get_customer_ledger(
            customer_id=self.customer_id,
            from_date="2026-05-01",
            to_date="2026-05-31",
        )
        self.assertEqual(report["opening_balance"], 500.0)
        self.assertEqual(report["opening_balance_type"], "DR")
        self.assertEqual(report["closing_balance"], 700.0)
        self.assertEqual(report["closing_balance_type"], "CR")


# ======================================================================
# 3. Itemwise Ledger Calculations & Stock Conventions
# ======================================================================
class TestItemwiseLedgerDAO(_BaseLedgerTest):

    def test_09_item_ledger_purchases_and_sales(self):
        """Inward increases closing stock, outward decreases it."""
        # 1. Purchase on 2026-04-02: 10 packs of 10 pay + 2 packs free = 12 * 10 = 120 units
        # 1. Purchase on 2026-04-02: 10 packs of 10 pay + 2 packs free = 12 * 10 = 120 units
        self._create_purchase(
            voucher_no="PUR-101",
            voucher_date="2026-04-02",
            supplier_id=self.supplier_id,
            total_amount=1200.0,
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 10.0,
                "free_qty": 2.0,
                "batch_no": "BATCH-A",
                "expiry": "06/27",
                "rate": 100.0,
                "mrp": 120.0,
                "amount": 1200.0,
            }],
        )

        # Find batch id
        conn = get_connection()
        b_row = conn.execute("SELECT id FROM stock_batches WHERE batch_no = 'BATCH-A'").fetchone()
        batch_id = b_row["id"]
        conn.close()

        # 2. Sale on 2026-04-10: 25 loose units
        self._create_sale(
            bill_no="BILL-101",
            sale_date="2026-04-10",
            customer_id=self.customer_id,
            total_amount=250.0,
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": batch_id,
                "batch_no": "BATCH-A",
                "expiry": "06/27",
                "pack_size": "10",
                "mrp": 12.0,
                "sale_qty": 25.0,
                "amount": 250.0,
            }],
        )

        # 3. Sales return (Credit Note) on 2026-04-15: 5 loose units inward
        cn_hdr = {
            "voucher_no": "CN-101",
            "voucher_date": "2026-04-15",
            "customer_id": self.customer_id,
            "total_amount": 50.0,
            "ledger_amount": 50.0,
        }
        cn_items = [{
            "item_id": self.item_id,
            "stock_batch_id": batch_id,
            "batch_no": "BATCH-A",
            "expiry": "06/27",
            "pack_size": "10",
            "rate": 10.0,
            "mrp": 12.0,
            "return_qty": 5.0,
            "amount": 50.0,
        }]
        CreditNoteDAO.insert_credit_note(cn_hdr, cn_items)

        # 4. Purchase return (Debit Note) on 2026-04-20: 10 loose units outward
        dn_hdr = {
            "voucher_no": "DN-101",
            "voucher_date": "2026-04-20",
            "supplier_id": self.supplier_id,
            "total_amount": 100.0,
            "ledger_amount": 100.0,
        }
        dn_items = [{
            "item_id": self.item_id,
            "stock_batch_id": batch_id,
            "batch_no": "BATCH-A",
            "expiry": "06/27",
            "pack_size": "10",
            "rate": 10.0,
            "mrp": 12.0,
            "return_qty": 10.0,
            "amount": 100.0,
        }]
        DebitNoteDAO.insert_debit_note(dn_hdr, dn_items)

        report = LedgerReportDAO.get_item_ledger(
            item_id=self.item_id,
            from_date="2026-04-01",
            to_date="2026-04-30",
        )

        self.assertEqual(report["opening_stock"], 0.0)
        self.assertEqual(report["total_inward"], 125.0)  # 120 purchase + 5 return
        self.assertEqual(report["total_outward"], 35.0)   # 25 sale + 10 debit note
        self.assertEqual(report["closing_stock"], 90.0)
        self.assertEqual(report["current_batch_stock"], 90.0)

        self.assertEqual(len(report["rows"]), 4)

        # Check chronological order and running stock
        # Row 1: Purchase (120 in -> 120)
        self.assertEqual(report["rows"][0]["voucher_type"], "Purchase")
        self.assertEqual(report["rows"][0]["inward_qty"], 120.0)
        self.assertEqual(report["rows"][0]["closing_stock"], 120.0)

        # Row 2: Sale (25 out -> 95)
        self.assertEqual(report["rows"][1]["voucher_type"], "Sale")
        self.assertEqual(report["rows"][1]["outward_qty"], 25.0)
        self.assertEqual(report["rows"][1]["closing_stock"], 95.0)

        # Row 3: Credit Note (5 in -> 100)
        self.assertEqual(report["rows"][2]["voucher_type"], "Credit Note")
        self.assertEqual(report["rows"][2]["inward_qty"], 5.0)
        self.assertEqual(report["rows"][2]["closing_stock"], 100.0)

        # Row 4: Debit Note (10 out -> 90)
        self.assertEqual(report["rows"][3]["voucher_type"], "Debit Note")
        self.assertEqual(report["rows"][3]["outward_qty"], 10.0)
        self.assertEqual(report["rows"][3]["closing_stock"], 90.0)

    def test_10_prior_stock_flows_into_opening_stock(self):
        """Movements before from_date accumulate into opening_stock."""
        # Purchase on 2026-03-20: 5 packs of 10 = 50 units
        self._create_purchase(
            voucher_no="PUR-090",
            voucher_date="2026-03-20",
            supplier_id=self.supplier_id,
            total_amount=500.0,
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 5.0,
                "free_qty": 0.0,
                "batch_no": "B090",
                "expiry": "12/28",
                "rate": 100.0,
                "mrp": 120.0,
                "amount": 500.0,
            }],
        )

        # Query for April 2026: opening stock should be 50.0
        report = LedgerReportDAO.get_item_ledger(
            item_id=self.item_id,
            from_date="2026-04-01",
            to_date="2026-04-30",
        )
        self.assertEqual(report["opening_stock"], 50.0)
        self.assertEqual(report["total_inward"], 0.0)
        self.assertEqual(report["total_outward"], 0.0)
        self.assertEqual(report["closing_stock"], 50.0)
        self.assertEqual(len(report["rows"]), 0)


# ======================================================================
# 4. UI Screens & Menu Wiring
# ======================================================================
class TestLedgerScreensAndWiring(_BaseLedgerTest):

    def test_11_menu_data_has_all_three_ledger_reports(self):
        """Reports menu must contain Supplier Ledger, Customer Ledger, Itemwise Ledger."""
        reports = MENUS["Reports"]
        self.assertIn("Supplier Ledger", reports)
        self.assertIn("Customer Ledger", reports)
        self.assertIn("Itemwise Ledger", reports)
        self.assertEqual(reports.count("Supplier Ledger"), 1)
        self.assertEqual(reports.count("Customer Ledger"), 1)
        self.assertEqual(reports.count("Itemwise Ledger"), 1)

    def test_12_screens_package_exports_pages(self):
        """screens package must export the 3 ledger page classes."""
        import screens
        self.assertTrue(hasattr(screens, "SupplierLedgerPage"))
        self.assertTrue(hasattr(screens, "CustomerLedgerPage"))
        self.assertTrue(hasattr(screens, "ItemwiseLedgerPage"))

    def test_13_supplier_ledger_page_instantiation_and_render(self):
        """SupplierLedgerPage can be instantiated, populated, and rendered."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import screens

        page = screens.SupplierLedgerPage()
        self.assertIsNotNone(page)

        # Test selecting a supplier and triggering generate
        page._supplier_selector.set_selected_id(self.supplier_id)
        page._on_generate()

        # Table should have at least Opening and Closing rows
        self.assertGreaterEqual(page._table.rowCount(), 2)
        # Check Opening balance cell
        ob_cell = page._table.item(0, 1)
        self.assertIn("OPENING BALANCE", ob_cell.text())

    def test_14_customer_ledger_page_instantiation_and_render(self):
        """CustomerLedgerPage can be instantiated, populated, and rendered."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import screens

        page = screens.CustomerLedgerPage()
        self.assertIsNotNone(page)

        page._customer_selector.set_selected_id(self.customer_id)
        page._on_generate()

        self.assertGreaterEqual(page._table.rowCount(), 2)
        ob_cell = page._table.item(0, 1)
        self.assertIn("OPENING BALANCE", ob_cell.text())

    def test_15_itemwise_ledger_page_instantiation_and_render(self):
        """ItemwiseLedgerPage can be instantiated, populated, and rendered."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import screens

        page = screens.ItemwiseLedgerPage()
        self.assertIsNotNone(page)

        page._item_selector.set_selected_id(self.item_id)
        page._on_generate()

        self.assertGreaterEqual(page._table.rowCount(), 2)
        os_cell = page._table.item(0, 1)
        self.assertIn("OPENING STOCK", os_cell.text())

    def test_16_financial_year_switch_updates_pages(self):
        """set_history_financial_year updates date range on all 3 pages."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import screens

        year = {"name": "2024-2025", "start_date": "2024-04-01", "end_date": "2025-03-31"}

        sp = screens.SupplierLedgerPage()
        sp.set_history_financial_year(year)
        self.assertEqual(sp._from_date.date().toString("yyyy-MM-dd"), "2024-04-01")
        self.assertEqual(sp._to_date.date().toString("yyyy-MM-dd"), "2025-03-31")

        cp = screens.CustomerLedgerPage()
        cp.set_history_financial_year(year)
        self.assertEqual(cp._from_date.date().toString("yyyy-MM-dd"), "2024-04-01")
        self.assertEqual(cp._to_date.date().toString("yyyy-MM-dd"), "2025-03-31")

        ip = screens.ItemwiseLedgerPage()
        ip.set_history_financial_year(year)
        self.assertEqual(ip._from_date.date().toString("yyyy-MM-dd"), "2024-04-01")
        self.assertEqual(ip._to_date.date().toString("yyyy-MM-dd"), "2025-03-31")

    def test_17_theme_refresh_without_error(self):
        """Calling refresh_theme with Day and Night modes executes cleanly."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import screens
        from ui.theme import theme_manager, palette

        sp = screens.SupplierLedgerPage()
        cp = screens.CustomerLedgerPage()
        ip = screens.ItemwiseLedgerPage()

        # Day mode
        theme_manager.set_mode("light")
        p_light = palette()
        sp.refresh_theme(p_light)
        cp.refresh_theme(p_light)
        ip.refresh_theme(p_light)

        # Night mode
        theme_manager.set_mode("night")
        p_dark = palette()
        sp.refresh_theme(p_dark)
        cp.refresh_theme(p_dark)
        ip.refresh_theme(p_dark)

    def test_18_zero_balance_shows_proper_normal_balance_type(self):
        """Suppliers with zero balance show CR, and customers with zero balance show DR."""
        zero_sup_id = SupplierDAO.insert("Zero Balance Supplier", opening_balance=0.0)
        zero_cust_id = CustomerDAO.insert("Zero Balance Customer", opening_balance=0.0)

        s_rep = LedgerReportDAO.get_supplier_ledger(zero_sup_id, "2026-04-01", "2026-04-30")
        self.assertEqual(s_rep["opening_balance"], 0.0)
        self.assertEqual(s_rep["opening_balance_type"], "CR")
        self.assertEqual(s_rep["closing_balance"], 0.0)
        self.assertEqual(s_rep["closing_balance_type"], "CR")

        c_rep = LedgerReportDAO.get_customer_ledger(zero_cust_id, "2026-04-01", "2026-04-30")
        self.assertEqual(c_rep["opening_balance"], 0.0)
        self.assertEqual(c_rep["opening_balance_type"], "DR")
        self.assertEqual(c_rep["closing_balance"], 0.0)
        self.assertEqual(c_rep["closing_balance_type"], "DR")

    def test_19_missing_opening_inventory_flags_warning(self):
        """When outward sales occur with no inward purchases, itemwise ledger flags notice."""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty) "
            "VALUES (?, 'DEFICIT-BATCH', '12/27', '10', 30.0, 10.0)",
            (self.item_id,),
        )
        batch_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Create a sale without any prior purchase
        self._create_sale(
            bill_no="SALE-DEFICIT-1",
            sale_date="2026-04-05",
            customer_id=self.customer_id,
            total_amount=120.0,
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": batch_id,
                "batch_no": "DEFICIT-BATCH",
                "expiry": "12/27",
                "sale_qty": 5.0,
                "rate": 24.0,
                "mrp": 30.0,
                "amount": 120.0,
                "discount_percent": 0.0,
            }],
        )

        rep = LedgerReportDAO.get_item_ledger(self.item_id, "2026-04-01", "2026-04-30")
        self.assertEqual(rep["closing_stock"], -5.0)
        self.assertIsNotNone(rep["warning"])
        self.assertIn("Historical initial stock was not recorded", rep["warning"])

    def test_20_unlinked_parties_display_explicit_warning(self):
        """Party with no linked ledger reports explicit warning instead of fabricated zero."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO suppliers (supplier_name) VALUES ('UNLINKED PHARMA')")
            orphan_sup_id = cur.lastrowid
            cur.execute("INSERT INTO customers (customer_name) VALUES ('UNLINKED PATIENT')")
            orphan_cust_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        s_rep = LedgerReportDAO.get_supplier_ledger(orphan_sup_id, "2026-04-01", "2026-04-30")
        self.assertIsNotNone(s_rep["warning"])
        self.assertIn("has no linked Account Ledger", s_rep["warning"])

        c_rep = LedgerReportDAO.get_customer_ledger(orphan_cust_id, "2026-04-01", "2026-04-30")
        self.assertIsNotNone(c_rep["warning"])
        self.assertIn("has no linked Account Ledger", c_rep["warning"])

    def test_21_invalid_dates_raise_ledger_report_error(self):
        """Passing from_date > to_date or non-ISO dates raises LedgerReportError."""
        with self.assertRaises(LedgerReportError):
            LedgerReportDAO.get_supplier_ledger(self.supplier_id, "2026-04-30", "2026-04-01")

        with self.assertRaises(LedgerReportError):
            LedgerReportDAO.get_customer_ledger(self.customer_id, "invalid-date", "2026-04-30")

        with self.assertRaises(LedgerReportError):
            LedgerReportDAO.get_item_ledger(self.item_id, "2026-04-30", "2026-04-01")


if __name__ == "__main__":
    unittest.main()

