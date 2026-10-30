"""Test verification for:
1. Renaming 'Daily Profit Calculation' to 'Profit Calculation' in Reports -> Sales Report.
2. Removing 'Ctrl+O' keyboard shortcut assigned to it.
3. Ensuring old shortcut no longer opens the report.
4. Ensuring backward compatibility and that all calculations, data, filters work unchanged.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, DEFAULT

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

import database.connection as db_conn
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from ui.menu_data import MENUS, REPORT_SALES_SUBMENU
from ui.navigation_bar import NavigationBar, MENU_SHORTCUTS
from ui.main_window import PharmacyMainWindow
import screens
from screens.sales_reports import DailyProfitCalculationPage, ProfitCalculationPage


class TestProfitCalculationRenameAndShortcut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._temp_path = cls._temp_file.name
        cls._temp_file.close()

        cls._db_patch = patch.object(db_conn, "get_db_path", return_value=cls._temp_path)
        cls._db_patch.start()
        os.environ["PHARMACY_DB"] = cls._temp_path

        db_conn.init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        cls.app = QApplication.instance() or QApplication([])

        cls.messages = patch.multiple(
            QMessageBox, warning=DEFAULT, information=DEFAULT,
            critical=DEFAULT, question=DEFAULT,
        )
        cls.messages.start()

        cls.win = PharmacyMainWindow()
        cls.win.resize(1366, 768)
        cls.win.show()
        cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.messages.stop()
        cls.win.hide()
        cls.win.deleteLater()
        cls.app.processEvents()
        cls._db_patch.stop()
        os.environ.pop("PHARMACY_DB", None)
        if os.path.exists(cls._temp_path):
            try:
                os.remove(cls._temp_path)
            except OSError:
                pass

    def test_01_menu_data_reports_sales_submenu(self):
        """Verify REPORT_SALES_SUBMENU contains 'Profit Calculation' and not 'Daily Profit Calculation'."""
        self.assertIn("Profit Calculation", REPORT_SALES_SUBMENU)
        self.assertNotIn("Daily Profit Calculation", REPORT_SALES_SUBMENU)
        self.assertEqual(
            REPORT_SALES_SUBMENU,
            [
                "Daily Billwise Sales",
                "Daily Itemwise Sales",
                "Companywise Sales",
                "Itemwise Sales",
                "Profit Calculation",
                "Daily Profit Itemwise",
            ],
        )

    def test_02_menu_shortcuts_removal(self):
        """Verify Ctrl+O is removed from MENU_SHORTCUTS and no shortcut is mapped to Profit Calculation."""
        self.assertNotIn("Daily Profit Calculation", MENU_SHORTCUTS)
        self.assertNotIn("Profit Calculation", MENU_SHORTCUTS)
        self.assertNotIn("Ctrl+O", MENU_SHORTCUTS.values())
        # Verify other shortcuts remain intact
        self.assertEqual(MENU_SHORTCUTS.get("Daily Itemwise Sales"), "Ctrl+T")
        self.assertEqual(MENU_SHORTCUTS.get("GST Report"), "Ctrl+G")
        self.assertEqual(MENU_SHORTCUTS.get("New Bill"), "Ctrl+S")

    def test_03_navigation_bar_reports_submenu_actions(self):
        """Verify NavigationBar menu creates 'Profit Calculation' action with no shortcut."""
        reports_btn = next(
            btn for btn in self.win._nav.findChildren(QPushButton)
            if btn.objectName() == "NavButton" and btn.text() == "Reports"
        )
        reports_menu = reports_btn.menu()
        self.assertIsNotNone(reports_menu)

        # Find the Sales Report submenu
        sales_sub_action = next(
            a for a in reports_menu.actions() if a.text() == "Sales Report"
        )
        sales_menu = sales_sub_action.menu()
        self.assertIsNotNone(sales_menu)

        action_names = [a.text() for a in sales_menu.actions() if not a.isSeparator()]
        self.assertIn("Profit Calculation", action_names)
        self.assertNotIn("Daily Profit Calculation", action_names)

        # Check shortcut for Profit Calculation action
        profit_action = next(a for a in sales_menu.actions() if a.text() == "Profit Calculation")
        self.assertTrue(profit_action.shortcut().isEmpty())

    def test_04_navigate_to_profit_calculation(self):
        """Opening 'Profit Calculation' loads the page, sets title and status bar."""
        self.win._on_menu_action("Reports", "Profit Calculation")
        self.app.processEvents()

        curr = self.win._stack.currentWidget()
        self.assertIsInstance(curr, DailyProfitCalculationPage)
        self.assertEqual(self.win._nav.status_label.text(), "Reports / Profit Calculation")
        self.assertIn("Profit Calculation", self.win.windowTitle())

    def test_05_ctrl_o_shortcut_no_longer_opens_profit_calculation(self):
        """Pressing Ctrl+O while on another page does NOT open Profit Calculation."""
        # Switch to Cash Book first
        self.win._on_menu_action("Account", "Cash Book")
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CashBookPage)

        # Press Ctrl+O
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_O, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()

        # Should still be on Cash Book, NOT on Profit Calculation
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CashBookPage)
        self.assertNotIsInstance(self.win._stack.currentWidget(), DailyProfitCalculationPage)

    def test_06_other_shortcuts_still_work(self):
        """Verify that other keyboard shortcuts (e.g. Ctrl+T, Ctrl+S) still work."""
        # Press Ctrl+T -> Daily Itemwise Sales
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_T, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.DailyItemwiseSalesPage)

        # Press Ctrl+S -> Counter Sale
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_S, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CounterSalePage)

    def test_07_backward_compatibility_daily_profit_calculation(self):
        """Legacy trigger with 'Daily Profit Calculation' still routes properly."""
        self.win._on_menu_action("Account", "Cash Book")
        self.app.processEvents()

        self.win._on_menu_action("Reports", "Daily Profit Calculation")
        self.app.processEvents()

        curr = self.win._stack.currentWidget()
        self.assertIsInstance(curr, DailyProfitCalculationPage)

    def test_08_page_functionality_preserved(self):
        """Verify table columns, date controls, data loading remain intact."""
        page = DailyProfitCalculationPage()
        self.assertEqual(page.widget.table.columnCount(), 12)
        expected_headers = [
            "VOUCHER DATE", "CASH RECEIPT", "CASH SALES", "TOTAL CASH RECEIVED",
            "CASH PAYMENT", "CASH SALES RETURN", "NET CASH RECEIVED",
            "BANK PAYMENT", "CREDIT SALES", "NET SALES", "NET PURCHASE", "NET PROFIT"
        ]
        for col, expected in enumerate(expected_headers):
            item = page.widget.table.horizontalHeaderItem(col)
            self.assertEqual(item.text().upper(), expected)

        # Verify ProfitCalculationPage is an alias
        self.assertIs(ProfitCalculationPage, DailyProfitCalculationPage)


if __name__ == "__main__":
    unittest.main()
