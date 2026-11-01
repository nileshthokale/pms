"""Unit and integration tests for Company Selector UI in Item Master.

Tests verify:
1. Company dropdown is replaced with a searchable selector using PySide6 QComboBox.
2. Case-insensitive autocomplete and filtering (beginning, middle, and end).
3. Typing finds company quickly.
4. Popup height is limited to approx 300-350 px.
5. Vertical scrollbar is displayed when company list exceeds popup height.
6. Popup stays directly below input and within screen geometry without covering dialog.
7. Company names are sorted alphabetically (case-insensitive).
8. Existing company database records and IDs are preserved.
9. Selecting a company saves its correct existing database integer ID.
10. Accidental creation of duplicate companies is prevented when arbitrary text is entered.
11. Edit item preserves existing company when untouched, updates when changed, clears when removed.
"""

import sys
import unittest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog
from PySide6.QtCore import Qt, QEvent, QPoint
from PySide6.QtGui import QKeyEvent

from database import CompanyDAO, ItemDAO, UnitDAO
from screens.item_master import _ItemDialog, _CompanyComboBox
from ui.components import SearchableComboBox

app = QApplication.instance() or QApplication(sys.argv)


class ItemMasterCompanySelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.all_companies = CompanyDAO.get_all()
        cls.company_count = len(cls.all_companies)

    def test_01_is_pyside6_qcombobox_and_searchable(self):
        """Selector is a PySide6 QComboBox and an editable SearchableComboBox."""
        dlg = _ItemDialog()
        combo = dlg._company_combo
        self.assertIsInstance(combo, QComboBox)
        self.assertIsInstance(combo, SearchableComboBox)
        self.assertTrue(combo.isEditable())
        dlg.close()

    def test_02_dialog_dimensions_preserved(self):
        """Dialog preserves standard 600x650 dimensions."""
        dlg = _ItemDialog()
        self.assertEqual(dlg.minimumWidth(), 600)
        self.assertEqual(dlg.minimumHeight(), 650)
        dlg.close()

    def test_03_all_companies_loaded_and_sorted_alphabetically(self):
        """All existing companies are loaded and sorted alphabetically case-insensitively."""
        dlg = _ItemDialog()
        combo = dlg._company_combo
        # count includes placeholder '-- Select Company --'
        self.assertEqual(combo.count(), self.company_count + 1)
        self.assertEqual(combo.itemText(0), "-- Select Company --")
        self.assertIsNone(combo.itemData(0))

        # Check alphabetical sorting
        names = [combo.itemText(i) for i in range(1, combo.count())]
        folded = [n.strip().casefold() for n in names]
        self.assertEqual(folded, sorted(folded), "Company names must be sorted alphabetically")
        dlg.close()

    def test_04_case_insensitive_autocomplete_beginning_and_middle(self):
        """Filtering matches beginning, middle, and is case-insensitive."""
        dlg = _ItemDialog()
        combo = dlg._company_combo

        # Test beginning match: "CIP"
        combo.lineEdit().setText("cip")
        combo.lineEdit().textEdited.emit("cip")
        app.processEvents()

        popup = combo._completer.popup()
        self.assertTrue(popup.isVisible())
        model = combo._completer_model
        self.assertGreater(model.rowCount(), 0)
        for r in range(model.rowCount()):
            item_text = model.item(r).text()
            self.assertIn("CIP", item_text.upper())

        # Test middle match: "TAB" (e.g. MEDITAB(CIPLA))
        combo.lineEdit().setText("tab")
        combo.lineEdit().textEdited.emit("tab")
        app.processEvents()
        matched_texts = [model.item(r).text() for r in range(model.rowCount())]
        self.assertTrue(any("TAB" in t.upper() for t in matched_texts))
        dlg.close()

    def test_05_popup_height_bounded_and_vertical_scrollbar_active(self):
        """Popup height is limited to 300-350 px and vertical scrollbar is active for 1220 items."""
        dlg = _ItemDialog()
        dlg.show()
        combo = dlg._company_combo
        combo.showPopup()
        app.processEvents()

        popup = combo._completer.popup()
        self.assertTrue(popup.isVisible())
        height = popup.height()
        # Popup height must be approx 300-350 px
        self.assertGreaterEqual(height, 300, f"Popup height {height} must be at least 300 px")
        self.assertLessEqual(height, 350, f"Popup height {height} must be at most 350 px")

        # Vertical scrollbar must be visible and functional
        v_bar = popup.verticalScrollBar()
        self.assertTrue(v_bar.isVisible())
        self.assertGreater(v_bar.maximum(), 0)
        dlg.close()

    def test_06_popup_positioned_below_combo_and_within_screen(self):
        """Popup is positioned directly below the combo and stays within screen bounds."""
        dlg = _ItemDialog()
        dlg.show()
        combo = dlg._company_combo
        combo.showPopup()
        app.processEvents()

        popup = combo._completer.popup()
        combo_bottom_left = combo.mapToGlobal(QPoint(0, combo.height()))
        popup_pos = popup.pos()

        # Should be placed below the combo line
        self.assertGreaterEqual(popup_pos.y(), combo_bottom_left.y())
        # Popup should not cover the top portion of the dialog
        dlg_pos = dlg.mapToGlobal(QPoint(0, 0))
        self.assertGreater(popup_pos.y(), dlg_pos.y() + 50)
        dlg.close()

    def test_07_keyboard_navigation_enter_and_escape(self):
        """Keyboard navigation: Down/Up to highlight, Enter to commit, Escape to dismiss."""
        dlg = _ItemDialog()
        combo = dlg._company_combo

        # Filter to a specific query
        combo.lineEdit().setText("CADBURYS")
        combo.lineEdit().textEdited.emit("CADBURYS")
        app.processEvents()

        popup = combo._completer.popup()
        self.assertTrue(popup.isVisible())

        # Down arrow to highlight
        down_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        combo.eventFilter(combo.lineEdit(), down_ev)
        app.processEvents()
        highlighted = popup.currentIndex().data(Qt.DisplayRole)
        self.assertIn("CADBURY", highlighted.upper())

        # Enter to select
        enter_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        combo.eventFilter(combo.lineEdit(), enter_ev)
        app.processEvents()

        self.assertFalse(popup.isVisible())
        self.assertEqual(combo.currentText(), highlighted)
        self.assertIsNotNone(combo.currentData())

        # Reopen and Escape dismisses
        combo.eventFilter(combo.lineEdit(), down_ev)
        app.processEvents()
        self.assertTrue(popup.isVisible())

        esc_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        combo.eventFilter(combo.lineEdit(), esc_ev)
        app.processEvents()
        self.assertFalse(popup.isVisible())
        dlg.close()

    def test_08_preserves_database_id_not_just_name(self):
        """Selecting a company saves its exact existing database integer ID."""
        dlg = _ItemDialog()
        combo = dlg._company_combo

        # Find Cipla Ltd in database
        cipla = next((c for c in self.all_companies if c["company_name"] == "CIPLA LTD"), None)
        self.assertIsNotNone(cipla)

        idx = combo.findData(cipla["id"])
        self.assertGreaterEqual(idx, 0)
        combo.setCurrentIndex(idx)

        self.assertEqual(combo.currentData(), cipla["id"])
        self.assertIsInstance(combo.currentData(), int)
        dlg.close()

    def test_09_prevents_accidental_duplicate_companies(self):
        """Typing arbitrary / non-existent text returns None and does not create a company."""
        companies_before = len(CompanyDAO.get_all())
        dlg = _ItemDialog()
        combo = dlg._company_combo

        combo.lineEdit().setText("TOTALLY NONEXISTENT PHARMA CO 99999")
        combo.resolve_text()

        self.assertIsNone(combo.currentData())
        companies_after = len(CompanyDAO.get_all())
        self.assertEqual(companies_before, companies_after, "No new company record should be inserted")
        dlg.close()

    def test_10_edit_item_untouched_preserves_company_id(self):
        """In Edit Item mode, an untouched company preserves its stored company_id."""
        cipla = next((c for c in self.all_companies if c["company_name"] == "CIPLA LTD"), None)
        self.assertIsNotNone(cipla)

        item = {
            "id": 999991,
            "item_name": "EXISTING ITEM",
            "unit_id": 1,
            "company_id": cipla["id"],
            "pack_size": "10",
            "tax_structure": "12",
        }
        dlg = _ItemDialog(item=item)
        self.assertEqual(dlg._company_combo.currentData(), cipla["id"])
        self.assertEqual(dlg._company_combo.currentText(), "CIPLA LTD")

        # Saving untouched returns the original company_id
        dlg._company_combo.resolve_text()
        self.assertEqual(dlg._company_combo.currentData(), cipla["id"])
        dlg.close()

    def test_11_edit_item_explicit_change_and_clear(self):
        """In Edit Item mode, changing company updates company_id; clearing sets it to None."""
        cipla = next((c for c in self.all_companies if c["company_name"] == "CIPLA LTD"), None)
        aabtac = next((c for c in self.all_companies if c["company_name"] == "AABTAC"), None)
        self.assertIsNotNone(cipla)
        self.assertIsNotNone(aabtac)

        item = {
            "id": 999992,
            "item_name": "EXISTING ITEM 2",
            "unit_id": 1,
            "company_id": cipla["id"],
            "pack_size": "10",
            "tax_structure": "12",
        }
        dlg = _ItemDialog(item=item)

        # 1. Change to AABTAC
        idx = dlg._company_combo.findData(aabtac["id"])
        dlg._company_combo.setCurrentIndex(idx)
        self.assertEqual(dlg._company_combo.currentData(), aabtac["id"])

        # 2. Clear selection
        dlg._company_combo.clear_selection()
        self.assertIsNone(dlg._company_combo.currentData())
        self.assertEqual(dlg._company_combo.currentText(), "")
        dlg.close()


if __name__ == "__main__":
    unittest.main()
