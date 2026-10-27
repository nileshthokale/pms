"""Verification tests for moving Debit Note and Credit Note from Account to Purchase menu."""

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from database.connection import init_database
from database import auth, financial_year
from ui.menu_data import MENUS
from ui.navigation_bar import NavigationBar, MENU_SHORTCUTS
from ui.main_window import PharmacyMainWindow
import screens


class TestPurchaseDebitCreditMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.tmp_db.close()
        os.environ["PHARMACY_DB"] = cls.tmp_db.name
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        admin = auth.create_first_admin("testadmin", "password123")
        auth.session.login("testadmin", "password123")

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(cls.tmp_db.name):
                os.remove(cls.tmp_db.name)
        except Exception:
            pass

    def test_01_menu_definitions(self):
        """1. Purchase menu contains Debit Note and Credit Note; Account menu does not."""
        purchase_items = MENUS.get("Purchase", [])
        self.assertIn("Debit Note (Return to Supplier)", purchase_items)
        self.assertIn("Credit Note (Return from Customer)", purchase_items)

        account_items = MENUS.get("Account", [])
        self.assertNotIn("Debit Note (Return to Supplier)", account_items)
        self.assertNotIn("Credit Note (Return from Customer)", account_items)

        # Existing items in Purchase are preserved
        self.assertIn("New Purchase", purchase_items)
        self.assertIn("Purchase History", purchase_items)
        self.assertIn("Stock Adjustment", purchase_items)

        # Existing items in Account are preserved
        self.assertIn("Supplier Payment Voucher", account_items)
        self.assertIn("Customer Receipt Voucher", account_items)
        self.assertIn("Cash Book", account_items)
        self.assertIn("Bank Book", account_items)
        self.assertIn("Ledger", account_items)
        self.assertIn("Journal Entry", account_items)
        self.assertIn("Account Roles", account_items)
        self.assertIn("Trial Balance", account_items)
        self.assertIn("Profit & Loss", account_items)
        self.assertIn("Balance Sheet", account_items)

    def test_02_shortcuts_preserved(self):
        """2. Keyboard shortcuts Ctrl+D and Ctrl+C are properly mapped."""
        self.assertEqual(MENU_SHORTCUTS.get("Debit Note (Return to Supplier)"), "Ctrl+D")
        self.assertEqual(MENU_SHORTCUTS.get("Credit Note (Return from Customer)"), "Ctrl+C")

    def test_03_navigation_bar_actions(self):
        """3. NavigationBar creates actions under Purchase QMenu and not under Account QMenu."""
        nav = NavigationBar()
        purchase_btn = None
        account_btn = None
        for btn in nav.findChildren(object, "NavButton"):
            if btn.text() == "Purchase":
                purchase_btn = btn
            elif btn.text() == "Account":
                account_btn = btn

        self.assertIsNotNone(purchase_btn)
        self.assertIsNotNone(account_btn)

        purchase_actions = [a.text() for a in purchase_btn.menu().actions() if not a.isSeparator()]
        self.assertIn("Debit Note (Return to Supplier)", purchase_actions)
        self.assertIn("Credit Note (Return from Customer)", purchase_actions)

        account_actions = [a.text() for a in account_btn.menu().actions() if not a.isSeparator()]
        self.assertNotIn("Debit Note (Return to Supplier)", account_actions)
        self.assertNotIn("Credit Note (Return from Customer)", account_actions)

        # Verify triggering action from Purchase menu emits correct signal
        triggered = []
        nav.menu_action_triggered.connect(lambda m, a: triggered.append((m, a)))

        for act in purchase_btn.menu().actions():
            if act.text() == "Debit Note (Return to Supplier)":
                act.trigger()
            elif act.text() == "Credit Note (Return from Customer)":
                act.trigger()

        self.assertEqual(
            triggered,
            [
                ("Purchase", "Debit Note (Return to Supplier)"),
                ("Purchase", "Credit Note (Return from Customer)"),
            ],
        )

    def test_04_main_window_screen_navigation(self):
        """4. Opening Debit Note and Credit Note from Purchase opens existing screen and functionality."""
        win = PharmacyMainWindow()

        # Check page map entries
        self.assertIn("Purchase:Debit Note (Return to Supplier)", win._page_map)
        self.assertIn("Purchase:Credit Note (Return from Customer)", win._page_map)

        dn_idx = win._page_map["Purchase:Debit Note (Return to Supplier)"]
        cn_idx = win._page_map["Purchase:Credit Note (Return from Customer)"]

        self.assertIsInstance(win._stack.widget(dn_idx), screens.DebitNotePage)
        self.assertIsInstance(win._stack.widget(cn_idx), screens.CreditNotePage)

        # Test switching to Debit Note via Purchase menu
        win._on_menu_action("Purchase", "Debit Note (Return to Supplier)")
        self.assertEqual(win._stack.currentIndex(), dn_idx)
        self.assertIsInstance(win._stack.currentWidget(), screens.DebitNotePage)
        self.assertEqual(win._nav.status_label.text(), "Purchase / Debit Note (Return to Supplier)")

        # Test switching to Credit Note via Purchase menu
        win._on_menu_action("Purchase", "Credit Note (Return from Customer)")
        self.assertEqual(win._stack.currentIndex(), cn_idx)
        self.assertIsInstance(win._stack.currentWidget(), screens.CreditNotePage)
        self.assertEqual(win._nav.status_label.text(), "Purchase / Credit Note (Return from Customer)")

        # Test legacy / backward compatibility redirection from Account
        win._on_menu_action("Account", "Debit Note (Return to Supplier)")
        self.assertEqual(win._stack.currentIndex(), dn_idx)
        self.assertEqual(win._nav.status_label.text(), "Purchase / Debit Note (Return to Supplier)")

        win._on_menu_action("Account", "Credit Note (Return from Customer)")
        self.assertEqual(win._stack.currentIndex(), cn_idx)
        self.assertEqual(win._nav.status_label.text(), "Purchase / Credit Note (Return from Customer)")

        win.close()


if __name__ == "__main__":
    unittest.main()
