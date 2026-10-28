import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from database.connection import init_database
from screens.schedule_reports import (
    ScheduleItemSearchCombo,
    ScheduleSalesItemwisePage,
    SchedulePurchaseItemwisePage,
)

_APP = None

def get_qapp() -> QApplication:
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication(sys.argv)
        return _APP
    return app


class TestScheduleItemwiseSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_qapp()
        init_database()

    def test_sales_itemwise_click_to_clear_and_search(self):
        page = ScheduleSalesItemwisePage(schedule_type="H1")
        combo = page.item_combo
        self.assertIsInstance(combo, ScheduleItemSearchCombo)

        # 1. Initial state
        self.assertEqual(combo.currentText(), "-- Select Item --")
        self.assertIsNone(combo.currentData())
        self.assertGreaterEqual(combo.count(), 47, "Must contain all items")

        # 2. Click on item name box -> text is automatically removed
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

        # 3. Enter 1st letter 'c' -> dropdown opens with ALL items containing 'C'
        # with prefix matches at the top (CEFAXONE, CEFUROCK, CETIL, CONTRAMAL)
        line.setText("c")
        combo._on_text_edited("c")
        popup = combo._completer.popup()
        self.assertTrue(popup.isVisible())
        count_c = combo._completer_model.rowCount()
        self.assertGreater(count_c, 5)

        # Verify all results contain 'c'
        results_c = [combo._completer_model.item(r).text() for r in range(count_c)]
        for item_text in results_c:
            self.assertIn("C", item_text.upper(), f"Item '{item_text}' should contain C")

        # Verify prefix matches appear first
        self.assertTrue(results_c[0].upper().startswith("C"))

        # Verify items like L-CIN and ULTRACET are also present (not dropped!)
        self.assertTrue(any("L-CIN" in it for it in results_c), "L-CIN must appear for search 'c'")
        self.assertTrue(any("ULTRACET" in it for it in results_c), "ULTRACET must appear for search 'c'")

        # 4. Enter 2nd letter 'co' -> dropdown dynamically filters down
        line.setText("co")
        combo._on_text_edited("co")
        count_co = combo._completer_model.rowCount()
        self.assertGreater(count_co, 0)
        self.assertLess(count_co, count_c)
        results_co = [combo._completer_model.item(r).text() for r in range(count_co)]
        for item_text in results_co:
            self.assertIn("CO", item_text.upper(), f"Item '{item_text}' should contain CO")

        # 5. Key down and Enter to select
        down_evt = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        combo.eventFilter(line, down_evt)
        enter_evt = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        combo.eventFilter(line, enter_evt)

        selected_text = combo.currentText()
        selected_id = combo.currentData()
        self.assertIn("CO", selected_text.upper())
        self.assertIsNotNone(selected_id)
        self.assertFalse(popup.isVisible())

        # 6. Click on item name box again -> automatically clears the selected item name
        combo.eventFilter(line, click_evt)
        self.assertEqual(line.text(), "")

        # 7. Focus out without typing -> restores '-- Select Item --'
        focus_out = QEvent(QEvent.FocusOut)
        combo.eventFilter(line, focus_out)
        self.assertEqual(combo.currentText(), "-- Select Item --")
        self.assertIsNone(combo.currentData())

    def test_proper_search_engine_substrings_and_tokens(self):
        """Verify proper search engine handles substrings, dosages, and tokens."""
        page = ScheduleSalesItemwisePage(schedule_type="H1")
        combo = page.item_combo

        # Search 'cin' -> finds L-CIN
        combo._on_text_edited("cin")
        results_cin = [combo._completer_model.item(r).text() for r in range(combo._completer_model.rowCount())]
        self.assertTrue(any("L-CIN" in it for it in results_cin))

        # Search '250' -> finds CETIL 250, L-CIN 250, etc.
        combo._on_text_edited("250")
        results_250 = [combo._completer_model.item(r).text() for r in range(combo._completer_model.rowCount())]
        self.assertTrue(any("250" in it for it in results_250))

        # Search '500' -> finds CEFUROCK 500, L-CIN 500, etc.
        combo._on_text_edited("500")
        results_500 = [combo._completer_model.item(r).text() for r in range(combo._completer_model.rowCount())]
        self.assertTrue(any("500" in it for it in results_500))

        # Search 'opox 50' -> finds OPOX 50 variants
        combo._on_text_edited("opox 50")
        results_opox50 = [combo._completer_model.item(r).text() for r in range(combo._completer_model.rowCount())]
        self.assertTrue(any("OPOX 50" in it for it in results_opox50))

        # Search 'semi' -> finds ULTRACET SEMI
        combo._on_text_edited("semi")
        results_semi = [combo._completer_model.item(r).text() for r in range(combo._completer_model.rowCount())]
        self.assertTrue(any("ULTRACET SEMI" in it for it in results_semi))

    def test_purchase_itemwise_click_to_clear_and_search(self):
        page = SchedulePurchaseItemwisePage(schedule_type="H1")
        combo = page.item_combo
        self.assertIsInstance(combo, ScheduleItemSearchCombo)

        # Initial state
        self.assertEqual(combo.currentText(), "-- Select Item --")
        self.assertIsNone(combo.currentData())

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

        # Enter 1st letter 'l'
        line.setText("l")
        combo._on_text_edited("l")
        self.assertTrue(combo._completer.popup().isVisible())
        count_l = combo._completer_model.rowCount()
        self.assertGreater(count_l, 0)

        # Enter 2nd letter 'le'
        line.setText("le")
        combo._on_text_edited("le")
        count_le = combo._completer_model.rowCount()
        self.assertGreater(count_le, 0)
        self.assertLessEqual(count_le, count_l)
        results_le = [combo._completer_model.item(r).text() for r in range(count_le)]
        self.assertTrue(any(it.upper().startswith("LE") for it in results_le))

    def test_dropdown_arrow_shows_all_suggestions_with_select_item(self):
        page = ScheduleSalesItemwisePage(schedule_type="H1")
        combo = page.item_combo
        combo.showPopup()
        self.assertGreater(combo._completer_model.rowCount(), 1)
        self.assertEqual(combo._completer_model.item(0).text(), "-- Select Item --")
        self.assertIsNone(combo._completer_model.item(0).data(Qt.UserRole))


if __name__ == "__main__":
    unittest.main()
