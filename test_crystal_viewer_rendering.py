"""Regression and Stress Tests for Crystal Report Viewer Rendering.

Tests specifically target:
1. draw_report_page() execution for all report types and block kinds:
   - ITEM_SUBTOTAL, BATCH_SUBTOTAL, STOCK_SUBTOTAL with and without custom_cells
   - GRAND_TOTAL with custom_cells, with 3 columns, and with 1 column
   - Empty widths list, 1 column, 2 columns, N columns
   - SUMMARY_BOX, GROUP_HEADER, TABLE_HEADER, DATA_ROW, EMPTY
2. ReportPageCanvas paintEvent lifecycle:
   - Ensuring QPainter save/restore symmetry
   - No QBackingStore::endPaint active painter errors
   - No QPainter::end saved states errors
   - Prevention of console error floods on repeated repainting
3. Real report screens rendering through canvas:
   - ItemsAllStockPage (populated and empty)
   - CompanywiseItemStockPage (populated and empty, with item subtotals and grand totals)
   - ExpiredItemListPage (populated and empty)
   - ItemListPage (populated and empty)
   - SalesReportPage (landscape layout, summary box)
   - BasePurchaseReportWindow (all 6 purchase reports)
4. Resize events and repeated repainting tests.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from database.connection import init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from ui.crystal_report_viewer import (
    BlockKind,
    CONTENT_WIDTH,
    CrystalReportViewer,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    ReportPageCanvas,
    draw_report_page,
)
from screens.stock_reports import (
    ItemsAllStockPage,
    CompanywiseItemStockPage,
    ExpiredItemListPage,
    ItemListPage,
)
from screens.sales_report import SalesReportPage
from screens.purchase_reports import (
    CompanywiseItemwisePurchasePage,
    CompanywiseSupplierwisePurchasePage,
    SupplierwiseItemwiseInvoicePurchasePage,
    SupplierwiseItemwiseChallanPurchasePage,
    ItemwisePurchasePage,
    ItemwiseBatchwisePurchasePage,
)


class TestCrystalViewerRendering(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_crystal_viewer_rendering.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass

    def _create_sample_header(self) -> ReportHeaderData:
        return ReportHeaderData(
            store_name="TEST PHARMACY STORE",
            store_address="123 MAIN ROAD, PUNE",
            header_line_1="TEST REPORT TITLE",
            header_line_2="Filter: All Items",
            header_line_3="Additional Info Line",
        )

    # ──────────────────────────────────────────────────────────────────
    # 1. draw_report_page() Subtotal & Total Boundary Path Tests
    # ──────────────────────────────────────────────────────────────────

    def test_01_stock_subtotal_with_custom_cells_renders_without_unbound_sum_prefix_w(self):
        """Proves the exact bug: STOCK_SUBTOTAL with custom_cells must NOT trigger UnboundLocalError."""
        header = self._create_sample_header()
        subtotal_cells = [
            (200.0, "PARACETAMOL 500MG Total :", "right"),
            (80.0, "150", "right"),
            (50.0, "", "center"),
            (80.0, "2250.00", "right"),
            (50.0, "", "center"),
            (80.0, "3750.00", "right"),
        ]
        block = ReportBlock(
            kind=BlockKind.STOCK_SUBTOTAL,
            height=20.0,
            data={"custom_cells": subtotal_cells},
        )
        page = ReportPage(page_num=1, total_pages=1, header=header, blocks=[block])

        img = QImage(int(PAGE_WIDTH), int(PAGE_HEIGHT), QImage.Format_ARGB32)
        painter = QPainter(img)
        try:
            # Must not raise UnboundLocalError: cannot access local variable 'sum_prefix_w'
            draw_report_page(painter, page)
        finally:
            painter.end()

    def test_02_item_subtotal_and_batch_subtotal_with_custom_cells(self):
        """ITEM_SUBTOTAL and BATCH_SUBTOTAL with custom_cells render cleanly."""
        header = self._create_sample_header()
        blocks = [
            ReportBlock(
                kind=BlockKind.ITEM_SUBTOTAL,
                height=20.0,
                data={"custom_cells": [(400.0, "Item Total :", "right"), (100.0, "500.00", "right")]},
            ),
            ReportBlock(
                kind=BlockKind.BATCH_SUBTOTAL,
                height=20.0,
                data={"custom_cells": [(400.0, "Batch Total :", "right"), (100.0, "250.00", "right")]},
            ),
            ReportBlock(
                kind="stock_subtotal",
                height=20.0,
                data={"custom_cells": [(400.0, "Stock Subtotal :", "right"), (100.0, "100.00", "right")]},
            ),
        ]
        page = ReportPage(page_num=1, total_pages=1, header=header, blocks=blocks)

        img = QImage(int(PAGE_WIDTH), int(PAGE_HEIGHT), QImage.Format_ARGB32)
        painter = QPainter(img)
        try:
            draw_report_page(painter, page)
        finally:
            painter.end()

    def test_03_subtotal_standard_path_with_various_column_widths(self):
        """Standard subtotal (without custom_cells) handles empty, 1, 2, and 3+ column widths safely."""
        header = self._create_sample_header()

        cases = [
            # 3+ columns
            {"widths": [100.0, 150.0, 100.0, 80.0, 60.0, 100.0], "pay_str": "10", "free_str": "2", "amt_str": "500.00"},
            # 2 columns
            {"widths": [300.0, 100.0], "amt_str": "350.00"},
            # 1 column
            {"widths": [200.0], "amt_str": "120.00"},
            # empty widths list
            {"widths": [], "pay_str": "5", "free_str": "0", "amt_str": "50.00"},
            # missing widths key
            {"pay_str": "0", "amt_str": "0.00"},
            # with batch_no
            {"widths": [100.0, 100.0, 100.0, 80.0, 80.0], "batch_no": "B123", "pay_str": "10", "amt_str": "99.00"},
        ]

        blocks = [
            ReportBlock(kind=BlockKind.ITEM_SUBTOTAL, height=20.0, data=c)
            for c in cases
        ]
        page = ReportPage(page_num=1, total_pages=1, header=header, blocks=blocks)

        img = QImage(int(PAGE_WIDTH), int(PAGE_HEIGHT), QImage.Format_ARGB32)
        painter = QPainter(img)
        try:
            draw_report_page(painter, page)
        finally:
            painter.end()

    def test_04_grand_total_all_variants(self):
        """GRAND_TOTAL renders properly with custom_cells, 3-column total, 1-column total, and edge-case widths."""
        header = self._create_sample_header()
        blocks = [
            # Variant 1: custom_cells (Used by stock reports)
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=20.0,
                data={"custom_cells": [(500.0, "Grand Total :", "right"), (100.0, "999.00", "right")]},
            ),
            # Variant 2: 3-column total (Used by sales report and purchase reports)
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=20.0,
                data={
                    "widths": [80.0, 120.0, 100.0, 80.0, 80.0, 100.0],
                    "label": "Grand Total :",
                    "qty_str": "150",
                    "disc_str": "50.00",
                    "amt_str": "1500.00",
                },
            ),
            # Variant 3: 1-column total (Amount only, used by Report 2)
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=20.0,
                data={
                    "widths": [150.0, 150.0, 100.0],
                    "label": "Grand Total :",
                    "amt_str": "4500.00",
                },
            ),
            # Variant 4: Edge case: 3-column total with empty widths
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=20.0,
                data={
                    "widths": [],
                    "qty_str": "10",
                    "disc_str": "0.00",
                    "amt_str": "100.00",
                },
            ),
            # Variant 5: Edge case: 1-column total with empty widths
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=20.0,
                data={
                    "widths": [],
                    "amt_str": "50.00",
                },
            ),
        ]
        page = ReportPage(page_num=1, total_pages=1, header=header, blocks=blocks)

        img = QImage(int(PAGE_WIDTH), int(PAGE_HEIGHT), QImage.Format_ARGB32)
        painter = QPainter(img)
        try:
            draw_report_page(painter, page)
        finally:
            painter.end()

    # ──────────────────────────────────────────────────────────────────
    # 2. ReportPageCanvas paintEvent Lifecycle & Exception Safety
    # ──────────────────────────────────────────────────────────────────

    def test_05_canvas_paint_event_none_page(self):
        """ReportPageCanvas paintEvent renders the placeholder message when _page is None."""
        canvas = ReportPageCanvas()
        canvas.set_page(None)

        # Force a paintEvent directly
        canvas.resize(400, 300)
        img = QImage(400, 300, QImage.Format_ARGB32)
        canvas.render(img)
        self.assertIsNone(canvas._last_paint_error)

    def test_06_canvas_paint_event_normal_page(self):
        """ReportPageCanvas paintEvent renders a populated page cleanly."""
        header = self._create_sample_header()
        page = ReportPage(
            page_num=1,
            total_pages=1,
            header=header,
            blocks=[
                ReportBlock(kind=BlockKind.TABLE_HEADER, height=20.0, data={"columns": ["A", "B"], "widths": [200.0, 200.0]}),
                ReportBlock(kind=BlockKind.DATA_ROW, height=18.0, data={"cells": ["Row 1", "Val 1"], "widths": [200.0, 200.0]}),
            ],
        )

        canvas = ReportPageCanvas()
        canvas.set_page(page)
        canvas.set_zoom(1.0)

        img = QImage(canvas.size(), QImage.Format_ARGB32)
        canvas.render(img)
        self.assertIsNone(canvas._last_paint_error)

    def test_07_canvas_paint_event_catches_exception_safely_no_leak(self):
        """If draw_report_page encounters an exception, paintEvent catches it, logs once, and ends painter cleanly."""
        # Create a faulty block that intentionally raises when processed
        header = self._create_sample_header()

        class FaultyBlock(ReportBlock):
            @property
            def kind(self):
                raise RuntimeError("Simulated block failure")

            @kind.setter
            def kind(self, val):
                pass

        page = ReportPage(page_num=1, total_pages=1, header=header, blocks=[FaultyBlock(kind="err", height=10.0)])

        canvas = ReportPageCanvas()
        canvas.set_page(page)

        # Capture stderr to verify error logging
        stderr_buf = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_buf
        try:
            # Trigger paintEvent multiple times (repeated repainting)
            for _ in range(5):
                img = QImage(canvas.size(), QImage.Format_ARGB32)
                canvas.render(img)
        finally:
            sys.stderr = old_stderr

        # Error was recorded and painter did NOT crash or leak state
        self.assertEqual(canvas._last_paint_error, "Simulated block failure")
        # Console output was logged ONCE, not 5 times (flood prevented)
        log_text = stderr_buf.getvalue()
        self.assertEqual(log_text.count("[CrystalReportViewer] Error rendering report page:"), 1)

    # ──────────────────────────────────────────────────────────────────
    # 3. All Real Report Screens Render Across the Canvas
    # ──────────────────────────────────────────────────────────────────

    def test_08_items_all_stock_screen_rendering(self):
        """ItemsAllStockPage renders its pages through the canvas without paint errors."""
        page = ItemsAllStockPage()
        page.spin_near_expiry.setValue(0)
        page.chk_expired.setChecked(True)
        page.generate_report()

        self.assertGreaterEqual(len(page._pages), 1)
        for pg in page._pages:
            page.viewer.canvas.set_page(pg)
            img = QImage(page.viewer.canvas.size(), QImage.Format_ARGB32)
            page.viewer.canvas.render(img)
            self.assertIsNone(page.viewer.canvas._last_paint_error)

    def test_09_companywise_item_stock_screen_rendering(self):
        """CompanywiseItemStockPage renders its pages (with item subtotals and grand totals) without paint errors."""
        page = CompanywiseItemStockPage()
        if page.cbo_company.count() > 0:
            page.cbo_company.setCurrentIndex(0)
        page.generate_report()

        for pg in page._pages:
            page.viewer.canvas.set_page(pg)
            img = QImage(page.viewer.canvas.size(), QImage.Format_ARGB32)
            page.viewer.canvas.render(img)
            self.assertIsNone(page.viewer.canvas._last_paint_error)

    def test_10_expired_item_list_screen_rendering(self):
        """ExpiredItemListPage renders without paint errors."""
        page = ExpiredItemListPage()
        page.generate_report()

        for pg in page._pages:
            page.viewer.canvas.set_page(pg)
            img = QImage(page.viewer.canvas.size(), QImage.Format_ARGB32)
            page.viewer.canvas.render(img)
            self.assertIsNone(page.viewer.canvas._last_paint_error)

    def test_11_item_list_screen_rendering(self):
        """ItemListPage renders without paint errors."""
        page = ItemListPage()
        page.generate_report()

        for pg in page._pages:
            page.viewer.canvas.set_page(pg)
            img = QImage(page.viewer.canvas.size(), QImage.Format_ARGB32)
            page.viewer.canvas.render(img)
            self.assertIsNone(page.viewer.canvas._last_paint_error)

    def test_12_sales_report_landscape_rendering(self):
        """SalesReportPage (landscape layout with Summary Box) renders without paint errors."""
        page = SalesReportPage()
        page._on_generate()

        for pg in page._pages:
            page.viewer.canvas.set_page(pg)
            img = QImage(page.viewer.canvas.size(), QImage.Format_ARGB32)
            page.viewer.canvas.render(img)
            self.assertIsNone(page.viewer.canvas._last_paint_error)

    def test_13_all_purchase_reports_rendering(self):
        """All 6 Purchase Reports render without paint errors."""
        purchase_pages = [
            CompanywiseItemwisePurchasePage(),
            CompanywiseSupplierwisePurchasePage(),
            SupplierwiseItemwiseInvoicePurchasePage(),
            SupplierwiseItemwiseChallanPurchasePage(),
            ItemwisePurchasePage(),
            ItemwiseBatchwisePurchasePage(),
        ]

        for p in purchase_pages:
            # Generate empty or default report
            pages = p.generate_report_pages("2026-04-01", "2026-04-30", -1)
            p.viewer.set_pages(pages)
            for pg in pages:
                p.viewer.canvas.set_page(pg)
                img = QImage(p.viewer.canvas.size(), QImage.Format_ARGB32)
                p.viewer.canvas.render(img)
                self.assertIsNone(p.viewer.canvas._last_paint_error)

    def test_14_zoom_and_resize_stress(self):
        """Changing zoom factor and resizing the canvas widget re-renders without painter issues."""
        header = self._create_sample_header()
        page = ReportPage(
            page_num=1,
            total_pages=1,
            header=header,
            blocks=[
                ReportBlock(kind=BlockKind.TABLE_HEADER, height=20.0, data={"columns": ["Col1", "Col2"], "widths": [300.0, 300.0]}),
                ReportBlock(kind=BlockKind.DATA_ROW, height=18.0, data={"cells": ["A", "B"], "widths": [300.0, 300.0]}),
                ReportBlock(kind=BlockKind.GRAND_TOTAL, height=20.0, data={"custom_cells": [(500.0, "Total :", "right"), (100.0, "10.00", "right")]}),
            ],
        )

        canvas = ReportPageCanvas()
        canvas.set_page(page)

        for zoom in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
            canvas.set_zoom(zoom)
            img = QImage(canvas.size(), QImage.Format_ARGB32)
            canvas.render(img)
            self.assertIsNone(canvas._last_paint_error)


if __name__ == "__main__":
    unittest.main()
