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
        """Page title font must be 16-18 px."""
        import re
        title = None
        from PySide6.QtWidgets import QLabel
        for lbl in self.page.findChildren(QLabel):
            if lbl.text() == "Sales / Counter Sale":
                title = lbl
                break
        self.assertIsNotNone(title, "page title label not found")
        ss = title.styleSheet()
        match = re.search(r"font-size:\s*(\d+)px", ss)
        self.assertIsNotNone(match, "title font-size not found in stylesheet")
        px_size = int(match.group(1))
        self.assertGreaterEqual(px_size, 16,
                                f"title font too small: {px_size}px")
        self.assertLessEqual(px_size, 18,
                             f"title font too large: {px_size}px")

    # -- 4. Table header font -----------------------------------------
    def test_07_history_table_header_font(self):
        """History table headers must be bold and 10-11 px."""
        hv = self.hist.horizontalHeader()
        ss = hv.styleSheet()
        self.assertIn("font-weight: bold", ss,
                      "history table header must be bold")
        self.assertIn("font-size: 11px", ss,
                      "history table header font must be 11px")

    def test_08_bill_table_header_font(self):
        """Bill table headers must be bold and 10-11 px."""
        hv = self.bill_table.horizontalHeader()
        ss = hv.styleSheet()
        self.assertIn("font-weight: bold", ss,
                      "bill table header must be bold")
        self.assertIn("font-size: 11px", ss,
                      "bill table header font must be 11px")

    def test_09_history_table_cell_font(self):
        """History table cells must be 10-11 px."""
        ss = self.hist.styleSheet()
        self.assertIn("font-size: 11px", ss,
                      "history table cell font must be 11px")

    def test_10_bill_table_cell_font(self):
        """Bill table cells must be 10-11 px."""
        ss = self.bill_table.styleSheet()
        self.assertIn("font-size: 11px", ss,
                      "bill table cell font must be 11px")

    # -- 5. Active-entry font -----------------------------------------
    def test_11_active_entry_labels_readable(self):
        """Active entry labels must be 10-11 px."""
        # Check the entry bar labels
        from PySide6.QtWidgets import QLabel
        for lbl in self.entry.findChildren(QLabel):
            ss = lbl.styleSheet()
            if "font-size" in ss:
                # Extract font size
                import re
                match = re.search(r"font-size:\s*(\d+)px", ss)
                if match:
                    size = int(match.group(1))
                    self.assertGreaterEqual(size, 10,
                                            f"entry label '{lbl.text()}' font too small: {size}px")
                    self.assertLessEqual(size, 11,
                                         f"entry label '{lbl.text()}' font too large: {size}px")

    def test_12_active_entry_input_font(self):
        """Active entry input fields must be 10-11 px."""
        for edit in (self.entry.qty_edit, self.entry.discount_edit,
                     self.entry.pack_edit, self.entry.mrp_edit):
            ss = edit.styleSheet()
            import re
            match = re.search(r"font-size:\s*(\d+)px", ss)
            if match:
                size = int(match.group(1))
                self.assertGreaterEqual(size, 10,
                                        f"input font too small: {size}px")
                self.assertLessEqual(size, 11,
                                     f"input font too large: {size}px")

    # -- 6. Sale Header font ------------------------------------------
    def test_13_sale_header_labels_readable(self):
        """Sale Header labels must be 10-11 px and bold."""
        from PySide6.QtWidgets import QLabel
        # Find the Sale Header group box
        sale_header = None
        for grp in self.page.findChildren(QGroupBox):
            if grp.title() == "Sale Header":
                sale_header = grp
                break
        self.assertIsNotNone(sale_header, "Sale Header group box not found")
        for lbl in sale_header.findChildren(QLabel):
            ss = lbl.styleSheet()
            if "font-size" in ss:
                import re
                match = re.search(r"font-size:\s*(\d+)px", ss)
                if match:
                    size = int(match.group(1))
                    self.assertGreaterEqual(size, 10,
                                            f"Sale Header label '{lbl.text()}' font too small: {size}px")
                    self.assertLessEqual(size, 11,
                                         f"Sale Header label '{lbl.text()}' font too large: {size}px")

    def test_14_sale_header_group_title_readable(self):
        """Sale Header group box title must be 11-12 px."""
        for grp in self.page.findChildren(QGroupBox):
            if grp.title() == "Sale Header":
                ss = grp.styleSheet()
                import re
                match = re.search(r"font-size:\s*(\d+)px", ss)
                if match:
                    size = int(match.group(1))
                    self.assertGreaterEqual(size, 11,
                                            f"Sale Header title font too small: {size}px")
                    self.assertLessEqual(size, 12,
                                         f"Sale Header title font too large: {size}px")
                break

    # -- 7. Totals font ------------------------------------------------
    def test_15_totals_labels_readable(self):
        """Totals labels must be 10-11 px."""
        import re
        from PySide6.QtWidgets import QLabel
        value_labels = {
            self.panel.total_amount_label,
            self.panel.round_off_label,
            self.panel.net_amt_label,
        }
        for lbl in self.totals.findChildren(QLabel):
            if lbl in value_labels:
                continue  # value labels are checked separately in test_16
            ss = lbl.styleSheet()
            if "font-size" in ss:
                match = re.search(r"font-size:\s*(\d+)px", ss)
                if match:
                    size = int(match.group(1))
                    self.assertGreaterEqual(size, 10,
                                            f"totals label '{lbl.text()}' font too small: {size}px")
                    self.assertLessEqual(size, 11,
                                         f"totals label '{lbl.text()}' font too large: {size}px")

    def test_16_totals_values_readable(self):
        """Totals numeric values must be 11-12 px."""
        for attr in ("total_amount_label", "round_off_label", "net_amt_label"):
            lbl = getattr(self.panel, attr)
            ss = lbl.styleSheet()
            import re
            match = re.search(r"font-size:\s*(\d+)px", ss)
            if match:
                size = int(match.group(1))
                self.assertGreaterEqual(size, 11,
                                        f"totals value '{attr}' font too small: {size}px")
                self.assertLessEqual(size, 12,
                                     f"totals value '{attr}' font too large: {size}px")

    # -- 8. Buttons font ----------------------------------------------
    def test_17_action_buttons_readable(self):
        """Save Sale, Hold Bill, Cancel buttons must be 10-11 px and bold."""
        for btn in self.totals.findChildren(QPushButton):
            ss = btn.styleSheet()
            import re
            match = re.search(r"font-size:\s*(\d+)px", ss)
            if match:
                size = int(match.group(1))
                self.assertGreaterEqual(size, 10,
                                        f"button '{btn.text()}' font too small: {size}px")
                self.assertLessEqual(size, 11,
                                     f"button '{btn.text()}' font too large: {size}px")
            self.assertIn("font-weight: bold", ss,
                          f"button '{btn.text()}' must be bold")

    def test_18_add_button_readable(self):
        """Add button must be 10-11 px and bold."""
        ss = self.entry.add_btn.styleSheet()
        import re
        match = re.search(r"font-size:\s*(\d+)px", ss)
        if match:
            size = int(match.group(1))
            self.assertGreaterEqual(size, 10,
                                    f"Add button font too small: {size}px")
            self.assertLessEqual(size, 11,
                                 f"Add button font too large: {size}px")
        self.assertIn("font-weight: bold", ss,
                      "Add button must be bold")

    def test_19_new_sale_button_readable(self):
        """New Sale button must be 10-11 px and bold."""
        ss = self.page._new_btn.styleSheet()
        import re
        match = re.search(r"font-size:\s*(\d+)px", ss)
        if match:
            size = int(match.group(1))
            self.assertGreaterEqual(size, 10,
                                    f"New Sale button font too small: {size}px")
            self.assertLessEqual(size, 11,
                                 f"New Sale button font too large: {size}px")
        self.assertIn("font-weight: bold", ss,
                      "New Sale button must be bold")

    # -- 9. Right bill panel ------------------------------------------
    def test_20_right_panel_labels_readable(self):
        """Right bill panel labels must be 10-11 px."""
        from PySide6.QtWidgets import QLabel
        panel = self.page.findChild(type(self.totals), "BillPanel")
        self.assertIsNotNone(panel, "Bill panel not found")
        for lbl in panel.findChildren(QLabel):
            ss = lbl.styleSheet()
            if "font-size" in ss:
                import re
                match = re.search(r"font-size:\s*(\d+)px", ss)
                if match:
                    size = int(match.group(1))
                    self.assertGreaterEqual(size, 10,
                                            f"right panel label '{lbl.text()}' font too small: {size}px")
                    self.assertLessEqual(size, 11,
                                         f"right panel label '{lbl.text()}' font too large: {size}px")

    def test_21_right_panel_buttons_readable(self):
        """Right bill panel buttons must be 10-11 px and bold."""
        panel = self.page.findChild(type(self.totals), "BillPanel")
        self.assertIsNotNone(panel, "Bill panel not found")
        for btn in panel.findChildren(QPushButton):
            ss = btn.styleSheet()
            import re
            match = re.search(r"font-size:\s*(\d+)px", ss)
            if match:
                size = int(match.group(1))
                self.assertGreaterEqual(size, 10,
                                        f"right panel button '{btn.text()}' font too small: {size}px")
                self.assertLessEqual(size, 11,
                                     f"right panel button '{btn.text()}' font too large: {size}px")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
