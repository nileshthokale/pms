"""Acceptance tests for the second Sales History entry point on Counter Sale.

Verifies the requested behaviour end to end:

1. A "Sales History" button sits directly beside the existing Refresh button
   in the Counter Sale (Sales page) history filter bar, aligned with it.
2. The original Sales -> Sales History menu entry is untouched and still
   opens the dedicated SalesHistoryPage.
3. Clicking the new button opens the exact same SalesHistoryPage instance.
4. Actual saved sales records load on the Sales History view.
5. Refresh and the existing Sales page features keep working.

Runs offscreen: QT_QPA_PLATFORM=offscreen.
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
from PySide6.QtWidgets import QApplication, QPushButton

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

from screens.counter_sale import CounterSalePage
from ui.main_window import PharmacyMainWindow


class CounterSaleSalesHistoryButtonTests(unittest.TestCase):
    _DB_PATH = os.path.join(
        tempfile.gettempdir(), "_test_counter_sale_sales_history_button.db"
    )

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
                "hold_bill_items", "hold_bills", "items", "customers",
                "doctors", "suppliers", "drugs", "units", "companies",
                "financial_years",
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
        self.doctor_id = DoctorDAO.insert("Dr. Smith", specialty="General")

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
            mock.patch("PySide6.QtWidgets.QMessageBox.warning", return_value=0),
            mock.patch("PySide6.QtWidgets.QMessageBox.information", return_value=0),
            mock.patch("PySide6.QtWidgets.QMessageBox.critical", return_value=0),
            mock.patch("PySide6.QtWidgets.QMessageBox.question", return_value=0x4000),
            mock.patch("PySide6.QtWidgets.QMessageBox.exec", return_value=0),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._pump(10)

    def _pump(self, n=3):
        for _ in range(n):
            self._app.processEvents()

    def _insert_sale(self, *, bill_no: str, sale_date: str, patient: str) -> int:
        return SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date=sale_date, sale_time="10:30",
            sale_type="Cash", customer_id=self.customer_id, patient_name=patient,
            doctor_id=self.doctor_id, discount=0.0, paid_amount=70.0,
            total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "SHELF-A",
                "batch_no": "BATCH-AMOX-01", "expiry": "12/28", "mrp": 70.0,
                "sale_qty": 1.0, "discount_amount": 0.0, "amount": 70.0,
            }],
        )

    def _make_window(self) -> PharmacyMainWindow:
        win = PharmacyMainWindow()
        win.resize(1200, 800)
        win.show()
        self._pump()
        self.addCleanup(lambda: (win.hide(), win.deleteLater()))
        return win

    def _counter_page(self, win: PharmacyMainWindow) -> CounterSalePage:
        return win._stack.widget(win._page_map["Sales:New Bill"])

    # ------------------------------------------------------------------
    # Criterion 1: the new button exists beside Refresh on the Sales page.
    # ------------------------------------------------------------------
    def test_01_sales_history_button_sits_beside_refresh(self):
        page = CounterSalePage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        btn = getattr(page, "_hist_sales_history_btn", None)
        self.assertIsNotNone(
            btn, "Counter Sale (Sales page) must expose a Sales History button"
        )
        self.assertIn(btn.text(), ("Patient Bill History", "Sales History"))
        self.assertTrue(btn.isEnabled())

        # Same toolbar and alignment metrics as the existing Refresh button.
        self.assertIs(btn.parent(), page._history_filter_bar)
        self.assertEqual(
            btn.height(), page._hist_refresh_btn.height(),
            "Sales History must be aligned with Refresh",
        )
        self.assertEqual(
            btn.maximumHeight(), page._hist_refresh_btn.maximumHeight()
        )

        # The first button right after Refresh in the filter bar is the new
        # Sales History button (QRadioButton is not a QPushButton subclass,
        # so the mode selector is excluded here).
        layout = page._history_filter_bar.layout()
        button_texts = []
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, QPushButton):
                button_texts.append(widget.text())
        self.assertIn("Refresh", button_texts)
        self.assertTrue("Patient Bill History" in button_texts or "Sales History" in button_texts)
        target_name = "Patient Bill History" if "Patient Bill History" in button_texts else "Sales History"
        self.assertEqual(
            button_texts[button_texts.index("Refresh") + 1],
            target_name,
            "Patient Bill History must sit directly beside Refresh",
        )

    # ------------------------------------------------------------------
    # Criterion 2: the original Sales History entry still works.
    # ------------------------------------------------------------------
    def test_02_original_menu_entry_still_navigates(self):
        win = self._make_window()

        win._on_menu_action("Sales", "Patient Bill History")
        self._pump()

        current = win._stack.currentWidget()
        self.assertEqual(current.__class__.__name__, "SalesHistoryPage")
        self.assertIs(
            current, win._stack.widget(win._page_map["Sales:Patient Bill History"])
        )

    # ------------------------------------------------------------------
    # Criterion 3: the new button opens the same Sales History view.
    # ------------------------------------------------------------------
    def test_03_new_button_navigates_to_same_sales_history_page(self):
        win = self._make_window()
        counter = self._counter_page(win)

        win._on_menu_action("Sales", "New Bill")
        self._pump()
        self.assertIs(win._stack.currentWidget(), counter)

        counter._hist_sales_history_btn.click()
        self._pump()

        hist = win._stack.widget(win._page_map["Sales:Patient Bill History"])
        self.assertIs(win._stack.currentWidget(), hist)
        self.assertEqual(
            win._stack.currentWidget().__class__.__name__, "SalesHistoryPage"
        )
        self.assertEqual(win._nav.status_label.text(), "Sales / Patient Bill History")

    # ------------------------------------------------------------------
    # Criterion 4: real saved records load after the button navigation.
    # ------------------------------------------------------------------
    def test_04_history_records_load_from_database(self):
        today = QDate.currentDate().toString("yyyy-MM-dd")
        today_id = self._insert_sale(
            bill_no="CS-TODAY-01", sale_date=today, patient="Button Test Patient"
        )
        old_id = self._insert_sale(
            bill_no="CS-OLD-01", sale_date="2026-04-05", patient="Old Patient"
        )

        win = self._make_window()
        counter = self._counter_page(win)
        win._on_menu_action("Sales", "New Bill")
        self._pump()

        counter._hist_sales_history_btn.click()
        self._pump()

        hist = win._stack.currentWidget()
        self.assertEqual(hist.__class__.__name__, "SalesHistoryPage")

        shown_ids = {
            hist._table.item(r, 0).data(Qt.UserRole)
            for r in range(hist._table.rowCount())
            if hist._table.item(r, 0) is not None
        }
        self.assertIn(today_id, shown_ids, "Today's saved bill must be listed")
        self.assertIn(old_id, shown_ids, "Older saved bill must be listed")

        # The displayed data matches the database rows.
        for r in range(hist._table.rowCount()):
            item = hist._table.item(r, 0)
            if item is None or item.data(Qt.UserRole) not in (today_id, old_id):
                continue
            expected = SalesDAO.get_by_id(item.data(Qt.UserRole))
            self.assertIn(
                expected["patient_name"], hist._table.item(r, 2).text()
            )

        # The page's own filters/pagination still work after navigation.
        self.assertGreaterEqual(hist._page_size_combo.count(), 1)
        self.assertTrue(hist._search_btn.isEnabled())
        self.assertTrue(hist._reset_btn.isEnabled())

    # ------------------------------------------------------------------
    # Criterion 5: Refresh and the existing Sales page features still work.
    # ------------------------------------------------------------------
    def test_05_refresh_and_existing_features_keep_working(self):
        today = QDate.currentDate().toString("yyyy-MM-dd")
        inv_id = self._insert_sale(
            bill_no="CS-REFRESH-01", sale_date=today, patient="Refresh Patient"
        )

        page = CounterSalePage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        def shown_invoice_ids() -> set:
            return {
                page._hist_table.item(r, 0).data(Qt.UserRole)
                for r in range(page._hist_table.rowCount())
                if page._hist_table.item(r, 0) is not None
            }

        # The default (today) history view shows the saved sale.
        self.assertIn(inv_id, shown_invoice_ids())

        # Refresh reloads the same day's results without moving the date.
        before = page._hist_date.date()
        page._hist_refresh_btn.click()
        self._pump()
        self.assertEqual(page._hist_date.date(), before)
        self.assertIn(inv_id, shown_invoice_ids())

        # Today button and view-mode switch still work.
        page._hist_today_btn.click()
        self._pump()
        self.assertEqual(page._hist_date.date(), QDate.currentDate())
        page._hist_bill_mode.setChecked(True)
        self._pump()
        self.assertIn(inv_id, shown_invoice_ids())
        page._hist_item_mode.setChecked(True)
        self._pump()

        # New Sale still works and does not disturb history.
        page._new_btn.click()
        self._pump()
        self.assertIn(inv_id, shown_invoice_ids())

        # Day/Night refresh keeps the new button styled and functional.
        # The previous mode is restored so the test leaves no side effect.
        from ui import theme as theme_mod
        original_mode = theme_mod.theme_manager.mode()
        self.addCleanup(theme_mod.theme_manager.set_mode, original_mode)
        for mode in ("dark", "light"):
            theme_mod.theme_manager.set_mode(mode)
            page.refresh_theme()
            self._pump()
            self.assertTrue(page._hist_sales_history_btn.styleSheet())
            self.assertTrue(page._hist_sales_history_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
