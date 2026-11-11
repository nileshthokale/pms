"""Unit & integration tests verifying that both sections of Patient Bill History:
1. Patient Bill History (screens/sales_history.py: SalesHistoryPage, SalesBillDetailsDialog)
2. Patient History Bill Wise (screens/patient_history_bill_wise.py: PatientHistoryBillWisePage)

use the exact same Crystal Report format, engine, and printing logic as Counter Sale
(database/counter_sale_a6_bill.py and reports/CounterSaleBill_A6.rpt).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.counter_sale_a6_bill import (
    CounterSaleBillA6PreviewDialog,
    REAL_RPT_FILE_PATH,
    generate_counter_sale_pdf,
    get_counter_sale_data,
    log_loaded_report_path,
    paginate_counter_sale_bill,
)
from screens.sales_history import SalesHistoryPage, SalesBillDetailsDialog
from screens.patient_history_bill_wise import PatientHistoryBillWisePage


class TestPatientBillHistoryCrystalReportPrint(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_patient_bill_history_print.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass
        os.environ["PHARMACY_DB"] = cls._DB_PATH

        if not QApplication.instance():
            cls._app = QApplication([])
        else:
            cls._app = QApplication.instance()

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO units (unit_name) VALUES ('10 TAB')")
            u_id = cur.lastrowid
            cur.execute("INSERT INTO companies (company_name, short_name) VALUES ('CIPLA PHARMA', 'CIPLA')")
            c_id = cur.lastrowid
            cur.execute("INSERT INTO doctors (doctor_name, phone_no) VALUES ('DR. A. P. SHAH', '9890011223')")
            doc_id = cur.lastrowid
            cur.execute("INSERT INTO customers (customer_name, address, contact_no) VALUES ('SURESH PATIL', 'PUNE', '9890044556')")
            cust1_id = cur.lastrowid
            cur.execute("INSERT INTO customers (customer_name, address, contact_no) VALUES ('MAHESH JOSHI', 'MUMBAI', '9890077889')")
            cust2_id = cur.lastrowid

            # Create items
            cur.execute("""
                INSERT INTO items (item_name, company_id, unit_id, pack_size, mrp, rate)
                VALUES ('PARACETAMOL 650MG', ?, ?, '10 TAB', 30.00, 25.00)
            """, (c_id, u_id))
            item1_id = cur.lastrowid

            cur.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (?, 'BATCH-P1', '2028-12-31', '10 TAB', 30.00, 100.0)
            """, (item1_id,))
            batch1_id = cur.lastrowid

            cur.execute("""
                INSERT INTO items (item_name, company_id, unit_id, pack_size, mrp, rate)
                VALUES ('AZITHROMYCIN 500MG', ?, ?, '3 TAB', 120.00, 100.00)
            """, (c_id, u_id))
            item2_id = cur.lastrowid

            cur.execute("""
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                VALUES (?, 'BATCH-A2', '2027-06-30', '3 TAB', 120.00, 50.0)
            """, (item2_id,))
            batch2_id = cur.lastrowid

            # Historical Bill 1 (Suresh Patil)
            cur.execute("""
                INSERT INTO sales_invoices (
                    bill_no, sale_date, sale_time, sale_type, customer_id, patient_name, doctor_id,
                    total_amount, discount, round_off, net_amount
                ) VALUES ('B-1001', '2026-06-10', '10:30:00', 'CASH', ?, 'SURESH PATIL', ?, 60.00, 5.00, 0.0, 55.00)
            """, (cust1_id, doc_id))
            cls.inv1_id = cur.lastrowid

            cur.execute("""
                INSERT INTO sales_invoice_items (
                    sales_invoice_id, item_id, stock_batch_id, pack_size, location,
                    batch_no, expiry, mrp, sale_qty, discount_amount, amount
                ) VALUES (?, ?, ?, '10 TAB', 'RACK-1', 'BATCH-P1', '12/28', 30.00, 2.0, 5.00, 55.00)
            """, (cls.inv1_id, item1_id, batch1_id))

            # Historical Bill 2 (Mahesh Joshi)
            cur.execute("""
                INSERT INTO sales_invoices (
                    bill_no, sale_date, sale_time, sale_type, customer_id, patient_name, doctor_id,
                    total_amount, discount, round_off, net_amount
                ) VALUES ('B-1002', '2026-06-15', '14:20:00', 'CASH', ?, 'MAHESH JOSHI', ?, 120.00, 10.00, 0.0, 110.00)
            """, (cust2_id, doc_id))
            cls.inv2_id = cur.lastrowid

            cur.execute("""
                INSERT INTO sales_invoice_items (
                    sales_invoice_id, item_id, stock_batch_id, pack_size, location,
                    batch_no, expiry, mrp, sale_qty, discount_amount, amount
                ) VALUES (?, ?, ?, '3 TAB', 'RACK-2', 'BATCH-A2', '06/27', 120.00, 1.0, 10.00, 110.00)
            """, (cls.inv2_id, item2_id, batch2_id))

            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass

    def test_crystal_report_template_exists(self):
        """Verify the exact Counter Sale Crystal Report template exists and is referenced."""
        self.assertTrue(os.path.isfile(REAL_RPT_FILE_PATH))
        self.assertTrue(REAL_RPT_FILE_PATH.endswith("CounterSaleBill_A6.rpt"))
        self.assertEqual(log_loaded_report_path(), REAL_RPT_FILE_PATH)

    def test_bill_data_retrieval_and_isolation(self):
        """Verify get_counter_sale_data and paginate_counter_sale_bill accurately isolate historical bills."""
        # Bill 1
        head1, items1 = get_counter_sale_data(self.inv1_id)
        self.assertEqual(head1["bill_no"], "B-1001")
        self.assertEqual(head1["customer_name"], "SURESH PATIL")
        self.assertEqual(len(items1), 1)
        self.assertEqual(items1[0]["item_name"], "PARACETAMOL 650MG")
        self.assertEqual(items1[0]["batch_no"], "BATCH-P1")
        self.assertEqual(float(head1["net_amount"]), 55.00)

        # Bill 2
        head2, items2 = get_counter_sale_data(self.inv2_id)
        self.assertEqual(head2["bill_no"], "B-1002")
        self.assertEqual(head2["customer_name"], "MAHESH JOSHI")
        self.assertEqual(len(items2), 1)
        self.assertEqual(items2[0]["item_name"], "AZITHROMYCIN 500MG")
        self.assertEqual(items2[0]["batch_no"], "BATCH-A2")
        self.assertEqual(float(head2["net_amount"]), 110.00)

        # Pagination for Bill 1
        pages1 = paginate_counter_sale_bill(self.inv1_id)
        self.assertEqual(len(pages1), 1)
        self.assertEqual(pages1[0]["head"]["bill_no"], "B-1001")
        self.assertEqual(pages1[0]["head"]["customer_name"], "SURESH PATIL")
        self.assertEqual(float(pages1[0]["head"]["net_amount"]), 55.00)

    def test_sales_history_page_print_and_pdf(self):
        """Verify SalesHistoryPage buttons trigger Counter Sale preview and PDF generator."""
        page = SalesHistoryPage()
        page._patient_edit.setText("SURESH PATIL")
        page._perform_search()

        self.assertGreaterEqual(page._table.rowCount(), 1)
        # Select the row for Suresh Patil
        selected_row = None
        for r in range(page._table.rowCount()):
            item = page._table.item(r, 0)
            if item and item.data(Qt.UserRole) == self.inv1_id:
                selected_row = r
                break
        self.assertIsNotNone(selected_row)
        page._table.selectRow(selected_row)
        self.assertEqual(page._selected_invoice_id(), self.inv1_id)

        # Verify Print button launches CounterSaleBillA6PreviewDialog
        with mock.patch("screens.sales_history.CounterSaleBillA6PreviewDialog") as mock_preview:
            mock_dlg = mock.MagicMock()
            mock_preview.return_value = mock_dlg
            page._print_btn.click()
            mock_preview.assert_called_once_with(self.inv1_id, parent=page)
            mock_dlg.exec.assert_called_once()

        # Verify PDF button calls generate_counter_sale_pdf
        with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("/tmp/b1001.pdf", "PDF (*.pdf)")), \
             mock.patch("screens.sales_history.generate_counter_sale_pdf") as mock_pdf, \
             mock.patch("PySide6.QtWidgets.QMessageBox.information"):
            page._save_pdf_btn.click()
            mock_pdf.assert_called_once_with(self.inv1_id, "/tmp/b1001.pdf")

    def test_sales_bill_details_dialog_print_and_pdf(self):
        """Verify SalesBillDetailsDialog buttons trigger Counter Sale preview and PDF generator."""
        dlg = SalesBillDetailsDialog(self.inv2_id)

        # Verify direct print launches CounterSaleBillA6PreviewDialog with self.inv2_id
        with mock.patch("screens.sales_history.CounterSaleBillA6PreviewDialog") as mock_preview:
            mock_sub_dlg = mock.MagicMock()
            mock_preview.return_value = mock_sub_dlg
            dlg._direct_print_btn.click()
            mock_preview.assert_called_once_with(self.inv2_id, parent=dlg)
            mock_sub_dlg.exec.assert_called_once()

        # Verify save PDF calls generate_counter_sale_pdf with self.inv2_id
        with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("/tmp/b1002.pdf", "PDF (*.pdf)")), \
             mock.patch("screens.sales_history.generate_counter_sale_pdf") as mock_pdf, \
             mock.patch("PySide6.QtWidgets.QMessageBox.information"):
            dlg._save_pdf_btn.click()
            mock_pdf.assert_called_once_with(self.inv2_id, "/tmp/b1002.pdf")

    def test_patient_history_bill_wise_page_print_and_pdf(self):
        """Verify PatientHistoryBillWisePage buttons trigger Counter Sale preview and PDF generator."""
        page = PatientHistoryBillWisePage()
        page._bill_no_edit.setText("B-1002")
        page._perform_search()

        self.assertEqual(page._bills_table.rowCount(), 1)
        page._bills_table.selectRow(0)
        self.assertEqual(page._selected_invoice_id(), self.inv2_id)

        # Verify Print button launches CounterSaleBillA6PreviewDialog
        with mock.patch("screens.patient_history_bill_wise.CounterSaleBillA6PreviewDialog") as mock_preview:
            mock_dlg = mock.MagicMock()
            mock_preview.return_value = mock_dlg
            page._print_btn.click()
            mock_preview.assert_called_once_with(self.inv2_id, parent=page)
            mock_dlg.exec.assert_called_once()

        # Verify PDF button calls generate_counter_sale_pdf
        with mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("/tmp/b1002_billwise.pdf", "PDF (*.pdf)")), \
             mock.patch("screens.patient_history_bill_wise.generate_counter_sale_pdf") as mock_pdf, \
             mock.patch("PySide6.QtWidgets.QMessageBox.information"):
            page._pdf_btn.click()
            mock_pdf.assert_called_once_with(self.inv2_id, "/tmp/b1002_billwise.pdf")

    def test_actual_pdf_generation_matches_counter_sale(self):
        """Verify generate_counter_sale_pdf actually generates a valid PDF without altering bill data."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        try:
            out = generate_counter_sale_pdf(self.inv1_id, pdf_path)
            self.assertEqual(out, pdf_path)
            self.assertTrue(os.path.exists(pdf_path))
            self.assertGreater(os.path.getsize(pdf_path), 500)
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)


if __name__ == "__main__":
    unittest.main()
