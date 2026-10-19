"""Stock Report Screens — Crystal Reports Style.

Implements all 4 separate Crystal Reports-style Stock Report screens matching Pharma-WINNER:
1. ItemsAllStockPage ("Items (All) Stock")
2. CompanywiseItemStockPage ("Companywise Item Stock")
3. ExpiredItemListPage ("Expired Item List")
4. ItemListPage ("Item List")

Each screen features:
- Standard blue title bar with report title and close "✕" button
- Crystal Reports viewer with toolbar (Export PDF, Print, Page navigation, Zoom, Find, Copy)
- Centered white A4 page with drop shadow on grey canvas
- Compact right-side filter panel with dedicated filters and Show Report action
- Full Day Mode and Night Mode theme compatibility
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from database.stock_reports_dao import StockReportsDAO
from ui import theme
from ui.crystal_report_viewer import (
    BlockKind,
    CONTENT_WIDTH,
    CrystalReportViewer,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    fmt_amt,
    fmt_qty,
    get_default_store_identity,
    print_or_export_report_pages,
)

MAX_PAGE_BODY_HEIGHT = 980.0


def fmt_qty_dash(qty: float) -> str:
    """Format quantity, showing '-' when quantity is zero."""
    if not qty or abs(qty) < 0.0001:
        return "-"
    return f"{int(qty)}" if qty == int(qty) else f"{qty:.2f}"


def paginate_stock_blocks(
    header: ReportHeaderData,
    blocks: List[ReportBlock],
    table_header_block: Optional[ReportBlock] = None,
) -> List[ReportPage]:
    """Split blocks across A4 pages, repeating table headers across page breaks."""
    if not blocks:
        return [ReportPage(page_num=1, total_pages=1, header=header, blocks=[])]

    pages: List[ReportPage] = []
    current_blocks: List[ReportBlock] = []
    current_h = 0.0

    for block in blocks:
        needed_h = 60.0 if block.kind in (BlockKind.GROUP_HEADER, BlockKind.ITEM_SUBTOTAL) else block.height
        if current_blocks and (current_h + needed_h > MAX_PAGE_BODY_HEIGHT):
            pages.append(
                ReportPage(
                    page_num=len(pages) + 1,
                    total_pages=0,
                    header=header,
                    blocks=current_blocks,
                )
            )
            current_blocks = []
            current_h = 0.0

            if table_header_block and block.kind != BlockKind.TABLE_HEADER:
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
            )
        )

    total = len(pages)
    for p in pages:
        p.total_pages = total

    return pages


# ══════════════════════════════════════════════════════════════════════
# Base Stock Report Page
# ══════════════════════════════════════════════════════════════════════

class _BaseStockReportPage(QWidget):
    """Common foundation for stock report screens."""

    close_requested = Signal()

    def __init__(self, window_title: str, panel_title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.window_title_text = window_title
        self.panel_title_text = panel_title
        self._pages: List[ReportPage] = []

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
        self.btn_close.clicked.connect(self.close_requested.emit)
        tb_layout.addWidget(self.btn_close)
        root.addWidget(self.title_bar)

        # 2. Splitter: Viewer (Left 80%), Filter Panel (Right 20%)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(2)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #A0B0C0; }")

        self.viewer = CrystalReportViewer()
        self.viewer.print_requested.connect(self.print_report)
        self.viewer.export_requested.connect(self.export_report)
        self.splitter.addWidget(self.viewer)

        self.filter_panel = QFrame()
        self.fp_layout = QVBoxLayout(self.filter_panel)
        self.fp_layout.setContentsMargins(14, 14, 14, 14)
        self.fp_layout.setSpacing(10)

        self.lbl_panel_title = QLabel(self.panel_title_text)
        self.lbl_panel_title.setStyleSheet("color: #003366; font-size: 14px; font-weight: bold; margin-bottom: 6px;")
        self.lbl_panel_title.setWordWrap(True)
        self.fp_layout.addWidget(self.lbl_panel_title)

        # Subclasses populate filter controls here
        self._setup_filters()

        self.fp_layout.addStretch()
        self.splitter.addWidget(self.filter_panel)

        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        root.addWidget(self.splitter, 1)

        theme.theme_manager.on_changed(lambda mode: self.refresh_theme())
        self.refresh_theme()

    def _setup_filters(self):
        """Override in subclasses to add specific filter controls."""
        pass

    def generate_report(self):
        """Override in subclasses to query data and update viewer."""
        pass

    def print_report(self):
        if not self._pages:
            self._show_msg("Print", "No report to print. Please generate the report first.")
            return
        print_or_export_report_pages(self._pages, parent=self)

    def export_report(self):
        if not self._pages:
            self._show_msg("Export PDF", "No report to export. Please generate the report first.")
            return
        default_name = f"{self.window_title_text.replace(' ', '_').lower()}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {self.window_title_text} PDF",
            default_name,
            "PDF Files (*.pdf)",
        )
        if file_path:
            success = print_or_export_report_pages(self._pages, output_pdf_path=file_path, parent=self)
            if success:
                self._show_msg("Export PDF", f"Report successfully exported to:\n{file_path}")

    def _show_msg(self, title: str, text: str):
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QMessageBox.information(self, title, text)

    def refresh_theme(self):
        p = theme.theme_manager.palette()
        is_dark = p.get("mode") == "dark" or p.get("bg", "").lower() in ("#1e1e1e", "#121212", "#222222")

        panel_bg = p["surface"] if is_dark else "#E8EFF7"
        panel_border = p["border"] if is_dark else "#B0C4DE"
        label_color = p["accent"] if is_dark else "#003366"

        self.filter_panel.setStyleSheet(
            f"QFrame {{ background-color: {panel_bg}; border-left: 1px solid {panel_border}; }}"
            f"QLabel {{ color: {p['text']}; font-size: 12px; font-weight: bold; background: transparent; }}"
            f"QSpinBox {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 2px; padding: 4px; font-size: 12px; }}"
            f"QComboBox {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 2px; padding: 4px; font-size: 12px; }}"
            f"QCheckBox {{ color: {p['text']}; font-size: 12px; font-weight: bold; background: transparent; }}"
            f"QPushButton {{ background-color: {p['accent']}; color: white; border: none; border-radius: 3px; padding: 7px 12px; font-size: 13px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
            f"QPushButton:disabled {{ background-color: {'#404040' if is_dark else '#A0B8D0'}; color: {'#707070' if is_dark else '#E0E8F0'}; }}"
        )
        self.lbl_panel_title.setStyleSheet(f"color: {label_color}; font-size: 14px; font-weight: bold; margin-bottom: 6px;")

        workspace_bg = QColor("#303030") if is_dark else QColor("#808080")
        self.viewer.canvas.set_workspace_bg(workspace_bg)
        self.viewer.scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color: {'#303030' if is_dark else '#808080'}; border: none; }}"
        )


# ══════════════════════════════════════════════════════════════════════
# 1. Items (All) Stock Report
# ══════════════════════════════════════════════════════════════════════

class ItemsAllStockPage(_BaseStockReportPage):
    """Items (All) Stock Report screen with near-expiry and expired item controls."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Item Stock Report", "Items (All) Stock Report", parent)

    def _setup_filters(self):
        # 1. Near to Expiry Days
        self.lbl_near_expiry = QLabel("Near to Expiry Days :")
        self.fp_layout.addWidget(self.lbl_near_expiry)

        self.spin_near_expiry = QSpinBox()
        self.spin_near_expiry.setRange(0, 9999)
        self.spin_near_expiry.setValue(0)
        self.fp_layout.addWidget(self.spin_near_expiry)

        # 2. Expired Items Includes checkbox
        self.chk_expired = QCheckBox("Expired Items Includes :")
        self.chk_expired.setChecked(False)
        self.fp_layout.addWidget(self.chk_expired)

        # 3. Hint box (yellow/amber callout matching Pharma-WINNER screenshot)
        self.hint_box = QFrame()
        self.hint_box.setStyleSheet(
            "QFrame { background-color: #FFFFE0; border: 1px solid #E6DB55; border-radius: 3px; padding: 4px; }"
            "QLabel { color: #555500; font-size: 11px; font-weight: normal; background: transparent; }"
        )
        hint_layout = QHBoxLayout(self.hint_box)
        hint_layout.setContentsMargins(6, 6, 6, 6)
        lbl_hint = QLabel("▶ Near to Expiry Days 0 (Zero) For All Items Stock")
        lbl_hint.setWordWrap(True)
        hint_layout.addWidget(lbl_hint)
        self.fp_layout.addWidget(self.hint_box)

        self.fp_layout.addSpacing(6)

        # 4. Show Report Button
        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.clicked.connect(self.generate_report)
        self.fp_layout.addWidget(self.btn_show_report)

        # 5. Print Button
        self.btn_print = QPushButton("Print")
        self.btn_print.setEnabled(False)
        self.btn_print.clicked.connect(self.print_report)
        self.fp_layout.addWidget(self.btn_print)

        # 6. Export PDF Button
        self.btn_export = QPushButton("Export PDF")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_report)
        self.fp_layout.addWidget(self.btn_export)

        # Auto-load report initially
        self.generate_report()

    def generate_report(self):
        near_days = self.spin_near_expiry.value()
        inc_expired = self.chk_expired.isChecked()

        rows = StockReportsDAO.get_items_all_stock(
            near_expiry_days=near_days,
            include_expired=inc_expired,
        )

        store_name, store_addr = get_default_store_identity()
        today_str = date.today().strftime("%d/%m/%Y")
        header = ReportHeaderData(
            store_name=store_name or "SHREE SAMARTH MEDICAL AND GEN STORE",
            store_address=store_addr or "GHORPADE HOSPITAL, RAHURI",
            header_line_1=f"ITEM STOCK REPORT ON {today_str}",
            header_line_2="",
        )

        # Column widths summing to 724.0 px (A4 portrait content width)
        widths = [35.0, 185.0, 60.0, 85.0, 75.0, 55.0, 55.0, 55.0, 55.0, 64.0]
        cols = ["SrNo", "Item Name", "Unit", "Batch No", "Expiry", "PurQty", "SaleQty", "BalQty", "NetRate", "Pur.Value"]
        aligns = ["center", "left", "left", "left", "center", "right", "right", "right", "right", "right"]

        table_header = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=20.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header]
        current_item_id: Optional[int] = None
        sr_no = 0
        total_bal = 0.0
        total_pur_val = 0.0

        for r in rows:
            item_id = r.get("item_id")
            if item_id != current_item_id:
                sr_no += 1
                item_sr = str(sr_no)
                item_name = r.get("item_name", "")
                unit_name = r.get("unit_name", "")
                current_item_id = item_id
            else:
                item_sr = ""
                item_name = ""
                unit_name = ""

            bal_qty = float(r.get("bal_qty", 0.0))
            pur_val = float(r.get("pur_value", 0.0))
            total_bal += bal_qty
            total_pur_val += pur_val

            cells = [
                item_sr,
                item_name,
                unit_name,
                r.get("batch_no", ""),
                r.get("expiry_formatted", ""),
                fmt_qty(r.get("pur_qty", 0.0)),
                fmt_qty_dash(r.get("sale_qty", 0.0)),
                fmt_qty(bal_qty),
                f"{r.get('net_rate', 0.0):.2f}",
                f"{pur_val:.2f}",
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.DATA_ROW,
                    height=18.0,
                    data={"cells": cells, "widths": widths, "aligns": aligns},
                )
            )

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=40.0,
                    data={"message": "No stock records found for the selected criteria."},
                )
            )
        else:
            # Grand Total row matching columns
            # Prefix cols 0..6: 550.0 px
            prefix_w = sum(widths[:7])
            custom_cells = [
                (prefix_w, "Grand Total :", "right"),
                (widths[7], fmt_qty(total_bal), "right"),
                (widths[8], "", "center"),
                (widths[9], f"{total_pur_val:.2f}", "right"),
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=20.0,
                    data={"custom_cells": custom_cells},
                )
            )

        self._pages = paginate_stock_blocks(header, blocks, table_header)
        self.viewer.set_pages(self._pages)
        has_pages = bool(rows)
        self.btn_print.setEnabled(has_pages)
        self.btn_export.setEnabled(has_pages)


# ══════════════════════════════════════════════════════════════════════
# 2. Companywise Item Stock Report
# ══════════════════════════════════════════════════════════════════════

class CompanywiseItemStockPage(_BaseStockReportPage):
    """Companywise Item Stock Report with company selector and item subtotal groups."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Companywise Item Stock Report", "Companywise Stock Report", parent)

    def _setup_filters(self):
        self.lbl_company = QLabel("Company :")
        self.fp_layout.addWidget(self.lbl_company)

        self.cbo_company = QComboBox()
        self.cbo_company.setEditable(True)
        self.cbo_company.setInsertPolicy(QComboBox.NoInsert)
        if self.cbo_company.completer():
            self.cbo_company.completer().setCaseSensitivity(Qt.CaseInsensitive)
            self.cbo_company.completer().setFilterMode(Qt.MatchContains)
        self.fp_layout.addWidget(self.cbo_company)

        self._populate_companies()

        self.fp_layout.addSpacing(6)

        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.clicked.connect(self.generate_report)
        self.fp_layout.addWidget(self.btn_show_report)

        self.btn_print = QPushButton("Print")
        self.btn_print.setEnabled(False)
        self.btn_print.clicked.connect(self.print_report)
        self.fp_layout.addWidget(self.btn_print)

        self.btn_export = QPushButton("Export PDF")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_report)
        self.fp_layout.addWidget(self.btn_export)

        if self.cbo_company.count() > 0:
            self.generate_report()

    def _populate_companies(self):
        companies = StockReportsDAO.get_companies()
        self.cbo_company.clear()
        for c in companies:
            self.cbo_company.addItem(c["company_name"], c["id"])

    def get_selected_company_id(self) -> Optional[int]:
        idx = self.cbo_company.currentIndex()
        text = self.cbo_company.currentText().strip()
        if idx >= 0 and self.cbo_company.itemText(idx).strip().lower() == text.lower():
            return self.cbo_company.itemData(idx)
        # Search match by text
        for i in range(self.cbo_company.count()):
            if self.cbo_company.itemText(i).strip().lower() == text.lower():
                return self.cbo_company.itemData(i)
        return None

    def generate_report(self):
        comp_id = self.get_selected_company_id()
        company_name = self.cbo_company.currentText().strip()

        if not comp_id:
            self.viewer.set_pages([])
            self.btn_print.setEnabled(False)
            self.btn_export.setEnabled(False)
            return

        rows = StockReportsDAO.get_companywise_item_stock(comp_id)

        store_name, store_addr = get_default_store_identity()
        header = ReportHeaderData(
            store_name=store_name or "SHREE SAMARTH MEDICAL AND GEN STORE",
            store_address=store_addr or "GHORPADE HOSPITAL, RAHURI",
            header_line_1="Companywise Item Stock Report",
            header_line_2=f"Company : {company_name}",
        )

        widths = [35.0, 180.0, 55.0, 80.0, 70.0, 55.0, 55.0, 64.0, 60.0, 70.0]
        cols = ["SrNo", "Item Name", "Unit", "Batch No", "Expiry", "Stock", "NetRate", "Pur.Value", "MRP", "SalesValue"]
        aligns = ["center", "left", "left", "left", "center", "right", "right", "right", "right", "right"]

        table_header = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=20.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header]

        # Group by item_id
        items_dict: Dict[int, List[dict]] = {}
        for r in rows:
            items_dict.setdefault(r["item_id"], []).append(r)

        sr_no = 0
        grand_pur_val = 0.0
        grand_sales_val = 0.0

        for item_id, item_batches in items_dict.items():
            sr_no += 1
            first_b = item_batches[0]
            item_name = first_b.get("item_name", "")
            unit_name = first_b.get("unit_name", "")

            item_stock = 0.0
            item_pur_val = 0.0
            item_sales_val = 0.0

            for b_idx, b in enumerate(item_batches):
                stock = float(b.get("stock_qty", 0.0))
                p_val = float(b.get("pur_value", 0.0))
                s_val = float(b.get("sales_value", 0.0))

                item_stock += stock
                item_pur_val += p_val
                item_sales_val += s_val
                grand_pur_val += p_val
                grand_sales_val += s_val

                b_sr = str(sr_no) if b_idx == 0 else ""
                b_name = item_name if b_idx == 0 else ""
                b_unit = unit_name if b_idx == 0 else ""

                cells = [
                    b_sr,
                    b_name,
                    b_unit,
                    b.get("batch_no", ""),
                    b.get("expiry_formatted", ""),
                    fmt_qty(stock),
                    f"{b.get('net_rate', 0.0):.2f}",
                    f"{p_val:.2f}",
                    f"{b.get('mrp', 0.0):.2f}",
                    f"{s_val:.2f}",
                ]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=18.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            # Item subtotal block matching screenshot: "<ITEM_NAME> <UNIT> Total :   <Stock>   <Pur.Value>   <SalesValue>"
            prefix_w = sum(widths[:5])
            subtotal_label = f"{item_name} {unit_name} Total :" if unit_name else f"{item_name} Total :"
            subtotal_cells = [
                (prefix_w, subtotal_label, "right"),
                (widths[5], fmt_qty(item_stock), "right"),
                (widths[6], "", "center"),
                (widths[7], f"{item_pur_val:.2f}", "right"),
                (widths[8], "", "center"),
                (widths[9], f"{item_sales_val:.2f}", "right"),
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.STOCK_SUBTOTAL,
                    height=18.0,
                    data={"custom_cells": subtotal_cells},
                )
            )

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=40.0,
                    data={"message": f"No active stock for {company_name}."},
                )
            )
        else:
            # Grand Total block matching screenshot: Grand total under Pur.Value and SalesValue
            prefix_w = sum(widths[:7])
            grand_cells = [
                (prefix_w, "Grand Total :", "right"),
                (widths[7], f"{grand_pur_val:.2f}", "right"),
                (widths[8], "", "center"),
                (widths[9], f"{grand_sales_val:.2f}", "right"),
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=20.0,
                    data={"custom_cells": grand_cells},
                )
            )

        self._pages = paginate_stock_blocks(header, blocks, table_header)
        self.viewer.set_pages(self._pages)
        has_pages = bool(rows)
        self.btn_print.setEnabled(has_pages)
        self.btn_export.setEnabled(has_pages)


# ══════════════════════════════════════════════════════════════════════
# 3. Expired Item List
# ══════════════════════════════════════════════════════════════════════

class ExpiredItemListPage(_BaseStockReportPage):
    """Expired Item Stock Report page with Expired Days filter."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Expired Item Stock Report", "Expired Items Stock", parent)

    def _setup_filters(self):
        self.lbl_expired_days = QLabel("Expired Days :")
        self.fp_layout.addWidget(self.lbl_expired_days)

        self.spin_expired_days = QSpinBox()
        self.spin_expired_days.setRange(0, 9999)
        self.spin_expired_days.setValue(0)
        self.fp_layout.addWidget(self.spin_expired_days)

        self.hint_box = QFrame()
        self.hint_box.setStyleSheet(
            "QFrame { background-color: #FFFFE0; border: 1px solid #E6DB55; border-radius: 3px; padding: 4px; }"
            "QLabel { color: #555500; font-size: 11px; font-weight: normal; background: transparent; }"
        )
        hint_layout = QHBoxLayout(self.hint_box)
        hint_layout.setContentsMargins(6, 6, 6, 6)
        lbl_hint = QLabel("▶ Expiry Days 0 (Zero) For All Expired Items")
        lbl_hint.setWordWrap(True)
        hint_layout.addWidget(lbl_hint)
        self.fp_layout.addWidget(self.hint_box)

        self.fp_layout.addSpacing(6)

        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.clicked.connect(self.generate_report)
        self.fp_layout.addWidget(self.btn_show_report)

        self.btn_print = QPushButton("Print")
        self.btn_print.setEnabled(False)
        self.btn_print.clicked.connect(self.print_report)
        self.fp_layout.addWidget(self.btn_print)

        self.btn_export = QPushButton("Export PDF")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_report)
        self.fp_layout.addWidget(self.btn_export)

        self.generate_report()

    def generate_report(self):
        exp_days = self.spin_expired_days.value()
        rows = StockReportsDAO.get_expired_item_list(expired_days=exp_days)

        store_name, store_addr = get_default_store_identity()
        today_str = date.today().strftime("%d/%m/%Y")
        header = ReportHeaderData(
            store_name=store_name or "SHREE SAMARTH MEDICAL AND GEN STORE",
            store_address=store_addr or "GHORPADE HOSPITAL, RAHURI",
            header_line_1=f"EXPIRED ITEM STOCK REPORT ON {today_str}",
            header_line_2="",
        )

        widths = [35.0, 185.0, 60.0, 85.0, 75.0, 55.0, 55.0, 55.0, 55.0, 64.0]
        cols = ["SrNo", "Item Name", "Unit", "Batch No", "Expiry", "PurQty", "SaleQty", "BalQty", "NetRate", "Pur.Value"]
        aligns = ["center", "left", "left", "left", "center", "right", "right", "right", "right", "right"]

        table_header = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=20.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header]
        current_item_id: Optional[int] = None
        sr_no = 0
        total_bal = 0.0
        total_pur_val = 0.0

        for r in rows:
            item_id = r.get("item_id")
            if item_id != current_item_id:
                sr_no += 1
                item_sr = str(sr_no)
                item_name = r.get("item_name", "")
                unit_name = r.get("unit_name", "")
                current_item_id = item_id
            else:
                item_sr = ""
                item_name = ""
                unit_name = ""

            bal_qty = float(r.get("bal_qty", 0.0))
            pur_val = float(r.get("pur_value", 0.0))
            total_bal += bal_qty
            total_pur_val += pur_val

            cells = [
                item_sr,
                item_name,
                unit_name,
                r.get("batch_no", ""),
                r.get("expiry_formatted", ""),
                fmt_qty(r.get("pur_qty", 0.0)),
                fmt_qty_dash(r.get("sale_qty", 0.0)),
                fmt_qty(bal_qty),
                f"{r.get('net_rate', 0.0):.2f}",
                f"{pur_val:.2f}",
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.DATA_ROW,
                    height=18.0,
                    data={"cells": cells, "widths": widths, "aligns": aligns},
                )
            )

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=40.0,
                    data={"message": "No expired items found."},
                )
            )
        else:
            prefix_w = sum(widths[:7])
            custom_cells = [
                (prefix_w, "Grand Total :", "right"),
                (widths[7], fmt_qty(total_bal), "right"),
                (widths[8], "", "center"),
                (widths[9], f"{total_pur_val:.2f}", "right"),
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=20.0,
                    data={"custom_cells": custom_cells},
                )
            )

        self._pages = paginate_stock_blocks(header, blocks, table_header)
        self.viewer.set_pages(self._pages)
        has_pages = bool(rows)
        self.btn_print.setEnabled(has_pages)
        self.btn_export.setEnabled(has_pages)


# ══════════════════════════════════════════════════════════════════════
# 4. Item List
# ══════════════════════════════════════════════════════════════════════

class ItemListPage(_BaseStockReportPage):
    """Item List Report showing all item master records, Rate, MRP, and current Balance Qty."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Item List Report", "Item List Report", parent)

    def _setup_filters(self):
        self.lbl_company = QLabel("Company (Optional) :")
        self.fp_layout.addWidget(self.lbl_company)

        self.cbo_company = QComboBox()
        self.cbo_company.setEditable(True)
        self.cbo_company.setInsertPolicy(QComboBox.NoInsert)
        if self.cbo_company.completer():
            self.cbo_company.completer().setCaseSensitivity(Qt.CaseInsensitive)
            self.cbo_company.completer().setFilterMode(Qt.MatchContains)
        self.fp_layout.addWidget(self.cbo_company)

        self._populate_companies()

        self.fp_layout.addSpacing(6)

        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.clicked.connect(self.generate_report)
        self.fp_layout.addWidget(self.btn_show_report)

        self.btn_print = QPushButton("Print")
        self.btn_print.setEnabled(False)
        self.btn_print.clicked.connect(self.print_report)
        self.fp_layout.addWidget(self.btn_print)

        self.btn_export = QPushButton("Export PDF")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_report)
        self.fp_layout.addWidget(self.btn_export)

        self.generate_report()

    def _populate_companies(self):
        self.cbo_company.clear()
        self.cbo_company.addItem("-- All Companies --", None)
        companies = StockReportsDAO.get_companies()
        for c in companies:
            self.cbo_company.addItem(c["company_name"], c["id"])

    def get_selected_company_id(self) -> Optional[int]:
        idx = self.cbo_company.currentIndex()
        if idx > 0:
            return self.cbo_company.itemData(idx)
        text = self.cbo_company.currentText().strip()
        if text and not text.startswith("--"):
            for i in range(1, self.cbo_company.count()):
                if self.cbo_company.itemText(i).strip().lower() == text.lower():
                    return self.cbo_company.itemData(i)
        return None

    def generate_report(self):
        comp_id = self.get_selected_company_id()
        rows = StockReportsDAO.get_item_list(company_id=comp_id)

        store_name, store_addr = get_default_store_identity()
        today_str = date.today().strftime("%d/%m/%Y")
        comp_text = f" | {self.cbo_company.currentText()}" if comp_id else ""
        header = ReportHeaderData(
            store_name=store_name or "SHREE SAMARTH MEDICAL AND GEN STORE",
            store_address=store_addr or "GHORPADE HOSPITAL, RAHURI",
            header_line_1=f"ITEM LIST REPORT ON {today_str}{comp_text}",
            header_line_2="",
        )

        widths = [50.0, 374.0, 100.0, 100.0, 100.0]
        cols = ["Sr No", "Item Name", "Rate", "MRP", "Balance Qty"]
        aligns = ["center", "left", "right", "right", "right"]

        table_header = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=20.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header]
        total_bal = 0.0

        for idx, r in enumerate(rows, start=1):
            bal = float(r.get("bal_qty", 0.0))
            total_bal += bal
            cells = [
                str(idx),
                r.get("item_name", ""),
                f"{r.get('rate', 0.0):.2f}",
                f"{r.get('mrp', 0.0):.2f}",
                fmt_qty(bal),
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.DATA_ROW,
                    height=18.0,
                    data={"cells": cells, "widths": widths, "aligns": aligns},
                )
            )

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=40.0,
                    data={"message": "No items found."},
                )
            )
        else:
            prefix_w = sum(widths[:4])
            custom_cells = [
                (prefix_w, f"Total Items: {len(rows)}   Grand Total :", "right"),
                (widths[4], fmt_qty(total_bal), "right"),
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=20.0,
                    data={"custom_cells": custom_cells},
                )
            )

        self._pages = paginate_stock_blocks(header, blocks, table_header)
        self.viewer.set_pages(self._pages)
        has_pages = bool(rows)
        self.btn_print.setEnabled(has_pages)
        self.btn_export.setEnabled(has_pages)
