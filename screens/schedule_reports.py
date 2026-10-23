"""Schedule H1 and NRX Crystal Reports screens.

Implements all 12 cascading schedule reports:
- Schedule > H1 > Sales:
    1. Datewise Schedule
    2. Itemwise Schedule
    3. All Items Schedule
- Schedule > H1 > Purchase:
    4. Datewise Schedule
    5. Itemwise Schedule
    6. All Items Schedule
- Schedule > NRX > Sales:
    7. Datewise Schedule
    8. Itemwise Schedule
    9. All Items Schedule
- Schedule > NRX > Purchase:
    10. Datewise Schedule
    11. Itemwise Schedule
    12. All Items Schedule
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.doc_formatter import format_sales_bill_number
from database.schedule_reports_dao import ScheduleReportsDAO
from database import financial_year
from ui import theme
from ui.crystal_report_viewer import (
    BlockKind,
    CONTENT_WIDTH_LANDSCAPE,
    CrystalReportViewer,
    PAGE_HEIGHT_LANDSCAPE,
    PAGE_WIDTH_LANDSCAPE,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    fmt_amt,
    fmt_qty,
    print_or_export_report_pages,
)
from ui.theme import palette

STORE_LINE_1 = "SHREE SAMARTH MEDICAL AND GEN STORE"
STORE_LINE_2 = "GHORPADE HOSPITAL, RAHURI"

MAX_PAGE_BODY_HEIGHT_LANDSCAPE = 635.0


def _format_dmy(date_val: str) -> str:
    """Format YYYY-MM-DD to dd/MM/yyyy."""
    if not date_val:
        return ""
    clean = str(date_val).strip()
    try:
        parts = clean.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return f"{parts[2].zfill(2)}/{parts[1].zfill(2)}/{parts[0]}"
        parts_slash = clean.split("/")
        if len(parts_slash) == 3 and len(parts_slash[2]) == 4:
            return f"{parts_slash[0].zfill(2)}/{parts_slash[1].zfill(2)}/{parts_slash[2]}"
    except Exception:
        pass
    return clean


def _format_dmy_dash(date_val: str) -> str:
    """Format YYYY-MM-DD to dd-MM-yyyy for headers."""
    if not date_val:
        return ""
    clean = str(date_val).strip()
    try:
        parts = clean.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return f"{parts[2].zfill(2)}-{parts[1].zfill(2)}-{parts[0]}"
    except Exception:
        pass
    return clean.replace("/", "-")


def _format_expiry_display(exp_val: str) -> str:
    """Format expiry date to MM/YY or dd/MM/yyyy."""
    if not exp_val:
        return ""
    clean = str(exp_val).strip()
    try:
        parts = clean.split("-")
        if len(parts) >= 2:
            yy = parts[0][-2:]
            mm = parts[1].zfill(2)
            return f"{mm}/{yy}"
    except Exception:
        pass
    return clean


def _make_total_custom_cells(
    prefix_width: float,
    label: str,
    total_col_specs: List[Tuple[float, str]],
) -> List[Dict[str, Any]]:
    """Build custom_cells for ITEM_SUBTOTAL or GRAND_TOTAL blocks."""
    cells: List[Dict[str, Any]] = [{"width": prefix_width, "text": label, "align": "right", "is_bold": True}]
    for col_w, col_val in total_col_specs:
        cells.append({"width": col_w, "text": str(col_val), "align": "right", "is_bold": True})
    return cells


def paginate_schedule_blocks(
    header: ReportHeaderData,
    blocks: List[ReportBlock],
    table_header_block: Optional[ReportBlock] = None,
    orientation: str = "landscape",
) -> List[ReportPage]:
    """Split schedule report blocks across A4 landscape pages."""
    if not blocks:
        empty_page = ReportPage(
            page_num=1,
            total_pages=1,
            header=header,
            blocks=[],
            orientation=orientation,
            page_width=PAGE_WIDTH_LANDSCAPE,
            page_height=PAGE_HEIGHT_LANDSCAPE,
        )
        return [empty_page]

    page_w = PAGE_WIDTH_LANDSCAPE
    page_h = PAGE_HEIGHT_LANDSCAPE
    max_h = MAX_PAGE_BODY_HEIGHT_LANDSCAPE

    pages: List[ReportPage] = []
    current_blocks: List[ReportBlock] = []
    current_h = 0.0

    for block in blocks:
        needed_h = 45.0 if block.kind in (BlockKind.GROUP_HEADER, BlockKind.ITEM_SUBTOTAL) else block.height
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
# Base Schedule Report Page
# ══════════════════════════════════════════════════════════════════════

class _BaseScheduleReportPage(QWidget):
    """Common foundation for Crystal-Reports-style schedule report screens."""

    close_requested = Signal()

    def __init__(
        self,
        window_title: str,
        panel_title: str,
        schedule_type: str = "H1",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.window_title_text = window_title
        self.panel_title_text = panel_title
        self.schedule_type = schedule_type.upper().strip()
        self._pages: List[ReportPage] = []
        self._history_financial_year: Optional[Dict] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Title Bar
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

        # 2. Main Splitter: Left (Viewer) + Right (Filter Panel)
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
        self.filter_panel.setMinimumWidth(250)
        self.filter_panel.setMaximumWidth(340)
        self.fp_layout = QVBoxLayout(self.filter_panel)
        self.fp_layout.setContentsMargins(14, 14, 14, 14)
        self.fp_layout.setSpacing(10)

        self.lbl_panel_title = QLabel(self.panel_title_text)
        self.lbl_panel_title.setStyleSheet("color: #003366; font-size: 14px; font-weight: bold; margin-bottom: 6px;")
        self.lbl_panel_title.setWordWrap(True)
        self.fp_layout.addWidget(self.lbl_panel_title)

        # Date pickers
        lbl_from = QLabel("From Date:")
        lbl_from.setStyleSheet("font-weight: bold;")
        self.fp_layout.addWidget(lbl_from)
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.from_date_edit)

        lbl_to = QLabel("To Date:")
        lbl_to.setStyleSheet("font-weight: bold;")
        self.fp_layout.addWidget(lbl_to)
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.to_date_edit)

        # Setup initial dates from financial year
        self._init_dates()

        # Specific filters (e.g. Item combo)
        self._setup_specific_filters()

        # Validation message
        self.lbl_msg = QLabel("")
        self.lbl_msg.setStyleSheet("color: #C00000; font-size: 11px; font-weight: bold; background: transparent;")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setVisible(False)
        self.fp_layout.addWidget(self.lbl_msg)

        self.fp_layout.addSpacing(6)

        # Action Buttons
        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.setFixedHeight(30)
        self.btn_show_report.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; font-weight: bold; border-radius: 3px; }"
            "QPushButton:hover { background-color: #1B5E20; }"
        )
        self.btn_show_report.clicked.connect(self.generate_report)
        self.fp_layout.addWidget(self.btn_show_report)

        self.btn_panel_print = QPushButton("Print")
        self.btn_panel_print.setFixedHeight(28)
        self.btn_panel_print.setEnabled(False)
        self.btn_panel_print.clicked.connect(self.print_report)
        self.fp_layout.addWidget(self.btn_panel_print)

        self.fp_layout.addStretch()
        self.main_splitter.addWidget(self.filter_panel)

        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 1)
        root.addWidget(self.main_splitter, 1)

        self.refresh_theme()

    def _init_dates(self):
        """Default From to start of active FY (01/04/2026), To to today."""
        today = QDate.currentDate()
        active = financial_year.get_active_financial_year()
        if active and active.get("start_date"):
            qd = QDate.fromString(active["start_date"], "yyyy-MM-dd")
            if qd.isValid():
                self.from_date_edit.setDate(qd)
            else:
                self.from_date_edit.setDate(QDate(today.year() if today.month() >= 4 else today.year() - 1, 4, 1))
        else:
            self.from_date_edit.setDate(QDate(today.year() if today.month() >= 4 else today.year() - 1, 4, 1))

        self.to_date_edit.setDate(today)

    def _setup_specific_filters(self):
        """Subclasses can add additional filters like item combo box."""
        pass

    def _on_close(self):
        self.close_requested.emit()

    def set_history_financial_year(self, year: Optional[Dict]):
        self._history_financial_year = dict(year) if year else None
        if self._history_financial_year and self._history_financial_year.get("start_date"):
            sd = QDate.fromString(self._history_financial_year["start_date"], "yyyy-MM-dd")
            if sd.isValid():
                self.from_date_edit.setDate(sd)
            ed = QDate.fromString(self._history_financial_year.get("end_date", ""), "yyyy-MM-dd")
            if ed.isValid():
                self.to_date_edit.setDate(ed)

    def validate_dates(self) -> bool:
        if self.from_date_edit.date() > self.to_date_edit.date():
            self.lbl_msg.setText("From Date cannot be after To Date.")
            self.lbl_msg.setVisible(True)
            QMessageBox.warning(self, "Validation Error", "From Date cannot be after To Date.")
            return False
        self.lbl_msg.setText("")
        self.lbl_msg.setVisible(False)
        return True

    def generate_report(self):
        """Override in subclasses."""
        pass

    def print_report(self):
        if not self._pages:
            return
        print_or_export_report_pages(
            self._pages,
            parent=self,
        )

    def export_report(self):
        if not self._pages:
            return
        safe_title = self.window_title_text.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")
        default_name = f"{safe_title}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", default_name, "PDF Files (*.pdf)")
        if not path:
            return
        print_or_export_report_pages(
            self._pages,
            parent=self,
            output_pdf_path=path,
        )

    def refresh_theme(self):
        p = palette()
        is_night = p.get("bg") == "#1a2530" or p.get("bg") != "#ffffff"
        bg_col = "#243342" if is_night else "#F0F4F8"
        text_col = "#FFFFFF" if is_night else "#002B49"
        border_col = "#3a4d60" if is_night else "#C5D5E5"

        self.filter_panel.setStyleSheet(
            f"QFrame {{ background-color: {bg_col}; border-left: 1px solid {border_col}; }}"
            f"QLabel {{ color: {text_col}; font-family: Segoe UI, Arial; }}"
            f"QDateEdit, QComboBox {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 2px; padding: 3px; font-size: 11px; }}"
        )
        self.lbl_panel_title.setStyleSheet(f"color: {p['accent'] if is_night else '#003366'}; font-size: 14px; font-weight: bold; margin-bottom: 6px;")


# ══════════════════════════════════════════════════════════════════════
# Report A: Sales - Datewise
# ══════════════════════════════════════════════════════════════════════

class ScheduleSalesDatewisePage(_BaseScheduleReportPage):
    """Report A: Sales Datewise Schedule Report (H1 or NRX)."""

    def __init__(self, schedule_type: str = "H1", parent: Optional[QWidget] = None):
        st = schedule_type.upper().strip()
        super().__init__(
            window_title=f"Sales Datewise Sheduled {st} Report",
            panel_title=f"Sales Datewise Sheduled {st}",
            schedule_type=st,
            parent=parent,
        )

    def generate_report(self):
        if not self.validate_dates():
            return

        from_str = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_str = self.to_date_edit.date().toString("yyyy-MM-dd")
        fmt_from = _format_dmy_dash(from_str)
        fmt_to = _format_dmy_dash(to_str)

        rows = ScheduleReportsDAO.get_sales_schedule(from_str, to_str, self.schedule_type)

        header = ReportHeaderData(
            store_name=STORE_LINE_1,
            store_address=STORE_LINE_2,
            header_line_1=f"SALES DATEWISE SHEDULED {self.schedule_type} REPORT",
            header_line_2=f"Report Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            header_line_3=f"Sales Sheduled {self.schedule_type} Report for {fmt_from} To {fmt_to}",
        )

        cols = ["SrNo", "Date", "BillNo", "PatientName", "Address", "Unit", "Pack", "ItemName", "BatchNo", "ExpiryDate", "Qty"]
        widths = [45.0, 80.0, 85.0, 175.0, 135.0, 55.0, 55.0, 200.0, 90.0, 70.0, 63.0]
        aligns = ["center", "center", "left", "left", "left", "center", "center", "left", "left", "center", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        tot_qty = 0.0
        if not rows:
            self.lbl_msg.setText("No records found.")
            self.lbl_msg.setVisible(True)
            self.btn_panel_print.setEnabled(True)
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=36.0,
                    data={"message": "No records found for the selected period."},
                )
            )
        else:
            self.lbl_msg.setVisible(False)
            self.btn_panel_print.setEnabled(True)

            for idx, r in enumerate(rows, 1):
                qty_val = float(r.get("qty") or 0.0)
                tot_qty += qty_val

                raw_bill = str(r.get("bill_no") or "")
                bill_no = format_sales_bill_number(raw_bill, patient_name=r.get("patient_name"))

                row_vals = [
                    str(idx),
                    _format_dmy(r.get("sale_date", "")),
                    bill_no,
                    str(r.get("patient_name") or ""),
                    str(r.get("address") or ""),
                    str(r.get("unit_name") or ""),
                    str(r.get("pack_size") or ""),
                    str(r.get("item_name") or ""),
                    str(r.get("batch_no") or ""),
                    _format_expiry_display(str(r.get("expiry") or "")),
                    fmt_qty(qty_val),
                ]

                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=20.0,
                        data={"cells": row_vals, "widths": widths, "aligns": aligns},
                    )
                )

        # Grand Total Row
        tot_cells = ["", "", "", "", "", "", "", "", "", "Total :", fmt_qty(tot_qty)]
        tot_aligns = ["center"] * 9 + ["right", "right"]
        prefix_w = sum(widths[:-1])
        custom_cells = _make_total_custom_cells(prefix_w, "Total :", [(widths[-1], fmt_qty(tot_qty))])
        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "cells": tot_cells,
                    "widths": widths,
                    "aligns": tot_aligns,
                    "custom_cells": custom_cells,
                    "qty_str": fmt_qty(tot_qty),
                    "amt_str": fmt_qty(tot_qty),
                    "label": "Total :",
                },
            )
        )

        self._pages = paginate_schedule_blocks(header, blocks, table_header_block, orientation="landscape")
        self.viewer.set_pages(self._pages)


# ══════════════════════════════════════════════════════════════════════
# Report B: Sales - Itemwise
# ══════════════════════════════════════════════════════════════════════

class ScheduleSalesItemwisePage(_BaseScheduleReportPage):
    """Report B: Sales Itemwise Schedule Report (H1 or NRX)."""

    def __init__(self, schedule_type: str = "H1", parent: Optional[QWidget] = None):
        st = schedule_type.upper().strip()
        super().__init__(
            window_title=f"Sales Itemwise Sheduled {st} Report",
            panel_title=f"Sales Itemwise Sheduled {st}",
            schedule_type=st,
            parent=parent,
        )

    def _setup_specific_filters(self):
        lbl_item = QLabel("Item:")
        lbl_item.setStyleSheet("font-weight: bold;")
        self.fp_layout.addWidget(lbl_item)

        self.item_combo = QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.setMaxVisibleItems(15)

        items = ScheduleReportsDAO.get_scheduled_items(self.schedule_type)
        self.item_combo.addItem("-- Select Item --", None)
        item_names = []
        for itm in items:
            name = str(itm.get("item_name") or "").strip()
            if name:
                self.item_combo.addItem(name, itm.get("id"))
                item_names.append(name)

        if self.item_combo.lineEdit():
            completer = QCompleter(item_names, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.item_combo.lineEdit().setCompleter(completer)

        self.fp_layout.addWidget(self.item_combo)

    def generate_report(self):
        if not self.validate_dates():
            return

        from_str = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_str = self.to_date_edit.date().toString("yyyy-MM-dd")
        fmt_from = _format_dmy_dash(from_str)
        fmt_to = _format_dmy_dash(to_str)

        item_id = self.item_combo.currentData()
        item_name = self.item_combo.currentText().strip()

        rows = ScheduleReportsDAO.get_sales_schedule(
            from_str, to_str, self.schedule_type, item_id=item_id
        )

        sub_header = f"Sales Sheduled {self.schedule_type} Report for {fmt_from} To {fmt_to}"
        if item_id:
            sub_header += f"  |  Item: {item_name}"

        header = ReportHeaderData(
            store_name=STORE_LINE_1,
            store_address=STORE_LINE_2,
            header_line_1=f"SALES ITEMWISE SHEDULED {self.schedule_type} REPORT",
            header_line_2=f"Report Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            header_line_3=sub_header,
        )

        cols = ["SrNo", "Date", "BillNo", "PatientName", "Address", "Unit", "Pack", "ItemName", "BatchNo", "ExpiryDate", "Qty"]
        widths = [45.0, 80.0, 85.0, 175.0, 135.0, 55.0, 55.0, 200.0, 90.0, 70.0, 63.0]
        aligns = ["center", "center", "left", "left", "left", "center", "center", "left", "left", "center", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        tot_qty = 0.0
        if not rows:
            self.lbl_msg.setText("No records found.")
            self.lbl_msg.setVisible(True)
            self.btn_panel_print.setEnabled(True)
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=36.0,
                    data={"message": "No records found for the selected period."},
                )
            )
        else:
            self.lbl_msg.setVisible(False)
            self.btn_panel_print.setEnabled(True)

            for idx, r in enumerate(rows, 1):
                qty_val = float(r.get("qty") or 0.0)
                tot_qty += qty_val

                raw_bill = str(r.get("bill_no") or "")
                bill_no = format_sales_bill_number(raw_bill, patient_name=r.get("patient_name"))

                row_vals = [
                    str(idx),
                    _format_dmy(r.get("sale_date", "")),
                    bill_no,
                    str(r.get("patient_name") or ""),
                    str(r.get("address") or ""),
                    str(r.get("unit_name") or ""),
                    str(r.get("pack_size") or ""),
                    str(r.get("item_name") or ""),
                    str(r.get("batch_no") or ""),
                    _format_expiry_display(str(r.get("expiry") or "")),
                    fmt_qty(qty_val),
                ]

                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=20.0,
                        data={"cells": row_vals, "widths": widths, "aligns": aligns},
                    )
                )

        # Grand Total Row
        tot_cells = ["", "", "", "", "", "", "", "", "", "Total :", fmt_qty(tot_qty)]
        tot_aligns = ["center"] * 9 + ["right", "right"]
        prefix_w = sum(widths[:-1])
        custom_cells = _make_total_custom_cells(prefix_w, "Total :", [(widths[-1], fmt_qty(tot_qty))])
        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "cells": tot_cells,
                    "widths": widths,
                    "aligns": tot_aligns,
                    "custom_cells": custom_cells,
                    "qty_str": fmt_qty(tot_qty),
                    "amt_str": fmt_qty(tot_qty),
                    "label": "Total :",
                },
            )
        )

        self._pages = paginate_schedule_blocks(header, blocks, table_header_block, orientation="landscape")
        self.viewer.set_pages(self._pages)


# ══════════════════════════════════════════════════════════════════════
# Report C: Sales - All Items (Grouped by item)
# ══════════════════════════════════════════════════════════════════════

class ScheduleSalesAllItemsPage(_BaseScheduleReportPage):
    """Report C: Sales Items (All) Schedule Report grouped by item (H1 or NRX)."""

    def __init__(self, schedule_type: str = "H1", parent: Optional[QWidget] = None):
        st = schedule_type.upper().strip()
        super().__init__(
            window_title=f"Sales Items (All) Sheduled {st} Report",
            panel_title=f"Sales Items (All) Sheduled {st}",
            schedule_type=st,
            parent=parent,
        )

    def generate_report(self):
        if not self.validate_dates():
            return

        from_str = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_str = self.to_date_edit.date().toString("yyyy-MM-dd")
        fmt_from = _format_dmy_dash(from_str)
        fmt_to = _format_dmy_dash(to_str)

        rows = ScheduleReportsDAO.get_sales_schedule(
            from_str, to_str, self.schedule_type, grouped_by_item=True
        )

        header = ReportHeaderData(
            store_name=STORE_LINE_1,
            store_address=STORE_LINE_2,
            header_line_1=f"SALES ITEMS (ALL) SHEDULED {self.schedule_type} REPORT",
            header_line_2=f"Report Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            header_line_3=f"Sales Sheduled {self.schedule_type} Report for {fmt_from} To {fmt_to}",
        )

        cols = ["SrNo", "Date", "BillNo", "PatientName", "Address", "Unit", "Pack Size", "BatchNo", "ExpiryDate", "Qty"]
        widths = [45.0, 85.0, 95.0, 220.0, 175.0, 70.0, 70.0, 115.0, 85.0, 93.0]
        aligns = ["center", "center", "left", "left", "left", "center", "center", "left", "center", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        grand_tot_qty = 0.0
        prefix_w = sum(widths[:-1])

        if not rows:
            self.lbl_msg.setText("No records found.")
            self.lbl_msg.setVisible(True)
            self.btn_panel_print.setEnabled(True)
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=36.0,
                    data={"message": "No records found for the selected period."},
                )
            )
        else:
            self.lbl_msg.setVisible(False)
            self.btn_panel_print.setEnabled(True)

            # Group rows by item_name
            groups: dict[str, list[dict]] = {}
            for r in rows:
                itm_name = str(r.get("item_name") or "Unknown Item").strip()
                groups.setdefault(itm_name, []).append(r)

            sr_no = 1

            for itm_name, itm_rows in groups.items():
                # Group Header: "Item Name : <ITEM>"
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.GROUP_HEADER,
                        height=26.0,
                        data={"title": f"Item Name : {itm_name}", "width": CONTENT_WIDTH_LANDSCAPE},
                    )
                )

                item_sub_qty = 0.0
                for r in itm_rows:
                    qty_val = float(r.get("qty") or 0.0)
                    item_sub_qty += qty_val
                    grand_tot_qty += qty_val

                    raw_bill = str(r.get("bill_no") or "")
                    bill_no = format_sales_bill_number(raw_bill, patient_name=r.get("patient_name"))

                    row_vals = [
                        str(sr_no),
                        _format_dmy(r.get("sale_date", "")),
                        bill_no,
                        str(r.get("patient_name") or ""),
                        str(r.get("address") or ""),
                        str(r.get("unit_name") or ""),
                        str(r.get("pack_size") or ""),
                        str(r.get("batch_no") or ""),
                        _format_expiry_display(str(r.get("expiry") or "")),
                        fmt_qty(qty_val),
                    ]

                    blocks.append(
                        ReportBlock(
                            kind=BlockKind.DATA_ROW,
                            height=20.0,
                            data={"cells": row_vals, "widths": widths, "aligns": aligns},
                        )
                    )
                    sr_no += 1

                # Group Subtotal: "Total :" for Qty
                sub_cells = ["", "", "", "", "", "", "", "", "Total :", fmt_qty(item_sub_qty)]
                sub_aligns = ["center"] * 8 + ["right", "right"]
                sub_custom_cells = _make_total_custom_cells(prefix_w, "Total :", [(widths[-1], fmt_qty(item_sub_qty))])
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.ITEM_SUBTOTAL,
                        height=22.0,
                        data={
                            "cells": sub_cells,
                            "widths": widths,
                            "aligns": sub_aligns,
                            "custom_cells": sub_custom_cells,
                            "pay_str": fmt_qty(item_sub_qty),
                            "amt_str": fmt_qty(item_sub_qty),
                            "label": "Total :",
                        },
                    )
                )

        # Grand Total
        tot_cells = ["", "", "", "", "", "", "", "", "Grand Total :", fmt_qty(grand_tot_qty)]
        tot_aligns = ["center"] * 8 + ["right", "right"]
        tot_custom_cells = _make_total_custom_cells(prefix_w, "Grand Total :", [(widths[-1], fmt_qty(grand_tot_qty))])
        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "cells": tot_cells,
                    "widths": widths,
                    "aligns": tot_aligns,
                    "custom_cells": tot_custom_cells,
                    "qty_str": fmt_qty(grand_tot_qty),
                    "amt_str": fmt_qty(grand_tot_qty),
                    "label": "Grand Total :",
                },
            )
        )

        self._pages = paginate_schedule_blocks(header, blocks, table_header_block, orientation="landscape")
        self.viewer.set_pages(self._pages)


# ══════════════════════════════════════════════════════════════════════
# Report D: Purchase - Datewise
# ══════════════════════════════════════════════════════════════════════

class SchedulePurchaseDatewisePage(_BaseScheduleReportPage):
    """Report D: Datewise Purchase Schedule Report (H1 or NRX)."""

    def __init__(self, schedule_type: str = "H1", parent: Optional[QWidget] = None):
        st = schedule_type.upper().strip()
        super().__init__(
            window_title=f"Datewise Purchase Sheduled {st} Report",
            panel_title=f"Datewise Purchase Sheduled {st}",
            schedule_type=st,
            parent=parent,
        )

    def generate_report(self):
        if not self.validate_dates():
            return

        from_str = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_str = self.to_date_edit.date().toString("yyyy-MM-dd")
        fmt_from = _format_dmy_dash(from_str)
        fmt_to = _format_dmy_dash(to_str)

        rows = ScheduleReportsDAO.get_purchase_schedule(from_str, to_str, self.schedule_type)

        header = ReportHeaderData(
            store_name=STORE_LINE_1,
            store_address=STORE_LINE_2,
            header_line_1=f"DATEWISE PURCHASE SHEDULED {self.schedule_type} REPORT",
            header_line_2=f"Report Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            header_line_3=f"Purchase Sheduled {self.schedule_type} Report for {fmt_from} To {fmt_to}",
        )

        cols = ["SrNo", "Inv.Date", "Inv.No", "Supplier", "VhNo", "Vh Date", "Unit", "Pack", "ItemName", "BatchNo", "ExpiryDate", "PurQty", "PurValue"]
        widths = [40.0, 75.0, 75.0, 175.0, 100.0, 75.0, 50.0, 50.0, 175.0, 85.0, 65.0, 43.0, 45.0]
        aligns = ["center", "center", "left", "left", "left", "center", "center", "center", "left", "left", "center", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        tot_qty = 0.0
        tot_val = 0.0
        prefix_w = sum(widths[:-2])

        if not rows:
            self.lbl_msg.setText("No records found.")
            self.lbl_msg.setVisible(True)
            self.btn_panel_print.setEnabled(True)
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=36.0,
                    data={"message": "No records found for the selected period."},
                )
            )
        else:
            self.lbl_msg.setVisible(False)
            self.btn_panel_print.setEnabled(True)

            for idx, r in enumerate(rows, 1):
                pur_qty = float(r.get("pur_qty") or 0.0)
                pur_val = float(r.get("pur_value") or 0.0)
                tot_qty += pur_qty
                tot_val += pur_val

                row_vals = [
                    str(idx),
                    _format_dmy(r.get("inv_date", "")),
                    str(r.get("inv_no") or ""),
                    str(r.get("supplier_name") or ""),
                    str(r.get("vh_no") or ""),
                    _format_dmy(r.get("vh_date", "")),
                    str(r.get("unit_name") or ""),
                    str(r.get("pack_size") or ""),
                    str(r.get("item_name") or ""),
                    str(r.get("batch_no") or ""),
                    _format_expiry_display(str(r.get("expiry") or "")),
                    fmt_qty(pur_qty),
                    str(int(round(pur_val))),  # Whole number in Datewise Purchase report
                ]

                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=20.0,
                        data={"cells": row_vals, "widths": widths, "aligns": aligns},
                    )
                )

        # Grand Total Row
        tot_cells = ["", "", "", "", "", "", "", "", "", "", "Total :", fmt_qty(tot_qty), str(int(round(tot_val)))]
        tot_aligns = ["center"] * 10 + ["right", "right", "right"]
        custom_cells = _make_total_custom_cells(
            prefix_w, "Total :", [(widths[-2], fmt_qty(tot_qty)), (widths[-1], str(int(round(tot_val))))]
        )
        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "cells": tot_cells,
                    "widths": widths,
                    "aligns": tot_aligns,
                    "custom_cells": custom_cells,
                    "qty_str": fmt_qty(tot_qty),
                    "amt_str": str(int(round(tot_val))),
                    "label": "Total :",
                },
            )
        )

        self._pages = paginate_schedule_blocks(header, blocks, table_header_block, orientation="landscape")
        self.viewer.set_pages(self._pages)


# ══════════════════════════════════════════════════════════════════════
# Report E: Purchase - Itemwise
# ══════════════════════════════════════════════════════════════════════

class SchedulePurchaseItemwisePage(_BaseScheduleReportPage):
    """Report E: Itemwise Purchase Schedule Report (H1 or NRX)."""

    def __init__(self, schedule_type: str = "H1", parent: Optional[QWidget] = None):
        st = schedule_type.upper().strip()
        super().__init__(
            window_title=f"Itemwise Purchase Sheduled {st} Report",
            panel_title=f"Itemwise Purchase Sheduled {st}",
            schedule_type=st,
            parent=parent,
        )

    def _setup_specific_filters(self):
        lbl_item = QLabel("Item:")
        lbl_item.setStyleSheet("font-weight: bold;")
        self.fp_layout.addWidget(lbl_item)

        self.item_combo = QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.setMaxVisibleItems(15)

        items = ScheduleReportsDAO.get_scheduled_items(self.schedule_type)
        self.item_combo.addItem("-- Select Item --", None)
        item_names = []
        for itm in items:
            name = str(itm.get("item_name") or "").strip()
            if name:
                self.item_combo.addItem(name, itm.get("id"))
                item_names.append(name)

        if self.item_combo.lineEdit():
            completer = QCompleter(item_names, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.item_combo.lineEdit().setCompleter(completer)

        self.fp_layout.addWidget(self.item_combo)

    def generate_report(self):
        if not self.validate_dates():
            return

        from_str = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_str = self.to_date_edit.date().toString("yyyy-MM-dd")
        fmt_from = _format_dmy_dash(from_str)
        fmt_to = _format_dmy_dash(to_str)

        item_id = self.item_combo.currentData()
        item_name = self.item_combo.currentText().strip()

        rows = ScheduleReportsDAO.get_purchase_schedule(
            from_str, to_str, self.schedule_type, item_id=item_id
        )

        sub_header = f"Purchase Sheduled {self.schedule_type} Report for {fmt_from} To {fmt_to}"
        if item_id:
            sub_header += f"  |  Item: {item_name}"

        header = ReportHeaderData(
            store_name=STORE_LINE_1,
            store_address=STORE_LINE_2,
            header_line_1=f"ITEMWISE PURCHASE SHEDULED {self.schedule_type} REPORT",
            header_line_2=f"Report Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            header_line_3=sub_header,
        )

        cols = ["SrNo", "Inv.Date", "Inv.No", "Supplier", "VhNo", "Vh Date", "Unit", "Pack", "ItemName", "BatchNo", "ExpiryDate", "PurQty", "PurValue"]
        widths = [40.0, 75.0, 75.0, 175.0, 100.0, 75.0, 50.0, 50.0, 175.0, 85.0, 65.0, 43.0, 45.0]
        aligns = ["center", "center", "left", "left", "left", "center", "center", "center", "left", "left", "center", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        tot_qty = 0.0
        tot_val = 0.0
        prefix_w = sum(widths[:-2])

        if not rows:
            self.lbl_msg.setText("No records found.")
            self.lbl_msg.setVisible(True)
            self.btn_panel_print.setEnabled(True)
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=36.0,
                    data={"message": "No records found for the selected period."},
                )
            )
        else:
            self.lbl_msg.setVisible(False)
            self.btn_panel_print.setEnabled(True)

            for idx, r in enumerate(rows, 1):
                pur_qty = float(r.get("pur_qty") or 0.0)
                pur_val = float(r.get("pur_value") or 0.0)
                tot_qty += pur_qty
                tot_val += pur_val

                row_vals = [
                    str(idx),
                    _format_dmy(r.get("inv_date", "")),
                    str(r.get("inv_no") or ""),
                    str(r.get("supplier_name") or ""),
                    str(r.get("vh_no") or ""),
                    _format_dmy(r.get("vh_date", "")),
                    str(r.get("unit_name") or ""),
                    str(r.get("pack_size") or ""),
                    str(r.get("item_name") or ""),
                    str(r.get("batch_no") or ""),
                    _format_expiry_display(str(r.get("expiry") or "")),
                    fmt_qty(pur_qty),
                    str(int(round(pur_val))),  # Whole number
                ]

                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=20.0,
                        data={"cells": row_vals, "widths": widths, "aligns": aligns},
                    )
                )

        # Grand Total Row
        tot_cells = ["", "", "", "", "", "", "", "", "", "", "Total :", fmt_qty(tot_qty), str(int(round(tot_val)))]
        tot_aligns = ["center"] * 10 + ["right", "right", "right"]
        custom_cells = _make_total_custom_cells(
            prefix_w, "Total :", [(widths[-2], fmt_qty(tot_qty)), (widths[-1], str(int(round(tot_val))))]
        )
        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "cells": tot_cells,
                    "widths": widths,
                    "aligns": tot_aligns,
                    "custom_cells": custom_cells,
                    "qty_str": fmt_qty(tot_qty),
                    "amt_str": str(int(round(tot_val))),
                    "label": "Total :",
                },
            )
        )

        self._pages = paginate_schedule_blocks(header, blocks, table_header_block, orientation="landscape")
        self.viewer.set_pages(self._pages)


# ══════════════════════════════════════════════════════════════════════
# Report F: Purchase - All Items (Grouped by item)
# ══════════════════════════════════════════════════════════════════════

class SchedulePurchaseAllItemsPage(_BaseScheduleReportPage):
    """Report F: All Items Purchase Schedule Report grouped by item (H1 or NRX)."""

    def __init__(self, schedule_type: str = "H1", parent: Optional[QWidget] = None):
        st = schedule_type.upper().strip()
        super().__init__(
            window_title=f"All Items Purchase Sheduled {st} Report",
            panel_title=f"Items (All) Purchase Sheduled {st}",
            schedule_type=st,
            parent=parent,
        )

    def generate_report(self):
        if not self.validate_dates():
            return

        from_str = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_str = self.to_date_edit.date().toString("yyyy-MM-dd")
        fmt_from = _format_dmy_dash(from_str)
        fmt_to = _format_dmy_dash(to_str)

        rows = ScheduleReportsDAO.get_purchase_schedule(
            from_str, to_str, self.schedule_type, grouped_by_item=True
        )

        header = ReportHeaderData(
            store_name=STORE_LINE_1,
            store_address=STORE_LINE_2,
            header_line_1=f"ITEMS (ALL) PURCHASE SHEDULED {self.schedule_type} REPORT",
            header_line_2=f"Report Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
            header_line_3=f"Purchase Sheduled {self.schedule_type} Report for {fmt_from} To {fmt_to}",
        )

        cols = ["SrNo", "Inv.Date", "Inv.No", "Supplier", "VhNo", "Vh Date", "Unit", "Pack Size", "BatchNo", "ExpiryDate", "PurQty", "PurValue"]
        widths = [45.0, 85.0, 85.0, 220.0, 120.0, 85.0, 55.0, 55.0, 110.0, 75.0, 58.0, 60.0]
        aligns = ["center", "center", "left", "left", "left", "center", "center", "center", "left", "center", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        grand_tot_qty = 0.0
        grand_tot_val = 0.0
        prefix_w = sum(widths[:-2])

        if not rows:
            self.lbl_msg.setText("No records found.")
            self.lbl_msg.setVisible(True)
            self.btn_panel_print.setEnabled(True)
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=36.0,
                    data={"message": "No records found for the selected period."},
                )
            )
        else:
            self.lbl_msg.setVisible(False)
            self.btn_panel_print.setEnabled(True)

            groups: dict[str, list[dict]] = {}
            for r in rows:
                itm_name = str(r.get("item_name") or "Unknown Item").strip()
                groups.setdefault(itm_name, []).append(r)

            sr_no = 1

            for itm_name, itm_rows in groups.items():
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.GROUP_HEADER,
                        height=26.0,
                        data={"title": f"Item Name : {itm_name}", "width": CONTENT_WIDTH_LANDSCAPE},
                    )
                )

                sub_qty = 0.0
                sub_val = 0.0

                for r in itm_rows:
                    pur_qty = float(r.get("pur_qty") or 0.0)
                    pur_val = float(r.get("pur_value") or 0.0)
                    sub_qty += pur_qty
                    sub_val += pur_val
                    grand_tot_qty += pur_qty
                    grand_tot_val += pur_val

                    row_vals = [
                        str(sr_no),
                        _format_dmy(r.get("inv_date", "")),
                        str(r.get("inv_no") or ""),
                        str(r.get("supplier_name") or ""),
                        str(r.get("vh_no") or ""),
                        _format_dmy(r.get("vh_date", "")),
                        str(r.get("unit_name") or ""),
                        str(r.get("pack_size") or ""),
                        str(r.get("batch_no") or ""),
                        _format_expiry_display(str(r.get("expiry") or "")),
                        fmt_qty(pur_qty),
                        f"{pur_val:.2f}",  # 2 decimals in All Items Purchase report
                    ]

                    blocks.append(
                        ReportBlock(
                            kind=BlockKind.DATA_ROW,
                            height=20.0,
                            data={"cells": row_vals, "widths": widths, "aligns": aligns},
                        )
                    )
                    sr_no += 1

                # Group Subtotal: "Total :" showing PurQty and PurValue
                sub_cells = ["", "", "", "", "", "", "", "", "", "Total :", fmt_qty(sub_qty), f"{sub_val:.2f}"]
                sub_aligns = ["center"] * 9 + ["right", "right", "right"]
                sub_custom_cells = _make_total_custom_cells(
                    prefix_w, "Total :", [(widths[-2], fmt_qty(sub_qty)), (widths[-1], f"{sub_val:.2f}")]
                )
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.ITEM_SUBTOTAL,
                        height=22.0,
                        data={
                            "cells": sub_cells,
                            "widths": widths,
                            "aligns": sub_aligns,
                            "custom_cells": sub_custom_cells,
                            "pay_str": fmt_qty(sub_qty),
                            "amt_str": f"{sub_val:.2f}",
                            "label": "Total :",
                        },
                    )
                )

        # Grand Total
        tot_cells = ["", "", "", "", "", "", "", "", "", "Grand Total :", fmt_qty(grand_tot_qty), f"{grand_tot_val:.2f}"]
        tot_aligns = ["center"] * 9 + ["right", "right", "right"]
        tot_custom_cells = _make_total_custom_cells(
            prefix_w, "Grand Total :", [(widths[-2], fmt_qty(grand_tot_qty)), (widths[-1], f"{grand_tot_val:.2f}")]
        )
        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "cells": tot_cells,
                    "widths": widths,
                    "aligns": tot_aligns,
                    "custom_cells": tot_custom_cells,
                    "qty_str": fmt_qty(grand_tot_qty),
                    "amt_str": f"{grand_tot_val:.2f}",
                    "label": "Grand Total :",
                },
            )
        )

        self._pages = paginate_schedule_blocks(header, blocks, table_header_block, orientation="landscape")
        self.viewer.set_pages(self._pages)
