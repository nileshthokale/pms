"""Automated regression and unit tests for SearchableComboBox autocomplete dropdown.

Verifies:
1. First-character typing immediately shows dropdown suggestions directly BELOW the input field.
2. Dynamic filtering as characters are typed (case-insensitive substring/contains matching).
3. Popup placement: positioned beneath the input field, not obscuring the line edit.
4. "No matching records found" state: displayed as disabled item when query has no matches;
   cannot be selected by Enter or mouse.
5. Keyboard navigation: Down/Up to highlight, Enter to commit, Escape to dismiss.
6. Mouse selection: clicking an item selects it, commits ID, and closes popup.
7. Preserves currentData(), currentText(), and emits selection_changed signal.
8. Single-click selects all text in lineEdit for easy replacement.
9. Debit Note integration:
   - Supplier combo displays matching suppliers on first char, sets supplier ID.
   - Item combo displays matching medicines on first char, sets item ID and populates batches.
10. Credit Note integration:
   - Customer combo displays matching customers on first char, sets customer ID.
   - Item combo displays matching medicines on first char, sets item ID and populates batches.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QEvent, QPoint, QPointF
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

app = QApplication.instance() or QApplication(sys.argv)

from database.connection import init_database
from ui.components import SearchableComboBox
from screens.debit_note import _DebitNoteEntryDialog
from screens.credit_note import _CreditNoteEntryDialog


class TestAutocompleteDropdown(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database()

    def setUp(self):
        self.window = QWidget()
        self.window.resize(600, 400)
        self.layout = QVBoxLayout(self.window)
        self.combo = SearchableComboBox(placeholder="Type to search...")
        self.layout.addWidget(self.combo)
        self.window.show()
        app.processEvents()

    def tearDown(self):
        self.window.close()
        app.processEvents()

    def test_01_empty_initial_state(self):
        """Initial combo should be unselected and lineEdit empty."""
        self.assertIsNone(self.combo.currentData())
        self.assertEqual(self.combo.lineEdit().text(), "")
        self.assertFalse(self.combo._completer.popup().isVisible())

    def test_02_first_character_shows_dropdown(self):
        """Typing a single character must immediately open the completion popup."""
        items = [
            (1, "Amoxicillin 500mg"),
            (2, "Azithromycin 250mg"),
            (3, "Paracetamol 650mg"),
            (4, "Pantoprazole 40mg"),
        ]
        self.combo.populate(items)

        # Simulate typing 'a'
        line = self.combo.lineEdit()
        line.setText("a")
        line.textEdited.emit("a")
        app.processEvents()

        popup = self.combo._completer.popup()
        self.assertTrue(popup.isVisible(), "Popup should be visible on first character")
        # Should have matching items ('Amoxicillin', 'Azithromycin', 'Paracetamol', 'Pantoprazole' all contain 'a')
        model = self.combo._completer_model
        self.assertEqual(model.rowCount(), 4)

    def test_03_case_insensitive_partial_search(self):
        """Typing query filters case-insensitively using contains/partial match."""
        items = [
            (10, "Crocin Advance 500mg"),
            (20, "Dolo 650mg"),
            (30, "Paracetamol Tab"),
            (40, "Azithral 500"),
        ]
        self.combo.populate(items)

        line = self.combo.lineEdit()
        # Search "650" - only Dolo 650mg contains 650
        line.setText("650")
        line.textEdited.emit("650")
        app.processEvents()

        model = self.combo._completer_model
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.item(0).data(Qt.UserRole), 20)
        self.assertIn("Dolo 650mg", model.item(0).text())

        # Search "para" - Crocin Advance does not contain "para", Paracetamol Tab does
        line.setText("para")
        line.textEdited.emit("para")
        app.processEvents()

        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.item(0).data(Qt.UserRole), 30)

    def test_04_no_results_displays_disabled_state(self):
        """When query has no matches, show 'No matching records found' disabled item."""
        items = [
            (1, "Aspirin 75mg"),
            (2, "Atorvastatin 10mg"),
        ]
        self.combo.populate(items)

        line = self.combo.lineEdit()
        query = "NONEXISTENT_ITEM_XYZ"
        line.setText(query)
        line.textEdited.emit(query)
        app.processEvents()

        popup = self.combo._completer.popup()
        self.assertTrue(popup.isVisible(), "Popup should show no-match indicator")

        model = self.combo._completer_model
        self.assertEqual(model.rowCount(), 1)
        item = model.item(0)
        self.assertIn("No matching records found", item.text())
        self.assertIn(query, item.text())
        self.assertIsNone(item.data(Qt.UserRole))
        # Ensure item is disabled
        self.assertFalse(bool(item.flags() & Qt.ItemIsEnabled))

        # Pressing Enter on disabled item must not select anything
        key_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.combo.eventFilter(line, key_event)
        app.processEvents()

        self.assertIsNone(self.combo.currentData())

    def test_05_keyboard_navigation_and_enter_selection(self):
        """Down arrow highlights first valid item and Enter commits selection."""
        items = [
            (101, "Cefixime 200mg"),
            (102, "Ciprofloxacin 500mg"),
            (103, "Clavam 625mg"),
        ]
        self.combo.populate(items)

        selected_ids = []
        self.combo.selection_changed.connect(selected_ids.append)

        line = self.combo.lineEdit()
        line.setText("cip")
        line.textEdited.emit("cip")
        app.processEvents()

        popup = self.combo._completer.popup()
        self.assertTrue(popup.isVisible())

        # Press Down arrow to highlight
        down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        self.combo.eventFilter(line, down_event)
        app.processEvents()

        # Press Enter to commit
        enter_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.combo.eventFilter(line, enter_event)
        app.processEvents()

        self.assertFalse(popup.isVisible(), "Popup should close after selection")
        self.assertEqual(self.combo.currentData(), 102)
        self.assertEqual(self.combo.currentText(), "Ciprofloxacin 500mg")
        self.assertIn(102, selected_ids)

    def test_06_escape_dismisses_popup(self):
        """Pressing Escape dismisses the popup without changing selection."""
        items = [(1, "Med A"), (2, "Med B")]
        self.combo.populate(items)

        line = self.combo.lineEdit()
        line.setText("m")
        line.textEdited.emit("m")
        app.processEvents()

        popup = self.combo._completer.popup()
        self.assertTrue(popup.isVisible())

        esc_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        self.combo.eventFilter(line, esc_event)
        app.processEvents()

        self.assertFalse(popup.isVisible())
        self.assertIsNone(self.combo.currentData())

    def test_07_mouse_click_selection(self):
        """Clicking an item in the popup commits the selection."""
        items = [
            (501, "Metformin 500mg"),
            (502, "Metoprolol 25mg"),
        ]
        self.combo.populate(items)

        line = self.combo.lineEdit()
        line.setText("met")
        line.textEdited.emit("met")
        app.processEvents()

        model = self.combo._completer_model
        index_to_click = model.index(1, 0)  # Metoprolol 25mg
        self.combo._on_completer_index_activated(index_to_click)
        app.processEvents()

        self.assertEqual(self.combo.currentData(), 502)
        self.assertEqual(self.combo.currentText(), "Metoprolol 25mg")

    def test_08_popup_positioned_below_field(self):
        """Dropdown popup must appear directly beneath the input field."""
        items = [(1, "Medicine 1"), (2, "Medicine 2")]
        self.combo.populate(items)

        line = self.combo.lineEdit()
        line.setText("m")
        line.textEdited.emit("m")
        app.processEvents()

        popup = self.combo._completer.popup()
        self.assertTrue(popup.isVisible())

        combo_pos = self.combo.mapToGlobal(QPoint(0, 0))
        combo_bottom = combo_pos.y() + self.combo.height()
        popup_pos = popup.pos()

        # Popup Y should be at or just below combo bottom
        self.assertGreaterEqual(
            popup_pos.y(),
            combo_bottom - 2,
            f"Popup y ({popup_pos.y()}) should be below combo bottom ({combo_bottom})"
        )

    def test_09_debit_note_dialog_supplier_and_item_autocomplete(self):
        """Test DebitNote dialog supplier and item autocomplete with live database records."""
        dlg = _DebitNoteEntryDialog()
        dlg.resize(900, 600)
        dlg.show()
        app.processEvents()

        try:
            # 1. Supplier autocomplete
            sup_line = dlg.supplier_combo.lineEdit()
            sup_line.setText("a")
            sup_line.textEdited.emit("a")
            app.processEvents()

            sup_popup = dlg.supplier_combo._completer.popup()
            self.assertTrue(sup_popup.isVisible(), "DebitNote supplier popup should be visible on typing 'a'")
            self.assertGreater(dlg.supplier_combo._completer_model.rowCount(), 0)

            # Select first supplier from completer model
            first_idx = dlg.supplier_combo._completer_model.index(0, 0)
            sup_id = first_idx.data(Qt.UserRole)
            self.assertIsNotNone(sup_id)
            dlg.supplier_combo._on_completer_index_activated(first_idx)
            app.processEvents()

            self.assertEqual(dlg.supplier_combo.currentData(), sup_id)

            # 2. Item autocomplete in entry bar
            item_combo = dlg._entry_bar.item_combo
            item_line = item_combo.lineEdit()
            item_line.setText("z")
            item_line.textEdited.emit("z")
            app.processEvents()

            item_popup = item_combo._completer.popup()
            self.assertTrue(item_popup.isVisible(), "DebitNote item popup should be visible on typing 'z'")
            self.assertGreater(item_combo._completer_model.rowCount(), 0)

            # Select first matching medicine
            first_item_idx = item_combo._completer_model.index(0, 0)
            item_id = first_item_idx.data(Qt.UserRole)
            self.assertIsNotNone(item_id)
            item_combo._on_completer_index_activated(first_item_idx)
            app.processEvents()

            self.assertEqual(item_combo.currentData(), item_id)
            # Item changed must trigger batch loading
            self.assertGreaterEqual(dlg._entry_bar.batch_combo.count(), 1)
        finally:
            dlg.close()
            app.processEvents()

    def test_10_credit_note_dialog_customer_and_item_autocomplete(self):
        """Test CreditNote dialog customer and item autocomplete with live database records."""
        dlg = _CreditNoteEntryDialog()
        dlg.resize(900, 600)
        dlg.show()
        app.processEvents()

        try:
            # 1. Customer autocomplete
            cust_line = dlg.customer_combo.lineEdit()
            # Customer should default to WALKIN (159)
            self.assertEqual(dlg.customer_combo.currentData(), 159)

            # Type 's' to search other customers
            cust_line.setText("s")
            cust_line.textEdited.emit("s")
            app.processEvents()

            cust_popup = dlg.customer_combo._completer.popup()
            self.assertTrue(cust_popup.isVisible(), "CreditNote customer popup should be visible on typing 's'")
            self.assertGreater(dlg.customer_combo._completer_model.rowCount(), 0)

            # 2. Item autocomplete in entry bar
            item_combo = dlg._entry_bar.item_combo
            item_line = item_combo.lineEdit()
            item_line.setText("p")
            item_line.textEdited.emit("p")
            app.processEvents()

            item_popup = item_combo._completer.popup()
            self.assertTrue(item_popup.isVisible(), "CreditNote item popup should be visible on typing 'p'")
            self.assertGreater(item_combo._completer_model.rowCount(), 0)

            first_item_idx = item_combo._completer_model.index(0, 0)
            item_id = first_item_idx.data(Qt.UserRole)
            self.assertIsNotNone(item_id)
            item_combo._on_completer_index_activated(first_item_idx)
            app.processEvents()

            self.assertEqual(item_combo.currentData(), item_id)
            self.assertGreaterEqual(dlg._entry_bar.batch_combo.count(), 1)
        finally:
            dlg.close()
            app.processEvents()

    def test_11_mouse_press_selects_all_text(self):
        """Clicking on lineEdit selects all text so typing immediately replaces it."""
        items = [("Medicine A", 1), ("Medicine B", 2)]
        self.combo.populate(items)
        self.combo.setCurrentIndex(0)
        app.processEvents()

        line = self.combo.lineEdit()
        self.assertEqual(line.text(), "Medicine A")

        # Simulate MouseButtonPress event
        press_event = QMouseEvent(QEvent.MouseButtonPress, QPointF(5.0, 5.0), QPointF(5.0, 5.0), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        self.combo.eventFilter(line, press_event)
        app.processEvents()

        self.assertTrue(line.hasSelectedText())
        self.assertEqual(line.selectedText(), "Medicine A")

    def test_12_arbitrary_unmatched_text_rejected(self):
        """Arbitrary text that does not match any record results in None currentData."""
        items = [("Paracetamol 500mg", 10), ("Amoxicillin 250mg", 20)]
        self.combo.populate(items)

        line = self.combo.lineEdit()
        line.setText("Unknown Drug 999")
        line.editingFinished.emit()
        app.processEvents()

        self.assertIsNone(self.combo.currentData())
        self.assertFalse(self.combo.resolve_text())

    def test_13_clear_selection_resets_state(self):
        """clear_selection resets index to -1 and lineEdit to empty string."""
        items = [("Medicine A", 1)]
        self.combo.populate(items)
        self.combo.setCurrentIndex(0)
        self.assertEqual(self.combo.currentData(), 1)

        self.combo.clear_selection()
        app.processEvents()

        self.assertIsNone(self.combo.currentData())
        self.assertEqual(self.combo.lineEdit().text(), "")

    def test_14_filter_bars_in_debit_and_credit_pages(self):
        """Filter bars in DebitNotePage and CreditNotePage support autocomplete filtering."""
        from screens.debit_note import DebitNotePage
        from screens.credit_note import CreditNotePage

        dn_page = DebitNotePage()
        cn_page = CreditNotePage()
        dn_page.show()
        cn_page.show()
        app.processEvents()

        try:
            # Debit Note Page filter
            dn_sup_filter = dn_page._filter_supplier
            dn_sup_filter.lineEdit().setText("a")
            dn_sup_filter.lineEdit().textEdited.emit("a")
            app.processEvents()
            self.assertTrue(dn_sup_filter._completer.popup().isVisible())

            # Credit Note Page filter
            cn_cust_filter = cn_page._filter_customer
            cn_cust_filter.lineEdit().setText("a")
            cn_cust_filter.lineEdit().textEdited.emit("a")
            app.processEvents()
            self.assertTrue(cn_cust_filter._completer.popup().isVisible())
        finally:
            dn_page.close()
            cn_page.close()
            app.processEvents()


    def test_15_typing_alone_does_not_commit_suggestion(self):
        """Typing partial text alone must not automatically commit the first suggestion."""
        items = [("Paracetamol 650mg", 101), ("Paracetamol 500mg", 102), ("Amoxicillin 250mg", 103)]
        self.combo.populate(items)

        line = self.combo.lineEdit()
        line.setText("Para")
        line.textEdited.emit("Para")
        app.processEvents()

        # The popup is open with matching suggestions, but user hasn't selected it
        self.assertTrue(self.combo._completer.popup().isVisible())
        self.assertIsNone(self.combo.currentData(), "Typing alone should not commit data")

        # Now simulate editingFinished without pressing Enter on suggestion
        line.editingFinished.emit()
        app.processEvents()

        self.assertIsNone(self.combo.currentData(), "Losing focus with partial text must not commit item")

    def test_16_down_arrow_or_show_popup_on_empty_shows_all_suggestions(self):
        """Down arrow or showPopup() on empty field displays all suggestions."""
        items = [("Cust 1", 1), ("Cust 2", 2), ("Cust 3", 3)]
        self.combo.populate(items)

        self.combo.clear_selection()
        app.processEvents()

        self.combo.showPopup()
        app.processEvents()

        popup = self.combo._completer.popup()
        self.assertTrue(popup.isVisible(), "Popup should open on showPopup even if field is empty")
        self.assertEqual(self.combo._completer_model.rowCount(), 3)

        # Pressing Down arrow on empty field should also open suggestions
        popup.hide()
        app.processEvents()
        self.assertFalse(popup.isVisible())

        down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        self.combo.eventFilter(self.combo.lineEdit(), down_event)
        app.processEvents()

        self.assertTrue(popup.isVisible(), "Down arrow should open suggestions on empty field")
        self.assertEqual(self.combo._completer_model.rowCount(), 3)

    def test_17_walkin_selection_and_persistence_in_credit_note(self):
        """Credit Note selects WALKIN by default and allows changing to another customer and back."""
        dlg = _CreditNoteEntryDialog()
        dlg.show()
        app.processEvents()

        try:
            # WALKIN (159) is selected by default
            self.assertEqual(dlg.customer_combo.currentData(), 159)
            self.assertIn("WALKIN", dlg.customer_combo.currentText().upper())

            # FocusIn on customer combo selects all text
            focus_event = QEvent(QEvent.FocusIn)
            dlg.customer_combo.eventFilter(dlg.customer_combo.lineEdit(), focus_event)
            app.processEvents()
            self.assertTrue(dlg.customer_combo.lineEdit().hasSelectedText())

            # Search another customer
            cust_line = dlg.customer_combo.lineEdit()
            cust_line.setText("s")
            cust_line.textEdited.emit("s")
            app.processEvents()

            c_popup = dlg.customer_combo._completer.popup()
            self.assertTrue(c_popup.isVisible())
            self.assertGreater(dlg.customer_combo._completer_model.rowCount(), 0)

            # Select the first matching customer
            cand_idx = dlg.customer_combo._completer_model.index(0, 0)
            other_id = cand_idx.data(Qt.UserRole)
            self.assertIsNotNone(other_id)
            dlg.customer_combo._on_completer_index_activated(cand_idx)
            app.processEvents()

            self.assertEqual(dlg.customer_combo.currentData(), other_id)
            self.assertEqual(dlg._entry_bar._customer_id, other_id)

            # Change back to WALKIN via set_selected_id
            dlg.customer_combo.set_selected_id(159)
            app.processEvents()
            self.assertEqual(dlg.customer_combo.currentData(), 159)
            self.assertEqual(dlg._entry_bar._customer_id, 159)
        finally:
            dlg.close()
            app.processEvents()

    def test_18_drug_substitute_dialog_remains_functional(self):
        """DrugSubstituteDialog continues to function properly without regressions."""
        from screens.counter_sale_actions import DrugSubstituteDialog
        dlg = DrugSubstituteDialog()
        dlg.show()
        app.processEvents()

        try:
            self.assertIsNotNone(dlg.drug_combo)
            self.assertGreater(dlg.drug_combo.count(), 0)
            self.assertTrue(dlg.show_btn.isEnabled())
        finally:
            dlg.close()
            app.processEvents()


    def test_19_batch_combo_live_filtering_and_typing(self):
        """Typing in batch combo filters batches dynamically on first character."""
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        app.processEvents()

        try:
            # Select item BIO D3 PLUS (id 951) which has multiple batches
            idx = dlg._entry_bar.item_combo.findData(951)
            dlg._entry_bar.item_combo.setCurrentIndex(idx)
            app.processEvents()

            bcombo = dlg._entry_bar.batch_combo
            self.assertGreater(bcombo.count(), 1)

            # Type 'KBC'
            bline = bcombo.lineEdit()
            bline.setText("KBC")
            bline.textEdited.emit("KBC")
            app.processEvents()

            popup = bcombo._completer.popup()
            self.assertTrue(popup.isVisible(), "Batch popup should be visible on typing")
            self.assertGreater(bcombo._completer_model.rowCount(), 0)
            for r in range(bcombo._completer_model.rowCount()):
                self.assertIn("KBC", bcombo._completer_model.item(r).text().upper())
        finally:
            dlg.close()
            app.processEvents()

    def test_20_batch_combo_exact_batch_selection(self):
        """Selecting a batch populates expiry, pack size, rate, and MRP."""
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        app.processEvents()

        try:
            idx = dlg._entry_bar.item_combo.findData(951)
            dlg._entry_bar.item_combo.setCurrentIndex(idx)
            app.processEvents()

            bcombo = dlg._entry_bar.batch_combo
            bline = bcombo.lineEdit()
            bline.setText("ACB2024A")
            bline.textEdited.emit("ACB2024A")
            app.processEvents()

            # Select the matching item
            first_idx = bcombo._completer_model.index(0, 0)
            bcombo._on_completer_index_activated(first_idx)
            app.processEvents()

            b = bcombo.currentData()
            self.assertIsNotNone(b)
            self.assertEqual(b["batch_no"], "ACB2024A")
            self.assertEqual(dlg._entry_bar.expiry_edit.text(), b["expiry"])
            self.assertEqual(dlg._entry_bar.pack_edit.text(), str(b["pack_size"]))
            self.assertEqual(dlg._entry_bar.rate_edit.text(), f"{b['purchase_rate']:.2f}")
            self.assertEqual(dlg._entry_bar.mrp_edit.text(), f"{b['mrp']:.2f}")
        finally:
            dlg.close()
            app.processEvents()

    def test_21_batch_combo_similar_batch_numbers_identity_preservation(self):
        """Selecting between similar batch numbers preserves the exact batch identity."""
        combo = SearchableComboBox(placeholder="-- Select Batch --", min_width=320)
        combo.resize(200, 32)
        combo.show()
        app.processEvents()

        b1 = {"id": 1001, "batch_no": "BATCH-1", "expiry": "2027-01-01", "mrp": 50.0}
        b2 = {"id": 1002, "batch_no": "BATCH-10", "expiry": "2028-01-01", "mrp": 60.0}

        combo.addItem("BATCH-1 (Exp: 2027-01-01, Stk: 5)", b1, raw_name="BATCH-1")
        combo.addItem("BATCH-10 (Exp: 2028-01-01, Stk: 10)", b2, raw_name="BATCH-10")

        # Type 'BATCH-10'
        line = combo.lineEdit()
        line.setText("BATCH-10")
        line.textEdited.emit("BATCH-10")
        app.processEvents()

        self.assertEqual(combo._completer_model.rowCount(), 1)
        matched_idx = combo._completer_model.index(0, 0)
        combo._on_completer_index_activated(matched_idx)
        app.processEvents()

        selected = combo.currentData()
        self.assertIsNotNone(selected)
        self.assertEqual(selected["id"], 1002)
        self.assertEqual(selected["batch_no"], "BATCH-10")
        combo.close()

    def test_22_batch_combo_expired_batches_and_filtering(self):
        """Expired batches show [EXP] badge and filter correctly when Expired Only is toggled."""
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        app.processEvents()

        try:
            idx = dlg._entry_bar.item_combo.findData(951)
            dlg._entry_bar.item_combo.setCurrentIndex(idx)
            app.processEvents()

            bcombo = dlg._entry_bar.batch_combo
            total_count = bcombo.count()

            # Check expired only
            dlg._entry_bar.expired_only_cb.setChecked(True)
            app.processEvents()

            expired_count = bcombo.count()
            self.assertLessEqual(expired_count, total_count)
            # All remaining batches (excluding index 0 placeholder) must be expired
            for i in range(1, expired_count):
                b = bcombo.itemData(i)
                self.assertTrue(b.get("is_expired"))
                self.assertIn("[EXP]", bcombo.itemText(i))
        finally:
            dlg.close()
            app.processEvents()

    def test_23_batch_combo_no_results_and_rejection_of_invalid_input(self):
        """Typing a non-existent batch shows 'No matching records found' and rejects invalid input."""
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        app.processEvents()

        try:
            idx = dlg._entry_bar.item_combo.findData(951)
            dlg._entry_bar.item_combo.setCurrentIndex(idx)
            app.processEvents()

            bcombo = dlg._entry_bar.batch_combo
            bline = bcombo.lineEdit()

            # Type non-existent query
            bline.setText("INVALID_BATCH_XYZ_999")
            bline.textEdited.emit("INVALID_BATCH_XYZ_999")
            app.processEvents()

            model = bcombo._completer_model
            self.assertEqual(model.rowCount(), 1)
            self.assertIn("No matching records found", model.item(0).text())
            self.assertFalse(model.item(0).isEnabled())

            # Press Enter on invalid query
            enter_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
            bcombo.eventFilter(bline, enter_ev)
            app.processEvents()

            self.assertIsNone(bcombo.currentData(), "Invalid typed batch must not be accepted")
        finally:
            dlg.close()
            app.processEvents()

    def test_24_batch_combo_popup_geometry_and_sizing(self):
        """Batch dropdown popup must be constrained to 8 rows max and positioned below the field."""
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        app.processEvents()

        try:
            idx = dlg._entry_bar.item_combo.findData(951)
            dlg._entry_bar.item_combo.setCurrentIndex(idx)
            app.processEvents()

            bcombo = dlg._entry_bar.batch_combo
            bline = bcombo.lineEdit()
            bline.setText("KBC")
            bline.textEdited.emit("KBC")
            app.processEvents()

            popup = bcombo._completer.popup()
            self.assertTrue(popup.isVisible())

            # Sizing check: height should be <= 8 rows (~250px)
            self.assertLessEqual(popup.height(), 270)
            self.assertGreaterEqual(popup.width(), 300)

            # Positioning check: popup top should be below or at combo bottom
            combo_pos = bcombo.mapToGlobal(QPoint(0, 0))
            combo_bottom = combo_pos.y() + bcombo.height()
            self.assertGreaterEqual(popup.pos().y(), combo_bottom - 2)
        finally:
            dlg.close()
            app.processEvents()

    def test_25_credit_note_batch_combo_integration(self):
        """Credit Note form reuses the same searchable batch selector safely."""
        dlg = _CreditNoteEntryDialog()
        dlg.show()
        app.processEvents()

        try:
            idx = dlg._entry_bar.item_combo.findData(951)
            dlg._entry_bar.item_combo.setCurrentIndex(idx)
            app.processEvents()

            bcombo = dlg._entry_bar.batch_combo
            self.assertIsInstance(bcombo, SearchableComboBox)
            self.assertGreater(bcombo.count(), 1)

            bline = bcombo.lineEdit()
            bline.setText("ACB2024A")
            bline.textEdited.emit("ACB2024A")
            app.processEvents()

            first_idx = bcombo._completer_model.index(0, 0)
            bcombo._on_completer_index_activated(first_idx)
            app.processEvents()

            b = bcombo.currentData()
            self.assertIsNotNone(b)
            self.assertEqual(b["batch_no"], "ACB2024A")
            self.assertEqual(dlg._entry_bar.expiry_edit.text(), b["expiry"])
        finally:
            dlg.close()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
