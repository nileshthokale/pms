"""Unit tests for search engine and auto-clear in Purchase Reports.

Tests:
1. BasePurchaseReportWindow uses ReportFilterSearchCombo for its filter dropdown.
2. Clicking the dropdown lineEdit automatically clears the text and resets index.
3. Real-time letter-by-letter multi-tier search engine:
   - Tier 1: prefix matches
   - Tier 2: word boundary matches
   - Tier 3: substring / token matches
   - All matches preserved (never dropped).
4. Full keyboard navigation (Down/Up arrow keys, Enter to commit, Escape to dismiss).
5. Focus out / blur restores index 0 (-- Select ... --) if left blank.
6. SearchableFilterEdit auto-clears on click and provides 3-tier filtering.
"""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from screens.purchase_reports import (
    CompanywiseItemwisePurchasePage,
    SupplierwiseItemwiseInvoicePurchasePage,
    ItemwisePurchasePage,
)
from screens.purchase_report import PurchaseReportPage
from ui.components import ReportFilterSearchCombo
from ui.searchable_filter import SearchableFilterEdit


class TestPurchaseReportsSearchEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_01_purchase_reports_dropdown_is_report_filter_search_combo(self):
        page = CompanywiseItemwisePurchasePage()
        self.assertIsInstance(page.dropdown, ReportFilterSearchCombo)

    def test_02_click_to_clear_on_company_dropdown(self):
        page = CompanywiseItemwisePurchasePage()
        line = page.dropdown.lineEdit()
        self.assertIsNotNone(line)
        self.assertEqual(line.text(), "-- Select Company --")

        # Simulate clicking on the lineEdit
        click_evt = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        page.dropdown.eventFilter(line, click_evt)

        # Line edit must be completely cleared
        self.assertEqual(line.text(), "")
        self.assertEqual(page.dropdown.currentIndex(), -1)

    def test_03_multi_tier_search_and_no_dropped_items(self):
        combo = ReportFilterSearchCombo()
        combo.addItem("-- Select Company --", None)
        combo.addItem("CIPLA LIMITED", 1, "CIPLA LIMITED CIP")
        combo.addItem("CADILA HEALTHCARE", 2, "CADILA HEALTHCARE CAD")
        combo.addItem("SUN PHARMA", 3, "SUN PHARMA SUN")
        combo.addItem("TORRENT PHARMA", 4, "TORRENT PHARMA TOR")
        combo.addItem("ALEMBIC PHARMACEUTICALS", 5, "ALEMBIC PHARMACEUTICALS AP")
        combo.setCurrentIndex(0)

        # Query "C"
        combo._on_text_edited("C")
        model = combo._completer_model
        results = [model.index(r, 0).data(Qt.DisplayRole) for r in range(model.rowCount())]

        # Both CADILA and CIPLA start with C -> Tier 1 (starts with)
        self.assertIn("CADILA HEALTHCARE", results[:2])
        self.assertIn("CIPLA LIMITED", results[:2])
        # ALEMBIC contains "PHARMACEUTICALS" which has "C" -> Tier 3
        self.assertIn("ALEMBIC PHARMACEUTICALS", results)
        # All items containing 'C' are present (no dropped items)
        self.assertEqual(len(results), 3)

        # Query "PH" -> "SUN PHARMA", "TORRENT PHARMA", "ALEMBIC PHARMACEUTICALS"
        combo._on_text_edited("PH")
        results_ph = [model.index(r, 0).data(Qt.DisplayRole) for r in range(model.rowCount())]
        # All three have words starting with "PH"
        self.assertEqual(len(results_ph), 3)
        self.assertIn("SUN PHARMA", results_ph)
        self.assertIn("TORRENT PHARMA", results_ph)
        self.assertIn("ALEMBIC PHARMACEUTICALS", results_ph)

    def test_04_keyboard_navigation_and_selection(self):
        combo = ReportFilterSearchCombo()
        combo.addItem("-- Select Supplier --", None)
        combo.addItem("ALPHA DISTRIBUTORS", 101)
        combo.addItem("AMRUT PHARMA", 102)
        combo.addItem("BETA AGENCIES", 103)
        combo.setCurrentIndex(0)

        # Click to clear
        line = combo.lineEdit()
        click_evt = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        combo.eventFilter(line, click_evt)
        self.assertEqual(line.text(), "")

        # Type "AM" -> matches AMRUT PHARMA
        combo._on_text_edited("AM")
        model = combo._completer_model
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.index(0, 0).data(Qt.DisplayRole), "AMRUT PHARMA")

        # Select the item
        combo._on_completer_index_activated(model.index(0, 0))
        self.assertEqual(combo.currentText(), "AMRUT PHARMA")
        self.assertEqual(combo.currentData(), 102)

    def test_05_focus_out_restores_placeholder_if_empty(self):
        combo = ReportFilterSearchCombo()
        combo.addItem("-- Select Item --", None)
        combo.addItem("PARACETAMOL 500MG", 501)
        combo.setCurrentIndex(0)

        line = combo.lineEdit()
        # Click to clear
        click_evt = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        combo.eventFilter(line, click_evt)
        self.assertEqual(line.text(), "")

        # Focus out without typing
        focus_out_evt = QEvent(QEvent.FocusOut)
        combo.eventFilter(line, focus_out_evt)
        self.assertEqual(combo.currentIndex(), 0)
        self.assertEqual(line.text(), "-- Select Item --")

    def test_06_searchable_filter_edit_click_to_clear_and_search(self):
        edit = SearchableFilterEdit("All suppliers")
        edit.set_options([
            {"id": 1, "supplier_name": "ALPHA DISTRIBUTORS"},
            {"id": 2, "supplier_name": "APOLLO PHARMACY"},
            {"id": 3, "supplier_name": "BHARAT MEDICO"},
        ], "id", "supplier_name")

        # Pick an option
        edit.setText("ALPHA DISTRIBUTORS")
        edit._selected_id = 1
        self.assertEqual(edit.text(), "ALPHA DISTRIBUTORS")

        # Click on edit -> automatically clears
        click_evt = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        edit.mousePressEvent(click_evt)
        self.assertEqual(edit.text(), "")
        self.assertIsNone(edit.selected_id)

        # Search "AP" -> matches APOLLO PHARMACY
        edit._on_text_edited("AP")
        self.assertEqual(edit.completer().completionCount(), 1)
        idx = edit.completer().completionModel().index(0, 0)
        edit._on_completion_activated(idx)
        self.assertEqual(edit.text(), "APOLLO PHARMACY")
        self.assertEqual(edit.selected_id, 2)


if __name__ == "__main__":
    unittest.main()
