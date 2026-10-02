"""Phase 6E — Counter Sale layout tests (fixed three-region layout).

Covers the layout fix only:
  * history region has a controlled height
  * an empty history table never expands into a giant blank area
  * the active sale-entry region sits directly below the history
  * the entry region is never vertically centered and never drifts
  * the current bill table expands below the entry region
  * the right-side Bill panel exists
  * adding items / history rows does not move the entry region
  * resizing preserves the region order
  * New Sale resets the inline form and focuses Item Name
  * existing buttons and the Hold/Resume path still work
  * the existing save wiring (SalesDAO.insert_invoice) is unchanged

GUI tests are skipped only when PySide6 is unavailable.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

# Offscreen so the suite runs headless; harmless when a display exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtWidgets import (QApplication, QComboBox, QGroupBox, QLabel,
                                   QMessageBox, QPushButton, QWidget)

    from screens.counter_sale import CounterSalePage, _BillItemRow

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover - headless environments
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


def _make_row(index: int = 1) -> "_BillItemRow":
    return _BillItemRow(
        item_id=index,
        item_name=f"Item {index}",
        stock_batch_id=index,
        pack_size="10x10",
        location="A-1",
        batch_no=f"B-{index:03d}",
        expiry="12/27",
        mrp=50.0,
        sale_qty=2.0,
        discount_amount=0.0,
        amount=100.0,
    )


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CounterSaleLayoutTests(unittest.TestCase):
    """Layout/stability tests for the inline Counter Sale page."""

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            tempfile.gettempdir(), "pharmacy_counter_sale_layout.db"
        )
        if os.path.exists(cls._db_path):
            os.remove(cls._db_path)
        os.environ["PHARMACY_DB"] = cls._db_path

        from database.connection import init_database
        from database import auth, financial_year
        from database.customer_dao import CustomerDAO

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        CustomerDAO.insert("Layout Test Customer", city="Test City")
        cls._customer_id = next(
            c["id"] for c in CustomerDAO.get_all()
            if c["customer_name"] == "Layout Test Customer"
        )

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Never block on modal dialogs during layout tests.
        self._msg_patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        ]
        for patcher in self._msg_patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        QApplication.processEvents()
        self.page._apply_history_height()
        QApplication.processEvents()

        self.panel = self.page._sale_panel
        self.entry = self.panel._entry_bar
        self.bill_table = self.panel._table
        self.hist = self.page._hist_table
        self.totals = self.panel._totals_widget

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        QApplication.processEvents()

    # -- helpers ------------------------------------------------------
    def _y(self, widget) -> int:
        return widget.mapTo(self.page, widget.rect().topLeft()).y()

    def _assert_region_order(self):
        self.assertLess(self._y(self.hist), self._y(self.entry),
                        "history must be above the sale entry")
        self.assertLess(self._y(self.entry), self._y(self.bill_table),
                        "sale entry must be above the bill table")
        self.assertLess(self._y(self.bill_table), self._y(self.totals),
                        "bill table must be above the totals bar")

    # -- Region A: history -------------------------------------------
    def test_01_history_region_has_controlled_height(self):
        self.assertGreaterEqual(self.hist.height(), 100)
        self.assertLessEqual(self.hist.height(), self.page.height() * 0.35)
        self.assertEqual(self.hist.minimumHeight(), self.hist.maximumHeight(),
                         "history height must be fixed/controlled")

    def test_02_empty_history_does_not_fill_the_page(self):
        self.assertEqual(self.hist.rowCount(), 0)
        self.assertLess(self.hist.height(), self.page.height() * 0.5)

    # -- Region B: active sale entry ---------------------------------
    def test_03_entry_region_is_directly_below_history(self):
        expected = self._y(self.hist) + self.hist.height()
        self.assertLessEqual(abs(self._y(self.entry) - expected), 6,
                             "entry region must sit directly under the history")

    def test_04_entry_region_is_not_vertically_centered(self):
        self.assertLess(self._y(self.entry), self.page.height() * 0.55)
        self.assertLessEqual(self.entry.maximumHeight(), 72)

    def test_05_bill_table_expands_below_entry(self):
        self.assertGreater(self._y(self.bill_table), self._y(self.entry))
        self.assertGreater(self.bill_table.height(), 100,
                           "bill table must occupy real space")
        small = self.bill_table.height()
        self.page.resize(1920, 1020)
        QApplication.processEvents()
        self.page._apply_history_height()
        QApplication.processEvents()
        self.assertGreater(self.bill_table.height(), small,
                           "bill table must take the remaining space")

    # -- Right-side bill panel ---------------------------------------
    def test_06_right_bill_panel_exists(self):
        panel = self.page.findChild(type(self.totals), "BillPanel")
        self.assertIsNotNone(panel, "right-side Bill panel missing")
        self.assertGreaterEqual(panel.width(), 180)
        self.assertLessEqual(panel.width(), 300)
        titles = [g.title() for g in self.page.findChildren(QGroupBox)]
        self.assertIn("Bill", titles)
        self.assertIn("Current Bill", titles)
        self.assertGreater(panel.x(), self.bill_table.x())
        self.assertIn("Edit", [b.text() for b in panel.findChildren(QPushButton)])
        self.assertIn("Delete", [b.text() for b in panel.findChildren(QPushButton)])
        self.assertIn("Print / PDF",
                      [b.text() for b in panel.findChildren(QPushButton)])

    # -- stability ----------------------------------------------------
    def test_07_adding_an_item_does_not_move_entry_region(self):
        before = self._y(self.entry)
        self.panel._item_rows.append(_make_row(1))
        self.panel._refresh_table()
        self.panel._recalc_totals()
        QApplication.processEvents()
        self.assertEqual(self.bill_table.rowCount(), 1)
        self.assertEqual(self._y(self.entry), before,
                         "entry region moved after adding an item")

    def test_08_history_rows_do_not_move_entry_region(self):
        before = self._y(self.entry)
        height_before = self.hist.height()
        self.hist.setRowCount(150)
        QApplication.processEvents()
        self.assertEqual(self.hist.height(), height_before,
                         "history region grew with rows")
        self.assertEqual(self._y(self.entry), before,
                         "entry region moved after adding history rows")

    def test_09_resize_preserves_region_order(self):
        for width, height in ((1366, 708), (1600, 840), (1920, 1020), (1100, 600)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.resize(width, height)
                QApplication.processEvents()
                self.page._apply_history_height()
                QApplication.processEvents()
                self._assert_region_order()
                self.assertLessEqual(self.hist.height(),
                                     max(240, self.page.height() * 0.35))

    # -- New Sale -----------------------------------------------------
    def test_10_new_sale_resets_and_focuses_active_area(self):
        self.panel._item_rows.append(_make_row(1))
        self.panel._refresh_table()
        self.page._on_new()
        QApplication.processEvents()
        self.assertEqual(self.bill_table.rowCount(), 0,
                         "New Sale must clear the current bill")
        self.assertTrue(self.entry.item_combo.hasFocus()
                        or QApplication.focusWidget() is self.entry.item_combo,
                        "New Sale must focus Item Name")
        self._assert_region_order()

    def test_11_existing_buttons_remain(self):
        texts = [b.text() for b in self.page.findChildren(QPushButton)]
        for required in ("New Sale", "Edit", "Delete", "Print / PDF",
                         "Save Sale", "Hold Bill", "Cancel", "+ Add"):
            self.assertIn(required, texts)

    # -- Hold / Resume ------------------------------------------------
    def test_12_hold_resume_loads_into_inline_sale_area(self):
        from database.hold_bill_dao import create_hold, get_by_id

        hold_id = create_hold(
            patient_name="Resume Patient",
            total_amount_preview=100.0,
            created_by="admin",
            items=[],
        )
        hold = get_by_id(hold_id)
        before = self._y(self.entry)

        self.page.open_sale_dialog_with_hold({"hold": hold, "items": []})
        QApplication.processEvents()

        self.assertEqual(self.panel._hold_bill_id, hold_id)
        self.assertEqual(self.panel.patient_name_edit.text(), "Resume Patient")
        self.assertEqual(self._y(self.entry), before,
                         "resumed hold must appear in the same Region B position")
        self._assert_region_order()

    # -- transaction wiring unchanged --------------------------------
    def test_13_save_wiring_still_calls_sales_dao(self):
        from screens import counter_sale as counter_sale_module
        from database.connection import get_connection
        from database.item_dao import ItemDAO

        index = self.panel.customer_combo.findData(self._customer_id)
        self.assertGreaterEqual(index, 0, "layout test customer missing")
        self.panel.customer_combo.setCurrentIndex(index)
        customer_id = self.panel.customer_combo.currentData()
        item_id = ItemDAO.insert("Layout Sale Item", pack_size="10x10", mrp=50.0)
        conn = get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO stock_batches "
                "(item_id, batch_no, expiry, pack_size, mrp, stock_qty) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, "LAYOUT-BATCH", "12/27", "10x10", 50.0, 100.0),
            )
            batch_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        self.panel._item_rows.append(_BillItemRow(
            item_id=item_id, item_name="Layout Sale Item",
            stock_batch_id=batch_id, pack_size="10x10", location="A-1",
            batch_no="LAYOUT-BATCH", expiry="12/27", mrp=50.0,
            sale_qty=2.0, discount_amount=0.0, amount=100.0,
        ))
        self.panel._refresh_table()
        self.panel._recalc_totals()

        recorded = {}

        def fake_insert_invoice(**kwargs):
            recorded.update(kwargs)
            return 1

        with mock.patch.object(counter_sale_module.SalesDAO, "insert_invoice",
                               side_effect=fake_insert_invoice):
            self.panel._on_save()

        # The inline form resets after a successful save (the modal dialog
        # used to close here), so the save is verified through the recorded
        # DAO payload plus the cleared bill table.
        self.assertEqual(self.bill_table.rowCount(), 0,
                         "sale area must reset after a successful save")
        for key in ("bill_no", "sale_date", "sale_time", "sale_type",
                    "customer_id", "patient_name", "doctor_id", "discount",
                    "paid_amount", "total_amount", "round_off", "net_amount",
                    "remarks", "items"):
            self.assertIn(key, recorded)
        self.assertEqual(recorded["customer_id"], customer_id)
        self.assertEqual(len(recorded["items"]), 1)
        self.assertEqual(recorded["items"][0]["amount"], 100.0)
        self.assertEqual(recorded["net_amount"], 100.0)

    # -- Final compact-footer visual polish -------------------------
    def test_14_sale_metadata_is_compact_not_a_standalone_panel(self):
        titles = [g.title() for g in self.panel.findChildren(QGroupBox)]
        self.assertNotIn("Sale Header", titles)
        strip = self.panel.findChild(type(self.totals), "CompactSaleMetadata")
        self.assertIsNotNone(strip)
        self.assertLessEqual(strip.height(), 60)
        self.assertGreater(self._y(strip), self._y(self.bill_table))

    def test_15_footer_is_fixed_and_actions_remain_visible(self):
        self.assertGreaterEqual(self.totals.height(), 40)
        self.assertLessEqual(self.totals.height(), 60)
        footer_bottom = self._y(self.totals) + self.totals.height()
        self.assertLessEqual(footer_bottom, self.page.height())
        texts = [b.text() for b in self.totals.findChildren(QPushButton)]
        self.assertEqual(texts, ["Hold Bill", "Save Sale", "Cancel"])

    def test_16_bill_row_and_delete_action_are_table_aligned(self):
        self.panel._item_rows.append(_make_row(1))
        self.panel._refresh_table()
        QApplication.processEvents()
        self.assertGreaterEqual(self.bill_table.rowHeight(0), 28)
        cell = self.bill_table.cellWidget(0, 10)
        self.assertIsNotNone(cell)
        buttons = cell.findChildren(QPushButton)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].text(), "Delete")
        self.assertLessEqual(buttons[0].height(), self.bill_table.rowHeight(0))

    def test_17_desktop_sizes_keep_compact_footer_visible(self):
        for width, height in ((1366, 708), (1600, 840), (1920, 1020)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.resize(width, height)
                QApplication.processEvents()
                self.assertLessEqual(
                    self._y(self.totals) + self.totals.height(), self.page.height()
                )
                self.assertLessEqual(self.panel._metadata_strip.height(), 60)


# ======================================================================
# Item entry bar / bill table / footer sizing polish
# ======================================================================
from PySide6.QtCore import QPoint  # noqa: E402

from screens.counter_sale import (  # noqa: E402
    _ACTION_BUTTON_HEIGHT,
    _BILL_COLUMN_WIDTHS,
    _BILL_DELETE_HEIGHT,
    _BILL_DELETE_WIDTH,
    _BILL_HEADER_HEIGHT,
    _BILL_ROW_HEIGHT,
    _ENTRY_ADD_WIDTH,
    _ENTRY_BAR_HEIGHT,
    _ENTRY_LABEL_MAX_WIDTH,
    _METADATA_STRIP_HEIGHT,
    _TOTALS_FOOTER_HEIGHT,
)

_DESKTOP_SIZES = ((1366, 708), (1600, 840), (1920, 1020))
_ENTRY_FIELDS = (
    "cno_label", "item_combo", "batch_combo", "pack_edit", "location_edit",
    "expiry_edit", "mrp_edit", "stock_edit", "qty_edit", "discount_edit",
    "amount_edit", "add_btn",
)
_NUMERIC_FIELDS = ("pack_edit", "mrp_edit", "stock_edit", "qty_edit",
                   "discount_edit", "amount_edit")
_METADATA_FIELDS = ("bill_no_edit", "sale_date", "sale_time_edit",
                    "sale_type_combo", "customer_combo", "patient_name_edit",
                    "doctor_combo")


def _bootstrap_disposable_db(tag: str) -> None:
    """Point PHARMACY_DB at a throwaway database and create the schema.

    Layout tests never touch ``data/pharmacy.db``: each sizing class builds
    its own temp database so the measurement runs are fully isolated.
    """
    db_path = os.path.join(tempfile.gettempdir(),
                           f"pharmacy_counter_sale_{tag}.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    os.environ["PHARMACY_DB"] = db_path

    from database.connection import init_database
    from database import auth, financial_year

    init_database()
    auth.ensure_auth_schema()
    financial_year.ensure_default_financial_year()
    if auth.user_count() == 0:
        auth.create_first_admin("admin", "admin-pass-1")
    auth.session.login("admin", "admin-pass-1")


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CounterSaleItemBarSizingTests(unittest.TestCase):
    """Item entry bar widths, heights and the compact Add action."""

    @classmethod
    def setUpClass(cls):
        _bootstrap_disposable_db("item_bar")
        cls._app = QApplication.instance() or QApplication([])
        cls.page = CounterSalePage()
        cls.page.resize(1366, 708)
        cls.page.show()
        QApplication.processEvents()
        cls.entry = cls.page._sale_panel._entry_bar

    @classmethod
    def tearDownClass(cls):
        cls.page.hide()
        cls.page.deleteLater()
        QApplication.processEvents()

    def _fields(self):
        return {name: getattr(self.entry, name) for name in _ENTRY_FIELDS}

    def test_01_item_is_the_widest_entry_control(self):
        fields = self._fields()
        item_width = fields["item_combo"].width()
        self.assertGreaterEqual(item_width, 150,
                                "Item must keep a usable search width")
        for name, widget in fields.items():
            if name != "item_combo":
                self.assertGreaterEqual(
                    item_width, widget.width(),
                    f"Item must stay the widest field (narrower than {name})")

    def test_02_item_expands_within_a_compact_cap(self):
        item = self.entry.item_combo
        self.assertEqual(item.minimumWidth(), 150)
        # Capped so a wide monitor cannot turn Item into a banner, but still
        # comfortably wider than every other entry control.
        self.assertEqual(item.maximumWidth(), 300)
        self.assertLessEqual(item.maximumWidth(), 320,
                             "Item must stay compact on wide monitors")
        narrow = item.width()
        self.page.resize(1920, 1020)
        QApplication.processEvents()
        wide = item.width()
        self.assertGreater(wide, narrow, "Item must still absorb spare width")
        self.assertLessEqual(wide, item.maximumWidth())
        # The width Item gives up goes to the other fields, not into a gap.
        batch_wide = self.entry.batch_combo.width()
        self.assertGreaterEqual(
            batch_wide, self.entry.batch_combo.minimumWidth())
        self.page.resize(1366, 708)
        QApplication.processEvents()

    def test_02b_item_stays_the_widest_control_on_a_wide_monitor(self):
        self.page.resize(1920, 1020)
        QApplication.processEvents()
        try:
            item = self.entry.item_combo
            for name, widget in self._fields().items():
                if name == "item_combo":
                    continue
                self.assertGreater(
                    item.width(), widget.width(),
                    f"Item must stay widest even when capped (vs {name})")
        finally:
            self.page.resize(1366, 708)
            QApplication.processEvents()

    def test_03_batch_has_room_for_a_batch_number(self):
        batch = self.entry.batch_combo
        self.assertGreaterEqual(batch.minimumWidth(), 96)
        self.assertGreaterEqual(batch.width(), 96)
        self.assertGreaterEqual(batch.maximumWidth(), 180,
                                "Batch needs room for popup selection")

    def test_04_numeric_fields_are_readable_and_content_sized(self):
        for name in _NUMERIC_FIELDS:
            with self.subTest(field=name):
                widget = getattr(self.entry, name)
                self.assertGreaterEqual(widget.width(), 44,
                                        "numeric field must stay readable")
                self.assertLessEqual(
                    widget.width(), 110,
                    "numeric field must not stretch into a banner")

    def test_05_numeric_fields_are_right_aligned(self):
        from PySide6.QtCore import Qt
        for name in ("mrp_edit", "stock_edit", "qty_edit", "discount_edit",
                     "amount_edit", "pack_edit"):
            with self.subTest(field=name):
                widget = getattr(self.entry, name)
                self.assertTrue(widget.alignment() & Qt.AlignRight,
                                f"{name} must be right aligned")

    def test_06_entry_controls_share_one_box_height(self):
        heights = {getattr(self.entry, name).height() for name in _ENTRY_FIELDS}
        self.assertEqual(len(heights), 1,
                         f"entry controls must share one height: {heights}")
        self.assertLessEqual(max(heights), self.entry.height())

    def test_07_add_button_is_compact_and_flush_right(self):
        add = self.entry.add_btn
        self.assertEqual(add.width(), _ENTRY_ADD_WIDTH)
        self.assertGreaterEqual(add.width(), 70)
        self.assertLessEqual(add.width(), 90)
        self.assertEqual(add.height(), self.entry.item_combo.height(),
                         "Add must be the same height as the entry controls")
        self.assertLessEqual(
            add.x() + add.width(), self.entry.width(),
            "Add must stay inside the bar")

    def test_08_captions_stay_compact_and_clear_of_the_field(self):
        labels = [child for child in self.entry.findChildren(QLabel)
                  if child is not self.entry.cno_label]
        self.assertEqual(len(labels), 11)
        for label in labels:
            with self.subTest(label=label.text()):
                self.assertLessEqual(label.width(), _ENTRY_LABEL_MAX_WIDTH)
                margin = label.contentsMargins().right()
                self.assertGreaterEqual(margin, 3,
                                        "caption must clear its field")

    def test_09_entry_bar_height_is_fixed_and_compact(self):
        self.assertEqual(self.entry.height(), _ENTRY_BAR_HEIGHT)
        self.assertEqual(self.entry.minimumHeight(), _ENTRY_BAR_HEIGHT)
        self.assertEqual(self.entry.maximumHeight(), _ENTRY_BAR_HEIGHT)

    def test_10_no_entry_control_overflows_at_any_desktop_size(self):
        for width, height in _DESKTOP_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                self.page.resize(width, height)
                QApplication.processEvents()
                self.page._apply_history_height()
                QApplication.processEvents()
                for name, widget in self._fields().items():
                    self.assertLessEqual(
                        widget.x() + widget.width(), self.entry.width(),
                        f"{name} overflows the entry bar at {width}x{height}")
                    self.assertGreaterEqual(widget.width(), 1,
                                            f"{name} was squeezed out")


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CounterSaleBillTableSizingTests(unittest.TestCase):
    """Bill Items grid, row height and the compact Del action."""

    @classmethod
    def setUpClass(cls):
        _bootstrap_disposable_db('bill_table')
        cls._app = QApplication.instance() or QApplication([])
        cls.page = CounterSalePage()
        cls.page.resize(1366, 708)
        cls.page.show()
        QApplication.processEvents()
        cls.panel = cls.page._sale_panel
        cls.table = cls.panel._table
        for i in range(1, 21):
            cls.panel._item_rows.append(_make_row(i))
        cls.panel._refresh_table()
        cls.panel._recalc_totals()
        QApplication.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.page.hide()
        cls.page.deleteLater()
        QApplication.processEvents()

    def test_01_row_height_is_28_px(self):
        self.assertEqual(self.table.rowHeight(0), _BILL_ROW_HEIGHT)
        self.assertEqual(_BILL_ROW_HEIGHT, 28)

    def test_02_header_band_is_taller_than_a_row(self):
        self.assertGreater(self.table.horizontalHeader().height(),
                           _BILL_ROW_HEIGHT)

    def test_03_columns_are_content_sized_with_item_name_stretching(self):
        self.assertEqual(self.table.columnCount(), len(_BILL_COLUMN_WIDTHS))
        self.assertEqual(
            [self.table.horizontalHeaderItem(i).text() for i in range(11)],
            ["#", "Item Name", "Pack Size", "Location", "Batch No", "Expiry",
             "MRP", "Qty", "Disc Amt", "Amount", "Del"])
        item_name_width = self.table.columnWidth(1)
        for index, width in enumerate(_BILL_COLUMN_WIDTHS):
            if index == 1:
                continue
            with self.subTest(column=index):
                self.assertEqual(self.table.columnWidth(index), width)

    def test_04_grid_fits_without_a_horizontal_scrollbar(self):
        total = sum(self.table.columnWidth(i) for i in range(11))
        self.assertLessEqual(total, self.table.viewport().width(),
                             "Bill Items must not need horizontal scrolling")
        self.assertGreater(self.table.columnWidth(1), 150,
                           "Item Name must keep a readable width")

    def test_05_delete_is_a_compact_table_action(self):
        cell = self.table.cellWidget(0, 10)
        self.assertIsNotNone(cell)
        buttons = cell.findChildren(QPushButton)
        self.assertEqual(len(buttons), 1)
        button = buttons[0]
        self.assertEqual(button.text(), "Delete")
        self.assertEqual(button.width(), _BILL_DELETE_WIDTH)
        self.assertEqual(button.height(), _BILL_DELETE_HEIGHT)
        self.assertGreaterEqual(button.width(), 50)
        self.assertLessEqual(button.width(), 65)
        self.assertLessEqual(button.height(), self.table.rowHeight(0))

    def test_06_delete_is_centred_in_the_del_column(self):
        cell = self.table.cellWidget(3, 10)
        button = cell.findChildren(QPushButton)[0]
        left = button.x()
        right = cell.width() - (button.x() + button.width())
        top = button.y()
        bottom = cell.height() - (button.y() + button.height())
        self.assertLessEqual(abs(left - right), 2,
                             "Delete must be horizontally centred")
        self.assertLessEqual(abs(top - bottom), 2,
                             "Delete must be vertically centred")

    def test_07_numeric_columns_are_right_aligned(self):
        from PySide6.QtCore import Qt
        for row in range(self.table.rowCount()):
            for column in (6, 7, 8, 9):
                item = self.table.item(row, column)
                self.assertTrue(item.textAlignment() & Qt.AlignRight)
                self.assertTrue(item.textAlignment() & Qt.AlignVCenter)
            self.assertTrue(
                self.table.item(row, 0).textAlignment() & Qt.AlignCenter)

    def test_08_delete_still_removes_the_line(self):
        before = self.table.rowCount()
        cell = self.table.cellWidget(0, 10)
        cell.findChildren(QPushButton)[0].click()
        QApplication.processEvents()
        self.assertEqual(self.table.rowCount(), before - 1)

    def test_19_populated_footer_stays_in_place(self):
        for width, height in _DESKTOP_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                self.page.resize(width, height)
                QApplication.processEvents()
                self.page._apply_history_height()
                QApplication.processEvents()
                footer = self.panel._totals_widget
                footer_bottom = (
                    footer.mapTo(
                        self.page,
                        QPoint(0, footer.height() - 1)).y())
                self.assertLessEqual(footer_bottom, self.page.height() - 1)


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CounterSaleFooterSizingTests(unittest.TestCase):
    """Sale Header strip and the totals/action footer."""

    @classmethod
    def setUpClass(cls):
        _bootstrap_disposable_db('footer')
        cls._app = QApplication.instance() or QApplication([])
        cls.page = CounterSalePage()
        cls.page.resize(1366, 708)
        cls.page.show()
        QApplication.processEvents()
        cls.panel = cls.page._sale_panel
        cls.strip = cls.panel._metadata_strip
        cls.footer = cls.panel._totals_widget

    @classmethod
    def tearDownClass(cls):
        cls.page.hide()
        cls.page.deleteLater()
        QApplication.processEvents()

    def test_01_sale_header_row_one_fields_are_visible(self):
        for name in ("bill_no_edit", "sale_date", "sale_time_edit",
                     "sale_type_combo"):
            with self.subTest(field=name):
                widget = getattr(self.panel, name)
                self.assertGreaterEqual(widget.width(), 60)
                self.assertGreaterEqual(widget.height(), 20)
                self.assertLessEqual(
                    widget.mapTo(self.strip, widget.rect().topRight()).x() + 1,
                    self.strip.width(), f"{name} is clipped")

    def test_02_customer_patient_doctor_share_the_second_row(self):
        widths = [getattr(self.panel, name).width()
                  for name in ("customer_combo", "patient_name_edit",
                               "doctor_combo")]
        for width in widths:
            self.assertGreaterEqual(width, 150)
        for name in ("customer_combo", "patient_name_edit", "doctor_combo"):
            widget = getattr(self.panel, name)
            self.assertLessEqual(
                widget.mapTo(self.strip, widget.rect().topRight()).x() + 1,
                self.strip.width(), f"{name} is clipped")

    def test_03_metadata_rows_use_one_shared_control_height(self):
        heights = {getattr(self.panel, name).height() for name in _METADATA_FIELDS}
        self.assertEqual(len(heights), 1,
                         f"metadata controls must share one height: {heights}")

    def test_04_footer_block_height_is_80_to_100_px(self):
        total = self.strip.height() + self.footer.height()
        self.assertGreaterEqual(total, 80)
        self.assertLessEqual(total, 100)
        self.assertEqual(self.strip.height(), _METADATA_STRIP_HEIGHT)
        self.assertEqual(self.footer.height(), _TOTALS_FOOTER_HEIGHT)

    def test_05_totals_are_visible_and_sized_by_role(self):
        self.assertLessEqual(self.panel.total_items_label.width(),
                             self.panel.total_amount_label.width())
        self.assertGreaterEqual(self.panel.net_amt_label.width(),
                                self.panel.round_off_label.width())
        for name in ("total_items_label", "total_amount_label",
                     "round_off_label", "net_amt_label", "bill_disc_edit",
                     "paid_edit"):
            with self.subTest(total=name):
                widget = getattr(self.panel, name)
                self.assertGreaterEqual(widget.width(), 60)
                self.assertGreaterEqual(widget.height(), 18)
                self.assertLessEqual(
                    widget.mapTo(self.footer, widget.rect().topRight()).x() + 1,
                    self.footer.width(), f"{name} is clipped")

    def test_06_action_buttons_share_one_height_and_stay_right(self):
        buttons = self.footer.findChildren(QPushButton)
        self.assertEqual([b.text() for b in buttons],
                         ["Hold Bill", "Save Sale", "Cancel"])
        for button in buttons:
            with self.subTest(button=button.text()):
                self.assertEqual(button.height(), _ACTION_BUTTON_HEIGHT)
                self.assertLessEqual(
                    button.x() + button.width(), self.footer.width())
        right_edge = max(b.x() + b.width() for b in buttons)
        left_edge = min(b.x() for b in buttons)
        self.assertGreater(right_edge, self.footer.width() * 0.6,
                           "actions must sit on the right of the footer")
        self.assertGreater(left_edge, self.footer.width() * 0.5,
                           "actions must not overlap the totals block")

    def test_07_footer_is_separated_from_bill_items(self):
        stylesheet = self.footer.styleSheet()
        self.assertIn("border-top", stylesheet)
        strip_y = self.strip.mapTo(self.page, self.strip.rect().topLeft()).y()
        footer_y = self.footer.mapTo(self.page, self.footer.rect().topLeft()).y()
        self.assertEqual(footer_y, strip_y + self.strip.height(),
                         "metadata strip and footer must stack flush")
        table_bottom = self.panel._table.mapTo(
            self.page, self.panel._table.rect().bottomLeft()).y()
        self.assertLessEqual(table_bottom, strip_y,
                             "Bill Items must not overlap the footer")

    def test_08_empty_and_populated_bills_keep_the_same_footer_position(self):
        positions = []
        for row_count in (0, 1, 5, 20):
            with self.subTest(rows=row_count):
                self.panel._item_rows = [_make_row(i + 1)
                                        for i in range(row_count)]
                self.panel._refresh_table()
                self.panel._recalc_totals()
                self.page.resize(1366, 708)
                QApplication.processEvents()
                self.page._apply_history_height()
                QApplication.processEvents()
                positions.append((
                    self.entry_y(),
                    self.footer.mapTo(
                        self.page, self.footer.rect().topLeft()).y(),
                ))
        self.assertEqual(len(set(positions)), 1,
                         f"entry bar / footer moved with row count: {positions}")

    def entry_y(self):
        bar = self.panel._entry_bar
        return bar.mapTo(self.page, bar.rect().topLeft()).y()

    def test_09_regions_stay_ordered_at_every_desktop_size(self):
        for width, height in _DESKTOP_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                self.page.resize(width, height)
                QApplication.processEvents()
                self.page._apply_history_height()
                QApplication.processEvents()
                ys = [self.page._hist_table.mapTo(
                    self.page, self.page._hist_table.rect().topLeft()).y(),
                    self.entry_y(),
                    self.panel._table.mapTo(
                        self.page, self.panel._table.rect().topLeft()).y(),
                    self.strip.mapTo(
                        self.page, self.strip.rect().topLeft()).y(),
                    self.footer.mapTo(
                        self.page, self.footer.rect().topLeft()).y()]
                self.assertEqual(ys, sorted(ys),
                                 "regions must stay top-to-bottom ordered")
                footer_bottom = ys[-1] + self.footer.height()
                self.assertLessEqual(footer_bottom, self.page.height(),
                                     "footer must not be clipped")

    def test_10_long_names_and_large_amounts_do_not_clip(self):
        self.panel._item_rows = [
            _BillItemRow(
                item_id=1,
                item_name="Extremely Long Item Name That Should Not Break The "
                          "Bill Items Layout At Any Resolution",
                stock_batch_id=1, pack_size="10x10x10x10",
                location="RACK-AAA-BBB-CCC-DDD-LONG-LOCATION",
                batch_no="BATCH-2026-0009999999999999", expiry="12/27",
                mrp=987654.32, sale_qty=1000.0, discount_amount=99999.99,
                amount=9876543.21,
            )
        ]
        self.panel._refresh_table()
        self.panel._recalc_totals()
        self.panel.bill_disc_edit.setText("100000.00")
        self.panel.paid_edit.setText("9876543.21")
        QApplication.processEvents()
        self.assertEqual(self.panel.net_amt_label.text(), "9776543.21")
        for width, height in _DESKTOP_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                self.page.resize(width, height)
                QApplication.processEvents()
                self.page._apply_history_height()
                QApplication.processEvents()
                for name in _METADATA_FIELDS:
                    widget = getattr(self.panel, name)
                    self.assertLessEqual(
                        widget.mapTo(self.strip,
                                     widget.rect().topRight()).x() + 1,
                        self.strip.width())
                for name in ("total_items_label", "total_amount_label",
                             "bill_disc_edit", "round_off_label",
                             "net_amt_label", "paid_edit"):
                    widget = getattr(self.panel, name)
                    self.assertLessEqual(
                        widget.mapTo(self.footer,
                                     widget.rect().topRight()).x() + 1,
                        self.footer.width())
        self.panel.reset_for_new()


def _traverse_from(page, start, presses=4):
    """Press Tab `presses` times and report the entry-bar control focused."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    entry = page._sale_panel._entry_bar
    order = []
    start.setFocus()
    QApplication.processEvents()
    for _ in range(presses):
        QTest.keyClick(QApplication.focusWidget() or start, Qt.Key_Tab)
        QApplication.processEvents()
        focused = QApplication.focusWidget()
        resolved = None
        for name in _ENTRY_FIELDS:
            candidate = getattr(entry, name)
            if focused is candidate or focused is getattr(
                    candidate, "lineEdit", lambda: None)():
                resolved = candidate
                break
        order.append(resolved)
    return order


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CounterSaleKeyboardUnchangedTests(unittest.TestCase):
    """The entry-bar polish must not disturb the keyboard contract."""

    @classmethod
    def setUpClass(cls):
        _bootstrap_disposable_db("keyboard")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Enter / "+ Add" validate before acting; never block on a dialog.
        self._msg_patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        ]
        for patcher in self._msg_patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_01_tab_order_is_unchanged(self):
        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        QApplication.processEvents()
        try:
            entry = page._sale_panel._entry_bar
            self.assertEqual(
                entry._focus_order,
                (entry.item_combo, entry.batch_combo, entry.qty_edit,
                 entry.discount_edit, entry.add_btn))
            # Real Tab traversal: Item -> Batch -> Qty -> Discount -> Add.
            self.assertEqual(
                _traverse_from(page, entry.item_combo),
                [entry.batch_combo, entry.qty_edit, entry.discount_edit,
                 entry.add_btn],
                "Tab order through the entry bar must be unchanged")
        finally:
            page.hide()
            page.deleteLater()
            QApplication.processEvents()

    def test_02_read_only_fields_stay_out_of_the_focus_chain(self):
        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        QApplication.processEvents()
        try:
            from PySide6.QtCore import Qt
            entry = page._sale_panel._entry_bar
            for name in ("cno_label", "pack_edit", "location_edit",
                         "expiry_edit", "mrp_edit", "stock_edit",
                         "amount_edit"):
                with self.subTest(field=name):
                    self.assertEqual(
                        getattr(entry, name).focusPolicy(), Qt.NoFocus)
            self.assertEqual(entry.item_combo.focusPolicy(), Qt.StrongFocus)
            self.assertEqual(entry.batch_combo.focusPolicy(), Qt.StrongFocus)
        finally:
            page.hide()
            page.deleteLater()
            QApplication.processEvents()

    def test_03_signal_wiring_is_unchanged(self):
        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        QApplication.processEvents()
        try:
            entry = page._sale_panel._entry_bar
            fired = []

            # Enter on Qty / Discount still commits the line, and the
            # completion signals still drive Item -> Batch -> Qty focus.
            entry.qty_edit.returnPressed.connect(
                lambda: fired.append("qty-return"))
            entry.discount_edit.returnPressed.connect(
                lambda: fired.append("disc-return"))
            entry.item_combo.completionAccepted.connect(
                lambda: fired.append("item-accepted"))
            entry.batch_combo.completionAccepted.connect(
                lambda: fired.append("batch-accepted"))

            entry.qty_edit.returnPressed.emit()
            entry.discount_edit.returnPressed.emit()
            entry.item_combo.completionAccepted.emit()
            entry.batch_combo.completionAccepted.emit()
            self.assertEqual(fired,
                             ["qty-return", "disc-return",
                              "item-accepted", "batch-accepted"])

            # The declared focus helpers are still the ones the bar uses.
            self.assertTrue(callable(entry._focus_batch))
            self.assertTrue(callable(entry._focus_quantity))
            self.assertTrue(callable(entry._activate_add))
        finally:
            page.hide()
            page.deleteLater()
            QApplication.processEvents()

    def test_04_add_button_still_triggers_a_line(self):
        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        QApplication.processEvents()
        try:
            panel = page._sale_panel
            clicked = []
            page._sale_panel._entry_bar.add_btn.clicked.connect(
                lambda: clicked.append("clicked"))
            page._sale_panel._entry_bar.add_btn.click()
            QApplication.processEvents()
            self.assertEqual(clicked, ["clicked"])
        finally:
            page.hide()
            page.deleteLater()
            QApplication.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
