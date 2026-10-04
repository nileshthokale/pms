"""A6 (105 x 148 mm) pharmacy receipt profile for sales and counter-sale bills.

This module owns the ``PHARMACY_A6`` print profile: physical page geometry, the
compact receipt column model, pagination, and two rendering backends that share
one layout so the printed bill and the exported PDF can never disagree.

Geometry is expressed in millimetres and derived from Qt's own
``QPageSize``/``QPageLayout`` so the PDF media box and the Windows print job are
the same page. When Qt is unavailable a standard-library millimetre conversion
is used instead.

Read-only: only stored sales rows are read. Nothing is inserted, updated,
deleted, posted or recalculated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from database.sales_dao import SalesDAO

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
PT_PER_MM = PT_PER_INCH / MM_PER_INCH


class ReceiptPrintError(ValueError):
    """Raised when an A6 receipt cannot be laid out, rendered or printed."""


# ── PHARMACY_A6 profile ───────────────────────────────────────────────

@dataclass(frozen=True)
class PaperProfile:
    """A physical paper definition; all sizes are millimetres."""

    name: str
    width_mm: float
    height_mm: float
    margin_left_mm: float
    margin_right_mm: float
    margin_top_mm: float
    margin_bottom_mm: float
    orientation: str = "Portrait"
    scale_percent: int = 100

    @property
    def width_pt(self) -> float:
        return self.width_mm * PT_PER_MM

    @property
    def height_pt(self) -> float:
        return self.height_mm * PT_PER_MM

    @property
    def content_width_mm(self) -> float:
        return self.width_mm - self.margin_left_mm - self.margin_right_mm

    @property
    def content_height_mm(self) -> float:
        return self.height_mm - self.margin_top_mm - self.margin_bottom_mm

    @property
    def size_label(self) -> str:
        return f"A6 ({self.width_mm:g} \u00d7 {self.height_mm:g} mm)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "width_mm": self.width_mm, "height_mm": self.height_mm,
            "orientation": self.orientation, "scale_percent": self.scale_percent,
            "margins_mm": {
                "left": self.margin_left_mm, "right": self.margin_right_mm,
                "top": self.margin_top_mm, "bottom": self.margin_bottom_mm,
            },
            "size_pt": (round(self.width_pt, 2), round(self.height_pt, 2)),
            "size_label": self.size_label,
        }


# 105 x 148 mm with receipt margins; printed content stays inside these bounds.
PHARMACY_A6 = PaperProfile(
    name="PHARMACY_A6",
    width_mm=105.0,
    height_mm=148.0,
    margin_left_mm=4.0,
    margin_right_mm=4.0,
    margin_top_mm=5.0,
    margin_bottom_mm=5.0,
)

A4_REFERENCE = PaperProfile(
    name="A4", width_mm=210.0, height_mm=297.0,
    margin_left_mm=17.6, margin_right_mm=17.6, margin_top_mm=17.6, margin_bottom_mm=17.6,
)

RECEIPT_PROFILES: dict[str, PaperProfile] = {PHARMACY_A6.name: PHARMACY_A6}

# ── Type ──────────────────────────────────────────────────────────────

TITLE_PT = 9.5
SUBTITLE_PT = 6.6
META_PT = 6.0
COLHEAD_PT = 5.4
BODY_PT = 6.2
BODY_SMALL_PT = 5.7
TOTAL_PT = 6.4
NET_PT = 7.6
FOOTER_PT = 5.6
RULE_PT = 0.5
ROW_PAD_MM = 0.55
LEADING = 1.24

# Helvetica advance widths (AFM units/1000) so wrapping never guesses.
_HELVETICA = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015,
    "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722,
    "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944, "X": 667,
    "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556, "h": 556,
    "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556, "o": 556, "p": 556,
    "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500, "w": 722, "x": 500,
    "y": 500, "z": 500, "{": 334, "|": 260, "}": 334, "~": 584,
    "**": 1000,
}
_HELVETICA.update({str(d): 556 for d in range(10)})
_HELVETICA_BOLD = {
    " ": 278, "!": 333, '"': 474, "#": 556, "$": 556, "%": 889, "&": 722, "'": 238,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    ":": 333, ";": 333, "<": 584, "=": 584, ">": 584, "?": 611, "@": 975,
    "A": 722, "B": 722, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722,
    "I": 278, "J": 556, "K": 722, "L": 611, "M": 833, "N": 722, "O": 778, "P": 667,
    "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944, "X": 667,
    "Y": 667, "Z": 611, "[": 333, "\\": 278, "]": 333, "^": 584, "_": 556, "`": 333,
    "a": 556, "b": 611, "c": 556, "d": 611, "e": 556, "f": 333, "g": 611, "h": 611,
    "i": 278, "j": 278, "k": 556, "l": 278, "m": 889, "n": 611, "o": 611, "p": 611,
    "q": 611, "r": 389, "s": 556, "t": 333, "u": 611, "v": 556, "w": 778, "x": 556,
    "y": 556, "z": 500, "{": 389, "|": 280, "}": 389, "~": 584,
}
_HELVETICA_BOLD.update({str(d): 556 for d in range(10)})

# ── Compact column model, widths in millimetres (sum = content width) ──

@dataclass(frozen=True)
class Column:
    key: str
    heading: str
    width_mm: float
    align: str = "left"
    wrap: bool = False
    max_lines: int = 1

    @property
    def x_mm(self) -> float:
        return PHARMACY_A6.margin_left_mm + sum(c.width_mm for c in COLUMNS[:COLUMNS.index(self)])


COLUMNS: tuple[Column, ...] = (
    Column("qty", "QTY", 8.0, "right"),
    Column("unit", "UNIT", 9.0),
    Column("description", "DESCRIPTION", 27.0, wrap=True, max_lines=2),
    Column("company", "COMP.", 12.0),
    Column("batch", "BATCH", 12.0),
    Column("expiry", "EXP. DT", 12.0),
    Column("amount", "AMT", 17.0, "right"),
)


def columns_width_mm(columns: tuple[Column, ...] = COLUMNS) -> float:
    return sum(column.width_mm for column in columns)


# ── Text measurement and fitting ──────────────────────────────────────

def text_width_mm(text: str, size_pt: float, *, bold: bool = False) -> float:
    """Advance width of ``text`` in millimetres at ``size_pt``."""
    table = _HELVETICA_BOLD if bold else _HELVETICA
    total = sum(table.get(character, 556) for character in str(text))
    return total / 1000.0 * size_pt * 0.352778


def line_height_mm(size_pt: float) -> float:
    return size_pt * 0.352778 * LEADING


ELLIPSIS = "..."


def ellipsize(text: str, size_pt: float, max_mm: float, *, bold: bool = False) -> str:
    """Clip ``text`` with an ASCII ellipsis so it can never overflow its column."""
    text = str(text)
    if text_width_mm(text, size_pt, bold=bold) <= max_mm:
        return text
    for cut in range(len(text) - 1, 0, -1):
        candidate = text[:cut].rstrip() + ELLIPSIS
        if text_width_mm(candidate, size_pt, bold=bold) <= max_mm:
            return candidate
    return ""


def wrap_text(text: str, size_pt: float, max_mm: float, max_lines: int, *, bold: bool = False) -> list[str]:
    """Wrap to at most ``max_lines`` lines, ellipsizing the final line."""
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if text_width_mm(trial, size_pt, bold=bold) <= max_mm:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines and len(" ".join(lines)) < len(str(text).strip()):
        lines[-1] = ellipsize(lines[-1] + " " + ELLIPSIS, size_pt, max_mm, bold=bold)
    return lines


# ── Store profile ─────────────────────────────────────────────────────

def store_profile() -> dict[str, str]:
    """Configured pharmacy identity for the receipt header.

    The schema has no pharmacy/store profile table, so this returns an empty
    mapping today and the receipt header is omitted entirely. It is the single
    extension point: when a store profile exists, return its ``name``,
    ``address``, ``gstin`` and ``pharmacist`` keys here and the A6 bill picks
    them up with no layout change. Business identity is never hard-coded and
    never invented.
    """
    return {}


# ── Layout model ──────────────────────────────────────────────────────

@dataclass
class Run:
    x_mm: float
    y_mm: float
    width_mm: float
    text: str
    size_pt: float
    bold: bool = False
    align: str = "left"


@dataclass
class Block:
    kind: str
    runs: list[Run] = field(default_factory=list)
    height_mm: float = 0.0
    rules: list[tuple[float, float]] = field(default_factory=list)
    top_mm: float = 0.0


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _money(value: Any) -> str:
    try:
        return f"{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return _text(value)


def _qty(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return _text(value)
    return f"{number:g}"


def sale_item_companies(invoice_id: int) -> dict[int, str]:
    """Company (manufacturer) short name per item id for one invoice.

    Read-only query local to printing; ``SalesDAO`` is deliberately untouched.
    """
    from database.connection import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT sii.item_id AS item_id, c.short_name AS short_name, c.company_name AS company_name
            FROM sales_invoice_items sii
            LEFT JOIN items i ON i.id = sii.item_id
            LEFT JOIN companies c ON c.id = i.company_id
            WHERE sii.sales_invoice_id = ?
            """,
            (invoice_id,),
        ).fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    result: dict[int, str] = {}
    for row in rows:
        name = row["short_name"] or row["company_name"] or ""
        if name:
            result[int(row["item_id"])] = _text(name)
    return result


def build_layout(record: dict[str, Any], items: list[dict[str, Any]],
                 companies: dict[int, str] | None = None,
                 profile: PaperProfile = PHARMACY_A6) -> list[Block]:
    """Build the A6 receipt as ordered layout blocks (millimetres, origin top-left).

    Gaps are folded into the height of the block that follows them so that
    pagination accounts for every millimetre of vertical space.
    """
    companies = companies or {}
    content_w = profile.content_width_mm
    x0 = profile.margin_left_mm
    cursor = profile.margin_top_mm
    blocks: list[Block] = []
    pending_gap = 0.0

    def emit(block: Block) -> Block:
        nonlocal pending_gap, cursor
        gap = pending_gap
        top = cursor
        # A pending gap sits above the block's content, so the block occupies
        # [top, top + gap + content]. Runs and rules are converted to offsets
        # from the block top so pagination can re-flow a block onto any page.
        for run in block.runs:
            run.y_mm = run.y_mm - top + gap
        block.rules = [(y - top + gap, thickness) for y, thickness in block.rules]
        block.height_mm += gap
        pending_gap = 0.0
        block.top_mm = top
        blocks.append(block)
        cursor += block.height_mm
        return block

    def line_block(text: str, size: float, *, bold: bool = False, align: str = "left",
                   kind: str = "line") -> Block:
        return Block(kind=kind, runs=[Run(x0, cursor + line_height_mm(size) * 0.78,
                                          content_w, text, size, bold, align)],
                     height_mm=line_height_mm(size))

    profile_data = store_profile()
    title = _text(record.get("document_title") or record.get("title") or "Sales Bill")

    # ── Header ──
    if profile_data.get("name"):
        emit(line_block(_text(profile_data["name"]), TITLE_PT, bold=True, align="center", kind="header"))
        if profile_data.get("address"):
            emit(line_block(_text(profile_data["address"]), SUBTITLE_PT, align="center", kind="header"))
    emit(line_block(title, TITLE_PT if not profile_data.get("name") else SUBTITLE_PT,
                    bold=True, align="center", kind="header"))

    bill_no = _text(record.get("bill_no"))
    left_bits = [f"Bill No: {bill_no}" if bill_no else "Bill No:"]
    date = _text(record.get("sale_date"))
    time = _text(record.get("sale_time"))
    right_bits = [f"Date: {date}" if date else "Date:"]
    if time:
        right_bits.append(f"Time: {time}")
    meta = Block(kind="header", height_mm=line_height_mm(META_PT) * 2.1)
    meta.rules.append((cursor + line_height_mm(META_PT) * 1.35, 0.4))
    for index, text in enumerate((("  ".join(left_bits), "  ".join(right_bits)))):
        meta.runs.append(Run(x0, cursor + line_height_mm(META_PT) * 0.78
                             + index * line_height_mm(META_PT),
                             content_w * 0.5, text, META_PT, False,
                             "left" if index == 0 else "right"))
    emit(meta)

    party_bits = []
    if record.get("patient_name"):
        party_bits.append(f"Patient: {_text(record['patient_name'])}")
    if record.get("customer_name"):
        party_bits.append(f"Customer: {_text(record['customer_name'])}")
    if record.get("doctor_name"):
        party_bits.append(f"Doctor: {_text(record['doctor_name'])}")
    if party_bits:
        pending_gap = 0.6
        emit(line_block("   ".join(party_bits), META_PT, kind="header"))

    # ── Item table ──
    pending_gap = 1.0
    colhead = Block(kind="colhead", height_mm=line_height_mm(COLHEAD_PT) * 1.55)
    for column in COLUMNS:
        colhead.runs.append(Run(column.x_mm, cursor + line_height_mm(COLHEAD_PT) * 0.8,
                                column.width_mm, column.heading, COLHEAD_PT, True, column.align))
    colhead.rules.append((cursor + line_height_mm(COLHEAD_PT) * 1.3, 0.4))
    colhead.repeat = True  # type: ignore[attr-defined]
    emit(colhead)

    if not items:
        pending_gap = 0.3
        emit(line_block("No items on this bill.", BODY_PT, align="center", kind="row"))

    for item in items:
        company = companies.get(int(item.get("item_id") or 0), "")
        values = {
            "qty": _qty(item.get("sale_qty")),
            "unit": _text(item.get("pack_size")),
            "description": _text(item.get("item_name")),
            "company": company,
            "batch": _text(item.get("batch_no")),
            "expiry": _text(item.get("expiry")),
            "amount": _money(item.get("amount")),
        }
        prepared: dict[str, list[str]] = {}
        row_lines = 1
        for column in COLUMNS:
            raw = values[column.key]
            if column.wrap:
                prepared[column.key] = wrap_text(raw, BODY_PT, column.width_mm, column.max_lines)
                row_lines = max(row_lines, len(prepared[column.key]))
            else:
                prepared[column.key] = [ellipsize(raw, BODY_PT, column.width_mm)]
        row = Block(kind="row", height_mm=row_lines * line_height_mm(BODY_PT) + ROW_PAD_MM)
        for column in COLUMNS:
            for line_index, line in enumerate(prepared[column.key][:row_lines]):
                size = BODY_PT if line_index == 0 else BODY_SMALL_PT
                row.runs.append(Run(column.x_mm,
                                    cursor + line_index * line_height_mm(BODY_PT)
                                    + line_height_mm(size) * 0.78 + ROW_PAD_MM / 2,
                                    column.width_mm, line, size, False, column.align))
        pending_gap = 0.15
        emit(row)

    # ── Totals (held back to the final page) ──
    pending_gap = 1.0

    def total_row(label: str, value: str, *, bold: bool = False, size: float = TOTAL_PT) -> None:
        nonlocal cursor
        height = line_height_mm(size) * 1.15
        block = Block(kind="totals", height_mm=height)
        block.runs.append(Run(x0, cursor + line_height_mm(size) * 0.8,
                              content_w * 0.6, label, size, bold, "left"))
        block.runs.append(Run(x0 + content_w * 0.6, cursor + line_height_mm(size) * 0.8,
                              content_w * 0.4, value, size, bold, "right"))
        emit(block)

    total_row("Total Items", str(len(items)))
    total_row("Total Amount", _money(record.get("total_amount")))
    total_row("Bill Discount", _money(record.get("discount")))
    total_row("Round Off", _money(record.get("round_off")))
    total_row("Paid Amount", _money(record.get("paid_amount")))

    net = Block(kind="totals", height_mm=line_height_mm(NET_PT) * 1.7,
                rules=[(cursor, 0.4), (cursor + line_height_mm(NET_PT) * 1.7 - 0.4, 0.4)])
    net.runs.append(Run(x0, cursor + line_height_mm(NET_PT) * 1.0,
                        content_w * 0.6, "Net Amt", NET_PT, True, "left"))
    net.runs.append(Run(x0 + content_w * 0.6, cursor + line_height_mm(NET_PT) * 1.0,
                        content_w * 0.4, _money(record.get("net_amount")), NET_PT, True, "right"))
    emit(net)

    # ── Footer (held back to the final page) ──
    pending_gap = 1.0
    remarks = _text(record.get("remarks"))
    if remarks:
        for remark_line in wrap_text(remarks, FOOTER_PT, content_w, 2):
            pending_gap = 0.0
            emit(line_block(remark_line, FOOTER_PT, align="center", kind="footer"))
    if profile_data.get("gstin"):
        pending_gap = 0.3
        emit(line_block(f"GSTIN: {_text(profile_data['gstin'])}", FOOTER_PT, align="center", kind="footer"))
    pending_gap = 0.5
    emit(line_block("E & O.E.", FOOTER_PT, align="center", kind="footer"))
    if profile_data.get("pharmacist"):
        pending_gap = 0.3
        emit(line_block(f"Pharmacist: {_text(profile_data['pharmacist'])}", FOOTER_PT,
                        align="center", kind="footer"))
    pending_gap = 0.3
    emit(line_block("Printed from stored application data.", FOOTER_PT, align="center", kind="footer"))
    return blocks


def reflow(blocks: list[Block], start_y_mm: float) -> list[Block]:
    """Place blocks sequentially from ``start_y_mm`` and return absolute positions.

    Blocks store positions relative to their own top, so this re-flows a page
    without mutating the shared header/tail blocks used on other pages.
    """
    cursor = start_y_mm
    placed: list[Block] = []
    for block in blocks:
        shift = start_y_mm
        moved = Block(kind=block.kind, height_mm=block.height_mm,
                      top_mm=cursor,
                      runs=[Run(run.x_mm, run.y_mm + shift, run.width_mm, run.text,
                                run.size_pt, run.bold, run.align) for run in block.runs],
                      rules=[(y + shift, thickness) for y, thickness in block.rules])
        if getattr(block, "repeat", False):
            moved.repeat = True  # type: ignore[attr-defined]
        placed.append(moved)
        cursor += block.height_mm
    return placed


def paginate(blocks: list[Block], profile: PaperProfile = PHARMACY_A6) -> list[list[Block]]:
    """Split blocks into A6 pages, repeating the item-table header.

    Page one carries the document header, every later page repeats the column
    heading, and totals plus footer are held back to the final page.
    """
    head = [block for block in blocks if block.kind in {"header", "rule", "colhead"}]
    repeating = [block for block in blocks if getattr(block, "repeat", False)]
    tail = [block for block in blocks if block.kind in {"totals", "footer"}]
    body = [block for block in blocks
            if block.kind not in {"header", "rule", "colhead", "totals", "footer"}]

    limit = profile.content_height_mm
    tail_height = sum(block.height_mm for block in tail)
    repeating_height = sum(block.height_mm for item in repeating for block in [item])

    def group_blocks(reserve_tail: float) -> list[list[Block]]:
        groups: list[list[Block]] = []
        current: list[Block] = []
        used = 0.0
        for block in body:
            prefix_height = 0.0 if not groups and not current else repeating_height
            available = limit - used - prefix_height - reserve_tail
            if current and block.height_mm > available:
                groups.append(current)
                current = []
                used = 0.0
                available = limit - repeating_height - reserve_tail
            current.append(block)
            used += block.height_mm
        groups.append(current)
        return groups

    # Only reserve room for totals/footer on the last page when the last page
    # needs it, so short bills are not pushed onto an extra sheet needlessly.
    groups = group_blocks(0.0)
    last_used = sum(block.height_mm for block in groups[-1])
    last_prefix = 0.0 if len(groups) == 1 else repeating_height
    if last_used + last_prefix + tail_height > limit:
        groups = group_blocks(tail_height)

    pages: list[list[Block]] = []
    for index, group in enumerate(groups):
        prefix = head if index == 0 else repeating
        body_blocks = reflow(group, profile.margin_top_mm + sum(
            block.height_mm for block in prefix))
        pages.append(reflow(prefix, profile.margin_top_mm) + body_blocks)
    tail_start = pages[-1][-1].top_mm + pages[-1][-1].height_mm if pages[-1] else profile.margin_top_mm
    pages[-1] = pages[-1] + reflow(tail, tail_start)
    return pages


# ── Qt page geometry ──────────────────────────────────────────────────

def qt_page_size(profile: PaperProfile = PHARMACY_A6):
    """``QPageSize`` for the profile, or ``None`` when Qt is unavailable."""
    try:
        from PySide6.QtCore import QSizeF
        from PySide6.QtGui import QPageSize
    except ImportError:
        return None
    return QPageSize(
        QSizeF(profile.width_mm, profile.height_mm),
        QPageSize.Millimeter, profile.name, QPageSize.ExactMatch,
    )


def qt_page_layout(profile: PaperProfile = PHARMACY_A6):
    """``QPageLayout`` (portrait, receipt margins) or ``None``."""
    try:
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout
    except ImportError:
        return None
    page_size = qt_page_size(profile)
    if page_size is None:
        return None
    return QPageLayout(
        page_size, QPageLayout.Portrait,
        QMarginsF(profile.margin_left_mm, profile.margin_top_mm,
                  profile.margin_right_mm, profile.margin_bottom_mm),
        QPageLayout.Millimeter,
    )


def page_size_pt(profile: PaperProfile = PHARMACY_A6) -> tuple[float, float]:
    """Exact page size in points (105 mm -> 297.638 pt).

    Computed from the profile rather than ``QPageSize.size(Point)`` because Qt
    rounds a page size to whole points (297 x 420 pt = 104.77 x 148.17 mm),
    which is not the A6 the profile declares. The printer still receives an
    exact-match ``QPageSize``; only the PDF media box and the painter scaling
    use these values, and both stay within a rounding error of 105 x 148 mm.
    """
    return profile.width_pt, profile.height_pt


def qt_page_size_pt(profile: PaperProfile = PHARMACY_A6) -> tuple[float, float] | None:
    """Page size as Qt reports it in points, or ``None`` without Qt."""
    page_size = qt_page_size(profile)
    if page_size is None:
        return None
    from PySide6.QtGui import QPageSize as _Size

    size = page_size.size(_Size.Point)
    return float(size.width()), float(size.height())


# ── PDF backend ───────────────────────────────────────────────────────

def _pdf_escape(value: Any) -> str:
    return (_text(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))


def _pdf_escape_bytes(value: Any) -> bytes:
    return _pdf_escape(value).encode("latin-1", "replace")


def _run_x_pt(run: Run) -> float:
    if run.align == "right":
        return run.x_mm + run.width_mm - text_width_mm(run.text, run.size_pt, bold=run.bold)
    if run.align == "center":
        return run.x_mm + (run.width_mm - text_width_mm(run.text, run.size_pt, bold=run.bold)) / 2.0
    return run.x_mm


def pages_to_pdf_bytes(pages: list[list[Block]], profile: PaperProfile = PHARMACY_A6) -> bytes:
    """Render paginated A6 blocks to a PDF 1.4 file with an exact A6 media box."""
    width_pt, height_pt = page_size_pt(profile)
    mm_to_pt = PT_PER_MM
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    page_ids: list[int] = []
    for page_index, page_blocks in enumerate(pages, 1):
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        commands: list[bytes] = []
        for block in page_blocks:
            for y_mm, thickness in block.rules:
                y_pt = height_pt - y_mm * mm_to_pt
                commands.append(
                    f"{profile.margin_left_mm * mm_to_pt:.2f} {y_pt:.2f} m "
                    f"{profile.content_width_mm * mm_to_pt:.2f} {thickness:.2f} l S".encode()
                )
        for block in page_blocks:
            for run in block.runs:
                if not run.text:
                    continue
                font = "/F2" if run.bold else "/F1"
                x_pt = _run_x_pt(run) * mm_to_pt
                y_pt = height_pt - run.y_mm * mm_to_pt
                commands.append(
                    f"BT {font} {run.size_pt:.2f} Tf 1 0 0 1 {x_pt:.2f} {y_pt:.2f} Tm "
                    f"({_pdf_escape(run.text).encode('latin-1', 'replace').decode('latin-1')}) Tj ET".encode()
                )
        stamp = f"Page {page_index} of {len(pages)}"
        commands.append(
            f"BT /F1 {FOOTER_PT:.2f} Tf 1 0 0 1 {profile.margin_left_mm * mm_to_pt:.2f} "
            f"{height_pt - (profile.height_mm - 2.2) * mm_to_pt:.2f} Tm "
            f"({_pdf_escape(stamp).encode('latin-1', 'replace').decode('latin-1')}) Tj ET".encode()
        )
        stream = b"\n".join(commands)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width_pt:.2f} {height_pt:.2f}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


# ── Stored data ───────────────────────────────────────────────────────

def load_sale(invoice_id: int, title: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    record = SalesDAO.get_by_id(invoice_id)
    if not record:
        raise ReceiptPrintError("Sales bill was not found or has been deleted.")
    items = SalesDAO.get_invoice_items(invoice_id)
    record = dict(record)
    record["document_title"] = title
    return record, items


def build_sale_pages(invoice_id: int, title: str = "Sales Bill",
                     profile: PaperProfile = PHARMACY_A6) -> tuple[list[list[Block]], dict]:
    record, items = load_sale(invoice_id, title)
    companies = sale_item_companies(invoice_id)
    pages = paginate(build_layout(record, items, companies, profile), profile)
    return pages, record


def pages_to_preview_text(pages: list[list[Block]]) -> str:
    """Plain-text rendering of the A6 layout, for preview and tests."""
    lines: list[str] = []
    for page_number, page_blocks in enumerate(pages, 1):
        if page_number > 1:
            lines.append(f"--- Page {page_number} ---")
        for block in page_blocks:
            row: dict[float, list[tuple[float, Run]]] = {}
            for run in block.runs:
                row.setdefault(round(run.y_mm, 2), []).append((run.x_mm, run))
            for y in sorted(row):
                parts = []
                for x, run in sorted(row[y]):
                    offset = max(0, int(round((x - PHARMACY_A6.margin_left_mm) / 1.6)))
                    parts.append(" " * offset + run.text)
                lines.append("".join(parts).rstrip())
            if block.rules:
                lines.append("-" * 46)
    return "\n".join(lines)


def generate_pharmacy_a6_bill(invoice_id: int, output_path: str | os.PathLike[str],
                              title: str = "Sales Bill",
                              profile: PaperProfile = PHARMACY_A6) -> str:
    """Write a sales/counter-sale receipt PDF on true A6 paper."""
    from pathlib import Path

    pages, _record = build_sale_pages(invoice_id, title, profile)
    path = Path(output_path)
    if path.suffix.casefold() != ".pdf":
        path = path.with_suffix(".pdf")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pages_to_pdf_bytes(pages, profile))
    except OSError as exc:
        raise ReceiptPrintError(f"Could not create PDF at {path}: {exc}") from exc
    return str(path)


def preview_pharmacy_a6_bill(invoice_id: int, title: str = "Sales Bill") -> str:
    pages, _record = build_sale_pages(invoice_id, title)
    return pages_to_preview_text(pages)


# ── Printer discovery and printing ────────────────────────────────────

def available_printers() -> list[str]:
    """Installed Windows printers; empty when Qt printing is unavailable."""
    try:
        from PySide6.QtPrintSupport import QPrinterInfo
    except ImportError:
        return []
    try:
        return [str(name) for name in QPrinterInfo.availablePrinterNames()]
    except Exception:
        return []


def default_printer_name() -> str:
    """The Windows default printer, never hard-coded."""
    try:
        from PySide6.QtPrintSupport import QPrinterInfo
    except ImportError:
        return ""
    try:
        return str(QPrinterInfo.defaultPrinterName() or "")
    except Exception:
        return ""


def supported_page_size_mm(printer_name: str) -> list[tuple[float, float]]:
    """Paper sizes a printer reports, in millimetres."""
    try:
        from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
    except ImportError:
        return []
    try:
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPrinterName(printer_name)
        info = QPrinterInfo(printer)
        sizes: list[tuple[float, float]] = []
        for size in info.supportedPageSizes():
            millimetres = size.size(size.Millimeter)
            sizes.append((round(float(millimetres.width()), 1), round(float(millimetres.height()), 1)))
        return sizes
    except Exception:
        return []


def draw_pages_on_painter(painter, pages: list[list[Block]], rect,
                          profile: PaperProfile = PHARMACY_A6, device=None) -> None:
    """Paint the A6 layout into ``rect`` (device units), letterboxed to fit.

    The receipt is scaled uniformly to the smaller axis and centred, so content
    can never land outside the device's printable area even when a driver forces
    a different paper size. In Qt 6 page breaks belong to the paged device
    (``QPdfWriter``/``QPrinter``), not the painter.
    """
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QFont

    paged = device if device is not None else painter.device()
    width_pt, height_pt = page_size_pt(profile)
    target_w = rect.width()
    target_h = rect.height()
    scale = min(target_w / width_pt, target_h / height_pt)
    origin_x = rect.x() + (target_w - width_pt * scale) / 2.0
    origin_y = rect.y() + (target_h - height_pt * scale) / 2.0

    for page_number, page_blocks in enumerate(pages, 1):
        if page_number > 1:
            advance = getattr(paged, "newPage", None)
            if advance is not None and not advance():
                break
        for block in page_blocks:
            for y_mm, thickness in block.rules:
                painter.fillRect(
                    QRectF(origin_x + profile.margin_left_mm * PT_PER_MM * scale,
                           origin_y + y_mm * PT_PER_MM * scale,
                           profile.content_width_mm * PT_PER_MM * scale,
                           max(0.5, thickness * PT_PER_MM * scale)),
                    painter.pen().color(),
                )
        for block in page_blocks:
            for run in block.runs:
                if not run.text:
                    continue
                font = QFont("Helvetica", run.size_pt)
                font.setBold(run.bold)
                painter.setFont(font)
                painter.drawText(
                    origin_x + _run_x_pt(run) * PT_PER_MM * scale,
                    origin_y + run.y_mm * PT_PER_MM * scale,
                    run.text,
                )


def print_pharmacy_a6_bill(invoice_id: int, parent=None, title: str = "Sales Bill",
                            profile: PaperProfile = PHARMACY_A6,
                            show_dialog: bool = True) -> bool:
    """Print a sales/counter-sale receipt on A6 through the Windows print system.

    The Windows default printer is used unless the user picks another one in the
    standard print dialog. Printer names are never hard-coded.
    """
    try:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    except ImportError as exc:
        raise ReceiptPrintError("Printer support requires PySide6; use Save PDF instead.") from exc

    pages, _record = build_sale_pages(invoice_id, title, profile)
    printer = QPrinter(QPrinter.HighResolution)
    layout = qt_page_layout(profile)
    if layout is not None:
        printer.setPageLayout(layout)
    if show_dialog:
        dialog = QPrintDialog(printer, parent)
        dialog.setWindowTitle(f"Print {title} - {profile.size_label}")
        if dialog.exec() != QPrintDialog.Accepted:
            return False
    painter = None
    try:
        from PySide6.QtGui import QPainter

        painter = QPainter()
        if not painter.begin(printer):
            raise ReceiptPrintError("Could not start the print job.")
        painter.setRenderHint(QPainter.Antialiasing, True)
        draw_pages_on_painter(painter, pages, painter.viewport(), profile)
    except ReceiptPrintError:
        raise
    except Exception as exc:
        raise ReceiptPrintError(f"Printing failed: {exc}") from exc
    finally:
        if painter is not None and painter.isActive():
            painter.end()
    return True


__all__ = [
    "ReceiptPrintError", "PaperProfile", "PHARMACY_A6", "A4_REFERENCE", "RECEIPT_PROFILES",
    "Column", "COLUMNS", "columns_width_mm", "Run", "Block",
    "text_width_mm", "line_height_mm", "ellipsize", "wrap_text", "store_profile",
    "build_layout", "paginate", "load_sale", "sale_item_companies",
    "qt_page_size", "qt_page_layout", "page_size_pt",
    "pages_to_pdf_bytes", "pages_to_preview_text", "build_sale_pages",
    "generate_pharmacy_a6_bill", "preview_pharmacy_a6_bill",
    "available_printers", "default_printer_name", "supported_page_size_mm",
    "draw_pages_on_painter", "print_pharmacy_a6_bill",
    "MM_PER_INCH", "PT_PER_INCH", "PT_PER_MM",
]