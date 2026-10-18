"""Tests for Purchase Invoice Item Fields: Pack, GST, Batch Autocomplete, and Full Expiry Date.

Verifies:
1. Pack and GST fields are read-only and automatically update when item selection changes.
2. Batch number autocomplete: dynamic suggestions on first character, item-specific suggestions,
   selection populates expiry, rate, MRP, arrow key navigation, Tab dismissal, and arbitrary new batch entry preservation.
3. Expiry date displays as DD-MM-YYYY with date picker control, accepts clear keyboard text entry, and stores as YYYY-MM-DD.
4. Item switching refreshes master rate, MRP, pack, GST, and resets batch/expiry.
5. Workflow arithmetic, free qty, GST, and totals are preserved.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from screens.purchase_invoice import (
    _ItemEntryBar,
    _InvoiceDialog,
    BatchLineEdit,
    ExpiryDateEdit,
    parse_expiry_to_date,
    format_expiry_display,
    normalize_expiry_db,
    _InvoiceItemRow,
)
from database.purchase_dao import PurchaseDAO


class TestExpiryHelpers(unittest.TestCase):
    """Unit tests for date conversion helpers."""

    def test_parse_iso(self):
        d = parse_expiry_to_date("2029-02-28")
        self.assertEqual(d, date(2029, 2, 28))

    def test_parse_dmy(self):
        d = parse_expiry_to_date("28-02-2029")
        self.assertEqual(d, date(2029, 2, 28))

    def test_parse_mmyy_legacy(self):
        d = parse_expiry_to_date("08/28")
        self.assertEqual(d, date(2028, 8, 31))

    def test_parse_leap_year_mmyy(self):
        # 2028 is a leap year; February has 29 days
        d = parse_expiry_to_date("02/28")
        self.assertEqual(d, date(2028, 2, 29))

    def test_parse_dash_mmyy(self):
        self.assertEqual(parse_expiry_to_date("12-28"), date(2028, 12, 31))
        self.assertEqual(parse_expiry_to_date("12-2028"), date(2028, 12, 31))

    def test_parse_continuous_digits(self):
        self.assertEqual(parse_expiry_to_date("28022029"), date(2029, 2, 28))
        self.assertEqual(parse_expiry_to_date("280229"), date(2029, 2, 28))
        self.assertEqual(parse_expiry_to_date("0229"), date(2029, 2, 28))
        self.assertEqual(parse_expiry_to_date("1228"), date(2028, 12, 31))

    def test_parse_dot_separators(self):
        self.assertEqual(parse_expiry_to_date("28.02.2029"), date(2029, 2, 28))
        self.assertEqual(parse_expiry_to_date("12.28"), date(2028, 12, 31))

    def test_parse_empty(self):
        self.assertIsNone(parse_expiry_to_date(""))
        self.assertIsNone(parse_expiry_to_date(None))
        self.assertIsNone(parse_expiry_to_date("DD-MM-YYYY"))
        self.assertIsNone(parse_expiry_to_date("MM/YY"))

    def test_format_expiry_display(self):
        self.assertEqual(format_expiry_display("2029-02-28"), "28-02-2029")
        self.assertEqual(format_expiry_display("28-02-2029"), "28-02-2029")
        self.assertEqual(format_expiry_display("08/28"), "31-08-2028")
        self.assertEqual(format_expiry_display("28022029"), "28-02-2029")
        self.assertEqual(format_expiry_display(""), "")

    def test_normalize_expiry_db(self):
        self.assertEqual(normalize_expiry_db("28-02-2029"), "2029-02-28")
        self.assertEqual(normalize_expiry_db("2029-02-28"), "2029-02-28")
        self.assertEqual(normalize_expiry_db("08/28"), "2028-08-31")
        self.assertEqual(normalize_expiry_db("28022029"), "2029-02-28")
        self.assertEqual(normalize_expiry_db(""), "")


class TestExpiryDateEditControl(unittest.TestCase):
    """Unit tests for ExpiryDateEdit widget."""

    def setUp(self):
        self.edit = ExpiryDateEdit(width=110)

    def test_calendar_popup_enabled(self):
        self.assertTrue(self.edit.calendarPopup())

    def test_display_format_dd_mm_yyyy(self):
        self.assertEqual(self.edit.displayFormat(), "dd-MM-yyyy")

    def test_initial_state_empty(self):
        self.assertEqual(self.edit.text(), "")
        self.assertEqual(self.edit.iso_date(), "")

    def test_set_text_iso(self):
        self.edit.setText("2029-02-28")
        self.assertEqual(self.edit.text(), "28-02-2029")
        self.assertEqual(self.edit.iso_date(), "2029-02-28")

    def test_set_text_dmy(self):
        self.edit.setText("15-05-2027")
        self.assertEqual(self.edit.text(), "15-05-2027")
        self.assertEqual(self.edit.iso_date(), "2027-05-15")

    def test_set_text_mmyy(self):
        self.edit.setText("12/27")
        self.assertEqual(self.edit.text(), "31-12-2027")
        self.assertEqual(self.edit.iso_date(), "2027-12-31")

    def test_clear_resets(self):
        self.edit.setText("2029-02-28")
        self.assertEqual(self.edit.text(), "28-02-2029")
        self.edit.clear()
        self.assertEqual(self.edit.text(), "")
        self.assertEqual(self.edit.iso_date(), "")

    def test_keyboard_typing_full_dmy(self):
        self.edit.clear()
        QTest.keyClicks(self.edit.lineEdit(), "28-02-2029")
        self.edit.lineEdit().editingFinished.emit()
        self.assertEqual(self.edit.text(), "28-02-2029")
        self.assertEqual(self.edit.iso_date(), "2029-02-28")

    def test_keyboard_typing_continuous_digits(self):
        self.edit.clear()
        QTest.keyClicks(self.edit.lineEdit(), "28022029")
        self.edit.lineEdit().editingFinished.emit()
        self.assertEqual(self.edit.text(), "28-02-2029")
        self.assertEqual(self.edit.iso_date(), "2029-02-28")

    def test_keyboard_typing_mmyy(self):
        self.edit.clear()
        QTest.keyClicks(self.edit.lineEdit(), "12/28")
        self.edit.lineEdit().editingFinished.emit()
        self.assertEqual(self.edit.text(), "31-12-2028")
        self.assertEqual(self.edit.iso_date(), "2028-12-31")

    def test_calendar_date_picked(self):
        self.edit.clear()
        self.edit._on_date_picked(QDate(2029, 6, 15))
        self.assertEqual(self.edit.text(), "15-06-2029")
        self.assertEqual(self.edit.iso_date(), "2029-06-15")

    def test_read_only_toggle(self):
        self.assertFalse(self.edit.isReadOnly())
        self.assertFalse(self.edit.lineEdit().isReadOnly())
        self.assertTrue(self.edit._btn.isEnabled())

        self.edit.setReadOnly(True)
        self.assertTrue(self.edit.isReadOnly())
        self.assertTrue(self.edit.lineEdit().isReadOnly())
        self.assertFalse(self.edit._btn.isEnabled())

        # When read-only, popup should not open and date picked should be ignored
        self.edit.show_popup()
        if self.edit._popup:
            self.assertFalse(self.edit._popup.isVisible())
        self.edit._on_date_picked(QDate(2035, 1, 1))
        self.assertNotEqual(self.edit.text(), "01-01-2035")

        self.edit.setReadOnly(False)
        self.assertFalse(self.edit.isReadOnly())
        self.assertFalse(self.edit.lineEdit().isReadOnly())
        self.assertTrue(self.edit._btn.isEnabled())


class TestBatchLineEditWidget(unittest.TestCase):
    """Unit tests for BatchLineEdit autocomplete."""

    def setUp(self):
        self.edit = BatchLineEdit("Batch", 96)
        self.sample_batches = [
            {"batch_no": "EF2026B1", "expiry": "2028-08-31", "rate": 74.64, "mrp": 110.0},
            {"batch_no": "EF2026B2", "expiry": "2028-10-31", "rate": 75.00, "mrp": 115.0},
            {"batch_no": "AUG9942", "expiry": "2027-12-31", "rate": 120.0, "mrp": 175.0},
        ]
        self.edit.set_batches(self.sample_batches)

    def test_first_char_dynamic_matching(self):
        # Typing 'E' or 'e' matches 2 batches
        self.edit._completer.setCompletionPrefix("e")
        self.assertEqual(self.edit._completer.completionCount(), 2)

        # Typing 'ef2026b2' narrows to 1
        self.edit._completer.setCompletionPrefix("ef2026b2")
        self.assertEqual(self.edit._completer.completionCount(), 1)

        # Typing 'a' matches AUG9942
        self.edit._completer.setCompletionPrefix("a")
        self.assertEqual(self.edit._completer.completionCount(), 1)

        # Non-matching
        self.edit._completer.setCompletionPrefix("xyz")
        self.assertEqual(self.edit._completer.completionCount(), 0)

    def test_dropdown_label_batch_no_and_expiry_only(self):
        item = self.edit._model.item(0)
        self.assertEqual(item.text(), "EF2026B1 | 31-08-2028")
        self.assertNotIn("Exp:", item.text())
        self.assertNotIn("MRP", item.text())

        # Second item
        item2 = self.edit._model.item(1)
        self.assertEqual(item2.text(), "EF2026B2 | 31-10-2028")

        # Third item
        item3 = self.edit._model.item(2)
        self.assertEqual(item3.text(), "AUG9942 | 31-12-2027")

    def test_selection_populates_batch_and_emits_data(self):
        received = []
        self.edit.batch_selected.connect(lambda d: received.append(d))

        self.edit._completer.setCompletionPrefix("EF2026B1")
        idx = self.edit._completer.completionModel().index(0, 0)
        self.edit._on_completer_activated(idx)

        self.assertEqual(self.edit.text(), "EF2026B1")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["batch_no"], "EF2026B1")
        self.assertEqual(received[0]["rate"], 74.64)
        self.assertEqual(received[0]["mrp"], 110.0)

    def test_allow_arbitrary_new_batch_entry(self):
        self.edit.setText("BRANDNEW_BATCH_999")
        self.assertEqual(self.edit.text(), "BRANDNEW_BATCH_999")

    def test_arrow_key_navigation_and_enter(self):
        received = []
        self.edit.batch_selected.connect(lambda d: received.append(d))

        self.edit.clear()
        QTest.keyClicks(self.edit, "EF")
        # Navigate down to second item (EF2026B2)
        QTest.keyClick(self.edit, Qt.Key_Down) # row 0
        QTest.keyClick(self.edit, Qt.Key_Down) # row 1
        QTest.keyClick(self.edit, Qt.Key_Return)

        self.assertEqual(self.edit.text(), "EF2026B2")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["batch_no"], "EF2026B2")
        self.assertEqual(received[0]["rate"], 75.00)

    def test_preserve_new_batch_on_enter(self):
        batches = [
            {"batch_no": "BATCH10", "rate": 10},
            {"batch_no": "BATCH100", "rate": 20},
        ]
        self.edit.set_batches(batches)
        self.edit.clear()

        # Type new batch BATCH1 without selecting from popup
        QTest.keyClicks(self.edit, "BATCH1")
        QTest.keyClick(self.edit, Qt.Key_Return)

        # Must keep BATCH1 and not get overwritten with BATCH10
        self.assertEqual(self.edit.text(), "BATCH1")

    def test_tab_hides_popup(self):
        self.edit.clear()
        QTest.keyClicks(self.edit, "EF")
        self.assertTrue(self.edit._completer.popup().isVisible())

        QTest.keyClick(self.edit, Qt.Key_Tab)
        self.assertFalse(self.edit._completer.popup().isVisible())

    def test_exact_match_resolves_on_tab(self):
        received = []
        self.edit.batch_selected.connect(lambda d: received.append(d))

        self.edit.clear()
        QTest.keyClicks(self.edit, "ef2026b2")
        QTest.keyClick(self.edit, Qt.Key_Tab)

        self.assertEqual(self.edit.text(), "EF2026B2")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["batch_no"], "EF2026B2")

    def test_mouse_click_emits_batch_selected_once(self):
        received = []
        self.edit.batch_selected.connect(lambda d: received.append(d))

        self.edit.clear()
        self.edit.show()
        QTest.keyClicks(self.edit, "EF")
        popup = self.edit._completer.popup()
        self.assertTrue(popup.isVisible())

        rect = popup.visualRect(popup.model().index(0, 0))
        QTest.mouseClick(popup.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())

        self.assertEqual(self.edit.text(), "EF2026B1")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["batch_no"], "EF2026B1")
        self.assertFalse(popup.isVisible())


class TestItemEntryBarBehavior(unittest.TestCase):
    """Test _ItemEntryBar field states, exact field order, and read-only toggle reactions."""

    def setUp(self):
        self.bar = _ItemEntryBar()

    def test_exact_single_row_field_order(self):
        """R1: Item entry fields strictly follow Item -> Pack -> Pay Qty -> Free Qty -> Batch -> Expiry -> Rate -> MRP -> Discount -> GST -> + Add Item."""
        labels = [lbl.text() for lbl in self.bar._entry_labels]
        expected_labels = [
            "Item", "Pack", "Pay Qty", "Free Qty", "Batch",
            "Expiry", "Rate", "MRP", "Discount", "GST"
        ]
        self.assertEqual(labels, expected_labels)

        layout = self.bar.layout()
        self.assertEqual(layout.count(), 11)
        # Check add button is the 11th control
        self.assertEqual(layout.itemAt(10).widget(), self.bar.add_btn)
        self.assertEqual(self.bar.add_btn.text(), "+ Add Item")

    def test_pack_and_gst_are_read_only(self):
        self.assertTrue(self.bar.pack_edit.isReadOnly())
        self.assertTrue(self.bar.gst_edit.isReadOnly())
        self.assertEqual(self.bar.pack_edit.focusPolicy(), Qt.NoFocus)
        self.assertEqual(self.bar.gst_edit.focusPolicy(), Qt.NoFocus)

    def test_initial_editable_state_for_batch_fields(self):
        """Expiry, Rate, and MRP should be editable initially when no saved batch is selected."""
        self.assertFalse(self.bar.expiry_edit.isReadOnly())
        self.assertFalse(self.bar.rate_edit.isReadOnly())
        self.assertFalse(self.bar.mrp_edit.isReadOnly())

    def test_batch_selected_populates_expiry_rate_mrp_and_locks_read_only(self):
        """R2: Selecting an existing batch populates Batch, Expiry, Rate, MRP and locks them as read-only."""
        data = {
            "batch_no": "EF2026B1",
            "expiry": "2029-02-28",
            "rate": 74.64,
            "mrp": 110.0,
        }
        self.bar._on_saved_batch_selected(data)
        self.assertEqual(self.bar.batch_edit.text(), "EF2026B1")
        self.assertEqual(self.bar.expiry_edit.text(), "28-02-2029")
        self.assertEqual(self.bar.rate_edit.text(), "74.64")
        self.assertEqual(self.bar.mrp_edit.text(), "110.00")

        # Expiry, Rate, and MRP must be read-only
        self.assertTrue(self.bar.expiry_edit.isReadOnly())
        self.assertTrue(self.bar.rate_edit.isReadOnly())
        self.assertTrue(self.bar.mrp_edit.isReadOnly())
        # Pack and GST remain permanently read-only
        self.assertTrue(self.bar.pack_edit.isReadOnly())
        self.assertTrue(self.bar.gst_edit.isReadOnly())

    def test_new_unlisted_batch_keeps_fields_editable(self):
        """R2: Entering a new batch (or changing away from saved batch) restores editability."""
        # 1. First select saved batch
        data = {
            "batch_no": "EF2026B1",
            "expiry": "2029-02-28",
            "rate": 74.64,
            "mrp": 110.0,
        }
        self.bar._on_saved_batch_selected(data)
        self.assertTrue(self.bar.expiry_edit.isReadOnly())
        self.assertTrue(self.bar.rate_edit.isReadOnly())
        self.assertTrue(self.bar.mrp_edit.isReadOnly())

        # 2. User changes batch text to an unlisted new batch
        self.bar.batch_edit.setText("BRANDNEW_BATCH_001")
        self.assertFalse(self.bar.expiry_edit.isReadOnly())
        self.assertFalse(self.bar.rate_edit.isReadOnly())
        self.assertFalse(self.bar.mrp_edit.isReadOnly())

    def test_clear_resets_all_fields_and_batches(self):
        self.bar.pack_edit.setText("10")
        self.bar.batch_edit.setText("B1")
        self.bar.batch_edit.set_batches([{"batch_no": "B1"}])
        self.bar.expiry_edit.setText("2029-02-28")
        self.bar.pay_qty_edit.setText("20")
        self.bar.set_batch_fields_readonly(True)

        self.bar.clear()
        self.assertEqual(self.bar.pack_edit.text(), "")
        self.assertEqual(self.bar.batch_edit.text(), "")
        self.assertEqual(self.bar.expiry_edit.text(), "")
        self.assertEqual(self.bar.pay_qty_edit.text(), "")
        self.assertEqual(self.bar.batch_edit._model.rowCount(), 0)
        # Should be editable after clear
        self.assertFalse(self.bar.expiry_edit.isReadOnly())
        self.assertFalse(self.bar.rate_edit.isReadOnly())
        self.assertFalse(self.bar.mrp_edit.isReadOnly())

    def test_saved_batch_with_no_expiry_clears_stale_expiry(self):
        # 1. User selects batch with expiry
        self.bar._on_saved_batch_selected({"batch_no": "B1", "expiry": "2028-10-31", "rate": 50.0, "mrp": 100.0})
        self.assertEqual(self.bar.expiry_edit.text(), "31-10-2028")

        # 2. User selects batch with no expiry date
        self.bar._on_saved_batch_selected({"batch_no": "B2", "expiry": "", "rate": 60.0, "mrp": 120.0})
        self.assertEqual(self.bar.batch_edit.text(), "B2")
        self.assertEqual(self.bar.expiry_edit.text(), "")
        self.assertTrue(self.bar.expiry_edit.isReadOnly())


class TestInvoiceDialogIntegration(unittest.TestCase):
    """End-to-end integration within _InvoiceDialog."""

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_switching_items_updates_pack_and_gst_from_master(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"
        mock_purch.get_saved_batches_for_item.return_value = []

        item1 = {
            "id": 100, "item_name": "MEDICINE A",
            "pack_size": "10", "mrp": 100.0, "rate": 50.0,
            "tax_structure": "5"
        }
        item2 = {
            "id": 200, "item_name": "MEDICINE B",
            "pack_size": "1", "mrp": 250.0, "rate": 180.0,
            "tax_structure": "12"
        }

        mock_item.get_all.return_value = [
            {"id": 100, "item_name": "MEDICINE A"},
            {"id": 200, "item_name": "MEDICINE B"},
        ]
        mock_item.get_by_id.side_effect = lambda iid: item1 if iid == 100 else (item2 if iid == 200 else None)

        dlg = _InvoiceDialog()

        # Select Item 1
        dlg._entry_bar.item_combo.blockSignals(True)
        dlg._entry_bar.item_combo.addItem("MEDICINE A", 100)
        dlg._entry_bar.item_combo.addItem("MEDICINE B", 200)
        dlg._entry_bar.item_combo.setCurrentIndex(0)
        dlg._entry_bar.item_combo.blockSignals(False)
        dlg._on_item_changed(0)

        self.assertEqual(dlg._entry_bar.pack_edit.text(), "10")
        self.assertEqual(dlg._entry_bar.gst_edit.text(), "5")

        # Select Item 2 -> Both pack and gst MUST update from item 2 master
        dlg._entry_bar.item_combo.setCurrentIndex(1)
        dlg._on_item_changed(1)

        self.assertEqual(dlg._entry_bar.pack_edit.text(), "1")
        self.assertEqual(dlg._entry_bar.gst_edit.text(), "12")
        dlg.close()

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_switching_items_resets_fields_and_updates_master_rates(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"
        mock_purch.get_saved_batches_for_item.return_value = []

        item1 = {
            "id": 100, "item_name": "MEDICINE A",
            "pack_size": "10", "mrp": 100.0, "rate": 50.0,
            "tax_structure": "5"
        }
        item2 = {
            "id": 200, "item_name": "MEDICINE B",
            "pack_size": "20", "mrp": 250.0, "rate": 180.0,
            "tax_structure": "18"
        }
        mock_item.get_by_id.side_effect = lambda iid: item1 if iid == 100 else (item2 if iid == 200 else None)

        dlg = _InvoiceDialog()
        dlg._entry_bar.item_combo.blockSignals(True)
        dlg._entry_bar.item_combo.addItem("MEDICINE A", 100)
        dlg._entry_bar.item_combo.addItem("MEDICINE B", 200)
        dlg._entry_bar.item_combo.setCurrentIndex(0)
        dlg._entry_bar.item_combo.blockSignals(False)
        dlg._on_item_changed(0)

        # User selected a saved batch for item 1 -> locks fields
        dlg._entry_bar._on_saved_batch_selected({"batch_no": "BATCH_ITEM_A", "expiry": "2028-02-28", "rate": 50.0, "mrp": 100.0})
        self.assertTrue(dlg._entry_bar.expiry_edit.isReadOnly())
        self.assertTrue(dlg._entry_bar.rate_edit.isReadOnly())
        self.assertTrue(dlg._entry_bar.mrp_edit.isReadOnly())

        # Now user switches to item 2
        dlg._entry_bar.item_combo.setCurrentIndex(1)
        dlg._on_item_changed(1)

        self.assertEqual(dlg._entry_bar.pack_edit.text(), "20")
        self.assertEqual(dlg._entry_bar.gst_edit.text(), "18")
        self.assertEqual(dlg._entry_bar.rate_edit.text(), "180.00")
        self.assertEqual(dlg._entry_bar.mrp_edit.text(), "250.00")
        self.assertEqual(dlg._entry_bar.batch_edit.text(), "")
        self.assertEqual(dlg._entry_bar.expiry_edit.text(), "")
        # Editability must be restored
        self.assertFalse(dlg._entry_bar.expiry_edit.isReadOnly())
        self.assertFalse(dlg._entry_bar.rate_edit.isReadOnly())
        self.assertFalse(dlg._entry_bar.mrp_edit.isReadOnly())
        dlg.close()

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_all_11_controls_fit_single_row_no_wrapping(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"
        mock_purch.get_saved_batches_for_item.return_value = []
        mock_item.get_all.return_value = []

        dlg = _InvoiceDialog()
        try:
            for w, h in [(1200, 700), (1366, 768)]:
                dlg.resize(w, h)
                dlg.show()
                app.processEvents()

                bar = dlg._entry_bar
                self.assertLessEqual(bar.height(), 46)

                bar_layout = bar.layout()
                self.assertEqual(bar_layout.count(), 11)

                add_btn = bar.add_btn
                btn_right = add_btn.geometry().right()
                self.assertLessEqual(btn_right, bar.width())

                item_container = bar_layout.itemAt(0).widget()
                self.assertGreaterEqual(item_container.width(), 180)
                self.assertGreaterEqual(bar.item_combo.width(), 160)
        finally:
            dlg.close()

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_gst_tax_structure_cleaning(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"
        mock_purch.get_saved_batches_for_item.return_value = []

        item_gst12 = {
            "id": 100, "item_name": "ITEM 12",
            "pack_size": "10", "mrp": 100.0, "rate": 50.0,
            "tax_structure": "GST 12%"
        }
        item_gst_desc = {
            "id": 200, "item_name": "ITEM DESC",
            "pack_size": "10", "mrp": 100.0, "rate": 50.0,
            "tax_structure": "GST @ 18% (CGST-9% & SGST-9%)"
        }
        item_legacy = {
            "id": 300, "item_name": "LEGACY ITEM",
            "pack_size": "10", "mrp": 100.0, "rate": 50.0,
            "tax_structure": "1"  # unmapped legacy code
        }
        mock_item.get_by_id.side_effect = lambda iid: {
            100: item_gst12,
            200: item_gst_desc,
            300: item_legacy
        }.get(iid)

        dlg = _InvoiceDialog()
        dlg._entry_bar.item_combo.blockSignals(True)
        dlg._entry_bar.item_combo.addItem("ITEM 12", 100)
        dlg._entry_bar.item_combo.addItem("ITEM DESC", 200)
        dlg._entry_bar.item_combo.addItem("LEGACY ITEM", 300)
        dlg._entry_bar.item_combo.blockSignals(False)

        dlg._entry_bar.item_combo.setCurrentIndex(0)
        dlg._on_item_changed(0)
        self.assertEqual(dlg._entry_bar.gst_edit.text(), "12")

        dlg._entry_bar.item_combo.setCurrentIndex(1)
        dlg._on_item_changed(1)
        self.assertEqual(dlg._entry_bar.gst_edit.text(), "18")

        dlg._entry_bar.item_combo.setCurrentIndex(2)
        dlg._on_item_changed(2)
        self.assertEqual(dlg._entry_bar.gst_edit.text(), "0")
        dlg.close()

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_batch_autocomplete_and_item_table_expiry_display(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"

        saved_batches = [
            {"batch_no": "EF2026B1", "expiry": "2029-02-28", "rate": 74.64, "mrp": 110.0, "pack_size": "10"}
        ]
        mock_purch.get_saved_batches_for_item.return_value = saved_batches

        item = {
            "id": 100, "item_name": "EFEREM SP",
            "pack_size": "10", "mrp": 110.0, "rate": 74.64,
            "tax_structure": "5"
        }
        mock_item.get_all.return_value = [item]
        mock_item.get_by_id.return_value = item

        dlg = _InvoiceDialog()
        dlg._entry_bar.item_combo.blockSignals(True)
        dlg._entry_bar.item_combo.addItem("EFEREM SP", 100)
        dlg._entry_bar.item_combo.setCurrentIndex(0)
        dlg._entry_bar.item_combo.blockSignals(False)
        dlg._on_item_changed(0)

        # Autocomplete model loaded with 1 batch
        self.assertEqual(dlg._entry_bar.batch_edit._model.rowCount(), 1)

        # Simulate batch selection
        dlg._entry_bar._on_saved_batch_selected(saved_batches[0])

        self.assertEqual(dlg._entry_bar.batch_edit.text(), "EF2026B1")
        self.assertEqual(dlg._entry_bar.expiry_edit.text(), "28-02-2029")
        self.assertEqual(dlg._entry_bar.rate_edit.text(), "74.64")
        self.assertEqual(dlg._entry_bar.mrp_edit.text(), "110.00")

        # Enter quantity and add
        dlg._entry_bar.pay_qty_edit.setText("20")
        dlg._entry_bar.free_qty_edit.setText("4")
        dlg._on_add_item()

        # Check table row
        self.assertEqual(len(dlg._item_rows), 1)
        row = dlg._item_rows[0]
        # In table column 6 (Exp), display is DD-MM-YYYY
        table_exp = dlg._table.item(0, 6).text()
        self.assertEqual(table_exp, "28-02-2029")

        # In row data dictionary (for DB), expiry is normalized to YYYY-MM-DD
        d = row.to_dict()
        self.assertEqual(d["expiry"], "2029-02-28")
        dlg.close()

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_item_with_no_existing_batches(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"
        mock_purch.get_saved_batches_for_item.return_value = []

        item = {
            "id": 101, "item_name": "NEW MEDICINE",
            "pack_size": "15", "mrp": 200.0, "rate": 150.0,
            "tax_structure": "12"
        }
        mock_item.get_all.return_value = [item]
        mock_item.get_by_id.return_value = item

        dlg = _InvoiceDialog()
        dlg._entry_bar.item_combo.blockSignals(True)
        dlg._entry_bar.item_combo.addItem("NEW MEDICINE", 101)
        dlg._entry_bar.item_combo.setCurrentIndex(0)
        dlg._entry_bar.item_combo.blockSignals(False)
        dlg._on_item_changed(0)

        # Batch autocomplete model is empty
        self.assertEqual(dlg._entry_bar.batch_edit._model.rowCount(), 0)

        # Type a new batch
        dlg._entry_bar.batch_edit.setText("NEW_BATCH_001")
        dlg._entry_bar.expiry_edit.setText("31-12-2029")
        dlg._entry_bar.pay_qty_edit.setText("10")
        dlg._entry_bar.free_qty_edit.setText("0")
        dlg._on_add_item()

        self.assertEqual(len(dlg._item_rows), 1)
        self.assertEqual(dlg._item_rows[0].batch_no, "NEW_BATCH_001")
        self.assertEqual(dlg._table.item(0, 6).text(), "31-12-2029")
        dlg.close()


class TestPurchaseDAOSavedBatches(unittest.TestCase):
    """Unit tests for PurchaseDAO.get_saved_batches_for_item deduplication."""

    @patch("database.purchase_dao.get_connection")
    def test_deduplication_and_backfill(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        # Cursor 1: purchase_invoice_items has B1 with rate 0 and no expiry, B2 with full data
        cur1 = MagicMock()
        cur1.fetchall.return_value = [
            {"batch_no": "B1", "expiry": "", "rate": 0.0, "mrp": 100.0, "pack_size": "10"},
            {"batch_no": "b2", "expiry": "2028-10-31", "rate": 50.0, "mrp": 80.0, "pack_size": "10"},
        ]

        # Cursor 2: stock_batches has b1 (case-insensitive) with expiry and rate
        cur2 = MagicMock()
        cur2.fetchall.return_value = [
            {"batch_no": "b1", "expiry": "2029-01-31", "rate": 45.0, "mrp": 100.0, "pack_size": "10"},
            {"batch_no": "B3", "expiry": "2027-05-31", "rate": 30.0, "mrp": 40.0, "pack_size": "5"},
        ]

        mock_conn.execute.side_effect = [cur1, cur2]

        batches = PurchaseDAO.get_saved_batches_for_item(999)
        self.assertEqual(len(batches), 3)

        b1 = next(b for b in batches if b["batch_no"].upper() == "B1")
        # Expiry and rate should be backfilled from stock_batches
        self.assertEqual(b1["expiry"], "2029-01-31")
        self.assertEqual(b1["rate"], 45.0)

        b2 = next(b for b in batches if b["batch_no"].upper() == "B2")
        self.assertEqual(b2["expiry"], "2028-10-31")
        self.assertEqual(b2["rate"], 50.0)


if __name__ == "__main__":
    unittest.main()
