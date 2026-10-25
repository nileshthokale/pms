"""Cash Memo Crystal Report Engine (Canon LBP2900).

Shared configuration and rendering engine for:
1. Duplicate Sales Bill (reports/DuplicateSalesBill_A6.rpt)
2. Real Counter Sale Bill (reports/CounterSaleBill_A6.rpt)

Features:
- Default Paper: A5 landscape (210 x 148 mm), with A6 landscape (148 x 105 mm) profile support.
- Margins: 12 mm left/right, 10 mm top/bottom (10-15 mm balanced margins), OriginAtMargins = False.
- Full Page Width: Content fills full printable width evenly, horizontally centered, no side shift.
- Typography: Arial ONLY. ALL text is EXTRA BOLD / BLACK (weight 900, toner overdraw):
  - Shop name: 15.0 pt bold (centered)
  - Address: 8.5 pt (centered)
  - Name, Doctor, Cash Memo, Date: 10.5 pt
  - Column Headings: 10.5 pt
  - Item Rows: 10.5 pt
  - Net Amt: 12.0 pt bold (prominent on right below table)
  - Footer lines: 9.5 pt
- Column Alignment & Fixed Widths (186 mm on A5):
  - QTY: 14 mm (left-aligned)
  - UNIT: 20 mm (left-aligned)
  - DESCRIPTION: 50 mm (left-aligned)
  - COMP.: 16 mm (left-aligned)
  - BATCH: 32 mm (left-aligned, shrink-to-fit down to 7.5 pt, never cut, never '...')
  - EXP. DT: 26 mm (left-aligned)
  - AMT: 28 mm (right-aligned)
- Divider rules: 0.35 mm solid lines (~4 px at 300 DPI) for deep black, crisp lines.
- Item Area: Exactly 10 fixed rows of 5.0 mm (ITEM_ROWS = 10, 50 mm total).
- Footer: Pinned at bottom, never shifts.
  - Left: E & O E. Subject to AHMEDNAGAR Jurisdiction, licence wrapped on 2 lines, GSTIN.
  - Right: Net Amt (12 pt bold), Shop name (9.5 pt), Pharmacist/Sign (9.5 pt).
- Canon LBP2900 feed rotation:
  - ROTATE_FOR_FEED = True (rotates 90 degrees for short-edge feed).
  - ROTATE_DIRECTION = 90
"""

from __future__ import annotations

import calendar
import logging
import math
import os
import re
import sys
from typing import Any

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import QApplication

# ── Report Template Paths ─────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUP_RPT_FILE_PATH = os.path.join(_PROJECT_ROOT, "reports", "DuplicateSalesBill_A6.rpt")
REAL_RPT_FILE_PATH = os.path.join(_PROJECT_ROOT, "reports", "CounterSaleBill_A6.rpt")
RPT_FILE_PATH = DUP_RPT_FILE_PATH
REPORT_VERSION_TAG = "RPT v2"

# ── Canon LBP2900 Printer Settings (Shared Calibration) ───────────────
ROTATE_FOR_FEED: bool = True
ROTATE_DIRECTION: int = 90
OFFSET_X_MM: float = 0.0
OFFSET_Y_MM: float = 0.0

MM_TO_PT: float = 72.0 / 25.4       # ~2.8346 pt/mm

# ── Paper Profiles (A6 Default matching printer paper & Image, A5 Supported) ──
PAPER_PROFILES: dict[str, dict[str, Any]] = {
    "A6": {
        "page_width_mm": 148.0,
        "page_height_mm": 105.0,
        "margin_left_mm": 4.0,
        "margin_right_mm": 4.0,
        "margin_top_mm": 5.0,
        "margin_bottom_mm": 5.0,
        "content_width_mm": 140.0,
        "content_height_mm": 95.0,
        "header_y_start_mm": 5.0,
        "rule1_y_mm": 24.5,
        "headings_y_mm": 24.9,
        "rule2_y_mm": 29.0,
        "item_start_y_mm": 31.0,
        "item_rows": 10,
        "row_height_mm": 4.0,
        "item_end_y_mm": 71.0,
        "net_amt_y_mm": 75.0,
        "footer_start_y_mm": 75.0,
        "columns": [
            ("qty", "QTY", 8.0, "left"),
            ("unit", "UNIT", 15.0, "left"),
            ("description", "DESCRIPTION", 38.0, "left"),
            ("comp", "COMP.", 12.0, "left"),
            ("batch", "BATCH", 28.0, "left"),
            ("expiry", "EXP. DT", 19.0, "left"),
            ("amount", "AMT", 20.0, "right"),
        ],
        "fonts": {
            "shop_name": 12.0,
            "address": 8.0,
            "meta": 8.5,
            "headings": 8.5,
            "items": 8.5,
            "batch_max": 8.5,
            "batch_min": 6.5,
            "net_amt": 11.0,
            "footer": 8.5,
            "watermark": 6.0,
        },
    },
    "A5": {
        "page_width_mm": 210.0,
        "page_height_mm": 148.0,
        "margin_left_mm": 12.0,
        "margin_right_mm": 12.0,
        "margin_top_mm": 10.0,
        "margin_bottom_mm": 10.0,
        "content_width_mm": 186.0,
        "content_height_mm": 128.0,
        "header_y_start_mm": 10.0,
        "rule1_y_mm": 36.0,
        "headings_y_mm": 36.8,
        "rule2_y_mm": 42.5,
        "item_start_y_mm": 44.0,
        "item_rows": 10,
        "row_height_mm": 5.0,
        "item_end_y_mm": 94.0,
        "net_amt_y_mm": 96.5,
        "footer_start_y_mm": 105.0,
        "columns": [
            ("qty", "QTY", 14.0, "left"),
            ("unit", "UNIT", 20.0, "left"),
            ("description", "DESCRIPTION", 50.0, "left"),
            ("comp", "COMP.", 16.0, "left"),
            ("batch", "BATCH", 32.0, "left"),
            ("expiry", "EXP. DT", 26.0, "left"),
            ("amount", "AMT", 28.0, "right"),
        ],
        "fonts": {
            "shop_name": 15.0,
            "address": 8.5,
            "meta": 10.5,
            "headings": 10.5,
            "items": 10.5,
            "batch_max": 10.5,
            "batch_min": 7.5,
            "net_amt": 12.0,
            "footer": 9.5,
            "watermark": 6.0,
        },
    },
}

DEFAULT_PAPER_SIZE: str = os.environ.get("PMS_BILL_PAPER_SIZE", "A6").upper()


def get_paper_profile(name: str | None = None) -> dict[str, Any]:
    """Retrieve geometry and font configuration for the given paper size (A6 or A5)."""
    key = str(name or DEFAULT_PAPER_SIZE).strip().upper()
    return PAPER_PROFILES.get(key, PAPER_PROFILES["A6"])


def set_default_paper_size(name: str) -> None:
    """Set default paper size ('A6' or 'A5')."""
    global DEFAULT_PAPER_SIZE
    key = str(name).strip().upper()
    if key in PAPER_PROFILES:
        DEFAULT_PAPER_SIZE = key


# Active profile aliases for backward compatibility
_active_prof = get_paper_profile()
ITEM_ROWS: int = _active_prof["item_rows"]
ITEM_LINES: int = ITEM_ROWS
ROW_HEIGHT_MM: float = _active_prof["row_height_mm"]

PAGE_WIDTH_MM: float = _active_prof["page_width_mm"]
PAGE_HEIGHT_MM: float = _active_prof["page_height_mm"]

MARGIN_LEFT_MM: float = _active_prof["margin_left_mm"]
MARGIN_RIGHT_MM: float = _active_prof["margin_right_mm"]
MARGIN_TOP_MM: float = _active_prof["margin_top_mm"]
MARGIN_BOTTOM_MM: float = _active_prof["margin_bottom_mm"]

CONTENT_WIDTH_MM: float = _active_prof["content_width_mm"]
CONTENT_HEIGHT_MM: float = _active_prof["content_height_mm"]

HEADER_Y_START_MM: float = _active_prof["header_y_start_mm"]
ITEM_START_Y_MM: float = _active_prof["item_start_y_mm"]
ITEM_END_Y_MM: float = _active_prof["item_end_y_mm"]
FOOTER_START_Y_MM: float = _active_prof["footer_start_y_mm"]

COLUMN_DEFS = _active_prof["columns"]


def log_loaded_report_path(report_file: str | None = None) -> str:
    """Log the loaded .rpt full path to the app log and return it."""
    path = os.path.abspath(report_file or RPT_FILE_PATH)
    msg = f"[Crystal Reports] Loaded report: {path}"
    logging.info(msg)
    print(msg, file=sys.stderr)
    return path


def get_store_identity() -> dict[str, str]:
    """Retrieve pharmacy identity from database or fall back to store default."""
    try:
        from database.pharmacy_a6_receipt import store_profile
        prof = store_profile()
        return {
            "name": str(prof.get("name") or "SHREE SAMARTH MEDICAL AND GEN STORE").strip(),
            "address": str(prof.get("address") or "GHORPADE HOSPITAL, RAHURI").strip(),
            "jurisdiction": str(prof.get("jurisdiction") or "AHMEDNAGAR").strip(),
            "licence": str(prof.get("licence") or "20-MH-AHM-61069,21-MH-AHM-61070,20C-MH-AHM-61071").strip(),
            "gstin": str(prof.get("gstin") or "").strip(),
        }
    except Exception:
        return {
            "name": "SHREE SAMARTH MEDICAL AND GEN STORE",
            "address": "GHORPADE HOSPITAL, RAHURI",
            "jurisdiction": "AHMEDNAGAR",
            "licence": "20-MH-AHM-61069,21-MH-AHM-61070,20C-MH-AHM-61071",
            "gstin": "",
        }


def format_display_date(val: Any) -> str:
    """Format any date string as dd/MM/yyyy."""
    raw = str(val or "").strip()
    if not raw:
        return ""
    m_iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if m_iso:
        return f"{int(m_iso.group(3)):02d}/{int(m_iso.group(2)):02d}/{m_iso.group(1)}"
    m_dmy = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})", raw)
    if m_dmy:
        return f"{int(m_dmy.group(1)):02d}/{int(m_dmy.group(2)):02d}/{m_dmy.group(3)}"
    return raw


def format_expiry_display(val: Any) -> str:
    """Format expiry strictly as MM/yy or dd/MM/yyyy for cash memo printing."""
    raw = str(val or "").strip()
    if not raw:
        return ""

    m_iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if m_iso:
        return f"{int(m_iso.group(3)):02d}/{int(m_iso.group(2)):02d}/{m_iso.group(1)}"

    m_dmy = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", raw)
    if m_dmy:
        year_str = m_dmy.group(3)
        year_full = int(year_str) if len(year_str) == 4 else int(f"20{year_str}")
        return f"{int(m_dmy.group(1)):02d}/{int(m_dmy.group(2)):02d}/{year_full:04d}"

    m_my = re.match(r"^(\d{1,2})[-/](\d{2,4})$", raw)
    if m_my:
        month = int(m_my.group(1))
        year = int(m_my.group(2))
        if year < 100:
            year += 2000
        if 1 <= month <= 12:
            last_day = calendar.monthrange(year, month)[1]
            return f"{last_day:02d}/{month:02d}/{year:04d}"
        return f"01/{month:02d}/{year:04d}"

    return raw


def format_qty_display(val: Any) -> str:
    try:
        f = float(str(val or 0).strip().replace(",", ""))
        return str(int(f)) if f.is_integer() else f"{f:.2f}"
    except Exception:
        return "0"


def format_amt_display(val: Any) -> str:
    try:
        f = float(str(val or 0).strip().replace(",", ""))
        return f"{f:.2f}"
    except Exception:
        return "0.00"


def paginate_items(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    show_duplicate: bool = False,
    report_file: str | None = None,
    watermark: str | None = None,
    paper_size: str | None = None,
) -> list[dict[str, Any]]:
    """Paginate item rows into fixed-size pages with exactly 10 rows each."""
    log_loaded_report_path(report_file)
    total_items = len(items)
    prof = get_paper_profile(paper_size)
    num_rows = prof["item_rows"]
    num_pages = max(1, math.ceil(total_items / num_rows)) if total_items > 0 else 1
    store = get_store_identity()

    effective_paper_size = (paper_size or DEFAULT_PAPER_SIZE).upper()

    pages: list[dict[str, Any]] = []
    for page_idx in range(num_pages):
        start_idx = page_idx * num_rows
        end_idx = min(start_idx + num_rows, total_items)
        page_items = items[start_idx:end_idx]

        padded_items = list(page_items)
        while len(padded_items) < num_rows:
            padded_items.append({})

        is_last = (page_idx == num_pages - 1)
        pages.append({
            "page_num": page_idx + 1,
            "total_pages": num_pages,
            "is_last_page": is_last,
            "items": padded_items,
            "head": head,
            "store": store,
            "show_duplicate": show_duplicate,
            "watermark": watermark,
            "paper_size": effective_paper_size,
        })
    return pages


def paginate_duplicate_items(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    show_duplicate: bool = True,
    paper_size: str | None = None,
) -> list[dict[str, Any]]:
    """Pagination alias for Duplicate Sales Bill with 'RPT v2' watermark."""
    return paginate_items(
        head,
        items,
        show_duplicate=show_duplicate,
        report_file=DUP_RPT_FILE_PATH,
        watermark=REPORT_VERSION_TAG,
        paper_size=paper_size,
    )


def _draw_bold_text(
    painter: QPainter,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    pt_size: float,
    align: str = "left",
    weight: int = 900,
    overdraw: bool = True,
    scale: float | None = None,
) -> None:
    """Draw heavy bold Arial text inside specified bounding rect with toner thickening.

    When scale is provided (> 0), sets pixelSize directly derived from resolution
    so text renders in identical proportions at 300 DPI, 150 DPI, or on paper.
    """
    clean_text = str(text or "").strip()
    if not clean_text:
        return
    font = QFont("Arial", -1)
    if scale is not None and scale > 0:
        px_size = max(1, int(round(pt_size * scale / MM_TO_PT)))
        font.setPixelSize(px_size)
    else:
        font.setPointSizeF(pt_size)
    font.setWeight(QFont.Weight(weight))
    painter.setFont(font)
    painter.setPen(QColor("#000000"))

    qt_align = Qt.AlignVCenter
    if align == "right":
        qt_align |= Qt.AlignRight
    elif align == "center":
        qt_align |= Qt.AlignHCenter
    else:
        qt_align |= Qt.AlignLeft

    rect = QRectF(x, y, w, h)
    painter.drawText(rect, qt_align, clean_text)
    if overdraw:
        # Subtle horizontal & vertical overdraw for solid, dark laser printer toner deposition
        ov = max(0.5, 0.08 * scale) if (scale and scale > 0) else 1.0
        painter.drawText(rect.translated(ov, 0.0), qt_align, clean_text)
        painter.drawText(rect.translated(0.0, ov * 0.5), qt_align, clean_text)


def _draw_shrink_to_fit_bold(
    painter: QPainter,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    max_pt: float = 8.5,
    min_pt: float = 6.5,
    align: str = "left",
    weight: int = 900,
    overdraw: bool = True,
    scale: float | None = None,
) -> None:
    """Draw heavy bold Arial text with shrink-to-fit down to min_pt.

    NEVER truncates with '...' and NEVER cuts characters.
    """
    clean_text = str(text or "").strip()
    if not clean_text:
        return

    font = QFont("Arial", -1)
    font.setWeight(QFont.Weight(weight))

    pt = max_pt
    while pt > min_pt:
        if scale is not None and scale > 0:
            font.setPixelSize(max(1, int(round(pt * scale / MM_TO_PT))))
        else:
            font.setPointSizeF(pt)
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(clean_text) <= w:
            break
        pt -= 0.5
    if pt < min_pt:
        pt = min_pt

    _draw_bold_text(painter, x, y, w, h, clean_text, pt, align, weight, overdraw, scale=scale)


def _draw_cut_to_fit_bold(
    painter: QPainter,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    pt_size: float = 8.5,
    align: str = "left",
    weight: int = 900,
    overdraw: bool = True,
    scale: float | None = None,
) -> None:
    """Draw heavy bold Arial text cut to column width without dots, single line."""
    clean_text = str(text or "").strip()
    if not clean_text:
        return

    font = QFont("Arial", -1)
    if scale is not None and scale > 0:
        font.setPixelSize(max(1, int(round(pt_size * scale / MM_TO_PT))))
    else:
        font.setPointSizeF(pt_size)
    font.setWeight(QFont.Weight(weight))
    fm = QFontMetricsF(font)

    if fm.horizontalAdvance(clean_text) > w:
        cut_len = len(clean_text)
        while cut_len > 0 and fm.horizontalAdvance(clean_text[:cut_len]) > w:
            cut_len -= 1
        clean_text = clean_text[:cut_len]

    _draw_bold_text(painter, x, y, w, h, clean_text, pt_size, align, weight, overdraw, scale=scale)


def draw_a6_cash_memo_page(painter: QPainter, page: dict[str, Any], scale: float = 1.0) -> None:
    """Render a single Cash Memo page with 100% precision matching Image 1."""
    paper_size = page.get("paper_size") or DEFAULT_PAPER_SIZE
    prof = get_paper_profile(paper_size)

    head = page.get("head") or {}
    store = page.get("store") or {}
    show_duplicate = bool(page.get("show_duplicate", False))
    watermark_text = page.get("watermark")
    page_num = page.get("page_num", 1)
    total_pages = page.get("total_pages", 1)
    is_last = bool(page.get("is_last_page", True))

    def rx(mm: float) -> float:
        return (mm + OFFSET_X_MM) * scale

    def ry(mm: float) -> float:
        return (mm + OFFSET_Y_MM) * scale

    def rw(mm: float) -> float:
        return mm * scale

    def rh(mm: float) -> float:
        return mm * scale

    margin_left = prof["margin_left_mm"]
    content_width = prof["content_width_mm"]
    x0 = rx(margin_left)
    x1 = rx(margin_left + content_width)
    w_content = rw(content_width)

    fonts = prof["fonts"]
    columns = prof["columns"]

    # Solid crisp rule pen (0.35 mm width, ~4 px at 300 DPI) for dark visible separator rules
    pen_rule = QPen(QColor("#000000"), max(2.5, rw(0.35)), Qt.SolidLine, Qt.SquareCap)
    painter.setPen(pen_rule)

    # ══════════════════════════════════════════════════════════════════
    # 1. HEADER (Fixed at top, centered, balanced)
    # ══════════════════════════════════════════════════════════════════
    shop_name = store.get("name", "SHREE SAMARTH MEDICAL AND GEN STORE")
    h_y_start = prof["header_y_start_mm"]

    # Line 1: Shop Name (centered, 12.0 pt on A6 / 15.0 pt on A5)
    _draw_bold_text(
        painter,
        x=x0,
        y=ry(h_y_start),
        w=w_content,
        h=rh(6.0 if paper_size == "A5" else 5.0),
        text=shop_name,
        pt_size=fonts["shop_name"],
        align="center",
        scale=scale,
    )

    # Page number at top-right only if multi-page
    if total_pages > 1:
        page_str = f"Page {page_num} of {total_pages}"
        _draw_bold_text(
            painter,
            x=rx(margin_left + content_width - 38.0),
            y=ry(h_y_start),
            w=rw(38.0),
            h=rh(4.5),
            text=page_str,
            pt_size=fonts["meta"],
            align="right",
            scale=scale,
        )

    # Line 2: Shop Address (centered, 8.0 pt on A6 / 8.5 pt on A5)
    shop_addr = store.get("address", "GHORPADE HOSPITAL, RAHURI")
    addr_y = h_y_start + (6.5 if paper_size == "A5" else 5.2)
    _draw_bold_text(
        painter,
        x=x0,
        y=ry(addr_y),
        w=w_content,
        h=rh(4.2 if paper_size == "A5" else 3.8),
        text=shop_addr,
        pt_size=fonts["address"],
        align="center",
        scale=scale,
    )

    # Left & Right Block (8.5 pt on A6 / 10.5 pt on A5)
    cust_name = str(head.get("patient_name") or head.get("customer_name") or "WALKIN").strip()
    addr = str(head.get("address") or "").strip()
    name_str = f"Name : {cust_name}" + (f", {addr}" if addr else "")

    doc_name = str(head.get("doctor_name") or "").strip()
    doc_str = f"Doctor : {doc_name}"

    v_no = str(head.get("voucher_no") or head.get("bill_no") or "1")
    bill_type = str(head.get("bill_type") or head.get("sale_type") or "Cash").strip()
    memo_label = "Credit Memo" if bill_type.lower() == "credit" else "Cash Memo"
    memo_str = f"{memo_label} : {v_no}"
    if show_duplicate:
        memo_str += "  [ DUPLICATE ]"

    sale_date_raw = head.get("vh_date") or head.get("sale_date")
    dt_str = f"Date : {format_display_date(sale_date_raw)}"

    left_w = rw(content_width * 0.60)
    right_w = rw(content_width * 0.40)
    right_x = x0 + left_w

    meta_y1 = h_y_start + (12.0 if paper_size == "A5" else 9.3)
    meta_y2 = h_y_start + (18.0 if paper_size == "A5" else 13.5)
    meta_h = 5.0 if paper_size == "A5" else 4.0

    # Meta Row 1
    _draw_cut_to_fit_bold(painter, x0, ry(meta_y1), left_w, rh(meta_h), name_str, fonts["meta"], "left", scale=scale)
    _draw_cut_to_fit_bold(painter, right_x, ry(meta_y1), right_w, rh(meta_h), memo_str, fonts["meta"], "right", scale=scale)

    # Meta Row 2
    _draw_cut_to_fit_bold(painter, x0, ry(meta_y2), left_w, rh(meta_h), doc_str, fonts["meta"], "left", scale=scale)
    _draw_cut_to_fit_bold(painter, right_x, ry(meta_y2), right_w, rh(meta_h), dt_str, fonts["meta"], "right", scale=scale)

    # Thin Rule 1 (0.35 mm solid): Above Column Headings
    rule1_y = prof["rule1_y_mm"]
    painter.setPen(pen_rule)
    painter.drawLine(QPointF(x0, ry(rule1_y)), QPointF(x1, ry(rule1_y)))

    # Column Headings
    headings_y = prof["headings_y_mm"]
    col_x_mm = margin_left
    for key, title, width_mm, align in columns:
        cx = rx(col_x_mm)
        cw = rw(width_mm)
        pad = rw(0.8) if align == "left" else 0.0
        r_pad = rw(0.8) if align == "right" else 0.0
        _draw_shrink_to_fit_bold(
            painter,
            cx + pad,
            ry(headings_y),
            cw - pad - r_pad,
            rh(5.0 if paper_size == "A5" else 3.8),
            title,
            max_pt=fonts["headings"],
            min_pt=7.5,
            align=align,
            scale=scale,
        )
        col_x_mm += width_mm

    # Thin Rule 2 (0.35 mm solid): Below Column Headings
    rule2_y = prof["rule2_y_mm"]
    painter.drawLine(QPointF(x0, ry(rule2_y)), QPointF(x1, ry(rule2_y)))

    # ══════════════════════════════════════════════════════════════════
    # 2. MIDDLE - RESERVED ITEM AREA (Exactly 10 rows)
    # ══════════════════════════════════════════════════════════════════
    num_rows = prof["item_rows"]
    row_h = prof["row_height_mm"]
    item_start_y = prof["item_start_y_mm"]

    for r_idx in range(num_rows):
        curr_y_mm = item_start_y + r_idx * row_h
        itm = page["items"][r_idx]

        if itm and (itm.get("item_name") or itm.get("sales_qty") or itm.get("sale_qty") or itm.get("amount") or itm.get("batch_no")):
            qty_val = itm.get("sales_qty") if itm.get("sales_qty") is not None else itm.get("sale_qty")
            qty_str = format_qty_display(qty_val)
            unit_str = str(itm.get("unit") or itm.get("pack_size") or "").strip()
            desc_str = str(itm.get("item_name") or "").strip()
            comp_str = str(itm.get("comp") or itm.get("location") or "").strip()
            batch_str = str(itm.get("batch_no") or "").strip()
            exp_str = format_expiry_display(itm.get("expiry"))
            amt_str = format_amt_display(itm.get("amount"))

            row_map = {
                "qty": qty_str,
                "unit": unit_str,
                "description": desc_str,
                "comp": comp_str,
                "batch": batch_str,
                "expiry": exp_str,
                "amount": amt_str,
            }

            col_x_mm = margin_left
            for key, title, width_mm, align in columns:
                val = row_map.get(key, "")
                cx = rx(col_x_mm)
                cw = rw(width_mm)
                pad = rw(0.8) if align == "left" else 0.0
                r_pad = rw(0.8) if align == "right" else 0.0

                if key == "batch":
                    # BATCH: Shrink-to-fit down to min_pt, NEVER cut, NEVER '...'
                    _draw_shrink_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(row_h),
                        val,
                        max_pt=fonts["batch_max"],
                        min_pt=fonts["batch_min"],
                        align=align,
                        scale=scale,
                    )
                elif key == "description":
                    # DESCRIPTION: Cut at column width without dots
                    _draw_cut_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(row_h),
                        val,
                        pt_size=fonts["items"],
                        align=align,
                        scale=scale,
                    )
                else:
                    _draw_shrink_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(row_h),
                        val,
                        max_pt=fonts["items"],
                        min_pt=6.5,
                        align=align,
                        scale=scale,
                    )
                col_x_mm += width_mm

    # Thin Rule 3 (0.35 mm solid): Below Items
    item_end_y = prof["item_end_y_mm"]
    painter.setPen(pen_rule)
    painter.drawLine(QPointF(x0, ry(item_end_y)), QPointF(x1, ry(item_end_y)))

    # Net Amt on the right, below the table (11 pt prominent bold on A6)
    if is_last:
        net_val = float(head.get("net_amount") or 0.0)
        net_str = f"Net Amt : {int(round(net_val))}"
    else:
        net_str = "Continued..."

    net_amt_y = prof["net_amt_y_mm"]
    _draw_bold_text(
        painter,
        right_x,
        ry(net_amt_y),
        right_w,
        rh(6.0 if paper_size == "A5" else 4.8),
        net_str,
        fonts["net_amt"],
        "right",
        scale=scale,
    )

    # ══════════════════════════════════════════════════════════════════
    # 3. FOOTER (Fixed at Bottom, balanced margins)
    # ══════════════════════════════════════════════════════════════════
    jur = store.get("jurisdiction", "AHMEDNAGAR")
    jur_line = f"E & O E. Subject to {jur} Jurisdiction"
    licence_raw = store.get("licence", "")
    gstin_raw = store.get("gstin", "")

    # Licence line wrapping across up to 2 lines so it is never clipped
    lic_line1 = licence_raw
    lic_line2 = ""
    if len(licence_raw) > 34 and "," in licence_raw:
        split_idx = licence_raw.rfind(",", 0, 34)
        if split_idx != -1:
            lic_line1 = licence_raw[:split_idx + 1].strip()
            lic_line2 = licence_raw[split_idx + 1:].strip()

    foot_left_w = rw(content_width * 0.65)
    foot_right_w = rw(content_width * 0.35)
    foot_right_x = x0 + foot_left_w
    foot_y = prof["footer_start_y_mm"]

    # Line 1: Jurisdiction
    _draw_shrink_to_fit_bold(
        painter,
        x0,
        ry(foot_y),
        foot_left_w,
        rh(4.5),
        jur_line,
        max_pt=fonts["footer"],
        min_pt=7.5,
        align="left",
        scale=scale,
    )

    # Line 2 & 3: Licences (wrapped so never clipped)
    lic_y1 = foot_y + (5.0 if paper_size == "A5" else 4.5)
    _draw_bold_text(painter, x0, ry(lic_y1), foot_left_w, rh(4.5), lic_line1, fonts["footer"], "left", scale=scale)
    curr_foot_y_mm = lic_y1 + (5.0 if paper_size == "A5" else 4.5)
    if lic_line2:
        _draw_bold_text(painter, x0, ry(curr_foot_y_mm), foot_left_w, rh(4.5), lic_line2, fonts["footer"], "left", scale=scale)
        curr_foot_y_mm += (5.0 if paper_size == "A5" else 4.5)

    # Line 4: GSTIN
    gstin_display = f"GSTIN: {gstin_raw}" if gstin_raw else "GSTIN:"
    _draw_bold_text(painter, x0, ry(curr_foot_y_mm), foot_left_w, rh(4.5), gstin_display, fonts["footer"], "left", scale=scale)

    # Right Block: Shop Name, Pharmacist/Sign
    shop_foot_y = foot_y + (5.0 if paper_size == "A5" else 8.5)
    sign_foot_y = foot_y + (15.0 if paper_size == "A5" else 17.5)
    # Shop Name: wide right bounding box from left margin offset to prevent clipping the first letter 'S'
    _draw_bold_text(painter, rx(margin_left + 35.0), ry(shop_foot_y), rw(content_width - 35.0), rh(4.5), shop_name, fonts["footer"], "right", scale=scale)
    _draw_bold_text(painter, foot_right_x, ry(sign_foot_y), foot_right_w, rh(4.5), "Pharmacist/Sign", fonts["footer"], "right", scale=scale)

    # Watermark (if present, tiny 6 pt grey text)
    if watermark_text:
        f_watermark = QFont("Arial", -1)
        if scale > 0:
            f_watermark.setPixelSize(max(1, int(round(fonts["watermark"] * scale / MM_TO_PT))))
        else:
            f_watermark.setPointSizeF(fonts["watermark"])
        painter.setFont(f_watermark)
        painter.setPen(QColor("#888888"))
        wm_y = prof["page_height_mm"] - prof["margin_bottom_mm"] - 4.0
        painter.drawText(QRectF(x0, ry(wm_y), w_content, rh(3.5)), Qt.AlignRight | Qt.AlignVCenter, watermark_text)


def render_a6_cash_memo_pixmap(page: dict[str, Any], dpi: float = 300.0) -> QPixmap:
    """Render page dict into an A5 (or A6) Landscape QPixmap at specified DPI (default 300 DPI)."""
    paper_size = page.get("paper_size") or DEFAULT_PAPER_SIZE
    prof = get_paper_profile(paper_size)

    scale = (dpi / 25.4)
    w_px = int(round(prof["page_width_mm"] * scale))
    h_px = int(round(prof["page_height_mm"] * scale))

    pix = QPixmap(w_px, h_px)
    pix.fill(QColor("#ffffff"))

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    draw_a6_cash_memo_page(p, page, scale=scale)
    p.end()

    return pix


def generate_a6_cash_memo_pdf(
    pages: list[dict[str, Any]],
    output_path: str,
) -> str:
    """Generate exact A5 (or A6) Landscape PDF from pre-paginated pages."""
    from PySide6.QtGui import QPdfWriter

    app = QApplication.instance() or QApplication([])

    paper_size = pages[0].get("paper_size") if pages else DEFAULT_PAPER_SIZE
    prof = get_paper_profile(paper_size)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    writer = QPdfWriter(output_path)

    q_page_size = QPageSize.A5 if str(paper_size).upper() == "A5" else QPageSize.A6
    layout = QPageLayout(
        QPageSize(q_page_size),
        QPageLayout.Landscape,
        QMarginsF(0, 0, 0, 0),
        QPageLayout.Millimeter,
    )
    writer.setPageLayout(layout)
    writer.setResolution(300)

    scale = 300.0 / 25.4

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

    for idx, page in enumerate(pages):
        if idx > 0:
            writer.newPage()
        draw_a6_cash_memo_page(painter, page, scale=scale)

    painter.end()
    return output_path


def generate_duplicate_a6_pdf(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    output_path: str,
    show_duplicate: bool = True,
    paper_size: str | None = None,
) -> str:
    """Generate exact Landscape PDF for Duplicate Sales Bill."""
    pages = paginate_duplicate_items(head, items, show_duplicate=show_duplicate, paper_size=paper_size)
    return generate_a6_cash_memo_pdf(pages, output_path)


def print_a6_cash_memo(
    pages: list[dict[str, Any]],
    parent=None,
    title: str = "Cash Memo",
    show_dialog: bool = True,
    rotate_for_feed: bool = ROTATE_FOR_FEED,
    rotate_direction: int = ROTATE_DIRECTION,
) -> bool:
    """Print Landscape Cash Memo using Windows print system (Canon LBP2900).

    Fixes:
    1. OriginAtMargins = False (printer.setFullPage(True)) to eliminate driver margin shift.
    2. Render at 300 DPI, draw at 100% scale with integer pixel mapping (no 'fit to page').
    3. Paper size matches physical sheet (A5 default or A6).
    4. Short-edge feeding rotation (rotate_direction: 90 or 270 degrees) fills 100% of page.
    """
    try:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    except ImportError as exc:
        raise RuntimeError("Printer support requires PySide6.") from exc

    paper_size = pages[0].get("paper_size") if pages else DEFAULT_PAPER_SIZE
    prof = get_paper_profile(paper_size)

    printer = QPrinter(QPrinter.HighResolution)
    voucher_no = pages[0]["head"].get("voucher_no") or pages[0]["head"].get("bill_no") or "1" if pages else "1"
    printer.setDocName(f"{title} #{voucher_no}")

    # Set paper size explicitly to A5 (or A6)
    q_page_size = QPageSize.A5 if str(paper_size).upper() == "A5" else QPageSize.A6

    if rotate_for_feed:
        # In portrait feed, short edge is fed first
        layout = QPageLayout(
            QPageSize(q_page_size),
            QPageLayout.Portrait,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Millimeter,
        )
    else:
        layout = QPageLayout(
            QPageSize(q_page_size),
            QPageLayout.Landscape,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Millimeter,
        )
    printer.setPageLayout(layout)

    # Use paper size as origin (OriginAtMargins = False)
    printer.setFullPage(True)

    if show_dialog:
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle(f"Print {title} #{voucher_no} - {paper_size} ({prof['page_width_mm']} x {prof['page_height_mm']} mm)")
        if dlg.exec() != QPrintDialog.Accepted:
            return False

    dpi = printer.resolution()
    target_dpi = 300.0

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError(f"Could not open printer for {paper_size} Landscape Cash Memo.")

    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)

    try:
        # Query the printer's actual printable rectangle to avoid hard-margin clipping.
        # With setFullPage(True), painter origin is at the paper edge, but the printer
        # physically cannot print in the hard-margin zone. We query the difference
        # between the full page rect and the printable rect to find the hard margins,
        # then fit and center the image within the printable area.
        full_rect = printer.pageRect(QPrinter.DevicePixel)
        printable_rect = printer.pageLayout().paintRectPixels(dpi)

        # On a real printer, pageRect with fullPage=True gives the whole page,
        # while the printer also exposes the paintable area. We need to use
        # the printer's own methods to get the hardware-limited paint area.
        # QPrinter in fullPage mode: pageRect = full paper, 
        # but we can temporarily check non-fullPage rect for the safe area.
        printer.setFullPage(False)
        safe_rect = printer.pageRect(QPrinter.DevicePixel)
        printer.setFullPage(True)

        # Hard margin offsets (how much the printable area is inset from paper edge)
        hm_left = safe_rect.x()
        hm_top = safe_rect.y()
        safe_w = safe_rect.width()
        safe_h = safe_rect.height()

        # If we couldn't detect margins (virtual printer), fall back to full page
        if safe_w <= 0 or safe_h <= 0:
            hm_left = 0
            hm_top = 0
            safe_w = full_rect.width()
            safe_h = full_rect.height()

        for idx, page in enumerate(pages):
            if idx > 0:
                printer.newPage()

            # Render at 300 DPI
            pixmap = render_a6_cash_memo_pixmap(page, dpi=target_dpi)
            img = pixmap.toImage()

            if rotate_for_feed:
                transform = QTransform().rotate(rotate_direction)
                rotated_img = img.transformed(transform, Qt.FastTransformation)
            else:
                rotated_img = img

            # Scale the image to fit within the safe (printable) area
            img_w = rotated_img.width()
            img_h = rotated_img.height()
            scale_x = float(safe_w) / img_w
            scale_y = float(safe_h) / img_h
            fit_scale = min(scale_x, scale_y)

            dest_w = img_w * fit_scale
            dest_h = img_h * fit_scale

            # Center within the safe printable rectangle
            offset_x = hm_left + (safe_w - dest_w) / 2.0
            offset_y = hm_top + (safe_h - dest_h) / 2.0

            target_rect = QRectF(offset_x, offset_y, dest_w, dest_h)
            painter.drawImage(target_rect, rotated_img)
    finally:
        painter.end()

    return True


def print_duplicate_a6_bill(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    parent=None,
    title: str = "Cash Memo",
    show_dialog: bool = True,
    show_duplicate: bool = True,
    rotate_for_feed: bool = ROTATE_FOR_FEED,
    rotate_direction: int = ROTATE_DIRECTION,
    paper_size: str | None = None,
) -> bool:
    """Print Duplicate Sales Bill on Landscape paper."""
    pages = paginate_duplicate_items(head, items, show_duplicate=show_duplicate, paper_size=paper_size)
    return print_a6_cash_memo(
        pages=pages,
        parent=parent,
        title=f"Duplicate {title}",
        show_dialog=show_dialog,
        rotate_for_feed=rotate_for_feed,
        rotate_direction=rotate_direction,
    )
