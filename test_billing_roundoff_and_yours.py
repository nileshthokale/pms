"""Comprehensive tests for billing round-off and "Yours" profit calculations.

Verifies:
1. Issue 1: Final bill round-off using Decimal ROUND_HALF_UP:
   - ₹100.16 -> round-off -₹0.16 -> payable ₹100
   - ₹100.49 -> round-off -₹0.49 -> payable ₹100
   - ₹100.50 -> round-off +₹0.50 -> payable ₹101 (exact tie break)
   - ₹137.16 -> round-off -₹0.16 -> payable ₹137
   - ₹11.25  -> round-off -₹0.25 -> payable ₹11 (was previously showing ₹0.00 round-off)
   - Exact tie breaking for odd and even integers: 1.50 -> 2, 2.50 -> 3 (not bankers rounding)
   - Line items preserve their unrounded precision.

2. Issue 2: Legacy "Yours" (Gross Profit) and "Customer Saving":
   - ALGESIA CR CAPSULE (MRP 137.16, Pack 10, Batch Net Rate 99.75, Qty 10):
     Yours = 137.16 - 99.75 = 37.41 (Exact match to Pharma-WINNER screenshot!)
     Customer Saving = 0.00
     Final rounded bill = 137.00 (Round-off = -0.16)
   - Partial packs / loose unit calculations.
   - Discount handling: bill discount reduces pharmacy profit and increases customer saving.
   - Fallback to purchase_rate when net_rate is absent or 0.
   - Missing cost handling: safe handling without inventing fake costs.
   - Multi-item bills and combined open-bill status bar reporting.

3. Accounting & Transaction consistency:
   - Database storage: sales_invoices has total_amount, discount, round_off, net_amount.
   - Ledger posting: balanced debit and credit equal to net_amount.
   - Printed document: displays Round Off and Net Amount consistently.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from decimal import Decimal, ROUND_HALF_UP

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Use isolated temporary database for safety
_TMP_DIR = tempfile.mkdtemp(prefix="pms_billing_test_")
_TMP_DB = os.path.join(_TMP_DIR, "billing_test.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from database.connection import get_connection, init_database
from database.sales_dao import SalesDAO
from database.customer_dao import CustomerDAO
from database.account_roles import ensure_system_ledgers
from database import accounting_posting as posting_engine
from database.document_printing import generate_counter_sale_bill, preview_document, _document_lines, _sales_data

try:
    from PySide6.QtWidgets import QApplication
    from screens.counter_sale import (
        CounterSalePage,
        SalesBillReviewDialog,
        _BillItemRow,
        _compute_bill_round_off,
        _compute_line_profit,
        _compute_bill_savings_and_profit,
        _SalePanel,
    )
    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

_APP = None


def setUpModule():
    global _APP
    init_database()
    ensure_system_ledgers()
    if HAS_PYSIDE6:
        _APP = QApplication.instance() or QApplication([])


class TestBillRoundOffCalculations(unittest.TestCase):
    """Test Issue 1: Nearest whole rupee round-off with ROUND_HALF_UP."""

    def test_legacy_examples_from_user(self):
        # - ₹100.16 → round-off −₹0.16 → payable ₹100
        ro, pay = _compute_bill_round_off(100.16)
        self.assertAlmostEqual(ro, -0.16, places=2)
        self.assertEqual(pay, 100.0)
        self.assertAlmostEqual(100.16 + ro, pay, places=2)

        # - ₹100.49 → round-off −₹0.49 → payable ₹100
        ro, pay = _compute_bill_round_off(100.49)
        self.assertAlmostEqual(ro, -0.49, places=2)
        self.assertEqual(pay, 100.0)
        self.assertAlmostEqual(100.49 + ro, pay, places=2)

        # - ₹100.50 → round-off +₹0.50 → payable ₹101
        ro, pay = _compute_bill_round_off(100.50)
        self.assertAlmostEqual(ro, 0.50, places=2)
        self.assertEqual(pay, 101.0)
        self.assertAlmostEqual(100.50 + ro, pay, places=2)

        # - ₹137.16 → round-off −₹0.16 → payable ₹137
        ro, pay = _compute_bill_round_off(137.16)
        self.assertAlmostEqual(ro, -0.16, places=2)
        self.assertEqual(pay, 137.0)
        self.assertAlmostEqual(137.16 + ro, pay, places=2)

    def test_problem_case_11_25_now_rounds_to_11(self):
        # Previously showed bill amount 11.25 with round-off 0.00
        # Expected: payable 11, round-off -0.25
        ro, pay = _compute_bill_round_off(11.25)
        self.assertAlmostEqual(ro, -0.25, places=2)
        self.assertEqual(pay, 11.0)
        self.assertAlmostEqual(11.25 + ro, pay, places=2)

    def test_exact_half_up_tie_breaking(self):
        # Crucial: standard Python round() uses banker's rounding (even round):
        # round(2.5) -> 2, round(3.5) -> 4.
        # ROUND_HALF_UP must ALWAYS round .50 upwards to next integer!
        ro1, p1 = _compute_bill_round_off(0.50)
        self.assertEqual(p1, 1.0)
        self.assertAlmostEqual(ro1, 0.50, places=2)

        ro2, p2 = _compute_bill_round_off(1.50)
        self.assertEqual(p2, 2.0)
        self.assertAlmostEqual(ro2, 0.50, places=2)

        ro3, p3 = _compute_bill_round_off(2.50)
        self.assertEqual(p3, 3.0)  # NOT 2.0
        self.assertAlmostEqual(ro3, 0.50, places=2)

        ro4, p4 = _compute_bill_round_off(3.50)
        self.assertEqual(p4, 4.0)
        self.assertAlmostEqual(ro4, 0.50, places=2)

    def test_zero_amount(self):
        ro, pay = _compute_bill_round_off(0.0)
        self.assertEqual(ro, 0.0)
        self.assertEqual(pay, 0.0)


class TestYoursProfitCalculations(unittest.TestCase):
    """Test Issue 2: Legacy 'Yours' (Gross Margin / Profit) and 'Customer Saving'."""

    def test_algesia_cr_exact_screenshot_match(self):
        """Item: ALGESIA CR CAPSULE
        Pack Size: 10
        MRP: 137.16
        Qty: 10
        Net Purchase Rate: 99.75
        Line Amount: 137.16
        Yours must equal 37.41 exactly!
        Customer Saving must equal 0.00!
        Final rounded payable must equal 137.00 with round-off -0.16!
        """
        row = _BillItemRow(
            item_id=1,
            item_name="ALGESIA CR CAPSULE",
            stock_batch_id=101,
            pack_size="10",
            location="A1",
            batch_no="18254384B",
            expiry="2027-10-31",
            mrp=137.16,
            sale_qty=10.0,
            discount_amount=0.0,
            amount=137.16,
            net_rate=99.75,
            purchase_rate=104.50,
        )
        saving, yours = _compute_line_profit(row)
        self.assertAlmostEqual(saving, 0.0, places=2)
        self.assertAlmostEqual(yours, 37.41, places=2)

        tot_saving, tot_yours = _compute_bill_savings_and_profit([row], bill_discount=0.0)
        self.assertAlmostEqual(tot_saving, 0.0, places=2)
        self.assertAlmostEqual(tot_yours, 37.41, places=2)

        ro, payable = _compute_bill_round_off(row.amount)
        self.assertAlmostEqual(ro, -0.16, places=2)
        self.assertEqual(payable, 137.0)

    def test_partial_pack_loose_units(self):
        """Selling 5 capsules from a pack of 10.
        MRP: 100.0 (pack of 10) -> unit MRP = 10.0
        Cost: 60.0 (net rate for pack of 10) -> unit cost = 6.0
        Qty: 5
        Line Amount: 50.0
        Line Cost: 5 * 6.0 = 30.0
        Yours Profit: 50.0 - 30.0 = 20.0
        Customer Saving: 0.0
        """
        row = _BillItemRow(
            item_id=2,
            item_name="TEST CAPSULE",
            stock_batch_id=102,
            pack_size="10",
            location="B1",
            batch_no="BATCH55",
            expiry="2028-01-31",
            mrp=100.0,
            sale_qty=5.0,
            discount_amount=0.0,
            amount=50.0,
            net_rate=60.0,
            purchase_rate=65.0,
        )
        saving, yours = _compute_line_profit(row)
        self.assertAlmostEqual(saving, 0.0, places=2)
        self.assertAlmostEqual(yours, 20.0, places=2)

    def test_bill_discount_effect(self):
        """A bill discount of ₹10 given on ₹200 total sale.
        Line gross profit = 50.0
        Bill discount = 10.0
        Net Yours Profit = 50.0 - 10.0 = 40.0
        Customer Saving = 10.0
        """
        row = _BillItemRow(
            item_id=3,
            item_name="SYRUP BOTTLE",
            stock_batch_id=103,
            pack_size="1",
            location="",
            batch_no="SYR01",
            expiry="2027-05-31",
            mrp=200.0,
            sale_qty=1.0,
            discount_amount=0.0,
            amount=200.0,
            net_rate=150.0,
            purchase_rate=160.0,
        )
        tot_saving, tot_yours = _compute_bill_savings_and_profit([row], bill_discount=10.0)
        self.assertAlmostEqual(tot_saving, 10.0, places=2)
        self.assertAlmostEqual(tot_yours, 40.0, places=2)

        # Final payable
        unrounded = 200.0 - 10.0  # 190.00
        ro, payable = _compute_bill_round_off(unrounded)
        self.assertEqual(ro, 0.0)
        self.assertEqual(payable, 190.0)

    def test_fallback_to_purchase_rate_when_net_rate_zero(self):
        """When net_rate is 0.0, use purchase_rate as cost."""
        row = _BillItemRow(
            item_id=4,
            item_name="CREAM",
            stock_batch_id=104,
            pack_size="1",
            location="",
            batch_no="CRM1",
            expiry="2027-01-31",
            mrp=100.0,
            sale_qty=1.0,
            discount_amount=0.0,
            amount=100.0,
            net_rate=0.0,
            purchase_rate=75.0,
        )
        saving, yours = _compute_line_profit(row)
        self.assertAlmostEqual(yours, 25.0, places=2)

    def test_missing_cost_gracefully_handled(self):
        """When neither net_rate nor purchase_rate is known (0.0):
        Cost is treated as 0.0, profit = line amount, no crash, no invented numbers.
        """
        row = _BillItemRow(
            item_id=5,
            item_name="UNKNOWN ITEM",
            stock_batch_id=0,
            pack_size="1",
            location="",
            batch_no="UNK",
            expiry="2027-01-31",
            mrp=80.0,
            sale_qty=1.0,
            discount_amount=0.0,
            amount=80.0,
            net_rate=0.0,
            purchase_rate=0.0,
        )
        saving, yours = _compute_line_profit(row)
        self.assertEqual(yours, 80.0)


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestBillingSaveAndAccountingIntegration(unittest.TestCase):
    """Test full integration: Save Sale -> Database -> Accounting Ledger -> Printing."""

    def setUp(self):
        conn = get_connection()
        try:
            # Clear tables for isolated testing
            for tbl in ["ledger_transactions", "sales_invoice_items", "sales_invoices", "stock_batches", "items"]:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()

            # Insert an item and a batch matching ALGESIA CR
            conn.execute(
                "INSERT INTO items (id, item_name, pack_size, mrp, rate) VALUES (1, 'ALGESIA CR CAPSULE', '10', 137.16, 137.16)"
            )
            conn.execute(
                """
                INSERT INTO stock_batches (
                    id, item_id, batch_no, expiry, pack_size, mrp,
                    purchase_rate, net_rate, stock_qty
                ) VALUES (7188, 1, '18254384B', '2027-10-31', '10', 137.16, 104.50, 99.75, 100.0)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def test_save_sale_stores_exact_round_off_and_payable(self):
        """Saving a sale with total 137.16 stores round_off -0.16 and net_amount 137.0."""
        customer_id = CustomerDAO.get_or_create_walkin()
        items = [{
            "item_id": 1,
            "stock_batch_id": 7188,
            "pack_size": "10",
            "location": "A1",
            "batch_no": "18254384B",
            "expiry": "2027-10-31",
            "mrp": 137.16,
            "sale_qty": 10.0,
            "discount_amount": 0.0,
            "amount": 137.16,
        }]

        unrounded = 137.16
        ro, net = _compute_bill_round_off(unrounded)

        inv_id = SalesDAO.insert_invoice(
            bill_no="TEST-001",
            sale_date="2026-10-22",
            sale_time="10:30",
            sale_type="Cash",
            customer_id=customer_id,
            patient_name="WALKIN",
            doctor_id=None,
            discount=0.0,
            paid_amount=net,
            total_amount=unrounded,
            round_off=ro,
            net_amount=net,
            remarks="Test billing round-off",
            items=items,
        )

        # Verify database record
        saved = SalesDAO.get_by_id(inv_id)
        self.assertEqual(saved["total_amount"], 137.16)
        self.assertEqual(saved["round_off"], -0.16)
        self.assertEqual(saved["net_amount"], 137.0)
        self.assertEqual(saved["paid_amount"], 137.0)

        # Verify line items preserved exact amount
        saved_items = SalesDAO.get_invoice_items(inv_id)
        self.assertEqual(len(saved_items), 1)
        self.assertEqual(saved_items[0]["amount"], 137.16)
        self.assertEqual(saved_items[0]["net_rate"], 99.75)
        self.assertEqual(saved_items[0]["purchase_rate"], 104.50)

        # Verify accounting posting
        conn = get_connection()
        try:
            lines = conn.execute(
                """
                SELECT lt.debit, lt.credit, al.ledger_name
                FROM ledger_transactions lt
                JOIN account_ledgers al ON al.id = lt.ledger_id
                WHERE lt.reference_type = 'COUNTER_SALE' AND lt.reference_id = ?
                """,
                (inv_id,),
            ).fetchall()
            self.assertEqual(len(lines), 2)
            tot_debit = sum(r[0] for r in lines)
            tot_credit = sum(r[1] for r in lines)
            self.assertEqual(tot_debit, 137.0)
            self.assertEqual(tot_credit, 137.0)
            self.assertEqual(tot_debit, tot_credit)  # Perfectly balanced
        finally:
            conn.close()

        # Verify document text printing
        lines = _document_lines("Sales Bill", saved, saved_items)
        text = "\n".join(lines)
        self.assertIn("Round Off: -0.16", text)
        self.assertIn("Net Amount: 137.00", text)
        self.assertIn("Total Amount: 137.16", text)

    def test_ui_sale_panel_recalc_and_status_bar(self):
        """Test _SalePanel recalculates round-off, customer saving, and yours live."""
        panel = _SalePanel()
        row = _BillItemRow(
            item_id=1,
            item_name="ALGESIA CR CAPSULE",
            stock_batch_id=7188,
            pack_size="10",
            location="A1",
            batch_no="18254384B",
            expiry="2027-10-31",
            mrp=137.16,
            sale_qty=10.0,
            discount_amount=0.0,
            amount=137.16,
            net_rate=99.75,
            purchase_rate=104.50,
        )
        panel._item_rows.append(row)
        panel._recalc_totals()

        self.assertEqual(panel.total_amount_label.text(), "137.16")
        self.assertEqual(panel.round_off_label.text(), "-0.16")
        self.assertEqual(panel.net_amt_label.text(), "137.00")
        self.assertEqual(panel.customer_saving_label.text(), "0.00")
        self.assertEqual(panel.yours_label.text(), "37.41")

    def test_positive_round_off_save_and_ledger(self):
        """Saving a sale with total 100.50 stores round_off +0.50 and net_amount 101.0."""
        customer_id = CustomerDAO.get_or_create_walkin()
        items = [{
            "item_id": 1,
            "stock_batch_id": 7188,
            "pack_size": "10",
            "location": "A1",
            "batch_no": "18254384B",
            "expiry": "2027-10-31",
            "mrp": 100.50,
            "sale_qty": 10.0,
            "discount_amount": 0.0,
            "amount": 100.50,
        }]

        unrounded = 100.50
        ro, net = _compute_bill_round_off(unrounded)
        self.assertEqual(ro, 0.50)
        self.assertEqual(net, 101.0)

        inv_id = SalesDAO.insert_invoice(
            bill_no="TEST-002",
            sale_date="2026-10-22",
            sale_time="11:00",
            sale_type="Cash",
            customer_id=customer_id,
            patient_name="WALKIN",
            doctor_id=None,
            discount=0.0,
            paid_amount=net,
            total_amount=unrounded,
            round_off=ro,
            net_amount=net,
            remarks="Positive round-off test",
            items=items,
        )

        saved = SalesDAO.get_by_id(inv_id)
        self.assertEqual(saved["total_amount"], 100.50)
        self.assertEqual(saved["round_off"], 0.50)
        self.assertEqual(saved["net_amount"], 101.0)

        conn = get_connection()
        try:
            lines = conn.execute(
                """
                SELECT lt.debit, lt.credit, al.ledger_name
                FROM ledger_transactions lt
                JOIN account_ledgers al ON al.id = lt.ledger_id
                WHERE lt.reference_type = 'COUNTER_SALE' AND lt.reference_id = ?
                """,
                (inv_id,),
            ).fetchall()
            self.assertEqual(len(lines), 2)
            tot_debit = sum(r[0] for r in lines)
            tot_credit = sum(r[1] for r in lines)
            self.assertEqual(tot_debit, 101.0)
            self.assertEqual(tot_credit, 101.0)
        finally:
            conn.close()

    def test_customer_linked_credit_sale_receivable_and_roundoff(self):
        """Customer-linked credit sale with partial payment.
        Bill total = 137.16 -> net_amount = 137.00.
        Paid = 50.00 -> Customer receivable = 87.00.
        Ledger postings: Debit CASH 50, Debit Customer 87, Credit SALES 137.
        """
        cust_id = CustomerDAO.insert("Test Credit Customer")
        cust_ledger_id = CustomerDAO.get_ledger_id(cust_id)
        self.assertIsNotNone(cust_ledger_id)

        items = [{
            "item_id": 1,
            "stock_batch_id": 7188,
            "pack_size": "10",
            "location": "A1",
            "batch_no": "18254384B",
            "expiry": "2027-10-31",
            "mrp": 137.16,
            "sale_qty": 10.0,
            "discount_amount": 0.0,
            "amount": 137.16,
        }]

        unrounded = 137.16
        ro, net = _compute_bill_round_off(unrounded)
        paid = 50.0

        inv_id = SalesDAO.insert_invoice(
            bill_no="TEST-003",
            sale_date="2026-10-22",
            sale_time="11:30",
            sale_type="Cash",
            customer_id=cust_id,
            patient_name="John Doe",
            doctor_id=None,
            discount=0.0,
            paid_amount=paid,
            total_amount=unrounded,
            round_off=ro,
            net_amount=net,
            remarks="Credit sale test",
            items=items,
        )

        conn = get_connection()
        try:
            lines = conn.execute(
                """
                SELECT lt.debit, lt.credit, lt.ledger_id
                FROM ledger_transactions lt
                WHERE lt.reference_type = 'COUNTER_SALE' AND lt.reference_id = ?
                """,
                (inv_id,),
            ).fetchall()
            # Expect 3 legs: CASH debit 50, Customer debit 87, SALES credit 137
            self.assertEqual(len(lines), 3)
            tot_debit = sum(r[0] for r in lines)
            tot_credit = sum(r[1] for r in lines)
            self.assertEqual(tot_debit, 137.0)
            self.assertEqual(tot_credit, 137.0)

            # Check customer ledger debit
            cust_entries = [r for r in lines if r[2] == cust_ledger_id]
            self.assertEqual(len(cust_entries), 1)
            self.assertEqual(cust_entries[0][0], 87.0)  # Debit 87.0
        finally:
            conn.close()

    def test_multiline_bill_with_savings_and_profit(self):
        """Multi-item bill with savings from discounts and differing costs."""
        # Row 1: ALGESIA CR (MRP 137.16, Cost 99.75, Amount 137.16) -> Yours 37.41, Saving 0
        r1 = _BillItemRow(
            item_id=1, item_name="ALGESIA CR", stock_batch_id=7188,
            pack_size="10", location="", batch_no="B1", expiry="2027-10-31",
            mrp=137.16, sale_qty=10.0, discount_amount=0.0, amount=137.16,
            net_rate=99.75, purchase_rate=104.50,
        )
        # Row 2: Discounted item (MRP 100, Cost 60, Line Discount 10, Amount 90) -> Yours 30, Saving 10
        r2 = _BillItemRow(
            item_id=2, item_name="DISCOUNTED ITEM", stock_batch_id=7189,
            pack_size="1", location="", batch_no="B2", expiry="2027-10-31",
            mrp=100.0, sale_qty=1.0, discount_amount=10.0, amount=90.0,
            net_rate=60.0, purchase_rate=65.0,
        )

        # Bill discount = 5.0
        # Line amounts: 137.16 + 90.0 = 227.16
        # Unrounded net: 227.16 - 5.0 = 222.16
        # Round-off: -0.16 -> Payable: 222.00
        # Line Yours: 37.41 + 30.0 = 67.41 -> Net Yours: 67.41 - 5.0 = 62.41
        # Line Savings: 0.0 + 10.0 = 10.0 -> Net Savings: 10.0 + 5.0 = 15.00
        savings, yours = _compute_bill_savings_and_profit([r1, r2], bill_discount=5.0)
        self.assertAlmostEqual(savings, 15.00, places=2)
        self.assertAlmostEqual(yours, 62.41, places=2)

        ro, payable = _compute_bill_round_off(227.16 - 5.0)
        self.assertAlmostEqual(ro, -0.16, places=2)
        self.assertEqual(payable, 222.0)

    def test_counter_sale_page_status_bar(self):
        """CounterSalePage bottom status bar shows CntNo, Total Items, Savings, Yours, and Bill(s) Total."""
        page = CounterSalePage()
        self.assertTrue(hasattr(page, "_status_bar"))
        self.assertTrue(hasattr(page, "_status_cnt_label"))
        self.assertTrue(hasattr(page, "_status_items_label"))
        self.assertTrue(hasattr(page, "_status_saving_label"))
        self.assertTrue(hasattr(page, "_status_yours_label"))
        self.assertTrue(hasattr(page, "_status_bills_total_label"))

        # Add ALGESIA CR to active panel
        row = _BillItemRow(
            item_id=1, item_name="ALGESIA CR", stock_batch_id=7188,
            pack_size="10", location="", batch_no="18254384B", expiry="2027-10-31",
            mrp=137.16, sale_qty=10.0, discount_amount=0.0, amount=137.16,
            net_rate=99.75, purchase_rate=104.50,
        )
        page._sale_panel._item_rows.append(row)
        page._sale_panel._recalc_totals()
        page._refresh_status_bar()

        self.assertIn("1", page._status_items_label.text())
        self.assertIn("0.00", page._status_saving_label.text())
        self.assertIn("37.41", page._status_yours_label.text())
        self.assertIn("137.00", page._status_bills_total_label.text())


if __name__ == "__main__":
    unittest.main()
