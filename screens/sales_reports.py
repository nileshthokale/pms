"""Sales Report Screens — Crystal Reports Style & Pharma-WINNER Reference.

Implements all 6 Pharma-WINNER Sales Reports:
1. Daily Billwise Sales
2. Daily Itemwise Sales (Ctrl+T)
3. Companywise Sales
4. Itemwise Sales
5. Daily Profit Calculation (Ctrl+O)
6. Daily Profit Itemwise

Each report features:
- Standard blue title bar with report title and close "✕" button
- Crystal Reports viewer with toolbar (Export PDF, Print, Page navigation, Zoom, Find, Copy)
  or comprehensive tabular analysis (for Daily Profit Calculation)
- Centered white A4 page (Portrait or Landscape) with drop shadow on grey canvas
- Compact right-side filter panel with dedicated filters and Show Report action
- Full Day Mode and Night Mode theme compatibility
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QDate, QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QStandardItem
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.doc_formatter import format_sales_bill_number
from ui.components import ReportFilterSearchCombo, SearchableComboBox
from database.sales_reports_dao import SalesReportsDAO
from ui import theme
from ui.crystal_report_viewer import (
    BlockKind,
    CONTENT_WIDTH,
    CONTENT_WIDTH_LANDSCAPE,
    CrystalReportViewer,
    PAGE_HEIGHT,
    PAGE_HEIGHT_LANDSCAPE,
    PAGE_WIDTH,
    PAGE_WIDTH_LANDSCAPE,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    fmt_amt,
    fmt_date_dash,
    fmt_qty,
    get_default_store_identity,
    print_or_export_report_pages,
)
from ui.fy_view import view_year_bounds
from ui.searchable_filter import SearchableFilterEdit
from ui.theme import palette

MAX_PAGE_BODY_HEIGHT_PORTRAIT = 980.0
MAX_PAGE_BODY_HEIGHT_LANDSCAPE = 635.0


def paginate_sales_blocks(
    header: ReportHeaderData,
    blocks: List[ReportBlock],
    table_header_block: Optional[ReportBlock] = None,
    orientation: str = "portrait",
) -> List[ReportPage]:
    """Split report blocks across A4 pages, repeating table headers across page breaks."""
    if not blocks:
        empty_page = ReportPage(
            page_num=1,
            total_pages=1,
            header=header,
            blocks=[],
            orientation=orientation,
            page_width=PAGE_WIDTH_LANDSCAPE if orientation == "landscape" else PAGE_WIDTH,
            page_height=PAGE_HEIGHT_LANDSCAPE if orientation == "landscape" else PAGE_HEIGHT,
        )
        return [empty_page]

    page_w = PAGE_WIDTH_LANDSCAPE if orientation == "landscape" else PAGE_WIDTH
    page_h = PAGE_HEIGHT_LANDSCAPE if orientation == "landscape" else PAGE_HEIGHT
    max_h = MAX_PAGE_BODY_HEIGHT_LANDSCAPE if orientation == "landscape" else MAX_PAGE_BODY_HEIGHT_PORTRAIT

    pages: List[ReportPage] = []
    current_blocks: List[ReportBlock] = []
    current_h = 0.0

    for block in blocks:
        needed_h = 60.0 if block.kind in (BlockKind.GROUP_HEADER, BlockKind.ITEM_SUBTOTAL) else block.height
        if current_blocks and (current_h + needed_h > max_h):
            pages.append(
                ReportPage(
                    page_num=len(pages) + 1,
                    total_pages=0,
                    header=header,
                    blocks=current_blocks,
                    orientation=orientation,
                    page_width=page_w,
                    page_height=page_h,
                )
            )
            current_blocks = []
            current_h = 0.0

            if table_header_block and block.kind not in (BlockKind.GROUP_HEADER, BlockKind.TABLE_HEADER):
                current_blocks.append(table_header_block)
                current_h += table_header_block.height

        current_blocks.append(block)
        current_h += block.height

    if current_blocks:
        pages.append(
            ReportPage(
                page_num=len(pages) + 1,
                total_pages=0,
                header=header,
                blocks=current_blocks,
                orientation=orientation,
                page_width=page_w,
                page_height=page_h,
            )
        )

    total = len(pages)
    for p in pages:
        p.total_pages = total

    return pages


# ══════════════════════════════════════════════════════════════════════
# Base Sales Report Page
# ══════════════════════════════════════════════════════════════════════

class _BaseSalesReportPage(QWidget):
    """Common foundation for Crystal-Reports-style sales report screens."""

    close_requested = Signal()

    def __init__(self, window_title: str, panel_title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.window_title_text = window_title
        self.panel_title_text = panel_title
        self._pages: List[ReportPage] = []
        self._history_financial_year: Optional[Dict] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Blue Title Bar
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(32)
        self.title_bar.setStyleSheet(
            "QFrame { background-color: #1B5299; border-bottom: 1px solid #0E356A; }"
            "QLabel { color: #FFFFFF; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; }"
            "QPushButton { background: transparent; color: #FFFFFF; font-size: 14px; font-weight: bold; border: none; width: 28px; height: 28px; }"
            "QPushButton:hover { background-color: #E81123; }"
        )
        tb_layout = QHBoxLayout(self.title_bar)
        tb_layout.setContentsMargins(10, 0, 4, 0)

        self.lbl_title = QLabel(self.window_title_text)
        tb_layout.addWidget(self.lbl_title)
        tb_layout.addStretch()

        self.btn_close = QPushButton("✕")
        self.btn_close.setToolTip("Close Report")
        self.btn_close.clicked.connect(self._on_close)
        tb_layout.addWidget(self.btn_close)
        root.addWidget(self.title_bar)

        # 2. Split Area: Left (Viewer) + Right (Filter Panel)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(2)
        self.main_splitter.setStyleSheet("QSplitter::handle { background-color: #A0B0C0; }")

        # Left: CrystalReportViewer
        self.viewer = CrystalReportViewer(self)
        self.viewer.print_requested.connect(self.print_report)
        self.viewer.export_requested.connect(self.export_report)
        self.main_splitter.addWidget(self.viewer)

        # Right: Filter Panel
        self.filter_panel = QFrame()
        self.filter_panel.setMinimumWidth(240)
        self.filter_panel.setMaximumWidth(320)
        self.fp_layout = QVBoxLayout(self.filter_panel)
        self.fp_layout.setContentsMargins(14, 14, 14, 14)
        self.fp_layout.setSpacing(10)

        self.lbl_panel_title = QLabel(self.panel_title_text)
        self.lbl_panel_title.setStyleSheet("color: #003366; font-size: 14px; font-weight: bold; margin-bottom: 6px;")
        self.lbl_panel_title.setWordWrap(True)
        self.fp_layout.addWidget(self.lbl_panel_title)

        # Subclass adds filters here
        self._setup_filters()

        # Validation message
        self.lbl_msg = QLabel("")
        self.lbl_msg.setStyleSheet("color: #C00000; font-size: 11px; font-weight: bold; background: transparent;")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setVisible(False)
        self.fp_layout.addWidget(self.lbl_msg)

        self.fp_layout.addSpacing(6)

        # Action Buttons
        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.clicked.connect(self.generate_report)
        self.fp_layout.addWidget(self.btn_show_report)

        self.btn_panel_print = QPushButton("Print")
        self.btn_panel_print.setEnabled(False)
        self.btn_panel_print.clicked.connect(self.print_report)
        self.fp_layout.addWidget(self.btn_panel_print)

        self.fp_layout.addStretch()
        self.main_splitter.addWidget(self.filter_panel)

        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 1)
        root.addWidget(self.main_splitter, 1)

        self.refresh_theme()

    def _setup_filters(self):
        """Override to add specific filter controls."""
        pass

    def _on_close(self):
        self.close_requested.emit()

    def set_history_financial_year(self, year: Optional[Dict]):
        self._history_financial_year = dict(year) if year else None

    def generate_report(self):
        """Override in subclasses."""
        pass

    def print_report(self):
        if not self._pages:
            return
        print_or_export_report_pages(self._pages, parent=self)

    def export_report(self):
        if not self._pages:
            return
        default_name = f"{self.window_title_text.lower().replace(' ', '_')}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Report", default_name, "PDF Files (*.pdf);;CSV Files (*.csv)"
        )
        if not path:
            return
        if path.casefold().endswith(".pdf"):
            if print_or_export_report_pages(self._pages, parent=self, output_pdf_path=path):
                QMessageBox.information(self, "Export", f"Report saved as PDF:\n{path}")
        else:
            self._export_csv(path)

    def _export_csv(self, path: str):
        lines: List[str] = []
        header_written = False
        for p in self._pages:
            for b in p.blocks:
                if b.kind == BlockKind.TABLE_HEADER:
                    if not header_written:
                        lines.append(",".join(f'"{c}"' for c in b.data.get("columns", [])))
                        header_written = True
                elif b.kind == BlockKind.DATA_ROW:
                    lines.append(",".join(f'"{c}"' for c in b.data.get("cells", [])))
                elif b.kind in (BlockKind.ITEM_SUBTOTAL, BlockKind.GRAND_TOTAL):
                    label = b.data.get("label", "Total :")
                    amt = b.data.get("amt_str", "")
                    lines.append(f'"{label}",,,,,,,,"{amt}"')
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(self, "Export", f"Report saved as CSV:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", f"Failed to save CSV: {exc}")

    def refresh_theme(self):
        p = palette()
        is_dark = p.get("mode") == "dark" or p.get("bg", "").lower() in ("#1e1e1e", "#121212", "#222222")

        self.setStyleSheet(f"background-color: {p['bg']};")
        panel_bg = p['surface'] if is_dark else "#E8EFF7"
        panel_border = p['border'] if is_dark else "#B0C4DE"
        text_color = p['text'] if is_dark else "#003366"

        self.filter_panel.setStyleSheet(
            f"QFrame {{ background-color: {panel_bg}; border-left: 1px solid {panel_border}; }}"
            f"QLabel {{ color: {text_color}; font-size: 12px; font-weight: bold; background: transparent; font-family: 'Segoe UI'; }}"
            f"QDateEdit, QLineEdit, QComboBox {{"
            f"  background-color: {p['surface']}; color: {p['text']};"
            f"  border: 1px solid {p['border']}; border-radius: 2px; padding: 4px 6px; font-size: 12px;"
            f"}}"
        )
        self.btn_show_report.setStyleSheet(
            f"QPushButton {{ background-color: #1B5299; color: white; border: none; border-radius: 3px; padding: 7px 12px; font-size: 13px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #2669B8; }}"
        )
        self.btn_panel_print.setStyleSheet(
            f"QPushButton {{ background-color: #1B5299; color: white; border: none; border-radius: 3px; padding: 7px 12px; font-size: 13px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #2669B8; }}"
            f"QPushButton:disabled {{ background-color: {'#404040' if is_dark else '#A0B8D0'}; color: {'#707070' if is_dark else '#E0E8F0'}; }}"
        )
        workspace_bg = QColor("#303030") if is_dark else QColor("#808080")
        self.viewer.canvas.set_workspace_bg(workspace_bg)
        self.viewer.scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color: {'#303030' if is_dark else '#808080'}; border: none; }}"
        )


# ══════════════════════════════════════════════════════════════════════
# 1. Daily Billwise Sales Page
# ══════════════════════════════════════════════════════════════════════

class DailyBillwiseSalesPage(_BaseSalesReportPage):
    """Report 1: Daily Billwise Sales."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            window_title="Daily Billwise Sales",
            panel_title="Daily Billwise Sales",
            parent=parent,
        )

    def _setup_filters(self):
        lbl_date = QLabel("Sales Date:")
        self.fp_layout.addWidget(lbl_date)
        self.date_edit = QDateEdit()
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.fp_layout.addWidget(self.date_edit)

    def generate_report(self):
        sale_date = self.date_edit.date().toString("yyyy-MM-dd")
        data = SalesReportsDAO.get_daily_billwise_sales(sale_date)
        rows = data.get("rows", [])
        summary = data.get("summary", {})

        store_name, store_address = get_default_store_identity()
        fmt_date = fmt_date_dash(sale_date)
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1=f"DAILY BILLWISE SALES REPORT - {fmt_date}",
            header_line_2=f"Report Date: {datetime.now().strftime('%d-%m-%Y %I:%M %p')}",
            header_line_3=f"Date: {fmt_date}  |  Total Bills: {summary.get('total_bills', 0)}",
        )

        cols = [
            "Sr No",
            "Bill No",
            "Bill Date",
            "Voucher Type",
            "Patient Name",
            "Voucher No",
            "Voucher Time",
            "Discount",
            "Bill Amount",
        ]
        # Sums to CONTENT_WIDTH_LANDSCAPE = 1053.0
        widths = [45.0, 110.0, 85.0, 90.0, 240.0, 110.0, 90.0, 95.0, 188.0]
        aligns = ["center", "left", "center", "left", "left", "left", "center", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=32.0,
                    data={"message": f"No sales bills found for {fmt_date}."},
                )
            )
        else:
            for idx, r in enumerate(rows, 1):
                raw_bill = str(r.get("bill_no") or "")
                bill_no = format_sales_bill_number(
                    raw_bill,
                    patient_name=r.get("original_patient_name", r.get("patient_name")),
                )
                b_date = fmt_date_dash(r.get("sale_date", ""))
                v_type = str(r.get("voucher_type") or "Cash")
                pat = str(r.get("patient_name") or "WALKIN").strip()
                v_no = bill_no
                v_time = str(r.get("sale_time") or "")
                disc = f"{float(r.get('discount') or 0.0):,.2f}"
                amt = f"{float(r.get('bill_amount') or 0.0):,.2f}"

                cells = [str(idx), bill_no, b_date, v_type, pat, v_no, v_time, disc, amt]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=18.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            # Grand Total block
            # Prefix covers columns 0..6 (width = 45+110+85+90+240+110+90 = 770.0)
            prefix_w = sum(widths[:7])
            disc_w = widths[7]
            amt_w = widths[8]

            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=22.0,
                    data={
                        "custom_cells": [
                            {"width": prefix_w, "text": "Total :", "align": "right", "is_bold": True},
                            {"width": disc_w, "text": f"{summary.get('total_discount', 0.0):,.2f}", "align": "right", "is_bold": True},
                            {"width": amt_w, "text": f"{summary.get('total_bill_amount', 0.0):,.2f}", "align": "right", "is_bold": True},
                        ]
                    },
                )
            )

        pages = paginate_sales_blocks(header, blocks, table_header_block, orientation="landscape")
        self._pages = pages
        self.viewer.set_pages(pages)
        self.btn_panel_print.setEnabled(bool(rows))


# ══════════════════════════════════════════════════════════════════════
# 2. Daily Itemwise Sales Page (Ctrl+T)
# ══════════════════════════════════════════════════════════════════════

class DailyItemwiseSalesPage(_BaseSalesReportPage):
    """Report 2: Daily Itemwise Sales (Shortcut Ctrl+T)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            window_title="Daily Itemwise Sales",
            panel_title="Daily Itemwise Sales",
            parent=parent,
        )

    def _setup_filters(self):
        lbl_date = QLabel("Sales Date:")
        self.fp_layout.addWidget(lbl_date)
        self.date_edit = QDateEdit()
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.fp_layout.addWidget(self.date_edit)

    def generate_report(self):
        sale_date = self.date_edit.date().toString("yyyy-MM-dd")
        data = SalesReportsDAO.get_daily_itemwise_sales(sale_date)
        rows = data.get("rows", [])
        summary = data.get("summary", {})

        store_name, store_address = get_default_store_identity()
        fmt_date = fmt_date_dash(sale_date)
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1=f"DAILY ITEMWISE SALES REPORT - {fmt_date}",
            header_line_2=f"Report Date: {datetime.now().strftime('%d-%m-%Y %I:%M %p')}",
            header_line_3=f"Date: {fmt_date}  |  Items: {summary.get('total_lines', 0)}  |  Qty: {fmt_qty(summary.get('total_qty', 0))}",
        )

        cols = [
            "Bill No",
            "Voucher Type",
            "Item Name",
            "MRP",
            "Quantity",
            "Amount",
            "Batch No",
            "Expiry",
            "Discount",
            "Bill Amount",
        ]
        # Sums to CONTENT_WIDTH_LANDSCAPE = 1053.0
        widths = [95.0, 85.0, 255.0, 75.0, 65.0, 105.0, 95.0, 75.0, 80.0, 123.0]
        aligns = ["left", "left", "left", "right", "right", "right", "left", "center", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=32.0,
                    data={"message": f"No item sales found for {fmt_date}."},
                )
            )
        else:
            for r in rows:
                raw_bill = str(r.get("bill_no") or "")
                bill_no = format_sales_bill_number(raw_bill, patient_name=r.get("patient_name"))
                v_type = str(r.get("voucher_type") or "Cash")
                item = str(r.get("item_name") or "")
                mrp_val = f"{float(r.get('mrp') or 0.0):,.2f}"
                qty_val = fmt_qty(r.get("quantity") or 0.0)
                amt_val = f"{float(r.get('amount') or 0.0):,.2f}"
                batch = str(r.get("batch_no") or "")
                exp = str(r.get("expiry") or "")
                disc = f"{float(r.get('discount') or 0.0):,.2f}"
                bill_amt = f"{float(r.get('bill_amount') or 0.0):,.2f}"

                cells = [bill_no, v_type, item, mrp_val, qty_val, amt_val, batch, exp, disc, bill_amt]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=18.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            # Grand Total block: Show total of Amount (sum of items), NOT sum of repeated bill amounts!
            prefix_w = sum(widths[:4])  # 95+85+255+75 = 510.0
            qty_w = widths[4]           # 65.0
            amt_w = widths[5]           # 105.0
            suffix_w = sum(widths[6:])  # 95+75+80+123 = 373.0

            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=22.0,
                    data={
                        "custom_cells": [
                            {"width": prefix_w, "text": "Total Item Amount :", "align": "right", "is_bold": True},
                            {"width": qty_w, "text": fmt_qty(summary.get("total_qty", 0.0)), "align": "right", "is_bold": True},
                            {"width": amt_w, "text": f"{summary.get('total_amount', 0.0):,.2f}", "align": "right", "is_bold": True},
                            {"width": suffix_w, "text": "", "align": "left", "is_bold": False},
                        ]
                    },
                )
            )

        pages = paginate_sales_blocks(header, blocks, table_header_block, orientation="landscape")
        self._pages = pages
        self.viewer.set_pages(pages)
        self.btn_panel_print.setEnabled(bool(rows))


# ══════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════
# Searchable Filter Selector for Sales Reports
# ══════════════════════════════════════════════════════════════════════

# ReportFilterSearchCombo is defined in ui.components and imported above.


# 3. Companywise Sales Page
# ══════════════════════════════════════════════════════════════════════

class CompanywiseSalesPage(_BaseSalesReportPage):
    """Report 3: Companywise Sales."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            window_title="Companywise Sales",
            panel_title="Companywise Sales",
            parent=parent,
        )
        self._load_companies()

    def _setup_filters(self):
        lbl_from = QLabel("From Date:")
        self.fp_layout.addWidget(lbl_from)
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.from_date_edit)

        lbl_to = QLabel("To Date:")
        self.fp_layout.addWidget(lbl_to)
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.to_date_edit)

        # Set default dates to active FY start -> today
        self._init_dates()

        lbl_comp = QLabel("Company:")
        self.fp_layout.addWidget(lbl_comp)
        self.company_combo = ReportFilterSearchCombo(self)
        self.fp_layout.addWidget(self.company_combo)

    def _init_dates(self):
        fy_from, fy_to = view_year_bounds(self._history_financial_year)
        self.from_date_edit.setDate(QDate.fromString(fy_from, "yyyy-MM-dd"))
        self.to_date_edit.setDate(QDate.currentDate())

    def _load_companies(self):
        companies = SalesReportsDAO.get_filter_companies()
        self.company_combo.clear()
        self.company_combo.addItem("-- Select Company --", None)
        for c in companies:
            display = str(c.get("company_name") or "").strip()
            short = str(c.get("short_name") or "").strip()
            raw = f"{display} {short}".strip() if short else display
            if display:
                self.company_combo.addItem(display, c.get("id"), raw)
        self.company_combo.setCurrentIndex(0)

    def set_history_financial_year(self, year: Optional[Dict]):
        super().set_history_financial_year(year)
        self._init_dates()

    def get_selected_company_id(self) -> Optional[int]:
        return self.company_combo.currentData()

    def generate_report(self):
        from_q = self.from_date_edit.date()
        to_q = self.to_date_edit.date()
        if from_q > to_q:
            self.lbl_msg.setText("From Date cannot be later than To Date.")
            self.lbl_msg.setVisible(True)
            return

        comp_id = self.get_selected_company_id()
        if comp_id is None:
            self.lbl_msg.setText("Please select a valid Company.")
            self.lbl_msg.setVisible(True)
            return

        self.lbl_msg.setText("")
        self.lbl_msg.setVisible(False)

        from_iso = from_q.toString("yyyy-MM-dd")
        to_iso = to_q.toString("yyyy-MM-dd")
        comp_name = self.company_combo.currentText().strip()

        data = SalesReportsDAO.get_companywise_sales(from_iso, to_iso, comp_id)
        rows = data.get("rows", [])
        summary = data.get("summary", {})

        store_name, store_address = get_default_store_identity()
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1="COMPANYWISE SALES REPORT",
            header_line_2=f"Company: {comp_name}",
            header_line_3=f"From: {fmt_date_dash(from_iso)} To: {fmt_date_dash(to_iso)}  |  Total Qty: {fmt_qty(summary.get('total_qty', 0))}",
        )

        cols = [
            "Sr No",
            "Item Name",
            "Unit",
            "Pack Size",
            "Batch No",
            "MRP",
            "Sales Quantity",
            "Amount",
        ]
        # Sums to CONTENT_WIDTH = 724.0
        widths = [38.0, 220.0, 55.0, 55.0, 85.0, 65.0, 70.0, 136.0]
        aligns = ["center", "left", "left", "center", "left", "right", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=32.0,
                    data={"message": f"No sales found for company '{comp_name}' in the selected period."},
                )
            )
        else:
            # Group by item for item subtotals
            current_item_id = None
            current_item_name = ""
            item_qty = 0.0
            item_amt = 0.0
            sr_no = 0

            for r in rows:
                sr_no += 1
                item_name = str(r.get("item_name") or "")
                unit = str(r.get("unit_name") or "")
                pack = str(r.get("pack_size") or "")
                batch = str(r.get("batch_no") or "")
                mrp_val = f"{float(r.get('mrp') or 0.0):,.2f}"
                qty_val = float(r.get("sales_qty") or 0.0)
                amt_val = float(r.get("amount") or 0.0)

                cells = [str(sr_no), item_name, unit, pack, batch, mrp_val, fmt_qty(qty_val), f"{amt_val:,.2f}"]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=18.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            # Grand Total block
            prefix_w = sum(widths[:6])  # 38+220+55+55+85+65 = 518.0
            qty_w = widths[6]           # 70.0
            amt_w = widths[7]           # 136.0

            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=22.0,
                    data={
                        "custom_cells": [
                            {"width": prefix_w, "text": "Grand Total :", "align": "right", "is_bold": True},
                            {"width": qty_w, "text": fmt_qty(summary.get("total_qty", 0.0)), "align": "right", "is_bold": True},
                            {"width": amt_w, "text": f"{summary.get('total_amount', 0.0):,.2f}", "align": "right", "is_bold": True},
                        ]
                    },
                )
            )

        pages = paginate_sales_blocks(header, blocks, table_header_block, orientation="portrait")
        self._pages = pages
        self.viewer.set_pages(pages)
        self.btn_panel_print.setEnabled(bool(rows))


# ══════════════════════════════════════════════════════════════════════
# 4. Itemwise Sales Page
# ══════════════════════════════════════════════════════════════════════

class ItemwiseSalesPage(_BaseSalesReportPage):
    """Report 4: Itemwise Sales."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            window_title="Itemwise Sales",
            panel_title="Itemwise Sales",
            parent=parent,
        )
        self._load_items()

    def _setup_filters(self):
        lbl_from = QLabel("From Date:")
        self.fp_layout.addWidget(lbl_from)
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.from_date_edit)

        lbl_to = QLabel("To Date:")
        self.fp_layout.addWidget(lbl_to)
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.to_date_edit)

        self._init_dates()

        lbl_item = QLabel("Item:")
        self.fp_layout.addWidget(lbl_item)
        self.item_combo = ReportFilterSearchCombo(self)
        self.fp_layout.addWidget(self.item_combo)

    def _init_dates(self):
        fy_from, fy_to = view_year_bounds(self._history_financial_year)
        self.from_date_edit.setDate(QDate.fromString(fy_from, "yyyy-MM-dd"))
        self.to_date_edit.setDate(QDate.currentDate())

    def _load_items(self):
        items = SalesReportsDAO.get_filter_items()
        self.item_combo.clear()
        self.item_combo.addItem("-- Select Item --", None)
        for it in items:
            name = str(it.get("item_name") or "").strip()
            unit = str(it.get("unit_name") or "").strip()
            raw = f"{name} {unit}".strip() if unit else name
            if name:
                self.item_combo.addItem(name, it.get("id"), raw)
        self.item_combo.setCurrentIndex(0)

    def set_history_financial_year(self, year: Optional[Dict]):
        super().set_history_financial_year(year)
        self._init_dates()

    def get_selected_item_id(self) -> Optional[int]:
        return self.item_combo.currentData()

    def generate_report(self):
        from_q = self.from_date_edit.date()
        to_q = self.to_date_edit.date()
        if from_q > to_q:
            self.lbl_msg.setText("From Date cannot be later than To Date.")
            self.lbl_msg.setVisible(True)
            return

        item_id = self.get_selected_item_id()
        if item_id is None:
            self.lbl_msg.setText("Please select a valid Item.")
            self.lbl_msg.setVisible(True)
            return

        self.lbl_msg.setText("")
        self.lbl_msg.setVisible(False)

        from_iso = from_q.toString("yyyy-MM-dd")
        to_iso = to_q.toString("yyyy-MM-dd")
        item_name = self.item_combo.currentText().strip()

        data = SalesReportsDAO.get_itemwise_sales(from_iso, to_iso, item_id)
        rows = data.get("rows", [])
        summary = data.get("summary", {})

        store_name, store_address = get_default_store_identity()
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1="ITEMWISE SALES REPORT",
            header_line_2=f"Item: {item_name}",
            header_line_3=f"From: {fmt_date_dash(from_iso)} To: {fmt_date_dash(to_iso)}  |  Total Qty: {fmt_qty(summary.get('total_qty', 0))}",
        )

        cols = [
            "Sr No",
            "Date",
            "Voucher Type",
            "Bill No",
            "Patient Name",
            "Batch No",
            "MRP",
            "Quantity",
            "Amount",
        ]
        # Sums to CONTENT_WIDTH = 724.0
        widths = [38.0, 75.0, 75.0, 85.0, 175.0, 80.0, 60.0, 56.0, 80.0]
        aligns = ["center", "center", "left", "left", "left", "left", "right", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=32.0,
                    data={"message": f"No sales found for item '{item_name}' in the selected period."},
                )
            )
        else:
            for idx, r in enumerate(rows, 1):
                d_str = fmt_date_dash(r.get("sale_date", ""))
                v_type = str(r.get("voucher_type") or "Cash")
                raw_bill = str(r.get("bill_no") or "")
                bill_no = format_sales_bill_number(
                    raw_bill,
                    patient_name=r.get("original_patient_name", r.get("patient_name")),
                )
                pat = str(r.get("patient_name") or "WALKIN").strip()
                batch = str(r.get("batch_no") or "")
                mrp_val = f"{float(r.get('mrp') or 0.0):,.2f}"
                qty_val = float(r.get("quantity") or 0.0)
                amt_val = float(r.get("amount") or 0.0)

                cells = [str(idx), d_str, v_type, bill_no, pat, batch, mrp_val, fmt_qty(qty_val), f"{amt_val:,.2f}"]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=18.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            # Grand Total block
            prefix_w = sum(widths[:7])  # 38+75+75+85+175+80+60 = 588.0
            qty_w = widths[7]           # 56.0
            amt_w = widths[8]           # 80.0

            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=22.0,
                    data={
                        "custom_cells": [
                            {"width": prefix_w, "text": "Grand Total :", "align": "right", "is_bold": True},
                            {"width": qty_w, "text": fmt_qty(summary.get("total_qty", 0.0)), "align": "right", "is_bold": True},
                            {"width": amt_w, "text": f"{summary.get('total_amount', 0.0):,.2f}", "align": "right", "is_bold": True},
                        ]
                    },
                )
            )

        pages = paginate_sales_blocks(header, blocks, table_header_block, orientation="portrait")
        self._pages = pages
        self.viewer.set_pages(pages)
        self.btn_panel_print.setEnabled(bool(rows))


# ══════════════════════════════════════════════════════════════════════
# 5. Daily Profit Calculation (Page & Dialog, Shortcut Ctrl+O)
# ══════════════════════════════════════════════════════════════════════

class DailyProfitCalculationWidget(QWidget):
    """Reusable wide tabular profit calculation view with 12 columns."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pages: List[ReportPage] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 1. Filter Strip
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(10)

        lbl_from = QLabel("From Date:")
        filter_bar.addWidget(lbl_from)
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDate(QDate.currentDate())
        filter_bar.addWidget(self.from_date_edit)

        lbl_to = QLabel("To Date:")
        filter_bar.addWidget(lbl_to)
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        self.to_date_edit.setDate(QDate.currentDate())
        filter_bar.addWidget(self.to_date_edit)

        self.btn_show = QPushButton("Show")
        self.btn_show.clicked.connect(self.load_data)
        filter_bar.addWidget(self.btn_show)

        self.btn_export = QPushButton("Export CSV")
        self.btn_export.clicked.connect(self.export_csv)
        filter_bar.addWidget(self.btn_export)

        self.btn_print = QPushButton("Print")
        self.btn_print.setEnabled(False)
        self.btn_print.clicked.connect(self.print_report)
        filter_bar.addWidget(self.btn_print)

        filter_bar.addStretch()
        root.addLayout(filter_bar)

        # 2. Main Table Widget
        self.table = QTableWidget()
        headers = [
            "Voucher Date",
            "Cash Receipt",
            "Cash Sales",
            "Total Cash Received",
            "Cash Payment",
            "Cash Sales Return",
            "Net Cash Received",
            "Bank Payment",
            "Credit Sales",
            "Net Sales",
            "Net Purchase",
            "Net Profit",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        # 3. Totals summary labels strip
        self.lbl_summary = QLabel("Ready")
        self.lbl_summary.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        root.addWidget(self.lbl_summary)

        self.refresh_theme()

    def load_data(self):
        from_iso = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_iso = self.to_date_edit.date().toString("yyyy-MM-dd")
        if from_iso > to_iso:
            QMessageBox.warning(self, "Invalid Range", "From Date cannot be later than To Date.")
            return

        data = SalesReportsDAO.get_daily_profit_calculation(from_iso, to_iso)
        rows = data.get("rows", [])
        totals = data.get("summary", {})

        # Include totals row if rows exist
        row_count = len(rows) + (1 if rows else 0)
        self.table.setRowCount(row_count)

        for i, r in enumerate(rows):
            d_item = QTableWidgetItem(fmt_date_dash(r["voucher_date"]))
            d_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, d_item)

            cols_vals = [
                r["cash_receipt"],
                r["cash_sales"],
                r["total_cash_received"],
                r["cash_payment"],
                r["cash_sales_return"],
                r["net_cash_received"],
                r["bank_payment"],
                r["credit_sales"],
                r["net_sales"],
                r["net_purchase"],
                r["net_profit"],
            ]
            for col_idx, val in enumerate(cols_vals, 1):
                item = QTableWidgetItem(f"{float(val or 0):,.2f}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, col_idx, item)

        # Totals row
        if rows:
            tot_row_idx = len(rows)
            t_label = QTableWidgetItem("Total :")
            t_label.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table.setItem(tot_row_idx, 0, t_label)

            tot_vals = [
                totals.get("cash_receipt", 0.0),
                totals.get("cash_sales", 0.0),
                totals.get("total_cash_received", 0.0),
                totals.get("cash_payment", 0.0),
                totals.get("cash_sales_return", 0.0),
                totals.get("net_cash_received", 0.0),
                totals.get("bank_payment", 0.0),
                totals.get("credit_sales", 0.0),
                totals.get("net_sales", 0.0),
                totals.get("net_purchase", 0.0),
                totals.get("net_profit", 0.0),
            ]
            for col_idx, val in enumerate(tot_vals, 1):
                item = QTableWidgetItem(f"{float(val or 0):,.2f}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setFont(QFont("Segoe UI", 9, QFont.Bold))
                self.table.setItem(tot_row_idx, col_idx, item)

        self.table.resizeColumnsToContents()
        self._pages = self._build_report_pages(rows, totals, from_iso, to_iso)
        self.btn_print.setEnabled(bool(rows))
        self.lbl_summary.setText(
            f"Dates: {len(rows)}  |  Total Sales: ₹{totals.get('net_sales', 0.0):,.2f}  |  "
            f"Total Purchase: ₹{totals.get('net_purchase', 0.0):,.2f}  |  "
            f"Net Profit: ₹{totals.get('net_profit', 0.0):,.2f}"
        )

    def print_report(self):
        if not self._pages:
            return
        print_or_export_report_pages(self._pages, parent=self)

    def _build_report_pages(
        self, rows: List[dict], totals: dict, from_iso: str, to_iso: str
    ) -> List[ReportPage]:
        """Build the A4 landscape report pages for the current table data."""
        store_name, store_address = get_default_store_identity()
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1="DAILY PROFIT CALCULATION",
            header_line_2=f"From: {fmt_date_dash(from_iso)} To: {fmt_date_dash(to_iso)}",
            header_line_3=(
                f"Net Sales: ₹{float(totals.get('net_sales', 0.0) or 0.0):,.2f}  |  "
                f"Net Purchase: ₹{float(totals.get('net_purchase', 0.0) or 0.0):,.2f}  |  "
                f"Net Profit: ₹{float(totals.get('net_profit', 0.0) or 0.0):,.2f}"
            ),
        )

        cols = [
            "Voucher Date",
            "Cash Receipt",
            "Cash Sales",
            "Total Cash Received",
            "Cash Payment",
            "Cash Sales Return",
            "Net Cash Received",
            "Bank Payment",
            "Credit Sales",
            "Net Sales",
            "Net Purchase",
            "Net Profit",
        ]
        # Sums to CONTENT_WIDTH_LANDSCAPE (1053.0); each long heading keeps
        # enough room to print in full instead of being clipped at the border.
        widths = [80.0, 84.0, 82.0, 112.0, 86.0, 103.0, 107.0, 84.0, 80.0, 76.0, 79.0, 80.0]
        aligns = ["center"] + ["right"] * 11
        keys = [
            "cash_receipt",
            "cash_sales",
            "total_cash_received",
            "cash_payment",
            "cash_sales_return",
            "net_cash_received",
            "bank_payment",
            "credit_sales",
            "net_sales",
            "net_purchase",
            "net_profit",
        ]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )
        blocks: List[ReportBlock] = [table_header_block]

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=32.0,
                    data={"message": "No daily profit records found for the selected dates."},
                )
            )
        else:
            for r in rows:
                cells = [fmt_date_dash(r.get("voucher_date", ""))]
                cells.extend(f"{float(r.get(key) or 0.0):,.2f}" for key in keys)
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=18.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            custom_cells = [
                {"width": widths[0], "text": "Total :", "align": "right", "is_bold": True}
            ]
            for key, width in zip(keys, widths[1:]):
                custom_cells.append({
                    "width": width,
                    "text": f"{float(totals.get(key, 0.0) or 0.0):,.2f}",
                    "align": "right",
                    "is_bold": True,
                })
            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=22.0,
                    data={"custom_cells": custom_cells},
                )
            )

        return paginate_sales_blocks(
            header, blocks, table_header_block, orientation="landscape"
        )

    def export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Export", "No data to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Daily Profit", "daily_profit_calculation.csv", "CSV Files (*.csv)")
        if not path:
            return
        lines = []
        # Header
        headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
        lines.append(",".join(f'"{h}"' for h in headers))
        # Rows
        for r in range(self.table.rowCount()):
            row_vals = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                row_vals.append(f'"{item.text() if item else ""}"')
            lines.append(",".join(row_vals))
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(self, "Export", f"File saved:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Failed to export CSV: {exc}")

    def refresh_theme(self):
        p = palette()
        is_dark = p.get("mode") == "dark" or p.get("bg", "").lower() in ("#1e1e1e", "#121212", "#222222")
        self.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']}; font-family: 'Segoe UI';")
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {p['surface']}; color: {p['text']}; gridline-color: {p['border']}; border: 1px solid {p['border']}; }}"
            f"QHeaderView::section {{ background-color: {'#2A2A2A' if is_dark else '#E8EEF5'}; color: {p['text']}; font-weight: bold; border: 1px solid {p['border']}; padding: 4px; }}"
        )
        self.btn_show.setStyleSheet(
            f"QPushButton {{ background-color: #1B5299; color: white; border: none; border-radius: 3px; padding: 6px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #2669B8; }}"
        )
        self.btn_export.setStyleSheet(
            f"QPushButton {{ background-color: {p['border']}; color: {p['text']}; border: none; border-radius: 3px; padding: 6px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['text_dim']}; color: white; }}"
        )
        self.btn_print.setStyleSheet(
            f"QPushButton {{ background-color: #1B5299; color: white; border: none; border-radius: 3px; padding: 6px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #2669B8; }}"
            f"QPushButton:disabled {{ background-color: {'#404040' if is_dark else '#A0B8D0'}; color: {'#707070' if is_dark else '#E0E8F0'}; }}"
        )


class DailyProfitCalculationPage(QWidget):
    """Report 5: Page embedded in MainWindow stack (Shortcut Ctrl+O)."""

    close_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet(
            "QFrame { background-color: #1B5299; border-bottom: 1px solid #0E356A; }"
            "QLabel { color: #FFFFFF; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; }"
            "QPushButton { background: transparent; color: #FFFFFF; font-size: 14px; font-weight: bold; border: none; width: 28px; height: 28px; }"
            "QPushButton:hover { background-color: #E81123; }"
        )
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(10, 0, 4, 0)
        lbl_title = QLabel("Profit Calculation")
        tb_layout.addWidget(lbl_title)
        tb_layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setToolTip("Close")
        btn_close.clicked.connect(self.close_requested.emit)
        tb_layout.addWidget(btn_close)
        root.addWidget(title_bar)

        self.widget = DailyProfitCalculationWidget(self)
        root.addWidget(self.widget, 1)

    def set_history_financial_year(self, year: Optional[Dict]):
        if year:
            s_date = year.get("start_date")
            e_date = year.get("end_date")
            if s_date:
                self.widget.from_date_edit.setDate(QDate.fromString(s_date, "yyyy-MM-dd"))
            if e_date:
                self.widget.to_date_edit.setDate(QDate.fromString(e_date, "yyyy-MM-dd"))

    def refresh_theme(self):
        self.widget.refresh_theme()


class DailyProfitCalculationDialog(QDialog):
    """Report 5: Separate wide, resizable dialog (Shortcut Ctrl+O)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Profit Calculation")
        self.resize(1300, 680)
        self.setMinimumSize(1000, 500)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.widget = DailyProfitCalculationWidget(self)
        root.addWidget(self.widget)
        self.widget.load_data()


ProfitCalculationPage = DailyProfitCalculationPage
ProfitCalculationDialog = DailyProfitCalculationDialog


# ══════════════════════════════════════════════════════════════════════
# 6. Daily Profit Itemwise Page
# ══════════════════════════════════════════════════════════════════════

class DailyProfitItemwisePage(_BaseSalesReportPage):
    """Report 6: Daily Profit Itemwise."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            window_title="Daily Profit Itemwise",
            panel_title="Daily Profit Itemwise",
            parent=parent,
        )

    def _setup_filters(self):
        lbl_from = QLabel("From Date:")
        self.fp_layout.addWidget(lbl_from)
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDate(QDate.currentDate())
        self.fp_layout.addWidget(self.from_date_edit)

        lbl_to = QLabel("To Date:")
        self.fp_layout.addWidget(lbl_to)
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        self.to_date_edit.setDate(QDate.currentDate())
        self.fp_layout.addWidget(self.to_date_edit)

    def generate_report(self):
        from_q = self.from_date_edit.date()
        to_q = self.to_date_edit.date()
        if from_q > to_q:
            self.lbl_msg.setText("From Date cannot be later than To Date.")
            self.lbl_msg.setVisible(True)
            return

        self.lbl_msg.setText("")
        self.lbl_msg.setVisible(False)

        from_iso = from_q.toString("yyyy-MM-dd")
        to_iso = to_q.toString("yyyy-MM-dd")

        data = SalesReportsDAO.get_daily_profit_itemwise(from_iso, to_iso)
        rows = data.get("rows", [])
        summary = data.get("summary", {})

        store_name, store_address = get_default_store_identity()
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1="DAILY PROFIT ITEMWISE REPORT",
            header_line_2=f"From: {fmt_date_dash(from_iso)} To: {fmt_date_dash(to_iso)}",
            header_line_3=f"Total Items: {summary.get('total_items', 0)}  |  Total Profit: ₹{summary.get('total_net_profit', 0.0):,.2f}",
        )

        cols = [
            "Sr No",
            "Item Name",
            "Unit",
            "Sales Quantity",
            "Sales",
            "Purchase",
            "Net Profit",
        ]
        # Sums to CONTENT_WIDTH = 724.0
        widths = [40.0, 234.0, 60.0, 80.0, 100.0, 100.0, 110.0]
        aligns = ["center", "left", "left", "right", "right", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=32.0,
                    data={"message": f"No item sales found between {fmt_date_dash(from_iso)} and {fmt_date_dash(to_iso)}."},
                )
            )
        else:
            for idx, r in enumerate(rows, 1):
                item_name = str(r.get("item_name") or "")
                unit = str(r.get("unit_name") or "")
                qty = float(r.get("sales_qty") or 0.0)
                sales_amt = float(r.get("sales") or 0.0)
                purch_cost = float(r.get("purchase") or 0.0)
                profit = float(r.get("net_profit") or 0.0)

                cells = [
                    str(idx),
                    item_name,
                    unit,
                    fmt_qty(qty),
                    f"{sales_amt:,.2f}",
                    f"{purch_cost:,.2f}",
                    f"{profit:,.2f}",
                ]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=18.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            # Grand Total block
            prefix_w = sum(widths[:3])  # 40+234+60 = 334.0
            qty_w = widths[3]           # 80.0
            sales_w = widths[4]         # 100.0
            purch_w = widths[5]         # 100.0
            profit_w = widths[6]        # 110.0

            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=22.0,
                    data={
                        "custom_cells": [
                            {"width": prefix_w, "text": "Grand Total :", "align": "right", "is_bold": True},
                            {"width": qty_w, "text": fmt_qty(summary.get("total_qty", 0.0)), "align": "right", "is_bold": True},
                            {"width": sales_w, "text": f"{summary.get('total_sales', 0.0):,.2f}", "align": "right", "is_bold": True},
                            {"width": purch_w, "text": f"{summary.get('total_purchase', 0.0):,.2f}", "align": "right", "is_bold": True},
                            {"width": profit_w, "text": f"{summary.get('total_net_profit', 0.0):,.2f}", "align": "right", "is_bold": True},
                        ]
                    },
                )
            )

        pages = paginate_sales_blocks(header, blocks, table_header_block, orientation="portrait")
        self._pages = pages
        self.viewer.set_pages(pages)
        self.btn_panel_print.setEnabled(bool(rows))


class DailyProfitItemwiseDialog(QDialog):
    """Report 6: Dialog view."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Daily Profit Itemwise")
        self.resize(1100, 700)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.page = DailyProfitItemwisePage(self)
        root.addWidget(self.page)
        self.page.generate_report()

