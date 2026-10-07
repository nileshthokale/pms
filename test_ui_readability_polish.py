"""UI readability polish tests (global styling + maximized startup).

Covers the readability pass without touching business logic:
  - shared control metrics are at readable sizes
  - default label/section/table-header/button styles are readable
  - the main application window starts maximized
  - Counter Sale keeps its readability pins after the polish
    (entry bar breathing room, 30 px bill rows, taller header band)

GUI tests are skipped only when PySide6 is unavailable.
"""

import os
import re
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtWidgets import QApplication

    from ui import components as ui_components

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


def _pt_size(stylesheet: str) -> int | None:
    match = re.search(r"font-size:\s*(\d+)pt", stylesheet)
    return int(match.group(1)) if match else None


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class SharedReadabilityMetricsTests(unittest.TestCase):
    """Global metrics must stay at readable (not cramped) sizes."""

    def test_01_row_height_is_readable(self):
        self.assertGreaterEqual(ui_components.ROW_HEIGHT, 26,
                                "data rows must breathe")

    def test_02_control_height_is_readable(self):
        self.assertGreaterEqual(ui_components.CONTROL_HEIGHT, 28,
                                "entry controls must breathe")

    def test_03_header_height_is_readable(self):
        self.assertGreaterEqual(ui_components.HEADER_HEIGHT, 28,
                                "table headers must breathe")

    def test_04_default_label_size_is_readable(self):
        size = _pt_size(ui_components.label_style())
        self.assertIsNotNone(size, "default label lost its font size")
        self.assertGreaterEqual(size, 10)

    def test_05_section_titles_are_bold_and_readable(self):
        style = ui_components.section_title_style()
        self.assertIn("font-weight: bold", style)
        size = _pt_size(style)
        self.assertIsNotNone(size)
        self.assertGreaterEqual(size, 11)

    def test_06_table_headers_are_bold_and_readable(self):
        style = ui_components.table_header_style()
        self.assertIn("font-weight: bold", style)
        size = _pt_size(style)
        self.assertIsNotNone(size)
        self.assertGreaterEqual(size, 10)

    def test_07_inputs_are_readable(self):
        for style in (ui_components.edit_style(), ui_components.combo_style(),
                      ui_components.date_style(), ui_components.spin_style()):
            size = _pt_size(style)
            self.assertIsNotNone(size, "input lost its font size")
            self.assertGreaterEqual(size, 10)

    def test_08_buttons_have_breathing_room(self):
        style = ui_components.btn_primary_style()
        match = re.search(r"min-height:\s*(\d+)px", style)
        self.assertIsNotNone(match, "buttons lost their minimum height")
        self.assertGreaterEqual(int(match.group(1)), 22)


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class MaximizedStartupTests(unittest.TestCase):
    """The main window must open maximized on a Windows desktop."""

    @classmethod
    def setUpClass(cls):
        db_path = os.path.join(tempfile.gettempdir(),
                               "pharmacy_ui_polish_startup.db")
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

        cls._app = QApplication.instance() or QApplication([])

    def test_01_main_entry_starts_maximized(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "main.py"), "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("showMaximized", source,
                      "main window must start maximized (showMaximized)")

    def test_02_main_window_supports_maximized(self):
        from ui import PharmacyMainWindow

        window = PharmacyMainWindow()
        try:
            window.showMaximized()
            QApplication.processEvents()
            self.assertTrue(window.isMaximized(),
                            "main window must support maximized state")
            self.assertGreaterEqual(window.minimumWidth(), 1000)
            self.assertGreaterEqual(window.minimumHeight(), 600)
        finally:
            window.hide()
            window.deleteLater()
            QApplication.processEvents()


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CounterSalePolishPinsTests(unittest.TestCase):
    """Counter Sale keeps comfortable (not cramped) metrics after polish."""

    @classmethod
    def setUpClass(cls):
        db_path = os.path.join(tempfile.gettempdir(),
                               "pharmacy_ui_polish_counter_sale.db")
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

        cls._app = QApplication.instance() or QApplication([])
        from screens.counter_sale import CounterSalePage

        cls.page = CounterSalePage()
        cls.page.resize(1366, 708)
        cls.page.show()
        QApplication.processEvents()
        cls.page._apply_history_height()
        from screens.counter_sale import _BillItemRow

        cls.page._sale_panel._item_rows.append(_BillItemRow(
            item_id=1, item_name="Polish Item", stock_batch_id=1,
            pack_size="10x10", location="A-1", batch_no="P-001",
            expiry="12/27", mrp=50.0, sale_qty=2.0,
            discount_amount=0.0, amount=100.0))
        cls.page._sale_panel._refresh_table()
        cls.page._sale_panel._recalc_totals()
        QApplication.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.page.hide()
        cls.page.deleteLater()
        QApplication.processEvents()

    def test_01_bill_rows_breathe(self):
        from screens.counter_sale import _BILL_ROW_HEIGHT

        self.assertGreaterEqual(_BILL_ROW_HEIGHT, 30)
        self.assertGreaterEqual(self.page._sale_panel._table.rowHeight(0), 30)

    def test_02_header_band_taller_than_rows(self):
        from screens.counter_sale import _BILL_ROW_HEIGHT

        self.assertGreater(
            self.page._sale_panel._table.horizontalHeader().height(),
            _BILL_ROW_HEIGHT)

    def test_03_entry_bar_has_vertical_breathing_room(self):
        from screens.counter_sale import _ENTRY_BAR_HEIGHT

        self.assertGreaterEqual(_ENTRY_BAR_HEIGHT, 38)
        self.assertEqual(self.page._sale_panel._entry_bar.height(),
                         _ENTRY_BAR_HEIGHT)

    def test_04_history_rows_are_readable(self):
        hist = self.page._hist_table
        self.assertGreaterEqual(
            hist.verticalHeader().defaultSectionSize(), 26)


if __name__ == "__main__":
    unittest.main(verbosity=2)
