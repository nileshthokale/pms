"""Tests for Reports > Sales Report Side Submenu.

Verifies:
1. Reports menu structure in ui/menu_data.py has Sales Report configured with REPORT_SALES_SUBMENU.
2. Backward compatibility: SubmenuDict compares equal to 'Sales Report'.
3. NavigationBar creates a nested QMenu for Sales Report with a right-arrow submenu.
4. Sales Report submenu contains the supported sales report option ('Sales Report').
5. Triggering the submenu action emits menu_action_triggered and opens SalesReportPage.
6. Other Reports items (Purchase Report, Stock Report, Expiry Report, Party Wise Report, GST Report, Ledger) remain intact and functional.
7. Submenu receives theme stylesheets in both Day Mode and Night Mode.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QPushButton, QMenu

from database.connection import init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from ui.menu_data import (
    MENUS,
    REPORT_SALES_SUBMENU,
    REPORT_PURCHASE_SUBMENU,
    REPORT_LEDGER_SUBMENU,
    SubmenuDict,
)
from ui.navigation_bar import NavigationBar
from ui.main_window import PharmacyMainWindow
import screens
import ui.theme as theme


class TestReportsSalesSubmenu(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_reports_sales_submenu.db")

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

        cls.app = QApplication.instance() or QApplication([])
        cls.win = PharmacyMainWindow()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass

    def test_01_menu_data_sales_report_submenu(self):
        """Verifies REPORT_SALES_SUBMENU and MENUS['Reports'] structure."""
        self.assertIn("Sales Report", REPORT_SALES_SUBMENU)
        self.assertEqual(REPORT_SALES_SUBMENU, ["Sales Report"])

        reports = MENUS["Reports"]
        # First entry is Sales Report submenu
        first_item = reports[0]
        self.assertIsInstance(first_item, dict)
        self.assertIn("Sales Report", first_item)
        self.assertEqual(first_item["Sales Report"], ["Sales Report"])

        # Backward compatibility with string matching
        self.assertEqual(first_item, "Sales Report")

    def test_02_reports_items_order_and_siblings_preserved(self):
        """Preserves Purchase Report, Stock Report, Expiry Report, Party Wise Report, GST Report, Ledger."""
        reports = MENUS["Reports"]
        self.assertEqual(len(reports), 7)
        self.assertEqual(reports[0], "Sales Report")
        self.assertEqual(reports[1], "Purchase Report")
        self.assertEqual(reports[2], "Stock Report")
        self.assertEqual(reports[3], "Expiry Report")
        self.assertEqual(reports[4], "Party Wise Report")
        self.assertEqual(reports[5], "GST Report")
        self.assertIn("Ledger", reports[6])

    def test_03_navigation_bar_builds_sales_report_submenu(self):
        """NavigationBar builds a nested QMenu with a right arrow under Reports for Sales Report."""
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
                "Expiry Report",
                "Party Wise Report",
                "GST Report",
                "Ledger",
            ],
        )

        sr_action = actions[0]
        self.assertEqual(sr_action.text(), "Sales Report")
        submenu = sr_action.menu()
        self.assertIsNotNone(submenu, "Sales Report action must have an attached QMenu submenu (right-arrow)")

        sub_actions = [a.text() for a in submenu.actions() if not a.isSeparator()]
        self.assertEqual(sub_actions, ["Sales Report"])

    def test_04_submenu_signal_emits_correct_menu_action(self):
        """Clicking the Sales Report submenu action emits menu_action_triggered('Reports', 'Sales Report')."""
        nav = NavigationBar()
        received = []
        nav.menu_action_triggered.connect(lambda m, a: received.append((m, a)))

        reports_btn = next(
            btn for btn in nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        sr_action = next(a for a in reports_btn.menu().actions() if a.text() == "Sales Report")
        submenu = sr_action.menu()
        self.assertIsNotNone(submenu)

        sub_action = next(a for a in submenu.actions() if a.text() == "Sales Report")
        sub_action.trigger()

        self.assertEqual(received, [("Reports", "Sales Report")])

    def test_05_main_window_navigates_to_sales_report_page(self):
        """PharmacyMainWindow navigates to screens.SalesReportPage via the submenu action."""
        self.win._on_menu_action("Reports", "Sales Report")
        curr = self.win._stack.currentWidget()
        self.assertIsInstance(curr, screens.SalesReportPage)
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Sales Report")

    def test_06_sibling_menus_remain_functional(self):
        """Verifies Stock Report, Purchase Report, and Ledger submenu still navigate cleanly."""
        # 1. Stock Report
        self.win._on_menu_action("Reports", "Stock Report")
        self.assertIsInstance(self.win._stack.currentWidget(), (screens.StockMasterPage, screens.ItemsAllStockPage))

        # 2. Purchase Report submenu
        self.win._on_menu_action("Reports", "Companywise Itemwise Purchase")
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CompanywiseItemwisePurchasePage)

        # 3. Ledger submenu
        self.win._on_menu_action("Reports", "Supplier Ledger")
        self.assertIsInstance(self.win._stack.currentWidget(), screens.SupplierLedgerPage)

        # 4. Return to Sales Report
        self.win._on_menu_action("Reports", "Sales Report")
        self.assertIsInstance(self.win._stack.currentWidget(), screens.SalesReportPage)

    def test_07_theme_styling_applies_to_sales_submenu(self):
        """Sales Report submenu receives Day Mode and Night Mode stylesheets."""
        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        sr_action = next(a for a in reports_btn.menu().actions() if a.text() == "Sales Report")
        submenu = sr_action.menu()
        self.assertIsNotNone(submenu)

        # Day mode
        theme.theme_manager.set_mode("light")
        self.assertIn("QMenu", submenu.styleSheet())
        p_light = theme.theme_manager.palette()
        self.assertIn(p_light["bg"], submenu.styleSheet())

        # Night mode
        theme.theme_manager.set_mode("dark")
        self.assertIn("QMenu", submenu.styleSheet())
        p_dark = theme.theme_manager.palette()
        self.assertIn(p_dark["bg"], submenu.styleSheet())

        # Restore Day mode
        theme.theme_manager.set_mode("light")


if __name__ == "__main__":
    unittest.main()
