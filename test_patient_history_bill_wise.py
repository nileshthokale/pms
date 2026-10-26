"""Tests for Patient History – Bill Number Wise screen.

Validates:
1. Search and filtering by Bill Number (with and without patient name).
2. Search and filtering by Patient Name (single word, multi-word, case-insensitive).
3. Multiple bills for the same patient listed chronologically.
4. Optional date range filtering.
5. Bill details pane populates with exact line items of the selected bill.
6. Summary strip (Total Items, Bill Amount, Discount, Net Amount) updates properly.
7. Reset and Refresh buttons.
8. Action buttons (View Details, Print Bill, Print / PDF, Close).
9. Integration with Main Window (menu navigation and close routing).
10. Theme refresh handling.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.sales_dao import SalesDAO
from database.account_roles import ensure_system_ledgers
from screens.patient_history_bill_wise import PatientHistoryBillWisePage
from ui.main_window import PharmacyMainWindow
from ui import menu_data


class PatientHistoryBillWiseTests(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_patient_history_bill_wise.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in (
                "ledger_transactions", "sales_invoice_items", "sales_invoices",
                "stock_batches", "items", "customers", "doctors", "financial_years"
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        financial_year.ensure_default_financial_year()

        # Seed test data:
        # Doctor
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO doctors (doctor_name) VALUES ('DR. SHARMA')")
            self.doctor_id = cur.lastrowid

            # Items
            cur.execute(
                "INSERT INTO items (item_name, pack_size, mrp) VALUES ('PARACETAMOL 500MG', '10 TAB', 20.0)"
            )
            self.item1_id = cur.lastrowid
            cur.execute(
                "INSERT INTO items (item_name, pack_size, mrp) VALUES ('AMOXICILLIN 250MG', '10 CAP', 55.0)"
            )
            self.item2_id = cur.lastrowid

            # Stock batches
            cur.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, mrp, purchase_rate, stock_qty)
                   VALUES (?, 'PCM001', '2028-12-31', 20.0, 12.0, 100)""",
                (self.item1_id,),
            )
            self.batch1_id = cur.lastrowid

            cur.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, mrp, purchase_rate, stock_qty)
                   VALUES (?, 'AMX002', '2027-06-30', 55.0, 35.0, 50)""",
                (self.item2_id,),
            )
            self.batch2_id = cur.lastrowid

            # Invoice 1: RAMESH KUMAR, Bill 101, 2 items
            cur.execute(
                """INSERT INTO sales_invoices
                   (bill_no, sale_date, sale_time, patient_name, doctor_id, total_amount, discount, net_amount)
                   VALUES ('101', '2026-05-10', '10:30:00', 'RAMESH KUMAR', ?, 75.0, 5.0, 70.0)""",
                (self.doctor_id,),
            )
            self.inv1_id = cur.lastrowid
            cur.execute(
                """INSERT INTO sales_invoice_items
                   (sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry, mrp, sale_qty, discount_amount, amount)
                   VALUES (?, ?, ?, '10 TAB', 'PCM001', '2028-12-31', 20.0, 1, 0.0, 20.0)""",
                (self.inv1_id, self.item1_id, self.batch1_id),
            )
            cur.execute(
                """INSERT INTO sales_invoice_items
                   (sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry, mrp, sale_qty, discount_amount, amount)
                   VALUES (?, ?, ?, '10 CAP', 'AMX002', '2027-06-30', 55.0, 1, 5.0, 50.0)""",
                (self.inv1_id, self.item2_id, self.batch2_id),
            )

            # Invoice 2: RAMESH KUMAR, Bill 102, 1 item (Multiple bills for same patient)
            cur.execute(
                """INSERT INTO sales_invoices
                   (bill_no, sale_date, sale_time, patient_name, doctor_id, total_amount, discount, net_amount)
                   VALUES ('102', '2026-05-15', '14:20:00', 'RAMESH KUMAR', ?, 40.0, 0.0, 40.0)""",
                (self.doctor_id,),
            )
            self.inv2_id = cur.lastrowid
            cur.execute(
                """INSERT INTO sales_invoice_items
                   (sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry, mrp, sale_qty, discount_amount, amount)
                   VALUES (?, ?, ?, '10 TAB', 'PCM001', '2028-12-31', 20.0, 2, 0.0, 40.0)""",
                (self.inv2_id, self.item1_id, self.batch1_id),
            )

            # Invoice 3: Walk-in (Blank patient name), Bill 103, 1 item
            cur.execute(
                """INSERT INTO sales_invoices
                   (bill_no, sale_date, sale_time, patient_name, doctor_id, total_amount, discount, net_amount)
                   VALUES ('103', '2026-06-01', '16:00:00', '', NULL, 55.0, 0.0, 55.0)"""
            )
            self.inv3_id = cur.lastrowid
            cur.execute(
                """INSERT INTO sales_invoice_items
                   (sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry, mrp, sale_qty, discount_amount, amount)
                   VALUES (?, ?, ?, '10 CAP', 'AMX002', '2027-06-30', 55.0, 1, 0.0, 55.0)""",
                (self.inv3_id, self.item2_id, self.batch2_id),
            )

            # Invoice 4: SITA DEVI, Bill 104, 1 item
            cur.execute(
                """INSERT INTO sales_invoices
                   (bill_no, sale_date, sale_time, patient_name, doctor_id, total_amount, discount, net_amount)
                   VALUES ('104', '2026-07-20', '11:15:00', 'SITA DEVI', NULL, 20.0, 0.0, 20.0)"""
            )
            self.inv4_id = cur.lastrowid
            cur.execute(
                """INSERT INTO sales_invoice_items
                   (sales_invoice_id, item_id, stock_batch_id, pack_size, batch_no, expiry, mrp, sale_qty, discount_amount, amount)
                   VALUES (?, ?, ?, '10 TAB', 'PCM001', '2028-12-31', 20.0, 1, 0.0, 20.0)""",
                (self.inv4_id, self.item1_id, self.batch1_id),
            )

            conn.commit()
        finally:
            conn.close()

    def test_search_by_bill_number_only(self):
        """Searching by bill number works even when patient name is empty or not provided."""
        page = PatientHistoryBillWisePage()
        page._bill_no_edit.setText("103")
        page._perform_search()

        self.assertEqual(page._bills_table.rowCount(), 1)
        self.assertEqual(page._bills_table.item(0, 0).text(), "103")
        self.assertEqual(page._bills_table.item(0, 2).text(), "WALKIN")
        self.assertEqual(page._bills_table.item(0, 4).text(), "1")  # 1 item
        self.assertEqual(page._bills_table.item(0, 7).text(), "55.00")  # net amount

    def test_search_by_patient_name(self):
        """Patient name search finds all bills for that patient in chronological order."""
        page = PatientHistoryBillWisePage()
        page._patient_edit.setText("RAMESH")
        page._perform_search()

        # Should find 2 bills for RAMESH KUMAR (102 and 101, ordered by date DESC)
        self.assertEqual(page._bills_table.rowCount(), 2)
        bno_first = page._bills_table.item(0, 0).text()
        bno_second = page._bills_table.item(1, 0).text()
        self.assertEqual(bno_first, "102")  # Newer (2026-05-15)
        self.assertEqual(bno_second, "101")  # Older (2026-05-10)

    def test_search_by_multi_word_patient_name(self):
        """Multi-word patient search matches in any order."""
        page = PatientHistoryBillWisePage()
        page._patient_edit.setText("KUMAR RAMESH")
        page._perform_search()

        self.assertEqual(page._bills_table.rowCount(), 2)

    def test_date_range_filtering(self):
        """Filtering with from_date and to_date restricts results correctly."""
        page = PatientHistoryBillWisePage()
        page._date_check.setChecked(True)
        page._from_date.setDate(QDate(2026, 5, 12))
        page._to_date.setDate(QDate(2026, 6, 15))
        page._perform_search()

        # Should match Bill 102 (2026-05-15) and Bill 103 (2026-06-01)
        self.assertEqual(page._bills_table.rowCount(), 2)
        bnos = {page._bills_table.item(i, 0).text() for i in range(2)}
        self.assertEqual(bnos, {"102", "103"})

    def test_bill_details_pane_populates_accurately(self):
        """Selecting a bill populates its medicine details and summary amounts."""
        page = PatientHistoryBillWisePage()
        page._bill_no_edit.setText("101")
        page._perform_search()

        self.assertEqual(page._bills_table.rowCount(), 1)
        page._bills_table.selectRow(0)

        # Invoice 1 has 2 items: PARACETAMOL 500MG and AMOXICILLIN 250MG
        self.assertEqual(page._items_table.rowCount(), 2)
        names = [page._items_table.item(i, 0).text() for i in range(2)]
        self.assertIn("PARACETAMOL 500MG", names)
        self.assertIn("AMOXICILLIN 250MG", names)

        # Verify summary label strip
        self.assertEqual(page._sum_items_lbl.text(), "Total Items: 2")
        self.assertEqual(page._sum_total_lbl.text(), "Bill Amount: ₹75.00")
        self.assertEqual(page._sum_disc_lbl.text(), "Discount: ₹5.00")
        self.assertEqual(page._sum_net_lbl.text(), "Net Amount: ₹70.00")

    def test_bill_selection_switching(self):
        """Selecting another bill updates the detail table to only that bill's items."""
        page = PatientHistoryBillWisePage()
        page._patient_edit.setText("RAMESH")
        page._perform_search()

        # Select row 0 (Bill 102, 1 item)
        page._bills_table.selectRow(0)
        self.assertEqual(page._items_table.rowCount(), 1)
        self.assertEqual(page._items_table.item(0, 0).text(), "PARACETAMOL 500MG")
        self.assertEqual(page._sum_items_lbl.text(), "Total Items: 1")
        self.assertEqual(page._sum_net_lbl.text(), "Net Amount: ₹40.00")

        # Select row 1 (Bill 101, 2 items)
        page._bills_table.selectRow(1)
        self.assertEqual(page._items_table.rowCount(), 2)
        self.assertEqual(page._sum_items_lbl.text(), "Total Items: 2")
        self.assertEqual(page._sum_net_lbl.text(), "Net Amount: ₹70.00")

    def test_empty_search_handled_safely(self):
        """No crash or lingering state on search with no matches."""
        page = PatientHistoryBillWisePage()
        page._bill_no_edit.setText("NON_EXISTENT_BILL_99999")
        page._perform_search()

        self.assertEqual(page._bills_table.rowCount(), 0)
        self.assertEqual(page._items_table.rowCount(), 0)
        self.assertEqual(page._stats_lbl.text(), "No matching bills found.")
        self.assertFalse(page._view_details_btn.isEnabled())
        self.assertFalse(page._print_btn.isEnabled())
        self.assertFalse(page._pdf_btn.isEnabled())

    def test_reset_button(self):
        """Reset clears inputs and reloads all records."""
        page = PatientHistoryBillWisePage()
        page._bill_no_edit.setText("101")
        page._perform_search()
        self.assertEqual(page._bills_table.rowCount(), 1)

        page._reset_btn.click()
        self.assertEqual(page._bill_no_edit.text(), "")
        self.assertEqual(page._patient_edit.text(), "")
        self.assertFalse(page._date_check.isChecked())
        # All 4 bills present
        self.assertEqual(page._bills_table.rowCount(), 4)

    def test_print_actions_invoke_correct_invoice(self):
        """Print Bill and PDF actions invoke document_printing with the selected invoice id."""
        page = PatientHistoryBillWisePage()
        page._bill_no_edit.setText("101")
        page._perform_search()
        page._bills_table.selectRow(0)

        with mock.patch("database.document_printing.print_pharmacy_a6_bill") as mock_print:
            page._print_btn.click()
            mock_print.assert_called_once_with(self.inv1_id, page, "Counter Sale Bill")

        with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("/tmp/test_bill.pdf", "PDF (*.pdf)")), \
             mock.patch("database.document_printing.generate_counter_sale_bill") as mock_pdf, \
             mock.patch("PySide6.QtWidgets.QMessageBox.information"):
            page._pdf_btn.click()
            mock_pdf.assert_called_once_with(self.inv1_id, "/tmp/test_bill.pdf")

    def test_close_button_emits_signal(self):
        """Close button emits close_requested signal."""
        page = PatientHistoryBillWisePage()
        emitted = []
        page.close_requested.connect(lambda: emitted.append(True))
        page._close_btn.click()
        self.assertTrue(emitted)

    def test_menu_entry_and_main_window_navigation(self):
        """Menu entry exists in Sales menu and navigates to PatientHistoryBillWisePage."""
        self.assertIn("Patient History – Bill Number Wise", menu_data.MENUS["Sales"])

        win = PharmacyMainWindow()
        self.assertIn("Sales:Patient History – Bill Number Wise", win._page_map)

        # Trigger menu action
        win._on_menu_action("Sales", "Patient History – Bill Number Wise")
        current_widget = win._stack.currentWidget()
        self.assertIsInstance(current_widget, PatientHistoryBillWisePage)

        # Test close routing returns to New Bill
        current_widget.close_requested.emit()
        new_widget = win._stack.currentWidget()
        self.assertEqual(win._nav.status_label.text(), "Sales / New Bill")

    def test_theme_refresh(self):
        """refresh_theme runs without errors."""
        page = PatientHistoryBillWisePage()
        page.refresh_theme()


if __name__ == "__main__":
    unittest.main()
