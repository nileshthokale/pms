"""Acceptance tests for the compact, FY-bounded Sales Report controls."""

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.document_printing import generate_sales_report_pdf

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from ui.searchable_filter import SearchableFilterEdit
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PySide6 is required for filter widget tests")
class TestSearchableFilterEdit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.edit = SearchableFilterEdit("All items")
        self.edit.set_options(
            [{"id": number, "name": f"Pain Relief {number:02d}"} for number in range(1, 24)],
            "id", "name",
        )

    def test_partial_case_insensitive_match_and_id_selection(self):
        self.edit.setText("relIEF 07")
        self.edit._on_text_edited("relIEF 07")
        self.assertEqual(self.edit.completer().completionCount(), 1)
        index = self.edit.completer().completionModel().index(0, 0)
        self.edit._on_completion_activated(index)
        self.assertEqual(self.edit.text(), "Pain Relief 07")
        self.assertEqual(self.edit.selected_id, 7)

    def test_popup_is_compact_and_clear_means_all(self):
        self.assertEqual(self.edit.completer().maxVisibleItems(), 12)
        self.assertLessEqual(self.edit.completer().popup().maximumHeight(), 316)
        self.edit._on_completion_activated(self.edit._model.index(0, 0))
        self.edit.clear_filter()
        self.assertEqual(self.edit.text(), "")
        self.assertIsNone(self.edit.selected_id)

    def test_keyboard_enter_selects_and_escape_closes(self):
        self.edit.show()
        self.edit.setFocus()
        QTest.keyClicks(self.edit, "relief 08")
        self.app.processEvents()
        # Down opens the compact list; choose the only match with Enter.
        QTest.keyClick(self.edit, Qt.Key_Down)
        self.app.processEvents()
        QTest.keyClick(self.edit, Qt.Key_Enter)
        self.assertEqual(self.edit.selected_id, 8)
        self.edit._on_text_edited("relief")
        self.assertTrue(self.edit.completer().popup().isVisible())
        QTest.keyClick(self.edit, Qt.Key_Escape)
        self.assertFalse(self.edit.completer().popup().isVisible())


class TestSalesReportPdf(unittest.TestCase):
    def test_print_pdf_repeats_headings_and_contains_year_filters_and_totals(self):
        rows = [{
            "bill_no": f"CS-{number:03d}", "sale_date": "2017-06-15",
            "customer_name": "Customer", "patient_name": "Patient", "doctor_name": "Doctor",
            "item_name": "Item", "batch_no": "B1", "expiry": "12/27", "mrp": 10,
            "sale_qty": 1, "discount_amount": 0, "amount": 10,
        } for number in range(45)]
        summary = {"total_bills": 45, "total_lines": 45, "total_qty": 45,
                   "total_gross": 450, "total_discount": 0, "total_net": 450}
        with tempfile.TemporaryDirectory() as directory:
            path = generate_sales_report_pdf(
                rows, summary, "2017-2018", "Financial year: 2017-2018 | Item: Item",
                os.path.join(directory, "sales.pdf"),
            )
            with open(path, "rb") as pdf:
                content = pdf.read().decode("latin-1")
        self.assertIn("/MediaBox [0 0 842 595]", content)
        self.assertIn("Financial Year: 2017-2018", content)
        self.assertIn("Totals: Bills: 45", content)
        self.assertIn("Page 1 of 2", content)
        self.assertIn("Page 2 of 2", content)
        self.assertGreaterEqual(content.count("Bill No"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
