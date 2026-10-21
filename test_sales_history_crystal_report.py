"""Tests for Sales History custom date filtering and Crystal Report preview & print.

Covers:
1. Financial Year box removed from visible filter layout; From Date and To Date pickers added in its place.
2. Backwards-compatibility attributes (_fy_combo, _date_check) preserved.
3. Date customization via From Date and To Date filters sales records correctly.
4. Crystal Report page generation (build_sales_history_report_pages) creates valid A4 landscape pages.
5. Column definitions (9 columns) and widths sum to 1053.0 px.
6. Grand Total calculations for Bill Total, Discount, Paid Amount, Net Amount.
7. SalesHistoryReportDialog provides viewer, print, and export capabilities.
8. Day Mode and Night Mode theme compatibility for all new widgets.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.company_dao import CompanyDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO
from database.unit_dao import UnitDAO
from database.account_roles import ensure_system_ledgers

from screens.sales_history import (
    SalesHistoryPage,
    SalesHistoryReportDialog,
    build_sales_history_report_pages,
)
from ui.crystal_report_viewer import (
    BlockKind,
    CONTENT_WIDTH_LANDSCAPE,
    PAGE_HEIGHT_LANDSCAPE,
    PAGE_WIDTH_LANDSCAPE,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
)
from ui import theme as theme_mod


class SalesHistoryCrystalReportTests(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_sales_history_cr.db")

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
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "items", "customers", "doctors", "suppliers", "units", "companies",
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        financial_year.ensure_default_financial_year()

        self.company_id = CompanyDAO.insert("TestPharma", "TP")
        self.unit_id = UnitDAO.insert("Strip")
        self.supplier_id = SupplierDAO.insert("MainSupplier")
        self.customer_id = CustomerDAO.insert("Customer Alpha")
        self.doctor_id = DoctorDAO.insert("Dr. Smith", specialty="Cardiology")

        self.item_id = ItemDAO.insert(
            item_name="Amoxicillin 500mg",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10x10",
        )
        ensure_system_ledgers()

        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2025-05-01", voucher_time="10:00",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="PINV-001", invoice_date="2025-05-01",
            invoice_net_amount=5000.0, bill_discount=0, due_date="",
            total_amount=5000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=5000.0, round_off=0,
            net_amount=5000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 200.0, "free_qty": 0, "batch_no": "BATCH-AMOX-01",
                "expiry": "12/28", "rate": 50.0, "mrp": 70.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 5000.0, "purchase_rate": 50.0,
                "net_rate": 50.0, "pp": 50.0,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertTrue(batches)
        self.batch_id = batches[0]["id"]

        self._patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _pump(self, n=3):
        for _ in range(n):
            self._app.processEvents()

    def _insert_sale(self, bill_no, sale_date, patient, total=100.0, disc=10.0, paid=90.0, net=90.0):
        return SalesDAO.insert_invoice(
            bill_no=bill_no,
            sale_date=sale_date,
            sale_time="12:00",
            sale_type="Cash",
            customer_id=self.customer_id,
            patient_name=patient,
            doctor_id=self.doctor_id,
            discount=disc,
            paid_amount=paid,
            total_amount=total,
            round_off=0.0,
            net_amount=net,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": self.batch_id,
                "pack_size": "10x10",
                "location": "A1",
                "batch_no": "BATCH-AMOX-01",
                "expiry": "12/28",
                "mrp": 70.0,
                "sale_qty": 1.0,
                "discount_amount": disc,
                "amount": net,
            }],
        )

    # ------------------------------------------------------------------
    # Test 1: UI filter bar structure (FY combo removed from visible row,
    # From and To date pickers added, backwards compatibility preserved).
    # ------------------------------------------------------------------
    def test_01_filter_bar_date_pickers_and_fy_removal(self):
        page = SalesHistoryPage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        # Backwards compatibility attributes exist
        self.assertTrue(hasattr(page, "_fy_combo"))
        self.assertTrue(hasattr(page, "_date_check"))
        self.assertTrue(hasattr(page, "_from_date"))
        self.assertTrue(hasattr(page, "_to_date"))
        self.assertTrue(hasattr(page, "_report_btn"))
        self.assertTrue(hasattr(page, "_footer_report_btn"))

        # From Date and To Date are visible and in the filter box layout
        self.assertTrue(page._from_date.isVisible())
        self.assertTrue(page._to_date.isVisible())
        self.assertEqual(page._from_date.displayFormat(), "dd/MM/yyyy")
        self.assertEqual(page._to_date.displayFormat(), "dd/MM/yyyy")
        self.assertTrue(page._from_date.calendarPopup())
        self.assertTrue(page._to_date.calendarPopup())

        # Financial Year box is NOT in the visible filter bar row
        # (It is retained as an internal attribute for compatibility)
        self.assertFalse(page._fy_combo.isVisible())

        # Print Report button exists on filter bar and footer
        self.assertEqual(page._report_btn.text(), "Print Report")
        self.assertEqual(page._footer_report_btn.text(), "Print Report")

    # ------------------------------------------------------------------
    # Test 2: Custom date filtering works as expected.
    # ------------------------------------------------------------------
    def test_02_custom_date_filtering(self):
        # Insert 3 sales on different dates
        id1 = self._insert_sale("B-01", "2026-05-10", "May Patient")
        id2 = self._insert_sale("B-02", "2026-06-15", "June Patient")
        id3 = self._insert_sale("B-03", "2026-07-20", "July Patient")

        page = SalesHistoryPage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        # By default, all 3 bills appear
        all_ids = [
            page._table.item(r, 0).data(Qt.UserRole)
            for r in range(page._table.rowCount())
        ]
        self.assertIn(id1, all_ids)
        self.assertIn(id2, all_ids)
        self.assertIn(id3, all_ids)

        # Customize date range to June only (2026-06-01 to 2026-06-30)
        page._date_check.setChecked(True)
        page._from_date.setDate(QDate(2026, 6, 1))
        page._to_date.setDate(QDate(2026, 6, 30))
        page._perform_search()
        self._pump()

        june_ids = [
            page._table.item(r, 0).data(Qt.UserRole)
            for r in range(page._table.rowCount())
        ]
        self.assertNotIn(id1, june_ids)
        self.assertIn(id2, june_ids)
        self.assertNotIn(id3, june_ids)

        # Reset returns all records
        page._on_reset_clicked()
        self._pump()
        reset_ids = [
            page._table.item(r, 0).data(Qt.UserRole)
            for r in range(page._table.rowCount())
        ]
        self.assertIn(id1, reset_ids)
        self.assertIn(id2, reset_ids)
        self.assertIn(id3, reset_ids)

    # ------------------------------------------------------------------
    # Test 3: Crystal Report page builder generates valid A4 landscape pages.
    # ------------------------------------------------------------------
    def test_03_crystal_report_page_builder(self):
        self._insert_sale("B-101", "2026-06-01", "Patient A", total=200.0, disc=20.0, paid=180.0, net=180.0)
        self._insert_sale("B-102", "2026-06-02", "Patient B", total=300.0, disc=30.0, paid=270.0, net=270.0)

        rows, total = SalesDAO.search_sales_history(limit=50)
        self.assertEqual(total, 2)

        pages = build_sales_history_report_pages(
            rows=rows,
            from_date="01/06/2026",
            to_date="02/06/2026",
            patient_filter="",
        )

        self.assertGreaterEqual(len(pages), 1)
        p1 = pages[0]
        self.assertEqual(p1.orientation, "landscape")
        self.assertEqual(p1.page_width, PAGE_WIDTH_LANDSCAPE)
        self.assertEqual(p1.page_height, PAGE_HEIGHT_LANDSCAPE)
        self.assertEqual(p1.header.header_line_1, "SALES HISTORY REPORT")
        self.assertIn("01/06/2026", p1.header.header_line_2)

        # Verify Table Header block (9 columns, sum of widths = 1053.0)
        tbl_hdr = [b for b in p1.blocks if b.kind == BlockKind.TABLE_HEADER][0]
        cols = tbl_hdr.data["columns"]
        self.assertEqual(len(cols), 9)
        self.assertEqual(cols[0], "Bill No")
        self.assertEqual(cols[1], "Date & Time")
        self.assertEqual(cols[2], "Patient Name")
        self.assertEqual(cols[3], "Doctor")
        self.assertEqual(cols[4], "Bill Total")
        self.assertEqual(cols[5], "Discount")
        self.assertEqual(cols[6], "Paid Amount")
        self.assertEqual(cols[7], "Net Amount")
        self.assertEqual(cols[8], "Pay Type")

        widths = tbl_hdr.data["widths"]
        self.assertAlmostEqual(sum(widths), CONTENT_WIDTH_LANDSCAPE, places=1)

        # Verify Data rows (2 data rows)
        data_rows = [b for b in p1.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 2)

        # Verify Grand Total row
        grand_totals = [b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL]
        self.assertEqual(len(grand_totals), 1)
        gt = grand_totals[0]
        custom_cells = gt.data["custom_cells"]
        # Total amounts: 200 + 300 = 500.0, disc: 20 + 30 = 50.0, paid: 180 + 270 = 450.0
        self.assertIn("2 Bills", custom_cells[0]["text"])
        self.assertEqual(custom_cells[1]["text"], "500.00")
        self.assertEqual(custom_cells[2]["text"], "50.00")
        self.assertEqual(custom_cells[3]["text"], "450.00")
        self.assertEqual(custom_cells[4]["text"], "450.00")

    # ------------------------------------------------------------------
    # Test 4: SalesHistoryReportDialog opens with viewer and print option.
    # ------------------------------------------------------------------
    def test_04_report_dialog_viewer_and_print(self):
        self._insert_sale("B-201", "2026-06-10", "Report Patient")
        rows, _ = SalesDAO.search_sales_history(limit=10)

        pages = build_sales_history_report_pages(
            rows=rows, from_date="10/06/2026", to_date="10/06/2026"
        )
        dlg = SalesHistoryReportDialog(pages)
        dlg.show()
        self._pump()
        self.addCleanup(lambda: (dlg.hide(), dlg.deleteLater()))

        self.assertIsNotNone(dlg.viewer)
        self.assertEqual(len(dlg._pages), len(pages))
        self.assertTrue(dlg.btn_print.isEnabled())
        self.assertTrue(dlg.btn_export.isEnabled())
        self.assertTrue(dlg.btn_close.isEnabled())

    # ------------------------------------------------------------------
    # Test 5: SalesHistoryPage _on_open_report triggers dialog.
    # ------------------------------------------------------------------
    def test_05_page_open_report_action(self):
        self._insert_sale("B-301", "2026-06-12", "Action Patient")
        page = SalesHistoryPage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        page._on_open_report()
        self._pump()

        dlg = getattr(page, "_report_dialog", None)
        self.assertIsNotNone(dlg)
        self.assertTrue(isinstance(dlg, SalesHistoryReportDialog))
        self.assertGreaterEqual(len(dlg._pages), 1)
        dlg.close()

    # ------------------------------------------------------------------
    # Test 6: Theme switching in Day Mode and Night Mode.
    # ------------------------------------------------------------------
    def test_06_theme_switching(self):
        page = SalesHistoryPage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        for mode in ("dark", "light", "dark", "light"):
            theme_mod.theme_manager.set_mode(mode, notify=False)
            page.refresh_theme()
            self._pump()

        self.assertTrue(page.isVisible())
        self.assertTrue(page._from_date.isVisible())
        self.assertTrue(page._to_date.isVisible())
        self.assertTrue(page._report_btn.isVisible())


if __name__ == "__main__":
    unittest.main()
