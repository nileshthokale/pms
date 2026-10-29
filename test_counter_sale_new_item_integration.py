from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QShowEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog

app = QApplication.instance() or QApplication(sys.argv)

def _fresh_db(tag: str) -> str:
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_counter_new_item_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            try:
                os.remove(stale)
            except OSError:
                pass
    os.environ["PHARMACY_DB"] = db_path
    return db_path


class TestCounterSaleNewItemIntegration(unittest.TestCase):
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
        self._msgbox_patch = mock.patch.multiple(
            QMessageBox,
            warning=mock.DEFAULT,
            information=mock.DEFAULT,
            critical=mock.DEFAULT,
            question=mock.DEFAULT,
        )
        self._msgbox_patch.start()
        self.addCleanup(self._msgbox_patch.stop)

        from database.unit_dao import UnitDAO
        from database.company_dao import CompanyDAO
        from database.item_dao import ItemDAO

        self.unit_id = UnitDAO.insert("STRIP") if not UnitDAO.get_all() else UnitDAO.get_all()[0]["id"]
        self.comp_id = CompanyDAO.insert("SUN PHARMA", "SUN") if not CompanyDAO.get_all() else CompanyDAO.get_all()[0]["id"]

        existing = ItemDAO.find_by_name("PARACETAMOL 500MG")
        if existing:
            self.existing_item_id = existing["id"]
        else:
            self.existing_item_id = ItemDAO.insert(
                item_name="PARACETAMOL 500MG",
                unit_id=self.unit_id,
                company_id=self.comp_id,
                pack_size="10",
                tax_structure="12",
                mrp=35.0,
                rate=25.0,
            )

    def test_01_new_item_instantly_appears_on_show_event(self):
        """When an item is added in Item Master/Purchase, switching to Counter Sale (showEvent)
        instantly reloads the item list so the new tablet is immediately available."""
        from screens.counter_sale import CounterSalePage
        from database.item_dao import ItemDAO

        page = CounterSalePage()
        bar = page._sale_panel._entry_bar

        # Initially, brand new tablet is NOT in the list
        self.assertEqual(bar.item_combo.findText("CETIRIZINE 10MG"), -1)

        # Enter new tablet in database (simulating Item Master or Purchase save)
        new_id = ItemDAO.insert(
            item_name="CETIRIZINE 10MG",
            unit_id=self.unit_id,
            company_id=self.comp_id,
            pack_size="10",
            tax_structure="12",
            mrp=45.0,
            rate=30.0,
        )

        # Before showEvent, cache still has old state
        # Now trigger page showEvent (as MainWindow does when switching to Counter Sale)
        page.showEvent(QShowEvent())

        # The new tablet is now INSTANTLY in the item list!
        self.assertGreaterEqual(bar.item_combo.findText("CETIRIZINE 10MG"), 0)
        self.assertIn("cetirizine 10mg", bar._item_search_values)

    def test_02_new_item_instantly_appears_while_typing_search(self):
        """Even if Counter Sale is already visible without showEvent, typing a newly entered
        tablet name dynamically reloads from DB so it is found instead of showing 'No products found'."""
        from screens.counter_sale import _ItemEntryBar
        from database.item_dao import ItemDAO

        bar = _ItemEntryBar()
        bar.load_items()

        # Add tablet after initial load
        ItemDAO.insert(
            item_name="AZITHROMYCIN 500MG",
            unit_id=self.unit_id,
            company_id=self.comp_id,
            pack_size="3",
            tax_structure="12",
            mrp=120.0,
            rate=85.0,
        )

        # Type the new tablet name in the search field
        bar.item_combo.lineEdit().setText("AZITHRO")
        bar._on_item_search_text_changed("AZITHRO")

        # Must not show "No products found" and must contain the new tablet
        self.assertFalse(bar._has_no_match_row)
        self.assertIn("azithromycin 500mg", bar._item_search_values)
        self.assertGreaterEqual(bar.item_combo.findText("AZITHROMYCIN 500MG"), 0)

    def test_03_refresh_button_reloads_item_list(self):
        """Clicking Refresh in Counter Sale reloads the items from Item Master."""
        from screens.counter_sale import CounterSalePage
        from database.item_dao import ItemDAO

        page = CounterSalePage()
        bar = page._sale_panel._entry_bar

        ItemDAO.insert(
            item_name="IBUPROFEN 400MG",
            unit_id=self.unit_id,
            company_id=self.comp_id,
            pack_size="10",
            tax_structure="12",
            mrp=28.0,
            rate=18.0,
        )

        self.assertEqual(bar.item_combo.findText("IBUPROFEN 400MG"), -1)
        page._hist_refresh_btn.click()
        self.assertGreaterEqual(bar.item_combo.findText("IBUPROFEN 400MG"), 0)

    def test_04_tab_on_non_existent_item_opens_new_item_dialog_and_selects(self):
        """In Counter Sale, entering a tablet name that does not exist and pressing Tab
        automatically opens the existing New Item popup, prefills the name, saves it to Item Master,
        and automatically selects it in Counter Sale."""
        from screens.counter_sale import _ItemEntryBar
        from screens.item_master import _ItemDialog
        from database.item_dao import ItemDAO

        bar = _ItemEntryBar()
        bar.load_items()

        bar.item_combo.lineEdit().setText("METFORMIN 500MG")

        def mock_exec(*args, **kwargs):
            dialog = bar._last_new_item_dialog
            self.assertEqual(dialog._item_name_edit.text(), "METFORMIN 500MG")
            # Fill required fields in the real dialog
            u_idx = dialog._unit_combo.findData(self.unit_id)
            dialog._unit_combo.setCurrentIndex(u_idx)
            c_idx = dialog._company_combo.findData(self.comp_id)
            dialog._company_combo.setCurrentIndex(c_idx)
            tax_idx = dialog._tax_structure_combo.findData("12")
            if tax_idx >= 0:
                dialog._tax_structure_combo.setCurrentIndex(tax_idx)
            dialog._pack_size_edit.setText("10")
            dialog._mrp_edit.setText("50.0")
            dialog._rate_edit.setText("35.0")
            dialog._on_save()
            return QDialog.Accepted

        with mock.patch.object(_ItemDialog, "exec", side_effect=mock_exec):
            # Simulate Tab key press
            tab_event = QEvent(QEvent.KeyPress)
            tab_event.key = lambda: Qt.Key_Tab
            tab_event.modifiers = lambda: Qt.NoModifier

            consumed = bar.eventFilter(bar.item_combo.lineEdit(), tab_event)
            self.assertTrue(consumed)

        # Verify saved in Item Master
        saved_item = ItemDAO.find_by_name("METFORMIN 500MG")
        self.assertIsNotNone(saved_item)

        # Verify automatically selected in Counter Sale
        self.assertEqual(bar.item_combo.currentData(), saved_item["id"])
        self.assertEqual(bar.item_combo.currentText(), "METFORMIN 500MG")

    def test_05_tab_on_existing_item_selects_without_popup(self):
        """Entering an existing item and pressing Tab does not open the popup."""
        from screens.counter_sale import _ItemEntryBar
        from screens.item_master import _ItemDialog

        bar = _ItemEntryBar()
        bar.load_items()

        bar.item_combo.lineEdit().setText("PARACETAMOL 500MG")

        with mock.patch.object(_ItemDialog, "exec") as mock_exec:
            tab_event = QEvent(QEvent.KeyPress)
            tab_event.key = lambda: Qt.Key_Tab
            tab_event.modifiers = lambda: Qt.NoModifier

            consumed = bar.eventFilter(bar.item_combo.lineEdit(), tab_event)
            self.assertTrue(consumed)
            mock_exec.assert_not_called()

        self.assertEqual(bar.item_combo.currentData(), self.existing_item_id)

    def test_06_tab_on_empty_input_does_not_open_popup(self):
        """Tab on empty or whitespace input allows normal tab navigation."""
        from screens.counter_sale import _ItemEntryBar
        from screens.item_master import _ItemDialog

        bar = _ItemEntryBar()
        bar.load_items()

        bar.item_combo.lineEdit().setText("   ")

        with mock.patch.object(_ItemDialog, "exec") as mock_exec:
            tab_event = QEvent(QEvent.KeyPress)
            tab_event.key = lambda: Qt.Key_Tab
            tab_event.modifiers = lambda: Qt.NoModifier

            consumed = bar.eventFilter(bar.item_combo.lineEdit(), tab_event)
            self.assertFalse(consumed)
            mock_exec.assert_not_called()

    def test_07_cancelled_new_item_popup_preserves_text_and_focus(self):
        """Cancelling the New Item popup keeps the typed tablet name in the search box."""
        from screens.counter_sale import _ItemEntryBar
        from screens.item_master import _ItemDialog

        bar = _ItemEntryBar()
        bar.load_items()

        bar.item_combo.lineEdit().setText("CANCELLED TABLET")

        def mock_reject(*args, **kwargs):
            dialog = bar._last_new_item_dialog
            dialog.reject()
            return QDialog.Rejected

        with mock.patch.object(_ItemDialog, "exec", side_effect=mock_reject):
            tab_event = QEvent(QEvent.KeyPress)
            tab_event.key = lambda: Qt.Key_Tab
            tab_event.modifiers = lambda: Qt.NoModifier

            bar.eventFilter(bar.item_combo.lineEdit(), tab_event)

        self.assertEqual(bar.item_combo.lineEdit().text(), "CANCELLED TABLET")


if __name__ == "__main__":
    unittest.main()
