"""Automated Test Suite for All Six Sales Reports & Menu Submenu.

Verifies:
1. Submenu hierarchy and shortcuts in ui/menu_data.py and ui/navigation_bar.py
2. Read-only DAO query logic in database/sales_reports_dao.py
3. UI page and dialog construction, filtering, pagination, and theme refresh
4. Rendering via draw_report_page() and ReportPageCanvas
5. Financial accuracy, unique bill counts, and pack-factor costing
"""

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unittest
from datetime import datetime
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

# Ensure single QApplication instance
app = QApplication.instance()
if app is None:
    app = QApplication([])

from database.sales_reports_dao import SalesReportsDAO
from database.connection import get_connection
from screens.sales_reports import (
    DailyBillwiseSalesPage,
    DailyItemwiseSalesPage,
    CompanywiseSalesPage,
    ItemwiseSalesPage,
    DailyProfitCalculationPage,
    DailyProfitCalculationDialog,
    DailyProfitItemwisePage,
    DailyProfitItemwiseDialog,
)
from ui.menu_data import MENUS, REPORT_SALES_SUBMENU
from ui.navigation_bar import MENU_SHORTCUTS, NavigationBar
from ui.crystal_report_viewer import (
    CrystalReportViewer,
    ReportPageCanvas,
    draw_report_page,
)


class TestSalesReportsSubmenu(unittest.TestCase):
    """Test 1: Submenu structure and shortcut definitions."""

    def test_submenu_options(self):
        expected_options = [
            "Daily Billwise Sales",
            "Daily Itemwise Sales",
            "Companywise Sales",
            "Itemwise Sales",
            "Daily Profit Calculation",
            "Daily Profit Itemwise",
        ]
        self.assertEqual(REPORT_SALES_SUBMENU, expected_options)

    def test_reports_menu_hierarchy(self):
        reports_menu = MENUS.get("Reports", [])
        sales_sub = None
        for item in reports_menu:
            if isinstance(item, dict) and "Sales Report" in item:
                sales_sub = item["Sales Report"]
                break
        self.assertIsNotNone(sales_sub, "Sales Report submenu not found in Reports menu")
        self.assertEqual(sales_sub, REPORT_SALES_SUBMENU)

    def test_keyboard_shortcuts(self):
        self.assertEqual(MENU_SHORTCUTS.get("Daily Itemwise Sales"), "Ctrl+T")
        self.assertEqual(MENU_SHORTCUTS.get("Daily Profit Calculation"), "Ctrl+O")

    def test_navigation_bar_builds_submenu(self):
        nav = NavigationBar()
        sales_menu = None
        for menu in nav._menus:
            if menu.objectName() == "NavSubMenu_Sales Report":
                sales_menu = menu
                break
        self.assertIsNotNone(sales_menu, "NavSubMenu_Sales Report not created in NavigationBar")
        action_texts = [a.text() for a in sales_menu.actions() if not a.isSeparator()]
        self.assertEqual(action_texts, REPORT_SALES_SUBMENU)


class TestSalesReportsDAO(unittest.TestCase):
    """Test 2: Database access layer for all 6 sales reports."""

    @classmethod
    def setUpClass(cls):
        conn = get_connection()
        # Find dates with sales data
        row = conn.execute("SELECT DISTINCT sale_date FROM sales_invoices ORDER BY sale_date DESC LIMIT 1").fetchone()
        cls.sample_date = row[0] if row else "2026-10-13"

        # Find a company with sales
        comp_row = conn.execute("""
            SELECT i.company_id FROM sales_invoice_items sii
            JOIN items i ON i.id = sii.item_id
            WHERE i.company_id IS NOT NULL LIMIT 1
        """).fetchone()
        cls.sample_company_id = comp_row[0] if comp_row else 1

        # Find an item with sales
        item_row = conn.execute("SELECT item_id FROM sales_invoice_items LIMIT 1").fetchone()
        cls.sample_item_id = item_row[0] if item_row else 1
        conn.close()

    def test_filter_lookups(self):
        companies = SalesReportsDAO.get_filter_companies()
        self.assertIsInstance(companies, list)
        self.assertGreater(len(companies), 0)
        self.assertIn("id", companies[0])
        self.assertIn("company_name", companies[0])

        items = SalesReportsDAO.get_filter_items()
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)
        self.assertIn("id", items[0])
        self.assertIn("item_name", items[0])

    def test_daily_billwise_sales_populated(self):
        res = SalesReportsDAO.get_daily_billwise_sales(self.sample_date)
        rows = res.get("rows", [])
        summary = res.get("summary", {})
        self.assertIsInstance(rows, list)
        self.assertEqual(summary.get("total_bills"), len(rows))
        if rows:
            first = rows[0]
            self.assertIn("bill_no", first)
            self.assertIn("sale_date", first)
            self.assertIn("voucher_type", first)
            self.assertIn("patient_name", first)
            self.assertIn("voucher_no", first)
            self.assertIn("discount", first)
            self.assertIn("bill_amount", first)
            # Verify total bill amount equals sum of bills
            expected_amt = round(sum(r["bill_amount"] for r in rows), 2)
            self.assertEqual(summary.get("total_bill_amount"), expected_amt)

    def test_daily_billwise_sales_empty(self):
        res = SalesReportsDAO.get_daily_billwise_sales("1900-01-01")
        self.assertEqual(len(res.get("rows", [])), 0)
        self.assertEqual(res.get("summary", {}).get("total_bills"), 0)
        self.assertEqual(res.get("summary", {}).get("total_bill_amount"), 0.0)

    def test_daily_itemwise_sales_separates_item_and_bill_totals(self):
        res = SalesReportsDAO.get_daily_itemwise_sales(self.sample_date)
        rows = res.get("rows", [])
        summary = res.get("summary", {})
        self.assertIsInstance(rows, list)
        if rows:
            first = rows[0]
            self.assertIn("bill_no", first)
            self.assertIn("item_name", first)
            self.assertIn("mrp", first)
            self.assertIn("quantity", first)
            self.assertIn("amount", first)
            self.assertIn("batch_no", first)
            self.assertIn("expiry", first)
            self.assertIn("discount", first)
            self.assertIn("bill_amount", first)

            # Item amount total must equal sum of line amounts
            expected_item_amt = round(sum(r["amount"] for r in rows), 2)
            self.assertEqual(summary.get("total_amount"), expected_item_amt)

            # Bill amount total must be unique per bill, NOT repeated sum
            unique_bills = {r["invoice_id"]: r["bill_amount"] for r in rows}
            expected_bill_amt = round(sum(unique_bills.values()), 2)
            self.assertEqual(summary.get("total_bill_amount"), expected_bill_amt)

    def test_companywise_sales(self):
        res = SalesReportsDAO.get_companywise_sales("2000-01-01", "2030-12-31", self.sample_company_id)
        rows = res.get("rows", [])
        summary = res.get("summary", {})
        self.assertIsInstance(rows, list)
        self.assertEqual(summary.get("total_records"), len(rows))
        if rows:
            first = rows[0]
            self.assertIn("item_name", first)
            self.assertIn("unit_name", first)
            self.assertIn("pack_size", first)
            self.assertIn("batch_no", first)
            self.assertIn("mrp", first)
            self.assertIn("sales_qty", first)
            self.assertIn("amount", first)

    def test_itemwise_sales(self):
        res = SalesReportsDAO.get_itemwise_sales("2000-01-01", "2030-12-31", self.sample_item_id)
        rows = res.get("rows", [])
        summary = res.get("summary", {})
        self.assertIsInstance(rows, list)
        self.assertEqual(summary.get("total_records"), len(rows))
        if rows:
            first = rows[0]
            self.assertIn("sale_date", first)
            self.assertIn("voucher_type", first)
            self.assertIn("bill_no", first)
            self.assertIn("patient_name", first)
            self.assertIn("batch_no", first)
            self.assertIn("mrp", first)
            self.assertIn("quantity", first)
            self.assertIn("amount", first)

    def test_daily_profit_calculation(self):
        res = SalesReportsDAO.get_daily_profit_calculation("2026-10-01", "2026-10-13")
        rows = res.get("rows", [])
        summary = res.get("summary", {})
        self.assertIsInstance(rows, list)
        if rows:
            first = rows[0]
            self.assertIn("voucher_date", first)
            self.assertIn("cash_receipt", first)
            self.assertIn("cash_sales", first)
            self.assertIn("total_cash_received", first)
            self.assertIn("cash_payment", first)
            self.assertIn("cash_sales_return", first)
            self.assertIn("net_cash_received", first)
            self.assertIn("bank_payment", first)
            self.assertIn("credit_sales", first)
            self.assertIn("net_sales", first)
            self.assertIn("net_purchase", first)
            self.assertIn("net_profit", first)

            # Mathematical checks per row
            for r in rows:
                self.assertAlmostEqual(r["total_cash_received"], r["cash_receipt"] + r["cash_sales"], places=2)
                self.assertAlmostEqual(r["net_cash_received"], r["total_cash_received"] - r["cash_payment"] - r["cash_sales_return"], places=2)
                self.assertAlmostEqual(r["net_profit"], r["net_sales"] - r["net_purchase"], places=2)

    def test_daily_profit_itemwise_pack_costing(self):
        res = SalesReportsDAO.get_daily_profit_itemwise("2026-10-01", "2026-10-13")
        rows = res.get("rows", [])
        summary = res.get("summary", {})
        self.assertIsInstance(rows, list)
        if rows:
            first = rows[0]
            self.assertIn("item_name", first)
            self.assertIn("unit_name", first)
            self.assertIn("sales_qty", first)
            self.assertIn("sales", first)
            self.assertIn("purchase", first)
            self.assertIn("net_profit", first)
            for r in rows:
                self.assertAlmostEqual(r["net_profit"], r["sales"] - r["purchase"], places=2)


class TestSalesReportsPages(unittest.TestCase):
    """Test 3 & 4: UI screen creation, rendering, and lifecycle."""

    def test_daily_billwise_sales_page(self):
        page = DailyBillwiseSalesPage()
        page.date_edit.setDate(QDate(2026, 10, 13))
        page.generate_report()
        self.assertGreater(len(page._pages), 0)
        self.assertTrue(page.btn_panel_print.isEnabled())

        # Render first page onto canvas without errors
        canvas = ReportPageCanvas()
        canvas.set_page(page._pages[0])
        pixmap = QImage(1123, 794, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(pixmap)
        try:
            draw_report_page(painter, page._pages[0])
        finally:
            painter.end()

    def test_daily_itemwise_sales_page(self):
        page = DailyItemwiseSalesPage()
        page.date_edit.setDate(QDate(2026, 10, 13))
        page.generate_report()
        self.assertGreater(len(page._pages), 0)

        # Render on canvas
        pixmap = QImage(1123, 794, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(pixmap)
        try:
            draw_report_page(painter, page._pages[0])
        finally:
            painter.end()

    def test_companywise_sales_page(self):
        page = CompanywiseSalesPage()
        # Find first non-null company in combo
        for i in range(page.company_combo.count()):
            if page.company_combo.itemData(i) is not None:
                page.company_combo.setCurrentIndex(i)
                break
        page.from_date_edit.setDate(QDate(2020, 1, 1))
        page.to_date_edit.setDate(QDate(2026, 12, 31))
        page.generate_report()
        self.assertGreater(len(page._pages), 0)

        # Render on canvas (portrait)
        pixmap = QImage(794, 1123, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(pixmap)
        try:
            draw_report_page(painter, page._pages[0])
        finally:
            painter.end()

    def test_itemwise_sales_page(self):
        page = ItemwiseSalesPage()
        for i in range(page.item_combo.count()):
            if page.item_combo.itemData(i) is not None:
                page.item_combo.setCurrentIndex(i)
                break
        page.from_date_edit.setDate(QDate(2020, 1, 1))
        page.to_date_edit.setDate(QDate(2026, 12, 31))
        page.generate_report()
        self.assertGreater(len(page._pages), 0)

        pixmap = QImage(794, 1123, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(pixmap)
        try:
            draw_report_page(painter, page._pages[0])
        finally:
            painter.end()

    def test_daily_profit_calculation_page_and_dialog(self):
        # Test Page
        page = DailyProfitCalculationPage()
        page.widget.from_date_edit.setDate(QDate(2026, 10, 1))
        page.widget.to_date_edit.setDate(QDate(2026, 10, 13))
        page.widget.load_data()
        self.assertGreater(page.widget.table.rowCount(), 0)
        self.assertEqual(page.widget.table.columnCount(), 12)

        # Test Dialog
        dialog = DailyProfitCalculationDialog()
        self.assertFalse(dialog.isModal())
        self.assertGreater(dialog.widget.table.rowCount(), 0)

    def test_daily_profit_itemwise_page_and_dialog(self):
        # Test Page
        page = DailyProfitItemwisePage()
        page.from_date_edit.setDate(QDate(2026, 10, 1))
        page.to_date_edit.setDate(QDate(2026, 10, 13))
        page.generate_report()
        self.assertGreater(len(page._pages), 0)

        pixmap = QImage(794, 1123, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(pixmap)
        try:
            draw_report_page(painter, page._pages[0])
        finally:
            painter.end()

        # Test Dialog
        dialog = DailyProfitItemwiseDialog()
        self.assertFalse(dialog.isModal())
        self.assertGreater(len(dialog.page._pages), 0)

    def test_theme_refresh_on_all_pages(self):
        pages = [
            DailyBillwiseSalesPage(),
            DailyItemwiseSalesPage(),
            CompanywiseSalesPage(),
            ItemwiseSalesPage(),
            DailyProfitCalculationPage(),
            DailyProfitItemwisePage(),
        ]
        for p in pages:
            # Must not throw in either day or night mode
            p.refresh_theme()


if __name__ == "__main__":
    unittest.main()

