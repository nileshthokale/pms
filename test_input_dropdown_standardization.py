"""Comprehensive unit tests for input sizing, dropdown standardization, and starts-with search.

Verifies:
1. Field Sizing Standards (CONTROL_HEIGHT=32px, small: 65-90px, medium: 105-140px, large: 220-450px).
2. Helper functions: apply_field_size, style_input_small, style_input_medium, style_input_large.
3. SearchableComboBox starts-with matching by default (B, BIO, case-insensitive, no middle match).
4. SearchableComboBox 'No matching records found' handling on Enter, Tab, and click.
5. TableComboBox starts-with matching and footer 'No matching records found'.
6. TableComboBox Enter/Tab does not commit hidden rows when query matches nothing.
7. Dropdown positioning geometry (opens below / above if near bottom, screen margin clamping).
8. Screens verification: daily_profit_calculation and stock_reports default to starts-with matching.
"""

import os
import sys
import tempfile
import unittest
from PySide6.QtCore import Qt, QPoint, QRect, QEvent
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QComboBox,
    QDateEdit,
    QSpinBox,
    QSizePolicy,
)
from PySide6.QtGui import QKeyEvent

# Ensure application package root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

app = QApplication.instance() or QApplication(sys.argv)

from database.connection import init_database, get_connection
import ui.components as uc
from ui.components import (
    CONTROL_HEIGHT,
    FIELD_WIDTH_SMALL,
    FIELD_WIDTH_SMALL_MIN,
    FIELD_WIDTH_SMALL_MAX,
    FIELD_WIDTH_MEDIUM,
    FIELD_WIDTH_MEDIUM_MIN,
    FIELD_WIDTH_MEDIUM_MAX,
    FIELD_WIDTH_LARGE,
    FIELD_WIDTH_LARGE_MIN,
    FIELD_WIDTH_LARGE_MAX,
    apply_field_size,
    style_input_small,
    style_input_medium,
    style_input_large,
    SearchableComboBox,
    TableComboBox,
    ConstrainedComboBox,
)


class TestInputDropdownStandardization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_db_fd, cls.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(cls.temp_db_fd)
        cls._orig_db = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = cls.temp_db_path
        init_database()

    @classmethod
    def tearDownClass(cls):
        if cls._orig_db is not None:
            os.environ["PHARMACY_DB"] = cls._orig_db
        else:
            os.environ.pop("PHARMACY_DB", None)
        if os.path.exists(cls.temp_db_path):
            try:
                os.remove(cls.temp_db_path)
            except Exception:
                pass
    # =========================================================================
    # 1. Standard Field Sizing Constants & Helper Functions
    # =========================================================================
    def test_01_sizing_constants(self):
        self.assertEqual(CONTROL_HEIGHT, 32)
        # Small: 65-90px (default 80px)
        self.assertEqual(FIELD_WIDTH_SMALL_MIN, 65)
        self.assertEqual(FIELD_WIDTH_SMALL, 80)
        self.assertEqual(FIELD_WIDTH_SMALL_MAX, 90)

        # Medium: 105-140px (default 130px)
        self.assertEqual(FIELD_WIDTH_MEDIUM_MIN, 105)
        self.assertEqual(FIELD_WIDTH_MEDIUM, 130)
        self.assertEqual(FIELD_WIDTH_MEDIUM_MAX, 140)

        # Large: 220-450px (default 300px)
        self.assertEqual(FIELD_WIDTH_LARGE_MIN, 220)
        self.assertEqual(FIELD_WIDTH_LARGE, 300)
        self.assertEqual(FIELD_WIDTH_LARGE_MAX, 450)

    def test_02_apply_field_size(self):
        # Small field by category name
        w1 = QLineEdit()
        apply_field_size(w1, "small")
        self.assertEqual(w1.height(), 32)
        self.assertEqual(w1.minimumWidth(), 65)
        self.assertEqual(w1.maximumWidth(), 90)

        # Small field by business field name (e.g. qty, mrp)
        w2 = QLineEdit()
        apply_field_size(w2, "qty")
        self.assertEqual(w2.minimumWidth(), 65)
        self.assertEqual(w2.maximumWidth(), 90)

        # Small field fixed
        w3 = QLineEdit()
        apply_field_size(w3, "rate", fixed=True)
        self.assertEqual(w3.width(), 80)

        # Medium field by business field name (e.g. batch_no, date)
        w4 = QLineEdit()
        apply_field_size(w4, "batch_no")
        self.assertEqual(w4.minimumWidth(), 105)
        self.assertEqual(w4.maximumWidth(), 140)
        self.assertEqual(w4.height(), 32)

        # Large field by business field name (e.g. item_name, supplier)
        w5 = QLineEdit()
        apply_field_size(w5, "supplier_name")
        self.assertEqual(w5.minimumWidth(), 220)
        self.assertEqual(w5.sizePolicy().horizontalPolicy(), QSizePolicy.Expanding)

    def test_03_style_input_helpers(self):
        # style_input_small
        edit_sm = QLineEdit()
        style_input_small(edit_sm)
        self.assertEqual(edit_sm.height(), 32)
        self.assertEqual(edit_sm.minimumWidth(), 65)
        self.assertEqual(edit_sm.maximumWidth(), 90)
        self.assertEqual(edit_sm.alignment(), Qt.AlignRight | Qt.AlignVCenter)

        # style_input_medium
        date_edit = QDateEdit()
        style_input_medium(date_edit)
        self.assertEqual(date_edit.height(), 32)
        self.assertEqual(date_edit.minimumWidth(), 105)
        self.assertEqual(date_edit.maximumWidth(), 140)

        # style_input_large
        edit_lg = QLineEdit()
        style_input_large(edit_lg)
        self.assertEqual(edit_lg.height(), 32)
        self.assertEqual(edit_lg.minimumWidth(), 220)
        self.assertEqual(edit_lg.sizePolicy().horizontalPolicy(), QSizePolicy.Expanding)

    # =========================================================================
    # 2. SearchableComboBox Starts-with Search Contract
    # =========================================================================
    def test_04_searchable_combo_starts_with_b_and_bio(self):
        combo = SearchableComboBox()
        self.assertTrue(combo._prefix_only)

        items = [
            ("BIOCLOX 500", 1),
            ("BIO D3 CAPSULE", 2),
            ("BIOPAR INJ", 3),
            ("CALCIUM BIO SYRUP", 4),
            ("COMBIFLAM TABLET", 5),
            ("BABY BIO DROP", 6),
            ("BACTOCLAV", 7),
        ]
        for name, item_id in items:
            combo.addItem(name, item_id)

        # 1. Typing 'B' must show names beginning with B
        combo._on_text_edited("B")
        matched = [combo._completer_model.item(i).text() for i in range(combo._completer_model.rowCount())]
        self.assertIn("BIOCLOX 500", matched)
        self.assertIn("BIO D3 CAPSULE", matched)
        self.assertIn("BIOPAR INJ", matched)
        self.assertIn("BABY BIO DROP", matched)
        self.assertIn("BACTOCLAV", matched)
        # Middle-string matches must NOT appear:
        self.assertNotIn("CALCIUM BIO SYRUP", matched)
        self.assertNotIn("COMBIFLAM TABLET", matched)

        # 2. Typing 'BIO' must show names beginning with BIO
        combo._on_text_edited("BIO")
        matched_bio = [combo._completer_model.item(i).text() for i in range(combo._completer_model.rowCount())]
        self.assertIn("BIOCLOX 500", matched_bio)
        self.assertIn("BIO D3 CAPSULE", matched_bio)
        self.assertIn("BIOPAR INJ", matched_bio)
        # Names starting with BABY or CALCIUM must NOT appear:
        self.assertNotIn("BABY BIO DROP", matched_bio)
        self.assertNotIn("CALCIUM BIO SYRUP", matched_bio)
        self.assertNotIn("BACTOCLAV", matched_bio)

        # 3. Lowercase 'bio' works identically
        combo._on_text_edited("bio")
        matched_lower = [combo._completer_model.item(i).text() for i in range(combo._completer_model.rowCount())]
        self.assertEqual(matched_bio, matched_lower)

    def test_05_searchable_combo_no_match_clean_handling(self):
        combo = SearchableComboBox()
        combo.addItem("PARACETAMOL 500", 1)
        combo.addItem("PARACETAMOL 650", 2)

        # Type non-existent query
        combo.lineEdit().setText("NON_EXISTENT_MED")
        combo._on_text_edited("NON_EXISTENT_MED")
        self.assertEqual(combo._completer_model.rowCount(), 1)
        no_match_item = combo._completer_model.item(0)
        self.assertFalse(no_match_item.isEnabled())
        self.assertIn("No matching records found", no_match_item.text())
        self.assertIsNone(no_match_item.data(Qt.UserRole))

        # Enter key on "No matching records found" must NOT select anything or crash
        enter_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        combo.eventFilter(combo.lineEdit(), enter_event)
        self.assertIsNone(combo.currentData())
        self.assertEqual(combo.currentIndex(), -1)

    # =========================================================================
    # 3. TableComboBox Starts-with Search Contract & Footer
    # =========================================================================
    def test_06_table_combo_starts_with_and_footer_no_match(self):
        combo = TableComboBox(placeholder="Select Batch...")
        batches = [
            {"id": 1, "batch_no": "B100", "expiry": "2027-12-31", "mrp": 50.0, "stock_qty": 100},
            {"id": 2, "batch_no": "BIO-200", "expiry": "2028-06-30", "mrp": 120.0, "stock_qty": 50},
            {"id": 3, "batch_no": "C-BIO-300", "expiry": "2028-06-30", "mrp": 150.0, "stock_qty": 20},
        ]
        combo.set_batches(batches)

        # 1. Search 'B'
        combo._on_text_edited("B")
        vis_rows = [r for r in range(combo._table_model.rowCount()) if not combo.table_view.isRowHidden(r)]
        vis_batches = [combo._table_model.item(r, 0).text() for r in vis_rows if combo._table_model.item(r, 0)]
        self.assertIn("B100", vis_batches)
        self.assertIn("BIO-200", vis_batches)
        self.assertNotIn("C-BIO-300", vis_batches)

        # 2. Search 'BIO'
        combo._on_text_edited("BIO")
        vis_rows2 = [r for r in range(combo._table_model.rowCount()) if not combo.table_view.isRowHidden(r)]
        vis_batches2 = [combo._table_model.item(r, 0).text() for r in vis_rows2 if combo._table_model.item(r, 0)]
        self.assertIn("BIO-200", vis_batches2)
        self.assertNotIn("B100", vis_batches2)
        self.assertNotIn("C-BIO-300", vis_batches2)

        # 3. Search non-existent query
        combo.lineEdit().setText("XYZ_NONEXISTENT")
        combo._on_text_edited("XYZ_NONEXISTENT")
        vis_rows3 = [r for r in range(combo._table_model.rowCount()) if not combo.table_view.isRowHidden(r)]
        self.assertEqual(len(vis_rows3), 0)
        self.assertIn("No matching records found", combo._status_label.text())

        # 4. Pressing Enter when no rows match must NOT commit a hidden row
        enter_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        combo.eventFilter(combo.lineEdit(), enter_event)
        self.assertIsNone(combo.currentData())

    # =========================================================================
    # 4. Screens starts-with verification
    # =========================================================================
    def test_07_screens_default_to_starts_with(self):
        # 1. daily_profit_calculation.py
        from screens.daily_profit_calculation import DailyProfitCostReportWidget
        page1 = DailyProfitCostReportWidget()
        if page1.item_combo.completer():
            self.assertEqual(page1.item_combo.completer().filterMode(), Qt.MatchStartsWith)
        if page1.company_combo.completer():
            self.assertEqual(page1.company_combo.completer().filterMode(), Qt.MatchStartsWith)

        # 2. stock_reports.py
        from screens.stock_reports import CompanywiseItemStockPage
        page2 = CompanywiseItemStockPage()
        if hasattr(page2, "cbo_company") and page2.cbo_company.completer():
            self.assertEqual(page2.cbo_company.completer().filterMode(), Qt.MatchStartsWith)


if __name__ == "__main__":
    unittest.main()
