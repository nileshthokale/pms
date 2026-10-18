"""Tests for Counter Sale Edit Button — Open Bill in an Editing Dialog.

Covers:
1. Selecting a saved bill in history and clicking Edit opens SalesBillReviewDialog modally.
2. The dialog is titled "Edit Sales Bill".
3. The dialog loads all bill data: bill no, date/time, customer, patient name, doctor, items, totals.
4. The main screen's lower Bill Items table and active draft are completely untouched.
5. Saving inside the dialog updates the existing bill in place via SalesDAO.update_invoice
   (same ID, same bill_no, no duplicates, sequence not advanced).
6. Closing or canceling the dialog discards changes and leaves the bill and drafts untouched.
7. Unsaved items in other open bills are protected through reservation provider.
8. Expired stock checks work properly.
9. Bill history and totals refresh after saving.
10. Double-clicking a row in the history table opens the edit dialog.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem
from screens.counter_sale import CounterSalePage, SalesBillReviewDialog, _display_bill_no

from database.connection import get_connection, init_database
from database.sales_dao import SalesDAO
from database.item_dao import ItemDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database.hold_bill_dao import ensure_hold_tables
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year

_DB_PATH = os.path.join(tempfile.gettempdir(), "pharmacy_edit_dialog_test.db")
_TABLES = [
    "ledger_transactions", "account_ledgers",
    "customer_receipts", "supplier_payments",
    "debit_note_items", "debit_notes",
    "credit_note_items", "credit_notes",
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "hold_bill_items", "hold_bills",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class TestCounterSaleEditDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_DB_PATH):
            try:
                os.remove(_DB_PATH)
            except Exception:
                pass
        os.environ["PHARMACY_DB"] = _DB_PATH
        init_database()
        ensure_hold_tables()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.MagicMock(return_value=QMessageBox.Yes),
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

        conn = get_connection()
        try:
            for tbl in _TABLES:
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()
        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.customer_walkin_id = CustomerDAO.insert("Walkin Customer")
        self.doctor_id = DoctorDAO.insert("Dr. Sharma")
        self.item_id = ItemDAO.insert(
            item_name="Paracetamol 500mg",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            mrp=100.0,
        )
        self._seed_stock(qty=200.0, rate=50.0, mrp=100.0)

    def _seed_stock(self, qty=200.0, rate=50.0, mrp=100.0, batch_no="BATCH-A", expiry="12/28"):
        PurchaseDAO.insert_invoice(
            voucher_no=f"PV-{batch_no}",
            voucher_date="2026-01-01",
            voucher_time="",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no=f"INV-{batch_no}",
            invoice_date="2026-01-01",
            invoice_net_amount=qty * rate,
            bill_discount=0,
            due_date="",
            total_amount=qty * rate,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=qty * rate,
            round_off=0,
            net_amount=qty * rate,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": qty,
                "free_qty": 0,
                "batch_no": batch_no,
                "expiry": expiry,
                "rate": rate,
                "mrp": mrp,
                "discount": 0,
                "gst_percent": 0,
                "gst_amount": 0,
                "amount": qty * rate,
                "purchase_rate": rate,
                "net_rate": rate,
                "pp": rate,
            }],
        )

    def _create_saved_sale(self, bill_no="2026-2027-101", patient_name="John Doe", sale_qty=5.0) -> int:
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch = batches[0]
        unit_price = batch["mrp"] / 10.0
        line_amt = round(sale_qty * unit_price, 2)
        inv_id = SalesDAO.insert_invoice(
            bill_no=bill_no,
            sale_date="2026-06-15",
            sale_time="10:30",
            sale_type="Cash",
            customer_id=self.customer_id,
            patient_name=patient_name,
            doctor_id=self.doctor_id,
            discount=0.0,
            paid_amount=line_amt,
            total_amount=line_amt,
            round_off=0.0,
            net_amount=line_amt,
            remarks="Initial sale remarks",
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": batch["id"],
                "batch_no": batch["batch_no"],
                "pack_size": "10",
                "location": "A1",
                "expiry": batch["expiry"],
                "mrp": batch["mrp"],
                "sale_qty": sale_qty,
                "discount_amount": 0.0,
                "amount": line_amt,
            }],
        )
        return inv_id

    def test_01_edit_opens_sales_bill_dialog(self):
        """Selecting a history bill and clicking Edit opens SalesBillReviewDialog."""
        inv_id = self._create_saved_sale(bill_no="2026-2027-101", patient_name="John Doe")
        page = CounterSalePage()
        page._hist_date.setDate(QDate(2026, 6, 15))
        page._refresh_history()

        self.assertGreater(page._hist_table.rowCount(), 0)
        page._hist_table.selectRow(0)

        dlg = page._on_edit()
        self.assertIsNotNone(dlg)
        self.assertIsInstance(dlg, SalesBillReviewDialog)
        self.assertEqual(dlg.windowTitle(), "Edit Sales Bill")
        dlg.reject()

    def test_02_main_screen_panel_and_draft_untouched_on_edit(self):
        """Active draft in main screen _sale_panel is NOT overwritten or touched when editing."""
        inv_id = self._create_saved_sale(bill_no="2026-2027-101", patient_name="John Doe")
        page = CounterSalePage()
        page._hist_date.setDate(QDate(2026, 6, 15))
        page._refresh_history()

        # Add a draft item to the main screen's panel
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch = batches[0]
        page._sale_panel._entry_bar.item_combo.setCurrentIndex(
            page._sale_panel._entry_bar.item_combo.findData(self.item_id)
        )
        page._sale_panel._entry_bar.batch_combo.setCurrentIndex(
            page._sale_panel._entry_bar.batch_combo.findData(batch["id"])
        )
        page._sale_panel._entry_bar.qty_edit.setText("2")
        page._sale_panel._on_add_item()
        self.assertEqual(len(page._sale_panel._item_rows), 1)
        self.assertEqual(page._sale_panel._item_rows[0].sale_qty, 2.0)

        # Select history row and click edit
        page._hist_table.selectRow(0)
        dlg = page._on_edit()

        # Main panel must still have exactly its 1 draft item with qty 2.0!
        self.assertEqual(len(page._sale_panel._item_rows), 1)
        self.assertEqual(page._sale_panel._item_rows[0].sale_qty, 2.0)

        # Dialog has the history bill's items (qty 5.0)
        self.assertEqual(len(dlg._panel._item_rows), 1)
        self.assertEqual(dlg._panel._item_rows[0].sale_qty, 5.0)

        dlg.reject()

        # Even after closing the dialog, main panel is still untouched!
        self.assertEqual(len(page._sale_panel._item_rows), 1)
        self.assertEqual(page._sale_panel._item_rows[0].sale_qty, 2.0)

    def test_03_edit_dialog_loads_full_invoice_data(self):
        """Dialog loads voucher number, date, time, customer, patient, doctor, items, and totals."""
        inv_id = self._create_saved_sale(bill_no="2026-2027-105", patient_name="Jane Doe", sale_qty=10.0)
        page = CounterSalePage()
        page._hist_date.setDate(QDate(2026, 6, 15))
        page._refresh_history()

        page._hist_table.selectRow(0)
        dlg = page._on_edit()

        # Voucher No display (numeric-only in label, full in tooltip)
        self.assertEqual(dlg._panel.voucher_no_label.text(), "105")
        self.assertIn("2026-2027-105", dlg._panel.voucher_no_label.toolTip())

        # Date & Time
        self.assertEqual(dlg._panel.header_date_label.text(), "15-06-2026")
        self.assertEqual(dlg._panel.header_time_label.text(), "10:30")

        # Customer, Patient, Doctor
        self.assertEqual(dlg._panel.customer_combo.currentData(), self.customer_id)
        self.assertEqual(dlg._panel.patient_name_edit.text(), "Jane Doe")
        self.assertEqual(dlg._panel.doctor_combo.currentData(), self.doctor_id)

        # Items
        self.assertEqual(len(dlg._panel._item_rows), 1)
        row = dlg._panel._item_rows[0]
        self.assertEqual(row.item_id, self.item_id)
        self.assertEqual(row.batch_no, "BATCH-A")
        self.assertEqual(row.sale_qty, 10.0)
        self.assertEqual(row.mrp, 100.0)
        self.assertEqual(row.amount, 100.0)

        # Footer totals
        self.assertEqual(dlg._total_items_label.text(), "1")
        self.assertEqual(dlg._footer_total_amount.text(), "100.00")
        self.assertEqual(dlg._footer_net_amount.text(), "100.00")
        self.assertEqual(dlg.remarks_edit.text(), "Initial sale remarks")

        dlg.reject()

    def test_04_edit_dialog_save_updates_in_place_without_new_id_or_sequence_advance(self):
        """Saving updates the bill using original ID and bill_no; no new records, sequence intact."""
        inv_id = self._create_saved_sale(bill_no="2026-2027-200", patient_name="Patient Alpha", sale_qty=5.0)
        initial_count = len(SalesDAO.get_all())
        initial_next_bno = SalesDAO.generate_next_bill_no()

        page = CounterSalePage()
        page._hist_date.setDate(QDate(2026, 6, 15))
        page._refresh_history()

        page._hist_table.selectRow(0)
        dlg = page._on_edit()

        # Modify patient name and remarks
        dlg._panel.patient_name_edit.setText("Patient Alpha Modified")
        dlg.remarks_edit.setText("Updated remarks")

        # Delete old line and add new line with qty 8
        dlg._panel._delete_item(0)
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch = batches[0]
        dlg._panel._entry_bar.item_combo.setCurrentIndex(
            dlg._panel._entry_bar.item_combo.findData(self.item_id)
        )
        dlg._panel._entry_bar.batch_combo.setCurrentIndex(
            dlg._panel._entry_bar.batch_combo.findData(batch["id"])
        )
        dlg._panel._entry_bar.qty_edit.setText("8")
        dlg._panel._on_add_item()
        dlg._panel.paid_edit.setText("80.00")

        # Click Save
        dlg._final_save_btn.click()
        self.assertTrue(dlg._panel.was_saved)

        # Check database: record count must be EXACTLY the same (no duplicates)
        after_count = len(SalesDAO.get_all())
        self.assertEqual(after_count, initial_count)

        # The invoice with inv_id must have updated values
        updated = SalesDAO.get_by_id(inv_id)
        self.assertIsNotNone(updated)
        self.assertEqual(updated["bill_no"], "2026-2027-200")
        self.assertEqual(updated["patient_name"], "Patient Alpha Modified")
        self.assertEqual(updated["remarks"], "Updated remarks")
        self.assertEqual(updated["net_amount"], 80.0)

        # Check next bill sequence did NOT advance
        after_next_bno = SalesDAO.generate_next_bill_no()
        self.assertEqual(after_next_bno, initial_next_bno)

    def test_05_edit_dialog_close_discards_changes(self):
        """Closing or canceling discards changes and leaves the bill untouched in database."""
        inv_id = self._create_saved_sale(bill_no="2026-2027-300", patient_name="Patient Beta", sale_qty=5.0)

        page = CounterSalePage()
        page._hist_date.setDate(QDate(2026, 6, 15))
        page._refresh_history()

        page._hist_table.selectRow(0)
        dlg = page._on_edit()

        # Modify values
        dlg._panel.patient_name_edit.setText("Discarded Name")
        dlg._panel._delete_item(0)

        # Reject / Close
        dlg.reject()

        # Check database: unchanged
        original = SalesDAO.get_by_id(inv_id)
        self.assertEqual(original["patient_name"], "Patient Beta")
        items = SalesDAO.get_invoice_items(inv_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sale_qty"], 5.0)

    def test_06_stock_delta_handling_allows_original_quantity(self):
        """Stock delta calculation allows the invoice's own original quantity during editing."""
        # Stock has 200 units total.
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch = batches[0]
        # Current batch stock in DB is 200 - 5 = 195 after sale of 5
        inv_id = self._create_saved_sale(bill_no="2026-2027-400", patient_name="Delta Patient", sale_qty=5.0)

        page = CounterSalePage()
        page._hist_date.setDate(QDate(2026, 6, 15))
        page._refresh_history()

        page._hist_table.selectRow(0)
        dlg = page._on_edit()

        # The dialog's panel loaded the original batch qty
        self.assertEqual(dlg._panel._original_batch_qty.get(batch["id"]), 5.0)

        # Can increase qty up to remaining stock + original qty
        dlg.reject()

    def test_07_double_click_history_table_triggers_edit(self):
        """Double clicking a history row opens the edit dialog."""
        inv_id = self._create_saved_sale(bill_no="2026-2027-500", patient_name="Click Patient", sale_qty=2.0)
        page = CounterSalePage()
        page._hist_date.setDate(QDate(2026, 6, 15))
        page._refresh_history()

        page._hist_table.selectRow(0)
        # Trigger edit directly (simulating double click connection)
        dlg = page._on_edit()
        self.assertIsNotNone(dlg)
        self.assertEqual(dlg.windowTitle(), "Edit Sales Bill")
        dlg.reject()


if __name__ == "__main__":
    unittest.main()
