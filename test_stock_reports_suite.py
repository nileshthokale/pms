"""Comprehensive Test Suite for Pharmacy Stock Reports (Crystal Reports Style).

Verifies:
1. Reports Menu & Navigation:
   - REPORT_STOCK_SUBMENU in ui/menu_data.py has exactly the 4 stock reports.
   - MENUS["Reports"] has "Stock Report" submenu; siblings (Sales Report, Purchase Report, Expiry, Party Wise, GST, Ledger) intact.
   - NavigationBar creates QMenu for Stock Report with the 4 options.
   - Triggering each option emits menu_action_triggered("Reports", action).
   - PharmacyMainWindow routes each of the 4 actions to its own dedicated page class:
     * "Items (All) Stock" -> ItemsAllStockPage
     * "Companywise Item Stock" -> CompanywiseItemStockPage
     * "Expired Item List" -> ExpiredItemListPage
     * "Item List" -> ItemListPage
   - Each screen is distinct and not routed to a generic page.
   - Close button emits close_requested.

2. Database / DAO Calculations:
   - ItemsAllStock: BalQty, PurQty, SaleQty, NetRate, Pur.Value calculation.
   - Near-expiry and expired filters behavior.
   - CompanywiseItemStock: Stock, NetRate, Pur.Value, MRP, SalesValue.
   - ExpiredItemStock: Only expired batches returned.
   - ItemList: Master items included (even zero balance), Rate, MRP, BalQty.

3. UI Layout & Controls:
   - ItemsAllStockPage: Near to Expiry Days spinbox, Expired Items Includes checkbox, Show Report button, hint callout.
   - CompanywiseItemStockPage: Company searchable dropdown, Show Report button, item subtotals.
   - ExpiredItemListPage: Expired Days spinbox, Show Report button.
   - ItemListPage: Optional Company filter, Show Report button, item count summary.

4. Viewer Features & Theming:
   - CrystalReportViewer pagination, blocks, and rendering.
   - Export PDF and Print execution without errors.
   - Day Mode and Night Mode theme switching.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QPushButton, QMenu, QWidget

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.stock_reports_dao import StockReportsDAO
from ui.menu_data import (
    MENUS,
    REPORT_STOCK_SUBMENU,
    REPORT_SALES_SUBMENU,
    REPORT_PURCHASE_SUBMENU,
    REPORT_LEDGER_SUBMENU,
    SubmenuDict,
)
from ui.navigation_bar import NavigationBar
from ui.main_window import PharmacyMainWindow
import screens
from screens.stock_reports import (
    ItemsAllStockPage,
    CompanywiseItemStockPage,
    ExpiredItemListPage,
    ItemListPage,
    fmt_qty_dash,
    paginate_stock_blocks,
)
from ui.crystal_report_viewer import (
    BlockKind,
    ReportBlock,
    ReportHeaderData,
    fmt_amt,
    fmt_qty,
)
import ui.theme as theme


class TestStockReportsSuite(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_stock_reports_suite.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        cls._seed_test_data()

        cls.app = QApplication.instance() or QApplication([])
        cls.win = PharmacyMainWindow()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win.deleteLater()
        if cls.app:
            cls.app.processEvents()
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass

    @classmethod
    def _seed_test_data(cls):
        conn = get_connection()
        cur = conn.cursor()

        # Seed Companies
        cur.execute("INSERT INTO companies (company_name, short_name) VALUES ('CIPLA LTD', 'CIP')")
        cls.comp1_id = cur.lastrowid
        cur.execute("INSERT INTO companies (company_name, short_name) VALUES ('SUN PHARMA', 'SUN')")
        cls.comp2_id = cur.lastrowid

        # Seed Units
        cur.execute("INSERT INTO units (unit_name) VALUES ('STRIP 10T')")
        cls.unit_strip_id = cur.lastrowid
        cur.execute("INSERT INTO units (unit_name) VALUES ('BOTTLE')")
        cls.unit_bot_id = cur.lastrowid

        # Seed Items
        cur.execute(
            """INSERT INTO items (item_name, company_id, unit_id, pack_size, rate, mrp)
               VALUES ('PARACETAMOL 500MG', ?, ?, '10', 15.00, 25.00)""",
            (cls.comp1_id, cls.unit_strip_id),
        )
        cls.item1_id = cur.lastrowid

        cur.execute(
            """INSERT INTO items (item_name, company_id, unit_id, pack_size, rate, mrp)
               VALUES ('AMOXICILLIN 250MG', ?, ?, '10', 30.00, 50.00)""",
            (cls.comp1_id, cls.unit_strip_id),
        )
        cls.item2_id = cur.lastrowid

        cur.execute(
            """INSERT INTO items (item_name, company_id, unit_id, pack_size, rate, mrp)
               VALUES ('COUGH SYRUP 100ML', ?, ?, '1', 40.00, 65.00)""",
            (cls.comp2_id, cls.unit_bot_id),
        )
        cls.item3_id = cur.lastrowid

        # Item with zero stock
        cur.execute(
            """INSERT INTO items (item_name, company_id, unit_id, pack_size, rate, mrp)
               VALUES ('ZERO STOCK TABLET', ?, ?, '10', 10.00, 20.00)""",
            (cls.comp2_id, cls.unit_strip_id),
        )
        cls.item_zero_id = cur.lastrowid

        # Seed Batches
        # Batch 1: Future expiry (active stock)
        future_exp = (date.today() + timedelta(days=365)).strftime("%Y-%m-%d")
        cur.execute(
            """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
               VALUES (?, 'BATCH-001', ?, '10', 15.00, 15.00, 25.00, 100)""",
            (cls.item1_id, future_exp),
        )
        cls.batch1_id = cur.lastrowid

        # Batch 2: Near expiry (15 days)
        near_exp = (date.today() + timedelta(days=15)).strftime("%Y-%m-%d")
        cur.execute(
            """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
               VALUES (?, 'BATCH-002', ?, '10', 15.00, 15.00, 25.00, 50)""",
            (cls.item1_id, near_exp),
        )
        cls.batch2_id = cur.lastrowid

        # Batch 3: Expired batch (-30 days)
        expired_exp = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        cur.execute(
            """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
               VALUES (?, 'BATCH-EXP', ?, '10', 30.00, 30.00, 50.00, 30)""",
            (cls.item2_id, expired_exp),
        )
        cls.batch3_id = cur.lastrowid

        # Batch 4: Sun pharma syrup
        cur.execute(
            """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
               VALUES (?, 'BATCH-SYR', ?, '1', 40.00, 40.00, 65.00, 20)""",
            (cls.item3_id, future_exp),
        )
        cls.batch4_id = cur.lastrowid

        conn.commit()

    # ══════════════════════════════════════════════════════════════════
    # Part 1: Menu & Navigation Structure Tests
    # ══════════════════════════════════════════════════════════════════

    def test_01_menu_data_stock_report_submenu(self):
        """Verifies REPORT_STOCK_SUBMENU list and MENUS['Reports'] structure."""
        expected_options = [
            "Items (All) Stock",
            "Companywise Item Stock",
            "Expired Item List",
            "Item List",
        ]
        self.assertEqual(REPORT_STOCK_SUBMENU, expected_options)

        reports = MENUS["Reports"]
        stock_item = reports[2]
        self.assertIsInstance(stock_item, dict)
        self.assertIn("Stock Report", stock_item)
        self.assertEqual(stock_item["Stock Report"], expected_options)
        # Backward compatibility with string matching
        self.assertEqual(stock_item, "Stock Report")

    def test_02_reports_siblings_preserved(self):
        """Ensures sibling report menus remain undisturbed."""
        reports = MENUS["Reports"]
        self.assertEqual(len(reports), 8)
        self.assertEqual(reports[0], "Sales Report")
        self.assertEqual(reports[1], "Purchase Report")
        self.assertEqual(reports[2], "Stock Report")
        self.assertEqual(reports[3], "Doctor's Reports")
        self.assertEqual(reports[4], "Expiry Report")
        self.assertEqual(reports[5], "Party Wise Report")
        self.assertEqual(reports[6], "GST Report")
        self.assertIn("Ledger", reports[7])

    def test_03_navigation_bar_builds_stock_report_submenu(self):
        """NavigationBar creates a nested QMenu for Stock Report containing the 4 options."""
        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        reports_menu = reports_btn.menu()
        self.assertIsNotNone(reports_menu)

        actions = reports_menu.actions()
        action_texts = [a.text() for a in actions]
        self.assertEqual(
            action_texts,
            [
                "Sales Report",
                "Purchase Report",
                "Stock Report",
                "Doctor's Reports",
                "Expiry Report",
                "Party Wise Report",
                "GST Report",
                "Ledger",
            ],
        )

        stock_action = actions[2]
        self.assertEqual(stock_action.text(), "Stock Report")
        submenu = stock_action.menu()
        self.assertIsNotNone(submenu, "Stock Report must have an attached QMenu submenu")

        sub_actions = [a.text() for a in submenu.actions() if not a.isSeparator()]
        self.assertEqual(
            sub_actions,
            [
                "Items (All) Stock",
                "Companywise Item Stock",
                "Expired Item List",
                "Item List",
            ],
        )

    def test_04_submenu_signals_emit_correct_actions(self):
        """NavigationBar emits menu_action_triggered('Reports', sub_action) for each option."""
        nav = NavigationBar()
        received = []
        nav.menu_action_triggered.connect(lambda m, a: received.append((m, a)))

        reports_btn = next(
            btn for btn in nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        stock_action = next(a for a in reports_btn.menu().actions() if a.text() == "Stock Report")
        submenu = stock_action.menu()
        self.assertIsNotNone(submenu)

        expected = [
            "Items (All) Stock",
            "Companywise Item Stock",
            "Expired Item List",
            "Item List",
        ]
        for a in submenu.actions():
            if not a.isSeparator():
                a.trigger()

        self.assertEqual(received, [("Reports", name) for name in expected])

    def test_05_main_window_navigates_to_distinct_screens(self):
        """Every Stock Report option routes to its own dedicated page class, not a generic page."""
        # 1. Items (All) Stock
        self.win._on_menu_action("Reports", "Items (All) Stock")
        curr = self.win._stack.currentWidget()
        self.assertIsInstance(curr, ItemsAllStockPage)
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Items (All) Stock")

        # 2. Companywise Item Stock
        self.win._on_menu_action("Reports", "Companywise Item Stock")
        curr = self.win._stack.currentWidget()
        self.assertIsInstance(curr, CompanywiseItemStockPage)
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Companywise Item Stock")

        # 3. Expired Item List
        self.win._on_menu_action("Reports", "Expired Item List")
        curr = self.win._stack.currentWidget()
        self.assertIsInstance(curr, ExpiredItemListPage)
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Expired Item List")

        # 4. Item List
        self.win._on_menu_action("Reports", "Item List")
        curr = self.win._stack.currentWidget()
        self.assertIsInstance(curr, ItemListPage)
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Item List")

    def test_06_close_button_returns_to_sales(self):
        """Clicking close '✕' on stock report navigates to New Bill."""
        self.win._on_menu_action("Reports", "Items (All) Stock")
        page = self.win._stack.currentWidget()
        self.assertIsInstance(page, ItemsAllStockPage)

        page.btn_close.click()
        self.assertEqual(self.win._nav.status_label.text(), "Sales / New Bill")

    # ══════════════════════════════════════════════════════════════════
    # Part 2: Database / DAO Calculation Tests
    # ══════════════════════════════════════════════════════════════════

    def test_07_dao_items_all_stock_calculations(self):
        """DAO get_items_all_stock correctly calculates quantities, NetRate, and Pur.Value."""
        # include_expired=False, near_expiry_days=0 -> active batches (BATCH-001, BATCH-002, BATCH-SYR)
        rows = StockReportsDAO.get_items_all_stock(near_expiry_days=0, include_expired=False)
        self.assertGreaterEqual(len(rows), 3)

        b1 = next(r for r in rows if r["batch_no"] == "BATCH-001")
        self.assertEqual(b1["bal_qty"], 100.0)
        self.assertEqual(b1["pur_qty"], 100.0)
        self.assertEqual(b1["sale_qty"], 0.0)
        self.assertEqual(b1["net_rate"], 15.0)
        # Pur.Value = 100 * 15.00 / 10 = 150.00
        self.assertAlmostEqual(b1["pur_value"], 150.0, places=2)

        # Syrian batch pack_size=1
        b_syr = next(r for r in rows if r["batch_no"] == "BATCH-SYR")
        self.assertEqual(b_syr["bal_qty"], 20.0)
        # Pur.Value = 20 * 40.00 / 1 = 800.00
        self.assertAlmostEqual(b_syr["pur_value"], 800.0, places=2)

    def test_08_dao_items_all_stock_expired_toggle(self):
        """DAO include_expired=True includes expired batches; False excludes them."""
        active_rows = StockReportsDAO.get_items_all_stock(near_expiry_days=0, include_expired=False)
        all_rows = StockReportsDAO.get_items_all_stock(near_expiry_days=0, include_expired=True)

        active_batches = [r["batch_no"] for r in active_rows]
        all_batches = [r["batch_no"] for r in all_rows]

        self.assertNotIn("BATCH-EXP", active_batches)
        self.assertIn("BATCH-EXP", all_batches)
        self.assertEqual(len(all_rows), len(active_rows) + 1)

    def test_09_dao_items_all_stock_near_expiry_filter(self):
        """DAO near_expiry_days filters batches expiring within N days."""
        # 10 days: BATCH-002 is 15 days out -> should be excluded
        rows_10 = StockReportsDAO.get_items_all_stock(near_expiry_days=10, include_expired=False)
        batches_10 = [r["batch_no"] for r in rows_10]
        self.assertNotIn("BATCH-002", batches_10)

        # 20 days: BATCH-002 is 15 days out -> should be included
        rows_20 = StockReportsDAO.get_items_all_stock(near_expiry_days=20, include_expired=False)
        batches_20 = [r["batch_no"] for r in rows_20]
        self.assertIn("BATCH-002", batches_20)
        self.assertNotIn("BATCH-001", batches_20)  # 365 days out

    def test_10_dao_companywise_item_stock(self):
        """DAO get_companywise_item_stock filters by company and calculates SalesValue."""
        rows_cipla = StockReportsDAO.get_companywise_item_stock(self.comp1_id)
        rows_sun = StockReportsDAO.get_companywise_item_stock(self.comp2_id)

        self.assertTrue(all(r["company_id"] == self.comp1_id for r in rows_cipla))
        self.assertTrue(all(r["company_id"] == self.comp2_id for r in rows_sun))

        # Check SalesValue calculation = stock_qty * mrp / pack_size
        b1 = next(r for r in rows_cipla if r["batch_no"] == "BATCH-001")
        # stock=100, mrp=25.0, pack_size=10 -> SalesValue = 100 * 25.0 / 10 = 250.00
        self.assertAlmostEqual(b1["sales_value"], 250.0, places=2)

        syr = next(r for r in rows_sun if r["batch_no"] == "BATCH-SYR")
        # stock=20, mrp=65.0, pack_size=1 -> SalesValue = 20 * 65.0 / 1 = 1300.00
        self.assertAlmostEqual(syr["sales_value"], 1300.0, places=2)

    def test_11_dao_expired_item_list(self):
        """DAO get_expired_item_list returns only expired batches."""
        rows = StockReportsDAO.get_expired_item_list(expired_days=0)
        self.assertGreaterEqual(len(rows), 1)
        batches = [r["batch_no"] for r in rows]
        self.assertIn("BATCH-EXP", batches)
        self.assertNotIn("BATCH-001", batches)
        self.assertNotIn("BATCH-002", batches)

    def test_12_dao_item_list_includes_zero_stock(self):
        """DAO get_item_list returns all master items, even those with zero balance."""
        rows = StockReportsDAO.get_item_list()
        item_names = [r["item_name"] for r in rows]
        self.assertIn("ZERO STOCK TABLET", item_names)

        zero_item = next(r for r in rows if r["item_name"] == "ZERO STOCK TABLET")
        self.assertEqual(zero_item["bal_qty"], 0.0)
        self.assertEqual(zero_item["rate"], 10.0)
        self.assertEqual(zero_item["mrp"], 20.0)

    # ══════════════════════════════════════════════════════════════════
    # Part 3: Screen UI & Crystal Reports Viewer Tests
    # ══════════════════════════════════════════════════════════════════

    def test_13_items_all_stock_page_ui(self):
        """ItemsAllStockPage has required controls, renders pages, and formats '-' for 0 sales."""
        page = ItemsAllStockPage()
        self.assertIsNotNone(page.spin_near_expiry)
        self.assertIsNotNone(page.chk_expired)
        self.assertIsNotNone(page.btn_show_report)

        page.spin_near_expiry.setValue(0)
        page.chk_expired.setChecked(True)
        page.generate_report()

        self.assertGreaterEqual(len(page._pages), 1)
        # Check fmt_qty_dash helper
        self.assertEqual(fmt_qty_dash(0.0), "-")
        self.assertEqual(fmt_qty_dash(15.0), "15")

        # Find row for BATCH-001
        p1 = page._pages[0]
        data_rows = [b for b in p1.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertGreater(len(data_rows), 0)

    def test_14_companywise_item_stock_page_subtotals(self):
        """CompanywiseItemStockPage includes item subtotals and grand totals."""
        page = CompanywiseItemStockPage()
        # Find CIPLA in dropdown
        idx = page.cbo_company.findData(self.comp1_id)
        self.assertGreaterEqual(idx, 0)
        page.cbo_company.setCurrentIndex(idx)
        page.generate_report()

        self.assertGreaterEqual(len(page._pages), 1)
        p1 = page._pages[0]

        # Check for STOCK_SUBTOTAL and GRAND_TOTAL blocks
        subtotals = [b for b in p1.blocks if b.kind == BlockKind.STOCK_SUBTOTAL]
        grand_totals = [b for b in p1.blocks if b.kind == BlockKind.GRAND_TOTAL]

        self.assertGreater(len(subtotals), 0, "Item subtotal row must be generated")
        self.assertEqual(len(grand_totals), 1, "Grand total row must be generated")

        # Verify custom_cells format
        st = subtotals[0]
        self.assertIn("custom_cells", st.data)
        st_cells = st.data["custom_cells"]
        # Label should end with 'Total :'
        self.assertTrue(st_cells[0][1].endswith("Total :"))

    def test_15_expired_item_list_page(self):
        """ExpiredItemListPage renders expired batches and responds to Expired Days filter."""
        page = ExpiredItemListPage()
        self.assertIsNotNone(page.spin_expired_days)
        page.spin_expired_days.setValue(0)
        page.generate_report()

        self.assertGreaterEqual(len(page._pages), 1)
        p1 = page._pages[0]
        data_rows = [b for b in p1.blocks if b.kind == BlockKind.DATA_ROW]
        batch_texts = [b.data["cells"][3] for b in data_rows]
        self.assertIn("BATCH-EXP", batch_texts)

    def test_16_item_list_page(self):
        """ItemListPage displays all master items, Rate, MRP, and Balance Qty."""
        page = ItemListPage()
        page.cbo_company.setCurrentIndex(0)  # All companies
        page.generate_report()

        self.assertGreaterEqual(len(page._pages), 1)
        p1 = page._pages[0]
        data_rows = [b for b in p1.blocks if b.kind == BlockKind.DATA_ROW]
        item_names = [b.data["cells"][1] for b in data_rows]
        self.assertIn("PARACETAMOL 500MG", item_names)
        self.assertIn("ZERO STOCK TABLET", item_names)

    # ══════════════════════════════════════════════════════════════════
    # Part 4: Export, Print, and Theme Tests
    # ══════════════════════════════════════════════════════════════════

    def test_17_export_pdf_and_print_execution(self):
        """Export PDF and Print execute cleanly without exceptions."""
        page = ItemsAllStockPage()
        page.generate_report()

        tmp_pdf = os.path.join(tempfile.gettempdir(), "_test_stock_export.pdf")
        if os.path.exists(tmp_pdf):
            try:
                os.remove(tmp_pdf)
            except OSError:
                pass

        from ui.crystal_report_viewer import print_or_export_report_pages
        success = print_or_export_report_pages(page._pages, output_pdf_path=tmp_pdf)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(tmp_pdf))
        self.assertGreater(os.path.getsize(tmp_pdf), 500)

        # Cleanup
        try:
            os.remove(tmp_pdf)
        except OSError:
            pass

    def test_18_theme_switching(self):
        """Stock report pages respond to refresh_theme() under Day and Night modes."""
        pages = [
            ItemsAllStockPage(),
            CompanywiseItemStockPage(),
            ExpiredItemListPage(),
            ItemListPage(),
        ]

        # Light / Day mode
        theme.theme_manager.set_mode("light")
        for p in pages:
            p.refresh_theme()

        # Dark / Night mode
        theme.theme_manager.set_mode("dark")
        for p in pages:
            p.refresh_theme()

        # Restore light mode
        theme.theme_manager.set_mode("light")


if __name__ == "__main__":
    unittest.main()
