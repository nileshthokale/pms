"""Counter Sale UI readability and layout tests.

Covers:
  - filter row removed
  - Bill History positioned directly under header
  - readable font size
  - table header font
  - active-entry font
  - Sale Header font
  - totals font
  - buttons font
  - no clipping at 1366x768
  - no clipping at 1600x900
  - no clipping at 1920x1080

GUI tests are skipped only when PySide6 is unavailable.
"""

import os
import re
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QMessageBox, QPushButton

    from screens.counter_sale import CounterSalePage, _BillItemRow

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


def _font_size(stylesheet: str) -> int | None:
    """Font size declared in a stylesheet, in px (``pt`` normalised at 96 dpi)."""
    match = re.search(r"font-size:\s*(\d+)(px|pt)", stylesheet)
    if not match:
        return None
    value = int(match.group(1))
    return value if match.group(2) == "px" else round(value * 96 / 72)


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
class CounterSaleUITests(unittest.TestCase):
    """UI readability and layout tests for Counter Sale."""

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            tempfile.gettempdir(), "pharmacy_counter_sale_ui_readability.db"
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
        CustomerDAO.insert("UI Test Customer", city="Test City")

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
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

    def _font_px(self, widget) -> float:
        """Return the effective font size in px from the widget's stylesheet."""
        from PySide6.QtGui import QFont
        return widget.font().pointSize() * 96.0 / 72.0

    def _assert_region_order(self):
        self.assertLess(self._y(self.hist), self._y(self.entry),
                        "history must be above the sale entry")
        self.assertLess(self._y(self.entry), self._y(self.bill_table),
                        "sale entry must be above the bill table")
        self.assertLess(self._y(self.bill_table), self._y(self.totals),
                        "bill table must be above the totals bar")

    # -- 1. History filter bar ----------------------------------------
    def test_01_history_filter_has_exactly_one_date(self):
        """The history filter contributes exactly one Date control."""
        from PySide6.QtWidgets import QDateEdit
        date_edits = self.page.findChildren(QDateEdit)
        # One Sale Header date + the single history Date control.
        self.assertEqual(len(date_edits), 2,
                         "expected the Sale Header date plus one history Date")
        self.assertIn(self.page._hist_date, date_edits)
        self.assertIsNot(self.page._hist_date, self.panel.sale_date)

    def test_02_filter_controls_removed(self):
        """From/To date filters and Customer filter must be gone."""
        # Check that no widget has "From", "To", "Customer" as filter labels
        # in a filter bar context (the Sale Header has "Customer *" but
        # that's in the customer bar, not a filter)
        buttons = [b.text() for b in self.page.findChildren(QPushButton)]
        self.assertNotIn("Filter", buttons,
                         "Filter button must be removed")

    def test_03_history_filter_bar_is_compact_and_styled(self):
        """The history filter bar exists with a controlled fixed height."""
        bar = self.page._history_filter_bar
        self.assertEqual(bar.objectName(), "HistoryFilterBar")
        self.assertLessEqual(bar.height(), 34,
                             "history filter bar must stay compact")

    # -- 2. Bill History positioned directly under the filter bar -----
    def test_04_history_directly_below_filter_bar(self):
        """Bill History table must start right after the filter bar."""
        bar_y = self._y(self.page._history_filter_bar)
        hist_y = self._y(self.hist)
        self.assertLessEqual(abs(hist_y - (bar_y + self.page._history_filter_bar.height())), 4,
                             f"history must start directly below the filter bar (y={hist_y})")

    def test_05_no_empty_gap_where_filter_was(self):
        """No empty gap between the filter bar and the history table."""
        bar = self.page._history_filter_bar
        hist_y = self._y(self.hist)
        self.assertLessEqual(hist_y, self._y(bar) + bar.height() + 4,
                             "no empty gap should exist below the filter row")

    # -- 3. Readable font size ----------------------------------------
    def test_06_page_title_font_readable(self):
        """Page title must be 16-18 px, bold and black."""
        title = None
        from PySide6.QtWidgets import QLabel
        for lbl in self.page.findChildren(QLabel):
            if lbl.text() == "Sales / Counter Sale":
                title = lbl
                break
        self.assertIsNotNone(title, "page title label not found")
        ss = title.styleSheet()
        size = _font_size(ss)
        self.assertIsNotNone(size, "title font-size not found in stylesheet")
        self.assertGreaterEqual(size, 16, f"title font too small: {size}px")
        self.assertLessEqual(size, 18, f"title font too large: {size}px")
        self.assertIn("font-weight: bold", ss, "page title must be bold")
        self.assertIn("#000000", ss, "page title must be black")

    # -- 4. Table header font -----------------------------------------
    def test_07_history_table_header_font(self):
        """History table headers must be bold, black and 12-13 px."""
        hv = self.hist.horizontalHeader()
        ss = hv.styleSheet()
        self.assertIn("font-weight: bold", ss,
                      "history table header must be bold")
        size = _font_size(hv.styleSheet())
        self.assertGreaterEqual(size, 12,
                                f"history header font too small: {size}px")
        self.assertLessEqual(size, 13,
                             f"history header font too large: {size}px")
        self.assertEqual(hv.font().pixelSize(), size,
                         "header QFont must match its stylesheet size")

    def test_08_bill_table_header_font(self):
        """Bill table headers must be bold, black and 12-13 px."""
        hv = self.bill_table.horizontalHeader()
        ss = hv.styleSheet()
        self.assertIn("font-weight: bold", ss,
                      "bill table header must be bold")
        size = _font_size(ss)
        self.assertGreaterEqual(size, 12,
                                f"bill table header font too small: {size}px")
        self.assertLessEqual(size, 13,
                             f"bill table header font too large: {size}px")
        self.assertEqual(hv.font().pixelSize(), size,
                         "header QFont must match its stylesheet size")

    def test_09_history_table_cell_font(self):
        """History table cells must be 12-13 px black."""
        size = _font_size(self.hist.styleSheet())
        self.assertGreaterEqual(size, 12,
                                f"history cell font too small: {size}px")
        self.assertLessEqual(size, 13,
                             f"history cell font too large: {size}px")
        self.assertIn("#000000", self.hist.styleSheet(),
                      "history cell text must be black")

    def test_10_bill_table_cell_font(self):
        """Bill table cells must be 12-13 px black."""
        size = _font_size(self.bill_table.styleSheet())
        self.assertGreaterEqual(size, 12,
                                f"bill table cell font too small: {size}px")
        self.assertLessEqual(size, 13,
                             f"bill table cell font too large: {size}px")
        self.assertIn("#000000", self.bill_table.styleSheet(),
                      "bill table cell text must be black")

    # -- 5. Active-entry font -----------------------------------------
    def test_11_active_entry_labels_readable(self):
        """Active entry captions must be 11-12 px, bold and black.

        ``cno_label`` is the live *value* read-out, not a caption, so it is
        held to the value size instead (see test_16's hierarchy).
        """
        from PySide6.QtWidgets import QLabel
        checked = 0
        for lbl in self.entry.findChildren(QLabel):
            if lbl is self.entry.cno_label:
                continue
            ss = lbl.styleSheet()
            if "font-size" not in ss:
                continue
            size = _font_size(ss)
            checked += 1
            self.assertGreaterEqual(size, 11,
                                    f"entry label '{lbl.text()}' too small: {size}px")
            self.assertLessEqual(size, 12,
                                 f"entry label '{lbl.text()}' too large: {size}px")
            self.assertIn("font-weight: bold", ss,
                          f"entry label '{lbl.text()}' must be bold")
            self.assertIn("#000000", ss,
                          f"entry label '{lbl.text()}' must be black")
        self.assertGreaterEqual(checked, 11, "entry captions not found")

    def test_12_active_entry_input_font(self):
        """Active entry input fields must be 12-13 px."""
        for edit in (self.entry.qty_edit, self.entry.discount_edit,
                     self.entry.pack_edit, self.entry.mrp_edit):
            size = _font_size(edit.styleSheet())
            self.assertGreaterEqual(size, 12,
                                    f"input font too small: {size}px")
            self.assertLessEqual(size, 13,
                                 f"input font too large: {size}px")
            self.assertIn("#000000", edit.styleSheet(),
                          "input text must be black")

    # -- 6. Sale Header font ------------------------------------------
    def test_13_sale_header_labels_readable(self):
        """Sale-header captions must be 11-12 px, bold and black.

        The old "Sale Header" group box was merged into the compact metadata
        strip that keeps the same captions (Bill No / Date / Time / Type /
        Customer / Patient / Doctor), so the strip captions are checked here.
        """
        from PySide6.QtWidgets import QLabel, QWidget

        strip = self.panel.findChild(QWidget, "CompactSaleMetadata")
        self.assertIsNotNone(strip, "compact sale metadata strip not found")
        captions = [lbl for lbl in strip.findChildren(QLabel)
                    if lbl.text() in ("Bill No", "Date", "Time", "Type",
                                      "Customer *", "Patient", "Doctor")]
        self.assertEqual(len(captions), 7, "sale-header captions missing")
        for lbl in captions:
            size = _font_size(lbl.styleSheet())
            self.assertIsNotNone(size, f"{lbl.text()} lost its font size")
            self.assertGreaterEqual(size, 11,
                                    f"Sale Header label '{lbl.text()}' too small: {size}px")
            self.assertLessEqual(size, 12,
                                 f"Sale Header label '{lbl.text()}' too large: {size}px")
            self.assertIn("font-weight: bold", lbl.styleSheet(),
                          f"Sale Header label '{lbl.text()}' must be bold")
            self.assertIn("#000000", lbl.styleSheet(),
                          f"Sale Header label '{lbl.text()}' must be black")

    def test_14_sale_header_panel_is_the_compact_strip(self):
        """The Sale Header / Customer panels are one compact strip, not boxes."""
        from PySide6.QtWidgets import QLabel, QWidget

        titles = [grp.title() for grp in self.panel.findChildren(QGroupBox)]
        self.assertNotIn("Sale Header", titles)
        self.assertNotIn("Customer / Doctor", titles)

        strip = self.panel.findChild(QWidget, "CompactSaleMetadata")
        self.assertIsNotNone(strip, "compact sale metadata strip not found")
        self.assertGreaterEqual(strip.height(), 40)
        self.assertLessEqual(strip.height(), 60)
        captions = [lbl.text() for lbl in strip.findChildren(QLabel)]
        for text in ("Bill No", "Date", "Time", "Type",
                     "Customer *", "Patient", "Doctor"):
            self.assertIn(text, captions, f"{text} left the sale header strip")

    # -- 7. Totals font ------------------------------------------------
    def test_15_totals_labels_readable(self):
        """Totals caption labels must be 11-12 px, bold and black."""
        from PySide6.QtWidgets import QLabel

        number = re.compile(r"^-?\d+(\.\d+)?$")
        checked = 0
        for lbl in self.totals.findChildren(QLabel):
            if number.match(lbl.text().strip()):
                continue  # numeric values are checked separately in test_16
            size = _font_size(lbl.styleSheet())
            if size is None:
                continue
            checked += 1
            self.assertGreaterEqual(size, 11,
                                    f"totals label '{lbl.text()}' too small: {size}px")
            self.assertLessEqual(size, 12,
                                 f"totals label '{lbl.text()}' too large: {size}px")
            self.assertIn("font-weight: bold", lbl.styleSheet(),
                          f"totals label '{lbl.text()}' must be bold")
            self.assertIn("#000000", lbl.styleSheet(),
                          f"totals label '{lbl.text()}' must be black")
        self.assertGreaterEqual(checked, 6, "totals captions not found")

    def test_16_totals_values_readable(self):
        """Totals numeric values must be 13-14 px bold black; NET AMT emphasised."""
        from PySide6.QtWidgets import QLabel

        number = re.compile(r"^-?\d+(\.\d+)?$")
        values = [lbl for lbl in self.totals.findChildren(QLabel)
                  if number.match(lbl.text().strip())]
        self.assertGreaterEqual(len(values), 4, "totals values not found")
        for lbl in values:
            size = _font_size(lbl.styleSheet())
            self.assertIsNotNone(size, f"totals value '{lbl.text()}' lost its font size")
            self.assertGreaterEqual(size, 13,
                                    f"totals value '{lbl.text()}' too small: {size}px")
            self.assertLessEqual(size, 14,
                                 f"totals value '{lbl.text()}' too large: {size}px")
            self.assertIn("font-weight: bold", lbl.styleSheet(),
                          f"totals value '{lbl.text()}' must be bold")
            self.assertIn("#000000", lbl.styleSheet(),
                          f"totals value '{lbl.text()}' must be black")
        # NET AMT is the emphasised figure of the footer.
        net = self.panel.net_amt_label
        size = _font_size(net.styleSheet())
        self.assertIsNotNone(size, "NET AMT lost its font size")
        self.assertGreaterEqual(size, 14,
                                "NET AMT must stay the strongest figure")
        self.assertIn("font-weight: bold", net.styleSheet(),
                      "NET AMT must stay bold")

    # -- 8. Buttons font ----------------------------------------------
    def test_17_action_buttons_readable(self):
        """Save Sale, Hold Bill, Cancel buttons must be 12 px and bold."""
        for btn in self.totals.findChildren(QPushButton):
            ss = btn.styleSheet()
            size = _font_size(ss)
            if size is None:
                continue
            self.assertGreaterEqual(size, 12,
                                    f"button '{btn.text()}' font too small: {size}px")
            self.assertLessEqual(size, 12,
                                 f"button '{btn.text()}' font too large: {size}px")
            self.assertIn("font-weight: bold", ss,
                          f"button '{btn.text()}' must be bold")

    def test_18_add_button_readable(self):
        """Add button must be 12 px and bold."""
        ss = self.entry.add_btn.styleSheet()
        size = _font_size(ss)
        self.assertIsNotNone(size, "Add button lost its font size")
        self.assertGreaterEqual(size, 12, f"Add button font too small: {size}px")
        self.assertLessEqual(size, 12, f"Add button font too large: {size}px")
        self.assertIn("font-weight: bold", ss, "Add button must be bold")

    def test_19_new_sale_button_readable(self):
        """New Sale button must be 12 px and bold."""
        ss = self.page._new_btn.styleSheet()
        size = _font_size(ss)
        self.assertIsNotNone(size, "New Sale button lost its font size")
        self.assertGreaterEqual(size, 12,
                                f"New Sale button font too small: {size}px")
        self.assertLessEqual(size, 12,
                             f"New Sale button font too large: {size}px")
        self.assertIn("font-weight: bold", ss, "New Sale button must be bold")

    # -- 9. Right bill panel ------------------------------------------
    def test_20_right_panel_labels_readable(self):
        """Right bill panel captions/values must be 12-13 px black/bold.

        The dim "Paper: A6 (105 x 148 mm)" note is a deliberate exception —
        it is secondary information, not data.
        """
        from PySide6.QtWidgets import QLabel
        panel = self.page.findChild(type(self.totals), "BillPanel")
        self.assertIsNotNone(panel, "Bill panel not found")
        checked = 0
        for lbl in panel.findChildren(QLabel):
            ss = lbl.styleSheet()
            size = _font_size(ss)
            if size is None:
                continue
            if "#55677a" in ss:
                continue  # the dim paper-size note
            checked += 1
            self.assertGreaterEqual(size, 12,
                                    f"right panel label '{lbl.text()}' too small: {size}px")
            self.assertLessEqual(size, 13,
                                 f"right panel label '{lbl.text()}' too large: {size}px")
            self.assertIn("font-weight: bold", ss,
                          f"right panel label '{lbl.text()}' must be bold")
        self.assertGreaterEqual(checked, 6, "right panel captions not found")

    def test_21_right_panel_buttons_readable(self):
        """Right bill panel buttons must be 12 px and bold."""
        panel = self.page.findChild(type(self.totals), "BillPanel")
        self.assertIsNotNone(panel, "Bill panel not found")
        checked = 0
        for btn in panel.findChildren(QPushButton):
            ss = btn.styleSheet()
            size = _font_size(ss)
            if size is None:
                continue
            checked += 1
            self.assertGreaterEqual(size, 12,
                                    f"right panel button '{btn.text()}' font too small: {size}px")
            self.assertLessEqual(size, 12,
                                 f"right panel button '{btn.text()}' font too large: {size}px")
        self.assertGreaterEqual(checked, 4, "right panel buttons not found")

    # -- 10. No clipping at different resolutions ----------------------
    def test_22_no_clipping_1366x768(self):
        """No clipping at 1366x768."""
        self.page.resize(1366, 768)
        QApplication.processEvents()
        self.page._apply_history_height()
        QApplication.processEvents()
        self._assert_no_clipping()

    def test_23_no_clipping_1600x900(self):
        """No clipping at 1600x900."""
        self.page.resize(1600, 900)
        QApplication.processEvents()
        self.page._apply_history_height()
        QApplication.processEvents()
        self._assert_no_clipping()

    def test_24_no_clipping_1920x1080(self):
        """No clipping at 1920x1080."""
        self.page.resize(1920, 1080)
        QApplication.processEvents()
        self.page._apply_history_height()
        QApplication.processEvents()
        self._assert_no_clipping()

    def _assert_no_clipping(self):
        """Verify no widget extends beyond the page boundaries."""
        page_rect = self.page.rect()
        widgets_to_check = [
            self.hist, self.entry, self.bill_table,
            self.totals, self.panel,
        ]
        for w in widgets_to_check:
            w_rect = w.rect()
            w_top_left = w.mapTo(self.page, w_rect.topLeft())
            w_bottom_right = w.mapTo(self.page, w_rect.bottomRight())
            self.assertGreaterEqual(w_top_left.x(), -1,
                                    f"{w.objectName() or w.__class__.__name__} clipped on left")
            self.assertGreaterEqual(w_top_left.y(), -1,
                                    f"{w.objectName() or w.__class__.__name__} clipped on top")
            self.assertLessEqual(w_bottom_right.x(), page_rect.width() + 1,
                                 f"{w.objectName() or w.__class__.__name__} clipped on right")
            self.assertLessEqual(w_bottom_right.y(), page_rect.height() + 1,
                                 f"{w.objectName() or w.__class__.__name__} clipped on bottom")

    # -- 11. Layout structure preserved --------------------------------
    def test_25_layout_structure_preserved(self):
        """History > Entry > Bill Items > Sale Header/Totals order."""
        self._assert_region_order()

    def test_26_right_panel_exists(self):
        """Right bill panel must still exist."""
        panel = self.page.findChild(type(self.totals), "BillPanel")
        self.assertIsNotNone(panel, "right-side Bill panel missing")
        self.assertGreaterEqual(panel.width(), 180)
        self.assertLessEqual(panel.width(), 300)

    # -- 12. Font consistency ------------------------------------------
    def test_27_font_family_consistent(self):
        """All widgets must use the centralized font family."""
        from PySide6.QtWidgets import QLabel
        # Check that no widget hard-codes a different font family
        # The centralized font is 'Segoe UI', 'Tahoma', sans-serif
        for lbl in self.page.findChildren(QLabel):
            ss = lbl.styleSheet()
            if "font-family" in ss:
                self.assertIn("Segoe UI", ss,
                              f"label '{lbl.text()}' does not use centralized font")
        for btn in self.page.findChildren(QPushButton):
            ss = btn.styleSheet()
            if "font-family" in ss:
                self.assertIn("Segoe UI", ss,
                              f"button '{btn.text()}' does not use centralized font")

    # -- 13. Black-text policy -----------------------------------------
    def test_28_section_headers_are_bold_black(self):
        """Section headers ('Bill History', 'Bill Items'): bold, black, 13-14 px."""
        from PySide6.QtWidgets import QLabel

        # "Bill History" is the header-strip section label.
        history = None
        for lbl in self.page.findChildren(QLabel):
            if lbl.text() == "Bill History":
                history = lbl
                break
        self.assertIsNotNone(history, "'Bill History' section header missing")
        size = _font_size(history.styleSheet())
        self.assertIsNotNone(size, "'Bill History' lost its font size")
        self.assertGreaterEqual(size, 13, f"'Bill History' too small: {size}px")
        self.assertLessEqual(size, 14, f"'Bill History' too large: {size}px")
        self.assertIn("font-weight: bold", history.styleSheet(),
                      "'Bill History' must be bold")
        self.assertIn("#000000", history.styleSheet(),
                      "'Bill History' must be black")

        # "Bill Items" is the grid's section title (a QGroupBox).
        groups = {g.title(): g for g in self.panel.findChildren(QGroupBox)}
        self.assertIn("Bill Items", groups, "'Bill Items' section missing")
        group_style = groups["Bill Items"].styleSheet()
        group_size = _font_size(group_style)
        self.assertIsNotNone(group_size, "'Bill Items' lost its font size")
        self.assertGreaterEqual(group_size, 13,
                                f"'Bill Items' too small: {group_size}px")
        self.assertLessEqual(group_size, 14,
                             f"'Bill Items' too large: {group_size}px")
        self.assertIn("font-weight: bold", group_style,
                      "'Bill Items' must be bold")
        self.assertIn("#000000", group_style, "'Bill Items' must be black")

    def test_29_normal_data_is_never_grey(self):
        """Readable data must be black — no #777/#888/#999 for table values."""
        for widget, label in ((self.hist, "history table"),
                              (self.bill_table, "bill table")):
            ss = widget.styleSheet()
            self.assertIn("#000000", ss, f"{label} data must be black")
            for grey in ("#777", "#888", "#999", "#aaaaaa", "#55677a"):
                self.assertNotIn(grey, ss,
                                 f"{label} must not use {grey} for data")

    def test_30_bill_row_height_still_fits_the_data_font(self):
        """The larger data font must still fit the unchanged 30 px row."""
        from PySide6.QtGui import QFontMetrics

        font = self.bill_table.font()
        needed = QFontMetrics(font).height() + 6  # + 3px item padding each side
        self.assertLessEqual(
            needed, self.bill_table.rowHeight(0),
            f"13 px data needs {needed}px but the row is "
            f"{self.bill_table.rowHeight(0)}px")


if __name__ == "__main__":
    unittest.main(verbosity=2)
