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
# Shortest receipt page worth printing; below this the paper would be mostly
# margin. A one-item bill is sized to its own content, never to a fixed sheet.
MIN_RECEIPT_HEIGHT_MM = 45.0

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
    Column("unit", "UNIT", 11.5),
    Column("description", "DESCRIPTION", 27.5, wrap=True, max_lines=2),
    Column("company", "COMP.", 12.0),
    Column("batch", "BATCH", 12.5),
    Column("expiry", "EXP. DT", 12.5),
    Column("qty", "QTY", 8.0, "right"),
    Column("amount", "AMT", 13.0, "right"),
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
    """Configured pharmacy identity for the receipt header and footer.

    The schema has no store/pharmacy-profile table, so the identity for this
    counter is declared here: the shop name prints big and bold, and the
    location line under it prints small.

    It is the single extension point: return ``name``, ``address``,
    ``jurisdiction``, ``gstin`` and ``pharmacist`` here once the application
    stores that identity, and the cash-memo layout picks all of it up with no
    layout change. Keys that are omitted are left out rather than invented.
    """
    return {
        "name": "SHREE SAMARTH MEDICAL AND GEN STORE",
        "address": "GHORPADE HOSPITAL ,RAHURI",
        "jurisdiction": "AHMEDNAGAR",
        "licence": "20-MH-AHM-61069,21-MH-AHM-61070,20C-MH-AHM-610",
    }


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


def _expiry(value: Any) -> str:
    """Stored expiry as DD/MM/YYYY when the stored value carries a day.

    Only re-formats what is already stored: ``YYYY-MM-DD`` becomes
    ``DD/MM/YYYY`` and ``DD/MM/YYYY`` is passed through. A month/year value
    such as ``12/27`` has no day, so the year is simply expanded to
    ``12/2027`` rather than inventing a day of the month.
    """
    import re

    text = _text(value).strip()
    if not text:
        return ""
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return f"{iso.group(3)}/{iso.group(2)}/{iso.group(1)}"
    month_year = re.fullmatch(r"(\d{1,2})/(\d{2,4})", text)
    if month_year:
        year = int(month_year.group(2))
        if year < 100:
            year += 2000
        return f"{int(month_year.group(1)):02d}/{year}"
    return text


def sale_item_units(invoice_id: int) -> dict[int, str]:
    """Unit name per item id for one invoice.

    Read-only query local to printing, exactly like ``sale_item_companies``;
    ``SalesDAO`` is deliberately untouched.
    """
    from database.connection import get_connection

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT sii.item_id AS item_id, u.unit_name AS unit_name
            FROM sales_invoice_items sii
            LEFT JOIN items i ON i.id = sii.item_id
            LEFT JOIN units u ON u.id = i.unit_id
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
        name = row["unit_name"] or ""
        if name:
            result[int(row["item_id"])] = _text(name)
    return result


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
                 units: dict[int, str] | None = None,
                 profile: PaperProfile = PHARMACY_A6) -> list[Block]:
    """Build the A6 receipt as ordered layout blocks (millimetres, origin top-left).

    Gaps are folded into the height of the block that follows them so that
    pagination accounts for every millimetre of vertical space.
    """
    companies = companies or {}
    units = units or {}
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

    # ── Header: pharmacy name + address, exactly as stored ──
    # Nothing is invented: when no store profile is configured the receipt
    # simply has no name/address line and falls back to the document title.
    if profile_data.get("name"):
        for name_line in wrap_text(_text(profile_data["name"]), TITLE_PT,
                                   content_w, 2, bold=True):
            emit(line_block(name_line, TITLE_PT, bold=True, align="center", kind="header"))
        if profile_data.get("address"):
            for address_line in wrap_text(_text(profile_data["address"]),
                                          SUBTITLE_PT, content_w, 2):
                emit(line_block(address_line, SUBTITLE_PT, align="center", kind="header"))
    emit(line_block(title, TITLE_PT if not profile_data.get("name") else SUBTITLE_PT,
                    bold=True, align="center", kind="header"))

    # ── Customer block: Name / Doctor on the left, Cash Memo / Date on the right ──
    customer = _text(record.get("patient_name")) or _text(record.get("customer_name"))
    doctor = _text(record.get("doctor_name"))
    memo = _text(record.get("bill_no"))
    sale_date = _text(record.get("sale_date"))

    # Two independent columns with a gutter between them, so a long name can
    # wrap inside its own column instead of running over the memo and date.
    line_h = line_height_mm(META_PT)
    left_x, left_w = x0, content_w * 0.50
    right_x, right_w = x0 + content_w * 0.52, content_w * 0.48

    left_lines: list[str] = []
    for label, value in (("Name", customer), ("Doctor", doctor)):
        if value:
            left_lines.extend(wrap_text(f"{label} : {value}", META_PT, left_w, 2))
    right_lines: list[str] = []
    for label, value in (("Cash Memo", memo), ("Date", sale_date)):
        if value:
            right_lines.append(ellipsize(f"{label} : {value}", META_PT, right_w))

    rows = max(len(left_lines), len(right_lines))
    pending_gap = 0.8
    party = Block(kind="header", height_mm=line_h * rows + line_h * 0.3)
    party.rules.append((cursor + party.height_mm - line_h * 0.15, 0.4))
    for index, line_text in enumerate(left_lines):
        party.runs.append(Run(left_x, cursor + line_h * 0.78 + index * line_h,
                              left_w, line_text, META_PT, False, "left"))
    for index, line_text in enumerate(right_lines):
        party.runs.append(Run(right_x, cursor + line_h * 0.78 + index * line_h,
                              right_w, line_text, META_PT, False, "right"))
    emit(party)

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
        item_id = int(item.get("item_id") or 0)
        values = {
            "qty": _qty(item.get("sale_qty")),
            "unit": units.get(item_id, ""),
            "description": _text(item.get("item_name")),
            "company": companies.get(item_id, ""),
            "batch": _text(item.get("batch_no")),
            "expiry": _expiry(item.get("expiry")),
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
    net_label = "Net Amt :"
    net = Block(kind="totals", height_mm=line_height_mm(NET_PT) * 1.7,
                rules=[(cursor, 0.4), (cursor + line_height_mm(NET_PT) * 1.7 - 0.4, 0.4)])
    net.runs.append(Run(x0, cursor + line_height_mm(NET_PT) * 1.0,
                        content_w * 0.6, net_label, NET_PT, True, "left"))
    net.runs.append(Run(x0 + content_w * 0.6, cursor + line_height_mm(NET_PT) * 1.0,
                        content_w * 0.4, _money(record.get("net_amount")), NET_PT, True, "right"))
    emit(net)

    # ── Footer (held back to the final page) ──
    # ── Footer (held back to the final page) ──
    pending_gap = 1.0
    remarks = _text(record.get("remarks"))
    if remarks:
        for remark_line in wrap_text(remarks, FOOTER_PT, content_w, 2):
            pending_gap = 0.0
            emit(line_block(remark_line, FOOTER_PT, align="left", kind="footer"))

    # Footer in two columns: "E & O E." and the licence numbers on the left,
    # the shop name and the sign-off line on the right.
    #
    # The rows are stacked rather than paired because the licence line
    # (51.7mm) and the shop name (43.8mm) need 95.5mm of the 97mm content
    # width, so pairing them on one row would leave a 0.01mm gutter and clip
    # one of them. Stacked, each line is measured against its own column and
    # keeps real clearance.
    line_h = line_height_mm(FOOTER_PT)
    gutter = 1.5

    # "E & O E." on the left; a configured jurisdiction is appended rather
    # than hard-coded, so no place name is invented.
    errors_line = "E & O E."
    if profile_data.get("jurisdiction"):
        errors_line = f"E & O E. Subject to {_text(profile_data['jurisdiction'])} Jurisdiction"

    # A row is (left text, right text, right bold).
    foot_rows: list[tuple[str, str, bool]] = [
        (errors_line, _text(profile_data.get("name")), True),
    ]
    # Drug licence numbers print only when one is actually configured.
    licence = _text(profile_data.get("licence"))
    if licence:
        foot_rows.append((licence, "", False))
    # GSTIN prints only when one is actually configured; a blank or invented
    # tax id is never shown.
    if profile_data.get("gstin"):
        foot_rows.append((f"GSTIN: {_text(profile_data['gstin'])}", "", False))
    foot_rows.append(("", "Pharmacist/Sign", False))

    # Size the right column to its own widest line, anchored to the right edge,
    # instead of splitting the width by a fixed ratio: the licence line needs
    # 51.7mm and the bold shop name 43.8mm of the 97mm content width, so any
    # fixed ratio either clips one of them or wastes the gutter.
    right_needed = max(
        (text_width_mm(text, FOOTER_PT, bold=bold)
         for _left, text, bold in foot_rows if text),
        default=0.0)
    right_w = min(content_w * 0.55, right_needed + 1.0)
    right_x = x0 + content_w - right_w
    # A row sharing its line with the right column gets only what is left of
    # the width; a row on its own (the licence numbers, GSTIN) uses the full
    # width instead of being squeezed for no reason.
    paired_left_w = max(0.0, right_x - gutter - x0)

    pending_gap = 0.0
    footer = Block(kind="footer", height_mm=line_h * len(foot_rows) + line_h * 0.3)
    for index, (left_text, right_text, right_bold) in enumerate(foot_rows):
        row_y = cursor + line_h * 0.78 + index * line_h
        if left_text:
            left_w = paired_left_w if right_text else content_w
            footer.runs.append(Run(x0, row_y, left_w,
                                   ellipsize(left_text, FOOTER_PT, left_w),
                                   FOOTER_PT, False, "left"))
        if right_text:
            footer.runs.append(Run(right_x, row_y, right_w,
                                   ellipsize(right_text, FOOTER_PT, right_w,
                                             bold=right_bold),
                                   FOOTER_PT, right_bold, "right"))
    emit(footer)
    return blocks


def reflow(blocks: list[Block], start_y_mm: float) -> list[Block]:
    """Place blocks sequentially from ``start_y_mm`` and return absolute positions.

    Blocks store run and rule positions relative to their own top, so each block
    must be shifted by ITS OWN top. Shifting every block by the page's start
    offset instead stacked the whole page on one y position, which made the
    header, the customer block and every item row print on top of each other.
    """
    cursor = start_y_mm
    placed: list[Block] = []
    for block in blocks:
        moved = Block(kind=block.kind, height_mm=block.height_mm,
                      top_mm=cursor,
                      runs=[Run(run.x_mm, cursor + run.y_mm, run.width_mm, run.text,
                                run.size_pt, run.bold, run.align) for run in block.runs],
                      rules=[(cursor + y, thickness) for y, thickness in block.rules])
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
    # The first page carries the document header, which occupies real height.
    # Sizing the first group as if it started at the top margin pushed the
    # last rows of a full page past the bottom of the sheet.
    head_height = sum(block.height_mm for block in head)

    def group_blocks(reserve_tail: float) -> list[list[Block]]:
        """Split the body into pages that each actually fit.

        The break test must compare the space left with the height of the block
        being added. Testing only whether one block fits keeps appending until a
        single block no longer fits, which pushed whole pages of item rows past
        the bottom of the sheet.
        """
        groups: list[list[Block]] = []
        current: list[Block] = []
        used = 0.0
        for block in body:
            prefix = head_height if not groups else repeating_height
            if current and used + block.height_mm > limit - prefix - reserve_tail:
                groups.append(current)
                current = []
                used = 0.0
            current.append(block)
            used += block.height_mm
        groups.append(current)
        return groups

    # Only reserve room for totals/footer on the last page when the last page
    # needs it, so short bills are not pushed onto an extra sheet needlessly.
    groups = group_blocks(0.0)
    last_used = sum(block.height_mm for block in groups[-1])
    last_prefix = head_height if len(groups) == 1 else repeating_height
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


def _run_left_mm(run: Run) -> float:
    """Left edge of a run's ink in millimetres, honouring its alignment.

    Layout is computed in millimetres throughout; conversion to points happens
    exactly once, at the backend that draws. Converting here as well would
    scale every x by mm->pt a second time and push the text off the page.
    """
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
        # Rules are horizontal separators. The PDF path operator takes ABSOLUTE
        # coordinates, so the line-to endpoint must be offset by the rule's own
        # origin: (x0, y0) -> (x0 + width, y0 + thickness). Passing the width and
        # thickness as absolute coordinates instead drew a long diagonal from the
        # rule's left edge down to the bottom-right of the page.
        rule_x_pt = profile.margin_left_mm * mm_to_pt
        rule_len_pt = profile.content_width_mm * mm_to_pt
        for block in page_blocks:
            for y_mm, thickness in block.rules:
                y_pt = height_pt - y_mm * mm_to_pt
                thickness_pt = max(0.4, thickness * mm_to_pt)
                commands.append(
                    f"{rule_x_pt:.2f} {y_pt:.2f} m "
                    f"{rule_x_pt + rule_len_pt:.2f} {y_pt + thickness_pt:.2f} l S".encode()
                )
        for block in page_blocks:
            for run in block.runs:
                if not run.text:
                    continue
                font = "/F2" if run.bold else "/F1"
                x_pt = _run_left_mm(run) * mm_to_pt
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


def deepest_content_mm(page_blocks: list[Block]) -> float:
    """Lowest point any run or rule reaches on one page, in millimetres."""
    deepest = 0.0
    for block in page_blocks:
        deepest = max(deepest, block.top_mm + block.height_mm)
        for run in block.runs:
            deepest = max(deepest, run.y_mm + line_height_mm(run.size_pt))
        for y_mm, thickness in block.rules:
            deepest = max(deepest, y_mm + thickness)
    return deepest


def used_height_mm(pages: list[list[Block]], profile: PaperProfile = PHARMACY_A6) -> float:
    """Deepest content across every page, plus the bottom margin."""
    deepest = 0.0
    for page_blocks in pages:
        deepest = max(deepest, deepest_content_mm(page_blocks))
    return deepest + profile.margin_bottom_mm


def content_profile(pages: list[list[Block]],
                    profile: PaperProfile = PHARMACY_A6) -> PaperProfile:
    """A receipt page sized to the bill instead of a fixed sheet.

    The width is always the receipt width; the height shrinks to the content
    so a one-item bill is a short receipt rather than a mostly blank A6 sheet,
    and never grows past the paper the profile already supports.
    """
    wanted = used_height_mm(pages, profile)
    height = max(MIN_RECEIPT_HEIGHT_MM, min(wanted, profile.height_mm))
    if abs(height - profile.height_mm) < 0.01:
        return profile
    return PaperProfile(
        name=f"{profile.name}_CONTENT",
        width_mm=profile.width_mm,
        height_mm=round(height, 2),
        margin_left_mm=profile.margin_left_mm,
        margin_right_mm=profile.margin_right_mm,
        margin_top_mm=profile.margin_top_mm,
        margin_bottom_mm=profile.margin_bottom_mm,
        orientation=profile.orientation,
        scale_percent=profile.scale_percent,
    )


def validate_pages(pages: list[list[Block]], profile: PaperProfile = PHARMACY_A6) -> None:
    """Fail loudly if any run or rule falls outside the page.

    Guards the coordinate mistakes that ruin a printed bill: a rule drawn with
    the page height as its x (or vice versa), a negative offset, or content that
    runs past the printable edge.
    """
    page_w = profile.width_mm
    page_h = profile.height_mm
    for number, page_blocks in enumerate(pages, 1):
        for block in page_blocks:
            for run in block.runs:
                if not run.text:
                    continue
                width = text_width_mm(run.text, run.size_pt, bold=run.bold)
                left = _run_left_mm(run)
                if left < -0.01:
                    raise ReceiptPrintError(
                        f"page {number}: negative x {left:.2f}mm for {run.text[:24]!r}")
                if left + width > page_w + 0.5:
                    raise ReceiptPrintError(
                        f"page {number}: text past the right edge "
                        f"({left + width:.2f}mm > {page_w}mm) for {run.text[:24]!r}")
                if run.y_mm < -0.01:
                    raise ReceiptPrintError(
                        f"page {number}: negative y {run.y_mm:.2f}mm for {run.text[:24]!r}")
                if run.y_mm > page_h + 0.5:
                    raise ReceiptPrintError(
                        f"page {number}: text below the page "
                        f"({run.y_mm:.2f}mm > {page_h}mm) for {run.text[:24]!r}")
            for y_mm, thickness in block.rules:
                if y_mm < -0.01 or y_mm > page_h + 0.5:
                    raise ReceiptPrintError(
                        f"page {number}: rule outside the page at y={y_mm:.2f}mm")


def run_ink_box(run: Run) -> tuple[float, float, float, float]:
    """Ink rectangle (left, top, right, bottom) in millimetres.

    ``run.y_mm`` is a text baseline, so the ink starts one ascent above it and
    ends one descent below. Treating the baseline as the top of the box would
    report false collisions for text that is printed correctly.
    """
    height = line_height_mm(run.size_pt)
    ascent = height * 0.75
    descent = height * 0.25
    left = _run_left_mm(run)
    return left, run.y_mm - ascent, left + text_width_mm(
        run.text, run.size_pt, bold=run.bold), run.y_mm + descent


def overlapping_runs(page_blocks: list[Block], *, pad_mm: float = 0.08) -> list[tuple[str, str]]:
    """Pairs of text runs whose ink boxes collide on one page.

    Used to prove the layout stacks sections instead of printing them on top of
    each other; two runs only collide when they really occupy the same band.
    """
    boxes = [(*run_ink_box(run), run.text)
             for block in page_blocks for run in block.runs if run.text]
    collisions: list[tuple[str, str]] = []
    for index, (x0, y0, x1, y1, t0) in enumerate(boxes):
        for x2, y2, x3, y3, t1 in boxes[index + 1:]:
            if x0 + pad_mm <= x2 or x2 + pad_mm <= x0:
                continue
            if y0 + pad_mm <= y2 or y2 + pad_mm <= y0:
                continue
            # Horizontal separation always wins; report only a true 2-D clash.
            if x1 <= x2 or x3 <= x0:
                continue
            if y1 <= y2 or y3 <= y0:
                continue
            collisions.append((t0, t1))
    return collisions


def build_sale_pages(invoice_id: int, title: str = "Sales Bill",
                     profile: PaperProfile = PHARMACY_A6) -> tuple[list[list[Block]], dict]:
    record, items = load_sale(invoice_id, title)
    companies = sale_item_companies(invoice_id)
    units = sale_item_units(invoice_id)
    pages = paginate(build_layout(record, items, companies, units, profile), profile)
    page_profile = content_profile(pages, profile)
    validate_pages(pages, page_profile)
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
    """Write a sales/counter-sale receipt PDF on a content-sized A6 page."""
    from pathlib import Path

    pages, _record = build_sale_pages(invoice_id, title, profile)
    page_profile = content_profile(pages, profile)
    path = Path(output_path)
    if path.suffix.casefold() != ".pdf":
        path = path.with_suffix(".pdf")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pages_to_pdf_bytes(pages, page_profile))
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
    """Paint the receipt layout into ``rect`` (device units), fitted to width.

    The receipt is scaled uniformly so its width fills the device and kept
    top-aligned, so a short bill prints as a short receipt at the top of the
    sheet instead of floating in the middle of it. In Qt 6 page breaks belong
    to the paged device (``QPdfWriter``/``QPrinter``), not the painter.
    """
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QFont

    paged = device if device is not None else painter.device()
    width_pt, height_pt = page_size_pt(profile)
    target_w = rect.width()
    target_h = rect.height()
    scale = min(target_w / width_pt, target_h / height_pt)
    if scale <= 0:
        return
    origin_x = rect.x() + (target_w - width_pt * scale) / 2.0
    origin_y = rect.y()

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
                    origin_x + _run_left_mm(run) * PT_PER_MM * scale,
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
    page_profile = content_profile(pages, profile)
    printer = QPrinter(QPrinter.HighResolution)
    layout = qt_page_layout(page_profile)
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
        draw_pages_on_painter(painter, pages, painter.viewport(), page_profile)
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
    "build_layout", "paginate", "load_sale", "sale_item_companies", "sale_item_units",
    "qt_page_size", "qt_page_layout", "page_size_pt",
    "pages_to_pdf_bytes", "pages_to_preview_text", "build_sale_pages",
    "deepest_content_mm", "used_height_mm", "content_profile",
    "validate_pages", "overlapping_runs", "run_ink_box",
    "generate_pharmacy_a6_bill", "preview_pharmacy_a6_bill",
    "available_printers", "default_printer_name", "supported_page_size_mm",
    "draw_pages_on_painter", "print_pharmacy_a6_bill",
    "MM_PER_INCH", "PT_PER_INCH", "PT_PER_MM",
]