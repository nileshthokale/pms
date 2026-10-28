import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from database.connection import init_database
from screens.sales_reports import (
    ReportFilterSearchCombo,
    CompanywiseSalesPage,
    ItemwiseSalesPage,
)

_APP = None

def get_qapp() -> QApplication:
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication(sys.argv)
        return _APP
    return app


class TestCompanywiseSalesSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_qapp()
        init_database()

    def test_companywise_sales_click_to_clear_and_search(self):
        page = CompanywiseSalesPage()
        combo = page.company_combo
        self.assertIsInstance(combo, ReportFilterSearchCombo)

        # 1. Initial state
        self.assertEqual(combo.currentText(), "-- Select Company --")
        self.assertIsNone(page.get_selected_company_id())
        self.assertGreaterEqual(combo.count(), 100, "Should load all companies")

        # 2. Click on company name box -> text is automatically removed
        line = combo.lineEdit()
        click_evt = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        combo.eventFilter(line, click_evt)
        self.assertEqual(line.text(), "", "Click must remove -- Select Company -- text")

        # 3. Enter 1st letter 'a' -> dropdown opens with companies containing 'A'
        # with prefix matches at the top
        line.setText("a")
        combo._on_text_edited("a")
        popup = combo._completer.popup()
        self.assertTrue(popup.isVisible(), "Popup opens on typing letter")
        count_a = combo._completer_model.rowCount()
        self.assertGreater(count_a, 5)

        results_a = [combo._completer_model.item(r).text() for r in range(count_a)]
        self.assertTrue(results_a[0].upper().startswith("A"))

        # 4. Enter 2nd letter 'ab' -> dropdown narrows down to Abbott, etc.
        line.setText("ab")
        combo._on_text_edited("ab")
        count_ab = combo._completer_model.rowCount()
        self.assertGreater(count_ab, 0)
        self.assertLess(count_ab, count_a)
        results_ab = [combo._completer_model.item(r).text() for r in range(count_ab)]
        self.assertTrue(any("ABBOTT" in name.upper() for name in results_ab))

        # 5. Key down and Enter to select
        down_evt = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        combo.eventFilter(line, down_evt)
        enter_evt = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        combo.eventFilter(line, enter_evt)

        selected_text = combo.currentText()
        selected_id = page.get_selected_company_id()
        self.assertTrue(selected_text.upper().startswith("AB"))
        self.assertIsNotNone(selected_id)
        self.assertFalse(popup.isVisible())

        # 6. Click on company box again -> automatically clears the selected company name
        combo.eventFilter(line, click_evt)
        self.assertEqual(line.text(), "", "Clicking selected company must remove text")

        # 7. Focus out without typing -> restores '-- Select Company --'
        focus_out = QEvent(QEvent.FocusOut)
        combo.eventFilter(line, focus_out)
        self.assertEqual(combo.currentText(), "-- Select Company --")
        self.assertIsNone(page.get_selected_company_id())

    def test_company_search_by_word_and_short_name(self):
        """Verify search engine finds companies by words and short names."""
        page = CompanywiseSalesPage()
        combo = page.company_combo

        # Search by word 'pharma' -> matches all pharmaceutical companies
        combo._on_text_edited("pharma")
        results_pharma = [combo._completer_model.item(r).text() for r in range(combo._completer_model.rowCount())]
        self.assertGreater(len(results_pharma), 0)
        self.assertTrue(any("PHARMA" in name.upper() for name in results_pharma))

        # Search by word 'healthcare'
        combo._on_text_edited("healthcare")
        results_health = [combo._completer_model.item(r).text() for r in range(combo._completer_model.rowCount())]
        self.assertGreater(len(results_health), 0)
        self.assertTrue(any("HEALTHCARE" in name.upper() for name in results_health))

    def test_itemwise_sales_click_to_clear_and_search(self):
        page = ItemwiseSalesPage()
        combo = page.item_combo
        self.assertIsInstance(combo, ReportFilterSearchCombo)

        # Initial state
        self.assertEqual(combo.currentText(), "-- Select Item --")
        self.assertIsNone(page.get_selected_item_id())

        # Click to clear
        line = combo.lineEdit()
        click_evt = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(10, 10),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        combo.eventFilter(line, click_evt)
        self.assertEqual(line.text(), "")

        # Type 'cin' -> finds L-CIN
        combo._on_text_edited("cin")
        results = [combo._completer_model.item(r).text() for r in range(combo._completer_model.rowCount())]
        self.assertTrue(any("L-CIN" in it for it in results))


if __name__ == "__main__":
    unittest.main()
