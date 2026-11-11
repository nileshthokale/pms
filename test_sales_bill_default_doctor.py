import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from database.connection import init_database
from database.doctor_dao import DoctorDAO
from screens.counter_sale import _SalePanel, SalesBillReviewDialog


class TestSalesBillDefaultDoctor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database()

    def test_01_default_doctor_in_sale_panel_is_dr_ghorpade(self):
        """In _SalePanel, default doctor is DR.K.N.GHORPADE."""
        panel = _SalePanel()
        text = panel.doctor_combo.currentText().upper()
        self.assertIn("GHORPADE", text)
        self.assertIsNotNone(panel.doctor_combo.currentData())

    def test_02_default_doctor_in_sales_bill_popup_is_dr_ghorpade(self):
        """When saving a bill and Sales Bill review popup opens, default doctor is Dr. Ghorpade."""
        panel = _SalePanel()
        dlg = SalesBillReviewDialog(panel)
        text = dlg._panel.doctor_combo.currentText().upper()
        self.assertIn("GHORPADE", text)
        self.assertIsNotNone(dlg._panel.doctor_combo.currentData())

    def test_03_dropdown_list_contains_all_doctors_to_change(self):
        """Dropdown list contains all doctors so user can change it."""
        panel = _SalePanel()
        dlg = SalesBillReviewDialog(panel)
        combo = dlg._panel.doctor_combo
        self.assertGreaterEqual(combo.count(), 2)
        # -- None -- is at index 0
        self.assertEqual(combo.itemText(0).strip(), "-- None --")
        self.assertIsNone(combo.itemData(0))

        # Check Ghorpade is selected
        selected_text = combo.currentText().upper()
        self.assertIn("GHORPADE", selected_text)

        # User can change to another doctor
        combo.setCurrentIndex(0)
        self.assertEqual(combo.currentText().strip(), "-- None --")
        self.assertIsNone(combo.currentData())

    def test_04_explicit_doctor_selection_preserved(self):
        """If user explicitly selects another doctor, that selection is preserved in popup."""
        panel = _SalePanel()
        # Find another doctor if exists
        other_idx = -1
        for i in range(panel.doctor_combo.count()):
            if "GHORPADE" not in panel.doctor_combo.itemText(i).upper() and panel.doctor_combo.itemData(i) is not None:
                other_idx = i
                break
        if other_idx >= 0:
            other_id = panel.doctor_combo.itemData(other_idx)
            panel.doctor_combo.setCurrentIndex(other_idx)
            dlg = SalesBillReviewDialog(panel)
            self.assertEqual(dlg._panel.doctor_combo.currentData(), other_id)

    def test_05_reset_for_new_resets_to_dr_ghorpade(self):
        """reset_for_new resets doctor back to Dr. Ghorpade."""
        panel = _SalePanel()
        panel.doctor_combo.setCurrentIndex(0)  # set to None
        self.assertIsNone(panel.doctor_combo.currentData())
        panel.reset_for_new()
        text = panel.doctor_combo.currentText().upper()
        self.assertIn("GHORPADE", text)


if __name__ == "__main__":
    unittest.main()
