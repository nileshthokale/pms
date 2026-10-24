"""A6 Landscape (148 x 105 mm) Cash Memo Crystal Report Engine (Canon LBP2900).

Shared configuration and rendering engine for:
1. Duplicate Sales Bill (reports/DuplicateSalesBill_A6.rpt)
2. Real Counter Sale Bill (reports/CounterSaleBill_A6.rpt)

Features:
- Paper: A6 landscape (148 x 105 mm) explicitly.
- Margins: safe clearance from all edges, OriginAtMargins = False (setFullPage(True)).
- Typography: Arial ONLY. ALL text is BOLD (labels, values, numbers, headings).
  Shop name: 11 pt, Address: 7 pt, Everything else: 8 pt.
- Hairline rules: 0.25 pt cosmetic solid lines (QPen width 0, NearestNeighbor rendering).
- Item Area: Exactly 10 fixed rows of 4.0 mm (ITEM_ROWS = 10, 40 mm total).
  - BATCH: 28 mm, font 8 pt bold with shrink-to-fit down to 6 pt. Never cut, never '...'.
  - DESCRIPTION: Cut at column width without dots, single line.
- Footer: Pinned at bottom, never shifts.
  - Left: E & O E. Subject to AHMEDNAGAR Jurisdiction, licence wrapped on 2 lines, GSTIN.
  - Right: Net Amt as whole number (e.g. 890) on last page only ('Continued...' before).
  - Suppress all internal debug text (no Category sales or header ID).
  - Footer watermark: 'RPT v2' (5 pt grey text for duplicate report).
- Canon LBP2900 feed rotation:
  - ROTATE_FOR_FEED = True (rotates 90 degrees for short-edge feed).
  - ROTATE_DIRECTION = 90 (configurable to 270 if paper feed orientation requires).
  - OFFSET_X_MM = 0.0, OFFSET_Y_MM = 0.0 (nudge offsets).
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

# ── Geometry Constants ────────────────────────────────────────────────
ITEM_ROWS: int = 10           # Fixed number of item rows per page
ITEM_LINES: int = ITEM_ROWS   # Backward compatibility alias
ROW_HEIGHT_MM: float = 4.0    # Fixed height per item row (mm)

PAGE_WIDTH_MM: float = 148.0
PAGE_HEIGHT_MM: float = 105.0

MARGIN_LEFT_MM: float = 4.0
MARGIN_RIGHT_MM: float = 4.0
MARGIN_TOP_MM: float = 5.0
MARGIN_BOTTOM_MM: float = 5.0

CONTENT_WIDTH_MM: float = 140.0   # 148 - 8 = 140.0 mm
CONTENT_HEIGHT_MM: float = 95.0  # 105 - 10 = 95.0 mm

# Exact Vertical Budget Coordinates (mm)
HEADER_Y_START_MM: float = 5.0
HEADER_HEIGHT_MM: float = 24.0
HEADER_Y_END_MM: float = 29.0       # 5.0 + 24.0

SPACING_1_MM: float = 2.0
ITEM_START_Y_MM: float = 31.0       # 29.0 + 2.0
ITEM_AREA_HEIGHT_MM: float = 40.0   # 10 rows * 4.0 mm
ITEM_END_Y_MM: float = 71.0         # 31.0 + 40.0

SPACING_2_MM: float = 4.0
FOOTER_START_Y_MM: float = 75.0     # 71.0 + 4.0
FOOTER_HEIGHT_MM: float = 25.0
FOOTER_END_Y_MM: float = 100.0      # 75.0 + 25.0

MM_TO_PT: float = 72.0 / 25.4       # ~2.8346 pt/mm

# ── Canon LBP2900 Printer Settings (Shared Calibration) ───────────────
ROTATE_FOR_FEED: bool = True
ROTATE_DIRECTION: int = 90
OFFSET_X_MM: float = 0.0
OFFSET_Y_MM: float = 0.0

# ── Table Columns (Sum of widths = 140.0 mm) ──────────────────────────
# QTY 8 | UNIT 15 | DESCRIPTION 38 | COMP. 12 | BATCH 28 | EXP. DT 19 | AMT 20
COLUMN_DEFS = [
    ("qty", "QTY", 8.0, "right"),
    ("unit", "UNIT", 15.0, "left"),
    ("description", "DESCRIPTION", 38.0, "left"),
    ("comp", "COMP.", 12.0, "left"),
    ("batch", "BATCH", 28.0, "left"),
    ("expiry", "EXP. DT", 19.0, "left"),
    ("amount", "AMT", 20.0, "right"),
]


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
            "licence": str(prof.get("licence") or "20-MH-AHM-61069,21-MH-AHM-61070,20C-MH-AHM-610").strip(),
            "gstin": str(prof.get("gstin") or "").strip(),
        }
    except Exception:
        return {
            "name": "SHREE SAMARTH MEDICAL AND GEN STORE",
            "address": "GHORPADE HOSPITAL, RAHURI",
            "jurisdiction": "AHMEDNAGAR",
            "licence": "20-MH-AHM-61069,21-MH-AHM-61070,20C-MH-AHM-610",
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
) -> list[dict[str, Any]]:
    """Paginate item rows into fixed-size A6 pages with exactly ITEM_ROWS rows each."""
    log_loaded_report_path(report_file)
    total_items = len(items)
    num_pages = max(1, math.ceil(total_items / ITEM_ROWS)) if total_items > 0 else 1
    store = get_store_identity()

    pages: list[dict[str, Any]] = []
    for page_idx in range(num_pages):
        start_idx = page_idx * ITEM_ROWS
        end_idx = min(start_idx + ITEM_ROWS, total_items)
        page_items = items[start_idx:end_idx]

        padded_items = list(page_items)
        while len(padded_items) < ITEM_ROWS:
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
        })
    return pages


def paginate_duplicate_items(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    show_duplicate: bool = True,
) -> list[dict[str, Any]]:
    """Pagination alias for Duplicate Sales Bill with 'RPT v2' watermark."""
    return paginate_items(
        head,
        items,
        show_duplicate=show_duplicate,
        report_file=DUP_RPT_FILE_PATH,
        watermark=REPORT_VERSION_TAG,
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
) -> None:
    """Draw bold Arial text inside specified bounding rect."""
    clean_text = str(text or "").strip()
    if not clean_text:
        return
    font = QFont("Arial", -1)
    font.setPointSizeF(pt_size)
    font.setBold(True)
    painter.setFont(font)

    qt_align = Qt.AlignVCenter
    if align == "right":
        qt_align |= Qt.AlignRight
    elif align == "center":
        qt_align |= Qt.AlignHCenter
    else:
        qt_align |= Qt.AlignLeft

    rect = QRectF(x, y, w, h)
    painter.drawText(rect, qt_align, clean_text)


def _draw_shrink_to_fit_bold(
    painter: QPainter,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    max_pt: float = 8.0,
    min_pt: float = 6.0,
    align: str = "left",
) -> None:
    """Draw bold Arial text with shrink-to-fit down to min_pt.

    NEVER truncates with '...' and NEVER cuts characters.
    """
    clean_text = str(text or "").strip()
    if not clean_text:
        return

    font = QFont("Arial", -1)
    font.setBold(True)

    pt = max_pt
    while pt > min_pt:
        font.setPointSizeF(pt)
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(clean_text) <= w:
            break
        pt -= 0.5
    if pt < min_pt:
        pt = min_pt

    font.setPointSizeF(pt)
    painter.setFont(font)

    qt_align = Qt.AlignVCenter
    if align == "right":
        qt_align |= Qt.AlignRight
    elif align == "center":
        qt_align |= Qt.AlignHCenter
    else:
        qt_align |= Qt.AlignLeft

    rect = QRectF(x, y, w, h)
    painter.drawText(rect, qt_align, clean_text)


def _draw_cut_to_fit_bold(
    painter: QPainter,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    pt_size: float = 8.0,
    align: str = "left",
) -> None:
    """Draw bold Arial text cut to column width without dots, single line."""
    clean_text = str(text or "").strip()
    if not clean_text:
        return

    font = QFont("Arial", -1)
    font.setPointSizeF(pt_size)
    font.setBold(True)
    painter.setFont(font)
    fm = QFontMetricsF(font)

    if fm.horizontalAdvance(clean_text) > w:
        cut_len = len(clean_text)
        while cut_len > 0 and fm.horizontalAdvance(clean_text[:cut_len]) > w:
            cut_len -= 1
        clean_text = clean_text[:cut_len]

    qt_align = Qt.AlignVCenter
    if align == "right":
        qt_align |= Qt.AlignRight
    elif align == "center":
        qt_align |= Qt.AlignHCenter
    else:
        qt_align |= Qt.AlignLeft

    rect = QRectF(x, y, w, h)
    painter.drawText(rect, qt_align, clean_text)


def draw_a6_cash_memo_page(painter: QPainter, page: dict[str, Any], scale: float = 1.0) -> None:
    """Render a single A6 Landscape Cash Memo page with 100% precision.

    Fixed layout:
    - Top: 5.0 mm to 29.0 mm (Header: Store name, address, patient, doctor, memo#, date)
    - Thin Rule 1 (0.25 pt): Y = 24.5 mm
    - Column Headers: Y = 24.9 mm to 28.7 mm
    - Thin Rule 2 (0.25 pt): Y = 29.0 mm
    - Middle: Y = 31.0 mm to 71.0 mm (Exactly 10 item rows x 4.0 mm = 40 mm)
    - Thin Rule 3 (0.25 pt): Y = 71.0 mm
    - Bottom: Y = 75.0 mm to 100.0 mm (Fixed Footer: Jurisdiction, Licences, GSTIN, Net Amt)
    """
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

    x0 = rx(MARGIN_LEFT_MM)
    x1 = rx(MARGIN_LEFT_MM + CONTENT_WIDTH_MM)
    w_content = rw(CONTENT_WIDTH_MM)

    # Cosmetic hairline pen (0.25 pt)
    pen_hairline = QPen(QColor("#000000"), 0, Qt.SolidLine)
    pen_hairline.setCosmetic(True)
    painter.setPen(pen_hairline)

    # ══════════════════════════════════════════════════════════════════
    # 1. HEADER (Fixed at top, Y = 5.0 to 29.0 mm)
    # ══════════════════════════════════════════════════════════════════
    # Line 1: Shop Name (centered, 11 pt bold, from firm master)
    shop_name = store.get("name", "SHREE SAMARTH MEDICAL AND GEN STORE")
    _draw_bold_text(
        painter,
        x=x0,
        y=ry(5.2),
        w=w_content,
        h=rh(4.8),
        text=shop_name,
        pt_size=11.0,
        align="center",
    )

    # Page number at top-right only if multi-page
    if total_pages > 1:
        page_str = f"Page {page_num} of {total_pages}"
        _draw_bold_text(
            painter,
            x=rx(MARGIN_LEFT_MM + CONTENT_WIDTH_MM - 35.0),
            y=ry(5.2),
            w=rw(35.0),
            h=rh(4.0),
            text=page_str,
            pt_size=8.0,
            align="right",
        )

    # Line 2: Shop Address (centered, 7 pt bold, from firm master)
    shop_addr = store.get("address", "GHORPADE HOSPITAL, RAHURI")
    _draw_bold_text(
        painter,
        x=x0,
        y=ry(10.4),
        w=w_content,
        h=rh(3.6),
        text=shop_addr,
        pt_size=7.0,
        align="center",
    )

    # Left & Right Block (8 pt bold)
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

    left_w = rw(CONTENT_WIDTH_MM * 0.58)
    right_w = rw(CONTENT_WIDTH_MM * 0.42)
    right_x = x0 + left_w

    # Meta Row 1 (Y: 14.5 mm)
    _draw_cut_to_fit_bold(painter, x0, ry(14.5), left_w, rh(3.8), name_str, 8.0, "left")
    _draw_cut_to_fit_bold(painter, right_x, ry(14.5), right_w, rh(3.8), memo_str, 8.0, "right")

    # Meta Row 2 (Y: 18.5 mm)
    _draw_cut_to_fit_bold(painter, x0, ry(18.5), left_w, rh(3.8), doc_str, 8.0, "left")
    _draw_cut_to_fit_bold(painter, right_x, ry(18.5), right_w, rh(3.8), dt_str, 8.0, "right")

    # Thin Rule 1 (0.25 pt): Above Column Headings (Y = 24.5 mm)
    painter.setPen(pen_hairline)
    painter.drawLine(QPointF(x0, ry(24.5)), QPointF(x1, ry(24.5)))

    # Column Headings (8 pt bold, Y: 24.9 to 28.7 mm)
    col_x_mm = MARGIN_LEFT_MM
    for key, title, width_mm, align in COLUMN_DEFS:
        cx = rx(col_x_mm)
        cw = rw(width_mm)
        pad = rw(0.6) if align == "left" else 0.0
        r_pad = rw(0.6) if align == "right" else 0.0
        _draw_bold_text(
            painter,
            cx + pad,
            ry(24.9),
            cw - pad - r_pad,
            rh(3.8),
            title,
            8.0,
            align,
        )
        col_x_mm += width_mm

    # Thin Rule 2 (0.25 pt): Below Column Headings (Y = 29.0 mm)
    painter.drawLine(QPointF(x0, ry(29.0)), QPointF(x1, ry(29.0)))

    # ══════════════════════════════════════════════════════════════════
    # 2. MIDDLE - RESERVED ITEM AREA (Exactly ITEM_ROWS = 10 rows)
    # ══════════════════════════════════════════════════════════════════
    # Y = 31.0 mm to 71.0 mm (40.0 mm height, 10 rows x 4.0 mm)
    for r_idx in range(ITEM_ROWS):
        curr_y_mm = ITEM_START_Y_MM + r_idx * ROW_HEIGHT_MM
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

            col_x_mm = MARGIN_LEFT_MM
            for key, title, width_mm, align in COLUMN_DEFS:
                val = row_map.get(key, "")
                cx = rx(col_x_mm)
                cw = rw(width_mm)
                pad = rw(0.6) if align == "left" else 0.0
                r_pad = rw(0.6) if align == "right" else 0.0

                if key == "batch":
                    # BATCH: Shrink-to-fit down to 6 pt, NEVER cut, NEVER '...'
                    _draw_shrink_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        max_pt=8.0,
                        min_pt=6.0,
                        align=align,
                    )
                elif key == "description":
                    # DESCRIPTION: Cut at column width without dots
                    _draw_cut_to_fit_bold(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        pt_size=8.0,
                        align=align,
                    )
                else:
                    _draw_bold_text(
                        painter,
                        cx + pad,
                        ry(curr_y_mm),
                        cw - pad - r_pad,
                        rh(ROW_HEIGHT_MM),
                        val,
                        pt_size=8.0,
                        align=align,
                    )
                col_x_mm += width_mm

    # Thin Rule 3 (0.25 pt): Below Items (Y = 71.0 mm)
    painter.setPen(pen_hairline)
    painter.drawLine(QPointF(x0, ry(ITEM_END_Y_MM)), QPointF(x1, ry(ITEM_END_Y_MM)))

    # ══════════════════════════════════════════════════════════════════
    # 3. FOOTER (Fixed at Bottom, Y = 75.0 to 100.0 mm)
    # ══════════════════════════════════════════════════════════════════
    # Left Block (8 pt bold): Jurisdiction, Licences (wrapped up to 2 lines), GSTIN
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

    foot_left_w = rw(CONTENT_WIDTH_MM * 0.58)

    # Line 1: Jurisdiction
    _draw_bold_text(painter, x0, ry(75.5), foot_left_w, rh(4.0), jur_line, 8.0, "left")

    # Line 2 & 3: Licences (wrapped so never clipped)
    _draw_bold_text(painter, x0, ry(80.0), foot_left_w, rh(4.0), lic_line1, 8.0, "left")
    curr_foot_y_mm = 84.5
    if lic_line2:
        _draw_bold_text(painter, x0, ry(curr_foot_y_mm), foot_left_w, rh(4.0), lic_line2, 8.0, "left")
        curr_foot_y_mm += 4.5

    # Line 4: GSTIN (no debug ID or remarks printed!)
    if gstin_raw:
        _draw_bold_text(painter, x0, ry(curr_foot_y_mm), foot_left_w, rh(4.0), f"GSTIN: {gstin_raw}", 8.0, "left")

    # Right Block (8 pt bold): Net Amt (or Continued...), Shop Name, Pharmacist/Sign
    foot_right_w = rw(CONTENT_WIDTH_MM * 0.42)
    foot_right_x = x0 + foot_left_w

    if is_last:
        net_val = float(head.get("net_amount") or 0.0)
        net_str = f"Net Amt : {int(round(net_val))}"
    else:
        net_str = "Continued..."

    # Row 1: Net Amt / Continued...
    _draw_bold_text(painter, foot_right_x, ry(75.5), foot_right_w, rh(4.8), net_str, 8.0, "right")

    # Row 2: Shop Name
    _draw_bold_text(painter, foot_right_x, ry(83.5), foot_right_w, rh(4.2), shop_name, 8.0, "right")

    # Row 3: Pharmacist/Sign
    _draw_bold_text(painter, foot_right_x, ry(92.5), foot_right_w, rh(4.2), "Pharmacist/Sign", 8.0, "right")

    # Watermark (if present, tiny 5 pt grey text)
    if watermark_text:
        f_watermark = QFont("Arial", -1)
        f_watermark.setPointSizeF(5.0)
        painter.setFont(f_watermark)
        painter.setPen(QColor("#888888"))
        painter.drawText(QRectF(x0, ry(98.5), w_content, rh(3.0)), Qt.AlignRight | Qt.AlignVCenter, watermark_text)


def render_a6_cash_memo_pixmap(page: dict[str, Any], dpi: float = 300.0) -> QPixmap:
    """Render page dict into an A6 Landscape QPixmap at specified DPI (default 300 DPI)."""
    scale = (dpi / 25.4)
    w_px = int(round(PAGE_WIDTH_MM * scale))
    h_px = int(round(PAGE_HEIGHT_MM * scale))

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
    """Generate exact A6 Landscape PDF from pre-paginated pages."""
    from PySide6.QtGui import QPdfWriter

    app = QApplication.instance() or QApplication([])

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    writer = QPdfWriter(output_path)
    layout = QPageLayout(
        QPageSize(QPageSize.A6),
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
) -> str:
    """Generate exact A6 Landscape PDF for Duplicate Sales Bill."""
    pages = paginate_duplicate_items(head, items, show_duplicate=show_duplicate)
    return generate_a6_cash_memo_pdf(pages, output_path)


def print_a6_cash_memo(
    pages: list[dict[str, Any]],
    parent=None,
    title: str = "Cash Memo",
    show_dialog: bool = True,
    rotate_for_feed: bool = ROTATE_FOR_FEED,
    rotate_direction: int = ROTATE_DIRECTION,
) -> bool:
    """Print A6 Landscape Cash Memo using Windows print system (Canon LBP2900).

    Fixes:
    1. OriginAtMargins = False (printer.setFullPage(True)) to eliminate driver margin shift.
    2. Render at 300 DPI, draw at 100% scale with integer pixel mapping (no 'fit to page').
    3. NearestNeighbor rendering (SmoothPixmapTransform = False) so hairline rules stay crisp.
    4. Short-edge feeding rotation (rotate_direction: 90 or 270 degrees).
    """
    try:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    except ImportError as exc:
        raise RuntimeError("Printer support requires PySide6.") from exc

    printer = QPrinter(QPrinter.HighResolution)
    voucher_no = pages[0]["head"].get("voucher_no") or pages[0]["head"].get("bill_no") or "1" if pages else "1"
    printer.setDocName(f"{title} #{voucher_no}")

    # Set paper size explicitly to A6 (105 x 148 mm Portrait feed or A6 Landscape)
    if rotate_for_feed:
        layout = QPageLayout(
            QPageSize(QSizeF(105, 148), QPageSize.Millimeter),
            QPageLayout.Portrait,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Millimeter,
        )
    else:
        layout = QPageLayout(
            QPageSize(QPageSize.A6),
            QPageLayout.Landscape,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Millimeter,
        )
    printer.setPageLayout(layout)

    # Use paper size as origin (OriginAtMargins = False)
    printer.setFullPage(True)

    if show_dialog:
        dlg = QPrintDialog(printer, parent)
        dlg.setWindowTitle(f"Print {title} #{voucher_no} - A6 (148 x 105 mm)")
        if dlg.exec() != QPrintDialog.Accepted:
            return False

    dpi = printer.resolution()
    target_dpi = 300.0

    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("Could not open printer for A6 Landscape Cash Memo.")

    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)

    try:
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

            scale_factor = float(dpi) / target_dpi
            dest_w = rotated_img.width() * scale_factor
            dest_h = rotated_img.height() * scale_factor
            target_rect = QRectF(0.0, 0.0, dest_w, dest_h)

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
) -> bool:
    """Print Duplicate Sales Bill on A6 Landscape."""
    pages = paginate_duplicate_items(head, items, show_duplicate=show_duplicate)
    return print_a6_cash_memo(
        pages=pages,
        parent=parent,
        title=f"Duplicate {title}",
        show_dialog=show_dialog,
        rotate_for_feed=rotate_for_feed,
        rotate_direction=rotate_direction,
    )
