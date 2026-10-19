"""Crystal-Reports-Style Report Viewer and Window Layout.

Provides:
- Blue title bar with close "X" at top right
- Report Viewer (about 80% width):
  * Toolbar: Export, Print, Copy icons | First, Prev, Next, Last | Page box "1" with "/N" | Find | Zoom dropdown
  * Tab below toolbar: "Main Report"
  * Grey background with white A4 page, thin dotted inner border, drop shadow
  * Status bar: "Current Page No.: X" | "Total Page No.: N" | "Zoom Factor: 100%"
- Filter Panel (about 20% width):
  * Light-blue background, bold blue title
  * From date picker (default 01/04/<fy_start>), label "To", To date picker (default today), format dd/MM/yyyy
  * Searchable dropdown (Company / Supplier / Item)
  * "Show Report" button
  * "Print" button directly below "Show Report", disabled until report shown
  * Validation: From <= To and dropdown must be selected
- Full print & export capability with identical A4 portrait layout
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QDate, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from database import pharmacy_a6_receipt as a6
from database import financial_year


# ── Page Dimensions (A4 Portrait at 96 DPI) ───────────────────────────
PAGE_WIDTH = 794.0
PAGE_HEIGHT = 1123.0
MARGIN_LEFT = 35.0
MARGIN_RIGHT = 35.0
MARGIN_TOP = 30.0
MARGIN_BOTTOM = 35.0
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT  # 724.0 px

# ── Page Dimensions (A4 Landscape at 96 DPI) ──────────────────────────
PAGE_WIDTH_LANDSCAPE = 1123.0
PAGE_HEIGHT_LANDSCAPE = 794.0
CONTENT_WIDTH_LANDSCAPE = PAGE_WIDTH_LANDSCAPE - MARGIN_LEFT - MARGIN_RIGHT  # 1053.0 px


@dataclass
class ReportHeaderData:
    store_name: str
    store_address: str
    header_line_1: str
    header_line_2: str
    header_line_3: str = ""


class BlockKind:
    GROUP_HEADER = "group_header"
    TABLE_HEADER = "table_header"
    DATA_ROW = "data_row"
    ITEM_SUBTOTAL = "item_subtotal"
    BATCH_SUBTOTAL = "batch_subtotal"
    STOCK_SUBTOTAL = "stock_subtotal"
    GRAND_TOTAL = "grand_total"
    SUMMARY_BOX = "summary_box"
    EMPTY = "empty"


@dataclass
class ReportBlock:
    kind: str
    height: float
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportPage:
    page_num: int
    total_pages: int
    header: ReportHeaderData
    blocks: List[ReportBlock] = field(default_factory=list)
    orientation: str = "portrait"
    page_width: float = PAGE_WIDTH
    page_height: float = PAGE_HEIGHT


def get_default_store_identity() -> Tuple[str, str]:
    try:
        profile = a6.store_profile()
    except Exception:
        profile = {}
    name = str((profile or {}).get("name") or "").strip() or "SHREE SAMARTH MEDICAL AND GEN STORE"
    address = str((profile or {}).get("address") or "").strip() or "GHORPADE HOSPITAL, RAHURI"
    return name, address


def fmt_amt(val: Any) -> str:
    try:
        return f"{float(val or 0):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def fmt_qty(val: Any) -> str:
    try:
        f = float(val or 0)
        return str(int(f)) if f.is_integer() else f"{f:.2f}"
    except (TypeError, ValueError):
        return "0"


def fmt_free(val: Any) -> str:
    try:
        f = float(val or 0)
        if f == 0.0:
            return "-"
        return str(int(f)) if f.is_integer() else f"{f:.2f}"
    except (TypeError, ValueError):
        return "-"


def fmt_date_slash(iso_str: Any) -> str:
    s = str(iso_str or "").strip()
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            if len(parts[0]) == 4:
                return f"{parts[2]}/{parts[1]}/{parts[0]}"
            return f"{parts[0]}/{parts[1]}/{parts[2]}"
        return s
    parts = s.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        if len(parts[0]) == 4:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
        return f"{parts[0]}/{parts[1]}/{parts[2]}"
    return s


def fmt_date_dash(iso_str: Any) -> str:
    s = str(iso_str or "").strip()
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            if len(parts[0]) == 4:
                return f"{parts[2]}-{parts[1]}-{parts[0]}"
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
        return s
    parts = s.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        if len(parts[0]) == 4:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return f"{parts[0]}-{parts[1]}-{parts[2]}"
    return s


# ── Page Drawer ───────────────────────────────────────────────────────

def draw_report_page(painter: QPainter, page: ReportPage):
    """Render a single ReportPage onto any QPainter (screen canvas or QPrinter)."""
    painter.save()
    try:
        _draw_report_page_content(painter, page)
    finally:
        painter.restore()


def _draw_report_page_content(painter: QPainter, page: ReportPage):
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

    page_w = getattr(page, "page_width", PAGE_WIDTH)
    page_h = getattr(page, "page_height", PAGE_HEIGHT)
    content_w = page_w - MARGIN_LEFT - MARGIN_RIGHT

    # 1. White Page Background
    painter.fillRect(QRectF(0, 0, page_w, page_h), QColor("#FFFFFF"))

    # 2. Thin Dotted Inner Border (Margin boundaries guide)
    pen_dotted = QPen(QColor("#A0A0A0"), 1, Qt.DotLine)
    painter.setPen(pen_dotted)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(
        QRectF(
            MARGIN_LEFT - 10,
            MARGIN_TOP - 10,
            content_w + 20,
            page_h - MARGIN_TOP - MARGIN_BOTTOM + 20,
        )
    )

    # 3. Report Header
    pen_text = QPen(QColor("#000000"), 1)
    painter.setPen(pen_text)

    # Left: Store Name & Address
    font_store = QFont("Segoe UI", 13, QFont.Bold)
    painter.setFont(font_store)
    painter.drawText(
        QRectF(MARGIN_LEFT, MARGIN_TOP, content_w * 0.52, 22),
        Qt.AlignLeft | Qt.AlignVCenter,
        page.header.store_name,
    )

    font_addr = QFont("Consolas", 8, QFont.Normal)
    font_addr.setCapitalization(QFont.SmallCaps)
    painter.setFont(font_addr)
    painter.drawText(
        QRectF(MARGIN_LEFT, MARGIN_TOP + 22, content_w * 0.52, 16),
        Qt.AlignLeft | Qt.AlignVCenter,
        page.header.store_address,
    )

    line3_text = getattr(page.header, "header_line_3", "")
    if line3_text:
        painter.setFont(QFont("Segoe UI", 8, QFont.Normal))
        painter.setPen(QColor("#444444"))
        fm_l3 = painter.fontMetrics()
        elided_l3 = fm_l3.elidedText(line3_text, Qt.ElideRight, int(content_w * 0.52))
        painter.drawText(
            QRectF(MARGIN_LEFT, MARGIN_TOP + 38, content_w * 0.52, 14),
            Qt.AlignLeft | Qt.AlignVCenter,
            elided_l3,
        )

    # Right: Line 1 (Report title & period) and Line 2 (Selected entity, bold)
    font_hdr1 = QFont("Segoe UI", 9, QFont.Normal)
    painter.setFont(font_hdr1)
    painter.setPen(QColor("#000000"))
    painter.drawText(
        QRectF(MARGIN_LEFT + content_w * 0.45, MARGIN_TOP, content_w * 0.55, 20),
        Qt.AlignRight | Qt.AlignVCenter,
        page.header.header_line_1,
    )

    font_hdr2 = QFont("Segoe UI", 9, QFont.Bold)
    painter.setFont(font_hdr2)
    painter.drawText(
        QRectF(MARGIN_LEFT + content_w * 0.45, MARGIN_TOP + 20, content_w * 0.55, 18),
        Qt.AlignRight | Qt.AlignVCenter,
        page.header.header_line_2,
    )

    # Horizontal Divider Line
    line_y = MARGIN_TOP + (54.0 if line3_text else 44.0)
    pen_solid = QPen(QColor("#000000"), 1, Qt.SolidLine)
    painter.setPen(pen_solid)
    painter.drawLine(MARGIN_LEFT, line_y, MARGIN_LEFT + content_w, line_y)

    # 4. Render Body Blocks
    curr_y = line_y + 8.0
    pen_grid = QPen(QColor("#333333"), 1, Qt.SolidLine)

    for block in page.blocks:
        kind = block.kind
        h = block.height

        if kind == BlockKind.GROUP_HEADER:
            # Bold Group Header: e.g. <ITEM NAME>   <FORM>
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
            painter.setPen(QColor("#000000"))
            painter.drawText(
                QRectF(MARGIN_LEFT, curr_y, content_w, h),
                Qt.AlignLeft | Qt.AlignVCenter,
                block.data.get("text", ""),
            )

        elif kind == BlockKind.TABLE_HEADER:
            cols: List[str] = block.data.get("columns", [])
            widths: List[float] = block.data.get("widths", [])
            aligns: List[str] = block.data.get("aligns", [])

            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            # Background fill for header row
            header_w = sum(widths) if widths else content_w
            painter.fillRect(QRectF(MARGIN_LEFT, curr_y, header_w, h), QColor("#F4F4F4"))
            x = MARGIN_LEFT
            for c_idx, title in enumerate(cols):
                w = widths[c_idx] if c_idx < len(widths) else 50.0
                painter.setPen(pen_grid)
                painter.drawRect(QRectF(x, curr_y, w, h))
                painter.setPen(QColor("#000000"))
                align_flag = Qt.AlignCenter
                if c_idx < len(aligns):
                    if aligns[c_idx] == "left":
                        align_flag = Qt.AlignLeft | Qt.AlignVCenter
                    elif aligns[c_idx] == "right":
                        align_flag = Qt.AlignRight | Qt.AlignVCenter
                painter.drawText(QRectF(x + 3, curr_y, w - 6, h), align_flag, title)
                x += w

        elif kind == BlockKind.DATA_ROW:
            cells: List[str] = block.data.get("cells", [])
            widths = block.data.get("widths", [])
            aligns = block.data.get("aligns", [])
            is_bold = block.data.get("bold", False)
            bg_color = block.data.get("bg")

            if bg_color:
                row_w = sum(widths) if widths else content_w
                painter.fillRect(QRectF(MARGIN_LEFT, curr_y, row_w, h), QColor(bg_color))

            painter.setFont(QFont("Segoe UI", 8, QFont.Bold if is_bold else QFont.Normal))
            fm = painter.fontMetrics()
            x = MARGIN_LEFT
            for c_idx, val in enumerate(cells):
                w = widths[c_idx] if c_idx < len(widths) else 50.0
                painter.setPen(pen_grid)
                painter.drawRect(QRectF(x, curr_y, w, h))
                painter.setPen(QColor("#000000"))
                align_flag = Qt.AlignLeft | Qt.AlignVCenter
                if c_idx < len(aligns):
                    if aligns[c_idx] == "right":
                        align_flag = Qt.AlignRight | Qt.AlignVCenter
                    elif aligns[c_idx] == "center":
                        align_flag = Qt.AlignCenter
                val_str = str(val)
                avail_w = max(0, int(w - 8))
                cell_text = fm.elidedText(val_str, Qt.ElideRight, avail_w)
                painter.drawText(QRectF(x + 4, curr_y, w - 8, h), align_flag, cell_text)
                x += w

        elif kind in (BlockKind.ITEM_SUBTOTAL, BlockKind.BATCH_SUBTOTAL, BlockKind.STOCK_SUBTOTAL, "stock_subtotal"):
            if "custom_cells" in block.data:
                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                x = MARGIN_LEFT
                for cell in block.data["custom_cells"]:
                    if isinstance(cell, dict):
                        cell_w = cell.get("width", 0.0)
                        cell_txt = cell.get("text", "")
                        cell_align = cell.get("align", "left")
                    else:
                        cell_w, cell_txt, cell_align = cell[0], cell[1], cell[2]
                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(x, curr_y, cell_w, h))
                    painter.setPen(QColor("#000000"))
                    align_flag = (
                        Qt.AlignRight | Qt.AlignVCenter if cell_align == "right"
                        else (Qt.AlignCenter if cell_align == "center" else (Qt.AlignLeft | Qt.AlignVCenter))
                    )
                    if cell_txt:
                        painter.drawText(QRectF(x + 4, curr_y, cell_w - 8, h), align_flag, str(cell_txt))
                    x += cell_w
            else:
                widths = block.data.get("widths", [])
                batch_no = block.data.get("batch_no", "")
                label_text = f"{batch_no}   Total :" if batch_no else block.data.get("label", "Total :")
                pay_str = block.data.get("pay_str", "0")
                free_str = block.data.get("free_str", "0")
                amt_str = block.data.get("amt_str", "0.00")

                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                if len(widths) >= 3:
                    sum_prefix_w = sum(widths[:-3])
                    pay_w = widths[-3]
                    free_w = widths[-2]
                    amt_w = widths[-1]
                elif len(widths) == 2:
                    sum_prefix_w = widths[0]
                    pay_w = 0.0
                    free_w = 0.0
                    amt_w = widths[1]
                elif len(widths) == 1:
                    amt_w = widths[0]
                    pay_w = 0.0
                    free_w = 0.0
                    sum_prefix_w = max(0.0, content_w - amt_w)
                else:
                    pay_w = 60.0
                    free_w = 50.0
                    amt_w = 80.0
                    sum_prefix_w = max(0.0, content_w - (pay_w + free_w + amt_w))

                # Label box: "Total :" or "<BATCHNO>   Total :"
                painter.setPen(pen_grid)
                painter.drawRect(QRectF(MARGIN_LEFT, curr_y, sum_prefix_w, h))
                painter.setPen(QColor("#000000"))
                painter.drawText(
                    QRectF(MARGIN_LEFT + 4, curr_y, sum_prefix_w - 8, h),
                    Qt.AlignRight | Qt.AlignVCenter,
                    label_text,
                )

                x = MARGIN_LEFT + sum_prefix_w
                if pay_w > 0:
                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(x, curr_y, pay_w, h))
                    painter.setPen(QColor("#000000"))
                    painter.drawText(QRectF(x + 4, curr_y, pay_w - 8, h), Qt.AlignRight | Qt.AlignVCenter, pay_str)
                    x += pay_w

                if free_w > 0:
                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(x, curr_y, free_w, h))
                    painter.setPen(QColor("#000000"))
                    painter.drawText(QRectF(x + 4, curr_y, free_w - 8, h), Qt.AlignRight | Qt.AlignVCenter, free_str)
                    x += free_w

                painter.setPen(pen_grid)
                painter.drawRect(QRectF(x, curr_y, amt_w, h))
                painter.setPen(QColor("#000000"))
                painter.drawText(QRectF(x + 4, curr_y, amt_w - 8, h), Qt.AlignRight | Qt.AlignVCenter, amt_str)

        elif kind == BlockKind.GRAND_TOTAL:
            if "custom_cells" in block.data:
                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                x = MARGIN_LEFT
                for cell in block.data["custom_cells"]:
                    if isinstance(cell, dict):
                        cell_w = cell.get("width", 0.0)
                        cell_txt = cell.get("text", "")
                        cell_align = cell.get("align", "left")
                    else:
                        cell_w, cell_txt, cell_align = cell[0], cell[1], cell[2]
                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(x, curr_y, cell_w, h))
                    painter.setPen(QColor("#000000"))
                    align_flag = (
                        Qt.AlignRight | Qt.AlignVCenter if cell_align == "right"
                        else (Qt.AlignCenter if cell_align == "center" else (Qt.AlignLeft | Qt.AlignVCenter))
                    )
                    if cell_txt:
                        painter.drawText(QRectF(x + 4, curr_y, cell_w - 8, h), align_flag, str(cell_txt))
                    x += cell_w
            else:
                widths = block.data.get("widths", [])
                label = block.data.get("label", "Grand Total :")
                pay_str = block.data.get("pay_str")
                free_str = block.data.get("free_str")
                qty_str = block.data.get("qty_str", pay_str)
                disc_str = block.data.get("disc_str", free_str)
                amt_str = block.data.get("amt_str", "0.00")

                painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
                if qty_str is not None and disc_str is not None:
                    # 3-column total (Pay/Qty, Free/Disc, Amount)
                    if len(widths) >= 3:
                        sum_prefix_w = sum(widths[:-3])
                        c1_w = widths[-3]
                        c2_w = widths[-2]
                        c3_w = widths[-1]
                    else:
                        c1_w = 60.0
                        c2_w = 60.0
                        c3_w = 80.0
                        sum_prefix_w = max(0.0, content_w - (c1_w + c2_w + c3_w))

                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(MARGIN_LEFT, curr_y, sum_prefix_w, h))
                    painter.setPen(QColor("#000000"))
                    painter.drawText(
                        QRectF(MARGIN_LEFT + 4, curr_y, sum_prefix_w - 8, h),
                        Qt.AlignRight | Qt.AlignVCenter,
                        label,
                    )

                    x = MARGIN_LEFT + sum_prefix_w
                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(x, curr_y, c1_w, h))
                    painter.setPen(QColor("#000000"))
                    painter.drawText(QRectF(x + 4, curr_y, c1_w - 8, h), Qt.AlignRight | Qt.AlignVCenter, str(qty_str))

                    x += c1_w
                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(x, curr_y, c2_w, h))
                    painter.setPen(QColor("#000000"))
                    painter.drawText(QRectF(x + 4, curr_y, c2_w - 8, h), Qt.AlignRight | Qt.AlignVCenter, str(disc_str))

                    x += c2_w
                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(x, curr_y, c3_w, h))
                    painter.setPen(QColor("#000000"))
                    painter.drawText(QRectF(x + 4, curr_y, c3_w - 8, h), Qt.AlignRight | Qt.AlignVCenter, str(amt_str))
                else:
                    # 1-column total (Amount only, e.g. Report 2)
                    if len(widths) >= 1:
                        prefix_w = sum(widths[:-1])
                        amt_w = widths[-1]
                    else:
                        amt_w = 100.0
                        prefix_w = max(0.0, content_w - amt_w)

                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(MARGIN_LEFT, curr_y, prefix_w, h))
                    painter.setPen(QColor("#000000"))
                    painter.drawText(
                        QRectF(MARGIN_LEFT + 4, curr_y, prefix_w - 8, h),
                        Qt.AlignRight | Qt.AlignVCenter,
                        label,
                    )

                    x = MARGIN_LEFT + prefix_w
                    painter.setPen(pen_grid)
                    painter.drawRect(QRectF(x, curr_y, amt_w, h))
                    painter.setPen(QColor("#000000"))
                    painter.drawText(QRectF(x + 4, curr_y, amt_w - 8, h), Qt.AlignRight | Qt.AlignVCenter, str(amt_str))

        elif kind in (BlockKind.SUMMARY_BOX, "summary_box"):
            box_w = block.data.get("width", content_w)
            painter.fillRect(QRectF(MARGIN_LEFT, curr_y, box_w, h), QColor("#F4F7FB"))
            painter.setPen(pen_grid)
            painter.drawRect(QRectF(MARGIN_LEFT, curr_y, box_w, h))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.setPen(QColor("#003366"))
            painter.drawText(
                QRectF(MARGIN_LEFT + 6, curr_y, box_w - 12, h),
                Qt.AlignCenter,
                block.data.get("text", ""),
            )

        elif kind == BlockKind.EMPTY:
            painter.setFont(QFont("Segoe UI", 9, QFont.Normal))
            painter.setPen(pen_grid)
            painter.drawRect(QRectF(MARGIN_LEFT, curr_y, content_w, h))
            painter.setPen(QColor("#666666"))
            painter.drawText(
                QRectF(MARGIN_LEFT, curr_y, content_w, h),
                Qt.AlignCenter,
                block.data.get("message", "No records found."),
            )

        curr_y += h

    # 5. Footer: Page Number
    footer_y = page_h - MARGIN_BOTTOM + 5
    painter.setFont(QFont("Segoe UI", 8, QFont.Normal))
    painter.setPen(QColor("#444444"))
    page_txt = f"Page {page.page_num} of {page.total_pages}"
    painter.drawText(
        QRectF(MARGIN_LEFT, footer_y, content_w, 20),
        Qt.AlignRight | Qt.AlignVCenter,
        page_txt,
    )


# ── Screen Canvas Widget ──────────────────────────────────────────────

class ReportPageCanvas(QWidget):
    """Draws a single A4 page with drop shadow and dotted border at a given zoom factor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page: Optional[ReportPage] = None
        self._zoom: float = 1.0
        self._bg_color: QColor = QColor("#808080")
        self._last_paint_error: Optional[str] = None
        self._update_geometry()

    def set_page(self, page: Optional[ReportPage]):
        self._last_paint_error = None
        self._page = page
        self._update_geometry()
        self.update()

    def set_zoom(self, zoom: float):
        self._zoom = max(0.20, min(2.5, zoom))
        self._update_geometry()
        self.update()

    def set_workspace_bg(self, color: QColor):
        self._bg_color = color
        self.update()

    def _update_geometry(self):
        page_w = getattr(self._page, "page_width", PAGE_WIDTH) if self._page else PAGE_WIDTH
        page_h = getattr(self._page, "page_height", PAGE_HEIGHT) if self._page else PAGE_HEIGHT
        w = int((page_w + 40) * self._zoom)
        h = int((page_h + 40) * self._zoom)
        self.setFixedSize(w, h)

    def paintEvent(self, event):
        painter = QPainter()
        if not painter.begin(self):
            return

        try:
            painter.fillRect(self.rect(), self._bg_color)  # Workspace background

            if self._page is None:
                painter.setFont(QFont("Segoe UI", 12))
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(self.rect(), Qt.AlignCenter, "No report loaded. Select filters and click Show Report.")
                return

            page_w = getattr(self._page, "page_width", PAGE_WIDTH)
            page_h = getattr(self._page, "page_height", PAGE_HEIGHT)

            painter.save()
            try:
                # Center the page in the canvas area
                offset_x = 20 * self._zoom
                offset_y = 20 * self._zoom
                painter.translate(offset_x, offset_y)
                painter.scale(self._zoom, self._zoom)

                # Drop shadow on right and bottom
                shadow_rect = QRectF(4, 4, page_w, page_h)
                painter.fillRect(shadow_rect, QColor(0, 0, 0, 70))

                # Render the page
                draw_report_page(painter, self._page)
            finally:
                painter.restore()

        except Exception as exc:
            err_msg = str(exc)
            if getattr(self, "_last_paint_error", None) != err_msg:
                self._last_paint_error = err_msg
                import sys, traceback
                print(f"[CrystalReportViewer] Error rendering report page: {err_msg}", file=sys.stderr)
                traceback.print_exc()

            try:
                painter.save()
                try:
                    painter.setPen(QPen(QColor("#D9534F"), 2))
                    painter.setBrush(QColor("#FFF0F0"))
                    err_rect = QRectF(30, 30, min(float(self.width() - 60), 600.0), 90.0)
                    painter.drawRect(err_rect)
                    painter.setPen(QColor("#D9534F"))
                    painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
                    painter.drawText(
                        err_rect.adjusted(12, 10, -12, -10),
                        Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                        f"Report Rendering Error:\n{err_msg}",
                    )
                finally:
                    painter.restore()
            except Exception:
                pass
        finally:
            if painter.isActive():
                painter.end()


# ── Crystal Reports Viewer (Left 80% Component) ───────────────────────

class CrystalReportViewer(QWidget):
    """Crystal Reports 80% Report Viewer."""

    print_requested = Signal()
    export_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pages: List[ReportPage] = []
        self._current_page_idx: int = 0
        self._zoom_factor: float = 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setFixedHeight(34)
        toolbar.setStyleSheet(
            "QFrame { background-color: #E8EEF5; border-bottom: 1px solid #B0C4DE; }"
            "QPushButton { background: transparent; border: 1px solid transparent; border-radius: 2px; padding: 2px 6px; font-size: 12px; }"
            "QPushButton:hover { background-color: #D0E0F0; border: 1px solid #90B0D0; }"
            "QPushButton:disabled { color: #A0B0C0; }"
            "QLineEdit { background: white; border: 1px solid #A0B0C0; border-radius: 2px; padding: 1px 4px; font-size: 12px; }"
            "QComboBox { background: white; border: 1px solid #A0B0C0; border-radius: 2px; padding: 1px 4px; font-size: 12px; }"
        )
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 2, 8, 2)
        tb_layout.setSpacing(4)

        # 1. Export, Print, Copy
        self.btn_export = QPushButton("📥 Export")
        self.btn_export.setToolTip("Export Report (PDF / CSV)")
        self.btn_export.clicked.connect(self._on_export)
        tb_layout.addWidget(self.btn_export)

        self.btn_print = QPushButton("🖨 Print")
        self.btn_print.setToolTip("Print Report")
        self.btn_print.clicked.connect(self._on_print)
        tb_layout.addWidget(self.btn_print)

        self.btn_copy = QPushButton("📋 Copy")
        self.btn_copy.setToolTip("Copy Report to Clipboard")
        self.btn_copy.clicked.connect(self._on_copy)
        tb_layout.addWidget(self.btn_copy)

        tb_layout.addSpacing(6)
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #B0C0D0;")
        tb_layout.addWidget(sep1)
        tb_layout.addSpacing(6)

        # 2. First, Previous, Next, Last
        self.btn_first = QPushButton("⏮")
        self.btn_first.setToolTip("First Page")
        self.btn_first.clicked.connect(self.first_page)
        tb_layout.addWidget(self.btn_first)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setToolTip("Previous Page")
        self.btn_prev.clicked.connect(self.prev_page)
        tb_layout.addWidget(self.btn_prev)

        # Page box "1" with "/N"
        self.page_box = QLineEdit("1")
        self.page_box.setFixedWidth(36)
        self.page_box.setAlignment(Qt.AlignCenter)
        self.page_box.returnPressed.connect(self._on_page_box_entered)
        tb_layout.addWidget(self.page_box)

        self.page_total_lbl = QLabel("/ 1")
        self.page_total_lbl.setStyleSheet("color: #333333; font-size: 12px;")
        tb_layout.addWidget(self.page_total_lbl)

        self.btn_next = QPushButton("▶")
        self.btn_next.setToolTip("Next Page")
        self.btn_next.clicked.connect(self.next_page)
        tb_layout.addWidget(self.btn_next)

        self.btn_last = QPushButton("⏭")
        self.btn_last.setToolTip("Last Page")
        self.btn_last.clicked.connect(self.last_page)
        tb_layout.addWidget(self.btn_last)

        tb_layout.addSpacing(6)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #B0C0D0;")
        tb_layout.addWidget(sep2)
        tb_layout.addSpacing(6)

        # 3. Find (binoculars)
        self.btn_find = QPushButton("🔍 Find")
        self.btn_find.setToolTip("Find in Report")
        self.btn_find.clicked.connect(self._on_find)
        tb_layout.addWidget(self.btn_find)

        tb_layout.addSpacing(6)
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.VLine)
        sep3.setStyleSheet("color: #B0C0D0;")
        tb_layout.addWidget(sep3)
        tb_layout.addSpacing(6)

        # 4. Zoom dropdown
        self.zoom_combo = QComboBox()
        self.zoom_combo.setFixedWidth(100)
        self.zoom_combo.addItems(["Fit to Width", "Fit to Page", "25%", "50%", "75%", "100%", "125%", "150%", "200%"])
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.currentTextChanged.connect(self._on_zoom_changed)
        tb_layout.addWidget(self.zoom_combo)

        tb_layout.addStretch()
        root.addWidget(toolbar)

        # ── Tab below toolbar: "Main Report" ──────────────────────────
        tab_bar = QTabBar()
        tab_bar.addTab("Main Report")
        tab_bar.setStyleSheet(
            "QTabBar::tab { background: #D8E4F2; color: #003366; font-weight: bold; font-size: 12px; padding: 4px 14px; border: 1px solid #B0C4DE; border-bottom: none; border-top-left-radius: 3px; border-top-right-radius: 3px; }"
            "QTabBar::tab:selected { background: #808080; color: white; }"
        )
        root.addWidget(tab_bar)

        # ── Central Grey Canvas Area with Scroll ──────────────────────
        self.scroll_area = QScrollArea()
        self.scroll_area.setStyleSheet("QScrollArea { background-color: #808080; border: none; }")
        self.scroll_area.setAlignment(Qt.AlignCenter)

        self.canvas = ReportPageCanvas(self)
        self.scroll_area.setWidget(self.canvas)
        root.addWidget(self.scroll_area, 1)

        # ── Status Bar at Bottom ──────────────────────────────────────
        status_bar = QFrame()
        status_bar.setFixedHeight(24)
        status_bar.setStyleSheet(
            "QFrame { background-color: #E8EEF5; border-top: 1px solid #B0C4DE; }"
            "QLabel { color: #333333; font-size: 11px; padding: 0 8px; border-right: 1px solid #C0D0E0; }"
        )
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        self.lbl_stat_curr = QLabel("Current Page No.: 1")
        self.lbl_stat_total = QLabel("Total Page No.: 1")
        self.lbl_stat_zoom = QLabel("Zoom Factor: 100%")
        self.lbl_stat_zoom.setStyleSheet("border-right: none;")

        sb_layout.addWidget(self.lbl_stat_curr)
        sb_layout.addWidget(self.lbl_stat_total)
        sb_layout.addWidget(self.lbl_stat_zoom)
        sb_layout.addStretch()
        root.addWidget(status_bar)

        self._update_controls()

    # ── Page Management ───────────────────────────────────────────────

    def set_pages(self, pages: List[ReportPage]):
        self._pages = pages
        self._current_page_idx = 0
        self._update_controls()
        self._display_current_page()

    set_report_pages = set_pages

    def clear_report(self):
        self._pages = []
        self._current_page_idx = 0
        self.canvas.set_page(None)
        self._update_controls()

    def _display_current_page(self):
        if self._pages and 0 <= self._current_page_idx < len(self._pages):
            page = self._pages[self._current_page_idx]
            self.canvas.set_page(page)
            self.page_box.setText(str(self._current_page_idx + 1))
            self.lbl_stat_curr.setText(f"Current Page No.: {self._current_page_idx + 1}")
            self.lbl_stat_total.setText(f"Total Page No.: {len(self._pages)}")
        else:
            self.canvas.set_page(None)
            self.page_box.setText("1")
            self.lbl_stat_curr.setText("Current Page No.: 1")
            self.lbl_stat_total.setText("Total Page No.: 1")

    def _update_controls(self):
        has_pages = bool(self._pages)
        total = len(self._pages) if has_pages else 1

        self.btn_export.setEnabled(has_pages)
        self.btn_print.setEnabled(has_pages)
        self.btn_copy.setEnabled(has_pages)
        self.btn_find.setEnabled(has_pages)

        self.btn_first.setEnabled(has_pages and self._current_page_idx > 0)
        self.btn_prev.setEnabled(has_pages and self._current_page_idx > 0)
        self.btn_next.setEnabled(has_pages and self._current_page_idx < total - 1)
        self.btn_last.setEnabled(has_pages and self._current_page_idx < total - 1)

        self.page_box.setEnabled(has_pages)
        self.page_total_lbl.setText(f"/ {total}")

    def first_page(self):
        if self._pages:
            self._current_page_idx = 0
            self._update_controls()
            self._display_current_page()

    def prev_page(self):
        if self._pages and self._current_page_idx > 0:
            self._current_page_idx -= 1
            self._update_controls()
            self._display_current_page()

    def next_page(self):
        if self._pages and self._current_page_idx < len(self._pages) - 1:
            self._current_page_idx += 1
            self._update_controls()
            self._display_current_page()

    def last_page(self):
        if self._pages:
            self._current_page_idx = len(self._pages) - 1
            self._update_controls()
            self._display_current_page()

    def _on_page_box_entered(self):
        if not self._pages:
            return
        text = self.page_box.text().strip()
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(self._pages):
                self._current_page_idx = idx
                self._update_controls()
                self._display_current_page()
            else:
                self.page_box.setText(str(self._current_page_idx + 1))
        else:
            self.page_box.setText(str(self._current_page_idx + 1))

    def fit_to_width(self):
        vw = self.scroll_area.viewport().width()
        if vw <= 0:
            vw = self.width() - 40
        page = self._pages[self._current_page_idx] if (self._pages and 0 <= self._current_page_idx < len(self._pages)) else None
        page_w = getattr(page, "page_width", PAGE_WIDTH) if page else PAGE_WIDTH
        if vw > 0 and page_w > 0:
            factor = max(0.20, min(2.5, (vw - 40) / (page_w + 40)))
            self._zoom_factor = factor
            self.canvas.set_zoom(factor)
            self.lbl_stat_zoom.setText(f"Zoom Factor: {int(factor * 100)}%")

    def fit_to_page(self):
        vh = self.scroll_area.viewport().height()
        if vh <= 0:
            vh = self.height() - 80
        page = self._pages[self._current_page_idx] if (self._pages and 0 <= self._current_page_idx < len(self._pages)) else None
        page_h = getattr(page, "page_height", PAGE_HEIGHT) if page else PAGE_HEIGHT
        if vh > 0 and page_h > 0:
            factor = max(0.20, min(2.5, (vh - 40) / (page_h + 40)))
            self._zoom_factor = factor
            self.canvas.set_zoom(factor)
            self.lbl_stat_zoom.setText(f"Zoom Factor: {int(factor * 100)}%")

    def _on_zoom_changed(self, text: str):
        if text == "Fit to Width":
            self.fit_to_width()
        elif text == "Fit to Page":
            self.fit_to_page()
        else:
            val = text.replace("%", "").strip()
            try:
                factor = float(val) / 100.0
                self._zoom_factor = factor
                self.canvas.set_zoom(factor)
                self.lbl_stat_zoom.setText(f"Zoom Factor: {text}")
            except ValueError:
                pass

    def _on_print(self):
        self.print_requested.emit()

    def _on_export(self):
        self.export_requested.emit()

    def _on_copy(self):
        if not self._pages:
            return
        lines = []
        for p in self._pages:
            lines.append(f"{p.header.store_name} - {p.header.store_address}")
            lines.append(f"{p.header.header_line_1} | {p.header.header_line_2}")
            for b in p.blocks:
                if b.kind == BlockKind.GROUP_HEADER:
                    lines.append(b.data.get("text", ""))
                elif b.kind == BlockKind.TABLE_HEADER:
                    lines.append("\t".join(b.data.get("columns", [])))
                elif b.kind == BlockKind.DATA_ROW:
                    lines.append("\t".join(str(c) for c in b.data.get("cells", [])))
                elif b.kind in (BlockKind.ITEM_SUBTOTAL, BlockKind.BATCH_SUBTOTAL):
                    lbl = b.data.get("batch_no", "") + " Total :" if b.kind == BlockKind.BATCH_SUBTOTAL else "Total :"
                    lines.append(f"{lbl}\t{b.data.get('pay_str')}\t{b.data.get('free_str')}\t{b.data.get('amt_str')}")
                elif b.kind == BlockKind.GRAND_TOTAL:
                    lines.append(f"Grand Total :\t{b.data.get('pay_str', '')}\t{b.data.get('free_str', '')}\t{b.data.get('amt_str')}")
            lines.append("")
        QApplication.clipboard().setText("\n".join(lines))
        _show_info(self, "Copy", "Report data copied to clipboard.")

    def _on_find(self):
        if not self._pages:
            return
        text, ok = QMessageBox_getText(self, "Find in Report", "Search term:")
        if ok and text:
            q = text.strip().lower()
            found_page = None
            for p_idx, p in enumerate(self._pages):
                for b in p.blocks:
                    cells = b.data.get("cells", [])
                    txt = b.data.get("text", "")
                    if q in txt.lower() or any(q in str(c).lower() for c in cells):
                        found_page = p_idx
                        break
                if found_page is not None:
                    break
            if found_page is not None:
                self._current_page_idx = found_page
                self._update_controls()
                self._display_current_page()
                _show_info(self, "Find", f"Match found on Page {found_page + 1}.")
            else:
                _show_info(self, "Find", "No matches found.")


def _show_info(parent: Optional[QWidget], title: str, message: str):
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        QMessageBox.information(parent, title, message)


def _show_warning(parent: Optional[QWidget], title: str, message: str):
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        QMessageBox.warning(parent, title, message)


def QMessageBox_getText(parent, title, prompt) -> Tuple[str, bool]:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setFixedWidth(280)
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel(prompt))
    edit = QLineEdit()
    layout.addWidget(edit)
    btns = QHBoxLayout()
    btns.addStretch()
    btn_cancel = QPushButton("Cancel")
    btn_cancel.clicked.connect(dlg.reject)
    btn_ok = QPushButton("Find")
    btn_ok.clicked.connect(dlg.accept)
    btns.addWidget(btn_cancel)
    btns.addWidget(btn_ok)
    layout.addLayout(btns)
    res = dlg.exec()
    return edit.text(), res == QDialog.Accepted


# ── Printing & PDF Export Helper ──────────────────────────────────────

def print_or_export_report_pages(
    pages: List[ReportPage],
    parent: Optional[QWidget] = None,
    output_pdf_path: Optional[str] = None,
) -> bool:
    """Print pages or export to PDF file with identical A4 layout (portrait or landscape)."""
    if not pages:
        return False

    first_page = pages[0]
    orientation_str = getattr(first_page, "orientation", "portrait").lower()
    is_landscape = (orientation_str == "landscape")
    page_w = getattr(first_page, "page_width", PAGE_WIDTH_LANDSCAPE if is_landscape else PAGE_WIDTH)
    page_h = getattr(first_page, "page_height", PAGE_HEIGHT_LANDSCAPE if is_landscape else PAGE_HEIGHT)

    if output_pdf_path:
        try:
            from PySide6.QtGui import QPdfWriter, QPageLayout, QPageSize
            from PySide6.QtCore import QMarginsF
            writer = QPdfWriter(output_pdf_path)
            q_orient = QPageLayout.Landscape if is_landscape else QPageLayout.Portrait
            layout = QPageLayout(QPageSize(QPageSize.A4), q_orient, QMarginsF(0, 0, 0, 0))
            writer.setPageLayout(layout)
            writer.setResolution(96)
            painter = QPainter()
            if not painter.begin(writer):
                return False
            try:
                for i, page in enumerate(pages):
                    if i > 0:
                        writer.newPage()
                    draw_report_page(painter, page)
            finally:
                painter.end()
            return True
        except Exception:
            return False

    is_headless = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    if is_headless:
        # Offscreen / headless environment cannot talk to a real interactive printer.
        # Route through a temporary PDF to fully exercise the rendering and pagination pipeline without hanging.
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            return print_or_export_report_pages(pages, parent=parent, output_pdf_path=tmp_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # Physical printer output via QPrinter
    try:
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from PySide6.QtGui import QPageLayout, QPageSize
    except ImportError:
        return False

    try:
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        q_orient = QPageLayout.Landscape if is_landscape else QPageLayout.Portrait
        printer.setPageOrientation(q_orient)
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle("Print Report")
        if dlg.exec() != QPrintDialog.Accepted:
            return False

        painter = QPainter()
        if not painter.begin(printer):
            return False
        try:
            page_rect = printer.pageRect(QPrinter.DevicePixel)
            scale_x = page_rect.width() / page_w
            scale_y = page_rect.height() / page_h
            scale = min(scale_x, scale_y)

            for i, page in enumerate(pages):
                if i > 0:
                    printer.newPage()
                painter.save()
                painter.scale(scale, scale)
                draw_report_page(painter, page)
                painter.restore()
        finally:
            painter.end()
        return True
    except Exception:
        return False


# ── Base Crystal Reports Form Window ──────────────────────────────────

class BasePurchaseReportWindow(QWidget):
    """Common window layout for all 6 Purchase Reports.

    - Title Bar: Blue background with report title + close "X" at top right
    - Left (80%): CrystalReportViewer
    - Right (20%): Filter panel (light-blue, bold blue title, From/To dates, dropdown, Show Report, Print)
    """

    close_requested = Signal()

    def __init__(
        self,
        report_title: str,
        panel_title: str,
        dropdown_label: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.report_title = report_title
        self.panel_title = panel_title
        self.dropdown_label = dropdown_label
        self._pages: List[ReportPage] = []
        self._history_financial_year: Optional[Dict] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 1. Top Blue Title Bar with Close "X" ──────────────────────
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

        # Window title = report name + " Report"
        window_title_text = f"{report_title} Report" if not report_title.endswith("Report") else report_title
        self.lbl_title = QLabel(window_title_text)
        tb_layout.addWidget(self.lbl_title)
        tb_layout.addStretch()

        self.btn_close = QPushButton("✕")
        self.btn_close.setToolTip("Close Report")
        self.btn_close.clicked.connect(self._on_close)
        tb_layout.addWidget(self.btn_close)

        root.addWidget(self.title_bar)

        # ── 2. Split Area: Left 80% Viewer, Right 20% Filter Panel ────
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(2)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: #A0B0C0; }")

        # Left: Viewer
        self.viewer = CrystalReportViewer()
        self.viewer.print_requested.connect(self.print_report)
        self.viewer.export_requested.connect(self.export_report)
        main_splitter.addWidget(self.viewer)

        # Right: Filter Panel
        filter_panel = QFrame()
        filter_panel.setStyleSheet(
            "QFrame { background-color: #E8EFF7; border-left: 1px solid #B0C4DE; }"
            "QLabel { color: #003366; font-size: 12px; font-weight: bold; }"
            "QDateEdit { background: white; border: 1px solid #B0C4DE; border-radius: 2px; padding: 4px 6px; font-size: 12px; color: #000000; }"
            "QComboBox { background: white; border: 1px solid #B0C4DE; border-radius: 2px; padding: 4px 6px; font-size: 12px; color: #000000; }"
            "QPushButton { background-color: #1B5299; color: white; border: none; border-radius: 3px; padding: 7px 12px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: #2669B8; }"
            "QPushButton:disabled { background-color: #A0B8D0; color: #E0E8F0; }"
        )
        fp_layout = QVBoxLayout(filter_panel)
        fp_layout.setContentsMargins(14, 14, 14, 14)
        fp_layout.setSpacing(10)

        # Title: bold blue title (panel title)
        lbl_panel_title = QLabel(self.panel_title)
        lbl_panel_title.setStyleSheet("color: #003366; font-size: 14px; font-weight: bold; margin-bottom: 6px;")
        lbl_panel_title.setWordWrap(True)
        fp_layout.addWidget(lbl_panel_title)

        # 1. From date picker, label "To", To date picker (dd/MM/yyyy)
        self.lbl_from = QLabel("From Date:")
        fp_layout.addWidget(self.lbl_from)
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        fp_layout.addWidget(self.from_date_edit)

        self.lbl_to = QLabel("To")
        self.lbl_to.setStyleSheet("color: #003366; font-size: 12px; font-weight: bold; margin-top: 2px;")
        fp_layout.addWidget(self.lbl_to)

        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        fp_layout.addWidget(self.to_date_edit)

        # Defaults for dates
        self._init_default_dates()

        # 2. One searchable dropdown
        self.lbl_dropdown = QLabel(f"{self.dropdown_label}:")
        fp_layout.addWidget(self.lbl_dropdown)

        self.dropdown = QComboBox()
        self.dropdown.setEditable(True)
        self.dropdown.setInsertPolicy(QComboBox.NoInsert)
        if self.dropdown.completer():
            self.dropdown.completer().setCaseSensitivity(Qt.CaseInsensitive)
            self.dropdown.completer().setFilterMode(Qt.MatchContains)
        fp_layout.addWidget(self.dropdown)

        # Small validation message label (red)
        self.lbl_msg = QLabel("")
        self.lbl_msg.setStyleSheet("color: #C00000; font-size: 11px; font-weight: bold; background: transparent;")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setVisible(False)
        fp_layout.addWidget(self.lbl_msg)

        fp_layout.addSpacing(4)

        # 3. "Show Report" button
        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.clicked.connect(self._on_show_report_clicked)
        fp_layout.addWidget(self.btn_show_report)

        # 4. "Print" button directly below "Show Report", same style. Disabled initially!
        self.btn_panel_print = QPushButton("Print")
        self.btn_panel_print.setEnabled(False)
        self.btn_panel_print.clicked.connect(self.print_report)
        fp_layout.addWidget(self.btn_panel_print)

        fp_layout.addStretch()
        main_splitter.addWidget(filter_panel)

        # Set 80% / 20% width ratio
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)
        root.addWidget(main_splitter, 1)

    def _init_default_dates(self):
        active_fy = financial_year.get_active_financial_year() or financial_year.ensure_default_financial_year()
        if active_fy and active_fy.get("start_date"):
            start_parts = active_fy["start_date"].split("-")
            start_year = int(start_parts[0])
            self.from_date_edit.setDate(QDate(start_year, 4, 1))
        else:
            cur_year = QDate.currentDate().year()
            # If current month is before April, default FY start is last year
            if QDate.currentDate().month() < 4:
                cur_year -= 1
            self.from_date_edit.setDate(QDate(cur_year, 4, 1))

        self.to_date_edit.setDate(QDate.currentDate())

    def set_history_financial_year(self, year: Optional[Dict[str, Any]]):
        self._history_financial_year = dict(year) if year else None
        if self._history_financial_year:
            s_date = self._history_financial_year.get("start_date")
            e_date = self._history_financial_year.get("end_date")
            if s_date:
                p = [int(x) for x in s_date.split("-")]
                self.from_date_edit.setDate(QDate(p[0], p[1], p[2]))
            if e_date:
                p = [int(x) for x in e_date.split("-")]
                self.to_date_edit.setDate(QDate(p[0], p[1], p[2]))
        else:
            self._init_default_dates()
        if self._pages:
            self._on_show_report_clicked()

    def _on_close(self):
        self.close_requested.emit()

    def get_selected_id(self) -> Optional[int]:
        text = self.dropdown.currentText().strip()
        if not text or text.lower().startswith("-- select"):
            return None

        # 1. If current index text matches text in the line edit, use its data
        curr_idx = self.dropdown.currentIndex()
        if 0 <= curr_idx < self.dropdown.count():
            item_text = self.dropdown.itemText(curr_idx).strip()
            if item_text.lower() == text.lower():
                data = self.dropdown.itemData(curr_idx)
                if data is not None and data != "":
                    return data

        # 2. Check exact match across all items
        for i in range(self.dropdown.count()):
            if self.dropdown.itemText(i).strip().lower() == text.lower():
                data = self.dropdown.itemData(i)
                if data is not None and data != "":
                    return data

        # 3. Check prefix match across items (excluding placeholder)
        prefix_matches = [
            self.dropdown.itemData(i)
            for i in range(self.dropdown.count())
            if self.dropdown.itemText(i).strip().lower().startswith(text.lower())
            and not self.dropdown.itemText(i).strip().lower().startswith("-- select")
            and self.dropdown.itemData(i) is not None and self.dropdown.itemData(i) != ""
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

        # 4. Check substring match across items (excluding placeholder)
        sub_matches = [
            self.dropdown.itemData(i)
            for i in range(self.dropdown.count())
            if text.lower() in self.dropdown.itemText(i).strip().lower()
            and not self.dropdown.itemText(i).strip().lower().startswith("-- select")
            and self.dropdown.itemData(i) is not None and self.dropdown.itemData(i) != ""
        ]
        if len(sub_matches) == 1:
            return sub_matches[0]

        return None

    def _show_validation_error(self, message: str):
        self.lbl_msg.setText(message)
        self.lbl_msg.setVisible(True)
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QMessageBox.warning(self, "Validation Error", message)

    def _on_show_report_clicked(self):
        from_qdate = self.from_date_edit.date()
        to_qdate = self.to_date_edit.date()

        # Validate: From <= To
        if from_qdate > to_qdate:
            self._pages = []
            self.viewer.clear_report()
            self.btn_panel_print.setEnabled(False)
            self._show_validation_error("From Date must be earlier than or equal to To Date.")
            return

        # Validate: Dropdown must be selected
        selected_id = self.get_selected_id()
        if selected_id is None:
            self._pages = []
            self.viewer.clear_report()
            self.btn_panel_print.setEnabled(False)
            self._show_validation_error(f"Please select a {self.dropdown_label}.")
            return

        self.lbl_msg.setText("")
        self.lbl_msg.setVisible(False)

        from_iso = from_qdate.toString("yyyy-MM-dd")
        to_iso = to_qdate.toString("yyyy-MM-dd")

        pages = self.generate_report_pages(from_iso, to_iso, selected_id)
        self._pages = pages
        self.viewer.set_pages(pages)
        self.btn_panel_print.setEnabled(bool(pages))

    def generate_report_pages(
        self, from_date: str, to_date: str, selected_id: int
    ) -> List[ReportPage]:
        """Subclasses must implement to query data and paginate."""
        raise NotImplementedError

    def print_report(self):
        if not self._pages:
            return
        print_or_export_report_pages(self._pages, parent=self)

    def export_report(self):
        if not self._pages:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Report",
            f"{self.report_title.lower().replace(' ', '_')}.pdf",
            "PDF Files (*.pdf);;CSV Files (*.csv)",
        )
        if not path:
            return
        if path.casefold().endswith(".pdf"):
            if print_or_export_report_pages(self._pages, parent=self, output_pdf_path=path):
                _show_info(self, "Export", f"Report saved as PDF:\n{path}")
        else:
            # CSV export
            lines = []
            header_written = False
            for p in self._pages:
                for b in p.blocks:
                    if b.kind == BlockKind.TABLE_HEADER:
                        if not header_written:
                            lines.append(",".join(f'"{c}"' for c in b.data.get("columns", [])))
                            header_written = True
                    elif b.kind == BlockKind.DATA_ROW:
                        lines.append(",".join(f'"{c}"' for c in b.data.get("cells", [])))
                    elif b.kind in (BlockKind.ITEM_SUBTOTAL, BlockKind.BATCH_SUBTOTAL):
                        lbl = b.data.get("batch_no", "") + " Total :" if b.kind == BlockKind.BATCH_SUBTOTAL else "Total :"
                        lines.append(f'"{lbl}",,,,,,"{b.data.get("pay_str")}","{b.data.get("free_str")}","{b.data.get("amt_str")}"')
                    elif b.kind == BlockKind.GRAND_TOTAL:
                        lines.append(f'"{b.data.get("label", "Grand Total :")}",,,,,,"{b.data.get("pay_str", "")}","{b.data.get("free_str", "")}","{b.data.get("amt_str")}"')
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                _show_info(self, "Export", f"Report saved as CSV:\n{path}")
            except Exception as exc:
                _show_warning(self, "Export Error", f"Failed to save CSV: {exc}")
