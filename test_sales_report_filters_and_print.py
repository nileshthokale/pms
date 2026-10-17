"""Acceptance tests for the compact, FY-bounded Sales Report controls."""

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.document_printing import generate_daily_sales_report_pdf

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


class TestDailySalesReportPdf(unittest.TestCase):
    def _fixture_rows(self):
        # Two bills on one date: the first carries two item lines so the
        # Bill Total row has something to total.
        return [
            {"invoice_id": 1, "bill_no": "2026-2027-1", "sale_date": "2026-09-18",
             "customer_name": "WALKIN", "item_name": "L-CIN 250",
             "company_name": "C", "batch_no": "JB02668", "expiry": "12/27",
             "mrp": 51.40, "sale_qty": 5, "discount_amount": 0,
             "amount": 257.00, "bill_discount": 0, "bill_net_amount": 457.00},
            {"invoice_id": 1, "bill_no": "2026-2027-1", "sale_date": "2026-09-18",
             "customer_name": "WALKIN", "item_name": "EFEREM SP",
             "company_name": "C", "batch_no": "CGT251865A", "expiry": "12/27",
             "mrp": 20.00, "sale_qty": 10, "discount_amount": 10.00,
             "amount": 200.00, "bill_discount": 0, "bill_net_amount": 457.00},
            {"invoice_id": 2, "bill_no": "2026-2027-2", "sale_date": "2026-09-18",
             "customer_name": "WALKIN", "patient_name": "Alice", "item_name": "FOLITRAX 10",
             "company_name": "C", "batch_no": "AT-130725", "expiry": "12/27",
             "mrp": 70.98, "sale_qty": 2, "discount_amount": 0,
             "amount": 141.96, "bill_discount": 0, "bill_net_amount": 141.96},
        ]

    def _fixture_summary(self):
        return {"total_bills": 2, "total_lines": 3, "total_qty": 17,
                "total_gross": 608.96, "total_discount": 10.00, "total_net": 598.96}

    def _render(self, rows, summary, directory, name="sales.pdf"):
        path = generate_daily_sales_report_pdf(
            rows, summary, "2026-2027", "Financial year: 2026-2027",
            os.path.join(directory, name),
        )
        with open(path, "rb") as pdf:
            return pdf.read().decode("latin-1")

    def test_daily_report_matches_reference_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            content = self._render(self._fixture_rows(), self._fixture_summary(), directory)
        # Portrait A4, store header and daily title.
        self.assertIn("/MediaBox [0 0 595 842]", content)
        self.assertIn("SHREE SAMARTH MEDICAL AND GEN STORE", content)
        self.assertIn("GHORPADE HOSPITAL", content)
        self.assertIn("DAILY SALES REPORT", content)
        self.assertNotIn("Billwise", content)
        self.assertNotIn("Companywise", content)
        self.assertIn("From : 18-09-2026", content)
        # Billwise table columns in reference order.
        heads = ["SrNo", "Item Name", "Batch No", "MRP", "Qty", "Discount", "Amount"]
        for head in heads:
            self.assertIn(f"({head})", content)
        positions = [content.index(f"({head})") for head in heads]
        self.assertEqual(positions, sorted(positions))
        # Each bill appears once as its own section with actual bill data.
        self.assertEqual(content.count("Bill No: 2026-2027-1"), 1)
        self.assertEqual(content.count("Bill No: 2026-2027-2"), 1)
        # Patient name when present, WALKIN fallback otherwise; the customer
        # name is no longer printed.
        self.assertIn("Patient: WALKIN", content)
        self.assertIn("Patient: Alice", content)
        self.assertNotIn("Customer:", content)
        self.assertIn("(L-CIN 250)", content)
        self.assertIn("(51.40)", content)
        self.assertIn("(257.00)", content)
        self.assertIn("(JB02668)", content)
        # One Bill Total per bill plus the overall Grand Total at the right.
        self.assertEqual(content.count("(Bill Total)"), 2)
        self.assertIn("(Grand Total: 598.96)", content)
        self.assertIn("457.00", content)
        self.assertIn("141.96", content)
        self.assertIn("Page 1 of 1", content)

    def test_daily_report_paginates_and_handles_empty(self):
        rows = [{
            "invoice_id": number, "bill_no": f"2026-2027-{number}",
            "sale_date": "2026-09-18", "customer_name": "WALKIN",
            "item_name": f"ITEM-{number:03d}", "company_name": "C",
            "batch_no": "B1", "expiry": "12/27", "mrp": 10,
            "sale_qty": 1, "discount_amount": 0, "amount": 10,
            "bill_discount": 0, "bill_net_amount": 10,
        } for number in range(1, 61)]
        summary = {"total_bills": 60, "total_lines": 60, "total_qty": 60,
                   "total_gross": 600, "total_discount": 0, "total_net": 600}
        with tempfile.TemporaryDirectory() as directory:
            content = self._render(rows, summary, directory)
            self.assertRegex(content, r"Page 2 of \d+")
            self.assertGreaterEqual(content.count("(SrNo)"), 2)
            self.assertIn("600.00", content)
            empty = self._render(
                [], {"total_bills": 0, "total_lines": 0, "total_qty": 0,
                     "total_gross": 0, "total_discount": 0, "total_net": 0},
                directory, name="empty.pdf")
            self.assertIn("DAILY SALES REPORT", empty)
            self.assertIn("No records found", empty)
            self.assertIn("(Grand Total: 0.00)", empty)


@unittest.skipUnless(HAS_QT, "PySide6 is required for daily report screen tests")
class TestDailySalesReportScreen(unittest.TestCase):
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

    def test_single_unified_report_without_mode_radios(self):
        self.assertFalse(hasattr(self.page, "item_wise_radio"))
        self.assertFalse(hasattr(self.page, "bill_wise_radio"))
        self.assertFalse(hasattr(self.page, "mode_group"))
        for name in ("customer_edit", "company_edit", "item_edit", "patient_edit",
                     "_from_date", "_to_date"):
            self.assertTrue(hasattr(self.page, name), name)

    def test_filter_toolbar_fits_the_window_in_two_clean_rows(self):
        """Layout regression: one row demanded ~2041px, wider than any window.

        The old toolbar put six filters and four buttons on a single line,
        which could never fit inside the app's 1024px minimum window — the
        controls were squeezed against, and on narrow screens over, each
        other.  The toolbar now stays well below the window minimum, keeps
        a real gap between neighbours, and lays the action buttons on a
        second row of their own.
        """
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QDateEdit, QLabel, QLineEdit, QPushButton

        page = self.page
        self.assertLessEqual(
            page._filters.minimumSizeHint().width(), 1300,
            "the filter toolbar must not demand a window wider than the app allows",
        )

        page.resize(1366, 700)
        page.show()
        self.app.processEvents()
        filters = page._filters

        def top_left(widget):
            return widget.mapTo(filters, QPoint(0, 0))

        controls = list(filters.findChildren(QLabel))
        controls += [w for w in filters.findChildren(QLineEdit)
                     if not isinstance(w.parent(), QDateEdit)]
        controls += list(filters.findChildren(QDateEdit))
        controls += list(filters.findChildren(QPushButton))

        placed = []
        for widget in controls:
            pos = top_left(widget)
            placed.append((pos.x(), pos.y(), widget.width(), widget.height(),
                           widget))

        # No control may overlap another.
        for index in range(len(placed)):
            ax, ay, aw, ah, a_widget = placed[index]
            for other in placed[index + 1:]:
                bx, by, bw, bh, b_widget = other
                self.assertFalse(
                    ax < bx + bw and bx < ax + aw
                    and ay < by + bh and by < ay + ah,
                    f"{a_widget.text()!r} overlaps {b_widget.text()!r}",
                )

        # Visual neighbours keep a readable gap.
        rows: dict[int, list] = {}
        for rect in placed:
            rows.setdefault(rect[1] + rect[3] // 2, []).append(rect)
        for row in rows.values():
            ordered = sorted(row)
            for previous, following in zip(ordered, ordered[1:]):
                gap = following[0] - (previous[0] + previous[2])
                self.assertGreaterEqual(
                    gap, 4,
                    f"no gap between {previous[4].text()!r} "
                    f"and {following[4].text()!r}",
                )

        # A label must never be narrower than its own text.
        for label in filters.findChildren(QLabel):
            self.assertGreaterEqual(
                label.width(), label.sizeHint().width(),
                f"label {label.text()!r} is clipped",
            )

        # The action buttons sit on the second row, below the data filters.
        customer_label = next(
            w for w in filters.findChildren(QLabel) if w.text() == "Customer")
        customer_y = top_left(customer_label).y()
        buttons = {w.text(): w for w in filters.findChildren(QPushButton)}
        for text in ("Search", "Clear", "Refresh", "Print"):
            self.assertIn(text, buttons)
            self.assertGreater(
                top_left(buttons[text]).y(), customer_y,
                f"{text} should be on the second toolbar row",
            )
        page.hide()

    def test_date_range_defaults_to_today(self):
        from PySide6.QtCore import QDate

        today = QDate.currentDate().toString("yyyy-MM-dd")
        filters = self.page._current_filters()
        self.assertEqual(filters["from_date"], today)
        self.assertEqual(filters["to_date"], today)
        day, month = today.split("-")[2], today.split("-")[1]
        self.assertIn(f"From: {day}-{month}-{today.split('-')[0]}", self.page._filter_summary())

    def test_date_range_narrows_table_and_summary(self):
        from unittest import mock

        from PySide6.QtCore import QDate

        from screens import sales_report as sales_report_module
        day_rows = [
            {"bill_no": "1727", "sale_date": "2026-09-18",
             "customer_name": "Cust", "patient_name": "", "doctor_name": "",
             "item_name": "STAFLEX 3D CAPSULE", "batch_no": "26SFC02", "expiry": "10/27",
             "mrp": 683.0, "sale_qty": 10, "discount_amount": 0, "amount": 487.86},
        ]
        day_summary = {"total_bills": 1, "total_lines": 1, "total_qty": 10,
                       "total_gross": 487.86, "total_discount": 0, "total_net": 487.86}
        with mock.patch.object(
            sales_report_module.SalesReportDAO, "get_sales_report",
            return_value={"rows": day_rows, "summary": day_summary},
        ):
            self.page._from_date.setDate(QDate(2026, 9, 18))
            self.page._to_date.setDate(QDate(2026, 9, 18))
            filters = self.page._current_filters()
            self.assertEqual(filters["from_date"], "2026-09-18")
            self.assertEqual(filters["to_date"], "2026-09-18")
            self.assertIn("From: 18-09-2026 To: 18-09-2026", self.page._filter_summary())
            self.assertEqual(self.page._table.rowCount(), 1)

    def test_reversed_range_warns_without_querying(self):
        from unittest import mock

        from PySide6.QtCore import QDate

        from screens import sales_report as sales_report_module
        empty = {"rows": [], "summary": {"total_bills": 0, "total_lines": 0,
                 "total_qty": 0, "total_gross": 0, "total_discount": 0, "total_net": 0}}
        with mock.patch.object(
            sales_report_module.QMessageBox, "warning",
        ) as warn, mock.patch.object(
            sales_report_module.SalesReportDAO, "get_sales_report", return_value=empty,
        ) as gen:
            self.page._from_date.setDate(QDate(2026, 9, 19))
            self.page._to_date.setDate(QDate(2026, 9, 18))
            gen.reset_mock()
            warn.reset_mock()
            self.page._on_generate()
            warn.assert_called_once()
            self.assertIn("From Date", warn.call_args.args[2])
            gen.assert_not_called()

    def test_patient_flows_into_filters_summary_and_clear(self):
        self.page.patient_edit.setText("Alice")
        self.assertEqual(self.page._current_filters()["patient"], "Alice")
        self.assertIn("Patient: Alice", self.page._filter_summary())
        self.page._on_clear()
        self.assertIsNone(self.page._current_filters()["patient"])
        self.assertEqual(self.page.patient_edit.text(), "")

    def test_clear_resets_dates_to_today(self):
        from PySide6.QtCore import QDate

        self.page._from_date.setDate(QDate(2026, 9, 18))
        self.page._to_date.setDate(QDate(2026, 9, 18))
        self.page._on_clear()
        today = QDate.currentDate().toString("yyyy-MM-dd")
        self.assertEqual(self.page._from_date.date().toString("yyyy-MM-dd"), today)
        self.assertEqual(self.page._to_date.date().toString("yyyy-MM-dd"), today)

    def test_print_generates_daily_report(self):
        from unittest import mock

        from screens import sales_report as sales_report_module
        with mock.patch.object(
            sales_report_module.SalesReportDAO, "get_sales_report",
            return_value={"rows": [], "summary": {"total_bills": 0, "total_lines": 0,
                          "total_qty": 0, "total_gross": 0, "total_discount": 0, "total_net": 0}},
        ), mock.patch.object(
            sales_report_module.QFileDialog, "getSaveFileName",
            return_value=("/tmp/daily_sales_report.pdf", "PDF (*.pdf)"),
        ) as dialog, mock.patch.object(
            sales_report_module.QMessageBox, "information",
        ), mock.patch.object(
            sales_report_module.document_printing, "generate_daily_sales_report_pdf",
            return_value="/tmp/daily_sales_report.pdf",
        ) as gen:
            self.page._on_print()
            gen.assert_called_once()
            args, _kwargs = gen.call_args
            self.assertEqual(args[4], "/tmp/daily_sales_report.pdf")
            self.assertEqual(dialog.call_args.args[1], "Save Daily Sales Report PDF")

    def test_print_with_reversed_range_warns_and_aborts(self):
        from unittest import mock

        from PySide6.QtCore import QDate

        from screens import sales_report as sales_report_module
        with mock.patch.object(
            sales_report_module.QMessageBox, "warning",
        ) as warn, mock.patch.object(
            sales_report_module.QFileDialog, "getSaveFileName",
        ) as dialog, mock.patch.object(
            sales_report_module.document_printing, "generate_daily_sales_report_pdf",
        ) as gen:
            self.page._from_date.setDate(QDate(2026, 9, 19))
            self.page._to_date.setDate(QDate(2026, 9, 18))
            warn.reset_mock()
            self.page._on_print()
            warn.assert_called_once()
            dialog.assert_not_called()
            gen.assert_not_called()

    def test_enter_in_any_filter_refreshes_report(self):
        from unittest import mock

        from screens import sales_report as sales_report_module
        empty = {"rows": [], "summary": {"total_bills": 0, "total_lines": 0,
                 "total_qty": 0, "total_gross": 0, "total_discount": 0, "total_net": 0}}
        with mock.patch.object(
            sales_report_module.SalesReportDAO, "get_sales_report", return_value=empty,
        ) as gen:
            for edit in (self.page.customer_edit, self.page.company_edit,
                         self.page.item_edit, self.page.patient_edit):
                edit.setFocus()
                QTest.keyClick(edit, Qt.Key_Return)
            self.assertGreaterEqual(gen.call_count, 4)

    def test_table_merges_customer_and_patient_columns(self):
        from unittest import mock

        from screens import sales_report as sales_report_module
        heads = [self.page._table.horizontalHeaderItem(col).text()
                 for col in range(self.page._table.columnCount())]
        self.assertEqual(heads, ["Bill No", "Sale Date", "Patient Name", "Doctor",
                                 "Item Name", "Batch No", "Expiry", "MRP", "Qty",
                                 "Discount", "Amount"])
        rows = [
            {"bill_no": "B1", "sale_date": "2026-09-18", "customer_name": "WALKIN",
             "patient_name": "", "doctor_name": "", "item_name": "X",
             "batch_no": "B", "expiry": "", "mrp": 10, "sale_qty": 1,
             "discount_amount": 0, "amount": 10},
            {"bill_no": "B2", "sale_date": "2026-09-18", "customer_name": "WALKIN",
             "patient_name": "Alice", "doctor_name": "", "item_name": "Y",
             "batch_no": "B", "expiry": "", "mrp": 10, "sale_qty": 1,
             "discount_amount": 0, "amount": 10},
        ]
        summary = {"total_bills": 2, "total_lines": 2, "total_qty": 2,
                   "total_gross": 20, "total_discount": 0, "total_net": 20}
        with mock.patch.object(
            sales_report_module.SalesReportDAO, "get_sales_report",
            return_value={"rows": rows, "summary": summary},
        ):
            self.page._on_generate()
            self.assertEqual(self.page._table.item(0, 2).text(), "WALKIN")
            self.assertEqual(self.page._table.item(1, 2).text(), "Alice")

    def test_typing_item_then_search_filters_by_typed_text(self):
        from unittest import mock

        from screens import sales_report as sales_report_module
        empty = {"rows": [], "summary": {"total_bills": 0, "total_lines": 0,
                 "total_qty": 0, "total_gross": 0, "total_discount": 0, "total_net": 0}}
        options = {"customers": [], "items": [{"id": 7, "item_name": "PARA 650"}],
                   "companies": [], "doctors": []}
        with mock.patch(
            "screens.sales_report.SalesReportDAO.get_filter_options", return_value=options), \
            mock.patch.object(
                sales_report_module.SalesReportDAO, "get_sales_report", return_value=empty,
            ) as gen:
            self.page._load_filter_options()
            # Picking the suggestion with Enter searches at once.
            self.page.item_edit.setFocus()
            QTest.keyClicks(self.page.item_edit, "para")
            QTest.keyClick(self.page.item_edit, Qt.Key_Enter)
            self.assertEqual(self.page.item_edit.selected_id, 7)
            self.assertTrue(gen.called)
            self.assertEqual(gen.call_args.kwargs.get("item_id"), 7)
            # Typing the exact name without picking also filters on Search.
            gen.reset_mock()
            self.page.item_edit._on_text_edited("PARA 650")
            self.assertIsNone(self.page.item_edit.selected_id)
            self.page._on_generate()
            self.assertEqual(gen.call_args.kwargs.get("item_id"), 7)

    def test_exact_id_for_text_matches_case_insensitively(self):
        from ui.searchable_filter import SearchableFilterEdit

        edit = SearchableFilterEdit("All items")
        edit.set_options([{"id": 7, "item_name": "PARA 650"}], "id", "item_name")
        self.assertEqual(edit.exact_id_for_text("para 650"), 7)
        self.assertEqual(edit.exact_id_for_text("  PARA 650 "), 7)
        self.assertIsNone(edit.exact_id_for_text("para"))
        self.assertIsNone(edit.exact_id_for_text(""))
        self.assertIsNone(edit.exact_id_for_text(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
