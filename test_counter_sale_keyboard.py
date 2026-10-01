"""Focused keyboard and autocomplete tests for Counter Sale entry."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from screens.counter_sale import _KeyboardCombo
from test_counter_sale_input import _DBBase


class CounterSaleKeyboardTests(_DBBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.messages = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        self.messages.start()
        self.addCleanup(self.messages.stop)
        from screens.counter_sale import CounterSalePage
        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        self.app.processEvents()
        self.entry = self.page._sale_panel._entry_bar
        self.item = self.entry.item_combo
        self.batch = self.entry.batch_combo
        self.qty = self.entry.qty_edit
        self.discount = self.entry.discount_edit
        self.add = self.entry.add_btn

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        self.app.processEvents()

    def _select_item_index(self):
        return self.item.findData(self.item_id)

    def _select_item_mouse(self):
        self.item.setCurrentIndex(self._select_item_index())
        self.app.processEvents()

    def _select_batch_mouse(self):
        self.batch.setCurrentIndex(1)
        self.app.processEvents()

    def _keyboard_item(self):
        self.item.setFocus()
        self.item.lineEdit().clear()
        QTest.keyClicks(self.item.lineEdit(), "Test")
        self.app.processEvents()

    def _keyboard_batch(self):
        self._select_item_mouse()
        self.batch.setFocus()
        self.batch.lineEdit().clear()
        QTest.keyClicks(self.batch.lineEdit(), "BATCH")
        self.app.processEvents()

    def _keyboard_to_quantity(self):
        self._keyboard_item()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self._keyboard_batch()
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Return)
        self.app.processEvents()

    def _add_keyboard_item(self):
        self._keyboard_to_quantity()
        self.qty.setText("1")
        self.discount.setText("0.00")
        self.discount.setFocus()
        QTest.keyClick(self.discount, Qt.Key_Return)
        self.app.processEvents()

    def test_01_item_combo_is_keyboard_enabled(self):
        self.assertIsInstance(self.item, _KeyboardCombo)
        self.assertEqual(self.item.focusPolicy(), Qt.StrongFocus)

    def test_02_batch_combo_is_keyboard_enabled(self):
        self.assertIsInstance(self.batch, _KeyboardCombo)
        self.assertEqual(self.batch.focusPolicy(), Qt.StrongFocus)

    def test_03_item_completer_exists(self):
        self.assertIsNotNone(self.item.completer())

    def test_04_batch_completer_exists(self):
        self.assertIsNotNone(self.batch.completer())

    def test_05_item_popup_matches_typed_text(self):
        self._keyboard_item()
        self.assertTrue(self.item.completer().popup().isVisible())
        self.assertGreater(self.item.completer().completionCount(), 0)

    def test_06_item_popup_is_single_instance(self):
        self._keyboard_item()
        popup = self.item.completer().popup()
        self.item.lineEdit().clear()
        QTest.keyClicks(self.item.lineEdit(), "Test")
        self.app.processEvents()
        self.assertIs(self.item.completer().popup(), popup)

    def test_item_click_with_empty_field_shows_products(self):
        self.item.lineEdit().clear()
        QTest.mouseClick(self.item.lineEdit(), Qt.LeftButton)
        self.app.processEvents()
        self.assertTrue(self.item.completer().popup().isVisible())
        self.assertEqual(self.item.completer().completionCount(), 1)

    def test_item_search_is_case_insensitive_and_partial(self):
        self.item.lineEdit().clear()
        QTest.keyClicks(self.item.lineEdit(), "tEsT")
        self.app.processEvents()
        self.assertEqual(self.item.completer().completionCount(), 1)

    def test_item_search_matches_generic_name(self):
        from database.item_dao import ItemDAO
        ItemDAO.save_ingredients(self.item_id, [{"drug_id": self.drug_id, "power": ""}])
        self.entry.load_items()
        self.item.lineEdit().clear()
        QTest.keyClicks(self.item.lineEdit(), "paracetamol")
        self.app.processEvents()
        self.assertEqual(self.item.completer().completionCount(), 1)
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.item.currentData(), self.item_id)

    def test_item_no_match_is_visible_but_not_selectable(self):
        self.item.lineEdit().clear()
        QTest.keyClicks(self.item.lineEdit(), "no-such-product")
        self.app.processEvents()
        model = self.item.completer().completionModel()
        self.assertEqual(self.item.completer().completionCount(), 1)
        self.assertEqual(model.index(0, 0).data(), "No products found")
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertIsNone(self.item.currentData())
        self.assertFalse(self.item.completer().popup().isVisible())

    def test_unmatched_typing_cannot_reuse_previous_selection(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.item.lineEdit().setText("not a product")
        self.batch.lineEdit().setText("not a batch")
        self.assertIsNone(self.entry.get_current_data())

    def test_item_popup_uses_light_colors(self):
        self.assertIn("#ffffff", self.item.completer().popup().styleSheet())

    def test_item_and_batch_dropdowns_use_light_colors(self):
        self.assertIn("background-color: #ffffff", self.item.styleSheet())
        self.assertIn("background-color: #ffffff", self.batch.styleSheet())

    def test_item_and_batch_popups_stay_inside_application_window(self):
        window_bounds = QRect(
            self.page.mapToGlobal(self.page.rect().topLeft()), self.page.size()
        )
        self.item.lineEdit().clear()
        QTest.mouseClick(self.item.lineEdit(), Qt.LeftButton)
        self.app.processEvents()
        self.assertTrue(window_bounds.contains(self.item.completer().popup().geometry()))
        self.item.completer().popup().hide()
        self._select_item_mouse()
        self.batch.lineEdit().clear()
        QTest.mouseClick(self.batch.lineEdit(), Qt.LeftButton)
        self.app.processEvents()
        self.assertTrue(window_bounds.contains(self.batch.completer().popup().geometry()))

    def test_07_item_down_selects_row(self):
        self._keyboard_item()
        popup = self.item.completer().popup()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Down)
        self.app.processEvents()
        self.assertGreaterEqual(popup.currentIndex().row(), 0)

    def test_08_item_up_stays_at_boundary(self):
        self._keyboard_item()
        popup = self.item.completer().popup()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Up)
        self.app.processEvents()
        self.assertGreaterEqual(popup.currentIndex().row(), 0)

    def test_09_item_enter_accepts_popup(self):
        self._keyboard_item()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.item.currentData(), self.item_id)

    def test_10_item_escape_closes_popup(self):
        self._keyboard_item()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Escape)
        self.app.processEvents()
        self.assertFalse(self.item.completer().popup().isVisible())
        self.assertIs(QApplication.focusWidget(), self.item)

    def test_11_item_tab_accepts_and_focuses_batch(self):
        self._keyboard_item()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Tab)
        self.app.processEvents()
        self.assertEqual(self.item.currentData(), self.item_id)
        self.assertIs(QApplication.focusWidget(), self.batch)

    def test_12_item_selection_loads_batches(self):
        self._select_item_mouse()
        self.assertGreaterEqual(self.batch.count(), 2)

    def test_13_item_selection_loads_stock_context(self):
        self._select_item_mouse()
        self.assertEqual(self.batch.itemData(1), self.batch_id)

    def test_batch_selection_preserves_item_master_location(self):
        from database.connection import get_connection
        conn = get_connection()
        try:
            conn.execute("UPDATE items SET location='Shelf A' WHERE id=?", (self.item_id,))
            conn.commit()
        finally:
            conn.close()
        self.entry.load_items()
        self._select_item_mouse()
        self._select_batch_mouse()
        self.assertEqual(self.entry.location_edit.text(), "Shelf A")
        self.assertEqual(self.entry.get_current_data()["location"], "Shelf A")

    def test_amount_preview_uses_unit_price_and_discount(self):
        from database.connection import get_connection
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE stock_batches SET pack_size='15', mrp=150 WHERE id=?",
                (self.batch_id,),
            )
            conn.commit()
        finally:
            conn.close()
        self._select_item_mouse()
        self._select_batch_mouse()
        self.qty.setText("3")
        self.discount.setText("2")
        self.assertEqual(self.entry.amount_edit.text(), "28.00")

    def test_14_item_completion_focuses_batch(self):
        self._keyboard_item()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), self.batch)

    def test_item_selection_opens_multiple_batch_popup(self):
        from database.connection import get_connection
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO stock_batches "
                "(item_id, batch_no, expiry, pack_size, mrp, stock_qty) "
                "VALUES (?, 'BATCH-B', '12/28', '10x10', 50, 5)",
                (self.item_id,),
            )
            conn.commit()
        finally:
            conn.close()
        self._keyboard_item()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertTrue(self.batch.completer().popup().isVisible())
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.batch.currentData(), self.batch_id)
        self.assertIs(QApplication.focusWidget(), self.qty)

    def test_15_batch_popup_matches_typed_text(self):
        self._keyboard_batch()
        self.assertTrue(self.batch.completer().popup().isVisible())
        self.assertGreater(self.batch.completer().completionCount(), 0)

    def test_16_batch_down_selects_row(self):
        self._keyboard_batch()
        popup = self.batch.completer().popup()
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Down)
        self.app.processEvents()
        self.assertGreaterEqual(popup.currentIndex().row(), 0)

    def test_17_batch_up_stays_at_boundary(self):
        self._keyboard_batch()
        popup = self.batch.completer().popup()
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Up)
        self.app.processEvents()
        self.assertGreaterEqual(popup.currentIndex().row(), 0)

    def test_18_batch_enter_accepts_popup(self):
        self._keyboard_batch()
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.batch.currentData(), self.batch_id)

    def test_19_batch_escape_closes_popup(self):
        self._keyboard_batch()
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Escape)
        self.app.processEvents()
        self.assertFalse(self.batch.completer().popup().isVisible())
        self.assertIs(QApplication.focusWidget(), self.batch)

    def test_20_batch_tab_accepts_and_focuses_quantity(self):
        self._keyboard_batch()
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Tab)
        self.app.processEvents()
        self.assertEqual(self.batch.currentData(), self.batch_id)
        self.assertIs(QApplication.focusWidget(), self.qty)

    def test_21_batch_selection_populates_pack(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.assertEqual(self.entry.pack_edit.text(), "10x10")

    def test_22_batch_selection_populates_expiry(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.assertEqual(self.entry.expiry_edit.text(), "12/27")

    def test_23_batch_selection_populates_mrp(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.assertEqual(self.entry.mrp_edit.text(), "50.00")

    def test_24_batch_selection_populates_stock(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.assertEqual(self.entry.stock_edit.text(), "100")

    def test_25_batch_enter_focuses_quantity(self):
        self._keyboard_batch()
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), self.qty)

    def test_26_quantity_tab_focuses_discount(self):
        self.qty.setFocus()
        QTest.keyClick(self.qty, Qt.Key_Tab)
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), self.discount)

    def test_27_discount_tab_focuses_add(self):
        self.discount.setFocus()
        QTest.keyClick(self.discount, Qt.Key_Tab)
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), self.add)

    def test_28_add_button_tab_focuses_next_widget(self):
        self.assertIsNotNone(self.add.nextInFocusChain())

    def test_29_quantity_enter_activates_add(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.qty.setText("1")
        self.qty.setFocus()
        QTest.keyClick(self.qty, Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.page._sale_panel._table.rowCount(), 1)

    def test_30_discount_enter_activates_add(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.qty.setText("1")
        self.discount.setText("0.00")
        self.discount.setFocus()
        QTest.keyClick(self.discount, Qt.Key_Return)
        self.app.processEvents()
        self.assertEqual(self.page._sale_panel._table.rowCount(), 1)

    def test_31_add_returns_focus_to_item(self):
        self._add_keyboard_item()
        self.assertIs(QApplication.focusWidget(), self.item)

    def test_32_keyboard_add_creates_one_row(self):
        self._add_keyboard_item()
        self.assertEqual(len(self.page._sale_panel._item_rows), 1)

    def test_33_keyboard_add_updates_total(self):
        self._add_keyboard_item()
        self.assertEqual(self.page._sale_panel.total_amount_label.text(), "50.00")

    def test_34_mouse_item_selection_still_works(self):
        self._select_item_mouse()
        self.assertEqual(self.item.currentData(), self.item_id)

    def test_35_mouse_batch_selection_still_works(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.assertEqual(self.batch.currentData(), self.batch_id)

    def test_36_repeated_item_selection_does_not_duplicate_batches(self):
        self._select_item_mouse()
        first = self.batch.count()
        self._select_item_mouse()
        self.assertEqual(self.batch.count(), first)

    def test_37_repeated_new_sale_keeps_one_entry_bar(self):
        self.page._on_new()
        self.page._on_new()
        self.assertEqual(len(self.page.findChildren(type(self.entry))), 1)

    def test_empty_quantity_is_rejected(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        self.qty.clear()
        self.add.click()
        self.app.processEvents()
        self.assertEqual(self.page._sale_panel._table.rowCount(), 0)
        QMessageBox.warning.assert_called()

    def test_zero_and_negative_quantities_are_rejected(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        for quantity in ("0", "-1"):
            self.qty.setText(quantity)
            self.add.click()
            self.app.processEvents()
            self.assertEqual(self.page._sale_panel._table.rowCount(), 0)
        QMessageBox.warning.assert_called()

    def test_iso_expired_batch_is_rejected_before_add(self):
        from database.connection import get_connection
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE stock_batches SET expiry='2014-04-30' WHERE id=?",
                (self.batch_id,),
            )
            conn.commit()
        finally:
            conn.close()
        self._select_item_mouse()
        self._select_batch_mouse()
        self.qty.setText("1")
        self.add.click()
        self.app.processEvents()
        self.assertEqual(self.page._sale_panel._table.rowCount(), 0)
        QMessageBox.warning.assert_called()

    def test_same_batch_merge_and_delete_releases_draft_stock(self):
        panel = self.page._sale_panel
        for _ in range(2):
            self._select_item_mouse()
            batch_index = self.batch.findData(self.batch_id)
            self.batch.setCurrentIndex(batch_index)
            self.qty.setText("1")
            self.discount.setText("0")
            self.add.click()
            self.app.processEvents()
        self.assertEqual(panel._table.rowCount(), 1)
        self.assertEqual(panel._item_rows[0].sale_qty, 2)
        self._select_item_mouse()
        self.batch.setCurrentIndex(self.batch.findData(self.batch_id))
        self.assertEqual(self.entry.stock_edit.text(), "98")
        panel._delete_item(0)
        self._select_item_mouse()
        self.batch.setCurrentIndex(self.batch.findData(self.batch_id))
        self.assertEqual(self.entry.stock_edit.text(), "100")

    def test_overstock_quantity_uses_live_draft_availability(self):
        self._select_item_mouse()
        self.batch.setCurrentIndex(self.batch.findData(self.batch_id))
        self.qty.setText("99")
        self.add.click()
        self._select_item_mouse()
        self.batch.setCurrentIndex(self.batch.findData(self.batch_id))
        self.assertEqual(self.entry.stock_edit.text(), "1")
        self.qty.setText("2")
        self.add.click()
        self.app.processEvents()
        self.assertEqual(self.page._sale_panel._table.rowCount(), 1)
        QMessageBox.warning.assert_called()

    def test_different_batches_remain_separate_bill_rows(self):
        from database.connection import get_connection
        conn = get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO stock_batches "
                "(item_id, batch_no, expiry, pack_size, mrp, stock_qty) "
                "VALUES (?, 'BATCH-B', '12/28', '10x10', 50, 5)",
                (self.item_id,),
            )
            second_batch_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        panel = self.page._sale_panel
        for batch_id in (self.batch_id, second_batch_id):
            self._select_item_mouse()
            self.batch.setCurrentIndex(self.batch.findData(batch_id))
            self.qty.setText("1")
            self.discount.setText("0")
            self.add.click()
        self.assertEqual(panel._table.rowCount(), 2)
        self.assertEqual(
            {row.stock_batch_id for row in panel._item_rows},
            {self.batch_id, second_batch_id},
        )

    def test_history_loads_older_invoices_as_table_scrolls(self):
        from database.connection import get_connection
        conn = get_connection()
        try:
            conn.executemany(
                "INSERT INTO sales_invoices (bill_no, sale_date, sale_type) "
                "VALUES (?, '2026-09-29', 'Cash')",
                [(f"CS-HIST-{index:03d}",) for index in range(205)],
            )
            conn.commit()
        finally:
            conn.close()

        self.page._refresh_history()
        self.assertEqual(self.page._hist_table.rowCount(), self.page.HISTORY_PAGE_SIZE)
        self.assertTrue(self.page._history_has_more)
        self.app.processEvents()
        scrollbar = self.page._hist_table.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.app.processEvents()
        self.assertEqual(self.page._hist_table.rowCount(), 205)
        self.assertFalse(self.page._history_has_more)

    def test_save_revalidates_stock_before_writing(self):
        from database.connection import get_connection
        from database.sales_dao import SalesDAO
        panel = self.page._sale_panel
        self._select_item_mouse()
        self.batch.setCurrentIndex(self.batch.findData(self.batch_id))
        self.qty.setText("1")
        self.add.click()
        conn = get_connection()
        try:
            conn.execute("UPDATE stock_batches SET stock_qty=0 WHERE id=?", (self.batch_id,))
            conn.commit()
        finally:
            conn.close()
        before = SalesDAO.get_all()
        panel._on_save()
        self.app.processEvents()
        self.assertEqual(SalesDAO.get_all(), before)
        QMessageBox.warning.assert_called()

    def test_save_rejects_invalid_bill_amounts_without_writing(self):
        from database.sales_dao import SalesDAO
        self._add_keyboard_item()
        panel = self.page._sale_panel
        before = SalesDAO.get_all()
        panel.bill_disc_edit.setText("-1")
        panel._on_save()
        self.assertEqual(SalesDAO.get_all(), before)
        panel.bill_disc_edit.setText("0")
        panel.paid_edit.setText("nan")
        panel._on_save()
        self.assertEqual(SalesDAO.get_all(), before)
        QMessageBox.warning.assert_called()

    def test_38_repeated_popup_opening_reuses_popup(self):
        self._keyboard_item()
        popup = self.item.completer().popup()
        self.item.completer().complete()
        self.app.processEvents()
        self.assertIs(self.item.completer().popup(), popup)

    def test_39_escape_does_not_cancel_sale(self):
        self._keyboard_item()
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Escape)
        self.assertFalse(self.page._sale_panel.was_saved)
        self.assertFalse(self.page._sale_panel.was_held)

    def test_40_existing_payload_shape_is_preserved(self):
        self._select_item_mouse()
        self._select_batch_mouse()
        data = self.entry.get_current_data()
        for key in ("item_id", "stock_batch_id", "batch_no", "mrp", "sale_qty"):
            self.assertIn(key, data)

    def test_41_stock_is_not_changed_by_entry(self):
        before = self.batch_info["stock_qty"]
        self._select_item_mouse()
        self._select_batch_mouse()
        self.assertEqual(self.entry.get_current_data()["batch_stock"], before)

    def test_42_full_keyboard_workflow(self):
        self._add_keyboard_item()
        row = self.page._sale_panel._item_rows[0]
        self.assertEqual(row.item_id, self.item_id)
        self.assertEqual(row.stock_batch_id, self.batch_id)
        self.assertEqual(row.sale_qty, 1.0)


if __name__ == "__main__":
    unittest.main()
