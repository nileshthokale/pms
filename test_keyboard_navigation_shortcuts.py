"""Comprehensive verification for all requested keyboard shortcuts:
- Ctrl+S: Open Counter Sale from any page
- Alt+S in Counter Sale: Open Save Bill review popup
- Alt+S in Save Bill popup: Save the bill directly
- Ctrl+I: Open New Purchase page
- Ctrl+A: Open Stock Adjustment
- Ctrl+B: Open Sales Bill
- Ctrl+C: Open Credit Note from customer
- Ctrl+D: Open Debit Note (credit note from supplier)
- Ctrl+P: Open Supplier Payment Voucher
- Ctrl+R: Open Customer Payment Voucher (Customer Receipt Voucher)
- Ctrl+G: Open GST Report
- Ctrl+T: Open Daily Itemwise Sales
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, DEFAULT

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox

import database.connection as db_conn
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.company_dao import CompanyDAO
from database.customer_dao import CustomerDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.unit_dao import UnitDAO
from ui import PharmacyMainWindow
from ui.navigation_bar import MENU_SHORTCUTS
import screens


class TestKeyboardNavigationShortcuts(unittest.TestCase):
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

        cls.cid = CompanyDAO.insert("AltSPharma", "ASP")
        cls.uid = UnitDAO.insert("Strip")
        cls.cust_id = CustomerDAO.insert(customer_name="Alt S Customer", city="Test")
        cls.item_id = ItemDAO.insert(item_name="Alt S Med 500", unit_id=cls.uid, company_id=cls.cid, pack_size="10")
        conn = db_conn.get_connection()
        try:
            conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cls.item_id, "AS-BATCH-1", "12/28", "10", 100.0, 70.0, 80.0, 50.0),
            )
            conn.commit()
        finally:
            conn.close()

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

    def test_menu_shortcuts_dictionary(self):
        """Verify navigation bar MENU_SHORTCUTS has all required mappings."""
        self.assertEqual(MENU_SHORTCUTS.get("New Bill"), "Ctrl+S")
        self.assertEqual(MENU_SHORTCUTS.get("New Purchase"), "Ctrl+I")
        self.assertEqual(MENU_SHORTCUTS.get("Stock Adjustment"), "Ctrl+A")
        self.assertEqual(MENU_SHORTCUTS.get("Debit Note (Return to Supplier)"), "Ctrl+D")
        self.assertEqual(MENU_SHORTCUTS.get("Credit Note (Return from Customer)"), "Ctrl+C")
        self.assertEqual(MENU_SHORTCUTS.get("Supplier Payment Voucher"), "Ctrl+P")
        self.assertEqual(MENU_SHORTCUTS.get("Customer Receipt Voucher"), "Ctrl+R")
        self.assertEqual(MENU_SHORTCUTS.get("GST Report"), "Ctrl+G")
        self.assertEqual(MENU_SHORTCUTS.get("Daily Itemwise Sales"), "Ctrl+T")

    def test_ctrl_shortcuts_navigate_from_other_pages(self):
        """Verify each shortcut opens its specific page when pressed on any other page."""
        # Start on Cash Book page
        self.win._on_menu_action("Account", "Cash Book")
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CashBookPage)

        # 1. Ctrl+S -> Counter Sale
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_S, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CounterSalePage)

        # 2. Ctrl+I -> New Purchase
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_I, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.PurchaseInvoicePage)

        # 3. Ctrl+A -> Stock Adjustment
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_A, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.AdjustedStockListPage)

        # 4. Ctrl+B -> Sales Bill / Counter Sale
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_B, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CounterSalePage)

        # 5. Ctrl+D -> Debit Note (Return to Supplier)
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_D, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.DebitNotePage)

        # 6. Ctrl+C -> Credit Note (Return from Customer)
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_C, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CreditNotePage)

        # 7. Ctrl+P -> Supplier Payment Voucher
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_P, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.SupplierPaymentPage)

        # 8. Ctrl+R -> Customer Payment Voucher
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_R, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.CustomerReceiptPage)

        # 9. Ctrl+G -> GST Report
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_G, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.GSTReportPage)

        # 10. Ctrl+T -> Daily Itemwise Sales
        ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_T, Qt.ControlModifier)
        self.app.sendEvent(self.win, ev)
        self.app.processEvents()
        self.assertIsInstance(self.win._stack.currentWidget(), screens.DailyItemwiseSalesPage)

    def test_alt_s_opens_review_dialog_and_second_alt_s_saves_directly(self):
        """Verify Alt+S in Counter Sale opens review dialog, and Alt+S in review dialog saves directly."""
        # Open Counter Sale
        self.win._open_counter_sale()
        cs_page: screens.CounterSalePage = self.win._stack.currentWidget()
        self.assertIsInstance(cs_page, screens.CounterSalePage)
        panel = cs_page._sale_panel

        # Ensure customers and items are loaded
        panel._load_customers()
        c_idx = panel.customer_combo.findData(self.cust_id)
        panel.customer_combo.setCurrentIndex(c_idx if c_idx >= 0 else 1)
        panel.patient_name_edit.setText("Shortcut Test Patient")

        bar = panel._entry_bar
        bar.load_items()
        i_idx = bar.item_combo.findData(self.item_id)
        bar.item_combo.setCurrentIndex(i_idx)
        bar.reload_item_batches()
        bar.batch_combo.setCurrentIndex(0)
        bar.qty_edit.setText("2")
        bar.add_btn.click()
        self.app.processEvents()

        self.assertEqual(len(panel._item_rows), 1)
        self.assertIsNone(getattr(panel, "_review_dialog", None))

        # First Alt+S: opens Save Bill review dialog
        ev1 = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_S, Qt.AltModifier)
        self.app.sendEvent(cs_page, ev1)
        self.app.processEvents()

        dlg = getattr(panel, "_review_dialog", None)
        self.assertIsNotNone(dlg, "SalesBillReviewDialog was not opened by Alt+S")
        self.assertTrue(dlg.isVisible())

        # Second Alt+S on review dialog: saves that bill directly!
        ev2 = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_S, Qt.AltModifier)
        self.app.sendEvent(dlg, ev2)
        self.app.processEvents()

        # The dialog should be closed and sale committed!
        self.assertFalse(dlg.isVisible(), "Review dialog remained open after second Alt+S")
        self.assertTrue(dlg._panel.was_saved, "Sale was not saved after second Alt+S")

    def test_new_purchase_button_on_counter_sale_navigates_to_new_purchase(self):
        """Verify the 'New Purchase' button near 'Patient Bill History' opens New Purchase."""
        self.win._open_counter_sale()
        self.app.processEvents()
        cs_page: screens.CounterSalePage = self.win._stack.currentWidget()
        self.assertIsInstance(cs_page, screens.CounterSalePage)

        btn = getattr(cs_page, "_hist_new_purchase_btn", None)
        self.assertIsNotNone(btn, "CounterSalePage must have _hist_new_purchase_btn")
        self.assertEqual(btn.text(), "New Purchase")
        self.assertIn("Ctrl+I", btn.toolTip())

        # Check button order in toolbar layout
        layout = cs_page._history_filter_bar.layout()
        btn_texts = []
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if isinstance(w, screens.counter_sale.QPushButton):
                btn_texts.append(w.text())
        self.assertIn("Patient Bill History", btn_texts)
        self.assertIn("New Purchase", btn_texts)
        pbh_idx = btn_texts.index("Patient Bill History")
        np_idx = btn_texts.index("New Purchase")
        self.assertEqual(np_idx, pbh_idx + 1, "New Purchase must be right next to Patient Bill History")

        # Click New Purchase button
        btn.click()
        self.app.processEvents()

        current = self.win._stack.currentWidget()
        self.assertIsInstance(current, screens.PurchaseInvoicePage)
        self.assertEqual(self.win._nav.status_label.text(), "Purchase / New Purchase")


if __name__ == "__main__":
    unittest.main()
