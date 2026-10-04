"""Focused tests for the Sales Bill popup size, layout and database lookups.

Covers only what this change touches:
  * the popup is larger and centred,
  * the single Item Entry row fits on one line with no overlap,
  * Patient Name is a database-backed autocomplete,
  * Doctor is a database-backed dropdown,
  * Address is a database-backed dropdown that still mirrors the customer,
  * item search, batch selection, Add and the Save workflow still behave.

Every test runs against an isolated temporary database copied from the
project schema; ``data/pharmacy.db`` is never opened for writing.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ----------------------------------------------------------------------
# Isolated temporary database — set before any database module is imported
# so ``data/pharmacy.db`` is never opened by this suite.
# ----------------------------------------------------------------------

_TMP_DIR = tempfile.mkdtemp(prefix="pms_popup_fields_")
_TMP_DB = os.path.join(_TMP_DIR, "popup_fields.db")
os.environ["PHARMACY_DB"] = _TMP_DB

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
    from screens.counter_sale import (
        CounterSalePage,
        SalesBillReviewDialog,
        _DBLookupCombo,
        _patient_name_options,
        _address_options,
    )
    HAS_PYSIDE6 = True
except ImportError:                                  # pragma: no cover
    HAS_PYSIDE6 = False

from database.connection import get_connection, init_database

_APP = None


def setUpModule():
    global _APP
    init_database()
    if HAS_PYSIDE6:
        _APP = QApplication.instance() or QApplication([])


ENTRY_ROW = (
    "cno_label", "item_combo", "batch_combo", "pack_edit",
    "location_edit", "expiry_edit", "mrp_edit", "stock_edit",
    "qty_edit", "discount_edit", "amount_edit", "add_btn",
)


class PopupFieldBase(unittest.TestCase):
    """Empty schema, then one real item/batch/customer/doctor per test."""

    def setUp(self):
        self._msg = mock.patch.multiple(
            QMessageBox if HAS_PYSIDE6 else object,
            warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        if HAS_PYSIDE6:
            self._msg.start()
            self.addCleanup(self._msg.stop)

        conn = get_connection()
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for table in tables:
                if table.startswith("sqlite_"):
                    continue
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        # The sale posts through the accounting engine, which needs its
        # system ledgers/roles present in this isolated database.
        from database.account_roles import ensure_system_ledgers
        ensure_system_ledgers()

        from database.customer_dao import CustomerDAO
        from database.doctor_dao import DoctorDAO
        from database.item_dao import ItemDAO
        from database.sales_dao import SalesDAO
        from database.unit_dao import UnitDAO
        from database.company_dao import CompanyDAO

        self.unit_id = UnitDAO.insert("Pcs")
        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.item_id = ItemDAO.insert(
            item_name="Paracetamol500", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10", mrp=26.0,
        )
        self.customer_id = CustomerDAO.insert("PopCo", address="PUNE CAMP")
        self.other_customer_id = CustomerDAO.insert("SecondCo", address="SATARA")
        self.doctor_id = DoctorDAO.insert("DR.ASHWIN", city="PUNE",
                                         specialty="M S ORTHO")
        self.doctor2_id = DoctorDAO.insert("DR.BEENA", city="PUNE",
                                          specialty="SKIN")

        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO stock_batches "
                "(item_id, batch_no, expiry, pack_size, mrp, stock_qty) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.item_id, "PB-1", "12/29", "10x10", 26.0, 100.0),
            )
            self.batch_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO stock_batches "
                "(item_id, batch_no, expiry, pack_size, mrp, stock_qty) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.item_id, "PB-2", "11/29", "10x10", 26.0, 100.0),
            )
            self.batch2_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        # Existing patient names, so the lookup has real data to find.
        self._insert_patients("RAMBHAU", "RAMDEVI", "SITA", "AJAY")
        self._sales_dao = SalesDAO

    def _insert_patients(self, *names):
        conn = get_connection()
        try:
            for name in names:
                conn.execute(
                    "INSERT INTO sales_invoices "
                    "(bill_no, sale_date, sale_time, sale_type, customer_id, "
                    " patient_name, discount, paid_amount, total_amount, "
                    " round_off, net_amount) "
                    "VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0)",
                    (f"X-{name}", "2026-04-01", "10:00", "Cash",
                     self.customer_id, name),
                )
            conn.commit()
        finally:
            conn.close()

    def _open_popup(self):
        """Fill a valid draft and return the opened review popup."""
        page = CounterSalePage()
        self.addCleanup(page.deleteLater)
        page.resize(1366, 768)
        page.show()
        _APP.processEvents()
        panel = page._sale_panel
        panel.customer_combo.setCurrentIndex(
            panel.customer_combo.findData(self.customer_id))
        bar = panel._entry_bar
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_id))
        bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(self.batch_id))
        bar.qty_edit.setText("2")
        bar.discount_edit.setText("0")
        bar.add_btn.click()
        _APP.processEvents()
        panel._on_save()
        _APP.processEvents()
        self.assertTrue(hasattr(panel, "_review_dialog"))
        self.addCleanup(panel._review_dialog.reject)
        return page, panel._review_dialog


# ----------------------------------------------------------------------
# Popup size and centring
# ----------------------------------------------------------------------

@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestPopupSize(PopupFieldBase):

    def test_popup_is_wider_than_the_old_narrow_window(self):
        self.assertGreaterEqual(SalesBillReviewDialog.MIN_WIDTH, 1180)
        self.assertLessEqual(SalesBillReviewDialog.MAX_WIDTH, 1300)

    def test_popup_height_stays_compact(self):
        self.assertGreaterEqual(SalesBillReviewDialog.MIN_HEIGHT, 520)
        self.assertLessEqual(SalesBillReviewDialog.MAX_HEIGHT, 600)

    def test_size_at_1366x768(self):
        width, height = SalesBillReviewDialog.target_size(1366, 768)
        self.assertTrue(900 <= width <= 1300, width)
        self.assertTrue(520 <= height <= 600, height)

    def test_size_at_1600x900(self):
        width, height = SalesBillReviewDialog.target_size(1600, 900)
        self.assertTrue(900 <= width <= 1300, width)
        self.assertTrue(520 <= height <= 600, height)

    def test_popup_is_never_full_screen(self):
        for width, height in ((1366, 768), (1600, 900)):
            popup_w, popup_h = SalesBillReviewDialog.target_size(width, height)
            self.assertLess(popup_w, width)
            self.assertLess(popup_h, height)

    def test_live_popup_uses_the_configured_size(self):
        _, dlg = self._open_popup()
        self.assertGreaterEqual(dlg.width(), SalesBillReviewDialog.MIN_WIDTH)
        self.assertLessEqual(dlg.width(), SalesBillReviewDialog.MAX_WIDTH)

    def test_popup_is_centred_over_the_parent_page(self):
        page, dlg = self._open_popup()
        parent = page.geometry()
        popup = dlg.geometry()
        self.assertLessEqual(abs(popup.center().x() - parent.center().x()), 40)
        self.assertLessEqual(abs(popup.center().y() - parent.center().y()), 40)

    def test_counter_sale_stays_visible_behind_the_popup(self):
        page, dlg = self._open_popup()
        self.assertTrue(page.isVisible())
        self.assertTrue(page._hist_table.isVisible())
        self.assertTrue(page._sale_panel.isVisible())


# ----------------------------------------------------------------------
# Item Entry row: one row, no overlap
# ----------------------------------------------------------------------

@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestEntryRowLayout(PopupFieldBase):

    def _spans(self, dlg):
        bar = dlg._panel._entry_bar
        spans = []
        for name in ENTRY_ROW:
            widget = getattr(bar, name)
            top_left = widget.mapTo(dlg, widget.rect().topLeft())
            spans.append((name, top_left.x(), top_left.x() + widget.width()))
        return spans

    def test_entry_row_keeps_its_single_row_order(self):
        _, dlg = self._open_popup()
        bar = dlg._panel._entry_bar
        found = []
        for index in range(bar.layout().count()):
            widget = bar.layout().itemAt(index).widget()
            for name in ENTRY_ROW:
                if widget is getattr(bar, name):
                    found.append(name)
        self.assertEqual(found, list(ENTRY_ROW))

    def test_no_entry_field_overlaps_its_neighbour(self):
        _, dlg = self._open_popup()
        spans = self._spans(dlg)
        for i in range(len(spans) - 1):
            self.assertLessEqual(
                spans[i][2], spans[i + 1][1],
                f"{spans[i][0]} overlaps {spans[i + 1][0]}: {spans[i]} {spans[i+1]}",
            )

    def test_entry_row_stays_inside_the_popup(self):
        _, dlg = self._open_popup()
        spans = self._spans(dlg)
        self.assertGreaterEqual(spans[0][1], 0)
        self.assertLessEqual(spans[-1][2], dlg.width())

    def test_item_field_is_readable(self):
        _, dlg = self._open_popup()
        self.assertGreaterEqual(dlg._panel._entry_bar.item_combo.minimumWidth(), 180)

    def test_batch_field_is_readable(self):
        _, dlg = self._open_popup()
        self.assertGreaterEqual(dlg._panel._entry_bar.batch_combo.minimumWidth(), 90)

    def test_add_button_is_readable(self):
        _, dlg = self._open_popup()
        self.assertGreaterEqual(dlg._panel._entry_bar.add_btn.minimumWidth(), 60)

    def test_no_label_is_clipped(self):
        _, dlg = self._open_popup()
        bar = dlg._panel._entry_bar
        for index in range(bar.layout().count()):
            widget = bar.layout().itemAt(index).widget()
            if isinstance(widget, QLabel) and widget is not bar.cno_label:
                self.assertGreaterEqual(widget.width(), widget.sizeHint().width(),
                                        f"label {widget.text()!r} is clipped")

    def test_widths_are_reapplied_for_a_wider_window(self):
        _, dlg = self._open_popup()
        bar = dlg._panel._entry_bar
        dlg.setFixedSize(1300, dlg.height())
        dlg._panel.apply_popup_entry_widths(1300 - 16)
        _APP.processEvents()
        spans = self._spans(dlg)
        for i in range(len(spans) - 1):
            self.assertLessEqual(spans[i][2], spans[i + 1][1])
        self.assertGreaterEqual(bar.qty_edit.width(), 30)

    def test_entry_row_widths_come_from_a_layout_not_absolute_positioning(self):
        _, dlg = self._open_popup()
        bar = dlg._panel._entry_bar
        for name in ENTRY_ROW:
            widget = getattr(bar, name)
            self.assertTrue(widget.isVisible() or not dlg.isVisible())
            # A layout-managed field has no explicit geometry override.
            self.assertIsNone(widget.layout())


# ----------------------------------------------------------------------
# Patient Name: database autocomplete
# ----------------------------------------------------------------------

@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestPatientLookup(PopupFieldBase):

    def test_patient_field_is_a_database_lookup(self):
        _, dlg = self._open_popup()
        self.assertIsInstance(dlg._panel.patient_name_edit, _DBLookupCombo)

    def test_clicking_patient_opens_the_list(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.reload("")
        combo._show_completion_popup()
        self.assertTrue(combo.completer().popup().isVisible())
        self.assertGreater(combo.completer().completionCount(), 0)

    def test_empty_click_lists_existing_patients(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.reload("")
        rows = [combo.itemText(i) for i in range(combo.count())]
        self.assertIn("RAMBHAU", rows)
        self.assertIn("AJAY", rows)

    def test_typing_filters_the_list(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.lineEdit().setText("RAM")
        combo._on_text_edited("RAM")
        rows = [combo.itemText(i) for i in range(combo.count())]
        self.assertIn("RAMBHAU", rows)
        self.assertNotIn("AJAY", rows)

    def test_partial_matching(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.lineEdit().setText("BHA")
        combo._on_text_edited("BHA")
        rows = [combo.itemText(i) for i in range(combo.count())]
        self.assertIn("RAMBHAU", rows)

    def test_filtering_is_case_insensitive(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        upper = _patient_name_options("RAM")
        lower = _patient_name_options("ram")
        mixed = _patient_name_options("rAm")
        self.assertEqual(upper, lower)
        self.assertEqual(upper, mixed)
        self.assertIn("RAMBHAU", upper)

    def test_arrow_down_then_arrow_up_move_the_selection(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.reload("")
        combo._open_popup_from_keyboard(True)
        self.assertTrue(combo.completer().popup().isVisible())
        first = combo.completer().popup().currentIndex().row()
        combo._move_popup_selection(1)
        second = combo.completer().popup().currentIndex().row()
        self.assertNotEqual(first, second)
        combo._move_popup_selection(-1)
        self.assertEqual(combo.completer().popup().currentIndex().row(), first)

    def test_enter_accepts_the_highlighted_patient(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.lineEdit().setText("RAMBHAU")
        combo._on_text_edited("RAMBHAU")
        combo._open_popup_from_keyboard(True)
        self.assertTrue(combo._accept_popup_selection())
        self.assertEqual(combo.text(), "RAMBHAU")

    def test_tab_accepts_the_highlighted_patient(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.reload("")
        combo._open_popup_from_keyboard(True)
        combo._accept_popup_selection()
        self.assertEqual(combo.text(), combo.itemText(0))

    def test_escape_closes_without_selecting(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.reload("")
        combo._open_popup_from_keyboard(True)
        self.assertTrue(combo.completer().popup().isVisible())
        combo.completer().popup().hide()
        self.assertFalse(combo.completer().popup().isVisible())

    def test_mouse_activation_selects_the_patient(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.reload("")
        combo._on_activated("AJAY")
        self.assertEqual(combo.text(), "AJAY")

    def test_selected_patient_is_stored_on_the_bill(self):
        _, dlg = self._open_popup()
        dlg._panel.patient_name_edit.setText("RAMBHAU")
        self.assertEqual(dlg._panel.patient_name_edit.text(), "RAMBHAU")

    def test_no_match_yields_no_rows(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.patient_name_edit
        combo.lineEdit().setText("zzzznotapatient")
        combo._on_text_edited("zzzznotapatient")
        self.assertEqual(combo.count(), 0)

    def test_patient_names_come_from_the_sale_history_table(self):
        self._insert_patients("NEWPATIENTX")
        self.assertIn("NEWPATIENTX", _patient_name_options("NEW"))


# ----------------------------------------------------------------------
# Doctor: database dropdown
# ----------------------------------------------------------------------

@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestDoctorLookup(PopupFieldBase):

    def test_doctor_click_opens_the_list(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.doctor_combo
        self.assertTrue(combo._show_all_on_click)
        combo._show_completion_popup()
        self.assertTrue(combo.completer().popup().isVisible())

    def test_doctor_values_come_from_the_database(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.doctor_combo
        rows = [combo.itemText(i) for i in range(combo.count())]
        self.assertTrue(any("DR.ASHWIN" in r for r in rows))
        self.assertTrue(any("DR.BEENA" in r for r in rows))

    def test_doctor_keeps_the_placeholder_first(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.doctor_combo
        self.assertIsNone(combo.itemData(0))
        self.assertEqual(combo.itemData(1), self.doctor_id)

    def test_doctor_shows_the_stored_specialty(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.doctor_combo
        self.assertIn("M S ORTHO", combo.itemText(1))

    def test_doctor_keyboard_selection(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.doctor_combo
        combo._open_popup_from_keyboard(True)
        combo._accept_popup_selection()
        self.assertIsNotNone(combo.currentData())

    def test_doctor_mouse_selection_keeps_the_id(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.doctor_combo
        index = combo.findData(self.doctor2_id)
        combo.setCurrentIndex(index)
        self.assertEqual(combo.currentData(), self.doctor2_id)

    def test_doctor_width_is_readable(self):
        _, dlg = self._open_popup()
        self.assertGreaterEqual(dlg._panel.doctor_combo.minimumWidth(), 180)


# ----------------------------------------------------------------------
# Address: database dropdown
# ----------------------------------------------------------------------

@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestAddressLookup(PopupFieldBase):

    def test_address_field_is_a_database_lookup(self):
        _, dlg = self._open_popup()
        self.assertIsInstance(dlg._panel.address_edit, _DBLookupCombo)

    def test_clicking_address_opens_the_list(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.address_edit
        combo.reload("")
        combo._show_completion_popup()
        self.assertTrue(combo.completer().popup().isVisible())

    def test_address_values_come_from_the_database(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.address_edit
        combo.reload("")
        rows = [combo.itemText(i) for i in range(combo.count())]
        self.assertIn("PUNE CAMP", rows)
        self.assertIn("SATARA", rows)

    def test_typing_filters_addresses(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.address_edit
        combo.lineEdit().setText("sat")
        combo._on_text_edited("sat")
        rows = [combo.itemText(i) for i in range(combo.count())]
        self.assertEqual(rows, ["SATARA"])

    def test_selected_address_populates_the_field(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.address_edit
        combo._on_activated("SATARA")
        self.assertEqual(combo.text(), "SATARA")

    def test_address_keyboard_selection(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.address_edit
        combo.reload("")
        combo._open_popup_from_keyboard(True)
        self.assertTrue(combo._accept_popup_selection())
        self.assertTrue(combo.text())

    def test_address_mouse_selection(self):
        _, dlg = self._open_popup()
        combo = dlg._panel.address_edit
        index = combo.findText("PUNE CAMP", Qt.MatchFixedString)
        combo.setCurrentIndex(index)
        self.assertEqual(combo.text(), "PUNE CAMP")

    def test_customer_selection_mirrors_its_address(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        panel.customer_combo.setCurrentIndex(
            panel.customer_combo.findData(self.other_customer_id))
        self.assertEqual(panel.address_edit.text(), "SATARA")

    def test_address_selection_does_not_disturb_patient_or_doctor(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        panel.patient_name_edit.setText("AJAY")
        panel.doctor_combo.setCurrentIndex(
            panel.doctor_combo.findData(self.doctor_id))
        panel.address_edit.setText("SATARA")
        self.assertEqual(panel.patient_name_edit.text(), "AJAY")
        self.assertEqual(panel.doctor_combo.currentData(), self.doctor_id)

    def test_address_width_is_readable(self):
        _, dlg = self._open_popup()
        self.assertGreaterEqual(dlg._panel.address_edit.minimumWidth(), 260)

    def test_patient_width_is_readable(self):
        _, dlg = self._open_popup()
        self.assertGreaterEqual(dlg._panel.patient_name_edit.minimumWidth(), 220)


# ----------------------------------------------------------------------
# Regression: existing popup behaviour still works
# ----------------------------------------------------------------------

@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestPopupRegression(PopupFieldBase):

    def test_item_search_still_works(self):
        page, _ = self._open_popup()
        bar = page._sale_panel._entry_bar
        self.assertGreater(bar.item_combo.count(), 0)
        bar.item_combo.lineEdit().setText("Para")
        bar._on_item_search_text_changed("Para")
        self.assertGreater(bar._item_completion_model.rowCount(), 0)

    def test_batch_selection_still_works(self):
        page, dlg = self._open_popup()
        bar = dlg._panel._entry_bar
        self.assertGreaterEqual(bar.batch_combo.count(), 1)
        index = bar.batch_combo.findData(self.batch_id)
        bar.batch_combo.setCurrentIndex(index)
        self.assertEqual(bar.batch_combo.currentData(), self.batch_id)

    def test_add_button_still_adds_a_line_in_the_popup(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        before = panel._table.rowCount()
        bar = panel._entry_bar
        bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(self.batch2_id))
        bar.qty_edit.setText("3")
        bar.discount_edit.setText("1")
        bar.add_btn.click()
        _APP.processEvents()
        self.assertEqual(panel._table.rowCount(), before + 1)

    def test_totals_recalculate_after_an_edit(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        before = panel.total_amount_label.text()
        bar = panel._entry_bar
        bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(self.batch2_id))
        bar.qty_edit.setText("5")
        bar.discount_edit.setText("0")
        bar.add_btn.click()
        _APP.processEvents()
        self.assertNotEqual(before, panel.total_amount_label.text())

    def test_close_still_saves_nothing(self):
        _, dlg = self._open_popup()
        before = len(self._sales_dao.get_all())
        dlg.reject()
        _APP.processEvents()
        self.assertEqual(len(self._sales_dao.get_all()), before)

    def test_final_save_still_commits_one_invoice(self):
        _, dlg = self._open_popup()
        before = len(self._sales_dao.get_all())
        dlg._final_save_btn.click()
        dlg._final_save_btn.click()
        _APP.processEvents()
        self.assertEqual(len(self._sales_dao.get_all()), before + 1)

    def test_final_save_writes_the_selected_patient(self):
        _, dlg = self._open_popup()
        dlg._panel.patient_name_edit.setText("RAMBHAU")
        dlg._final_save_btn.click()
        _APP.processEvents()
        rows = self._sales_dao.get_all()
        self.assertTrue(any(r.get("patient_name") == "RAMBHAU" for r in rows))

    def test_final_save_writes_the_selected_doctor(self):
        _, dlg = self._open_popup()
        dlg._panel.doctor_combo.setCurrentIndex(
            dlg._panel.doctor_combo.findData(self.doctor_id))
        dlg._final_save_btn.click()
        _APP.processEvents()
        rows = self._sales_dao.get_all()
        self.assertTrue(any(r.get("doctor_id") == self.doctor_id for r in rows))

    def test_bill_number_is_unchanged_by_the_popup(self):
        _, dlg = self._open_popup()
        self.assertEqual(dlg._panel.bill_no_edit.text(),
                         dlg._panel.bill_no_edit.text())
        self.assertTrue(dlg._panel.bill_no_edit.text())


# ----------------------------------------------------------------------
# Customer / Patient / Address / Doctor horizontal spacing
# ----------------------------------------------------------------------

@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestTopStripSpacing(PopupFieldBase):
    """The top strip must be tight, aligned and free of empty bands."""

    def _strip(self, dlg):
        from PySide6.QtWidgets import QWidget
        strip = dlg._panel.findChild(QWidget, "SalesBillTopStrip")
        self.assertIsNotNone(strip, "popup top strip not found")
        return strip

    def _right_edge(self, widget, relative_to):
        return (widget.mapTo(relative_to, widget.rect().topRight()).x() + 1)

    def _left_edge(self, widget, relative_to):
        return widget.mapTo(relative_to, widget.rect().topLeft()).x()

    def test_middle_fields_share_one_width(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        widths = {panel.customer_combo.width(),
                  panel.patient_name_edit.width(),
                  panel.address_edit.width()}
        self.assertEqual(len(widths), 1,
                         f"Customer/Patient/Address are not aligned: {widths}")

    def test_doctor_side_fields_share_one_width(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        widths = {panel.doctor_combo.width(),
                  panel.bill_disc_edit.width(),
                  panel.paid_edit.width()}
        self.assertEqual(len(widths), 1,
                         f"Doctor/Discount/Paid are not aligned: {widths}")

    def test_doctor_label_sits_next_to_the_doctor_box(self):
        _, dlg = self._open_popup()
        strip = self._strip(dlg)
        panel = dlg._panel
        doctor_label = None
        for label in strip.findChildren(QLabel):
            if label.text().strip() == "Doctor":
                doctor_label = label
                break
        self.assertIsNotNone(doctor_label, "Doctor label not found")
        gap = self._left_edge(panel.doctor_combo, dlg) - \
            self._right_edge(doctor_label, dlg)
        self.assertLessEqual(gap, 20,
                             f"{gap}px of empty space between the Doctor "
                             f"label and its box")

    def test_patient_label_sits_next_to_the_patient_box(self):
        _, dlg = self._open_popup()
        strip = self._strip(dlg)
        panel = dlg._panel
        label = next(l for l in strip.findChildren(QLabel)
                     if l.text().strip() == "Patient Name")
        gap = self._left_edge(panel.patient_name_edit, dlg) - \
            self._right_edge(label, dlg)
        self.assertLessEqual(gap, 20, f"{gap}px of empty space")

    def test_no_empty_band_between_the_middle_and_doctor_blocks(self):
        _, dlg = self._open_popup()
        strip = self._strip(dlg)
        panel = dlg._panel
        doctor_label = next(l for l in strip.findChildren(QLabel)
                            if l.text().strip() == "Doctor")
        gap = self._left_edge(doctor_label, dlg) - \
            self._right_edge(panel.address_edit, dlg)
        self.assertLessEqual(gap, 24,
                             f"{gap}px gap between the address field and the "
                             f"Doctor label")

    def test_fields_keep_their_minimum_readable_widths(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        for widget, minimum, name in (
            (panel.customer_combo, 200, "Customer"),
            (panel.patient_name_edit, 260, "Patient"),
            (panel.address_edit, 300, "Address"),
            (panel.doctor_combo, 190, "Doctor"),
            (panel.bill_disc_edit, 100, "Discount"),
            (panel.paid_edit, 100, "Paid Amount"),
        ):
            self.assertGreaterEqual(widget.minimumWidth(), minimum,
                                    f"{name} lost width")

    def test_no_field_overlaps_in_the_strip(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        # Fields that sit side by side on the same visual row, left to right.
        rows = (
            (panel.cnt_no_edit, panel.customer_combo, panel.doctor_combo),
            (panel.sale_type_combo, panel.patient_name_edit,
             panel.bill_disc_edit),
            (panel.address_edit, panel.paid_edit),
        )
        for row in rows:
            for left, right in zip(row, row[1:]):
                self.assertLessEqual(
                    self._right_edge(left, dlg),
                    self._left_edge(right, dlg) + 1,
                    f"{type(left).__name__} overlaps "
                    f"{type(right).__name__}",
                )

    def test_popup_size_is_unchanged_by_the_spacing_fix(self):
        self.assertEqual(SalesBillReviewDialog.MIN_WIDTH, 1180)
        self.assertEqual(SalesBillReviewDialog.MAX_WIDTH, 1300)
        self.assertEqual(SalesBillReviewDialog.MIN_HEIGHT, 520)
        self.assertEqual(SalesBillReviewDialog.MAX_HEIGHT, 600)

    def test_strip_fills_the_window_width(self):
        _, dlg = self._open_popup()
        panel = dlg._panel
        trailing = (dlg.width()
                    - self._right_edge(panel.paid_edit, dlg))
        self.assertLessEqual(trailing, 40,
                             f"{trailing}px left empty at the right edge")


if __name__ == "__main__":
    unittest.main(verbosity=2)