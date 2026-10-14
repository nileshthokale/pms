"""Focused GUI tests — Counter Sale responsive item entry bar.

The active item entry used to be split across two stacked rows:

    ROW 1: CNo | Item | Batch | Qty | Disc | Add
    ROW 2: Pack | Loc   | Exp  | MRP | Avail | Amount

The inline Counter Sale keeps the entry order across two compact lanes:

    CNo | Item | Batch | Pack | Loc | Exp
    MRP | Avail | Qty | Disc | Amount | + Add

Required contract covered here:

    01  all entry fields exist
    02  fields appear in the required order across two horizontal lanes
    03  both lanes stay inside the entry bar without overlap
    04  row fits at 1366x768
    05  row fits at 1600x900
    06  row fits at 1920x1080
    07  Item field remains usable
    08  Batch field remains usable
    09  Qty remains usable
    10  Discount remains usable
    11  Add button remains usable
    12  keyboard navigation remains functional
    13  item selection remains functional
    14  batch selection remains functional
    15  live draft stock remains functional
    16  same-batch merge remains functional

plus the structural details of the merge: exact field order, read-only
fields staying read-only, and the declared tab order.

GUI tests are skipped only when PySide6 is unavailable.
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.sales_dao import SalesDAO
from test_counter_sale_input import _DBBase

try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication, QBoxLayout, QMessageBox,
    )

    from screens.counter_sale import CounterSalePage

    HAS_PYSIDE6 = True
    _SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover - headless environments
    HAS_PYSIDE6 = False
    _SKIP_REASON = f"PySide6 not available ({_exc})"


# Exact left-to-right order of the single row.
LABEL_ORDER = ("CNo", "Item", "Batch", "Pack", "Loc", "Exp", "MRP",
               "Avail", "Qty", "Disc", "Amt")
FIELD_ORDER = ("cno_label", "item_combo", "batch_combo", "pack_edit",
               "location_edit", "expiry_edit", "mrp_edit", "stock_edit",
               "qty_edit", "discount_edit", "amount_edit", "add_btn")
READ_ONLY_FIELDS = ("cno_label", "pack_edit", "location_edit", "expiry_edit",
                    "mrp_edit", "stock_edit", "amount_edit")
EDITABLE_FIELDS = ("item_combo", "batch_combo", "qty_edit", "discount_edit")
SIZES = ((1366, 768), (1600, 900), (1920, 1080))


@unittest.skipUnless(HAS_PYSIDE6, _SKIP_REASON)
class CounterSaleEntryRowTests(_DBBase):
    """One horizontal entry row — structure, fit and behaviour."""

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

        self.page = CounterSalePage()
        self.page.resize(1366, 768)
        self.page.show()
        self.app.processEvents()
        self.page._apply_history_height()
        self.app.processEvents()

        self.panel = self.page._sale_panel
        self.entry = self.panel._entry_bar
        self.item = self.entry.item_combo
        self.batch = self.entry.batch_combo
        self.qty = self.entry.qty_edit
        self.discount = self.entry.discount_edit
        self.add = self.entry.add_btn

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        self.app.processEvents()

    # -- helpers ------------------------------------------------------
    def _resize(self, width: int, height: int):
        self.page.resize(width, height)
        self.app.processEvents()
        self.page._apply_history_height()
        self.app.processEvents()

    def _layout_rows(self):
        """Return widgets for each horizontal lane, in layout order."""
        rows = []
        layout = self.entry.layout()
        for i in range(layout.count()):
            row_layout = layout.itemAt(i).layout()
            if row_layout is None:
                continue
            rows.append([
                row_layout.itemAt(j).widget()
                for j in range(row_layout.count())
                if row_layout.itemAt(j).widget() is not None
            ])
        return rows

    def _layout_widgets(self):
        return [widget for row in self._layout_rows() for widget in row]

    def _select_item(self):
        self.item.setCurrentIndex(self.item.findData(self.item_id))
        self.app.processEvents()

    def _select_batch(self):
        self.batch.setCurrentIndex(1)
        self.app.processEvents()

    def _add(self, qty: str = "1"):
        self.qty.setText(qty)
        self.discount.setText("0.00")
        self.add.click()
        self.app.processEvents()

    def _assert_fits(self):
        """Both lanes fit at their readable floors without overlapping."""
        layout = self.entry.layout()
        margins = layout.contentsMargins()

        self.assertLessEqual(
            layout.minimumSize().width(), self.entry.width(),
            "entry lanes require more width than the entry bar")

        for row in self._layout_rows():
            previous_end = None
            for widget in row:
                self.assertGreaterEqual(
                    widget.width(), widget.minimumWidth(),
                    f"{widget.objectName() or widget} squeezed below its minimum")
                position = widget.mapTo(self.entry, widget.rect().topLeft())
                if previous_end is not None:
                    self.assertGreaterEqual(
                        position.x(), previous_end,
                        "entry fields overlap within a lane")
                previous_end = position.x() + widget.width()
                self.assertGreaterEqual(position.y(), margins.top())
                self.assertLessEqual(
                    position.y() + widget.height(),
                    self.entry.height() - margins.bottom(),
                )
            self.assertLessEqual(
                previous_end, self.entry.width() - margins.right(),
                "entry lane overflows the right edge of the bar")

    def _focus_candidates(self, widget):
        """A combo is focused through its line-edit focus proxy."""
        if hasattr(widget, "lineEdit"):
            return (widget, widget.lineEdit())
        return (widget,)

    # -- 1. fields ----------------------------------------------------
    def test_01_all_entry_fields_exist(self):
        """01: every field of the entry bar exists."""
        for name in FIELD_ORDER:
            self.assertTrue(hasattr(self.entry, name),
                            f"entry field missing: {name}")

        labels = [w.text() for w in self.entry.findChildren(type(self.entry.cno_label))]
        for text in LABEL_ORDER:
            self.assertIn(text, labels, f"label missing: {text}")

    def test_01a_draft_identity_is_consistent(self):
        self.assertEqual(self.page._current_bill_no_label.text(),
                         "Bill: New Bill (Draft)")
        self.assertEqual(self.page._current_bill_no_label.toolTip(),
                         "New Bill (Draft)")
        self.assertEqual(self.entry.cno_label.text(), "Draft")
        self.assertEqual(self.entry.cno_label.toolTip(), "New Bill (Draft)")

    # -- 2. two ordered lanes ----------------------------------------
    def test_02_fields_follow_order_across_two_lanes(self):
        """02: the full field order is preserved across two lanes."""
        layout = self.entry.layout()
        self.assertEqual(layout.direction(), QBoxLayout.TopToBottom)
        rows = self._layout_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self._layout_widgets()),
                         len(LABEL_ORDER) + len(FIELD_ORDER))
        for field_names in (FIELD_ORDER[:6], FIELD_ORDER[6:]):
            xs = [getattr(self.entry, name).mapTo(
                self.entry, getattr(self.entry, name).rect().topLeft()
            ).x() for name in field_names]
            self.assertEqual(xs, sorted(xs), "entry fields are out of order")
        self.assertLess(
            self.entry.expiry_edit.mapTo(
                self.entry, self.entry.expiry_edit.rect().center()
            ).y(),
            self.entry.mrp_edit.mapTo(
                self.entry, self.entry.mrp_edit.rect().center()
            ).y(),
            "the lower lane must continue after Expiry",
        )
        self.assertLessEqual(self.entry.height(), 100)

    # -- 4-6. fits at the three target resolutions --------------------
    def test_04_row_fits_at_1366x768(self):
        """04: both entry lanes fit at 1366x768."""
        self._resize(1366, 768)
        self._assert_fits()

    def test_05_row_fits_at_1600x900(self):
        """05: both entry lanes fit at 1600x900."""
        self._resize(1600, 900)
        self._assert_fits()

    def test_06_row_fits_at_1920x1080(self):
        """06: both entry lanes fit at 1920x1080."""
        self._resize(1920, 1080)
        self._assert_fits()

    def test_06b_item_is_the_expanding_widest_field(self):
        """Item Name remains the widest search field at supported widths."""
        for width, height in ((1600, 900), (1920, 1080)):
            with self.subTest(size=f"{width}x{height}"):
                self._resize(width, height)
                widths = {n: getattr(self.entry, n).width()
                          for n in FIELD_ORDER}
                self.assertEqual(
                    widths["item_combo"], max(widths.values()),
                    "Item Name must stay the widest entry field")

    # -- 7-11. fields stay usable ------------------------------------
    def test_07_item_field_remains_usable(self):
        """07: Item Name is editable, focusable and accepts typing."""
        self.assertFalse(self.item.isReadOnly())
        self.assertNotEqual(self.item.focusPolicy(), Qt.NoFocus)
        self.assertGreaterEqual(self.item.width(), self.item.minimumWidth())

        self.item.setFocus()
        self.app.processEvents()
        QTest.keyClicks(self.item.lineEdit(), "Test")
        self.app.processEvents()
        self.assertIn("Test", self.item.lineEdit().text(),
                      "typing into Item Name did not reach the field")

    def test_08_batch_field_remains_usable(self):
        """08: Batch is editable, focusable and loads batch choices."""
        self._select_item()
        self.assertFalse(self.batch.isReadOnly())
        self.assertNotEqual(self.batch.focusPolicy(), Qt.NoFocus)
        self.assertGreaterEqual(
            self.batch.count(), 2,
            "batch list should hold a placeholder plus real batches")
        self.assertGreaterEqual(self.batch.width(),
                                self.batch.minimumWidth())

    def test_09_qty_remains_usable(self):
        """09: Qty stays an editable numeric field."""
        self.assertFalse(self.qty.isReadOnly())
        self.assertNotEqual(self.qty.focusPolicy(), Qt.NoFocus)
        self.assertGreaterEqual(self.qty.width(), self.qty.minimumWidth())
        self.qty.setText("7")
        self.assertEqual(self.qty.text(), "7")

    def test_10_discount_remains_usable(self):
        """10: Discount stays an editable numeric field."""
        self.assertFalse(self.discount.isReadOnly())
        self.assertNotEqual(self.discount.focusPolicy(), Qt.NoFocus)
        self.assertGreaterEqual(self.discount.width(),
                                self.discount.minimumWidth())
        self.discount.setText("5.00")
        self.assertEqual(self.discount.text(), "5.00")

    def test_11_add_button_remains_usable(self):
        """11: the Add button is enabled, clickable and ends the lower lane."""
        self.assertEqual(self.add.text(), "+ Add")
        self.assertTrue(self.add.isEnabled())
        self.assertNotEqual(self.add.focusPolicy(), Qt.NoFocus)
        self.assertGreaterEqual(self.add.width(), self.add.minimumWidth())
        self.assertFalse(self.add.isHidden())
        # It is the last control in the ordered two-lane form.
        self.assertIs(self._layout_widgets()[-1], self.add)

    # -- 12. keyboard navigation -------------------------------------
    def test_12_keyboard_navigation_remains_functional(self):
        """12: TYPE -> Down -> Enter -> batch -> Down -> Enter -> Tab ..."""
        self.item.setFocus()
        self.app.processEvents()
        QTest.keyClicks(self.item.lineEdit(), "Test")
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.item.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertIn(QApplication.focusWidget(),
                      self._focus_candidates(self.batch),
                      "Enter on an item must move focus to Batch")

        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Down)
        QTest.keyClick(self.batch.lineEdit(), Qt.Key_Return)
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), self.qty,
                      "Enter on a batch must move focus to Qty")

        QTest.keyClick(self.qty, Qt.Key_Tab)
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), self.discount,
                      "Tab from Qty must reach Discount")

        QTest.keyClick(self.discount, Qt.Key_Tab)
        self.app.processEvents()
        self.assertIs(QApplication.focusWidget(), self.add,
                      "Tab from Discount must reach Add")

    # -- 13-14. selection --------------------------------------------
    def test_13_item_selection_remains_functional(self):
        """13: choosing an item loads its batches."""
        self._select_item()
        self.assertEqual(self.item.currentData(), self.item_id)
        self.assertGreaterEqual(
            self.batch.count(), 2,
            "item selection did not load the batch list")
        self.assertIn(QApplication.focusWidget(),
                      self._focus_candidates(self.batch),
                      "item selection must hand focus to Batch")

    def test_14_batch_selection_remains_functional(self):
        """14: choosing a batch auto-fills the read-only detail fields."""
        self._select_item()
        self._select_batch()

        self.assertTrue(self.entry.pack_edit.text(), "Pack not filled")
        self.assertTrue(self.entry.expiry_edit.text(), "Expiry not filled")
        self.assertTrue(self.entry.mrp_edit.text(), "MRP not filled")
        self.assertTrue(self.entry.stock_edit.text(), "Avail not filled")
        self.assertEqual(self.batch.lineEdit().cursorPosition(), 0,
                 "selected batch text must begin with its batch number")
        self.assertEqual(self.batch.currentData(), self.batch_id)

    # -- 15. live draft stock ----------------------------------------
    def test_15_live_draft_stock_remains_functional(self):
        """15: an unsold draft lowers availability on screen only."""
        stored = SalesDAO.get_batch_by_id(self.batch_id)["stock_qty"]

        self._select_item()
        self._select_batch()
        self.assertEqual(float(self.entry.stock_edit.text()), float(stored))

        self._add("1")
        self.assertEqual(self.panel._table.rowCount(), 1)

        # Re-select: the screen shows stored minus the draft reservation...
        self._select_item()
        self._select_batch()
        self.assertEqual(float(self.entry.stock_edit.text()),
                         float(stored) - 1.0,
                         "live draft stock did not react to the draft row")

        # ...while the stored batch row is untouched until Save.
        self.assertEqual(
            SalesDAO.get_batch_by_id(self.batch_id)["stock_qty"], stored,
            "draft row must not change stored stock")

    # -- 16. same-batch merge ----------------------------------------
    def test_16_same_batch_merge_remains_functional(self):
        """16: adding the same item+batch twice merges into one row."""
        self._select_item()
        self._select_batch()
        self._add("1")

        self._select_item()
        self._select_batch()
        self._add("1")

        self.assertEqual(self.panel._table.rowCount(), 1,
                         "same batch created a second row")
        self.assertEqual(len(self.panel._item_rows), 1)
        self.assertEqual(self.panel._item_rows[0].sale_qty, 2.0,
                         "merged quantity is not 2")

    # -- structural extras -------------------------------------------
    def test_17_exact_field_order(self):
        """Captions and fields alternate in the required target order.

        Eleven caption/control pairs run left to right and the caption-less
        "+ Add" button closes the row, so the row is 23 widgets long.
        """
        field_names = {id(getattr(self.entry, name)): name for name in FIELD_ORDER}
        actual = []
        for widget in self._layout_widgets():
            name = field_names.get(id(widget))
            actual.append(name if name is not None else widget.text())
        expected: list[str] = []
        for text, name in zip(LABEL_ORDER, FIELD_ORDER):
            expected += [text, name]
        expected.append(FIELD_ORDER[-1])
        self.assertEqual(actual, expected)

    def test_18_read_only_fields_stay_read_only(self):
        """Auto-filled fields must never take keyboard focus or edits."""
        for name in READ_ONLY_FIELDS:
            widget = getattr(self.entry, name)
            self.assertEqual(widget.focusPolicy(), Qt.NoFocus,
                             f"{name} may steal keyboard focus")
        for name in ("pack_edit", "location_edit", "expiry_edit",
                     "mrp_edit", "stock_edit", "amount_edit"):
            self.assertTrue(getattr(self.entry, name).isReadOnly(),
                            f"{name} must stay read-only")
        for name in EDITABLE_FIELDS:
            widget = getattr(self.entry, name)
            if hasattr(widget, "isReadOnly"):
                self.assertFalse(widget.isReadOnly(),
                                 f"{name} must stay editable")

    def test_19_tab_order_chain(self):
        """Item -> Batch -> Qty -> Discount -> Add (read-only skipped)."""
        order = (self.item, self.batch, self.qty, self.discount, self.add)
        for index, source in enumerate(order[:-1]):
            target = order[index + 1]
            source.setFocus()
            self.app.processEvents()
            QTest.keyClick(source, Qt.Key_Tab)
            self.app.processEvents()
            self.assertIn(
                QApplication.focusWidget(), self._focus_candidates(target),
                f"Tab from {source} did not reach {target}")

    def test_20_labels_stay_compact(self):
        """Captions stay compact but must read as bold black 12-14 px text."""
        import re

        for text in LABEL_ORDER:
            label = next(w for w in self.entry.findChildren(
                type(self.entry.cno_label)) if w.text() == text)
            match = re.search(r"font-size:\s*(\d+)px", label.styleSheet())
            self.assertIsNotNone(match, f"{text} lost its font size")
            self.assertGreaterEqual(int(match.group(1)), 12)
            self.assertLessEqual(int(match.group(1)), 14)
            self.assertIn("font-weight: bold", label.styleSheet(),
                          f"{text} caption must be bold")
            self.assertIn("#000000", label.styleSheet(),
                          f"{text} caption must be black")


if __name__ == "__main__":
    unittest.main(verbosity=2)
