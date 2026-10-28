from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog

app = QApplication.instance() or QApplication(sys.argv)

def _fresh_db(tag: str) -> str:
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_new_item_tab_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            try:
                os.remove(stale)
            except OSError:
                pass
    os.environ["PHARMACY_DB"] = db_path
    return db_path


class TestPurchaseNewItemTabIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = _fresh_db(cls.__name__)
        from database.connection import init_database
        from database.financial_year import ensure_default_financial_year
        from database.account_roles import ensure_system_ledgers

        init_database()
        ensure_default_financial_year()
        ensure_system_ledgers()

    def setUp(self):
        # Auto-dismiss any QMessageBox during tests
        self._msgbox_patch = mock.patch.multiple(
            QMessageBox,
            warning=mock.DEFAULT,
            information=mock.DEFAULT,
            critical=mock.DEFAULT,
            question=mock.DEFAULT,
        )
        self._msgbox_patch.start()
        self.addCleanup(self._msgbox_patch.stop)

        from database.connection import get_connection
        from database.unit_dao import UnitDAO
        from database.company_dao import CompanyDAO
        from database.supplier_dao import SupplierDAO
        from database.item_dao import ItemDAO

        conn = get_connection()
        try:
            for tbl in (
                "purchase_invoice_items",
                "purchase_invoices",
                "stock_batches",
                "item_ingredients",
                "items",
                "units",
                "companies",
                "suppliers",
            ):
                conn.execute(f'DELETE FROM "{tbl}"')
            conn.commit()
        finally:
            conn.close()

        # Seed units and companies
        self.unit_tablet = UnitDAO.insert("TABLET")
        self.unit_syrup = UnitDAO.insert("SYRUP")
        self.company_cipla = CompanyDAO.insert("CIPLA", "CIP")
        self.company_sun = CompanyDAO.insert("SUN PHARMA", "SUN")

        # Seed supplier
        self.supplier_id = SupplierDAO.insert(
            supplier_name="ABC DISTRIBUTORS",
            contact_no="9876543210",
            address="City Center",
            credit_period=30,
        )

        # Seed an existing item
        self.existing_item_id = ItemDAO.insert(
            item_name="PARACETAMOL 500MG",
            unit_id=self.unit_tablet,
            company_id=self.company_cipla,
            pack_size="10x10",
            tax_structure="12",
            mrp=45.0,
            rate=30.0,
            discount=5.0,
        )

    def _create_dialog(self):
        from screens.purchase_invoice import _InvoiceDialog
        dlg = _InvoiceDialog()
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        app.processEvents()
        return dlg

    # ------------------------------------------------------------------
    # Scenario 1: Enter an existing item and press Tab: no popup should open
    # ------------------------------------------------------------------
    def test_01_existing_item_tab_no_popup_opened(self):
        dlg = self._create_dialog()
        bar = dlg._entry_bar

        with mock.patch("screens.purchase_invoice._ItemDialog.exec") as mock_popup:
            # 1a. Exact name
            bar.item_combo.lineEdit().setText("PARACETAMOL 500MG")
            handled = bar._on_item_field_tab_pressed()
            self.assertTrue(handled)
            mock_popup.assert_not_called()
            self.assertEqual(bar.item_combo.currentData(), self.existing_item_id)
            self.assertEqual(bar.pack_edit.text(), "10x10")
            self.assertEqual(bar.rate_edit.text(), "30.00")
            self.assertEqual(bar.mrp_edit.text(), "45.00")
            self.assertTrue(bar.pay_qty_edit.hasFocus())

            # 1b. Case insensitive and leading/trailing spaces
            bar.clear()
            bar.item_combo.lineEdit().setText("  paracetamol 500mg   ")
            handled = bar._on_item_field_tab_pressed()
            self.assertTrue(handled)
            mock_popup.assert_not_called()
            self.assertEqual(bar.item_combo.currentData(), self.existing_item_id)

    def test_01b_empty_or_whitespace_input_tab_no_popup(self):
        dlg = self._create_dialog()
        bar = dlg._entry_bar

        with mock.patch("screens.purchase_invoice._ItemDialog.exec") as mock_popup:
            bar.item_combo.lineEdit().setText("   ")
            handled = bar._on_item_field_tab_pressed()
            self.assertFalse(handled, "Empty input must allow normal tab traversal without opening popup")
            mock_popup.assert_not_called()

            bar.item_combo.lineEdit().setText("")
            handled = bar._on_item_field_tab_pressed()
            self.assertFalse(handled)
            mock_popup.assert_not_called()

    # ------------------------------------------------------------------
    # Scenario 2 & 3: Enter completely new item + Tab: existing New Item popup opens
    # and Item Name is automatically populated
    # ------------------------------------------------------------------
    def test_02_03_new_item_tab_opens_popup_with_prefilled_name(self):
        dlg = self._create_dialog()
        bar = dlg._entry_bar

        from screens.item_master import _ItemDialog

        captured_dialogs = []

        def mock_exec(*args, **kwargs):
            dialog_self = getattr(bar, "_last_new_item_dialog", None)
            captured_dialogs.append(dialog_self)
            if dialog_self:
                dialog_self.reject()
            return QDialog.Rejected

        with mock.patch.object(_ItemDialog, "exec", side_effect=mock_exec):
            bar.item_combo.lineEdit().setText("AMLO 5MG")
            handled = bar._on_item_field_tab_pressed()
            self.assertTrue(handled)
            self.assertEqual(len(captured_dialogs), 1)
            opened_dlg = captured_dialogs[0]
            self.assertIsNotNone(opened_dlg)
            # Verify exact name populated
            self.assertEqual(opened_dlg._item_name_edit.text(), "AMLO 5MG")

    # ------------------------------------------------------------------
    # Scenario 4 & 5: Save new item: saved in Item Master and automatically
    # selected in New Purchase with applicable details populated
    # ------------------------------------------------------------------
    def test_04_05_save_new_item_populates_in_purchase(self):
        dlg = self._create_dialog()
        bar = dlg._entry_bar

        from screens.item_master import _ItemDialog
        from database.item_dao import ItemDAO

        def mock_save_item(*args, **kwargs):
            dialog_self = bar._last_new_item_dialog
            # Simulate user filling out remaining fields
            idx_unit = dialog_self._unit_combo.findData(self.unit_tablet)
            dialog_self._unit_combo.setCurrentIndex(idx_unit)
            idx_comp = dialog_self._company_combo.findData(self.company_sun)
            dialog_self._company_combo.setCurrentIndex(idx_comp)
            dialog_self._pack_size_edit.setText("10x10")
            idx_tax = dialog_self._tax_structure_combo.findData("12")
            dialog_self._tax_structure_combo.setCurrentIndex(idx_tax)
            dialog_self._mrp_edit.setText("55.00")
            dialog_self._rate_edit.setText("40.00")
            dialog_self._on_save()
            return QDialog.Accepted

        with mock.patch.object(_ItemDialog, "exec", side_effect=mock_save_item):
            bar.item_combo.lineEdit().setText("TELMA 40MG")
            bar._on_item_field_tab_pressed()
            app.processEvents()

            # Verify saved in Item Master
            saved_item = ItemDAO.find_by_name("TELMA 40MG")
            self.assertIsNotNone(saved_item)
            self.assertEqual(saved_item["item_name"], "TELMA 40MG")
            self.assertEqual(saved_item["unit_name"], "TABLET")
            self.assertEqual(saved_item["company_name"], "SUN PHARMA")

            # Verify automatically selected in New Purchase
            self.assertEqual(bar.item_combo.currentData(), saved_item["id"])
            self.assertEqual(bar.item_combo.currentText(), "TELMA 40MG")
            self.assertEqual(bar.pack_edit.text(), "10x10")
            self.assertEqual(bar.gst_edit.text(), "12")
            self.assertEqual(bar.rate_edit.text(), "40.00")
            self.assertEqual(bar.mrp_edit.text(), "55.00")
            self.assertTrue(bar.pay_qty_edit.hasFocus())

    # ------------------------------------------------------------------
    # Scenario 6: Complete and save purchase: purchase references the correct item
    # ------------------------------------------------------------------
    def test_06_complete_and_save_purchase_references_new_item(self):
        from database.item_dao import ItemDAO
        from database.purchase_dao import PurchaseDAO
        from screens.item_master import _ItemDialog

        dlg = self._create_dialog()
        bar = dlg._entry_bar

        # Set header fields
        idx_sup = dlg.supplier_combo.findData(self.supplier_id)
        dlg.supplier_combo.setCurrentIndex(idx_sup)
        dlg.invoice_no_edit.setText("INV-2026-99")

        def mock_save_item(*args, **kwargs):
            dialog_self = bar._last_new_item_dialog
            idx_unit = dialog_self._unit_combo.findData(self.unit_tablet)
            dialog_self._unit_combo.setCurrentIndex(idx_unit)
            dialog_self._pack_size_edit.setText("10x15")
            idx_tax = dialog_self._tax_structure_combo.findData("5")
            dialog_self._tax_structure_combo.setCurrentIndex(idx_tax)
            dialog_self._mrp_edit.setText("80.00")
            dialog_self._rate_edit.setText("60.00")
            dialog_self._on_save()
            return QDialog.Accepted

        with mock.patch.object(_ItemDialog, "exec", side_effect=mock_save_item):
            bar.item_combo.lineEdit().setText("PANTOCID 40")
            bar._on_item_field_tab_pressed()
            app.processEvents()

        new_item = ItemDAO.find_by_name("PANTOCID 40")
        self.assertIsNotNone(new_item)

        # Enter quantity and batch details in New Purchase
        bar.pay_qty_edit.setText("20")
        bar.free_qty_edit.setText("2")
        bar.batch_edit.setText("PAN999")
        bar.expiry_edit.setText("12-28")
        bar.discount_edit.setText("2.0")

        # Add item to invoice table
        dlg._on_add_item()
        self.assertEqual(len(dlg._item_rows), 1)
        self.assertEqual(dlg._item_rows[0].item_id, new_item["id"])

        # Save purchase invoice
        dlg._on_save()
        self.assertTrue(dlg.was_saved)

        # Verify from database
        invoices = PurchaseDAO.get_all()
        self.assertEqual(len(invoices), 1)
        inv_id = invoices[0]["id"]
        full_inv = PurchaseDAO.get_by_id(inv_id)
        self.assertIsNotNone(full_inv)
        items = PurchaseDAO.get_invoice_items(inv_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item_id"], new_item["id"])
        self.assertEqual(items[0]["item_name"], "PANTOCID 40")
        self.assertEqual(items[0]["batch_no"], "PAN999")
        self.assertEqual(items[0]["pay_qty"], 20.0)

    # ------------------------------------------------------------------
    # Scenario 7: Verify new item appears in search and relevant inventory screens
    # ------------------------------------------------------------------
    def test_07_new_item_appears_in_item_master_search_and_stock(self):
        from database.item_dao import ItemDAO
        from database.stock_dao import StockDAO

        item = ItemDAO.find_by_name("PANTOCID 40")
        if not item:
            self.test_06_complete_and_save_purchase_references_new_item()
            item = ItemDAO.find_by_name("PANTOCID 40")

        # Search by substring
        results = ItemDAO.search("PANTO")
        self.assertTrue(any(r["item_name"] == "PANTOCID 40" for r in results))

        # Check get_all
        all_items = ItemDAO.get_all()
        self.assertTrue(any(r["item_name"] == "PANTOCID 40" for r in all_items))

        # Check stock batches created by purchase (22 packs * 150 pack_multiplier = 3300)
        batches = StockDAO.get_stock_batches_for_item(item["id"])
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["batch_no"], "PAN999")
        self.assertEqual(batches[0]["stock_qty"], 3300.0)

    # ------------------------------------------------------------------
    # Scenario 8: Cancel popup: previously entered purchase information remains intact
    # ------------------------------------------------------------------
    def test_08_cancel_popup_preserves_existing_purchase_data(self):
        dlg = self._create_dialog()
        bar = dlg._entry_bar

        # User fills supplier and invoice no
        idx_sup = dlg.supplier_combo.findData(self.supplier_id)
        dlg.supplier_combo.setCurrentIndex(idx_sup)
        dlg.invoice_no_edit.setText("PRESERVE-001")

        # User adds an existing item first
        bar.item_combo.set_selected_id(self.existing_item_id)
        dlg._on_item_changed(bar.item_combo.currentIndex())
        bar.pay_qty_edit.setText("10")
        bar.batch_edit.setText("EXISTING_BATCH")
        bar.expiry_edit.setText("01-28")
        dlg._on_add_item()
        self.assertEqual(len(dlg._item_rows), 1)

        from screens.item_master import _ItemDialog

        def mock_cancel_item(*args, **kwargs):
            dialog_self = bar._last_new_item_dialog
            if dialog_self:
                dialog_self.reject()
            return QDialog.Rejected

        with mock.patch.object(_ItemDialog, "exec", side_effect=mock_cancel_item):
            bar.item_combo.lineEdit().setText("ABANDONED MED")
            bar._on_item_field_tab_pressed()
            app.processEvents()

        # Check that header and table items are completely preserved
        self.assertEqual(dlg.supplier_combo.currentData(), self.supplier_id)
        self.assertEqual(dlg.invoice_no_edit.text(), "PRESERVE-001")
        self.assertEqual(len(dlg._item_rows), 1)
        self.assertEqual(dlg._item_rows[0].item_id, self.existing_item_id)

        # Check that ABANDONED MED was not saved to DB
        from database.item_dao import ItemDAO
        self.assertIsNone(ItemDAO.find_by_name("ABANDONED MED"))

        # Check that line edit retained entered text and focus
        self.assertEqual(bar.item_combo.lineEdit().text(), "ABANDONED MED")
        self.assertTrue(bar.item_combo.lineEdit().hasFocus())

    # ------------------------------------------------------------------
    # Scenario 9: Duplicate prevention rules
    # ------------------------------------------------------------------
    def test_09a_equivalent_item_case_and_spaces_selected_not_duplicated(self):
        dlg = self._create_dialog()
        bar = dlg._entry_bar

        from screens.item_master import _ItemDialog

        with mock.patch.object(_ItemDialog, "exec") as mock_exec:
            # "  paracetamol 500mg  " vs "PARACETAMOL 500MG"
            bar.item_combo.lineEdit().setText("  paracetamol 500mg  ")
            bar._on_item_field_tab_pressed()
            mock_exec.assert_not_called()
            self.assertEqual(bar.item_combo.currentData(), self.existing_item_id)

    def test_09b_dialog_rejects_same_name_same_unit_duplicate(self):
        from screens.item_master import _ItemDialog
        from database.item_dao import ItemDAO

        dialog = _ItemDialog(initial_name="PARACETAMOL 500MG")
        self.assertEqual(dialog._item_name_edit.text(), "PARACETAMOL 500MG")

        # Select TABLET (which already exists for PARACETAMOL 500MG)
        idx_tablet = dialog._unit_combo.findData(self.unit_tablet)
        dialog._unit_combo.setCurrentIndex(idx_tablet)

        dialog._on_save()
        self.assertFalse(dialog.was_saved)

    def test_09c_dialog_allows_same_name_different_unit(self):
        from screens.item_master import _ItemDialog
        from database.item_dao import ItemDAO

        dialog = _ItemDialog(initial_name="PARACETAMOL 500MG")
        # Select SYRUP (distinct unit)
        idx_syrup = dialog._unit_combo.findData(self.unit_syrup)
        dialog._unit_combo.setCurrentIndex(idx_syrup)

        dialog._on_save()
        self.assertTrue(dialog.was_saved)

        # Both records exist under different units
        records = [r for r in ItemDAO.get_all() if r["item_name"] == "PARACETAMOL 500MG"]
        self.assertEqual(len(records), 2)
        units = {r["unit_name"] for r in records}
        self.assertEqual(units, {"TABLET", "SYRUP"})

    # ------------------------------------------------------------------
    # Scenario 10: Verify QTest key clicks and eventFilter work cleanly
    # ------------------------------------------------------------------
    def test_10_keyboard_tab_event_navigation(self):
        dlg = self._create_dialog()
        bar = dlg._entry_bar

        from screens.item_master import _ItemDialog

        opened = []
        def mock_exec(*args, **kwargs):
            dialog_self = getattr(bar, "_last_new_item_dialog", None)
            opened.append(dialog_self)
            if dialog_self:
                dialog_self.reject()
            return QDialog.Rejected

        with mock.patch.object(_ItemDialog, "exec", side_effect=mock_exec):
            line = bar.item_combo.lineEdit()
            line.setFocus()
            line.setText("KEYBOARD NEW MED")
            QTest.keyClick(line, Qt.Key.Key_Tab)
            app.processEvents()

            self.assertEqual(len(opened), 1)
            self.assertEqual(opened[0]._item_name_edit.text(), "KEYBOARD NEW MED")


if __name__ == "__main__":
    unittest.main()
