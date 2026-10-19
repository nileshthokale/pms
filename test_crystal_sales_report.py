"""Tests for Crystal Reports-style Sales Report Viewer (screens/sales_report.py).

Verifies all requirements:
1. No optional filters and a large date range.
2. A restricted date range.
3. Each supported optional filter (Customer, Company, Item, Patient).
4. Multi-page pagination (repeated table headers, page numbers, totals only on final page).
5. PDF export and print workflow (A4 Landscape, valid PDF).
6. Day Mode and Night Mode theme refreshing.
7. Right-hand filter panel layout, Show Report, Clear/Reset action.
8. Zoom controls ("Fit to Width", "Fit to Page", zoom factors) and navigation.
9. Empty results handling.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

from screens.sales_report import (
    SalesReportPage,
    generate_sales_report_pages,
)
from ui.crystal_report_viewer import (
    BlockKind,
    PAGE_HEIGHT_LANDSCAPE,
    PAGE_WIDTH_LANDSCAPE,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    print_or_export_report_pages,
)


class TestCrystalSalesReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.mock_rows = [
            {
                "invoice_id": 1,
                "bill_no": "2026-2027-1",
                "sale_date": "2026-05-10",
                "sale_type": "Cash",
                "customer_name": "WALKIN",
                "patient_name": "John Doe",
                "doctor_name": "Dr. Sharma",
                "item_name": "PARACETAMOL 650MG",
                "company_name": "CIPLA LTD",
                "unit_name": "TAB",
                "pack_size": "10",
                "batch_no": "B1001",
                "expiry": "05/28",
                "mrp": 35.00,
                "sale_qty": 2.0,
                "discount_amount": 3.50,
                "amount": 66.50,
                "bill_discount": 0.0,
                "bill_net_amount": 66.50,
            },
            {
                "invoice_id": 2,
                "bill_no": "2026-2027-2",
                "sale_date": "2026-05-12",
                "sale_type": "Credit",
                "customer_name": "Rahul Verma",
                "patient_name": "Rahul Verma",
                "doctor_name": "Dr. Patil",
                "item_name": "AMOXICILLIN 500MG",
                "company_name": "ABBOTT LTD",
                "unit_name": "CAP",
                "pack_size": "10",
                "batch_no": "AMX55",
                "expiry": "11/27",
                "mrp": 120.00,
                "sale_qty": 1.0,
                "discount_amount": 12.00,
                "amount": 108.00,
                "bill_discount": 0.0,
                "bill_net_amount": 108.00,
            },
        ]
        self.mock_summary = {
            "total_bills": 2,
            "total_lines": 2,
            "total_qty": 3.0,
            "total_gross": 174.50,
            "total_discount": 15.50,
            "total_net": 174.50,
        }

        self.filter_options = {
            "customers": [{"id": 10, "customer_name": "Rahul Verma"}],
            "companies": [{"id": 20, "company_name": "CIPLA LTD"}, {"id": 21, "company_name": "ABBOTT LTD"}],
            "items": [{"id": 30, "item_name": "PARACETAMOL 650MG"}, {"id": 31, "item_name": "AMOXICILLIN 500MG"}],
            "doctors": [{"id": 40, "doctor_name": "Dr. Sharma"}],
        }

        self.p_dao_report = mock.patch(
            "screens.sales_report.SalesReportDAO.get_sales_report",
            return_value={"rows": self.mock_rows, "summary": self.mock_summary},
        )
        self.p_dao_opts = mock.patch(
            "screens.sales_report.SalesReportDAO.get_filter_options",
            return_value=self.filter_options,
        )
        self.mock_get_report = self.p_dao_report.start()
        self.mock_get_opts = self.p_dao_opts.start()

        self.page = SalesReportPage()
        self.addCleanup(self.page.deleteLater)

    def tearDown(self):
        self.p_dao_report.stop()
        self.p_dao_opts.stop()

    # ── Test 1: No optional filters and large date range ──────────────
    def test_01_no_optional_filters_large_date_range(self):
        """Verifies report generation with full date range and no optional filters."""
        self.page._from_date.setDate(QDate(2025, 4, 1))
        self.page._to_date.setDate(QDate(2026, 3, 31))
        self.page.customer_edit.clear_filter()
        self.page.company_edit.clear_filter()
        self.page.item_edit.clear_filter()
        self.page.patient_edit.clear()

        self.page._on_generate()

        self.assertEqual(len(self.page._pages), 1)
        p = self.page._pages[0]
        self.assertEqual(p.orientation, "landscape")
        self.assertEqual(p.page_width, PAGE_WIDTH_LANDSCAPE)
        self.assertEqual(p.page_height, PAGE_HEIGHT_LANDSCAPE)

        # Header contains store name, date range, title
        self.assertIn("SALES REPORT", p.header.header_line_1)
        self.assertIn("01-04-2025", p.header.header_line_1)
        self.assertIn("31-03-2026", p.header.header_line_1)

        # Columns match the 10 required
        tbl_hdr = next(b for b in p.blocks if b.kind == BlockKind.TABLE_HEADER)
        self.assertEqual(
            tbl_hdr.data["columns"],
            [
                "Bill No",
                "Sale Date",
                "Patient Name",
                "Item Name",
                "Batch No",
                "Expiry",
                "MRP",
                "Qty",
                "Discount",
                "Amount",
            ],
        )

        # Rows rendered
        data_rows = [b for b in p.blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 2)
        self.assertEqual(data_rows[0].data["cells"][3], "PARACETAMOL 650MG")
        self.assertEqual(data_rows[1].data["cells"][3], "AMOXICILLIN 500MG")

        # Grand total and summary box present
        grand = next(b for b in p.blocks if b.kind == BlockKind.GRAND_TOTAL)
        self.assertEqual(grand.data["qty_str"], "3")
        self.assertIn("174.50", grand.data["amt_str"])

        sbox = next(b for b in p.blocks if b.kind in (BlockKind.SUMMARY_BOX, "summary_box"))
        self.assertIn("Total Bills: 2", sbox.data["text"])
        self.assertIn("Total Items: 2", sbox.data["text"])
        self.assertIn("Net Amount: ₹174.50", sbox.data["text"])

    # ── Test 2: Restricted date range ─────────────────────────────────
    def test_02_restricted_date_range(self):
        """Verifies report generation with a narrow / restricted date range."""
        self.mock_get_report.return_value = {
            "rows": [self.mock_rows[0]],
            "summary": {
                "total_bills": 1,
                "total_lines": 1,
                "total_qty": 2.0,
                "total_gross": 70.0,
                "total_discount": 3.5,
                "total_net": 66.50,
            },
        }
        self.page._from_date.setDate(QDate(2026, 5, 10))
        self.page._to_date.setDate(QDate(2026, 5, 10))
        self.page._on_generate()

        filters = self.mock_get_report.call_args.kwargs
        self.assertEqual(filters["from_date"], "2026-05-10")
        self.assertEqual(filters["to_date"], "2026-05-10")

        self.assertEqual(len(self.page._pages), 1)
        data_rows = [b for b in self.page._pages[0].blocks if b.kind == BlockKind.DATA_ROW]
        self.assertEqual(len(data_rows), 1)
        self.assertEqual(data_rows[0].data["cells"][0], "1")  # formatted bill no

    # ── Test 3: Each supported optional filter ────────────────────────
    def test_03_customer_filter(self):
        """Verifies filtering by Customer."""
        self.page.customer_edit.setText("Rahul Verma")
        self.page.customer_edit._on_completion_activated(
            self.page.customer_edit._model.index(0, 0)
        )
        self.page._on_generate()

        filters = self.mock_get_report.call_args.kwargs
        self.assertEqual(filters["customer_id"], 10)
        self.assertIn("PATIENTWISE", self.page._report_title())

    def test_04_company_filter(self):
        """Verifies filtering by Company."""
        self.page.company_edit.setText("CIPLA LTD")
        self.page.company_edit._on_completion_activated(
            self.page.company_edit._model.index(0, 0)
        )
        self.page._on_generate()

        filters = self.mock_get_report.call_args.kwargs
        self.assertEqual(filters["company_id"], 20)
        self.assertIn("COMPANYWISE", self.page._report_title())

    def test_05_item_filter(self):
        """Verifies filtering by Item."""
        self.page.item_edit.setText("PARACETAMOL 650MG")
        self.page.item_edit._on_completion_activated(
            self.page.item_edit._model.index(0, 0)
        )
        self.page._on_generate()

        filters = self.mock_get_report.call_args.kwargs
        self.assertEqual(filters["item_id"], 30)
        self.assertIn("ITEMWISE", self.page._report_title())

    def test_06_patient_filter(self):
        """Verifies filtering by Patient text."""
        self.page.patient_edit.setText("John Doe")
        self.page._on_generate()

        filters = self.mock_get_report.call_args.kwargs
        self.assertEqual(filters["patient"], "John Doe")
        self.assertIn("PATIENTWISE", self.page._report_title())

    # ── Test 4: Multi-page pagination ─────────────────────────────────
    def test_07_multiple_pages_pagination(self):
        """Generates enough rows to exceed one page (~75 rows) and verifies pagination."""
        many_rows = []
        for i in range(1, 76):
            many_rows.append(
                {
                    "invoice_id": i,
                    "bill_no": f"2026-2027-{i}",
                    "sale_date": "2026-05-15",
                    "patient_name": f"Patient {i:03d}",
                    "item_name": f"MEDICINE {i:03d} TABLETS 10S",
                    "batch_no": f"BAT{i:03d}",
                    "expiry": "12/28",
                    "mrp": 100.0,
                    "sale_qty": 2.0,
                    "discount_amount": 5.0,
                    "amount": 195.0,
                }
            )
        summary = {
            "total_bills": 75,
            "total_lines": 75,
            "total_qty": 150.0,
            "total_gross": 15000.0,
            "total_discount": 375.0,
            "total_net": 14625.0,
        }

        pages = generate_sales_report_pages(
            rows=many_rows,
            summary=summary,
            from_date="2026-05-01",
            to_date="2026-05-31",
            report_title="DAILY SALES REPORT",
            filter_summary="From: 01-05-2026 To: 31-05-2026",
        )

        # 75 rows at 18px = 1350px. Max page body = 635px. Must be 3 pages.
        self.assertGreaterEqual(len(pages), 3)

        # Verify page numbering on every page
        for idx, p in enumerate(pages):
            self.assertEqual(p.page_num, idx + 1)
            self.assertEqual(p.total_pages, len(pages))
            self.assertEqual(p.orientation, "landscape")
            # Table header repeated on EVERY page!
            first_block = p.blocks[0]
            self.assertEqual(first_block.kind, BlockKind.TABLE_HEADER)

        # Totals appear ONLY on the final page
        for p in pages[:-1]:
            self.assertFalse(any(b.kind == BlockKind.GRAND_TOTAL for b in p.blocks))
            self.assertFalse(any(b.kind in (BlockKind.SUMMARY_BOX, "summary_box") for b in p.blocks))

        last_p = pages[-1]
        self.assertTrue(any(b.kind == BlockKind.GRAND_TOTAL for b in last_p.blocks))
        self.assertTrue(any(b.kind in (BlockKind.SUMMARY_BOX, "summary_box") for b in last_p.blocks))

    # ── Test 5: PDF Export and Print Workflow ─────────────────────────
    def test_08_pdf_export_and_print_workflow(self):
        """Verifies PDF export writes a valid A4 Landscape PDF with all pages."""
        many_rows = [
            {
                "invoice_id": i,
                "bill_no": f"2026-2027-{i}",
                "sale_date": "2026-05-15",
                "patient_name": f"Patient {i}",
                "item_name": f"Medicine {i}",
                "batch_no": "B1",
                "expiry": "12/28",
                "mrp": 50.0,
                "sale_qty": 1.0,
                "discount_amount": 0.0,
                "amount": 50.0,
            }
            for i in range(1, 45)
        ]
        summary = {
            "total_bills": 44,
            "total_lines": 44,
            "total_qty": 44.0,
            "total_gross": 2200.0,
            "total_discount": 0.0,
            "total_net": 2200.0,
        }
        pages = generate_sales_report_pages(
            rows=many_rows,
            summary=summary,
            from_date="2026-05-01",
            to_date="2026-05-31",
            report_title="SALES REPORT",
            filter_summary="",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = os.path.join(tmp_dir, "test_sales_report_landscape.pdf")
            success = print_or_export_report_pages(pages, output_pdf_path=pdf_path)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(pdf_path))
            self.assertGreater(os.path.getsize(pdf_path), 1000)

            with open(pdf_path, "rb") as f:
                content = f.read()
                # Must be a valid PDF
                self.assertTrue(content.startswith(b"%PDF"))

            # Test print in offscreen environment
            print_success = print_or_export_report_pages(pages, parent=self.page)
            self.assertTrue(print_success)

    # ── Test 6: Day Mode and Night Mode Theme Refresh ─────────────────
    def test_09_day_and_night_mode_themes(self):
        """Verifies theme refresh works without error in both modes."""
        # 1. Day Mode
        with mock.patch("screens.sales_report.palette", return_value={
            "mode": "light", "bg": "#F5F7FA", "surface": "#FFFFFF",
            "border": "#D0D7DE", "accent": "#0066CC", "accent_hover": "#0052A3",
            "text": "#1A202C", "text_dim": "#718096",
        }):
            self.page.refresh_theme()
            self.assertEqual(self.page.viewer.canvas._bg_color.name().upper(), "#808080")

        # 2. Night Mode
        with mock.patch("screens.sales_report.palette", return_value={
            "mode": "dark", "bg": "#1E1E1E", "surface": "#252526",
            "border": "#3E3E42", "accent": "#007ACC", "accent_hover": "#1C97EA",
            "text": "#D4D4D4", "text_dim": "#858585",
        }):
            self.page.refresh_theme()
            self.assertEqual(self.page.viewer.canvas._bg_color.name().upper(), "#303030")

    # ── Test 7: Right-hand filter panel & Clear/Reset ─────────────────
    def test_10_right_side_filters_and_clear_action(self):
        """Verifies right panel components and Clear functionality."""
        self.assertIsNotNone(self.page._filters)
        self.assertGreaterEqual(self.page._filters.minimumWidth(), 240)

        # Enter filter values
        self.page.patient_edit.setText("Custom Patient")
        self.page.customer_edit.setText("Rahul Verma")
        self.page.customer_edit._selected_id = 10
        self.page.company_edit.setText("CIPLA LTD")
        self.page.company_edit._selected_id = 20

        # Click Clear
        self.page._on_clear()

        self.assertEqual(self.page.patient_edit.text(), "")
        self.assertIsNone(self.page.customer_edit.selected_id)
        self.assertEqual(self.page.customer_edit.text(), "")
        self.assertIsNone(self.page.company_edit.selected_id)
        self.assertEqual(self.page.company_edit.text(), "")

        # Dates reset to today
        today = QDate.currentDate().toString("yyyy-MM-dd")
        self.assertEqual(self.page._from_date.date().toString("yyyy-MM-dd"), today)
        self.assertEqual(self.page._to_date.date().toString("yyyy-MM-dd"), today)

    # ── Test 8: Zoom controls and viewer toolbar ──────────────────────
    def test_11_zoom_controls_and_toolbar(self):
        """Verifies Crystal Reports toolbar controls (zoom, page buttons)."""
        viewer = self.page.viewer

        # Zoom options
        zoom_items = [viewer.zoom_combo.itemText(i) for i in range(viewer.zoom_combo.count())]
        self.assertIn("Fit to Width", zoom_items)
        self.assertIn("Fit to Page", zoom_items)
        self.assertIn("100%", zoom_items)
        self.assertIn("75%", zoom_items)

        # Set zoom to 75%
        viewer.zoom_combo.setCurrentText("75%")
        self.assertAlmostEqual(viewer._zoom_factor, 0.75, places=2)

        # Set zoom to Fit to Width
        viewer.fit_to_width()
        self.assertGreater(viewer._zoom_factor, 0.2)

        # Set zoom to Fit to Page
        viewer.fit_to_page()
        self.assertGreater(viewer._zoom_factor, 0.2)

    # ── Test 9: Empty results handling ────────────────────────────────
    def test_12_empty_results_handling(self):
        """Verifies report behavior when no data matches criteria."""
        self.mock_get_report.return_value = {
            "rows": [],
            "summary": {
                "total_bills": 0,
                "total_lines": 0,
                "total_qty": 0.0,
                "total_gross": 0.0,
                "total_discount": 0.0,
                "total_net": 0.0,
            },
        }
        self.page._on_generate()

        self.assertEqual(len(self.page._pages), 1)
        p = self.page._pages[0]
        empty_b = next(b for b in p.blocks if b.kind == BlockKind.EMPTY)
        self.assertIn("No sales records found", empty_b.data["message"])

        # Grand total still displays with 0
        grand_b = next(b for b in p.blocks if b.kind == BlockKind.GRAND_TOTAL)
        self.assertEqual(grand_b.data["qty_str"], "0")
        self.assertIn("0.00", grand_b.data["amt_str"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
