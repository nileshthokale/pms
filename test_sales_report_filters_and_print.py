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
        # Companywise portrait layout: one group per distinct item so that a
        # large company report paginates and repeats its column headings.
        rows = [{
            "bill_no": f"CS-{number:03d}", "sale_date": "2017-06-15",
            "customer_name": "Customer", "patient_name": "Patient", "doctor_name": "Doctor",
            "item_name": f"Item-{number:03d}", "company_name": "TestCompany",
            "unit_name": "TAB", "pack_size": "10x10",
            "batch_no": "B1", "expiry": "12/27", "mrp": 10,
            "sale_qty": 1, "discount_amount": 0, "amount": 10,
        } for number in range(45)]
        summary = {"total_bills": 45, "total_lines": 45, "total_qty": 45,
                   "total_gross": 450, "total_discount": 0, "total_net": 450}
        with tempfile.TemporaryDirectory() as directory:
            path = generate_sales_report_pdf(
                rows, summary, "2017-2018", "Financial year: 2017-2018 | Company: TestCompany",
                os.path.join(directory, "sales.pdf"),
            )
            with open(path, "rb") as pdf:
                content = pdf.read().decode("latin-1")
        # Portrait A4, companywise title and header.
        self.assertIn("/MediaBox [0 0 595 842]", content)
        self.assertIn("Companywise Sales Report", content)
        self.assertIn("Company : TestCompany", content)
        self.assertIn("From : 15-06-2017", content)
        # Table columns, per-item subtotals and bordered grand total.
        for head in ("SrNo", "Item Name", "Unit", "Pack Size", "Batch No", "MRP", "SalesQty", "Amount"):
            self.assertIn(head, content)
        self.assertIn("Total", content)
        self.assertIn("Grand Total", content)
        self.assertIn("450.00", content)
        # Paginated with repeated headings and page numbers.
        self.assertIn("Page 1 of 2", content)
        self.assertIn("Page 2 of 2", content)
        self.assertGreaterEqual(content.count("SrNo"), 2)

    def test_print_pdf_single_company_group_shows_subtotal_and_grand_total(self):
        rows = [
            {"bill_no": "CS-001", "sale_date": "2017-06-15", "item_name": "ItemA",
             "company_name": "TestCompany", "unit_name": "TAB", "pack_size": "10x10",
             "batch_no": "B1", "mrp": 10, "sale_qty": 2, "amount": 20},
            {"bill_no": "CS-002", "sale_date": "2017-06-16", "item_name": "ItemA",
             "company_name": "TestCompany", "unit_name": "TAB", "pack_size": "10x10",
             "batch_no": "B2", "mrp": 10, "sale_qty": 3, "amount": 30},
        ]
        summary = {"total_bills": 2, "total_lines": 2, "total_qty": 5,
                   "total_gross": 50, "total_discount": 0, "total_net": 50}
        with tempfile.TemporaryDirectory() as directory:
            path = generate_sales_report_pdf(
                rows, summary, "2017-2018", "Financial year: 2017-2018 | Company: TestCompany",
                os.path.join(directory, "sales.pdf"),
            )
            with open(path, "rb") as pdf:
                content = pdf.read().decode("latin-1")
        self.assertIn("Companywise Sales Report", content)
        self.assertIn("ItemA", content)
        self.assertIn("B1", content)
        self.assertIn("B2", content)
        # Item subtotal qty 5 / amount 50.00 and identical grand total.
        self.assertIn("50.00", content)
        self.assertIn("Grand Total", content)
        self.assertIn("/MediaBox [0 0 595 842]", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
