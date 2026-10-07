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


def _font_px(stylesheet: str) -> int | None:
    """Font size declared in a stylesheet, normalised to pixels.

    ``pt`` is converted with the 96 dpi Qt uses for stylesheet fonts, so a
    legacy ``10pt`` declaration and a ``13px`` one are comparable.
    """
    match = re.search(r"font-size:\s*(\d+)(px|pt)", stylesheet)
    if not match:
        return None
    value = int(match.group(1))
    return value if match.group(2) == "px" else round(value * 96 / 72)


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
        size = _font_px(ui_components.label_style())
        self.assertIsNotNone(size, "default label lost its font size")
        self.assertGreaterEqual(size, 12,
                                f"field captions must be >= 12px, got {size}")

    def test_05_section_titles_are_bold_and_readable(self):
        style = ui_components.section_title_style()
        self.assertIn("font-weight: bold", style)
        size = _font_px(style)
        self.assertIsNotNone(size)
        self.assertGreaterEqual(size, 13,
                                f"section headers must be >= 13px, got {size}")

    def test_06_table_headers_are_bold_and_readable(self):
        style = ui_components.table_header_style()
        self.assertIn("font-weight: bold", style)
        size = _font_px(style)
        self.assertIsNotNone(size)
        self.assertGreaterEqual(size, 12,
                                f"table headers must be >= 12px, got {size}")

    def test_07_inputs_are_readable(self):
        for style in (ui_components.edit_style(), ui_components.combo_style(),
                      ui_components.date_style(), ui_components.spin_style()):
            size = _font_px(style)
            self.assertIsNotNone(size, "input lost its font size")
            self.assertGreaterEqual(size, 12,
                                    f"input text must be >= 12px, got {size}")

    def test_08_buttons_have_breathing_room(self):
        style = ui_components.btn_primary_style()
        match = re.search(r"min-height:\s*(\d+)px", style)
        self.assertIsNotNone(match, "buttons lost their minimum height")
        self.assertGreaterEqual(int(match.group(1)), 22)

    def test_09_table_data_is_readable(self):
        size = _font_px(ui_components.table_style())
        self.assertIsNotNone(size, "table style lost its font size")
        self.assertGreaterEqual(size, 12,
                                f"table data must be >= 12px, got {size}")

    def test_10_page_title_outranks_table_text(self):
        title = _font_px(ui_components.title_style())
        data = _font_px(ui_components.table_style())
        self.assertIsNotNone(title)
        self.assertIsNotNone(data)
        self.assertGreaterEqual(title, 16, "page title must stay prominent")
        self.assertGreater(title, data,
                           "page title must be clearly larger than table text")

    def test_11_shared_font_matches_stylesheet(self):
        """The declared stylesheet size and the real QFont must agree."""
        for size in (ui_components.TYPE_TABLE_DATA,
                     ui_components.TYPE_TABLE_HEADER):
            font = ui_components.readable_font(size)
            self.assertEqual(font.pixelSize(), size)

    def test_12_typography_scale_floor(self):
        from ui.theme import (TYPE_FORM_LABEL, TYPE_TABLE_DATA,
                              TYPE_TABLE_HEADER, TYPE_VALUE)
        self.assertGreaterEqual(TYPE_TABLE_DATA, 12)
        self.assertGreaterEqual(TYPE_TABLE_HEADER, 12)
        self.assertGreaterEqual(TYPE_FORM_LABEL, 11)
        self.assertGreaterEqual(TYPE_VALUE, 12)


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
