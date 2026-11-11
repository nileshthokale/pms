"""Tests for Reports menu nested Ledger submenu.

Verifies:
1. Top-level menus remain unchanged: Sales, Purchase, Account, Reports, Master.
   No top-level Ledger menu exists.
2. Reports dropdown contains existing items in order, followed by Ledger at the bottom.
3. Supplier Ledger, Customer Ledger, and Itemwise Ledger are removed as direct entries
   from Reports and exist ONLY inside the nested Ledger submenu.
4. Hovering / accessing Ledger opens a nested submenu to its right containing exactly:
   - Supplier Ledger
   - Customer Ledger
   - Itemwise Ledger
5. Navigating to each submenu option opens the correct existing ledger page:
   - Supplier Ledger -> screens.SupplierLedgerPage
   - Customer Ledger -> screens.CustomerLedgerPage
   - Itemwise Ledger -> screens.ItemwiseLedgerPage
6. Reuses existing navigation handlers without duplicate handlers or pages.
7. Menus and nested submenu properly adhere to Day Mode and Night Mode themes.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu, QPushButton

from database.connection import init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers

import screens
from ui import theme
from ui.menu_data import MENUS, REPORT_LEDGER_SUBMENU
from ui.navigation_bar import NavigationBar
from ui.main_window import PharmacyMainWindow
from version import APP_TITLE


class TestReportsLedgerSubmenu(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_reports_ledger_submenu.db")

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

    def test_01_top_level_menus_unchanged(self):
        """Top-level menus must remain unchanged and not include a new Ledger menu."""
        expected_top_menus = ["Sales", "Purchase", "Account", "Reports", "Master"]
        self.assertEqual(list(MENUS.keys()), expected_top_menus)
        self.assertNotIn("Ledger", MENUS)

        nav_buttons = [
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton"
        ]
        button_labels = [btn.text() for btn in nav_buttons]
        self.assertEqual(button_labels, expected_top_menus)

    def test_02_reports_menu_structure(self):
        """Reports menu has original items followed by nested Ledger submenu at the bottom."""
        reports = MENUS["Reports"]
        expected_direct_items = [
            "Sales Report",
            "Purchase Report",
            "Stock Report",
            "Expiry Report",
            "Party Wise Report",
            "GST Report",
        ]
        # First 6 items unchanged
        self.assertEqual(reports[:6], expected_direct_items)

        # Removed as direct entries
        self.assertNotIn("Supplier Ledger", reports)
        self.assertNotIn("Customer Ledger", reports)
        self.assertNotIn("Itemwise Ledger", reports)

        # Bottom item is Ledger submenu dictionary
        bottom_item = reports[-1]
        self.assertIsInstance(bottom_item, dict)
        self.assertIn("Ledger", bottom_item)
        self.assertEqual(
            bottom_item["Ledger"],
            ["Supplier Ledger", "Customer Ledger", "Itemwise Ledger"],
        )
        self.assertEqual(REPORT_LEDGER_SUBMENU, ["Supplier Ledger", "Customer Ledger", "Itemwise Ledger"])

    def test_03_navigation_bar_builds_nested_submenu(self):
        """NavigationBar builds a nested QMenu under Reports for Ledger."""
        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        reports_menu = reports_btn.menu()
        self.assertIsNotNone(reports_menu)

        actions = reports_menu.actions()
        action_texts = [a.text() for a in actions]
        expected_actions = [
            "Sales Report",
            "Purchase Report",
            "Stock Report",
            "Expiry Report",
            "Party Wise Report",
            "GST Report",
            "Ledger",
        ]
        self.assertEqual(action_texts, expected_actions)

        # Direct entries must NOT include the 3 ledger items
        self.assertNotIn("Supplier Ledger", action_texts)
        self.assertNotIn("Customer Ledger", action_texts)
        self.assertNotIn("Itemwise Ledger", action_texts)

        # Bottom action must be Ledger and have a submenu
        ledger_action = actions[-1]
        self.assertEqual(ledger_action.text(), "Ledger")
        submenu = ledger_action.menu()
        self.assertIsNotNone(submenu, "Ledger action must have an attached QMenu submenu")

        # Submenu contains exactly the 3 items
        sub_actions = [a.text() for a in submenu.actions()]
        self.assertEqual(sub_actions, ["Supplier Ledger", "Customer Ledger", "Itemwise Ledger"])

    def test_04_submenu_signals_trigger_navigation(self):
        """Triggering actions in the Ledger submenu emits menu_action_triggered signal."""
        nav = NavigationBar()
        received = []
        nav.menu_action_triggered.connect(lambda menu, action: received.append((menu, action)))

        reports_btn = next(
            btn for btn in nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        ledger_menu = reports_btn.menu().actions()[-1].menu()
        self.assertIsNotNone(ledger_menu)

        for sub_act in ledger_menu.actions():
            sub_act.trigger()

        self.assertEqual(received, [
            ("Reports", "Supplier Ledger"),
            ("Reports", "Customer Ledger"),
            ("Reports", "Itemwise Ledger"),
        ])

    def test_05_main_window_navigates_to_ledger_pages(self):
        """PharmacyMainWindow navigates to the correct ledger pages via the submenu."""
        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        ledger_menu = reports_btn.menu().actions()[-1].menu()

        # 1. Supplier Ledger
        sup_act = next(a for a in ledger_menu.actions() if a.text() == "Supplier Ledger")
        sup_act.trigger()
        current_page = self.win._stack.currentWidget()
        self.assertIsInstance(current_page, screens.SupplierLedgerPage)
        self.assertIn("Supplier Ledger", self.win.windowTitle())
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Supplier Ledger")

        # 2. Customer Ledger
        cust_act = next(a for a in ledger_menu.actions() if a.text() == "Customer Ledger")
        cust_act.trigger()
        current_page = self.win._stack.currentWidget()
        self.assertIsInstance(current_page, screens.CustomerLedgerPage)
        self.assertIn("Customer Ledger", self.win.windowTitle())
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Customer Ledger")

        # 3. Itemwise Ledger
        item_act = next(a for a in ledger_menu.actions() if a.text() == "Itemwise Ledger")
        item_act.trigger()
        current_page = self.win._stack.currentWidget()
        self.assertIsInstance(current_page, screens.ItemwiseLedgerPage)
        self.assertIn("Itemwise Ledger", self.win.windowTitle())
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Itemwise Ledger")

    def test_06_no_duplicate_pages_or_routes(self):
        """Ensure ledger pages are registered only once per report."""
        page_counts = {
            screens.SupplierLedgerPage: 0,
            screens.CustomerLedgerPage: 0,
            screens.ItemwiseLedgerPage: 0,
        }
        for index in range(self.win._stack.count()):
            widget = self.win._stack.widget(index)
            for cls in page_counts:
                if isinstance(widget, cls):
                    page_counts[cls] += 1

        self.assertEqual(page_counts[screens.SupplierLedgerPage], 1)
        self.assertEqual(page_counts[screens.CustomerLedgerPage], 1)
        self.assertEqual(page_counts[screens.ItemwiseLedgerPage], 1)

    def test_07_theme_styling_applies_to_submenu(self):
        """Submenu receives Day Mode and Night Mode stylesheets."""
        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        ledger_menu = reports_btn.menu().actions()[-1].menu()

        orig_mode = theme.theme_manager.mode()
        try:
            # Day Mode
            theme.theme_manager.set_mode("light")
            self.win._nav._apply_theme()
            p_light = theme.palette()
            self.assertIn(p_light["bg"], ledger_menu.styleSheet())
            self.assertIn(p_light["selected"], ledger_menu.styleSheet())

            # Night Mode
            theme.theme_manager.set_mode("night")
            self.win._nav._apply_theme()
            p_dark = theme.palette()
            self.assertIn(p_dark["bg"], ledger_menu.styleSheet())
            self.assertIn(p_dark["selected"], ledger_menu.styleSheet())
        finally:
            theme.theme_manager.set_mode(orig_mode)
            self.win._nav._apply_theme()


if __name__ == "__main__":
    unittest.main()
