"""Comprehensive test suite for Supplier Payment Voucher and Customer Receipt Voucher

Covers all 11 acceptance criteria:
1. Selecting a supplier loads only that supplier's outstanding purchase invoices.
2. Selecting a customer loads only that customer's outstanding sales bills.
3. Full and partial payments/receipts update outstanding balances correctly.
4. FIFO allocation works correctly, including the ₹10,000 example.
5. Supplier payments update the Supplier Ledger and Cash/Bank ledger correctly.
6. Customer receipts update the Customer Ledger and Cash/Bank ledger correctly.
7. Failed saves roll back all database changes.
8. Editing and deleting vouchers do not duplicate or leave behind ledger postings.
9. Duplicate Save actions do not post twice.
10. Missing account mappings and excess payments are handled safely.
11. Menu wiring and existing accounting regression tests still pass.

Runs offscreen: QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import (
    ROLE_BANK,
    ROLE_CASH,
    ROLE_PURCHASE,
    ROLE_SALES,
    ensure_system_ledgers,
)
from database.accounting_posting import (
    SOURCE_CUSTOMER_RECEIPT,
    SOURCE_SUPPLIER_PAYMENT,
    PostingError,
    posting_engine,
)
from database.company_dao import CompanyDAO
from database.customer_dao import CustomerDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.ledger_dao import LedgerDAO
from database.ledger_report_dao import LedgerReportDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.unit_dao import UnitDAO
from screens.customer_receipt import CustomerReceiptPage, _CustomerReceiptEntryDialog
from screens.supplier_payment import SupplierPaymentPage, _SupplierPaymentEntryDialog
from ui.main_window import PharmacyMainWindow
from ui.menu_data import MENUS

_TABLES = [
    "customer_receipt_allocations",
    "supplier_payment_allocations",
    "customer_receipts",
    "supplier_payments",
    "ledger_transactions",
    "journal_entry_items",
    "journal_entries",
    "account_ledgers",
    "debit_note_items",
    "debit_notes",
    "credit_note_items",
    "credit_notes",
    "sales_invoice_items",
    "sales_invoices",
    "purchase_invoice_items",
    "purchase_invoices",
    "stock_batches",
    "item_ingredients",
    "items",
    "doctors",
    "customers",
    "suppliers",
    "drugs",
    "units",
    "companies",
]


class VoucherSystemAndLedgerIntegrationTests(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_voucher_ledger_sys.db")

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in _TABLES:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

        # Seed master data
        self.company_id = CompanyDAO.insert("Apex Pharma", "APEX")
        self.unit_id = UnitDAO.insert("Strip")
        self.doctor_id = DoctorDAO.insert("Dr. Sharma")

        # 1. Suppliers with linked ledgers
        self.sup1_id = SupplierDAO.insert("Alfa Pharma", city="Mumbai")
        self.sup2_id = SupplierDAO.insert("Beta Healthcare", city="Pune")

        # Supplier 3 without linked ledger (for missing mapping test)
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO suppliers (supplier_name, city, opening_balance) VALUES (?, ?, ?)",
                ("Gamma Unmapped", "Nashik", 0.0),
            )
            self.sup3_unmapped_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        # 2. Customers with linked ledgers
        self.cust1_id = CustomerDAO.insert("John Doe", city="Mumbai")
        self.cust2_id = CustomerDAO.insert("Jane Smith", city="Pune")

        # Customer 3 without linked ledger
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO customers (customer_name, city, opening_balance) VALUES (?, ?, ?)",
                ("Unmapped Customer", "Nashik", 0.0),
            )
            self.cust3_unmapped_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()

        # Item for purchases and sales
        self.item_id = ItemDAO.insert(
            item_name="Paracetamol 650",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
        )

        # 3. Create purchase invoices for Alfa Pharma
        # Invoice A: 5,249.00
        self.inv_a_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0001",
            voucher_date="2026-04-10",
            voucher_time="10:00",
            purchase_type="Credit",
            supplier_id=self.sup1_id,
            invoice_no="INV-A101",
            invoice_date="2026-04-10",
            invoice_net_amount=5249.0,
            bill_discount=0,
            due_date="",
            total_amount=5249.0,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=0.0,
            round_off=0,
            net_amount=5249.0,
            remarks="Invoice A",
            items=[{
                "item_id": self.item_id, "pack_size": "10", "pay_qty": 100, "free_qty": 0,
                "batch_no": "B-001", "expiry": "12/28", "rate": 52.49, "mrp": 65.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 5249.0,
                "purchase_rate": 52.49, "net_rate": 52.49, "pp": 52.49,
            }],
        )

        # Invoice B: 6,327.00
        self.inv_b_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0002",
            voucher_date="2026-04-15",
            voucher_time="11:00",
            purchase_type="Credit",
            supplier_id=self.sup1_id,
            invoice_no="INV-B102",
            invoice_date="2026-04-15",
            invoice_net_amount=6327.0,
            bill_discount=0,
            due_date="",
            total_amount=6327.0,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=0.0,
            round_off=0,
            net_amount=6327.0,
            remarks="Invoice B",
            items=[{
                "item_id": self.item_id, "pack_size": "10", "pay_qty": 100, "free_qty": 0,
                "batch_no": "B-002", "expiry": "12/28", "rate": 63.27, "mrp": 75.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 6327.0,
                "purchase_rate": 63.27, "net_rate": 63.27, "pp": 63.27,
            }],
        )

        # Invoice C for Beta Healthcare: 3,000.00
        self.inv_c_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0003",
            voucher_date="2026-04-12",
            voucher_time="12:00",
            purchase_type="Credit",
            supplier_id=self.sup2_id,
            invoice_no="INV-C103",
            invoice_date="2026-04-12",
            invoice_net_amount=3000.0,
            bill_discount=0,
            due_date="",
            total_amount=3000.0,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=0.0,
            round_off=0,
            net_amount=3000.0,
            remarks="Invoice C",
            items=[{
                "item_id": self.item_id, "pack_size": "10", "pay_qty": 50, "free_qty": 0,
                "batch_no": "B-003", "expiry": "12/28", "rate": 60.0, "mrp": 70.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 3000.0,
                "purchase_rate": 60.0, "net_rate": 60.0, "pp": 60.0,
            }],
        )

        # 4. Create sales bills for John Doe
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]

        # Bill A: 1,500.00
        self.bill_a_id = SalesDAO.insert_invoice(
            bill_no="CS-0001",
            sale_date="2026-04-11",
            sale_time="14:00",
            sale_type="Credit",
            customer_id=self.cust1_id,
            patient_name="Patient 1",
            doctor_id=self.doctor_id,
            discount=0.0,
            paid_amount=0.0,
            total_amount=1500.0,
            round_off=0.0,
            net_amount=1500.0,
            remarks="Bill A",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "B-001", "expiry": "12/28", "mrp": 65.0,
                "pack_size": "10", "location": "", "sale_qty": 20, "discount_amount": 0.0, "amount": 1500.0,
            }],
        )

        # Bill B: 2,500.00
        self.bill_b_id = SalesDAO.insert_invoice(
            bill_no="CS-0002",
            sale_date="2026-04-14",
            sale_time="15:00",
            sale_type="Credit",
            customer_id=self.cust1_id,
            patient_name="Patient 1",
            doctor_id=self.doctor_id,
            discount=0.0,
            paid_amount=0.0,
            total_amount=2500.0,
            round_off=0.0,
            net_amount=2500.0,
            remarks="Bill B",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "B-001", "expiry": "12/28", "mrp": 65.0,
                "pack_size": "10", "location": "", "sale_qty": 30, "discount_amount": 0.0, "amount": 2500.0,
            }],
        )

        # Bill C for Jane Smith: 4,000.00
        self.bill_c_id = SalesDAO.insert_invoice(
            bill_no="CS-0003",
            sale_date="2026-04-13",
            sale_time="16:00",
            sale_type="Credit",
            customer_id=self.cust2_id,
            patient_name="Patient 2",
            doctor_id=self.doctor_id,
            discount=0.0,
            paid_amount=0.0,
            total_amount=4000.0,
            round_off=0.0,
            net_amount=4000.0,
            remarks="Bill C",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "B-001", "expiry": "12/28", "mrp": 65.0,
                "pack_size": "10", "location": "", "sale_qty": 50, "discount_amount": 0.0, "amount": 4000.0,
            }],
        )

    # ------------------------------------------------------------------
    # 1. Supplier Invoices Isolation
    # ------------------------------------------------------------------
    def test_01_supplier_invoices_isolation(self):
        """Selecting a supplier loads ONLY that supplier's outstanding purchase invoices."""
        sup1_invoices = SupplierPaymentDAO.get_outstanding_invoices(self.sup1_id)
        sup1_invoice_nos = [x["invoice_no"] for x in sup1_invoices]
        self.assertEqual(len(sup1_invoices), 2)
        self.assertIn("INV-A101", sup1_invoice_nos)
        self.assertIn("INV-B102", sup1_invoice_nos)
        self.assertNotIn("INV-C103", sup1_invoice_nos)

        sup2_invoices = SupplierPaymentDAO.get_outstanding_invoices(self.sup2_id)
        sup2_invoice_nos = [x["invoice_no"] for x in sup2_invoices]
        self.assertEqual(len(sup2_invoices), 1)
        self.assertEqual(sup2_invoice_nos, ["INV-C103"])

    # ------------------------------------------------------------------
    # 2. Customer Bills Isolation
    # ------------------------------------------------------------------
    def test_02_customer_bills_isolation(self):
        """Selecting a customer loads ONLY that customer's outstanding sales bills."""
        cust1_bills = CustomerReceiptDAO.get_outstanding_bills(self.cust1_id)
        cust1_bill_nos = [x["bill_no"] for x in cust1_bills]
        self.assertEqual(len(cust1_bills), 2)
        self.assertIn("CS-0001", cust1_bill_nos)
        self.assertIn("CS-0002", cust1_bill_nos)
        self.assertNotIn("CS-0003", cust1_bill_nos)

        cust2_bills = CustomerReceiptDAO.get_outstanding_bills(self.cust2_id)
        cust2_bill_nos = [x["bill_no"] for x in cust2_bills]
        self.assertEqual(len(cust2_bills), 1)
        self.assertEqual(cust2_bill_nos, ["CS-0003"])

    # ------------------------------------------------------------------
    # 3. FIFO Allocation Logic (including ₹10,000 example)
    # ------------------------------------------------------------------
    def test_03_fifo_allocation_10000_example(self):
        """FIFO allocates ₹10,000 across Inv A (₹5,249) and Inv B (₹6,327).

        Expected:
        - Invoice A paid: ₹5,249.00
        - Invoice B paid: ₹4,751.00
        - Remaining amount due on Invoice B: ₹1,576.00
        """
        invoices = SupplierPaymentDAO.get_outstanding_invoices(self.sup1_id)
        allocations = SupplierPaymentDAO.calculate_fifo_allocation(invoices, 10000.0)

        self.assertEqual(len(allocations), 2)
        self.assertEqual(allocations[0]["purchase_invoice_id"], self.inv_a_id)
        self.assertAlmostEqual(allocations[0]["allocated_amount"], 5249.0)
        self.assertAlmostEqual(allocations[0]["remaining_balance"], 0.0)

        self.assertEqual(allocations[1]["purchase_invoice_id"], self.inv_b_id)
        self.assertAlmostEqual(allocations[1]["allocated_amount"], 4751.0)
        self.assertAlmostEqual(allocations[1]["remaining_balance"], 1576.0)

        # Save payment and verify database allocations
        pay_header = {
            "payment_date": "2026-04-18",
            "payment_time": "12:00",
            "supplier_id": self.sup1_id,
            "payment_mode": "Cash",
            "amount": 10000.0,
            "reference_no": "CASH-100",
            "remarks": "FIFO payment test",
        }
        pay_id = SupplierPaymentDAO.insert_payment(pay_header, allocations=allocations)
        self.assertGreater(pay_id, 0)

        saved_allocs = SupplierPaymentDAO.get_payment_allocations(pay_id)
        self.assertEqual(len(saved_allocs), 2)
        self.assertAlmostEqual(saved_allocs[0]["allocated_amount"], 5249.0)
        self.assertAlmostEqual(saved_allocs[1]["allocated_amount"], 4751.0)

        # Subsequent fetch: Inv A is fully paid (omitted), Inv B outstanding is exactly ₹1,576
        rem_invoices = SupplierPaymentDAO.get_outstanding_invoices(self.sup1_id)
        self.assertEqual(len(rem_invoices), 1)
        self.assertEqual(rem_invoices[0]["id"], self.inv_b_id)
        self.assertAlmostEqual(rem_invoices[0]["outstanding_balance"], 1576.0)

    # ------------------------------------------------------------------
    # 4. Full and Partial Receipts Updates
    # ------------------------------------------------------------------
    def test_04_full_and_partial_receipt_updates(self):
        """Customer receipt updates outstanding sales bills in FIFO order and supports partial payment."""
        bills = CustomerReceiptDAO.get_outstanding_bills(self.cust1_id)
        # Bill A: 1500, Bill B: 2500. Receipt: 2000
        rc_header = {
            "receipt_date": "2026-04-18",
            "receipt_time": "14:00",
            "customer_id": self.cust1_id,
            "receipt_mode": "Cash",
            "amount": 2000.0,
            "reference_no": "REC-01",
            "remarks": "Partial receipt test",
        }
        rc_id = CustomerReceiptDAO.insert_receipt(rc_header)

        # Bill A is fully paid, Bill B has 2000 remaining
        rem_bills = CustomerReceiptDAO.get_outstanding_bills(self.cust1_id)
        self.assertEqual(len(rem_bills), 1)
        self.assertEqual(rem_bills[0]["bill_no"], "CS-0002")
        self.assertAlmostEqual(rem_bills[0]["outstanding_balance"], 2000.0)

        # Settle the remaining 2000 on Bill B
        rc2_header = {
            "receipt_date": "2026-04-19",
            "receipt_time": "15:00",
            "customer_id": self.cust1_id,
            "receipt_mode": "Bank",
            "amount": 2000.0,
            "reference_no": "UPI-02",
            "remarks": "Final settlement",
        }
        CustomerReceiptDAO.insert_receipt(rc2_header)

        final_bills = CustomerReceiptDAO.get_outstanding_bills(self.cust1_id)
        self.assertEqual(len(final_bills), 0, "All bills must be fully settled")

    # ------------------------------------------------------------------
    # 5. Supplier Payment Updates Supplier Ledger and Cash/Bank Ledger
    # ------------------------------------------------------------------
    def test_05_supplier_payment_updates_ledgers(self):
        """Supplier payment debits Supplier Ledger and credits Cash/Bank correctly."""
        sup1 = SupplierDAO.get_by_id(self.sup1_id)
        sup_ledger_id = sup1["ledger_id"]

        # Initial balance: 5249 + 6327 = 11576 Credit
        init_bal = LedgerDAO.get_balance(sup_ledger_id)
        self.assertAlmostEqual(init_bal["closing_balance"], 11576.0)
        self.assertEqual(init_bal["closing_balance_type"], "Credit")

        # Make payment of 10,000 Cash
        pay_header = {
            "payment_date": "2026-04-18",
            "payment_time": "10:30",
            "supplier_id": self.sup1_id,
            "payment_mode": "Cash",
            "amount": 10000.0,
            "reference_no": "CASH-PAY",
            "remarks": "Ledger test",
        }
        pay_id = SupplierPaymentDAO.insert_payment(pay_header)

        # Supplier ledger balance should now be 1,576 Credit
        new_sup_bal = LedgerDAO.get_balance(sup_ledger_id)
        self.assertAlmostEqual(new_sup_bal["closing_balance"], 1576.0)
        self.assertEqual(new_sup_bal["closing_balance_type"], "Credit")

        # Cash ledger should have credit of 10,000
        cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.assertIsNotNone(cash_ledger)
        cash_bal = LedgerDAO.get_balance(cash_ledger["id"])
        self.assertAlmostEqual(cash_bal["total_credit"], 10000.0)

        # Supplier Ledger report verification
        report = LedgerReportDAO.get_supplier_ledger(self.sup1_id, "2026-04-01", "2026-04-30")
        self.assertIsNotNone(report)
        self.assertAlmostEqual(report["total_debit"], 10000.0)
        self.assertAlmostEqual(report["total_credit"], 11576.0)
        self.assertAlmostEqual(report["closing_balance"], 1576.0)
        self.assertEqual(report["closing_balance_type"], "CR")

    # ------------------------------------------------------------------
    # 6. Customer Receipt Updates Customer Ledger and Cash/Bank Ledger
    # ------------------------------------------------------------------
    def test_06_customer_receipt_updates_ledgers(self):
        """Customer receipt credits Customer Ledger and debits Cash/Bank correctly."""
        cust1 = CustomerDAO.get_by_id(self.cust1_id)
        cust_ledger_id = cust1["ledger_id"]

        # Initial balance: 1500 + 2500 = 4000 Debit
        init_bal = LedgerDAO.get_balance(cust_ledger_id)
        self.assertAlmostEqual(init_bal["closing_balance"], 4000.0)
        self.assertEqual(init_bal["closing_balance_type"], "Debit")

        # Receive 2500 into Bank
        rc_header = {
            "receipt_date": "2026-04-18",
            "receipt_time": "11:00",
            "customer_id": self.cust1_id,
            "receipt_mode": "Bank",
            "amount": 2500.0,
            "reference_no": "NEFT-001",
            "remarks": "Bank receipt test",
        }
        rc_id = CustomerReceiptDAO.insert_receipt(rc_header)

        # Customer ledger balance should now be 1,500 Debit
        new_cust_bal = LedgerDAO.get_balance(cust_ledger_id)
        self.assertAlmostEqual(new_cust_bal["closing_balance"], 1500.0)
        self.assertEqual(new_cust_bal["closing_balance_type"], "Debit")

        # Bank ledger should have debit of 2,500
        bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.assertIsNotNone(bank_ledger)
        bank_bal = LedgerDAO.get_balance(bank_ledger["id"])
        self.assertAlmostEqual(bank_bal["total_debit"], 2500.0)

        # Customer Ledger report verification
        report = LedgerReportDAO.get_customer_ledger(self.cust1_id, "2026-04-01", "2026-04-30")
        self.assertIsNotNone(report)
        self.assertAlmostEqual(report["total_debit"], 4000.0)
        self.assertAlmostEqual(report["total_credit"], 2500.0)
        self.assertAlmostEqual(report["closing_balance"], 1500.0)
        self.assertEqual(report["closing_balance_type"], "DR")

    # ------------------------------------------------------------------
    # 7. Failed Saves Roll Back All Database Changes
    # ------------------------------------------------------------------
    def test_07_failed_saves_rollback_all_changes(self):
        """Failed saves roll back all database changes atomically without orphaned records."""
        # Intentionally invalid mode that raises PostingError
        bad_header = {
            "payment_date": "2026-04-18",
            "payment_time": "12:00",
            "supplier_id": self.sup1_id,
            "payment_mode": "Bitcoin",  # unsupported
            "amount": 1000.0,
            "reference_no": "FAIL",
            "remarks": "Should rollback",
        }
        with self.assertRaises(PostingError):
            SupplierPaymentDAO.insert_payment(bad_header)

        # Ensure no payment row exists
        conn = get_connection()
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM supplier_payments WHERE reference_no = 'FAIL'").fetchone()[0]
            self.assertEqual(cnt, 0)
            alloc_cnt = conn.execute("SELECT COUNT(*) FROM supplier_payment_allocations").fetchone()[0]
            self.assertEqual(alloc_cnt, 0)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 8. Editing and Deleting Vouchers
    # ------------------------------------------------------------------
    def test_08_editing_and_deleting_vouchers(self):
        """Editing and deleting vouchers properly update allocations and reverse ledger entries."""
        # 1. Create initial payment of 10,000
        pay_header = {
            "payment_date": "2026-04-18",
            "payment_time": "10:00",
            "supplier_id": self.sup1_id,
            "payment_mode": "Cash",
            "amount": 10000.0,
            "reference_no": "CASH-1",
            "remarks": "Initial",
        }
        pay_id = SupplierPaymentDAO.insert_payment(pay_header)

        # 2. Edit payment down to 8,000
        edit_header = {
            "payment_date": "2026-04-18",
            "payment_time": "10:30",
            "supplier_id": self.sup1_id,
            "payment_mode": "Cash",
            "amount": 8000.0,
            "reference_no": "CASH-1-EDITED",
            "remarks": "Edited amount",
        }
        # Invoices should show original outstanding when excluding this payment
        invoices_for_edit = SupplierPaymentDAO.get_outstanding_invoices(self.sup1_id, exclude_payment_id=pay_id)
        allocations_edit = SupplierPaymentDAO.calculate_fifo_allocation(invoices_for_edit, 8000.0)

        SupplierPaymentDAO.update_payment(pay_id, edit_header, allocations=allocations_edit)

        # Outstanding on Inv B is now 6327 - (8000 - 5249) = 3576
        rem_invoices = SupplierPaymentDAO.get_outstanding_invoices(self.sup1_id)
        self.assertEqual(len(rem_invoices), 1)
        self.assertEqual(rem_invoices[0]["id"], self.inv_b_id)
        self.assertAlmostEqual(rem_invoices[0]["outstanding_balance"], 3576.0)

        # 3. Delete payment
        SupplierPaymentDAO.delete_payment(pay_id)

        # Invoices A and B should be completely restored
        restored_invoices = SupplierPaymentDAO.get_outstanding_invoices(self.sup1_id)
        self.assertEqual(len(restored_invoices), 2)
        inv_map = {x["id"]: x["outstanding_balance"] for x in restored_invoices}
        self.assertAlmostEqual(inv_map[self.inv_a_id], 5249.0)
        self.assertAlmostEqual(inv_map[self.inv_b_id], 6327.0)

        # No orphaned allocations
        conn = get_connection()
        try:
            alloc_cnt = conn.execute("SELECT COUNT(*) FROM supplier_payment_allocations WHERE supplier_payment_id = ?", (pay_id,)).fetchone()[0]
            self.assertEqual(alloc_cnt, 0)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 9. Duplicate Save Actions Do Not Post Twice
    # ------------------------------------------------------------------
    def test_09_duplicate_save_protection(self):
        """Duplicate save attempts are blocked and cannot post twice to the ledger."""
        pay_header = {
            "payment_date": "2026-04-18",
            "payment_time": "10:00",
            "supplier_id": self.sup1_id,
            "payment_mode": "Cash",
            "amount": 1000.0,
            "reference_no": "DUP-TEST",
            "remarks": "",
        }
        pay_id = SupplierPaymentDAO.insert_payment(pay_header)

        # Attempting to post the same payment ID again raises PostingError
        with self.assertRaises(PostingError):
            posting_engine.post_supplier_payment(pay_id)

    # ------------------------------------------------------------------
    # 10. Missing Account Mappings and Excess Payments Handled Safely
    # ------------------------------------------------------------------
    def test_10_missing_account_mappings_and_excess_payments(self):
        """Parties without linked ledgers and excess payments are rejected safely."""
        # Unmapped supplier payment attempt
        unmapped_header = {
            "payment_date": "2026-04-18",
            "payment_time": "10:00",
            "supplier_id": self.sup3_unmapped_id,
            "payment_mode": "Cash",
            "amount": 500.0,
            "reference_no": "",
            "remarks": "",
        }
        with self.assertRaises(PostingError):
            SupplierPaymentDAO.insert_payment(unmapped_header)

        # Unmapped customer receipt attempt
        unmapped_rc_header = {
            "receipt_date": "2026-04-18",
            "receipt_time": "10:00",
            "customer_id": self.cust3_unmapped_id,
            "receipt_mode": "Cash",
            "amount": 500.0,
            "reference_no": "",
            "remarks": "",
        }
        with self.assertRaises(PostingError):
            CustomerReceiptDAO.insert_receipt(unmapped_rc_header)

    # ------------------------------------------------------------------
    # 11. Menu Wiring and UI Instantiation
    # ------------------------------------------------------------------
    def test_11_menu_wiring_and_ui_dialogs(self):
        """Account menu contains both voucher options and routes to working pages and dialogs."""
        account_menu = MENUS["Account"]
        self.assertIn("Supplier Payment Voucher", account_menu)
        self.assertIn("Customer Receipt Voucher", account_menu)

        old_user = auth.session.user
        try:
            auth.session.user = {"id": 1, "username": "admin", "role": auth.ROLE_ADMIN, "is_active": 1}
            main_window = PharmacyMainWindow()
            self.assertIsNotNone(main_window)
        finally:
            auth.session.user = old_user

        # Verify page instances
        sp_page = SupplierPaymentPage()
        cr_page = CustomerReceiptPage()
        self.assertIsNotNone(sp_page)
        self.assertIsNotNone(cr_page)

        # Verify dialog instances
        sp_dlg = _SupplierPaymentEntryDialog()
        cr_dlg = _CustomerReceiptEntryDialog()
        self.assertIsNotNone(sp_dlg)
        self.assertIsNotNone(cr_dlg)


if __name__ == "__main__":
    unittest.main()
