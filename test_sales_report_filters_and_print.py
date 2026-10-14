"""Acceptance tests for the compact, FY-bounded Sales Report controls."""

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.document_printing import generate_billwise_sales_report_pdf, generate_sales_report_pdf

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
    def _fixture_rows(self):
        # Visual test fixture mirroring the reference screenshot (same date,
        # two bills, repeated bill amount per line of a bill).
        return [
            {"bill_no": "1727", "sale_date": "2026-09-18", "sale_type": "Cash",
             "item_name": "STAFLEX 3D CAPSULE", "mrp": 683.00, "sale_qty": 10,
             "amount": 487.86, "batch_no": "26SFC02", "expiry": "2027-10-31",
             "discount_amount": 0, "bill_net_amount": 854},
            {"bill_no": "1726", "sale_date": "2026-09-18", "sale_type": "Cash",
             "item_name": "LIGAMOVE TABLET", "mrp": 311.00, "sale_qty": 5,
             "amount": 155.50, "batch_no": "VHT18511", "expiry": "2027-08-31",
             "discount_amount": 0, "bill_net_amount": 548},
            {"bill_no": "1726", "sale_date": "2026-09-18", "sale_type": "Cash",
             "item_name": "PROTONIX DSR CAPSULE", "mrp": 120.00, "sale_qty": 10,
             "amount": 120.00, "batch_no": "C-26056", "expiry": "2028-06-30",
             "discount_amount": 0, "bill_net_amount": 548},
            {"bill_no": "1726", "sale_date": "2026-09-18", "sale_type": "Cash",
             "item_name": "MGMIX TABLET", "mrp": 285.00, "sale_qty": 5,
             "amount": 142.50, "batch_no": "NPT2029", "expiry": "2028-06-30",
             "discount_amount": 0, "bill_net_amount": 548},
            {"bill_no": "1726", "sale_date": "2026-09-18", "sale_type": "Cash",
             "item_name": "ENDORLAM SP TABLET", "mrp": 130.00, "sale_qty": 10,
             "amount": 130.00, "batch_no": "SGT-60437", "expiry": "2028-09-30",
             "discount_amount": 0, "bill_net_amount": 548},
        ]

    def _render(self, rows, summary, directory, name="sales.pdf",
                report_from="2026-09-18", report_to="2026-09-18"):
        path = generate_sales_report_pdf(
            rows, summary, "FY", "Financial year: FY",
            os.path.join(directory, name),
            report_from=report_from, report_to=report_to,
        )
        with open(path, "rb") as pdf:
            return pdf.read().decode("latin-1")

    def test_itemwise_matches_reference_layout(self):
        rows = self._fixture_rows()
        summary = {"total_bills": 2, "total_lines": 5, "total_qty": 40,
                   "total_gross": 1035.86, "total_discount": 0, "total_net": 1402}
        with tempfile.TemporaryDirectory() as directory:
            content = self._render(rows, summary, directory)
        # Portrait A4, monospaced black-on-white report.
        self.assertIn("/MediaBox [0 0 595 842]", content)
        self.assertIn("/Courier", content)
        # Header: store top-left, daily title with the dynamic report date.
        self.assertIn("SHREE SAMARTH MEDICAL AND GEN STORE", content)
        self.assertIn("GHORPADE HOSPITAL", content)
        self.assertIn("DAILY ITEMWISE SALES REPORT FOR DATE 18-09-2026", content)
        # Exact columns in reference order.
        heads = ["BillNo", "VhType", "ItemName", "MRP", "Qty", "Amount",
                 "BatchNo", "Expiry", "Disc.", "Bill Amt"]
        for head in heads:
            self.assertIn(f"({head})", content)
        positions = [content.index(f"({head})") for head in heads]
        self.assertEqual(positions, sorted(positions))
        # Stored values, reference formatting.
        self.assertIn("(1727)", content)
        self.assertIn("(Cash)", content)
        self.assertIn("(STAFLEX 3D CAPSULE)", content)
        self.assertIn("(683.00)", content)
        self.assertIn("(487.86)", content)
        self.assertIn("(26SFC02)", content)
        self.assertIn("(31/10/2027)", content)
        self.assertIn("(548)", content)
        self.assertIn("(854)", content)
        # Footer: generation timestamp bottom-left, total bottom-right.
        self.assertRegex(content, r"\(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}\)")
        self.assertIn("(Total: 1,035.86)", content)
        self.assertIn("Page 1 of 1", content)

    def test_duplicate_lines_merge_only_within_one_bill(self):
        rows = [
            {"bill_no": "1727", "sale_date": "2026-09-18", "sale_type": "Cash",
             "item_name": "DEF-Z", "mrp": 149.06, "sale_qty": 100,
             "amount": 14906.00, "batch_no": "ADT2T5007D", "expiry": "2027-10-31",
             "discount_amount": 0, "bill_net_amount": 21166.52},
            {"bill_no": "1727", "sale_date": "2026-09-18", "sale_type": "Cash",
             "item_name": "DEF-Z", "mrp": 149.06, "sale_qty": 42,
             "amount": 6260.52, "batch_no": "ADT2T5007D", "expiry": "2027-10-31",
             "discount_amount": 0, "bill_net_amount": 21166.52},
            {"bill_no": "1726", "sale_date": "2026-09-18", "sale_type": "Cash",
             "item_name": "DEF-Z", "mrp": 149.06, "sale_qty": 10,
             "amount": 1490.60, "batch_no": "ADT2T5007D", "expiry": "2027-10-31",
             "discount_amount": 0, "bill_net_amount": 1490.60},
        ]
        summary = {"total_bills": 2, "total_lines": 3, "total_qty": 152,
                   "total_gross": 22657.12, "total_discount": 0, "total_net": 22657.12}
        with tempfile.TemporaryDirectory() as directory:
            content = self._render(rows, summary, directory)
        # Same bill + item + batch + MRP merges once (qty 142, 21,166.52);
        # the other bill's identical batch stays a separate row.
        self.assertEqual(content.count("(ADT2T5007D)"), 2)
        self.assertIn("(142)", content)
        self.assertIn("(21,166.52)", content)
        self.assertIn("(Total: 22,657.12)", content)

    def test_range_title_pagination_empty_and_long_names(self):
        rows = [{
            "bill_no": f"{1700 + number}",
            "sale_date": "2025-04-05" if number % 2 == 0 else "2026-03-20",
            "sale_type": "Cash",
            "item_name": f"ITEM-{number:03d}-WITH-A-VERY-LONG-NAME-THAT-MUST-NOT-BREAK-COLUMNS",
            "company_name": "TestCompany", "mrp": 10, "sale_qty": 1,
            "discount_amount": 0, "amount": 10, "batch_no": "B1", "expiry": "12/27",
            "bill_net_amount": 10,
        } for number in range(70)]
        summary = {"total_bills": 70, "total_lines": 70, "total_qty": 70,
                   "total_gross": 700, "total_discount": 0, "total_net": 700}
        with tempfile.TemporaryDirectory() as directory:
            content = self._render(rows, summary, directory,
                                   report_from="2025-04-01", report_to="2026-03-31")
            self.assertIn("DAILY ITEMWISE SALES REPORT FOR DATE 01-04-2025 TO 31-03-2026", content)
            self.assertIn("Page 1 of 2", content)
            self.assertIn("Page 2 of 2", content)
            self.assertGreaterEqual(content.count("(BillNo)"), 2)
            self.assertIn("...", content)
            self.assertNotIn("ITEM-000-WITH-A-VERY-LONG-NAME-THAT-MUST-NOT-BREAK-COLUMNS", content)
            self.assertIn("(Total: 700.00)", content)
            empty = self._render([], {"total_bills": 0, "total_lines": 0, "total_qty": 0,
                                      "total_gross": 0, "total_discount": 0, "total_net": 0},
                                 directory, name="empty.pdf", report_from=None, report_to=None)
            self.assertIn("DAILY ITEMWISE SALES REPORT", empty)
            self.assertIn("No sales found", empty)
            self.assertIn("(Total: 0.00)", empty)


class TestBillwiseReportPdf(unittest.TestCase):
    def test_bills_stay_separate_with_bill_and_grand_totals(self):
        rows = [
            {"invoice_id": 1, "bill_no": "CS-0001", "sale_date": "2017-06-15", "customer_name": "CustA",
             "item_name": "ItemA", "company_name": "TestCompany", "batch_no": "B1",
             "mrp": 10, "sale_qty": 2, "discount_amount": 1, "amount": 19},
            {"invoice_id": 1, "bill_no": "CS-0001", "sale_date": "2017-06-15", "customer_name": "CustA",
             "item_name": "ItemB", "company_name": "TestCompany", "batch_no": "B2",
             "mrp": 20, "sale_qty": 1, "discount_amount": 0, "amount": 20},
            {"invoice_id": 2, "bill_no": "CS-0002", "sale_date": "2017-06-16", "customer_name": "CustB",
             "item_name": "ItemA", "company_name": "TestCompany", "batch_no": "B1",
             "mrp": 10, "sale_qty": 3, "discount_amount": 0, "amount": 30},
        ]
        summary = {"total_bills": 2, "total_lines": 3, "total_qty": 6,
                   "total_gross": 70, "total_discount": 1, "total_net": 69}
        with tempfile.TemporaryDirectory() as directory:
            path = generate_billwise_sales_report_pdf(
                rows, summary, "2017-2018", "Financial year: 2017-2018 | Company: TestCompany | Mode: Bill Wise",
                os.path.join(directory, "sales.pdf"),
            )
            with open(path, "rb") as pdf:
                content = pdf.read().decode("latin-1")
        # Portrait A4, billwise title and header.
        self.assertIn("/MediaBox [0 0 595 842]", content)
        self.assertIn("Billwise Sales Report", content)
        self.assertIn("Company : TestCompany", content)
        for head in ("SrNo", "Item Name", "Batch No", "MRP", "Qty", "Discount", "Amount"):
            self.assertIn(head, content)
        # Each bill keeps its own section and bill total; nothing is combined
        # across bills.
        self.assertEqual(content.count("Bill No: CS-0001"), 1)
        self.assertEqual(content.count("Bill No: CS-0002"), 1)
        self.assertEqual(content.count("Bill Total"), 2)
        self.assertIn("CustA", content)
        self.assertIn("CustB", content)
        # Bill 1: qty 3 / disc 1.00 / amt 39.00; grand: qty 6 / disc 1.00 / amt 69.00.
        self.assertIn("39.00", content)
        self.assertIn("Grand Total", content)
        self.assertIn("69.00", content)
        self.assertIn("Page 1 of 1", content)

    def test_empty_billwise_report_prints_grand_total(self):
        summary = {"total_bills": 0, "total_lines": 0, "total_qty": 0,
                   "total_gross": 0, "total_discount": 0, "total_net": 0}
        with tempfile.TemporaryDirectory() as directory:
            path = generate_billwise_sales_report_pdf(
                [], summary, "2017-2018", "Financial year: 2017-2018 | Mode: Bill Wise",
                os.path.join(directory, "sales.pdf"),
            )
            with open(path, "rb") as pdf:
                content = pdf.read().decode("latin-1")
        self.assertIn("Billwise Sales Report", content)
        self.assertIn("No sales found", content)
        self.assertIn("Grand Total", content)
        self.assertIn("/MediaBox [0 0 595 842]", content)


@unittest.skipUnless(HAS_QT, "PySide6 is required for report mode tests")
class TestSalesReportMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from unittest import mock

        from screens.sales_report import SalesReportPage
        empty_report = {
            "rows": [],
            "summary": {"total_bills": 0, "total_lines": 0, "total_qty": 0,
                        "total_gross": 0, "total_discount": 0, "total_net": 0},
        }
        options = {"customers": [], "items": [], "companies": [], "doctors": []}
        get_filters = mock.patch(
            "screens.sales_report.SalesReportDAO.get_filter_options", return_value=options)
        get_report = mock.patch(
            "screens.sales_report.SalesReportDAO.get_sales_report", return_value=empty_report)
        get_filters.start()
        get_report.start()
        self.addCleanup(get_filters.stop)
        self.addCleanup(get_report.stop)
        self.page = SalesReportPage()
        self.addCleanup(self.page.deleteLater)

    def test_item_wise_is_default_and_replaces_bill_patient_fields(self):
        self.assertTrue(self.page.item_wise_radio.isChecked())
        self.assertFalse(self.page.bill_wise_radio.isChecked())
        self.assertFalse(hasattr(self.page, "bill_edit"))
        self.assertFalse(hasattr(self.page, "patient_edit"))

    def test_modes_are_exclusive(self):
        self.page.bill_wise_radio.click()
        self.assertTrue(self.page.bill_wise_radio.isChecked())
        self.assertFalse(self.page.item_wise_radio.isChecked())
        self.page.item_wise_radio.click()
        self.assertTrue(self.page.item_wise_radio.isChecked())
        self.assertFalse(self.page.bill_wise_radio.isChecked())

    def test_filters_keep_customer_company_item_only(self):
        self.assertEqual(
            set(self.page._current_filters()),
            {"from_date", "to_date", "customer_id", "item_id", "company_id"},
        )
        self.assertIn("Mode: Item Wise", self.page._filter_summary())

    def test_print_uses_selected_mode(self):
        from unittest import mock

        from screens import sales_report as sales_report_module
        with mock.patch.object(
            sales_report_module.SalesReportDAO, "get_sales_report",
            return_value={"rows": [], "summary": {"total_bills": 0, "total_lines": 0,
                          "total_qty": 0, "total_gross": 0, "total_discount": 0, "total_net": 0}},
        ), mock.patch.object(
            sales_report_module.QFileDialog, "getSaveFileName",
            return_value=("/tmp/sales_report.pdf", "PDF (*.pdf)"),
        ), mock.patch.object(
            sales_report_module.QMessageBox, "information",
        ), mock.patch.object(
            sales_report_module.document_printing, "generate_sales_report_pdf",
            return_value="/tmp/sales_report.pdf",
        ) as item_gen, mock.patch.object(
            sales_report_module.document_printing, "generate_billwise_sales_report_pdf",
            return_value="/tmp/sales_report.pdf",
        ) as bill_gen:
            self.page.item_wise_radio.setChecked(True)
            self.page._on_print()
            item_gen.assert_called_once()
            bill_gen.assert_not_called()
            # The selected FY bounds travel with the itemwise print-out so the
            # daily title always shows the report date, never a hardcode.
            self.assertIn("report_from", item_gen.call_args.kwargs)
            self.assertIn("report_to", item_gen.call_args.kwargs)
            item_gen.reset_mock()
            bill_gen.reset_mock()
            self.page.bill_wise_radio.setChecked(True)
            self.page._on_print()
            bill_gen.assert_called_once()
            item_gen.assert_not_called()

    def test_enter_in_item_filter_refreshes_report(self):
        from unittest import mock

        from screens import sales_report as sales_report_module
        empty = {"rows": [], "summary": {"total_bills": 0, "total_lines": 0,
                 "total_qty": 0, "total_gross": 0, "total_discount": 0, "total_net": 0}}
        with mock.patch.object(
            sales_report_module.SalesReportDAO, "get_sales_report", return_value=empty,
        ) as gen:
            self.page.item_edit.setFocus()
            QTest.keyClick(self.page.item_edit, Qt.Key_Return)
            self.assertTrue(gen.called)

    def test_date_filter_narrows_table_and_print_to_one_day(self):
        from unittest import mock

        from PySide6.QtCore import QDate

        from screens import sales_report as sales_report_module
        day_rows = [
            {"bill_no": "1727", "sale_date": "2026-09-18", "sale_type": "Cash",
             "customer_name": "Cust", "patient_name": "", "doctor_name": "",
             "item_name": "STAFLEX 3D CAPSULE", "company_name": "C",
             "batch_no": "26SFC02", "expiry": "2027-10-31", "mrp": 683.0,
             "sale_qty": 10, "discount_amount": 0, "amount": 487.86,
             "invoice_id": 1, "bill_discount": 0, "bill_net_amount": 854},
        ]
        day_summary = {"total_bills": 1, "total_lines": 1, "total_qty": 10,
                       "total_gross": 487.86, "total_discount": 0, "total_net": 854}
        with mock.patch.object(
            sales_report_module.SalesReportDAO, "get_sales_report",
            return_value={"rows": day_rows, "summary": day_summary},
        ) as gen:
            self.assertFalse(self.page._date_check.isChecked())
            self.assertFalse(self.page._date_edit.isEnabled())
            self.page._date_edit.setDate(QDate(2026, 9, 18))
            self.page._date_check.setChecked(True)
            filters = self.page._current_filters()
            self.assertEqual(filters["from_date"], "2026-09-18")
            self.assertEqual(filters["to_date"], "2026-09-18")
            self.assertIn("Date: 18-09-2026", self.page._filter_summary())
            self.assertEqual(self.page._table.rowCount(), 1)
            with mock.patch.object(
                sales_report_module.QFileDialog, "getSaveFileName",
                return_value=("/tmp/sales_report.pdf", "PDF (*.pdf)"),
            ), mock.patch.object(
                sales_report_module.QMessageBox, "information",
            ), mock.patch.object(
                sales_report_module.document_printing, "generate_sales_report_pdf",
                return_value="/tmp/sales_report.pdf",
            ) as item_gen:
                self.page.item_wise_radio.setChecked(True)
                self.page._on_print()
                item_gen.assert_called_once()
                self.assertEqual(item_gen.call_args.kwargs.get("report_from"), "2026-09-18")
                self.assertEqual(item_gen.call_args.kwargs.get("report_to"), "2026-09-18")
            gen.reset_mock()
            self.page._on_clear()
            self.assertFalse(self.page._date_check.isChecked())
            self.assertIsNone(self.page._selected_day())
            self.assertFalse(self.page._date_edit.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
