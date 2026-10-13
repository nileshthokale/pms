from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from PySide6.QtCore import (
    QDate,
    QEvent,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QFontMetrics, QStandardItem, QStandardItemModel

from database.customer_dao import CustomerDAO
from database.connection import get_connection
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.sales_dao import SalesDAO
from database.draft_stock import available_quantity, reserved_quantity
from database import auth
from database import financial_year
from database.document_printing import (DocumentPrintError, a6_profile,
                                        generate_counter_sale_bill,
                                        print_pharmacy_a6_bill)
from database.hold_bill_dao import (
    create_hold,
    ensure_hold_tables,
    get_hold_items,
    update_status,
    STATUS_ACTIVE,
    STATUS_RESUMED,
)

from ui.theme import palette
from ui.theme import indicator_style
from ui.components import FONT_FAMILY, readable_font, refresh_containers
from ui import fy_view
from ui.theme import (
    TYPE_BUTTON,
    TYPE_FORM_LABEL,
    TYPE_HINT,
    TYPE_INPUT,
    TYPE_INPUT_COMPACT,
    TYPE_PAGE_TITLE,
    TYPE_SECTION_HEADER,
    TYPE_TABLE_DATA,
    TYPE_TABLE_HEADER,
    TYPE_VALUE,
    TYPE_VALUE_EMPHASIS,
)
_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]
_SELECTED = _p["selected"]
_SELECTED_TEXT = _p["selected_text"]
_ERROR = "#c0392b"
_WARNING = "#b26a00"
# Completion-popup colours follow the active Day/Night theme.  They used to be
# hardcoded light-mode values, which left every popup in this screen blank in
# Night Mode: the popup background stayed white while the primary text colour
# flipped to white, so the product names were painted white on white.
def _popup_palette(p: dict | None = None) -> dict:
    """Popup colours derived from a theme palette (the active one by default).

    ``bg``/``text`` are the same pair the shared stylesheet uses for item
    views, so the popup matches the combo it drops from in both modes.
    """
    p = p or palette()
    return {
        "bg": p["bg"],
        "text": p["text"],
        "border": p["border"],
        "selected": p["selected"],
    }


_POPUP = _popup_palette()
_POPUP_BG = _POPUP["bg"]
_POPUP_TEXT = _POPUP["text"]
_POPUP_BORDER = _POPUP["border"]
_POPUP_SELECTED = _POPUP["selected"]

_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 4px 6px; font-size: {TYPE_INPUT}px;"
    f"  font-family: {FONT_FAMILY};"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 22px; }}"
    f"QComboBox::down-arrow {{ image: none; border: none; }}"
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_POPUP_BG}; color: {_POPUP_TEXT};"
    f"  border: 1px solid {_POPUP_BORDER}; selection-background-color: {_POPUP_SELECTED};"
    f"  selection-color: {_POPUP_TEXT}; outline: 0;"
    f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 6px; }}"
    f"QComboBox QAbstractItemView::item:selected {{"
    f"  background-color: {_POPUP_SELECTED}; color: {_POPUP_TEXT};"
    f"}}"
)

_ENTRY_COMBO_STYLE = _COMBO_STYLE + (
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_POPUP_BG}; color: {_POPUP_TEXT};"
    f"  border: 1px solid {_POPUP_BORDER};"
    f"  selection-background-color: {_POPUP_SELECTED};"
    f"  selection-color: {_POPUP_TEXT}; outline: 0;"
    f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
    f"}}"
)

_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 4px 6px; font-size: {TYPE_INPUT}px;"
    f"  font-family: {FONT_FAMILY};"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 4px 6px; font-size: {TYPE_INPUT}px;"
    f"  font-family: {FONT_FAMILY};"
    f"}}"
    f"QDateEdit:focus {{ border: 1px solid {_ACCENT}; }}"
    f"QDateEdit::drop-down {{ border: none; width: 22px; }}"
    f"QDateEdit::down-arrow {{ image: none; border: none; }}"
)

# â”€â”€ Compact controls for the bottom billing block â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# The Sale Header strip and the totals/action footer live in a fixed
# ~100 px area, so their controls use 2 px vertical padding instead of the
# 4 px used by the entry bar.  Same fonts, same colours, same border: only
# the box is shorter so two metadata rows and a label/value stack both fit
# without clipping.
_COMPACT_PADDING = "2px 5px"

_COMPACT_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: {_COMPACT_PADDING}; font-size: {TYPE_INPUT_COMPACT}px;"
    f"  font-family: {FONT_FAMILY};"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_COMPACT_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: {_COMPACT_PADDING}; font-size: {TYPE_INPUT_COMPACT}px;"
    f"  font-family: {FONT_FAMILY};"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 18px; }}"
    f"QComboBox::down-arrow {{ image: none; border: none; }}"
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_POPUP_BG}; color: {_POPUP_TEXT};"
    f"  border: 1px solid {_POPUP_BORDER}; selection-background-color: {_POPUP_SELECTED};"
    f"  selection-color: {_POPUP_TEXT}; outline: 0;"
    f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 2px 6px; }}"
    f"QComboBox QAbstractItemView::item:selected {{"
    f"  background-color: {_POPUP_SELECTED}; color: {_POPUP_TEXT};"
    f"}}"
)

_COMPACT_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: {_COMPACT_PADDING}; font-size: {TYPE_INPUT_COMPACT}px;"
    f"  font-family: {FONT_FAMILY};"
    f"}}"
    f"QDateEdit:focus {{ border: 1px solid {_ACCENT}; }}"
    f"QDateEdit::drop-down {{ border: none; width: 18px; }}"
    f"QDateEdit::down-arrow {{ image: none; border: none; }}"
)

# â”€â”€ Classic front-page buttons â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Reference look (legacy Pharma-WINNER front page): every button is a light,
# softly-rounded face with a thin coloured edge and dark bold text.  The
# button's *edge* carries its role instead of a flat coloured fill, so
# primary / hold / delete still read apart at a glance.
_BTN_FACE = _p["surface_alt"]
_BTN_FACE_HOVER = _p["selected"]
_BTN_FACE_PRESSED = _p["surface"]
_BTN_EDGE = _p["text_dim"]
_BTN_EDGE_HOVER = _p["accent"]
_BTN_FACE_DISABLED = _p["disabled_bg"]
_BTN_TEXT_DISABLED = _p["disabled_text"]
_BTN_DANGER_EDGE = _p.get("danger", _ERROR)
_BTN_WARNING_EDGE = _p.get("warning", _WARNING)


def _btn_style(
    edge: str,
    *,
    face: str | None = None,
    face_hover: str | None = None,
    face_pressed: str | None = None,
    fg: str | None = None,
    padding: str = "5px 14px",
    radius: str = "5px",
    font_size: str = f"{TYPE_BUTTON}px",
) -> str:
    """Build a classic (light face + thin edge) QPushButton stylesheet."""
    face = face or _BTN_FACE
    face_hover = face_hover or _BTN_FACE_HOVER
    face_pressed = face_pressed or _BTN_FACE_PRESSED
    return (
        "QPushButton {"
        f"  background-color: {face}; color: {fg or _TEXT};"
        f"  border: 1px solid {edge}; border-radius: {radius};"
        f"  padding: {padding}; font-weight: bold;"
        f"  font-size: {font_size}; font-family: {FONT_FAMILY};"
        "}"
        "QPushButton:hover {"
        f"  background-color: {face_hover}; border: 1px solid {edge};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {face_pressed}; border: 1px solid {edge};"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {_BTN_FACE_DISABLED};"
        f"  color: {_BTN_TEXT_DISABLED}; border: 1px solid {_BTN_EDGE};"
        "}"
    )


# Primary action â€” blue edge (Save Sale, New Sale).
_BTN_SAVE = _btn_style(_p["accent"])
# Neutral action (Cancel, Edit, Print / PDF).
_BTN_SECONDARY = _btn_style(_BTN_EDGE)
# Destructive action â€” red edge (the right-panel Delete button).
_BTN_DANGER = _btn_style(_BTN_DANGER_EDGE, padding="3px 8px", radius="4px")
# Compact primary (the "+ Add" button in the entry row).
_BTN_GREEN_SM = _btn_style(_p["accent"], padding="4px 10px", radius="4px")
# Hold / pending action â€” amber edge (Hold Bill).
_BTN_ORANGE = _btn_style(_BTN_WARNING_EDGE)
# Table row action (per-row Delete inside the Bill Items "Del" column).
# A quiet red edge on the light surface: it reads as a control inside a
# table cell rather than as a standalone button competing with the row.
# Kept at 11 px (below TYPE_BUTTON) because the button is pinned to the 22 px
# table row action box; the caption still reads as bold red-on-light and is
# not part of the main action hierarchy.
_BTN_ROW_ACTION = (
    "QPushButton {"
    f"  background-color: {_p['surface_alt']}; color: {_BTN_DANGER_EDGE};"
    f"  border: 1px solid {_BTN_DANGER_EDGE}; border-radius: 3px;"
    "  padding: 2px 6px; font-size: 11px; font-weight: bold;"
    f"  font-family: {FONT_FAMILY};"
    "}"
    "QPushButton:hover {"
    f"  background-color: {_p['selected']}; border: 1px solid {_BTN_DANGER_EDGE};"
    "}"
    "QPushButton:pressed {"
    f"  background-color: {_p['surface']}; border: 1px solid {_BTN_DANGER_EDGE};"
    "}"
    "QPushButton:disabled {"
    f"  background-color: {_p['disabled_bg']}; color: {_p['disabled_text']};"
    f"  border: 1px solid {_p['border']};"
    "}"
)

# ── Caption / label typography ────────────────────────────────────────
# Captions are black and bold: a classic desktop form reads its field
# captions, and grey captions were the single biggest cause of the "washed
# out" look.  ``_LABEL_DIM`` is reserved for genuinely secondary notes
# (hints, paper size) that must not compete with the data.
_LABEL_STYLE = (
    f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
    f"font-family: {FONT_FAMILY}; background: transparent;"
)
_LABEL_DIM = (
    f"color: {_TEXT_DIM}; font-size: {TYPE_HINT}px;"
    f"font-family: {FONT_FAMILY}; background: transparent;"
)
# Field captions (entry bar, totals, metadata strip): black, bold, 11 px.
_CAPTION_STYLE = (
    f"color: {_TEXT}; font-size: {TYPE_HINT}px; font-weight: bold;"
    f"font-family: {FONT_FAMILY}; background: transparent;"
)
# Captions of the item entry row only.  One step up from the other captions
# (12 px ~= 9 pt, the readable end of the 9-10 pt the row is specified at),
# so the row's twelve captions stay legible without enlarging the screen.
# Scoped to the entry bar so no other screen or strip changes with it.
_ENTRY_CAPTION_STYLE = (
    f"color: {_TEXT}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;"
    f"font-family: {FONT_FAMILY}; background: transparent;"
)
_HEADER_LABEL = (
    f"color: {_TEXT}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;"
    f"font-family: {FONT_FAMILY}; background: transparent;"
)

# â”€â”€ Item entry bar metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# One compact row shared by all twelve controls.  Every control uses the
# same box height so the bar reads as a single instrument strip instead of
# a row of mismatched boxes, and the label width is measured from the real
# font (capped) so labels never reserve a wide, mostly empty box.
_ENTRY_BAR_HEIGHT = 40          # label + control box, one straight row
_ENTRY_ADD_WIDTH = 78           # compact "+ Add": inside the 70-90 px target

# Caption metrics.  A caption box is its own text plus one fixed gap, so the
# text can never be clipped by the box that holds it, and the gap between a
# caption and the field it names is always the same 10 px -- the captions
# used to reserve a wide box whose 10 px inner margin ate into the text, so
# "Batch" / "Avail" / "MRP" were rendered clipped and read as if they were
# stuck to their fields.  The cap only stops a future long caption from
# stealing width from the fields.
_ENTRY_LABEL_GAP = 10           # caption -> the field it names (10-14 px)
_ENTRY_LABEL_MAX_WIDTH = 52     # longest caption + gap, on any platform font

# Seam between one field and the caption that follows it.  A caption names
# the field on its RIGHT, so it must hug that field and stand clear of the
# one before it.  Each caption is preceded by a dedicated QSpacerItem rather
# than by a wider caption box, so the gap is ordinary layout spacing and
# nothing is positioned by hand.  12 px of air plus the row's own 1 px
# spacing reads as the 10-14 px separation the row is specified to keep.
_ENTRY_GROUP_GAP = 12

# The Item -> Batch boundary is the busiest one on the row (a wide search box
# running into the next group), so it opens a little wider than the others.
_ENTRY_ITEM_BATCH_GAP = 16

# Field sizing.  Twelve controls and eleven captions do not fit a 1366-wide
# window at their comfortable widths, so the row is *responsive*: every field
# has a comfortable target it reaches when there is room, and a floor it
# shrinks to before the row starts taking width from its neighbours.  Item
# and Batch lead -- they hold the text a cashier actually reads -- while Pack
# and Qty stay compact by design.
_ENTRY_PREFERRED_WIDTHS = {
    "item_combo": 250,          # the primary search box
    "batch_combo": 157,         # long batch numbers stay readable
    "pack_edit": 50,
    "location_edit": 80,
    "expiry_edit": 80,
    "mrp_edit": 80,
    "stock_edit": 80,
    "qty_edit": 48,
    "discount_edit": 75,
    "amount_edit": 80,
}
_ENTRY_FLOOR_WIDTHS = {
    "item_combo": 150,
    "batch_combo": 110,
    "pack_edit": 44,
    "location_edit": 44,
    "expiry_edit": 44,
    "mrp_edit": 44,
    "stock_edit": 44,
    "qty_edit": 44,
    "discount_edit": 44,
    "amount_edit": 44,
}
# Absolute floor.  Below this a field can show nothing useful, so the row
# stops shrinking rather than pretend the partition still fits.
_ENTRY_MIN_DRAWABLE = 30
# Smallest bar the row will report it needs.  The row pins its fields to a
# partition of the bar's *current* width, so without this the bar's own
# minimum would equal its current size and the window could never be made
# narrower; the bar re-fits itself for whatever width it is actually given.
_ENTRY_MIN_BAR_WIDTH = 420

# Batch field sizing.  The combo shows
#   "<batch> | Exp: .. | MRP: .. | Avail: .."
# so its tail is elided by design, but the batch number at the head must
# always be readable in full.  The floor is measured from the real font and
# this chrome, never guessed: 6 px padding each side, the 22 px drop-down
# arrow reserved by QComboBox::drop-down, and a 1 px border each side.
_ENTRY_BATCH_CHROME = 6 + 6 + 22 + 2
_ENTRY_BATCH_MIN_WIDTH = 110   # matches _ENTRY_FLOOR_WIDTHS["batch_combo"]
_ENTRY_BATCH_MAX_WIDTH = 157   # matches _ENTRY_PREFERRED_WIDTHS["batch_combo"]

# â”€â”€ Bottom billing block metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# The Sale Header strip and the totals/action footer together form the
# fixed bottom billing section (~98 px), and both rows inside the strip use
# one shared box height so nothing is squeezed or clipped.
_METADATA_STRIP_HEIGHT = 56    # Bill No / Date / Time / Type + Customer row
_METADATA_CONTROL_HEIGHT = 24  # shared box height for every metadata control
_TOTALS_FOOTER_HEIGHT = 44     # totals + Hold / Save / Cancel
_TOTALS_CONTROL_HEIGHT = 24    # shared box height for footer totals
_ACTION_BUTTON_HEIGHT = 30     # Hold Bill / Save Sale / Cancel
_BILL_ROW_HEIGHT = 30          # Bill Items body row height
_BILL_HEADER_HEIGHT = 34       # header band is slightly taller than a row
_BILL_DELETE_WIDTH = 56        # compact Del action inside the table cell
_BILL_DELETE_HEIGHT = 22

# Bill Items columns.  Index 1 (Item Name) stretches; the rest are sized to
# their content so long item names and batch numbers cannot push the
# numeric columns off screen.
_BILL_COLUMN_WIDTHS = (34, 0, 82, 106, 150, 76, 76, 54, 84, 96, 72)
_BILL_CENTERED_COLUMNS = (0, 10)
_BILL_RIGHT_COLUMNS = (6, 7, 8, 9)

def _group_box_style(p: dict | None = None) -> str:
    """QGroupBox style built from a palette (live palette by default).

    The box is opaque in the workspace ``bg`` with the title cut out in the
    same ``bg``: without an explicit background the interior stays
    transparent and shows the backing store (a solid black rectangle in Day
    Mode after a Night -> Day switch, or a washed-out frame in Night Mode).
    """
    p = p or palette()
    return (
        f"QGroupBox {{"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']}; font-weight: bold; font-size: {TYPE_SECTION_HEADER}px;"
        f"  font-family: {FONT_FAMILY};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  margin-top: 10px; padding-top: 14px;"
        f"}}"
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px;"
        f"  color: {p['text']}; background-color: {p['bg']}; }}"
    )


_GROUP_BOX = _group_box_style(_p)


# ── Live (Day/Night-safe) style builders ──────────────────────────────
# Module-level ``_COMBO_STYLE`` / ``_EDIT_STYLE`` / … constants are snapshots
# baked at import time.  After a Day/Night switch the module is reloaded so
# FUTURE widgets bake fresh colours, but EXISTING widgets keep the stale
# snapshot (dark ``#000000`` backgrounds persisting in Day Mode is the
# reported black rectangle below "Bill Items").  These builders recompute the
# identical structural styles from the LIVE centralized palette, so
# ``refresh_theme()`` can re-apply them in place without losing bill drafts,
# focus, selection or scroll state.  Every colour comes from ``palette()``.
def _fresh_popup(p: dict | None = None) -> dict:
    return _popup_palette(p or palette())


def _fresh_combo_style(p: dict | None = None) -> str:
    p = p or palette()
    pp = _popup_palette(p)
    return (
        f"QComboBox {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
        f"QComboBox:hover {{ border: 1px solid {p['accent']}; }}"
        f"QComboBox::drop-down {{ border: none; width: 22px; }}"
        f"QComboBox::down-arrow {{ image: none; border: none; }}"
        f"QComboBox QAbstractItemView {{"
        f"  background-color: {pp['bg']}; color: {pp['text']};"
        f"  border: 1px solid {pp['border']}; selection-background-color: {pp['selected']};"
        f"  selection-color: {pp['text']}; outline: 0;"
        f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 6px; }}"
        f"QComboBox QAbstractItemView::item:selected {{"
        f"  background-color: {pp['selected']}; color: {pp['text']};"
        f"}}"
    )


def _fresh_entry_combo_style(p: dict | None = None) -> str:
    p = p or palette()
    pp = _popup_palette(p)
    return _fresh_combo_style(p) + (
        f"QComboBox QAbstractItemView {{"
        f"  background-color: {pp['bg']}; color: {pp['text']};"
        f"  border: 1px solid {pp['border']};"
        f"  selection-background-color: {pp['selected']};"
        f"  selection-color: {pp['text']}; outline: 0;"
        f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
    )


def _fresh_edit_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QLineEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
        f"QLineEdit:focus {{ border: 1px solid {p['accent']}; }}"
    )


def _fresh_date_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QDateEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
        f"QDateEdit:focus {{ border: 1px solid {p['accent']}; }}"
        f"QDateEdit::drop-down {{ border: none; width: 22px; }}"
        f"QDateEdit::down-arrow {{ image: none; border: none; }}"
    )


def _fresh_compact_edit_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QLineEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: {_COMPACT_PADDING}; font-size: {TYPE_INPUT_COMPACT}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
        f"QLineEdit:focus {{ border: 1px solid {p['accent']}; }}"
    )


def _fresh_compact_combo_style(p: dict | None = None) -> str:
    p = p or palette()
    pp = _popup_palette(p)
    return (
        f"QComboBox {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: {_COMPACT_PADDING}; font-size: {TYPE_INPUT_COMPACT}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
        f"QComboBox:hover {{ border: 1px solid {p['accent']}; }}"
        f"QComboBox::drop-down {{ border: none; width: 18px; }}"
        f"QComboBox::down-arrow {{ image: none; border: none; }}"
        f"QComboBox QAbstractItemView {{"
        f"  background-color: {pp['bg']}; color: {pp['text']};"
        f"  border: 1px solid {pp['border']}; selection-background-color: {pp['selected']};"
        f"  selection-color: {pp['text']}; outline: 0;"
        f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 2px 6px; }}"
        f"QComboBox QAbstractItemView::item:selected {{"
        f"  background-color: {pp['selected']}; color: {pp['text']};"
        f"}}"
    )


def _fresh_compact_date_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QDateEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: {_COMPACT_PADDING}; font-size: {TYPE_INPUT_COMPACT}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
        f"QDateEdit:focus {{ border: 1px solid {p['accent']}; }}"
        f"QDateEdit::drop-down {{ border: none; width: 18px; }}"
        f"QDateEdit::down-arrow {{ image: none; border: none; }}"
    )


def _fresh_btn_style(edge: str, p: dict | None = None, **kwargs) -> str:
    """Fresh classic button (light face + thin edge) from live palette."""
    p = p or palette()
    face = kwargs.get("face") or p["surface_alt"]
    face_hover = kwargs.get("face_hover") or p["selected"]
    face_pressed = kwargs.get("face_pressed") or p["surface"]
    fg = kwargs.get("fg") or p["text"]
    padding = kwargs.get("padding", "5px 14px")
    radius = kwargs.get("radius", "5px")
    font_size = kwargs.get("font_size", f"{TYPE_BUTTON}px")
    return (
        "QPushButton {"
        f"  background-color: {face}; color: {fg};"
        f"  border: 1px solid {edge}; border-radius: {radius};"
        f"  padding: {padding}; font-weight: bold;"
        f"  font-size: {font_size}; font-family: {FONT_FAMILY};"
        "}"
        "QPushButton:hover {"
        f"  background-color: {face_hover}; border: 1px solid {edge};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {face_pressed}; border: 1px solid {edge};"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {p['disabled_bg']};"
        f"  color: {p['disabled_text']}; border: 1px solid {p['text_dim']};"
        "}"
    )


def _fresh_row_action_style(p: dict | None = None) -> str:
    p = p or palette()
    danger = p.get("danger", "#c0392b")
    return (
        "QPushButton {"
        f"  background-color: {p['surface_alt']}; color: {danger};"
        f"  border: 1px solid {danger}; border-radius: 3px;"
        "  padding: 2px 6px; font-size: 11px; font-weight: bold;"
        f"  font-family: {FONT_FAMILY};"
        "}"
        "QPushButton:hover {"
        f"  background-color: {p['selected']}; border: 1px solid {danger};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {p['surface']}; border: 1px solid {danger};"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {p['disabled_bg']}; color: {p['disabled_text']};"
        f"  border: 1px solid {p['border']};"
        "}"
    )


def _fresh_completer_popup_style(p: dict | None = None) -> str:
    """Fresh QCompleter popup (top-level QListView) from live palette."""
    p = p or palette()
    pp = _popup_palette(p)
    return (
        f"QAbstractItemView {{ background-color: {pp['bg']}; color: {pp['text']}; "
        f"border: 1px solid {pp['border']}; selection-background-color: {pp['selected']}; "
        f"selection-color: {pp['text']}; font: 11px 'Segoe UI'; outline: 0; }}"
        f"QAbstractItemView::item {{ min-height: 24px; padding: 2px 6px; }}"
        f"QAbstractItemView::item:selected {{ background-color: {pp['selected']}; color: {pp['text']}; }}"
    )


def _fresh_bill_header_style(p: dict | None = None) -> str:
    p = p or palette()
    # 12px == TYPE_TABLE_HEADER (numeric literal so source-typography guards
    # recognise the header floor; runtime value equals the shared scale).
    return (
        f"QHeaderView::section {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: none; border-bottom: 2px solid {p['accent']};"
        f"  padding: 4px 5px; font-weight: bold;"
        f"  font-size: 12px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
    )


def _fresh_bill_table_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QTableWidget {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; gridline-color: {p['border']};"
        f"  font-size: {TYPE_TABLE_DATA}px; font-family: {FONT_FAMILY};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        f"}}"
        f"QTableWidget::item {{ padding: 3px 6px; }}"
    )


def _fresh_history_header_style(p: dict | None = None) -> str:
    p = p or palette()
    # 12px == TYPE_TABLE_HEADER (numeric literal for source-typography guards).
    return (
        f"QHeaderView::section {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: none; border-bottom: 2px solid {p['accent']};"
        f"  padding: 4px 6px; font-weight: bold;"
        f"  font-size: 12px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
    )


def _fresh_history_table_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QTableWidget {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; gridline-color: {p['border']};"
        f"  font-size: {TYPE_TABLE_DATA}px; font-family: {FONT_FAMILY};"
        f"  selection-background-color: {p['accent']};"
        f"  selection-color: white;"
        f"}}"
        f"QTableWidget::item {{ padding: 3px 5px; }}"
    )


def _fresh_radio_style(p: dict | None = None) -> str:
    """Item Wise / Bill Wise radios: text plus the live indicator glyph.

    The previous version set only ``width``/``height`` on the indicator.
    Naming the ``::indicator`` sub-control is enough to stop Qt drawing the
    native radio dot, so a checked mode looked exactly like an unchecked
    one — and in Night Mode both were a black square.

    The button itself stays borderless (no outer rectangle around the
    indicator + label in any state); only the small circular ::indicator
    carries a border + dot, so checked stays unmistakable in Day and Night
    Mode.
    """
    p = p or palette()
    return (
        f"QRadioButton {{ color: {p['text']}; font-size: {TYPE_FORM_LABEL}px;"
        f"  background: transparent; border: none; outline: none;"
        f"  spacing: 5px; font-family: {FONT_FAMILY}; }}"
        "QRadioButton:focus { background: transparent;"
        "  border: none; outline: none; }"
        "QRadioButton:hover { background: transparent; border: none; }"
        + indicator_style(checkbox=False)
    )


def _refresh_completer_popup(combo) -> None:
    """Re-apply the live popup colours to a _KeyboardCombo's list."""
    try:
        completer = combo.completer()
        popup = completer.popup() if completer is not None else None
        if popup is not None:
            popup.setStyleSheet(_fresh_completer_popup_style())
            popup.update()
    except Exception:
        pass


def _fresh_button_for_text(text: str, p: dict) -> str | None:
    """Fresh button style for a Counter Sale caption (None if unknown).

    Button texts in this screen are fixed, so the caption identifies the
    variant without guessing from stale hex values (dark ``#141414`` faces
    persisting in Day Mode is a black-rectangle source).  Every colour comes
    from the live palette.
    """
    t = (text or "").strip()
    if t in ("Save Sale", "New Sale"):
        return _fresh_btn_style(p["accent"], p)
    if t == "+ Add":
        return _fresh_btn_style(p["accent"], p, padding="4px 10px", radius="4px")
    if t == "Hold Bill":
        return _fresh_btn_style(p.get("warning", "#b26a00"), p)
    if t == "Delete":
        # Panel Delete (full-width) vs row Delete (56x22, 11 px) share the
        # caption; the caller distinguishes by size via cs_btn_kind.
        return None
    if t in ("Cancel", "Edit", "Print", "Print / PDF", "All Dates", "Refresh"):
        return _fresh_btn_style(p["text_dim"], p)
    return None


def refresh_cs_tree(root) -> int:
    """In-place Day/Night refresh for Counter Sale widget subtrees.

    Re-applies live centralized colours to group boxes, tables + headers,
    combos/edits/dates (via ``cs_style`` tags), completer popups, buttons
    (via fixed captions) and transparent labels — preserving layout, focus,
    selection, drafts and scroll state.  Returns widgets updated.
    """
    try:
        from PySide6.QtWidgets import (
            QComboBox, QDateEdit, QGroupBox, QLabel, QLineEdit,
            QPushButton, QTableWidget, QWidget,
        )
    except Exception:
        return 0
    try:
        p = palette()
    except Exception:
        return 0
    updated = 0
    try:
        widgets = [root] + list(root.findChildren(QWidget))
    except Exception:
        return 0
    # Known text/dim hexes across BOTH modes to infer label roles.
    try:
        from ui.theme import _PALETTES as _PALS
        text_hexes = {str(_PALS[m].get("text", "")).lower() for m in _PALS}
        dim_hexes = {str(_PALS[m].get("text_dim", "")).lower() for m in _PALS}
    except Exception:
        text_hexes, dim_hexes = set(), set()
    for w in widgets:
        try:
            if isinstance(w, QGroupBox):
                w.setStyleSheet(_group_box_style(p))
                updated += 1
                continue
            if isinstance(w, _KeyboardCombo):
                try:
                    w.refresh_theme()
                except Exception:
                    _refresh_completer_popup(w)
                updated += 1
                continue
            if isinstance(w, QComboBox):
                try:
                    kind = w.property("cs_style")
                except Exception:
                    kind = None
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                try:
                    if kind == "compact_combo" or "2px 5px" in ss:
                        w.setStyleSheet(_fresh_compact_combo_style(p))
                    elif kind == "entry_combo":
                        w.setStyleSheet(_fresh_entry_combo_style(p))
                    elif "QComboBox" in ss:
                        w.setStyleSheet(_fresh_combo_style(p))
                    else:
                        continue
                    updated += 1
                except Exception:
                    pass
                _refresh_completer_popup(w)
                continue
            if isinstance(w, QLineEdit):
                # Skip combo-internal line edits (transparent, borderless).
                try:
                    parent = w.parent()
                    from PySide6.QtWidgets import QComboBox as _CB
                    if parent is not None and isinstance(parent, _CB):
                        continue
                except Exception:
                    pass
                try:
                    kind = w.property("cs_style")
                except Exception:
                    kind = None
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                try:
                    if kind == "compact_edit" or "2px 5px" in ss:
                        w.setStyleSheet(_fresh_compact_edit_style(p))
                    elif "QLineEdit" in ss:
                        w.setStyleSheet(_fresh_edit_style(p))
                    else:
                        continue
                    updated += 1
                except Exception:
                    pass
                continue
            if isinstance(w, QDateEdit):
                try:
                    kind = w.property("cs_style")
                except Exception:
                    kind = None
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                try:
                    if kind == "compact_date" or "2px 5px" in ss:
                        w.setStyleSheet(_fresh_compact_date_style(p))
                    elif "QDateEdit" in ss:
                        w.setStyleSheet(_fresh_date_style(p))
                    else:
                        continue
                    updated += 1
                except Exception:
                    pass
                continue
            if isinstance(w, QPushButton):
                try:
                    kind = w.property("cs_btn_kind")
                except Exception:
                    kind = None
                txt = w.text() if hasattr(w, "text") else ""
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if "QPushButton" not in ss:
                    continue
                try:
                    if kind == "row_delete" or (
                        txt.strip() == "Delete"
                        and w.maximumWidth() <= 60
                        and "11px" in ss
                    ):
                        w.setStyleSheet(_fresh_row_action_style(p))
                        updated += 1
                    elif txt.strip() == "Delete":
                        w.setStyleSheet(_fresh_btn_style(p.get("danger", "#c0392b"), p,
                                                         padding="3px 8px", radius="4px"))
                        updated += 1
                    else:
                        fresh = _fresh_button_for_text(txt, p)
                        if fresh is not None:
                            w.setStyleSheet(fresh)
                            updated += 1
                except Exception:
                    pass
                continue
            if isinstance(w, QLabel):
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if not ss or "background: transparent" not in ss:
                    continue
                # Preserve size/weight; only the colour role refreshes.
                import re as _re
                m = _re.search(r"color:\s*(#[0-9a-fA-F]{6}|white|black)", ss)
                if not m:
                    continue
                col = m.group(1).lower()
                try:
                    if col in dim_hexes:
                        new_col = p["text_dim"]
                    elif col in text_hexes or col in ("#000000", "#ffffff", "black", "white"):
                        # White/black alone is ambiguous; transparent labels
                        # in this screen are always text or dim.  Dim labels
                        # declare 11 px without bold in _LABEL_DIM; bold 11 px
                        # captions are text.  Fall back to text.
                        if "font-size: 11px" in ss and "font-weight: bold" not in ss:
                            new_col = p["text_dim"]
                        else:
                            new_col = p["text"]
                    else:
                        # Danger/warning accents (red/amber) are identical in
                        # both modes — leave them.
                        continue
                    new_ss = ss[:m.start()] + f"color: {new_col}" + ss[m.end():]
                    # Radio buttons are handled via _fresh_radio_style.
                    w.setStyleSheet(new_ss)
                    updated += 1
                except Exception:
                    pass
                continue
        except Exception:
            continue
    # Tables + headers via stored structure (bill vs history by header text).
    for w in widgets:
        try:
            if isinstance(w, QTableWidget):
                try:
                    headers = [
                        w.horizontalHeaderItem(c).text()
                        if w.horizontalHeaderItem(c) is not None else ""
                        for c in range(w.columnCount())
                    ]
                except Exception:
                    headers = []
                is_bill = "Del" in headers or "Item Name" in headers and "Disc Amt" in headers and len(headers) == 11
                try:
                    if is_bill:
                        w.setStyleSheet(_fresh_bill_table_style(p))
                        hv = w.horizontalHeader()
                        hv.setStyleSheet(_fresh_bill_header_style(p))
                    else:
                        w.setStyleSheet(_fresh_history_table_style(p))
                        hv = w.horizontalHeader()
                        hv.setStyleSheet(_fresh_history_header_style(p))
                    updated += 1
                except Exception:
                    pass
        except Exception:
            continue
    # Radio indicators follow text; ensure transparent bg (no black box).
    for w in widgets:
        try:
            from PySide6.QtWidgets import QRadioButton
            if isinstance(w, QRadioButton):
                w.setStyleSheet(_fresh_radio_style(p))
                updated += 1
        except Exception:
            continue
    # Plain container chrome (header strip, history filter bar, the
    # right-side Bill / Current Bill panel) is styled from baked module
    # constants and is reached by none of the branches above — without this
    # it kept the Day Mode light-blue surface in Night Mode.
    try:
        updated += refresh_containers(root)
    except Exception:
        pass
    return updated


# Keep transient Qt widgets alive long enough for their Python wrappers to
# remain usable during tests and when a page is re-created without an explicit
# parent.  This prevents PySide from deleting the underlying C++ object while
# the Python code still holds a reference to the widget.
_LIVE_WIDGETS: list[object] = []


def _keep_alive(widget: object) -> None:
    _LIVE_WIDGETS.append(widget)


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        return float(text.strip()) if text.strip() else default
    except ValueError:
        return default


def _d(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round2(value) -> float:
    return float(_d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _mark_cs(widget, kind: str) -> None:
    """Tag a Counter Sale widget with its style kind for refresh_theme()."""
    try:
        widget.setProperty("cs_style", kind)
    except Exception:
        pass


def _make_edit(placeholder: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_EDIT_STYLE)
    _mark_cs(e, "edit")
    e.setFont(readable_font(TYPE_INPUT))
    if width:
        e.setMaximumWidth(width)
    return e


def _make_compact_edit(placeholder: str = "", *,
                       height: int = _TOTALS_CONTROL_HEIGHT) -> QLineEdit:
    """Shorter-boxed line edit for the fixed bottom billing block."""
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_COMPACT_EDIT_STYLE)
    _mark_cs(e, "compact_edit")
    e.setFont(readable_font(TYPE_INPUT_COMPACT))
    e.setFixedHeight(height)
    return e


def _make_compact_combo() -> QComboBox:
    """Shorter-boxed combo for the fixed bottom billing block.

    Built on ``_KeyboardCombo`` so the popup styling and keyboard contract
    stay identical to the entry bar; only the box height differs.
    """
    c = _KeyboardCombo()
    c.setStyleSheet(_COMPACT_COMBO_STYLE)
    _mark_cs(c, "compact_combo")
    c.setFixedHeight(_METADATA_CONTROL_HEIGHT)
    c.lineEdit().setFixedHeight(_METADATA_CONTROL_HEIGHT - 2)
    _keep_alive(c)
    return c


def _make_compact_date() -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setStyleSheet(_COMPACT_DATE_STYLE)
    _mark_cs(d, "compact_date")
    d.setFixedHeight(_METADATA_CONTROL_HEIGHT)
    return d


class _KeyboardCombo(QComboBox):
    """Editable combo with a local, predictable completion keyboard contract."""

    completionAccepted = Signal()

    def __init__(self):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCompleter(QCompleter(self.model(), self))
        completer = self.completer()
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setMaxVisibleItems(10)
        completer.popup().setFocusPolicy(Qt.NoFocus)
        completer.popup().setSelectionMode(QAbstractItemView.SingleSelection)
        # QCompleter owns a separate popup window; style it explicitly from
        # the active Day/Night palette so it never falls back to the
        # platform's own colours and never ends up as unreadable text (a
        # white popup with white names was the Night Mode blank-list bug).
        completer.popup().setStyleSheet(_fresh_completer_popup_style())
        _mark_cs(self, "combo")
        self.setFocusPolicy(Qt.StrongFocus)
        self._show_all_on_click = False
        self.lineEdit().installEventFilter(self)
        # An editable QComboBox redirects keyboard focus to the combo itself
        # (the line edit's focus proxy), so a physical keyboard sends its key
        # events to *this* widget, not to the line edit.  Filtering both
        # targets keeps one predictable keyboard contract: completer keys are
        # handled by this class whether they arrive on the combo, on its line
        # edit, or on the completion popup.
        self.installEventFilter(self)
        completer.popup().installEventFilter(self)
        completer.activated[str].connect(self._on_activated)

    def set_completion_model(self, model, role=Qt.DisplayRole):
        self.completer().setModel(model)
        self.completer().setCompletionRole(role)

    def show_all_completions_on_click(self, enabled=True):
        self._show_all_on_click = enabled

    def isReadOnly(self) -> bool:
        """Read-only state of the editable text (the QLineEdit contract).

        Auto-filled entry fields are read-only line edits while the searchable
        ones are editable combos; reporting one uniform flag keeps every
        entry-bar field checkable the same way.
        """
        line_edit = self.lineEdit()
        return bool(line_edit is not None and line_edit.isReadOnly())

    def _restore_owner_activation(self) -> None:
        """Hand window activation back to the owner after the list closes.

        The completion list is its own top-level window. When it closes, some
        platforms (notably the offscreen test platform, but also a driver or a
        remote session) leave it as the active window, and focus then cannot
        move inside the page at all - so "Enter on a batch" would never reach
        Qty. Reactivating the owner restores the normal keyboard chain and is
        a no-op when the owner is already active.
        """
        owner = self.window()
        if owner is None:
            return
        active = QApplication.activeWindow()
        if active is not None and active is not owner:
            owner.activateWindow()

    def eventFilter(self, watched, event):
        popup = self.completer().popup()
        if watched is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            if self._show_all_on_click:
                QTimer.singleShot(0, self._show_completion_popup)
        elif watched is popup and event.type() == QEvent.Show:
            QTimer.singleShot(0, self._position_completion_popup)

        if event.type() != QEvent.KeyPress:
            return super().eventFilter(watched, event)

        key = event.key()
        if watched not in (self, self.lineEdit(), popup):
            return super().eventFilter(watched, event)

        if key in (Qt.Key_Down, Qt.Key_Up):
            if popup.isVisible():
                self._move_popup_selection(1 if key == Qt.Key_Down else -1)
                return True
            # Popup closed: open the list with a row already highlighted so
            # TYPE -> Down -> Enter always lands on a real entry instead of
            # being swallowed by QComboBox's own dropdown handling.
            self._open_popup_from_keyboard(key == Qt.Key_Down)
            return True

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if popup.isVisible():
                self._accept_popup_selection()
                return True
            if self.currentData() is not None:
                self.completionAccepted.emit()
            # Always consumed: falling through would let QComboBox swallow
            # Enter instead of advancing the keyboard chain.
            return True

        if key == Qt.Key_Escape:
            popup.hide()
            self._restore_owner_activation()
            self.setFocus()
            return True

        if key == Qt.Key_Tab and popup.isVisible():
            if not self._accept_popup_selection():
                self.focusNextChild()
            return True

        return super().eventFilter(watched, event)

    def _completion_source_has_data(self) -> bool:
        """True when the completion source stores a role value per row.

        Placeholder rows (``-- Select --``, ``-- Select Batch --``,
        ``No products found``) store ``None`` in ``Qt.UserRole`` and are
        never selectable.  Plain choice lists (sale type) never store a role
        value, so every row of those counts as selectable.
        """
        model = self.completer().model()
        if model is None:
            return False
        for row in range(model.rowCount()):
            if model.index(row, 0).data(Qt.UserRole) is not None:
                return True
        return False

    def _selectable_index(self, start: int, step: int):
        """Walk the completion rows from ``start`` for a selectable one."""
        completer = self.completer()
        count = completer.completionCount()
        row = start
        while 0 <= row < count:
            index = completer.completionModel().index(row, 0)
            if index.data(Qt.UserRole) is not None:
                return index
            row += step
        if count and not self._completion_source_has_data():
            row = min(max(start, 0), count - 1)
            return completer.completionModel().index(row, 0)
        return QModelIndex()

    def _highlight_row(self, index) -> bool:
        if not index.isValid():
            return False
        popup = self.completer().popup()
        popup.setCurrentIndex(index)
        popup.scrollTo(index)
        return True

    def _move_popup_selection(self, step: int) -> bool:
        row = self.completer().popup().currentIndex().row()
        if row < 0:
            start = 0 if step > 0 else self.completer().completionCount() - 1
        else:
            start = row + step
        return self._highlight_row(self._selectable_index(start, step))

    def _open_popup_from_keyboard(self, from_top: bool) -> None:
        """Open the completion list from the keyboard with a row selected."""
        text = self.currentText()
        # An exact entry match would only filter the list down to itself;
        # listing every row keeps Down useful after a previous selection.
        if text and self.findText(text, Qt.MatchFixedString) >= 0:
            text = ""
        completer = self.completer()
        completer.setCompletionPrefix(text)
        if completer.completionCount() == 0:
            return
        completer.complete()
        self._position_completion_popup()
        if not completer.popup().isVisible():
            return
        start = 0 if from_top else completer.completionCount() - 1
        step = 1 if from_top else -1
        self._highlight_row(self._selectable_index(start, step))

    def _show_completion_popup(self):
        self.completer().setCompletionPrefix("")
        self.completer().complete()
        self._position_completion_popup()

    def _position_completion_popup(self):
        popup = self.completer().popup()
        if not popup.isVisible():
            return
        window = self.window()
        bounds = QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
        count = max(1, self.completer().completionCount())
        row_height = max(24, popup.sizeHintForRow(0))
        height = min(row_height * min(count, 10) + 4, bounds.height())
        width = min(max(self.width(), popup.sizeHintForColumn(0) + 28), bounds.width())
        below = self.mapToGlobal(QPoint(0, self.height())).y()
        x = min(max(bounds.left(), self.mapToGlobal(QPoint(0, 0)).x()),
                bounds.right() - width + 1)
        y = min(below, bounds.bottom() - height + 1)
        y = max(bounds.top(), y)
        popup.setGeometry(x, y, width, height)

    def _accept_text(self, text: str):
        index = self.findText(text, Qt.MatchFixedString)
        if index >= 0:
            self.setCurrentIndex(index)
            return True
        return False

    def _on_activated(self, text: str):
        if self._accept_text(text):
            self.completionAccepted.emit()

    def _accept_popup_selection(self) -> bool:
        completer = self.completer()
        popup = completer.popup()
        index = popup.currentIndex()
        if index.isValid() and index.data(Qt.UserRole) is not None:
            accepted = True
        elif index.isValid() and not self._completion_source_has_data():
            # Plain choice list (sale type): rows carry no role value, so
            # the row the keyboard highlighted is the selection.
            accepted = True
        else:
            # Status rows ("-- Select --", "No products found") are shown in
            # the list but are never selectable; take the first real row.
            index = self._selectable_index(0, 1)
            accepted = index.isValid()
        if accepted:
            self._accept_text(index.data())
        popup.hide()
        self._restore_owner_activation()
        if accepted:
            self.completionAccepted.emit()
        return accepted

    def refresh_theme(self) -> None:
        """Re-apply live Day/Night colours to the combo box + its popup.

        The completer popup is a separate top-level window with an explicit
        stylesheet baked at construction; without this it keeps the stale
        mode's background (black list in Day Mode, white-on-white in Night
        Mode).  The box style is chosen by the ``cs_style`` tag so entry,
        regular and compact combos each keep their own metrics.
        """
        try:
            kind = self.property("cs_style")
        except Exception:
            kind = None
        try:
            p = palette()
            if kind == "compact_combo":
                self.setStyleSheet(_fresh_compact_combo_style(p))
            elif kind == "entry_combo":
                self.setStyleSheet(_fresh_entry_combo_style(p))
            else:
                self.setStyleSheet(_fresh_combo_style(p))
        except Exception:
            pass
        _refresh_completer_popup(self)
        try:
            self.update()
        except Exception:
            pass


def _make_combo() -> QComboBox:
    c = _KeyboardCombo()
    c.setStyleSheet(_COMBO_STYLE)
    _mark_cs(c, "combo")
    _keep_alive(c)
    return c


def _make_date() -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setStyleSheet(_DATE_STYLE)
    _mark_cs(d, "date")
    return d


# ======================================================================
# Database-backed lookup fields (Sales Bill popup only)
# ======================================================================

# Cap on how many suggestions one lookup shows.  Patient names come from a
# large history table, so the list is a filtered window rather than the whole
# column â€” enough to browse, small enough to stay instant while typing.
_DB_LOOKUP_LIMIT = 60


def _patient_name_options(query: str) -> list[str]:
    """Distinct patient names already recorded in the database.

    Patient is free text on the sale, so the existing sale history is the
    real source of names.  Matching is case-insensitive and partial, so
    "ram" finds "BHRAMHAKUMARI NANDA".  Nothing is invented here.
    """
    text = (query or "").strip()
    pattern = f"%{text}%" if text else "%"
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT patient_name FROM sales_invoices "
            "WHERE patient_name IS NOT NULL AND TRIM(patient_name) <> '' "
            "AND patient_name COLLATE NOCASE LIKE ? "
            "ORDER BY patient_name LIMIT ?",
            (pattern, _DB_LOOKUP_LIMIT),
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def _address_options(query: str) -> list[str]:
    """Distinct addresses already stored against customers."""
    text = (query or "").strip()
    pattern = f"%{text}%" if text else "%"
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT address FROM customers "
            "WHERE address IS NOT NULL AND TRIM(address) <> '' "
            "AND address COLLATE NOCASE LIKE ? "
            "ORDER BY address LIMIT ?",
            (pattern, _DB_LOOKUP_LIMIT),
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


class _DBLookupCombo(_KeyboardCombo):
    """Editable combo whose suggestions come from the live database.

    Behaves exactly like the existing item autocomplete: a click opens the
    list, typing filters it case-insensitively on a partial match, and
    Arrow Up / Arrow Down / Enter / Escape / Tab and mouse selection all
    work through the shared ``_KeyboardCombo`` contract.  Only the source of
    the rows differs â€” the values are queried on demand instead of held in
    memory, so a large patient history stays responsive.

    The ``text()`` / ``setText()`` / ``clear()`` trio mirrors the plain line
    edit it replaces, so the surrounding save logic is unchanged.
    """

    def __init__(self, option_provider, *, placeholder: str = "",
                 width: int | None = None):
        super().__init__()
        self._option_provider = option_provider
        self.setStyleSheet(_COMBO_STYLE)
        if placeholder:
            self.lineEdit().setPlaceholderText(placeholder)
        if width:
            # A floor, not a fixed size: the field may grow into whatever
            # space the strip has spare, so the row never shows a gap.
            self.setMinimumWidth(width)
        self.show_all_completions_on_click()
        self.lineEdit().textEdited.connect(self._on_text_edited)
        self._on_text_edited("")

    def _on_text_edited(self, text: str):
        """Re-query the database for what the user has typed so far."""
        self._reload(text)

    def _reload(self, query: str):
        """Replace the suggestion rows, keeping the typed text intact."""
        typed = self.lineEdit().text()
        try:
            options = self._option_provider(query)
        except Exception:
            # A lookup failure must never block typing in the bill.
            options = []
        self.blockSignals(True)
        try:
            QComboBox.clear(self)
            for option in options:
                self.addItem(option)
            # The completer reads the combo's own model, so a selected row
            # can always be matched back by text.
            self.set_completion_model(self.model())
            self.setEditText(typed)
        finally:
            self.blockSignals(False)

    def reload(self, query: str = ""):
        """Public refresh used when the popup opens."""
        self._reload(query)

    def text(self) -> str:
        return self.lineEdit().text()

    def setText(self, value: str):
        self.setEditText(value or "")

    def clear(self):
        """Clear the typed value only â€” the suggestion rows stay."""
        self.lineEdit().clear()


# ======================================================================
# Bill line item data class
# ======================================================================

class _BillItemRow:
    """One line item in the current bill."""

    def __init__(self, item_id: int, item_name: str, stock_batch_id: int,
                 pack_size: str, location: str, batch_no: str, expiry: str,
                 mrp: float, sale_qty: float, discount_amount: float,
                 amount: float):
        self.item_id = item_id
        self.item_name = item_name
        self.stock_batch_id = stock_batch_id
        self.pack_size = pack_size
        self.location = location
        self.batch_no = batch_no
        self.expiry = expiry
        self.mrp = mrp
        self.sale_qty = sale_qty
        self.discount_amount = discount_amount
        self.amount = amount

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "stock_batch_id": self.stock_batch_id,
            "pack_size": self.pack_size,
            "location": self.location,
            "batch_no": self.batch_no,
            "expiry": self.expiry,
            "mrp": self.mrp,
            "sale_qty": self.sale_qty,
            "discount_amount": self.discount_amount,
            "amount": self.amount,
        }


# ======================================================================
# Item Entry Bar (top of sale form)
# ======================================================================

class _ItemEntryBar(QWidget):
    """Single horizontal row for selecting item, batch and sale quantity.

    All twelve controls (CNo, Item, Batch, Pack, Loc, Exp, MRP, Avail, Qty,
    Disc, Amount, + Add) live on ONE row in that order â€” there is no second
    detail row, so the bar costs one line of vertical space instead of two.

    Kept at a fixed compact height so the active sale-entry region can never
    drift or grow when items/history rows are added.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        _keep_alive(self)
        # Own deferred focus callbacks with this widget. Static
        # QTimer.singleShot callbacks can outlive a short-lived test/dialog
        # instance and otherwise call into deleted Qt controls.
        self._focus_batch_timer = QTimer(self)
        self._focus_batch_timer.setSingleShot(True)
        self._focus_batch_timer.timeout.connect(self._focus_batch)
        self._focus_quantity_timer = QTimer(self)
        self._focus_quantity_timer.setSingleShot(True)
        self.setObjectName("ItemEntryBar")
        self._draft_reserved_qty = lambda _batch_id: 0.0
        # The row sizes itself (see _refit_to_bar).  Off until the row has
        # been built and measured, then on for good; the Sales Bill popup
        # turns it off because it measures and pins its own widths.
        self._auto_fit = False
        self._in_refit = False
        # Batch's real floor: _ENTRY_FLOOR_WIDTHS, raised by
        # _reserve_batch_number_width when a batch number needs more room.
        self._batch_floor = _ENTRY_FLOOR_WIDTHS["batch_combo"]
        # One single horizontal row â€” the target billing-bar order:
        #   CNo | Item | Batch | Pack | Loc | Exp | MRP | Avail | Qty |
        #   Disc | Amount | + Add
        #
        # There is deliberately NO second row: the auto-filled details used
        # to sit underneath and wasted a whole line of vertical space.
        self.setFixedHeight(_ENTRY_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(1)

        # CNo (counter / current bill number â€” display only)
        layout.addWidget(self._lbl("CNo"))
        self.cno_label = QLabel("--")
        self.cno_label.setFixedWidth(110)
        self.cno_label.setAlignment(Qt.AlignCenter)
        self.cno_label.setStyleSheet(_LABEL_STYLE)
        self.cno_label.setFixedHeight(_ENTRY_BAR_HEIGHT - 8)
        layout.addWidget(self.cno_label)

        # Item â€” the widest field, capped at 300 px. The main search box, but not a
        # banner: on a 1920-wide monitor the width it does not take is shared
        # with the other fields so the bar fills evenly.
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("Item"))
        self.item_combo = _make_combo()
        self.item_combo.setStyleSheet(_ENTRY_COMBO_STYLE)
        _mark_cs(self.item_combo, "entry_combo")
        self._fit(self.item_combo, _ENTRY_FLOOR_WIDTHS["item_combo"],
                  _ENTRY_PREFERRED_WIDTHS["item_combo"])
        self.item_combo.setSizePolicy(QSizePolicy.Expanding,
                                      QSizePolicy.Fixed)
        self.item_combo.show_all_completions_on_click()
        self._item_completion_model = QStandardItemModel(self)
        self.item_combo.set_completion_model(
            self._item_completion_model, Qt.UserRole + 1
        )
        self._item_search_values: list[str] = []
        self._items_by_id: dict[int, dict] = {}
        self._has_no_match_row = False
        self.item_combo.lineEdit().textEdited.connect(
            self._on_item_search_text_changed
        )
        # Stretch weights: Item leads because it is the primary search field, but it
        # only takes a share of the spare width â€” Batch and the read-outs widen
        # too, so a wide monitor fills the bar evenly instead of turning Item
        # into a banner.  A trailing stretch keeps "+ Add" flush right once
        # every field has hit its maximum.
        layout.addWidget(self.item_combo, 3)

        # Batch â€” medium width: long batch numbers stay readable and the
        # light completion popup has room to show useful batch text.
        layout.addSpacing(_ENTRY_ITEM_BATCH_GAP)
        layout.addWidget(self._lbl("Batch"))
        self.batch_combo = _make_combo()
        self.batch_combo.setStyleSheet(_ENTRY_COMBO_STYLE)
        _mark_cs(self.batch_combo, "entry_combo")
        self._fit(self.batch_combo, _ENTRY_BATCH_MIN_WIDTH, _ENTRY_BATCH_MAX_WIDTH)
        self.batch_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.batch_combo.show_all_completions_on_click()
        layout.addWidget(self.batch_combo, 2)

        # Pack size (auto-filled)
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("Pack"))
        self.pack_edit = _make_edit("")
        self._fit(self.pack_edit, _ENTRY_FLOOR_WIDTHS["pack_edit"],
                  _ENTRY_PREFERRED_WIDTHS["pack_edit"])
        self.pack_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pack_edit.setReadOnly(True)
        layout.addWidget(self.pack_edit)

        # Location (from item master)
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("Loc"))
        self.location_edit = _make_edit("")
        self._fit(self.location_edit, _ENTRY_FLOOR_WIDTHS["location_edit"],
                  _ENTRY_PREFERRED_WIDTHS["location_edit"])
        self.location_edit.setReadOnly(True)
        layout.addWidget(self.location_edit, 1)

        # Expiry (auto-filled)
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("Exp"))
        self.expiry_edit = _make_edit("")
        self._fit(self.expiry_edit, _ENTRY_FLOOR_WIDTHS["expiry_edit"],
                  _ENTRY_PREFERRED_WIDTHS["expiry_edit"])
        self.expiry_edit.setAlignment(Qt.AlignCenter)
        self.expiry_edit.setReadOnly(True)
        layout.addWidget(self.expiry_edit, 1)

        # MRP (auto-filled)
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("MRP"))
        self.mrp_edit = _make_edit("")
        self._fit(self.mrp_edit, _ENTRY_FLOOR_WIDTHS["mrp_edit"],
                  _ENTRY_PREFERRED_WIDTHS["mrp_edit"])
        self.mrp_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mrp_edit.setReadOnly(True)
        layout.addWidget(self.mrp_edit, 1)

        # Batch stock (auto-filled)
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("Avail"))
        self.stock_edit = _make_edit("")
        self._fit(self.stock_edit, _ENTRY_FLOOR_WIDTHS["stock_edit"],
                  _ENTRY_PREFERRED_WIDTHS["stock_edit"])
        self.stock_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.stock_edit.setReadOnly(True)
        layout.addWidget(self.stock_edit, 1)

        # Sale Qty
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("Qty"))
        self.qty_edit = _make_edit("1")
        self._focus_quantity_timer.timeout.connect(self.qty_edit.setFocus)
        self._fit(self.qty_edit, _ENTRY_FLOOR_WIDTHS["qty_edit"],
                  _ENTRY_PREFERRED_WIDTHS["qty_edit"])
        self.qty_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.qty_edit)

        # Discount
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("Disc"))
        self.discount_edit = _make_edit("0.00")
        self._fit(self.discount_edit, _ENTRY_FLOOR_WIDTHS["discount_edit"],
                  _ENTRY_PREFERRED_WIDTHS["discount_edit"])
        self.discount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.discount_edit, 1)

        # Calculated line amount (auto-filled)
        layout.addSpacing(_ENTRY_GROUP_GAP)
        layout.addWidget(self._lbl("Amt"))
        self.amount_edit = _make_edit("")
        self._fit(self.amount_edit, _ENTRY_FLOOR_WIDTHS["amount_edit"],
                  _ENTRY_PREFERRED_WIDTHS["amount_edit"])
        self.amount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.amount_edit.setReadOnly(True)
        layout.addWidget(self.amount_edit, 1)

        # Absorb any width left over once every field hit its maximum, so
        # the Add button always stays flush against the right edge.
        layout.addStretch(1)

        # Add button â€” compact, same box height as the entry controls.
        self.add_btn = QPushButton("+ Add")
        self.add_btn.setStyleSheet(_BTN_GREEN_SM)
        self.add_btn.setFixedWidth(_ENTRY_ADD_WIDTH)
        self.add_btn.setMinimumHeight(_ENTRY_BAR_HEIGHT - 8)
        layout.addWidget(self.add_btn)

        # All entry controls share one box height, whatever the platform's
        # native control metrics turn out to be (a Windows combo renders
        # one pixel taller than a styled line edit).
        self._unify_control_heights()

        # Read-only fields must never steal the keyboard chain.
        for widget in (self.cno_label, self.pack_edit, self.location_edit,
                       self.expiry_edit, self.mrp_edit, self.stock_edit,
                       self.amount_edit):
            widget.setFocusPolicy(Qt.NoFocus)

        self.item_combo.completionAccepted.connect(self._focus_batch)
        self.batch_combo.completionAccepted.connect(self._focus_quantity)
        self.qty_edit.returnPressed.connect(self._activate_add)
        self.discount_edit.returnPressed.connect(self._activate_add)
        self._focus_order = (
            self.item_combo, self.batch_combo, self.qty_edit,
            self.discount_edit, self.add_btn,
        )
        # Tab order is declared on the combo widgets (the real focus
        # targets).  Their line edits are focus proxies and are skipped by
        # focus traversal, so naming them here would drop the batch combo
        # out of the chain entirely.
        self.setTabOrder(self.item_combo, self.batch_combo)
        self.setTabOrder(self.batch_combo, self.qty_edit)
        self.setTabOrder(self.qty_edit, self.discount_edit)
        self.setTabOrder(self.discount_edit, self.add_btn)

        # Wire signals
        self.item_combo.currentIndexChanged.connect(self._on_item_changed)
        self.batch_combo.currentIndexChanged.connect(self._on_batch_changed)
        self.qty_edit.textChanged.connect(self._refresh_amount_preview)
        self.discount_edit.textChanged.connect(self._refresh_amount_preview)
        self.pack_edit.textChanged.connect(self._refresh_amount_preview)
        self.mrp_edit.textChanged.connect(self._refresh_amount_preview)

        # The row is built and measured: from here on it keeps itself fitting
        # the bar.  Enabled last so the first fit sees the finished row.
        self._auto_fit = True
        self._refit_to_bar()

    # ------------------------------------------------------------------
    # Responsive width fitting
    # ------------------------------------------------------------------

    def set_auto_fit(self, enabled: bool) -> None:
        """Turn the row's own width fitting on or off.

        The Sales Bill popup measures and pins its entry widths itself, so it
        turns this off to keep them.  The Counter Sale screen leaves it on,
        which is what keeps its row inside the bar at every window size.
        """
        self._auto_fit = enabled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_auto_fit", False):
            self._refit_to_bar()

    def minimumSizeHint(self) -> QSize:
        """The bar may be squeezed: the row re-fits itself on every resize.

        The fields are pinned to a partition of the bar's current width,
        which is what keeps them on one line.  Left at that, the bar's own
        minimum size would equal its current size and the window could never
        be made narrower.  Reporting a small minimum keeps the window
        resizable, and ``_refit_to_bar`` recomputes the partition for
        whatever width the bar is actually given.
        """
        width = max(_ENTRY_MIN_BAR_WIDTH, self._fixed_chrome_width())
        return QSize(width, _ENTRY_BAR_HEIGHT)

    def _flexible_fields(self) -> dict:
        """The ten fields the fitter shares width across, in row order."""
        return {
            "item_combo": self.item_combo,
            "batch_combo": self.batch_combo,
            "pack_edit": self.pack_edit,
            "location_edit": self.location_edit,
            "expiry_edit": self.expiry_edit,
            "mrp_edit": self.mrp_edit,
            "stock_edit": self.stock_edit,
            "qty_edit": self.qty_edit,
            "discount_edit": self.discount_edit,
            "amount_edit": self.amount_edit,
        }

    def _fixed_chrome_width(self) -> int:
        """Width the row spends before a flexible field is given a pixel.

        The CNo read-out and the "+ Add" button are pinned and every caption
        is a fixed-width label, so all of them are constant.  Only the seams
        and the layout's own spacing have to be added on top of them.  The
        captions are measured, never guessed, so the same arithmetic holds on
        any platform font.
        """
        layout = self.layout()
        if layout is None:
            return 0
        flexible = set(self._flexible_fields().values())
        margins = layout.contentsMargins()
        total = (layout.spacing() * max(layout.count() - 1, 0)
                 + margins.left() + margins.right())
        for index in range(layout.count()):
            item = layout.itemAt(index)
            spacer = item.spacerItem()
            if spacer is not None:
                total += spacer.sizeHint().width()
                continue
            widget = item.widget()
            if widget is None or widget in flexible:
                continue
            total += widget.minimumWidth()
        return total

    def _share_row_width(self, room: int) -> dict:
        """Partition ``room`` px across the flexible fields.

        Every field starts on its floor.  The surplus then goes to Item and
        then to Batch -- the two fields a cashier actually reads and types
        into -- up to their comfortable widths, and whatever is left widens
        the read-outs in proportion to the room each one still has to grow
        into.  When even the floors do not fit, the fields shrink together
        instead of the row printing past the edge of its bar.
        """
        floors = dict(_ENTRY_FLOOR_WIDTHS)
        floors["batch_combo"] = max(floors["batch_combo"], self._batch_floor)
        preferred = dict(_ENTRY_PREFERRED_WIDTHS)
        for name, floor in floors.items():
            preferred[name] = max(preferred[name], floor)
        names = list(floors)
        total_floor = sum(floors.values())
        if room < total_floor:
            return self._shrink_to_fit(room, floors)

        widths = dict(floors)
        surplus = room - total_floor
        for name in ("item_combo", "batch_combo"):
            if surplus <= 0:
                break
            grow = min(surplus, preferred[name] - widths[name])
            widths[name] += grow
            surplus -= grow

        grow_into = {name: preferred[name] - widths[name] for name in names}
        weight = sum(grow_into.values())
        if surplus > 0 and weight > 0:
            handed = 0
            for name in names:
                share = surplus * grow_into[name] // weight
                widths[name] += share
                handed += share
            # Rounding must not invent or lose a pixel of the bar.
            widths["item_combo"] += surplus - handed
        return widths

    @staticmethod
    def _shrink_to_fit(room: int, floors: dict) -> dict:
        """Shrink every field together when even the floors do not fit.

        The floors are what each field wants before it takes width from its
        neighbours.  If the bar is narrower than all of them together the row
        would otherwise print past its own right edge, so the fields shrink in
        proportion and stop at the size below which they could show nothing.
        """
        total = sum(floors.values())
        if total <= 0:
            return dict(floors)
        widths = {name: max(_ENTRY_MIN_DRAWABLE, floor * room // total)
                  for name, floor in floors.items()}
        # Clamping at the absolute floor can leave the partition a few pixels
        # long on a very narrow bar; take the remainder off the widest field
        # so the row still lands inside its own edge.
        overflow = sum(widths.values()) - room
        while overflow > 0:
            widest = max(widths, key=lambda name: widths[name])
            if widths[widest] <= _ENTRY_MIN_DRAWABLE:
                break
            taken = min(overflow, widths[widest] - _ENTRY_MIN_DRAWABLE)
            widths[widest] -= taken
            overflow -= taken
        return widths

    def _refit_to_bar(self) -> None:
        """Share the bar's real width across the row whenever it changes."""
        if self._in_refit or self.layout() is None or self.width() <= 0:
            return
        self._in_refit = True
        try:
            room = self.width() - self._fixed_chrome_width()
            widths = self._share_row_width(room)
            for name, widget in self._flexible_fields().items():
                width = widths[name]
                if (widget.minimumWidth() == width
                        and widget.maximumWidth() == width):
                    continue
                self._fit(widget, width, width)
        finally:
            self._in_refit = False

    def _unify_control_heights(self) -> None:
        """Pin every entry-bar control to one shared box height.

        A styled ``QComboBox`` reports a different natural height from a
        styled ``QLineEdit`` on some platforms (Windows renders the combo
        one pixel taller).  Rather than hard-coding a number that would be
        wrong on another machine, take the tallest natural height the
        widgets ask for and pin them all to it, so the bar reads as a
        single straight row.
        """
        widgets = (
            self.cno_label, self.item_combo, self.batch_combo,
            self.pack_edit, self.location_edit, self.expiry_edit,
            self.mrp_edit, self.stock_edit, self.qty_edit,
            self.discount_edit, self.amount_edit, self.add_btn,
        )
        height = max(widget.sizeHint().height() for widget in widgets)
        for widget in widgets:
            widget.setFixedHeight(height)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_ENTRY_CAPTION_STYLE)
        # The caption box is exactly its own text plus the gap that keeps it
        # clear of the field it names, measured from the real font.  The old
        # box reserved ``advance + 3`` and then ate 10 px of it back as a
        # content margin, which clipped "Batch" / "Avail" / "MRP" and left
        # every caption looking welded to its box.  Nothing is reserved for
        # padding now, so the text always fits and the gap is always shown.
        font = readable_font(TYPE_FORM_LABEL, bold=True)
        lbl.setFont(font)
        width = min(QFontMetrics(font).horizontalAdvance(text)
                    + _ENTRY_LABEL_GAP,
                    _ENTRY_LABEL_MAX_WIDTH)
        lbl.setFixedWidth(width)
        lbl.setContentsMargins(0, 0, 0, 0)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return lbl

    @staticmethod
    def _fit(widget, minimum: int, maximum: int) -> None:
        """Clamp a field into ``[minimum, maximum]``.

        Every field of the single entry row is clamped instead of left free:
        the compact read-outs can never be squeezed out of existence, nothing
        is allowed to grow past its preferred width, and only *Item* keeps an
        open maximum so it is always the widest control and the first one to
        give up space at narrow window sizes.
        """
        widget.setMinimumWidth(minimum)
        widget.setMaximumWidth(maximum)

    def _reserve_batch_number_width(self, batch_numbers) -> None:
        """Keep the Batch field wide enough to show a whole batch number.

        The combo's caption is ``"<batch> | Exp: .. | MRP: .. | Avail: .."``,
        so the tail is elided on purpose and the popup carries the detail.  A
        narrower field than the batch number itself, though, hides part of
        the one value the field exists to show.  The floor is measured from
        the real entry font and the combo's own chrome rather than guessed,
        and only ever grows, so the row cannot twitch as the user moves from
        one item to the next.
        """
        metrics = QFontMetrics(readable_font(TYPE_INPUT))
        widest = max((metrics.horizontalAdvance(str(number))
                      for number in batch_numbers), default=0)
        needed = widest + _ENTRY_BATCH_CHROME
        floor = min(max(needed, _ENTRY_BATCH_MIN_WIDTH), _ENTRY_BATCH_MAX_WIDTH)
        if floor > self._batch_floor:
            self._batch_floor = floor
            if self.batch_combo.minimumWidth() < floor:
                self.batch_combo.setMinimumWidth(floor)
            if self._auto_fit:
                self._refit_to_bar()

    def load_items(self):
        self.item_combo.blockSignals(True)
        self.item_combo.clear()
        self._item_completion_model.clear()
        self._item_search_values.clear()
        self._items_by_id.clear()
        self._has_no_match_row = False
        self.item_combo.addItem("-- Select --", None)
        items = ItemDAO.get_all()
        for it in items:
            item_name = it["item_name"]
            generic_name = it.get("generic_name", "") or ""
            product_code = it.get("product_code", it.get("item_code", "")) or ""
            search_value = " ".join((item_name, generic_name, product_code)).strip()
            self.item_combo.addItem(item_name, it["id"])
            self._items_by_id[it["id"]] = it
            completion_item = QStandardItem(item_name)
            completion_item.setData(it["id"], Qt.UserRole)
            completion_item.setData(search_value, Qt.UserRole + 1)
            self._item_completion_model.appendRow(completion_item)
            self._item_search_values.append(search_value.casefold())
        self.item_combo.blockSignals(False)
        self.item_combo.setCurrentIndex(0)
        self.item_combo.lineEdit().setPlaceholderText("Search products")
        self.item_combo.lineEdit().clear()

    def _on_item_search_text_changed(self, text: str):
        query = text.strip()
        if self._has_no_match_row:
            self._item_completion_model.removeRow(
                self._item_completion_model.rowCount() - 1
            )
            self._has_no_match_row = False
        if query and not any(query.casefold() in value for value in self._item_search_values):
            status = QStandardItem("No products found")
            status.setData(None, Qt.UserRole)
            status.setData(query, Qt.UserRole + 1)
            self._item_completion_model.appendRow(status)
            self._has_no_match_row = True
        completer = self.item_combo.completer()
        completer.setCompletionPrefix(text)
        if text:
            completer.complete()

    def set_draft_reservation_provider(self, provider):
        """Set ``provider(batch_id) -> reserved quantity`` for this draft."""
        self._draft_reserved_qty = provider or (lambda _batch_id: 0.0)

    def _availability(self, batch: dict) -> tuple[float, float]:
        stock = float(batch.get("stock_qty", 0.0) or 0.0)
        reserved = max(0.0, float(self._draft_reserved_qty(batch["id"]) or 0.0))
        return reserved, max(0.0, stock - reserved)

    def _refresh_amount_preview(self):
        if self.batch_combo.currentData() is None:
            self.amount_edit.clear()
            return
        quantity = _safe_float(self.qty_edit.text())
        mrp = _safe_float(self.mrp_edit.text())
        pack_text = self.pack_edit.text().strip()
        pack_size = int(pack_text) if pack_text.isdigit() else 1
        if quantity <= 0 or pack_size <= 0 or not math.isfinite(quantity):
            self.amount_edit.clear()
            return
        discount = _safe_float(self.discount_edit.text())
        amount = _round2(quantity * mrp / pack_size - discount)
        self.amount_edit.setText(f"{amount:.2f}")

    def _on_item_changed(self, idx: int, focus_batch: bool = True):
        item_id = self.item_combo.currentData()
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self.pack_edit.clear()
        self.location_edit.clear()
        self.expiry_edit.clear()
        self.mrp_edit.clear()
        self.stock_edit.clear()
        self.amount_edit.clear()
        if item_id is None:
            self.batch_combo.blockSignals(False)
            return
        item = self._items_by_id.get(item_id, {})
        self.location_edit.setText(item.get("location", "") or "")

        # Load available batches
        batches = SalesDAO.get_stock_batches_for_item(item_id)
        # A real batch number must never be elided by its own field.
        self._reserve_batch_number_width(b.get("batch_no", "") for b in batches)
        self.batch_combo.addItem("-- Select Batch --", None)
        for b in batches:
            exp = b.get("expiry", "")
            reserved, available = self._availability(b)
            suffix = f" | Bill: {reserved:.0f}" if reserved else ""
            label = (
                f"{b['batch_no']} | Exp: {exp} | MRP: {b.get('mrp', 0.0):.2f} "
                f"| Avail: {available:.0f}{suffix}"
            )
            self.batch_combo.addItem(label, b["id"])
        self.batch_combo.blockSignals(False)
        if item_id is not None and focus_batch:
            self._focus_batch_timer.start(0)

    def _focus_batch(self):
        self.batch_combo.lineEdit().setFocus()
        if self.batch_combo.count() > 2:
            self.batch_combo._show_completion_popup()

    def _focus_quantity(self):
        self.qty_edit.selectAll()
        self._focus_quantity_timer.start(0)

    def _activate_add(self):
        self.add_btn.click()

    def _on_batch_changed(self, idx: int):
        batch_id = self.batch_combo.currentData()
        if batch_id is None:
            self.pack_edit.clear()
            self.expiry_edit.clear()
            self.mrp_edit.clear()
            self.stock_edit.clear()
            return
        batch = SalesDAO.get_batch_by_id(batch_id)
        if batch:
            self.pack_edit.setText(batch.get("pack_size", ""))
            item = self._items_by_id.get(self.item_combo.currentData(), {})
            self.location_edit.setText(
                batch.get("location") or item.get("location", "") or ""
            )
            self.expiry_edit.setText(batch.get("expiry", ""))
            self.mrp_edit.setText(f"{batch.get('mrp', 0.0):.2f}")
            reserved, available = self._availability(batch)
            self.stock_edit.setText(f"{available:.0f}")
            self.stock_edit.setToolTip(
                f"Stored: {batch.get('stock_qty', 0.0):.0f} | "
                f"In bill: {reserved:.0f} | Available: {available:.0f}"
            )

    def refresh_draft_availability(self):
        """Refresh selected batch details and batch-popup labels after a draft change."""
        item_id = self.item_combo.currentData()
        batch_id = self.batch_combo.currentData()
        if item_id is None:
            return
        self._on_item_changed(self.item_combo.currentIndex(), focus_batch=False)
        idx = self.batch_combo.findData(batch_id)
        if idx >= 0:
            self.batch_combo.setCurrentIndex(idx)

    def clear(self):
        self.item_combo.setCurrentIndex(0)
        self.item_combo.lineEdit().clear()
        self.batch_combo.clear()
        self.pack_edit.clear()
        self.location_edit.clear()
        self.expiry_edit.clear()
        self.mrp_edit.clear()
        self.stock_edit.clear()
        self.amount_edit.clear()
        self.qty_edit.setText("1")
        self.discount_edit.setText("0.00")

    def set_cno(self, text: str):
        """Display the current counter/bill number (no logic attached).

        Shows the provisional CNo preview (regular bill-number format)
        or the saved CNo.  Long values elide with the full number in
        the tooltip, so the row never overflows its slot.
        """
        full = text or "--"
        try:
            fm = QFontMetrics(self.cno_label.font())
            elided = fm.elidedText(full, Qt.ElideRight, max(40, self.cno_label.width()))
        except Exception:
            elided = full
        self.cno_label.setText(elided)
        self.cno_label.setToolTip(full)

    def get_current_data(self) -> dict | None:
        item_index = self.item_combo.currentIndex()
        item_id = self.item_combo.currentData()
        if (item_id is None or item_index < 0 or
                self.item_combo.currentText() != self.item_combo.itemText(item_index)):
            return None
        batch_index = self.batch_combo.currentIndex()
        batch_id = self.batch_combo.currentData()
        if (batch_id is None or batch_index < 0 or
                self.batch_combo.currentText() != self.batch_combo.itemText(batch_index)):
            return None
        batch = SalesDAO.get_batch_by_id(batch_id)
        if not batch:
            return None
        return {
            "item_id": item_id,
            "item_name": self.item_combo.currentText(),
            "stock_batch_id": batch_id,
            "pack_size": batch.get("pack_size", ""),
            "location": batch.get("location") or self.location_edit.text(),
            "batch_no": batch["batch_no"],
            "expiry": batch.get("expiry", ""),
            "mrp": batch.get("mrp", 0.0),
            "sale_qty": _safe_float(self.qty_edit.text(), 0.0),
            "discount_amount": _safe_float(self.discount_edit.text()),
            "batch_stock": batch.get("stock_qty", 0.0),
            "draft_qty": self._availability(batch)[0],
            "available_stock": self._availability(batch)[1],
        }

    def refresh_theme(self) -> None:
        """Re-apply live Day/Night colours in place (state preserved)."""
        try:
            p = palette()
        except Exception:
            return
        try:
            # Entry combos keep their entry metrics; edits keep theirs.
            self.item_combo.refresh_theme()
        except Exception:
            pass
        try:
            self.batch_combo.refresh_theme()
        except Exception:
            pass
        for edit in (self.pack_edit, self.location_edit, self.expiry_edit,
                     self.mrp_edit, self.stock_edit, self.qty_edit,
                     self.discount_edit, self.amount_edit):
            try:
                edit.setStyleSheet(_fresh_edit_style(p))
            except Exception:
                pass
        try:
            self.cno_label.setStyleSheet(
                f"color: {p['text']}; font-size: {TYPE_VALUE}px; font-weight: bold;"
                f"font-family: {FONT_FAMILY}; background: transparent;"
            )
        except Exception:
            pass
        try:
            self.add_btn.setStyleSheet(_fresh_btn_style(p["accent"], p,
                                                        padding="4px 10px", radius="4px"))
        except Exception:
            pass
        try:
            refresh_cs_tree(self)
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass


# ======================================================================
# Multiple-bill provisional numbering
# ======================================================================
# Each open bill shows a unique provisional CNo in the regular financial-
# year bill-number format (e.g. CS-0007).  Provisionals live in memory
# only: they never create invoice records and never consume permanent
# numbers.  The stable internal draft id (an int) is kept separately and
# is never shown in the billing UI.  At Save the provisional is validated
# against the database; a conflicting preview is replaced by the next
# free number, so sequential saves can never share one permanent CNo.


def _increment_bill_no(bill_no: str) -> str:
    """Next bill number after *bill_no*, same prefix/width convention."""
    text = (bill_no or '').strip() or 'CS-0000'
    idx = text.rfind('-')
    if idx >= 0:
        prefix, num_part = text[:idx + 1], text[idx + 1:]
    else:
        prefix, num_part = 'CS-', text
    try:
        num = int(num_part) + 1
    except ValueError:
        num = 1
    width = max(4, len(num_part) if num_part.isdigit() else 4)
    return f"{prefix}{num:0{width}d}"


def _resolve_bill_no_for_save(provisional: str) -> str:
    """Permanent CNo to commit for a draft showing *provisional*.

    If the provisional preview is still free in the database, keep it so that
    other open drafts' previews are not displaced.  If it is already taken
    (e.g. another session committed the same number), fall back to the next
    sequential number from committed invoices.
    """
    candidate = (provisional or '').strip()
    # Use the provisional when it is valid and not yet committed.
    if candidate and not SalesDAO.bill_no_exists(candidate):
        return candidate
    # Provisional is empty or already taken — allocate the next free number.
    candidate = SalesDAO.generate_next_bill_no()
    try:
        guard = 0
        while SalesDAO.bill_no_exists(candidate) and guard < 10000:
            candidate = _increment_bill_no(candidate)
            guard += 1
    except Exception:
        candidate = SalesDAO.generate_next_bill_no()
    return candidate


def _is_provisional_state(state: dict | None) -> bool:
    """True when a stored draft snapshot still carries a provisional CNo."""
    if not state:
        return True
    try:
        return bool(state.get('provisional_bill_no', False))
    except Exception:
        return False


# ======================================================================
# Sale Dialog
# ======================================================================

class _SalePanel(QWidget):
    """Inline counter-sale entry panel (Regions B + C of the page layout).

    Owns the same widgets, validation and DAO calls that previously lived
    inside the modal ``_SaleDialog``.  The only change is *who hosts the
    widgets*: the Counter Sale page now embeds this panel directly under
    the history region so the active sale area is always in a fixed
    position.  No transaction logic was changed.

    Layout (top â†’ bottom):
        item entry bar  â†’  current bill table  â†’  bill/customer details
        â†’  totals + actions
    """

    saved = Signal()
    held = Signal()
    cancelled = Signal()
    totals_changed = Signal(str, str, str)  # bill_no, amount, bill_total

    def __init__(self, parent: QWidget | None = None, *,
                 invoice: dict | None = None,
                 hold_bill_data: dict | None = None,
                 popup_mode: bool = False):
        super().__init__(parent)
        _keep_alive(self)
        self._invoice = invoice
        self._hold_bill = hold_bill_data
        # Sales Bill popup layout only.  When true the sale header /
        # customer group are folded into one compact top strip so the popup
        # matches the reference arrangement; the inline Counter Sale panel
        # keeps its original footer layout untouched.
        self._popup_mode = popup_mode
        self._hold_bill_id: int | None = (
            hold_bill_data["hold"]["id"] if hold_bill_data else None
        )
        self._saved = False
        self._held = False
        # The Sales Bill review popup embeds its own panel; inside it
        # "Save Sale" is already the final step, so it commits instead of
        # opening another popup.
        self._in_review_popup = False
        # Re-entrancy / double-submit guard: a committed panel never commits
        # a second time, so a double-click cannot create two sales.
        self._commit_locked = False
        self._item_rows: list[_BillItemRow] = []
        # An edit has already deducted its original lines from stored stock.
        # Keep that quantity as an allowance while validating the draft; the
        # DAO's existing edit transaction restores old stock then applies the
        # replacement lines atomically on Save.
        self._original_batch_qty: dict[int, float] = {}
        # Other open Counter Sale drafts reserve stock in memory as well.
        # The page supplies this callback; it never writes stock.
        self._other_draft_reserved_qty = lambda _batch_id: 0.0
        self._provisional_bill_no = False
        # Contact number / address of each loaded customer, used by the
        # popup's read-only Cnt No and Address fields.
        self._customer_contacts: dict[int, str] = {}
        self._customer_addresses: dict[int, str] = {}

        self.setObjectName("SalePanel")
        self.setStyleSheet(
            f"#SalePanel {{ background-color: {_DARK_BG}; }}"
            f"#SalePanel QLabel {{ {_LABEL_STYLE} }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if self._popup_mode:
            # Reference arrangement for the Sales Bill popup: one compact
            # sale-header / customer strip at the top, then the existing
            # entry bar, bill table and totals below it.
            self._build_header(None)
            self._build_customer_bar(None)
            self._build_totals()
            top_strip = self._build_popup_top_strip()

        # -- Region B: active sale entry (directly below the history) --
        self._entry_bar = _ItemEntryBar()
        self._entry_bar.set_draft_reservation_provider(self._reserved_for_entry)
        self._entry_bar.load_items()
        root.addWidget(self._entry_bar)

        if self._popup_mode:
            self.apply_popup_entry_widths()

        # -- Region C: current bill table (gets the remaining space) --
        self._build_bill_table()
        root.addWidget(self._table_group, 1)

        if self._popup_mode:
            root.insertWidget(0, top_strip)
            root.addWidget(self._totals_widget)
        else:
            # Compact metadata replaces the former tall Sale Header /
            # Customer panels; the same field objects and data bindings
            # are retained.
            self._build_compact_sale_metadata()
            # The strip's fields (Bill No / Date / Time / Type and
            # Customer / Patient / Doctor) are no longer shown.  Every
            # field and binding is still built exactly as before, so
            # save / load / hold logic is untouched; the strip itself is
            # simply not displayed.
            root.addWidget(self._metadata_strip)
            self._metadata_strip.setVisible(False)

            # -- Totals + actions --
            self._build_totals()
            root.addWidget(self._totals_widget)

        # Wire add button
        self._entry_bar.add_btn.clicked.connect(self._on_add_item)

        # CNo display mirrors the current bill number (display only).
        self.bill_no_edit.textChanged.connect(self._entry_bar.set_cno)
        self.bill_no_edit.textChanged.connect(self._emit_totals)

        self._set_bill_no()
        self._set_current_datetime()
        self._entry_bar.set_cno(self.bill_no_edit.text())

        if self._popup_mode:
            self._refresh_customer_info()

        if invoice:
            self._populate_invoice(invoice)
        elif hold_bill_data:
            self._populate_hold_bill(hold_bill_data)

    # ------------------------------------------------------------------
    # Inline lifecycle helpers (reset / load)
    # ------------------------------------------------------------------

    def reset_for_new(self):
        """Reset the form for a brand-new sale (New Sale / after a save)."""
        self._invoice = None
        self._hold_bill = None
        self._hold_bill_id = None
        self._saved = False
        self._held = False
        self._commit_locked = False
        self._item_rows.clear()
        self._original_batch_qty.clear()
        self._refresh_table()
        self._set_bill_no()
        self._set_current_datetime()
        if self.sale_type_combo.count():
            self.sale_type_combo.setCurrentIndex(0)
        for index in range(self.customer_combo.count()):
            if self.customer_combo.itemText(index).upper() == "WALKIN":
                self.customer_combo.setCurrentIndex(index)
                break
        self.patient_name_edit.clear()
        if self.doctor_combo.count():
            self.doctor_combo.setCurrentIndex(0)
        self.bill_disc_edit.setText("0.00")
        self.paid_edit.setText("0.00")
        self._entry_bar.load_items()
        self._entry_bar.clear()
        self._recalc_totals()
        self._entry_bar.set_cno(self.bill_no_edit.text())

    def load_invoice(self, invoice: dict):
        """Load an existing sale into the inline area for editing."""
        self.reset_for_new()
        self._invoice = invoice
        self._populate_invoice(invoice)

    def load_hold(self, hold_bill_data: dict):
        """Load a held bill into the inline area for resume."""
        self.reset_for_new()
        self._hold_bill = hold_bill_data
        self._hold_bill_id = (
            hold_bill_data["hold"]["id"] if hold_bill_data else None
        )
        self._populate_hold_bill(hold_bill_data)

    def focus_item_name(self):
        """Put the keyboard focus on the Item Name entry."""
        self._entry_bar.item_combo.lineEdit().setFocus()

    # ------------------------------------------------------------------
    # Live draft stock (display/validation only; never writes stock)
    # ------------------------------------------------------------------

    def _draft_qty_for_batch(self, batch_id: int) -> float:
        return sum(r.sale_qty for r in self._item_rows if r.stock_batch_id == batch_id)

    def _reserved_for_entry(self, batch_id: int) -> float:
        """Quantity reserved by this unsaved draft for a batch.

        Existing invoice lines are excluded up to their original quantity:
        their stock will be restored by the established edit workflow before
        the replacement rows are applied on Save.
        """
        return reserved_quantity(
            self._draft_qty_for_batch(batch_id),
            self._original_batch_qty.get(batch_id, 0.0),
        ) + max(0.0, float(self._other_draft_reserved_qty(batch_id) or 0.0))

    def _available_for_batch(self, batch_id: int, stored_stock: float) -> float:
        own_reserved = reserved_quantity(
            self._draft_qty_for_batch(batch_id),
            self._original_batch_qty.get(batch_id, 0.0),
        )
        return max(0.0, float(stored_stock or 0.0) - own_reserved - max(
            0.0, float(self._other_draft_reserved_qty(batch_id) or 0.0)
        ))

    def set_other_draft_reservation_provider(self, provider) -> None:
        """Set ``provider(batch_id)`` for quantities in *other* open drafts."""
        self._other_draft_reserved_qty = provider or (lambda _batch_id: 0.0)
        self._refresh_draft_availability()

    def set_provisional_bill_no(self, preview: str) -> None:
        """Display an in-memory provisional CNo preview.

        The preview uses the regular bill-number format but reserves
        nothing: no invoice record is written and the permanent
        sequence is untouched until Save (see
        :func:`_resolve_bill_no_for_save`).
        """
        self._provisional_bill_no = True
        self.bill_no_edit.setText(preview)
        try:
            self.bill_no_edit.setToolTip(preview)
        except Exception:
            pass
        self._entry_bar.set_cno(preview)

    def _refresh_draft_availability(self):
        self._entry_bar.refresh_draft_availability()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self, parent_layout):
        grp = QGroupBox("Sale Header")
        grp.setStyleSheet(_GROUP_BOX)
        grp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        grp.setFixedHeight(54)
        grid = QGridLayout(grp)
        grid.setSpacing(10)
        grid.setContentsMargins(8, 14, 8, 4)

        row = 0
        grid.addWidget(self._lbl("Bill No"), row, 0)
        self.bill_no_edit = _make_edit()
        self.bill_no_edit.setReadOnly(True)
        grid.addWidget(self.bill_no_edit, row, 1)

        grid.addWidget(self._lbl("Date"), row, 2)
        self.sale_date = _make_date()
        self.sale_date.setMaximumWidth(130)
        grid.addWidget(self.sale_date, row, 3)

        grid.addWidget(self._lbl("Time"), row, 4)
        self.sale_time_edit = _make_edit()
        self.sale_time_edit.setMaximumWidth(80)
        grid.addWidget(self.sale_time_edit, row, 5)

        grid.addWidget(self._lbl("Type"), row, 6)
        self.sale_type_combo = _make_combo()
        self.sale_type_combo.addItems(["Cash", "Credit", "Credit Card"])
        self.sale_type_combo.setMaximumWidth(110)
        grid.addWidget(self.sale_type_combo, row, 7)

        # A None parent layout builds the widgets without showing the group
        # box: the Sales Bill popup places these same widgets in its own top
        # strip instead of repeating the section at the bottom.
        if parent_layout is not None:
            parent_layout.addWidget(grp)
        else:
            # Popup mode: the group box is not shown, but it owns the Bill
            # No / Date / Time widgets, so it must stay referenced.
            self._sale_header_group = grp

    def _build_customer_bar(self, parent_layout):
        grp = QGroupBox("Customer / Doctor")
        grp.setStyleSheet(_GROUP_BOX)
        grp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        grp.setFixedHeight(54)
        grid = QGridLayout(grp)
        grid.setSpacing(10)
        grid.setContentsMargins(8, 14, 8, 4)

        row = 0
        grid.addWidget(self._lbl("Customer *"), row, 0)
        self.customer_combo = _make_combo()
        self.customer_combo.setMinimumWidth(200)
        grid.addWidget(self.customer_combo, row, 1)

        grid.addWidget(self._lbl("Patient Name"), row, 2)
        self.patient_name_edit = _make_edit()
        grid.addWidget(self.patient_name_edit, row, 3)

        grid.addWidget(self._lbl("Doctor"), row, 4)
        self.doctor_combo = _make_combo()
        self.doctor_combo.setMinimumWidth(160)
        grid.addWidget(self.doctor_combo, row, 5)

        if parent_layout is not None:
            parent_layout.addWidget(grp)
        else:
            # Popup mode: Customer / Patient / Doctor are re-parented into
            # the top strip, so the hidden box only needs to stay alive.
            self._customer_group = grp
        self._load_customers()
        self._load_doctors()


    def _build_popup_top_strip(self) -> QWidget:
        """Top sale-header strip of the Sales Bill popup.

        ROW 1 (Header): Voucher No | Date | Time
        ROW 2 (Three-column form):
          LEFT:   Cnt No / Type
          MIDDLE: Customer * / Patient Name / Address
          RIGHT:  Doctor / Discount / Paid Amount

        Uses QGridLayout for stable, responsive layout with proper spacing.
        """
        strip = QWidget()
        strip.setObjectName("SalesBillTopStrip")
        strip.setStyleSheet(
            f"#SalesBillTopStrip {{ background-color: {_SURFACE};"
            f"  border-bottom: 1px solid {_BORDER}; }}"
        )
        strip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Discount and Paid Amount are the panel's own bill-discount / paid
        # boxes. In the popup they are built here instead of in the totals
        # row, so each widget exists exactly once.
        self.bill_disc_edit = _make_edit("0.00")
        self.paid_edit = _make_edit("0.00")

        # Main vertical layout for the strip
        main_layout = QVBoxLayout(strip)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(6)

        # ============================================================
        # ROW 1: Voucher No | Date | Time (horizontal alignment)
        # ============================================================
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        # Voucher No
        voucher_layout = QHBoxLayout()
        voucher_layout.setSpacing(6)
        voucher_layout.addWidget(self._lbl("Voucher No"))
        self.voucher_no_label = QLabel(self.bill_no_edit.text() or "--")
        self.voucher_no_label.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        # Draft previews ("Draft 12 -- Assigned on Save") need room: 230 px
        # keeps the full identifier readable; tooltip carries it as well.
        self.voucher_no_label.setMinimumWidth(230)
        try:
            self.voucher_no_label.setToolTip(self.bill_no_edit.text() or "--")
        except Exception:
            pass
        voucher_layout.addWidget(self.voucher_no_label)
        header_row.addLayout(voucher_layout)

        # Date
        date_layout = QHBoxLayout()
        date_layout.setSpacing(6)
        date_layout.addWidget(self._lbl("Date"))
        self.header_date_label = QLabel(self.sale_date.date().toString("dd-MM-yyyy"))
        self.header_date_label.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self.header_date_label.setMinimumWidth(100)
        date_layout.addWidget(self.header_date_label)
        header_row.addLayout(date_layout)

        # Time
        time_layout = QHBoxLayout()
        time_layout.setSpacing(6)
        time_layout.addWidget(self._lbl("Time"))
        self.header_time_label = QLabel(self.sale_time_edit.text() or "--")
        self.header_time_label.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self.header_time_label.setMinimumWidth(80)
        time_layout.addWidget(self.header_time_label)
        header_row.addLayout(time_layout)

        header_row.addStretch(1)
        main_layout.addLayout(header_row)

        # ============================================================
        # ROW 2: Three-column form layout (proven three-grid structure)
        # ============================================================
        form_row = QHBoxLayout()
        form_row.setSpacing(10)  # Match original outer spacing

        # ---- LEFT COLUMN: Cnt No / Type ----
        left = QGridLayout()
        left.setHorizontalSpacing(10)
        left.setVerticalSpacing(2)
        left.addWidget(self._lbl("Cnt No"), 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.cnt_no_edit = _make_edit()
        self.cnt_no_edit.setReadOnly(True)
        _ItemEntryBar._fit(self.cnt_no_edit, 55, 90)  # Match original
        left.addWidget(self.cnt_no_edit, 0, 1)
        left.addWidget(self._lbl("Type"), 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.sale_type_combo.setMinimumWidth(110)
        left.addWidget(self.sale_type_combo, 1, 1)
        form_row.addLayout(left)  # No stretch - fixed width

        # ---- MIDDLE COLUMN: Customer / Patient Name / Address ----
        centre = QGridLayout()
        centre.setHorizontalSpacing(10)
        centre.setVerticalSpacing(2)
        centre.addWidget(self._lbl("Customer *"), 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.customer_combo.setMinimumWidth(200)
        centre.addWidget(self.customer_combo, 0, 1)
        centre.addWidget(self._lbl("Patient Name"), 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        plain_patient = self.patient_name_edit
        patient = _DBLookupCombo(
            _patient_name_options, placeholder="Search patient name", width=260,
        )
        self.patient_name_edit = patient
        plain_patient.setParent(None)
        plain_patient.deleteLater()
        centre.addWidget(patient, 1, 1)
        centre.addWidget(self._lbl("Address"), 2, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.address_edit = _DBLookupCombo(
            _address_options, placeholder="Search saved address", width=300,
        )
        centre.addWidget(self.address_edit, 2, 1)
        centre.setColumnStretch(1, 1)  # Stretch fields within centre grid

        # Wrap the middle section so it shares the available width evenly
        # with the right section. Keeping both sections at the same stretch
        # factor prevents a blank band between Address and Doctor.
        centre_container = QWidget()
        centre_container.setLayout(centre)
        form_row.addWidget(centre_container, 1)

        # ---- RIGHT COLUMN: Doctor / Discount / Paid Amount ----
        right = QGridLayout()
        right.setHorizontalSpacing(10)
        right.setVerticalSpacing(2)
        doctor_label = self._lbl("Doctor")
        doctor_label.setMinimumWidth(121)
        right.addWidget(doctor_label, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self._make_doctor_lookup()
        self.doctor_combo.setMinimumWidth(190)
        right.addWidget(self.doctor_combo, 0, 1)
        discount_label = self._lbl("Discount")
        discount_label.setMinimumWidth(121)
        right.addWidget(discount_label, 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.bill_disc_edit.setMinimumWidth(100)
        self.bill_disc_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right.addWidget(self.bill_disc_edit, 1, 1)
        paid_label = self._lbl("Paid Amount")
        paid_label.setMinimumWidth(121)
        right.addWidget(paid_label, 2, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.paid_edit.setMinimumWidth(100)
        self.paid_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right.addWidget(self.paid_edit, 2, 1)
        right.setColumnStretch(1, 1)  # Stretch right fields
        form_row.addLayout(right, 1)

        main_layout.addLayout(form_row)

        # Discount / Paid recalculate through the same wiring as the panel.
        self.bill_disc_edit.textChanged.connect(self._recalc_totals)
        self.paid_edit.textChanged.connect(self._recalc_totals)

        # Cnt No / Address follow the selected customer.
        self.customer_combo.currentIndexChanged.connect(self._refresh_customer_info)

        # Keep voucher/date/time labels in sync with edits
        self.bill_no_edit.textChanged.connect(self._update_header_labels)
        self.sale_date.dateChanged.connect(self._update_header_labels)
        self.sale_time_edit.textChanged.connect(self._update_header_labels)

        return strip

    def _update_header_labels(self):
        """Keep the header row labels in sync with the editable fields."""
        if hasattr(self, 'voucher_no_label'):
            self.voucher_no_label.setText(self.bill_no_edit.text() or "--")
            try:
                self.voucher_no_label.setToolTip(self.bill_no_edit.text() or "--")
            except Exception:
                pass
        if hasattr(self, 'header_date_label'):
            self.header_date_label.setText(self.sale_date.date().toString("dd-MM-yyyy"))
        if hasattr(self, 'header_time_label'):
            self.header_time_label.setText(self.sale_time_edit.text() or "--")

    def apply_popup_entry_widths(self, available_width: int | None = None):
        """Size the popup's single Item Entry row so nothing overlaps.

        The row keeps its existing order, widgets, labels and behaviour â€”
        CNo, Item, Batch, Pack, Loc, Exp, MRP, Avail, Qty, Disc, Amt, + Add.
        Twelve fields plus their labels are simply wider than the popup, so
        instead of fixed guesses this measures what the row's labels, gaps
        and margins already consume and shares the rest across the fields in
        proportion to their comfortable sizes.  The sum is forced to the
        remaining space, so the row always lands on exactly one line with
        every field clear of its neighbour.

        Sizing stays inside Qt's layout system (minimum == maximum width on
        each field); no widget is positioned by coordinates.

        The Counter Sale screen is untouched: it keeps the entry bar's own
        widths because this runs only in popup mode.
        """
        bar = self._entry_bar
        # The popup measures and pins these widths itself, so the row must
        # stop re-fitting them the moment a resize would undo this work.
        bar.set_auto_fit(False)
        layout = bar.layout()
        if available_width is None:
            available_width = bar.width()

        # What the row spends before any field: every label, every gap and
        # the bar's own margins.
        spent = (layout.spacing() * max(layout.count() - 1, 0)
                 + layout.contentsMargins().left()
                 + layout.contentsMargins().right())
        captions = 0
        for index in range(layout.count()):
            item = layout.itemAt(index)
            spacer = item.spacerItem()
            if spacer is not None:
                # The column seams are real spacer items.  The gap count
                # above only charges the layout's per-item spacing, so each
                # spacer's own width has to be measured too — otherwise the
                # fields would be sized as if the seams cost nothing.
                spent += spacer.sizeHint().width()
                continue
            widget = item.widget()
            if widget is bar.cno_label:
                # This label mirrors the whole bill number, so its sizeHint is
                # far wider than the slot it is given below.  Charge the slot,
                # not the text.
                spent += _POPUP_CNO_WIDTH
            elif isinstance(widget, QLabel):
                spent += widget.sizeHint().width()
                captions += 1

        # Comfortable size per field: (attribute, preferred width).
        preferred = (
            # (attribute, comfortable width, smallest usable width)
            ("item_combo", 280, 120),
            ("batch_combo", 150, 80),
            ("pack_edit", 70, 34),
            ("location_edit", 90, 40),
            ("expiry_edit", 105, 48),
            ("mrp_edit", 95, 44),
            ("stock_edit", 90, 40),
            ("qty_edit", 75, 34),
            ("discount_edit", 90, 40),
            ("amount_edit", 110, 50),
            ("add_btn", 85, 60),
        )
        total_preferred = sum(width for _, width, _floor in preferred)
        # Captions are pinned to their own text width below, so everything the
        # row has not already spent on labels and gaps belongs to the fields.
        room = max(0, available_width - spent)

        # Search fields and the Add button are the ones a user actually types
        # into or reads at length, so they are guaranteed a comfortable width
        # first; the compact read-outs share what is left.
        floors = {"item_combo": 200, "batch_combo": 100, "add_btn": 64}
        if room >= sum(floors.values()):
            widths = dict(floors)
            shared = room - sum(floors.values())
            weights = [(a, w) for a, w, _f in preferred if a not in floors]
            weight_total = sum(w for _, w in weights)
            for attribute, weight in weights:
                widths[attribute] = shared * weight // weight_total
            widths["item_combo"] += shared - sum(
                v for a, v in widths.items() if a not in floors
            )
        else:
            # Not even the comfortable widths fit: share everything evenly.
            widths = {a: room * w // total_preferred for a, w, _f in preferred}
        # Give the rounding remainder to the Item field so the row consumes
        # exactly the space that was measured.
        widths["item_combo"] += room - sum(widths.values())

        for attribute, comfortable, floor in preferred:
            widget = getattr(bar, attribute)
            width = widths[attribute]
            _ItemEntryBar._fit(widget, width, width)

        # CNo mirrors the bill number in its own narrow label, kept wide
        # enough for the number and narrow enough to stay out of Item's way.
        bar.cno_label.setMinimumWidth(_POPUP_CNO_WIDTH)
        bar.cno_label.setMaximumWidth(_POPUP_CNO_WIDTH)
        self._pin_popup_entry_captions()
        self._fit_popup_entry_row_to_width(available_width, preferred)

    def _fit_popup_entry_row_to_width(self, available_width: int,
                                      preferred) -> None:
        """Trim the Item field if the row still does not fit the window.

        The widths above are computed from measured label and gap sizes, but
        Qt's own rounding can leave the row a pixel or two long.  Rather than
        let a caption or a field be squeezed, the Item field â€” which has the
        most room to give â€” absorbs the difference, never dropping below its
        usable minimum.
        """
        bar = self._entry_bar
        layout = bar.layout()

        def required_width() -> int:
            total = (layout.spacing() * max(layout.count() - 1, 0)
                     + layout.contentsMargins().left()
                     + layout.contentsMargins().right())
            for index in range(layout.count()):
                item = layout.itemAt(index)
                spacer = item.spacerItem()
                if spacer is not None:
                    # Same reasoning as apply_popup_entry_widths: a seam is a
                    # real width the row has to fit, not a free gap.
                    total += spacer.sizeHint().width()
                    continue
                widget = item.widget()
                if widget is None:
                    continue
                if widget is bar.cno_label:
                    total += _POPUP_CNO_WIDTH
                elif isinstance(widget, QLabel):
                    total += widget.maximumWidth()
                else:
                    total += widget.maximumWidth()
            return total

        overflow = required_width() - available_width
        item = bar.item_combo
        floor = {attribute: smallest
                for attribute, _comfortable, smallest in preferred}["item_combo"]
        if overflow > 0:
            width = max(floor, item.maximumWidth() - overflow)
            _ItemEntryBar._fit(item, width, width)

    def _pin_popup_entry_captions(self):
        """Stop the row's captions being squeezed by the fields.

        Each caption is held at exactly the width its own text needs, which
        is what keeps a label from being clipped once the fields beside it
        have taken their share of the window.
        """
        bar = self._entry_bar
        for index in range(bar.layout().count()):
            widget = bar.layout().itemAt(index).widget()
            if isinstance(widget, QLabel) and widget is not bar.cno_label:
                width = widget.sizeHint().width()
                widget.setMinimumWidth(width)
                widget.setMaximumWidth(width)


    def _make_doctor_lookup(self):
        """Doctor becomes a click-to-open database dropdown in the popup.

        The rows stay exactly the doctors loaded from the ``doctors`` table
        (same ids, same order, ``-- None --`` placeholder first).  The popup
        only appends the specialty the table already stores, so the list is
        readable at a glance, and enables the same click-to-open list the
        item and batch fields use.  Selection keeps storing ``doctor_id``, so
        the saved bill is unchanged.
        """
        self.doctor_combo.show_all_completions_on_click(True)
        for row, doctor in enumerate(DoctorDAO.get_all()):
            specialty = (doctor.get("specialty") or "").strip()
            if not specialty:
                continue
            index = row + 1  # row 0 is the "-- None --" placeholder
            if index < self.doctor_combo.count():
                self.doctor_combo.setItemText(
                    index, f"{doctor['doctor_name']} - {specialty}"
                )

    def _refresh_customer_info(self, *_args):
        """Mirror the selected customer's contact number and address.

        Setting the address only replaces the text; the saved-address
        suggestions stay loaded, so the user can still pick another one.
        Patient and Doctor are never touched here.
        """
        if not hasattr(self, "cnt_no_edit"):
            return
        cid = self.customer_combo.currentData()
        self.cnt_no_edit.setText(self._customer_contacts.get(cid, ""))
        self.address_edit.setText(self._customer_addresses.get(cid, ""))

    def _remarks_text(self) -> str:
        """Bill remarks typed in the popup's Remarks box.

        Only the Sales Bill popup owns a Remarks box; everywhere else the
        stored remarks stay empty exactly as before.
        """
        box = getattr(self, "remarks_edit", None)
        return box.text().strip() if box is not None else ""


    def _build_compact_sale_metadata(self):
        """Small two-line metadata strip; no standalone Sale Header panel.

        Row 1 carries the bill identity (Bill No / Date / Time / Type) with
        balanced, content-sized widths and a trailing stretch.  Row 2 gives
        Customer / Patient / Doctor the full remaining width instead of
        forcing them through the same columns as row 1 â€” the two rows are
        independent, so neither row is squeezed by the other.
        """
        self._metadata_strip = QWidget()
        self._metadata_strip.setObjectName("CompactSaleMetadata")
        self._metadata_strip.setFixedHeight(_METADATA_STRIP_HEIGHT)
        self._metadata_strip.setStyleSheet(
            f"#CompactSaleMetadata {{ background-color: {_DARK_BG}; "
            f"border-top: 1px solid {_BORDER}; border-bottom: 1px solid {_BORDER}; }}"
        )
        outer = QVBoxLayout(self._metadata_strip)
        outer.setContentsMargins(8, 3, 8, 3)
        outer.setSpacing(2)

        # -- Row 1: bill identity ---------------------------------------
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(5)

        row1.addWidget(self._compact_lbl("Bill No"))
        self.bill_no_edit = _make_compact_edit(height=_METADATA_CONTROL_HEIGHT)
        self.bill_no_edit.setReadOnly(True)
        # Full FY bill numbers (e.g. "2026-2027-Cash-0015") and draft labels
        # ("Draft 12 — Assigned on Save") must read in full: a minimum width
        # (not fixed) lets the field grow with the row, and the tooltip always
        # carries the complete identifier.
        self.bill_no_edit.setMinimumWidth(250)
        self.bill_no_edit.setAlignment(Qt.AlignCenter)
        self.bill_no_edit.setToolTip(self.bill_no_edit.text())
        try:
            self.bill_no_edit.textChanged.connect(self.bill_no_edit.setToolTip)
        except Exception:
            pass
        row1.addWidget(self.bill_no_edit, 1)

        row1.addWidget(self._compact_lbl("Date"))
        self.sale_date = _make_compact_date()
        self.sale_date.setFixedWidth(112)
        row1.addWidget(self.sale_date)

        row1.addWidget(self._compact_lbl("Time"))
        self.sale_time_edit = _make_compact_edit(height=_METADATA_CONTROL_HEIGHT)
        self.sale_time_edit.setFixedWidth(70)
        self.sale_time_edit.setAlignment(Qt.AlignCenter)
        row1.addWidget(self.sale_time_edit)

        row1.addWidget(self._compact_lbl("Type"))
        self.sale_type_combo = _make_compact_combo()
        self.sale_type_combo.addItems(["Cash", "Credit", "Credit Card"])
        self.sale_type_combo.setFixedWidth(110)
        row1.addWidget(self.sale_type_combo)

        row1.addStretch(1)
        outer.addLayout(row1)

        # -- Row 2: customer / patient / doctor -------------------------
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(5)

        row2.addWidget(self._compact_lbl("Customer *"))
        self.customer_combo = _make_compact_combo()
        self.customer_combo.setMinimumWidth(200)
        row2.addWidget(self.customer_combo, 3)

        row2.addWidget(self._compact_lbl("Patient"))
        self.patient_name_edit = _make_compact_edit(height=_METADATA_CONTROL_HEIGHT)
        self.patient_name_edit.setMinimumWidth(150)
        row2.addWidget(self.patient_name_edit, 3)

        row2.addWidget(self._compact_lbl("Doctor"))
        self.doctor_combo = _make_compact_combo()
        self.doctor_combo.setMinimumWidth(160)
        row2.addWidget(self.doctor_combo, 2)

        outer.addLayout(row2)

        self._load_customers()
        self._load_doctors()

    def _load_customers(self):
        customers = CustomerDAO.get_all()
        self.customer_combo.addItem("-- Select Customer --", None)
        for c in customers:
            self.customer_combo.addItem(c["customer_name"], c["id"])
            # Kept for the popup's read-only Cnt No / Address display.  The
            # customer rows are already loaded here, so no extra query runs.
            self._customer_contacts[c["id"]] = c.get("contact_no") or ""
            self._customer_addresses[c["id"]] = c.get("address") or ""
        # Try to default to WALKIN
        for i in range(self.customer_combo.count()):
            if self.customer_combo.itemText(i).upper() == "WALKIN":
                self.customer_combo.setCurrentIndex(i)
                break

    def _load_doctors(self):
        doctors = DoctorDAO.get_all()
        self.doctor_combo.addItem("-- None --", None)
        for d in doctors:
            self.doctor_combo.addItem(d["doctor_name"], d["id"])

    def _set_bill_no(self):
        if not self._invoice:
            self._provisional_bill_no = False
            self.bill_no_edit.setText(SalesDAO.generate_next_bill_no())

    def _set_current_datetime(self):
        now = datetime.now()
        from PySide6.QtCore import QDate
        self.sale_date.setDate(QDate(now.year, now.month, now.day))
        self.sale_time_edit.setText(now.strftime("%H:%M"))

    # ------------------------------------------------------------------
    # Bill table
    # ------------------------------------------------------------------

    def _build_bill_table(self):
        self._table_group = QGroupBox("Bill Items")
        self._table_group.setStyleSheet(_GROUP_BOX)
        layout = QVBoxLayout(self._table_group)
        layout.setContentsMargins(8, 20, 8, 8)

        self._table = QTableWidget()
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "#", "Item Name", "Pack Size", "Location", "Batch No",
            "Expiry", "MRP", "Qty", "Disc Amt", "Amount", "Del"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setDefaultSectionSize(_BILL_ROW_HEIGHT)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setFixedHeight(_BILL_HEADER_HEIGHT)

        # Content-based fixed widths keep the grid readable and stop a long
        # batch number or location from inflating its column: only *Item
        # Name* stretches, so it absorbs the spare width at every desktop
        # size instead of pushing the numeric columns out of view.
        hv = self._table.horizontalHeader()
        for index, width in enumerate(_BILL_COLUMN_WIDTHS):
            hv.setSectionResizeMode(index, QHeaderView.Fixed)
            hv.resizeSection(index, width)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)

        for index in _BILL_CENTERED_COLUMNS:
            item = self._table.horizontalHeaderItem(index)
            item.setTextAlignment(Qt.AlignCenter)
        for index in _BILL_RIGHT_COLUMNS:
            item = self._table.horizontalHeaderItem(index)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 5px; font-weight: bold;"
            f"  font-size: {TYPE_TABLE_HEADER}px;"
            f"  font-family: {FONT_FAMILY};"
            f"}}"
        )
        hv.setFont(readable_font(TYPE_TABLE_HEADER, bold=True))
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: {TYPE_TABLE_DATA}px; font-family: {FONT_FAMILY};"
            f"  selection-background-color: {_SELECTED};"
            f"  selection-color: {_SELECTED_TEXT};"
            f"}}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
        )
        self._table.setFont(readable_font(TYPE_TABLE_DATA))
        layout.addWidget(self._table, 1)

    def _on_add_item(self):
        data = self._entry_bar.get_current_data()
        if data is None:
            QMessageBox.warning(self, "Validation", "Please select an item and batch.")
            return

        qty_text = self._entry_bar.qty_edit.text().strip()
        if not qty_text:
            self._entry_bar.qty_edit.setFocus()
            QMessageBox.warning(self, "Validation", "Sale Quantity is required.")
            return
        try:
            sale_qty = float(qty_text)
        except (TypeError, ValueError):
            sale_qty = 0.0
        if not math.isfinite(sale_qty) or sale_qty <= 0:
            self._entry_bar.qty_edit.setFocus()
            QMessageBox.warning(
                self, "Validation", "Sale Quantity must be a valid number greater than 0."
            )
            return
        data["sale_qty"] = sale_qty

        discount_text = self._entry_bar.discount_edit.text().strip()
        try:
            discount = float(discount_text) if discount_text else 0.0
        except (TypeError, ValueError):
            discount = float("nan")
        if not math.isfinite(discount) or discount < 0:
            self._entry_bar.discount_edit.setFocus()
            QMessageBox.warning(
                self, "Validation", "Discount must be a valid non-negative amount."
            )
            return
        data["discount_amount"] = discount

        available = self._available_for_batch(
            data["stock_batch_id"], data["batch_stock"]
        )
        if sale_qty > available:
            QMessageBox.warning(
                self, "Insufficient Stock",
                f"Only {available:.0f} units are available for this batch."
            )
            return

        if SalesDAO.is_expired(data["expiry"]):
            QMessageBox.warning(
                self, "Expired Batch",
                f"Batch {data['batch_no']} (Exp: {data['expiry']}) is expired. "
                f"Cannot sell expired stock."
            )
            return

        mrp = data["mrp"]
        discount = data["discount_amount"]
        ps_str = data["pack_size"]
        pack_size_int = 1
        if ps_str and str(ps_str).strip().isdigit():
            try:
                pack_size_int = int(str(ps_str).strip())
            except (ValueError, TypeError):
                pack_size_int = 1
        if pack_size_int < 1:
            pack_size_int = 1
        unit_price = mrp / pack_size_int
        gross = _round2(sale_qty * unit_price)
        if discount > gross:
            QMessageBox.warning(self, "Validation", "Discount cannot exceed gross amount.")
            return
        amount = _round2(gross - discount)

        existing = next(
            (r for r in self._item_rows
             if r.item_id == data["item_id"] and r.stock_batch_id == data["stock_batch_id"]),
            None,
        )
        if existing is not None:
            # Same item+batch is one bill line.  The per-add discount is
            # accumulated, matching the prior line-level discount semantics.
            existing.sale_qty += sale_qty
            existing.discount_amount = _round2(existing.discount_amount + discount)
            combined_gross = _round2(existing.sale_qty * unit_price)
            existing.amount = _round2(combined_gross - existing.discount_amount)
        else:
            row = _BillItemRow(
                item_id=data["item_id"], item_name=data["item_name"],
                stock_batch_id=data["stock_batch_id"], pack_size=data["pack_size"],
                location=data["location"], batch_no=data["batch_no"],
                expiry=data["expiry"], mrp=mrp, sale_qty=sale_qty,
                discount_amount=discount, amount=amount,
            )
            self._item_rows.append(row)
        self._refresh_table()
        self._recalc_totals()
        self._refresh_draft_availability()
        self._entry_bar.clear()
        self._entry_bar.item_combo.setFocus()

    def _refresh_table(self):
        self._table.setRowCount(len(self._item_rows))
        for i, r in enumerate(self._item_rows):
            self._table.setRowHeight(i, _BILL_ROW_HEIGHT)
            index_item = QTableWidgetItem(str(i + 1))
            index_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._table.setItem(i, 0, index_item)
            self._table.setItem(i, 1, QTableWidgetItem(r.item_name))
            self._table.setItem(i, 2, QTableWidgetItem(r.pack_size))
            self._table.setItem(i, 3, QTableWidgetItem(r.location))
            self._table.setItem(i, 4, QTableWidgetItem(r.batch_no))
            expiry_item = QTableWidgetItem(r.expiry)
            expiry_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._table.setItem(i, 5, expiry_item)

            mrp_item = QTableWidgetItem(f"{r.mrp:.2f}")
            mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 6, mrp_item)

            qty_item = QTableWidgetItem(f"{r.sale_qty:.0f}")
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 7, qty_item)

            disc_item = QTableWidgetItem(f"{r.discount_amount:.2f}")
            disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 8, disc_item)

            amt_item = QTableWidgetItem(f"{r.amount:.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 9, amt_item)

            self._make_row_delete_button(i)

    def _make_row_delete_button(self, index: int) -> QPushButton:
        """Compact Delete action, centred inside the fixed-width Del column.

        The button is wrapped in a filler cell so it is centred both ways and
        never stretches to the row height â€” a small table action instead of a
        standalone control dominating the row.  Delete behaviour is unchanged.
        """
        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet(_BTN_ROW_ACTION)
        try:
            del_btn.setProperty("cs_btn_kind", "row_delete")
        except Exception:
            pass
        del_btn.setFixedSize(_BILL_DELETE_WIDTH, _BILL_DELETE_HEIGHT)
        del_btn.setToolTip(f"Remove line {index + 1} from this bill")
        del_btn.clicked.connect(lambda _, idx=index: self._delete_item(idx))

        cell = QWidget()
        cell.setStyleSheet("background: transparent;")
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.setSpacing(0)
        cell_layout.addStretch(1)
        cell_layout.addWidget(del_btn, 0, Qt.AlignVCenter)
        cell_layout.addStretch(1)
        _keep_alive(cell)
        self._table.setCellWidget(index, 10, cell)
        # QTableView sizes an index widget from its sizeHint, so pin the
        # filler to the full cell rect to guarantee the action is centred
        # both horizontally and vertically inside the Del column.
        column = self._table.columnWidth(10)
        cell.setFixedWidth(column)
        cell.setFixedHeight(_BILL_ROW_HEIGHT)
        return cell

    def _delete_item(self, idx: int):
        if 0 <= idx < len(self._item_rows):
            self._item_rows.pop(idx)
            self._refresh_table()
            self._recalc_totals()
            self._refresh_draft_availability()

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------

    def _build_totals(self):
        """One clean totals + actions row across the bottom of the page.

        LEFT  : Total Items, Total Amt, Customer Saving, Round Off, NET AMT
                and Paid, each with a content-sized box (Net Amt emphasised).
        RIGHT : Hold Bill (secondary), Save Sale (primary), Cancel
                (secondary), all with the same box height as the entry bar.
        """
        self._totals_widget = QWidget()
        self._totals_widget.setFixedHeight(_TOTALS_FOOTER_HEIGHT)
        self._totals_widget.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        layout = QHBoxLayout(self._totals_widget)
        layout.setContentsMargins(12, 2, 12, 2)
        layout.setSpacing(10)

        if self._popup_mode:
            # Discount / Paid Amount live in the popup's top strip, so the
            # summary row keeps only the calculated values.  The same
            # widgets are created there - nothing is duplicated.
            self._add_total_field(layout, "Total Amt", "total_amount_label",
                                  width=96)
            self._add_total_field(layout, "Round Off", "round_off_label",
                                  width=92)
            self._add_total_field(layout, "NET AMT", "net_amt_label",
                                  width=112, emphasised=True)
            layout.addStretch()
            return

        self._add_total_field(layout, "Total Items", "total_items_label",
                              width=64, emphasised=False)
        self._add_total_field(layout, "Total Amt", "total_amount_label",
                              width=96)
        self._add_total_field(layout, "Customer Saving", "bill_disc_edit",
                              width=100)
        self._add_total_field(layout, "Round Off", "round_off_label",
                              width=92)
        self._add_total_field(layout, "NET AMT", "net_amt_label",
                              width=112, emphasised=True)
        self._add_total_field(layout, "Paid", "paid_edit", width=96)

        # Wire recalc
        self.bill_disc_edit.textChanged.connect(self._recalc_totals)
        self.paid_edit.textChanged.connect(self._recalc_totals)

        # -- Actions (one set only: the sale area owns Save/Hold/Cancel) --
        layout.addStretch()

        # -- All Open Bills summary (UI-only combined totals) --
        # Compact two-line block in the stretch zone: bill count + total
        # quantity on top, combined amount + net below.  Read-only labels;
        # never written to any invoice or accounting table.
        self._combined_box = QWidget()
        self._combined_box.setObjectName("CombinedSummary")
        self._combined_box.setStyleSheet(
            f"#CombinedSummary {{ background: transparent;"
            f"  border-left: 1px solid {_BORDER}; }}"
        )
        combined_layout = QVBoxLayout(self._combined_box)
        combined_layout.setContentsMargins(8, 0, 0, 0)
        combined_layout.setSpacing(0)
        self._combined_line1 = QLabel("All Bills (1)")
        self._combined_line1.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._combined_line1.setFixedWidth(172)
        self._combined_line1.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_HINT}px; font-weight: bold;"
            f"font-family: {FONT_FAMILY}; background: transparent;"
        )
        self._combined_line2 = QLabel("Qty 0   Amt 0.00   Net 0.00")
        self._combined_line2.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._combined_line2.setFixedWidth(172)
        self._combined_line2.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;"
            f"font-family: {FONT_FAMILY}; background: transparent;"
        )
        combined_layout.addWidget(self._combined_line1)
        combined_layout.addWidget(self._combined_line2)
        layout.addWidget(self._combined_box)

        hold_btn = QPushButton("Hold Bill")
        hold_btn.setStyleSheet(_BTN_ORANGE)
        hold_btn.setFixedSize(88, _ACTION_BUTTON_HEIGHT)
        hold_btn.clicked.connect(self._on_hold)
        layout.addWidget(hold_btn)

        save_btn = QPushButton("Save Sale")
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.setFixedSize(96, _ACTION_BUTTON_HEIGHT)
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.setFixedSize(78, _ACTION_BUTTON_HEIGHT)
        cancel_btn.clicked.connect(self.cancelled.emit)
        layout.addWidget(cancel_btn)

    def _add_total_field(self, layout: QHBoxLayout, title: str, attr_name: str,
                         *, width: int, emphasised: bool = False):
        """One caption-over-value block of a fixed width in the footer."""
        container = QVBoxLayout()
        container.setSpacing(0)
        container.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(title)
        lbl.setStyleSheet(_CAPTION_STYLE)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedWidth(width)
        lbl.setFixedHeight(16)
        container.addWidget(lbl)

        if attr_name.endswith("_label"):
            val_lbl = QLabel("0.00")
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setFixedWidth(width)
            val_lbl.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
            val_lbl.setStyleSheet(
                f"color: {_TEXT};"
                f"font-size: "
                f"{TYPE_VALUE_EMPHASIS if emphasised else TYPE_VALUE}px;"
                f"font-weight: bold;"
                f"background: transparent; font-family: {FONT_FAMILY};"
            )
            container.addWidget(val_lbl)
            setattr(self, attr_name, val_lbl)
        else:
            edit = _make_compact_edit("0.00", height=_TOTALS_CONTROL_HEIGHT)
            edit.setFixedWidth(width)
            edit.setAlignment(Qt.AlignRight)
            container.addWidget(edit)
            setattr(self, attr_name, edit)
            if attr_name not in ("bill_disc_edit", "paid_edit"):
                edit.setReadOnly(True)

        layout.addLayout(container)

    def set_combined_totals(self, count: int, qty: float,
                              amount: float, net: float) -> None:
        """Show the UI-only All-Open-Bills summary (popup has none)."""
        if getattr(self, "_popup_mode", False):
            return
        line1 = getattr(self, "_combined_line1", None)
        line2 = getattr(self, "_combined_line2", None)
        if line1 is None or line2 is None:
            return
        try:
            qty_text = f"{qty:.0f}" if float(qty).is_integer() else f"{qty}"
        except Exception:
            qty_text = str(qty)
        bill_word = "bill" if int(count) == 1 else "bills"
        line1.setText(f"All Bills ({int(count)} {bill_word}) • Qty {qty_text}")
        line2.setText(f"Amt ₹{float(amount):.2f} • Net ₹{float(net):.2f}")
        try:
            tip = (f"{int(count)} open {bill_word} — total qty {qty_text}, "
                   f"combined amount {float(amount):.2f}, net {float(net):.2f}")
            line1.setToolTip(tip)
            line2.setToolTip(tip)
        except Exception:
            pass

    def _recalc_totals(self):
        total = sum(r.amount for r in self._item_rows)
        if getattr(self, "total_items_label", None) is not None:
            self.total_items_label.setText(str(len(self._item_rows)))
        self.total_amount_label.setText(f"{total:.2f}")

        bill_disc = _safe_float(self.bill_disc_edit.text())
        net = total - bill_disc
        round_off = _round2(net) - net
        net = _round2(net + round_off)

        self.round_off_label.setText(f"{round_off:.2f}")
        self.net_amt_label.setText(f"{net:.2f}")
        self._emit_totals()

    def _emit_totals(self):
        """Publish the live bill figures for the right-side bill panel."""
        self.totals_changed.emit(
            self.bill_no_edit.text(),
            self.total_amount_label.text(),
            self.net_amt_label.text(),
        )

    def refresh_theme(self) -> None:
        """Re-apply live Day/Night colours in place (drafts preserved).

        Only stylesheet strings are recomputed from the live centralized
        palette; bill rows, entry text, focus, selection and layout are
        untouched, so an in-progress sale survives a theme switch.
        """
        try:
            p = palette()
        except Exception:
            return
        try:
            self.setStyleSheet(
                f"#SalePanel {{ background-color: {p['bg']}; }}"
                f"#SalePanel QLabel {{ color: {p['text']}; font-size: {TYPE_VALUE}px;"
                f" font-weight: bold; font-family: {FONT_FAMILY}; background: transparent; }}"
            )
        except Exception:
            pass
        # Entry bar (combos, edits, add button, captions, popups).
        try:
            if hasattr(self, "_entry_bar") and hasattr(self._entry_bar, "refresh_theme"):
                self._entry_bar.refresh_theme()
        except Exception:
            pass
        # Bill Items group + table + header (the reported black rectangle).
        try:
            if hasattr(self, "_table_group"):
                self._table_group.setStyleSheet(_group_box_style(p))
        except Exception:
            pass
        try:
            if hasattr(self, "_table"):
                self._table.setStyleSheet(_fresh_bill_table_style(p))
                self._table.horizontalHeader().setStyleSheet(_fresh_bill_header_style(p))
        except Exception:
            pass
        # Row Delete buttons inside the bill grid.
        try:
            from PySide6.QtWidgets import QPushButton
            for btn in self.findChildren(QPushButton):
                try:
                    if btn.text().strip() == "Delete" and btn.maximumWidth() <= 60:
                        btn.setStyleSheet(_fresh_row_action_style(p))
                except Exception:
                    continue
        except Exception:
            pass
        # Compact metadata strip + totals footer.
        try:
            if hasattr(self, "_metadata_strip"):
                self._metadata_strip.setStyleSheet(
                    f"#CompactSaleMetadata {{ background-color: {p['bg']}; "
                    f"border-top: 1px solid {p['border']}; border-bottom: 1px solid {p['border']}; }}"
                )
        except Exception:
            pass
        try:
            if hasattr(self, "_totals_widget"):
                self._totals_widget.setStyleSheet(
                    f"background-color: {p['surface']}; border-top: 1px solid {p['border']};"
                )
        except Exception:
            pass
        # All-Open-Bills summary block (border + two label lines).
        try:
            box = getattr(self, "_combined_box", None)
            if box is not None:
                box.setStyleSheet(
                    f"#CombinedSummary {{ background: transparent;"
                    f"  border-left: 1px solid {p['border']}; }}"
                )
            line1 = getattr(self, "_combined_line1", None)
            if line1 is not None:
                line1.setStyleSheet(
                    f"color: {p['text']}; font-size: {TYPE_HINT}px; font-weight: bold;"
                    f"font-family: {FONT_FAMILY}; background: transparent;"
                )
            line2 = getattr(self, "_combined_line2", None)
            if line2 is not None:
                line2.setStyleSheet(
                    f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;"
                    f"font-family: {FONT_FAMILY}; background: transparent;"
                )
        except Exception:
            pass
        # Everything else (combos, edits, dates, buttons, labels, popups).
        try:
            refresh_cs_tree(self)
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Populate for edit
    # ------------------------------------------------------------------

    def _populate_invoice(self, inv: dict):
        self.bill_no_edit.setText(inv.get("bill_no", ""))

        from PySide6.QtCore import QDate
        sd = inv.get("sale_date", "")
        if sd:
            try:
                parts = sd.split("-")
                self.sale_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.sale_time_edit.setText(inv.get("sale_time", ""))
        idx = self.sale_type_combo.findText(inv.get("sale_type", "Cash"))
        if idx >= 0:
            self.sale_type_combo.setCurrentIndex(idx)

        cid = inv.get("customer_id")
        if cid:
            idx = self.customer_combo.findData(cid)
            if idx >= 0:
                self.customer_combo.setCurrentIndex(idx)

        self.patient_name_edit.setText(inv.get("patient_name", ""))

        did = inv.get("doctor_id")
        if did:
            idx = self.doctor_combo.findData(did)
            if idx >= 0:
                self.doctor_combo.setCurrentIndex(idx)

        items = SalesDAO.get_invoice_items(inv["id"])
        for it in items:
            row = _BillItemRow(
                item_id=it["item_id"],
                item_name=it.get("item_name", ""),
                stock_batch_id=it["stock_batch_id"],
                pack_size=it.get("pack_size", ""),
                location=it.get("location", ""),
                batch_no=it.get("batch_no", ""),
                expiry=it.get("expiry", ""),
                mrp=it.get("mrp", 0.0),
                sale_qty=it.get("sale_qty", 0.0),
                discount_amount=it.get("discount_amount", 0.0),
                amount=it.get("amount", 0.0),
            )
            self._item_rows.append(row)
            self._original_batch_qty[row.stock_batch_id] = (
                self._original_batch_qty.get(row.stock_batch_id, 0.0) + row.sale_qty
            )
        self._refresh_table()

        self.bill_disc_edit.setText(str(inv.get("discount", 0.0)))
        self.paid_edit.setText(str(inv.get("paid_amount", 0.0)))

        self._recalc_totals()
        self._refresh_draft_availability()

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    @staticmethod
    def _compact_lbl(text: str) -> QLabel:
        """Small bold caption for the metadata strip.

        Measured from the real font so the caption hugs its text instead of
        reserving a wide box, and vertically centred against its field.
        """
        lbl = QLabel(text)
        lbl.setStyleSheet(_CAPTION_STYLE)
        font = readable_font(TYPE_HINT, bold=True)
        lbl.setFont(font)
        lbl.setFixedWidth(QFontMetrics(font).horizontalAdvance(text) + 4)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return lbl

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _focus_batch_for_row(self, row: _BillItemRow):
        item_index = self._entry_bar.item_combo.findData(row.item_id)
        if item_index >= 0:
            self._entry_bar.item_combo.setCurrentIndex(item_index)
        batch_index = self._entry_bar.batch_combo.findData(row.stock_batch_id)
        if batch_index >= 0:
            self._entry_bar.batch_combo.setCurrentIndex(batch_index)
        self._entry_bar.batch_combo.lineEdit().setFocus()

    def _validate_sale_items(self) -> bool:
        batches = {}
        for row in self._item_rows:
            if row.item_id is None:
                self._entry_bar.item_combo.lineEdit().setFocus()
                QMessageBox.warning(self, "Validation", "An item is required for every bill row.")
                return False
            if row.stock_batch_id is None:
                self._entry_bar.batch_combo.lineEdit().setFocus()
                QMessageBox.warning(self, "Validation", "A batch is required for every bill row.")
                return False
            try:
                quantity = float(row.sale_qty)
            except (TypeError, ValueError):
                quantity = 0.0
            if not math.isfinite(quantity) or quantity <= 0:
                self._focus_batch_for_row(row)
                self._entry_bar.qty_edit.setFocus()
                QMessageBox.warning(
                    self, "Validation", "Sale Quantity must be a valid number greater than 0."
                )
                return False
            try:
                discount = float(row.discount_amount)
            except (TypeError, ValueError):
                discount = float("nan")
            if not math.isfinite(discount) or discount < 0 or not math.isfinite(float(row.amount)):
                self._focus_batch_for_row(row)
                self._entry_bar.discount_edit.setFocus()
                QMessageBox.warning(self, "Validation", "Bill row amounts must be valid and non-negative.")
                return False

            batch = SalesDAO.get_batch_by_id(row.stock_batch_id)
            if not batch or batch.get("item_id") != row.item_id:
                self._focus_batch_for_row(row)
                QMessageBox.warning(
                    self, "Validation", f"Batch {row.batch_no} is no longer available for this item."
                )
                return False
            if SalesDAO.is_expired(batch.get("expiry", row.expiry)):
                self._focus_batch_for_row(row)
                QMessageBox.warning(
                    self, "Expired Batch",
                    f"Batch {batch.get('batch_no', row.batch_no)} is expired and cannot be sold."
                )
                return False
            batches[row.stock_batch_id] = batch

        for batch_id, batch in batches.items():
            draft_quantity = self._draft_qty_for_batch(batch_id)
            original_quantity = self._original_batch_qty.get(batch_id, 0.0)
            stored_quantity = float(batch.get("stock_qty", 0.0) or 0.0)
            # Multi-bill safety: unsaved quantities in *other* open drafts
            # reserve the same stored stock, so the commit-time check must
            # include them.  `own_reserved` already nets the edit allowance;
            # `other_reserved` is the in-memory reservation from sibling
            # drafts (never persisted, never double-deducted).
            other_reserved = max(
                0.0, float(self._other_draft_reserved_qty(batch_id) or 0.0)
            )
            own_reserved = reserved_quantity(draft_quantity, original_quantity)
            if own_reserved + other_reserved > stored_quantity + 1e-9:
                available = self._available_for_batch(batch_id, stored_quantity)
                row = next(r for r in self._item_rows if r.stock_batch_id == batch_id)
                self._focus_batch_for_row(row)
                QMessageBox.warning(
                    self, "Insufficient Stock",
                    f"Only {available:.0f} units are available for this batch "
                    f"(other open bills reserve {other_reserved:.0f})."
                )
                return False
        return True

    def _on_save(self):
        """Entry point for the panel's Save Sale button.

        On the Counter Sale screen this only *validates* the draft and then
        opens the Sales Bill review popup.  Inside that popup the same button
        is the final step, so it validates and commits directly.  Either way
        validation runs first and nothing is committed until it passes.
        """
        if not self._validate_for_commit():
            return
        if self._in_review_popup:
            self._commit_sale()
            return
        self._open_review_dialog()

    def _open_review_dialog(self):
        """Show the compact, centred Sales Bill review/edit popup.

        ``show()`` (not ``exec()``) is used deliberately: the popup is modal
        and application-blocking for the user, but the call returns
        immediately so the save flow stays re-entrant and testable.
        """
        dialog = SalesBillReviewDialog(self, self)
        self._review_dialog = dialog
        dialog.finished.connect(self._release_review_dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _release_review_dialog(self, *_args):
        """Drop the popup handle once it is gone (Close, Escape or Save)."""
        if getattr(self, "_review_dialog", None) is not None:
            del self._review_dialog

    def _validate_for_commit(self) -> bool:
        """Every business rule that must pass before a sale may be written.

        Used by both the Counter Sale Save Sale step and the popup's final
        Save, so the review popup can never be the step that skips a rule.
        """
        if not fy_view.confirm_transaction_date(
            self,
            self.sale_date.date().toString("yyyy-MM-dd"),
            action="sale",
        ):
            self.sale_date.setFocus()
            return False

        if not self.customer_combo.currentData():
            self.customer_combo.setFocus()
            QMessageBox.warning(self, "Validation", "Customer is required.")
            return False

        if not self.bill_no_edit.text().strip():
            self.bill_no_edit.setFocus()
            QMessageBox.warning(self, "Validation", "Bill number is required.")
            return False

        if not self._item_rows:
            self._entry_bar.item_combo.lineEdit().setFocus()
            QMessageBox.warning(self, "Validation", "At least one item is required.")
            return False

        if not self._validate_sale_items():
            return False

        sale_time = self.sale_time_edit.text().strip()
        try:
            datetime.strptime(sale_time, "%H:%M")
        except ValueError:
            self.sale_time_edit.setFocus()
            QMessageBox.warning(self, "Validation", "Enter a valid sale time in HH:MM format.")
            return False

        self._recalc_totals()

        total_amount = _round2(float(_d(sum(r.amount for r in self._item_rows))))
        bill_discount_text = self.bill_disc_edit.text().strip()
        try:
            bill_discount = float(bill_discount_text) if bill_discount_text else 0.0
        except ValueError:
            bill_discount = float("nan")
        if (not math.isfinite(bill_discount) or bill_discount < 0 or
                bill_discount > total_amount):
            self.bill_disc_edit.setFocus()
            QMessageBox.warning(
                self, "Validation",
                "Bill discount must be a valid amount between 0 and the bill total."
            )
            return False

        paid_text = self.paid_edit.text().strip()
        try:
            paid = float(paid_text) if paid_text else 0.0
        except ValueError:
            paid = float("nan")
        if not math.isfinite(paid) or paid < 0:
            self.paid_edit.setFocus()
            QMessageBox.warning(
                self, "Validation", "Paid amount must be a valid non-negative amount."
            )
            return False

        return True

    def _commit_sale(self):
        """Write the sale: one invoice, one stock deduction, one posting.

        Only reachable through the popup's final Save (or directly from a
        panel already inside that popup).  Stock and accounting are handled
        by the established SalesDAO transaction, so the review popup adds no
        accounting behaviour of its own.
        """
        if self._commit_locked:
            # Double-submit guard: a second click on Save cannot produce a
            # second invoice, deduction or posting set.
            return
        self._commit_locked = True

        try:
            self._recalc_totals()
            total_amount = _round2(float(_d(sum(r.amount for r in self._item_rows))))
            bill_discount = _safe_float(self.bill_disc_edit.text())
            paid = _safe_float(self.paid_edit.text())
            round_off = _safe_float(self.round_off_label.text())
            net_amount = _round2(total_amount - bill_discount + round_off)
            sale_date = self.sale_date.date().toString("yyyy-MM-dd")
            sale_time = self.sale_time_edit.text().strip()
            sale_type = self.sale_type_combo.currentText()
            patient_name = self.patient_name_edit.text().strip()
            cid = self.customer_combo.currentData()
            did = self.doctor_combo.currentData()
            # Provisional previews never reserve a database number.  Keep the
            # displayed preview when it is still free; otherwise take the next
            # free number, so sequential open drafts can never share one
            # permanent CNo even if a preview went stale.
            displayed = self.bill_no_edit.text().strip()
            bill_no = (_resolve_bill_no_for_save(displayed)
                       if self._provisional_bill_no and not self._invoice
                       else displayed)
            remarks = self._remarks_text()
            items_data = [r.to_dict() for r in self._item_rows]

            if self._invoice:
                # Edit: update in place â€” stock is adjusted and the
                # accounting posting is reversed + re-posted atomically.
                SalesDAO.update_invoice(
                    invoice_id=self._invoice["id"],
                    bill_no=bill_no, sale_date=sale_date,
                    sale_time=sale_time, sale_type=sale_type,
                    customer_id=cid, patient_name=patient_name,
                    doctor_id=did, discount=bill_discount,
                    paid_amount=paid, total_amount=total_amount,
                    round_off=round_off, net_amount=net_amount,
                    remarks=remarks, items=items_data,
                )
            else:
                SalesDAO.insert_invoice(
                    bill_no=bill_no, sale_date=sale_date, sale_time=sale_time,
                    sale_type=sale_type, customer_id=cid,
                    patient_name=patient_name, doctor_id=did,
                    discount=bill_discount, paid_amount=paid,
                    total_amount=total_amount, round_off=round_off,
                    net_amount=net_amount, remarks=remarks,
                    items=items_data,
                )
            self._saved = True
            self._provisional_bill_no = False
            self.saved.emit()
        except Exception as e:
            self._commit_locked = False
            QMessageBox.critical(self, "Error", f"Failed to save sale:\n{e}")

    # ------------------------------------------------------------------
    # Draft hand-off to / from the Sales Bill review popup
    # ------------------------------------------------------------------

    def draft_state(self) -> dict:
        """Snapshot of the unsaved draft, for the review popup to edit.

        Pure copy â€” nothing is written and no stock is reserved by taking
        this snapshot, which is what keeps the popup free of side effects.
        """
        return {
            "bill_no": self.bill_no_edit.text(),
            "provisional_bill_no": self._provisional_bill_no,
            "sale_date": self.sale_date.date(),
            "sale_time": self.sale_time_edit.text(),
            "sale_type": self.sale_type_combo.currentText(),
            "customer_id": self.customer_combo.currentData(),
            "patient_name": self.patient_name_edit.text(),
            "doctor_id": self.doctor_combo.currentData(),
            "bill_discount": self.bill_disc_edit.text(),
            "paid_amount": self.paid_edit.text(),
            "invoice": self._invoice,
            "hold_bill_id": self._hold_bill_id,
            "original_batch_qty": dict(self._original_batch_qty),
            "rows": [
                {
                    "item_id": r.item_id,
                    "item_name": r.item_name,
                    "stock_batch_id": r.stock_batch_id,
                    "pack_size": r.pack_size,
                    "location": r.location,
                    "batch_no": r.batch_no,
                    "expiry": r.expiry,
                    "mrp": r.mrp,
                    "sale_qty": r.sale_qty,
                    "discount_amount": r.discount_amount,
                    "amount": r.amount,
                }
                for r in self._item_rows
            ],
        }

    def load_draft_state(self, state: dict):
        """Adopt a draft snapshot (used by the review popup to load the bill)."""
        self._invoice = state.get("invoice")
        self._hold_bill_id = state.get("hold_bill_id")
        # A newly loaded workspace is committable: clear the previous
        # double-submit lock and saved/held flags so sequential multi-bill
        # saves cannot be swallowed by the prior bill's lock.
        self._commit_locked = False
        self._saved = False
        self._held = False
        self._provisional_bill_no = bool(state.get("provisional_bill_no", False))
        self.bill_no_edit.setText(state.get("bill_no", ""))

        date_value = state.get("sale_date")
        if date_value is not None:
            self.sale_date.setDate(date_value)

        self.sale_time_edit.setText(state.get("sale_time", ""))

        type_index = self.sale_type_combo.findText(state.get("sale_type", "Cash"))
        if type_index >= 0:
            self.sale_type_combo.setCurrentIndex(type_index)

        customer_index = self.customer_combo.findData(state.get("customer_id"))
        if customer_index >= 0:
            self.customer_combo.setCurrentIndex(customer_index)

        self.patient_name_edit.setText(state.get("patient_name", ""))

        doctor_index = self.doctor_combo.findData(state.get("doctor_id"))
        if doctor_index >= 0:
            self.doctor_combo.setCurrentIndex(doctor_index)

        self.bill_disc_edit.setText(state.get("bill_discount", "0.00"))
        self.paid_edit.setText(state.get("paid_amount", "0.00"))

        self._original_batch_qty = dict(state.get("original_batch_qty") or {})
        self._item_rows = [
            _BillItemRow(
                item_id=row["item_id"],
                item_name=row["item_name"],
                stock_batch_id=row["stock_batch_id"],
                pack_size=row["pack_size"],
                location=row["location"],
                batch_no=row["batch_no"],
                expiry=row["expiry"],
                mrp=row["mrp"],
                sale_qty=row["sale_qty"],
                discount_amount=row["discount_amount"],
                amount=row["amount"],
            )
            for row in state.get("rows") or []
        ]
        self._refresh_table()
        self._recalc_totals()
        self._refresh_draft_availability()
        self._entry_bar.set_cno(self.bill_no_edit.text())
        self._focus_entry_on_first_row()

    def _focus_entry_on_first_row(self):
        """Show the first bill line's item/batch in the entry bar.

        Display only: selecting in the entry bar fills the read-only Pack /
        Location / Expiry / MRP / Batch-Stock boxes and loads the batch list,
        so the entry area of a review step always shows live item data
        instead of empty controls.  It reserves nothing and writes nothing.
        """
        if not self._item_rows:
            return
        first = self._item_rows[0]
        item_index = self._entry_bar.item_combo.findData(first.item_id)
        if item_index >= 0:
            self._entry_bar.item_combo.setCurrentIndex(item_index)
        batch_index = self._entry_bar.batch_combo.findData(first.stock_batch_id)
        if batch_index >= 0:
            self._entry_bar.batch_combo.setCurrentIndex(batch_index)

    @property
    def was_saved(self) -> bool:
        return self._saved

    # ------------------------------------------------------------------
    # Hold Bill
    # ------------------------------------------------------------------

    def _on_hold(self):
        if not self._item_rows:
            QMessageBox.warning(self, "Hold Bill", "No items to hold. Add items first.")
            return

        cid = self.customer_combo.currentData()
        patient_name = self.patient_name_edit.text().strip()
        did = self.doctor_combo.currentData()

        self._recalc_totals()
        total_amount = _round2(float(_d(sum(r.amount for r in self._item_rows))))

        items_data = []
        for r in self._item_rows:
            items_data.append({
                "item_id": r.item_id,
                "item_name_snapshot": r.item_name,
                "batch_no": r.batch_no,
                "pack_size": r.pack_size,
                "location": r.location,
                "expiry": r.expiry,
                "mrp": r.mrp,
                "sale_qty": r.sale_qty,
                "discount_amount": r.discount_amount,
                "amount": r.amount,
            })

        user = auth.session.user
        created_by = user["username"] if user else ""

        try:
            hold_id = create_hold(
                customer_id=cid,
                patient_name=patient_name,
                doctor_id=did,
                counter_no="",
                remarks="",
                total_amount_preview=total_amount,
                created_by=created_by,
                items=items_data,
            )
            hold = __import__(
                "database.hold_bill_dao", fromlist=["get_by_id"]
            ).get_by_id(hold_id)
            hold_num = hold["hold_number"] if hold else str(hold_id)
            QMessageBox.information(
                self, "Bill Held",
                f"Bill has been held as {hold_num}.\n"
                f"Items: {len(self._item_rows)}  |  Amount: {total_amount:.2f}"
            )
            self._held = True
            self.held.emit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to hold bill:\n{e}")

    @property
    def was_held(self) -> bool:
        return getattr(self, "_held", False)

    def _populate_hold_bill(self, data: dict):
        """Load items from a held bill into the dialog for resume."""
        hold = data["hold"]
        items = data["items"]

        cid = hold.get("customer_id")
        if cid:
            idx = self.customer_combo.findData(cid)
            if idx >= 0:
                self.customer_combo.setCurrentIndex(idx)

        self.patient_name_edit.setText(hold.get("patient_name", ""))

        did = hold.get("doctor_id")
        if did:
            idx = self.doctor_combo.findData(did)
            if idx >= 0:
                self.doctor_combo.setCurrentIndex(idx)

        warnings = []
        for it in items:
            batch = SalesDAO.get_batch_by_item_and_batch_no(
                it["item_id"], it["batch_no"]
            )

            batch_stock = 0.0
            stock_batch_id = None
            if batch:
                stock_batch_id = batch["id"]
                batch_stock = batch.get("stock_qty", 0.0)

            if stock_batch_id is None:
                warnings.append(
                    f"Item '{it.get('item_name_snapshot', '')}' "
                    f"batch '{it['batch_no']}' â€” batch no longer available."
                )
                continue

            if SalesDAO.is_expired(it.get("expiry", "")):
                warnings.append(
                    f"Item '{it.get('item_name_snapshot', '')}' "
                    f"batch '{it['batch_no']}' â€” batch is expired."
                )
                continue

            if stock_batch_id and batch_stock < it.get("sale_qty", 0):
                warnings.append(
                    f"Item '{it.get('item_name_snapshot', '')}' "
                    f"batch '{it['batch_no']}' â€” insufficient stock "
                    f"({batch_stock:.0f} available, {it.get('sale_qty', 0):.0f} needed)."
                )

            row = _BillItemRow(
                item_id=it["item_id"],
                item_name=it.get("item_name_snapshot", ""),
                stock_batch_id=stock_batch_id,
                pack_size=it.get("pack_size", ""),
                location=it.get("location", ""),
                batch_no=it["batch_no"],
                expiry=it.get("expiry", ""),
                mrp=it.get("mrp", 0.0),
                sale_qty=it.get("sale_qty", 0.0),
                discount_amount=it.get("discount_amount", 0.0),
                amount=it.get("amount", 0.0),
            )
            self._item_rows.append(row)

        self._refresh_table()
        self._recalc_totals()
        self._refresh_draft_availability()

        if warnings:
            QMessageBox.warning(
                self, "Resume Warnings",
                "Some items from the held bill could not be loaded:\n\n"
                + "\n".join(warnings)
                + "\n\nPlease review before completing the sale."
            )


class _SaleDialog(QDialog):
    """Modal wrapper around :class:`_SalePanel` (compatibility only).

    The Counter Sale page uses the panel inline; this wrapper is kept so
    the modal entry point keeps working for any external caller.  It adds
    no transaction behaviour of its own.
    """

    def __init__(self, parent: QWidget | None = None, *,
                 invoice: dict | None = None,
                 hold_bill_data: dict | None = None):
        super().__init__(parent)
        _keep_alive(self)
        self.setWindowTitle("Counter Sale")
        self.setMinimumWidth(1200)
        self.setMinimumHeight(700)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._panel = _SalePanel(self, invoice=invoice,
                                 hold_bill_data=hold_bill_data)
        layout.addWidget(self._panel)

        self._panel.saved.connect(self.accept)
        self._panel.held.connect(self.accept)
        self._panel.cancelled.connect(self.reject)

    @property
    def was_saved(self) -> bool:
        return self._panel.was_saved

    @property
    def was_held(self) -> bool:
        return self._panel.was_held


# ======================================================================
# Sales Bill â€” review / edit popup (compact, modal, classic layout)
# ======================================================================

# Traditional pharmacy-software popup header: a solid blue title bar with
# white bold text, matching the reference bill window rather than a modern
# card.  Only this dialog uses the blue bar; the app palette is untouched.
_BILL_HEADER_BG = "#1f5c9e"
# Horizontal space the popup's own chrome takes from the item entry row:
# the body widget's margins and the vertical border either side.
_POPUP_BODY_CHROME = 16
# Slot reserved for the CNo mirror at the head of the popup's entry row.
_POPUP_CNO_WIDTH = 54
_BILL_DIALOG_STYLE = (
    f"QDialog#SalesBillDialog {{ background-color: {_SURFACE}; }}"
)


class SalesBillReviewDialog(QDialog):
    """Compact "Sales Bill" review/edit step for Counter Sale.

    Opened by the Counter Sale **Save Sale** button *after* the draft has
    been validated.  It shows the bill and lets the user correct the
    customer, patient, doctor, quantities, discounts and line items before
    committing.

    Transaction contract
    --------------------
    * Opening this popup writes nothing: no invoice, no stock deduction,
      no accounting entry.  It only takes a copy of the unsaved draft.
    * **Save** runs the full validation again and then performs the one and
      only commit (invoice + stock + posting) through the existing
      ``SalesDAO`` workflow.
    * **Close** / **Escape** discard the copy and return to Counter Sale
      with the draft untouched.

    The bill is edited through an embedded :class:`_SalePanel` set to
    review mode, so every existing control â€” item autocomplete, batch
    selection, draft stock reservation, add/delete line, keyboard
    navigation â€” is the same one the Counter Sale screen uses.
    """

    def __init__(self, panel: _SalePanel, parent: QWidget | None = None):
        super().__init__(parent)
        _keep_alive(self)
        self._source_panel = panel
        self.setObjectName("SalesBillDialog")
        self.setWindowTitle("Sales Bill")
        self.setModal(True)
        self.setStyleSheet(_BILL_DIALOG_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_blue_header(panel))

        body = QWidget()
        body.setObjectName("SalesBillBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 6, 4)
        body_layout.setSpacing(0)

        # The editable copy of the draft.  Review mode makes its own
        # "Save Sale" behave as the final commit instead of opening a
        # second popup.
        self._panel = _SalePanel(body, popup_mode=True)
        self._panel._in_review_popup = True
        self._panel.load_draft_state(panel.draft_state())
        # A review copy must honour reservations made by the other open
        # Counter Sale drafts just like the inline panel does.
        self._panel.set_other_draft_reservation_provider(
            panel._other_draft_reserved_qty
        )

        body_layout.addWidget(self._panel, 1)
        root.addWidget(body, 1)

        root.addWidget(self._build_actions())

        # The popup's Remarks box is the bill's remarks source when the sale
        # is committed from here; an edited bill shows its stored remarks.
        self._panel.remarks_edit = self.remarks_edit
        invoice = self._panel._invoice
        if invoice:
            self.remarks_edit.setText(invoice.get("remarks") or "")

        # A successful commit re-emits on the *source* panel so the Counter
        # Sale page performs its normal history refresh / form reset.
        self._panel.saved.connect(self._source_panel.saved.emit)
        # Hold stays a draft-only action: it is forwarded like Save so the
        # page resets, but no stock or accounting is touched either way.
        self._panel.held.connect(self._on_popup_held)
        # Cancel inside the popup means "discard", exactly like Close.
        self._panel.cancelled.connect(self.reject)

        self._resize_compact()
        # The popup's own width is only known now, so the Item Entry row is
        # measured and sized to fit exactly this window.
        self._panel.apply_popup_entry_widths(self.width() - _POPUP_BODY_CHROME)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------


    def _build_blue_header(self, panel: _SalePanel) -> QWidget:
        """Blue title bar carrying Voucher No / Date / Time from the bill.

        Professional layout with aligned Voucher No, Date, Time fields.
        """
        bar = QWidget()
        bar.setObjectName("SalesBillHeader")
        bar.setFixedHeight(56)
        bar.setStyleSheet(
            f"#SalesBillHeader {{ background-color: {_BILL_HEADER_BG};"
            f"  border-bottom: 1px solid {_BILL_HEADER_BG}; }}"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(24)

        title = QLabel("Sales Bill")
        title.setStyleSheet(
            "color: #ffffff; font-size: 14px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        layout.addWidget(title)
        layout.addSpacing(20)

        # Voucher No
        voucher_layout = QHBoxLayout()
        voucher_layout.setSpacing(8)
        voucher_caption = QLabel("Voucher No")
        voucher_caption.setStyleSheet(
            "color: #d8e6f5; font-size: 11px; background: transparent;"
            f"font-family: {FONT_FAMILY};"
        )
        voucher_layout.addWidget(voucher_caption)
        self._header_voucher_label = QLabel(panel.bill_no_edit.text() or "--")
        self._header_voucher_label.setStyleSheet(
            "color: #ffffff; font-size: 12px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._header_voucher_label.setMinimumWidth(140)
        voucher_layout.addWidget(self._header_voucher_label)
        layout.addLayout(voucher_layout)

        # Date
        date_layout = QHBoxLayout()
        date_layout.setSpacing(8)
        date_caption = QLabel("Date")
        date_caption.setStyleSheet(
            "color: #d8e6f5; font-size: 11px; background: transparent;"
            f"font-family: {FONT_FAMILY};"
        )
        date_layout.addWidget(date_caption)
        self._header_date_label = QLabel(panel.sale_date.date().toString("dd-MM-yyyy"))
        self._header_date_label.setStyleSheet(
            "color: #ffffff; font-size: 12px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._header_date_label.setMinimumWidth(110)
        date_layout.addWidget(self._header_date_label)
        layout.addLayout(date_layout)

        # Time
        time_layout = QHBoxLayout()
        time_layout.setSpacing(8)
        time_caption = QLabel("Time")
        time_caption.setStyleSheet(
            "color: #d8e6f5; font-size: 11px; background: transparent;"
            f"font-family: {FONT_FAMILY};"
        )
        time_layout.addWidget(time_caption)
        self._header_time_label = QLabel(panel.sale_time_edit.text() or "--")
        self._header_time_label.setStyleSheet(
            "color: #ffffff; font-size: 12px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._header_time_label.setMinimumWidth(80)
        time_layout.addWidget(self._header_time_label)
        layout.addLayout(time_layout)

        layout.addStretch(1)
        return bar

    def _build_actions(self) -> QWidget:
        """Bottom footer with professional multi-row structure.

        ROW 1: Total Items | Remarks
        ROW 2: Total Amount | Bill Discount | CN Amount | Dr Amount | Credit Note | Round Off | Net Amount
        ROW 3: Save | Close (bottom-right aligned)
        """
        bar = QWidget()
        bar.setObjectName("SalesBillActions")
        bar.setStyleSheet(
            f"#SalesBillActions {{ background-color: {_SURFACE};"
            f"  border-top: 1px solid {_BORDER}; }}"
        )
        main_layout = QVBoxLayout(bar)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # ============================================================
        # ROW 1: Total Items | Remarks
        # ============================================================
        row1 = QHBoxLayout()
        row1.setSpacing(16)

        items_caption = QLabel("Total Items")
        items_caption.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_FORM_LABEL}px;"
            f"font-weight: bold; background: transparent;"
            f"font-family: {FONT_FAMILY};"
        )
        row1.addWidget(items_caption)

        self._total_items_label = QLabel(str(len(self._panel._item_rows)))
        self._total_items_label.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._total_items_label.setMinimumWidth(50)
        row1.addWidget(self._total_items_label)
        row1.addSpacing(24)

        remarks_caption = QLabel("Remarks")
        remarks_caption.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_FORM_LABEL}px;"
            f"font-weight: bold; background: transparent;"
            f"font-family: {FONT_FAMILY};"
        )
        row1.addWidget(remarks_caption)

        self.remarks_edit = _make_edit()
        self.remarks_edit.setMinimumWidth(280)
        row1.addWidget(self.remarks_edit)

        row1.addStretch(1)
        main_layout.addLayout(row1)

        # ============================================================
        # ROW 2: Totals breakdown
        # ============================================================
        row2 = QHBoxLayout()
        row2.setSpacing(16)

        # Total Amount
        total_amt_container = QVBoxLayout()
        total_amt_container.setSpacing(2)
        total_amt_caption = QLabel("Total Amount")
        total_amt_caption.setStyleSheet(_HEADER_LABEL)
        total_amt_caption.setAlignment(Qt.AlignCenter)
        total_amt_container.addWidget(total_amt_caption)
        self._footer_total_amount = QLabel(self._panel.total_amount_label.text())
        self._footer_total_amount.setAlignment(Qt.AlignCenter)
        self._footer_total_amount.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._footer_total_amount.setMinimumWidth(100)
        self._footer_total_amount.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
        total_amt_container.addWidget(self._footer_total_amount)
        row2.addLayout(total_amt_container)

        # Bill Discount
        bill_disc_container = QVBoxLayout()
        bill_disc_container.setSpacing(2)
        bill_disc_caption = QLabel("Bill Discount")
        bill_disc_caption.setStyleSheet(_HEADER_LABEL)
        bill_disc_caption.setAlignment(Qt.AlignCenter)
        bill_disc_container.addWidget(bill_disc_caption)
        self._footer_bill_discount = QLabel(f"{_safe_float(self._panel.bill_disc_edit.text()):.2f}")
        self._footer_bill_discount.setAlignment(Qt.AlignCenter)
        self._footer_bill_discount.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._footer_bill_discount.setMinimumWidth(100)
        self._footer_bill_discount.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
        bill_disc_container.addWidget(self._footer_bill_discount)
        row2.addLayout(bill_disc_container)

        # CN Amount (Credit Note)
        cn_container = QVBoxLayout()
        cn_container.setSpacing(2)
        cn_caption = QLabel("CN Amount")
        cn_caption.setStyleSheet(_HEADER_LABEL)
        cn_caption.setAlignment(Qt.AlignCenter)
        cn_container.addWidget(cn_caption)
        self._footer_cn_amount = QLabel("0.00")
        self._footer_cn_amount.setAlignment(Qt.AlignCenter)
        self._footer_cn_amount.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._footer_cn_amount.setMinimumWidth(100)
        self._footer_cn_amount.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
        cn_container.addWidget(self._footer_cn_amount)
        row2.addLayout(cn_container)

        # Dr Amount (Debit Note)
        dr_container = QVBoxLayout()
        dr_container.setSpacing(2)
        dr_caption = QLabel("Dr Amount")
        dr_caption.setStyleSheet(_HEADER_LABEL)
        dr_caption.setAlignment(Qt.AlignCenter)
        dr_container.addWidget(dr_caption)
        self._footer_dr_amount = QLabel("0.00")
        self._footer_dr_amount.setAlignment(Qt.AlignCenter)
        self._footer_dr_amount.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._footer_dr_amount.setMinimumWidth(100)
        self._footer_dr_amount.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
        dr_container.addWidget(self._footer_dr_amount)
        row2.addLayout(dr_container)

        # Credit Note (placeholder for future)
        credit_note_container = QVBoxLayout()
        credit_note_container.setSpacing(2)
        credit_note_caption = QLabel("Credit Note")
        credit_note_caption.setStyleSheet(_HEADER_LABEL)
        credit_note_caption.setAlignment(Qt.AlignCenter)
        credit_note_container.addWidget(credit_note_caption)
        self._footer_credit_note = QLabel("0.00")
        self._footer_credit_note.setAlignment(Qt.AlignCenter)
        self._footer_credit_note.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._footer_credit_note.setMinimumWidth(100)
        self._footer_credit_note.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
        credit_note_container.addWidget(self._footer_credit_note)
        row2.addLayout(credit_note_container)

        # Round Off
        round_off_container = QVBoxLayout()
        round_off_container.setSpacing(2)
        round_off_caption = QLabel("Round Off")
        round_off_caption.setStyleSheet(_HEADER_LABEL)
        round_off_caption.setAlignment(Qt.AlignCenter)
        round_off_container.addWidget(round_off_caption)
        self._footer_round_off = QLabel(self._panel.round_off_label.text())
        self._footer_round_off.setAlignment(Qt.AlignCenter)
        self._footer_round_off.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE}px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._footer_round_off.setMinimumWidth(90)
        self._footer_round_off.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
        round_off_container.addWidget(self._footer_round_off)
        row2.addLayout(round_off_container)

        # Net Amount (emphasized)
        net_amt_container = QVBoxLayout()
        net_amt_container.setSpacing(2)
        net_amt_caption = QLabel("Net Amount")
        net_amt_caption.setStyleSheet(_HEADER_LABEL)
        net_amt_caption.setAlignment(Qt.AlignCenter)
        net_amt_container.addWidget(net_amt_caption)
        self._footer_net_amount = QLabel(self._panel.net_amt_label.text())
        self._footer_net_amount.setAlignment(Qt.AlignCenter)
        self._footer_net_amount.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_VALUE_EMPHASIS}px;"
            f"font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._footer_net_amount.setMinimumWidth(120)
        self._footer_net_amount.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
        net_amt_container.addWidget(self._footer_net_amount)
        row2.addLayout(net_amt_container)

        row2.addStretch(1)
        main_layout.addLayout(row2)

        # ============================================================
        # ROW 3: Save / Close (bottom-right aligned)
        # ============================================================
        row3 = QHBoxLayout()
        row3.addStretch(1)

        self._final_save_btn = QPushButton("Save")
        self._final_save_btn.setStyleSheet(_BTN_SAVE)
        self._final_save_btn.setFixedWidth(100)
        self._final_save_btn.setFixedHeight(32)
        self._final_save_btn.setDefault(True)
        self._final_save_btn.setToolTip(
            "Commit this bill: save the sale, deduct stock and post accounting"
        )
        self._final_save_btn.clicked.connect(self._on_final_save)
        row3.addWidget(self._final_save_btn)

        row3.addSpacing(8)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_BTN_SECONDARY)
        close_btn.setFixedWidth(100)
        close_btn.setFixedHeight(32)
        close_btn.setAutoDefault(False)
        close_btn.clicked.connect(self.reject)
        row3.addWidget(close_btn)

        main_layout.addLayout(row3)

        # Keep footer totals live while the bill is edited.
        self._panel.totals_changed.connect(self._on_totals_changed)
        # Also watch bill discount changes to update footer
        self._panel.bill_disc_edit.textChanged.connect(self._update_footer_totals)

        return bar

    def _update_footer_totals(self):
        """Update footer total labels when bill discount changes."""
        if hasattr(self, '_footer_bill_discount'):
            self._footer_bill_discount.setText(f"{_safe_float(self._panel.bill_disc_edit.text()):.2f}")
        if hasattr(self, '_footer_total_amount'):
            self._footer_total_amount.setText(self._panel.total_amount_label.text())
        if hasattr(self, '_footer_round_off'):
            self._footer_round_off.setText(self._panel.round_off_label.text())
        if hasattr(self, '_footer_net_amount'):
            self._footer_net_amount.setText(self._panel.net_amt_label.text())

    def _on_totals_changed(self, bill_no: str, amount: str, bill_total: str):
        # Update header voucher no if it changed
        if hasattr(self, '_header_voucher_label'):
            self._header_voucher_label.setText(bill_no or "--")

        # Update footer totals
        if hasattr(self, '_total_items_label'):
            self._total_items_label.setText(str(len(self._panel._item_rows)))
        if hasattr(self, '_footer_total_amount'):
            self._footer_total_amount.setText(amount)
        if hasattr(self, '_footer_round_off'):
            self._footer_round_off.setText(self._panel.round_off_label.text())
        if hasattr(self, '_footer_net_amount'):
            self._footer_net_amount.setText(bill_total)

    # Reference proportions for the Sales Bill window: a compact dialog that is
    # never full-screen at any of the supported desktop resolutions.  The
    # width is sized so the whole Item Entry row fits on ONE line with every
    # label and value clear of its neighbour â€” twelve labelled fields plus
    # their captions need roughly 1.2k px, so the window is wide and short
    # rather than square, and the height stays compact.
    MIN_WIDTH, MAX_WIDTH = 1180, 1300
    MIN_HEIGHT, MAX_HEIGHT = 520, 600

    @classmethod
    def target_size(cls, available_w: int, available_h: int) -> tuple[int, int]:
        """Popup size for a screen of ``available_w`` x ``available_h``."""
        width = min(cls.MAX_WIDTH,
                    max(cls.MIN_WIDTH, int(available_w * 0.96)))
        height = min(cls.MAX_HEIGHT,
                     max(cls.MIN_HEIGHT, int(available_h * 0.72)))
        return width, height

    def _resize_compact(self):
        """Keep the popup in the reference proportions, not full-screen."""
        screen = self.screen() if self.screen() else None
        available = (screen.availableSize() if screen else QSize(1366, 768))
        width, height = self.target_size(available.width(), available.height())
        self.setFixedSize(width, height)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.setMaximumSize(self.MAX_WIDTH, self.MAX_HEIGHT)
        self._center_over_host()

    def _center_over_host(self):
        """Centre the popup on the Counter Sale screen behind it.

        Qt centres a dialog on its immediate parent, which here is the sale
        panel, so the position is set explicitly against the whole page to
        keep the window visually centred over Counter Sale.
        """
        host = self.parentWidget()
        anchor = host.window() if host is not None else None
        if anchor is None:
            return
        area = anchor.geometry()
        self.move(
            area.x() + max(0, (area.width() - self.width()) // 2),
            area.y() + max(0, (area.height() - self.height()) // 2),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_popup_held(self):
        """Forward a Hold made inside the popup and close it unchanged."""
        self._source_panel.held.emit()
        self.reject()

    def _on_final_save(self):
        """The only place the sale is actually written.

        ``was_saved`` is checked before and after so a second click (or a
        double-click) on Save can never produce a second invoice, stock
        deduction or posting set.
        """
        if self._panel.was_saved:
            return
        self._final_save_btn.setEnabled(False)
        # Runs the same full validation as the Counter Sale Save Sale step,
        # then commits.  Re-enables Save if validation or the write failed.
        self._panel._on_save()
        if not self._panel.was_saved:
            self._final_save_btn.setEnabled(True)
            return
        # Committed: the page has already refreshed history via the `saved`
        # signal, so close the popup.
        self.accept()

    def refresh_theme(self) -> None:
        """Re-apply live Day/Night colours to the open Sales Bill popup."""
        try:
            p = palette()
        except Exception:
            return
        try:
            self.setStyleSheet(
                f"QDialog#SalesBillDialog {{ background-color: {p['surface']}; }}"
            )
        except Exception:
            pass
        try:
            if hasattr(self, "_panel") and hasattr(self._panel, "refresh_theme"):
                self._panel.refresh_theme()
        except Exception:
            pass
        try:
            refresh_cs_tree(self)
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass


# ======================================================================
# Counter Sale PAGE (History | inline active sale area | bill panel)
# ======================================================================

# ----------------------------------------------------------------------
# Bill-history view modes (read-only views of existing sales)
# ----------------------------------------------------------------------
# "item" -> one row per sale item, the bill number repeated on each item
#           row (the pre-existing grid, unchanged).
# "bill" -> exactly one row per bill using bill-level fields only.
# The first column is always Bill No in both modes and always carries the
# invoice id in Qt.UserRole, so Edit / Delete / Print behave identically.
HISTORY_MODE_ITEM = "item"
HISTORY_MODE_BILL = "bill"

# How the history grid is being narrowed.  All three are display-only.
HISTORY_FILTER_ALL = "all"       # every bill, no date narrowing
HISTORY_FILTER_DATE = "date"     # the single Date control's exact day
HISTORY_FILTER_FY = "fy"         # the chosen financial year's start..end

_HISTORY_COLUMNS = {
    HISTORY_MODE_ITEM: [
        "Bill No", "Type", "Item Name", "MRP", "Qty", "Amount",
        "Patient", "Pack Size", "Batch No", "Expiry", "Time",
        "Disc Amt", "Bill Amount",
    ],
    HISTORY_MODE_BILL: [
        "Bill No", "Type", "Patient", "Date", "Time", "Items",
        "Total Amount", "Disc Amt", "Paid Amount", "Net Amount",
    ],
}

# Column that takes the leftover width in each mode.
_HISTORY_STRETCH_COLUMN = {
    HISTORY_MODE_ITEM: 2,
    HISTORY_MODE_BILL: 2,
}

# Item Wise / Bill Wise radios are styled at construction (and refreshed on
# every Day/Night switch) rather than from a baked module constant: the
# indicator style carries a generated check/dot glyph, which can only be
# produced once a QGuiApplication exists.
_HISTORY_FILTER_BAR_HEIGHT = 30


class _OpenBillCard(QPushButton):
    """Four-line open-bill selector with a guaranteed readable height.

    A plain ``QPushButton`` reports a multi-line ``sizeHint`` that is too
    short for its own text (about 74 px for four 11 px lines), so a layout
    shrinks the card to that hint and the last two lines clip or paint
    over the next card.  Pinning the hints to the measured four-line
    height keeps every line inside its own card even if an explicit
    fixed height is later cleared by style changes.
    """

    CARD_HEIGHT = 80

    def sizeHint(self):  # noqa: N802 (Qt override)
        hint = super().sizeHint()
        return QSize(max(hint.width(), 180), self.CARD_HEIGHT)

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        hint = super().minimumSizeHint()
        return QSize(max(hint.width(), 180), self.CARD_HEIGHT)

    def pin_height(self) -> None:
        """Lock this card to the readable compact height.

        ``setText``/stylesheet/font updates reset the explicit minimum
        height back to the style hint (~34 px), letting the scroll layout
        compress the card and clip its last lines.  Clearing the explicit
        minimum (max stays pinned) hands sizing back to the pinned size
        hints above, which the layout cannot compress.
        """
        try:
            self.setMaximumHeight(self.CARD_HEIGHT)
        except Exception:
            pass
        try:
            self.setMinimumSize(QSize(0, 0))
        except Exception:
            pass
        try:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        except Exception:
            pass

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Re-pin after deferred font/style changes.

        Making the active card bold posts an async FontChange whose style
        re-polish resets the explicit minimum height again (the inactive
        cards keep their pin because their font never changes).  Re-pinning
        here keeps every card at full height in both modes.
        """
        try:
            super().changeEvent(event)
        except Exception:
            pass
        try:
            if event is not None and event.type() in (
                QEvent.FontChange,
                QEvent.StyleChange,
            ):
                self.pin_height()
        except Exception:
            pass


class CounterSalePage(QWidget):
    """Counter Sale screen.

    Fixed three-region desktop layout (Phase 6E — Counter Sale Layout Fix):

        Region A  page header + controlled-height Bill History table
        Region B  active sale entry, directly below the history table
        Region C  current bill table (takes the remaining space)
        Right     fixed "Bill" panel with actions and live bill totals

    The sale area is embedded inline (via ``_SalePanel``), so adding items
    or history rows never moves or vertically centers the entry region.

    The history region is read-only: a date filter and the Item Wise /
    Bill Wise mode selector only change which existing rows are displayed.
    They never touch the active draft sale or any business record.
    """

    HISTORY_PAGE_SIZE = 200

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        _keep_alive(self)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Region A (top): page header strip
        self._header_strip = self._build_header_strip()
        root.addWidget(self._header_strip)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)

        self._history_mode = HISTORY_MODE_ITEM
        self._history_filter = HISTORY_FILTER_DATE
        self._history_financial_year: dict | None = None
        self._history_filter_bar = self._build_history_filter_bar()
        left.addWidget(self._history_filter_bar)

        self._hist_table = self._build_history_table()
        self._history_offset = 0
        self._history_has_more = True
        self._history_loading = False
        self._hist_table.verticalScrollBar().valueChanged.connect(
            self._on_history_scroll
        )
        left.addWidget(self._hist_table)

        # Regions B + C: inline active sale area.  Only the bill table
        # inside the panel expands, so the entry region stays pinned.
        self._sale_panel = _SalePanel()
        # Open bills are in-memory workspaces only.  Their snapshots never
        # create invoices, reserve rows in the database, or alter stock.
        self._open_bills: dict[int, dict] = {}
        self._active_open_bill_id = 1
        self._next_open_bill_id = 2
        self._sale_panel.set_other_draft_reservation_provider(
            self._reserved_by_other_open_bills
        )
        self._sale_panel.saved.connect(self._on_sale_saved)
        self._sale_panel.held.connect(self._on_sale_held)
        self._sale_panel.cancelled.connect(self._on_sale_cancelled)
        left.addWidget(self._sale_panel, 1)

        body.addLayout(left, 1)
        self._bill_panel = self._build_bill_panel()
        body.addWidget(self._bill_panel)

        # The first workspace is an unassigned draft: it shows its stable
        # draft label, never a proposed permanent number.
        self._assign_new_provisional_bill_no()
        self._open_bills[self._active_open_bill_id] = self._sale_panel.draft_state()
        self._refresh_open_bill_cards()

        root.addLayout(body, 1)

        self._editing_invoice_id: int | None = None
        self._refresh_history()
        self._apply_history_height()

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_header_strip(self) -> QWidget:
        """Region A header: page title + New Sale (history actions live in
        the right-side bill panel)."""
        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(8)

        title = QLabel("Sales / Counter Sale")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_PAGE_TITLE}px;"
            f"font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        hl.addWidget(title)

        subtitle = QLabel("Bill History")
        subtitle.setStyleSheet(
            f"color: {_TEXT}; font-size: {TYPE_SECTION_HEADER}px;"
            f"font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        hl.addWidget(subtitle)
        hl.addStretch()

        self._new_btn = QPushButton("New Sale")
        self._new_btn.setFixedWidth(110)
        self._new_btn.setStyleSheet(_BTN_SAVE)
        self._new_btn.setToolTip(
            "Start a new sale in the active sale area below"
        )
        self._new_btn.clicked.connect(self._on_new)
        hl.addWidget(self._new_btn)

        return header

    # ------------------------------------------------------------------
    # Bill-history filter bar (single Date + Item Wise / Bill Wise)
    # ------------------------------------------------------------------

    def _build_history_filter_bar(self) -> QWidget:
        """Read-only controls for the history grid.

        One compact Date selector (calendar popup opens directly below it)
        plus the two existing view modes.  Nothing here writes to the
        database; every handler just re-reads existing sales.
        """
        bar = QWidget()
        bar.setObjectName("HistoryFilterBar")
        bar.setFixedHeight(_HISTORY_FILTER_BAR_HEIGHT)
        bar.setStyleSheet(
            f"#HistoryFilterBar {{ background-color: {_SURFACE};"
            f"  border-bottom: 1px solid {_BORDER}; }}"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        self._hist_date = _make_compact_date()
        self._hist_date.setCalendarPopup(True)
        self._hist_date.setFixedWidth(118)
        # A bare QDateEdit starts on 01/01/2000, which is what the history
        # filter used to show.  It opens on today's live system date instead.
        # Set here, before dateChanged is connected below, so this stays a
        # display default: it never selects the date filter and never
        # overrides a date the user picks afterwards.
        self._hist_date.setDate(QDate.currentDate())
        self._hist_date.setToolTip(
            "Show Counter Sale history for this date only"
        )

        self._hist_item_mode = QRadioButton("Item Wise")
        self._hist_bill_mode = QRadioButton("Bill Wise")
        _radio_style = _fresh_radio_style()
        self._hist_item_mode.setStyleSheet(_radio_style)
        self._hist_bill_mode.setStyleSheet(_radio_style)
        self._hist_item_mode.setChecked(True)          # default mode
        self._hist_item_mode.setToolTip(
            "One row per sale item, with the bill number repeated"
        )
        self._hist_bill_mode.setToolTip(
            "One row per bill using bill-level totals only"
        )

        self._hist_today_btn = QPushButton("Today")
        self._hist_today_btn.setFixedWidth(56)
        self._hist_today_btn.setStyleSheet(_BTN_SECONDARY)
        self._hist_today_btn.setToolTip("Show today's sales")

        self._hist_all_btn = QPushButton("All Dates")
        self._hist_all_btn.setFixedWidth(80)
        self._hist_all_btn.setStyleSheet(_BTN_SECONDARY)
        self._hist_all_btn.setToolTip(
            "Show every bill regardless of date"
        )
        self._hist_refresh_btn = QPushButton("Refresh")
        self._hist_refresh_btn.setFixedWidth(76)
        self._hist_refresh_btn.setStyleSheet(_BTN_SECONDARY)

        layout.addWidget(self._flbl("Daily Sales:"))
        layout.addWidget(self._flbl("Date"))
        layout.addWidget(self._hist_date)
        layout.addWidget(self._hist_today_btn)
        layout.addWidget(self._hist_all_btn)
        layout.addStretch()
        layout.addWidget(self._flbl("View"))
        layout.addWidget(self._hist_item_mode)
        layout.addWidget(self._hist_bill_mode)
        layout.addWidget(self._hist_refresh_btn)

        # A committed date change or a mode switch refreshes the grid
        # immediately.  Neither path touches the active sale area.
        self._hist_date.dateChanged.connect(self._on_history_date_changed)
        self._hist_today_btn.clicked.connect(self._on_show_today_history)
        self._hist_item_mode.toggled.connect(self._on_history_mode_toggled)
        self._hist_bill_mode.toggled.connect(self._on_history_mode_toggled)
        self._hist_all_btn.clicked.connect(self._on_show_all_history)
        self._hist_refresh_btn.clicked.connect(self._refresh_history)
        return bar

    def _on_show_today_history(self):
        """Show today's sales."""
        self._hist_date.blockSignals(True)
        self._hist_date.setDate(QDate.currentDate())
        self._hist_date.blockSignals(False)
        self._history_filter = HISTORY_FILTER_DATE
        self._history_financial_year = None
        self._refresh_history()

    # ------------------------------------------------------------------
    # History view filtering (date / financial year / all)
    # ------------------------------------------------------------------

    def _history_filter_dates(self) -> tuple[str, str]:
        """Return the (start, end) YYYY-MM-DD bounds; ("", "") means all."""
        if self._history_filter == HISTORY_FILTER_ALL:
            return "", ""
        if self._history_filter == HISTORY_FILTER_FY:
            year = self._history_financial_year or {}
            return year.get("start_date", ""), year.get("end_date", "")
        day = self._hist_date.date().toString("yyyy-MM-dd")
        return day, day

    def _on_history_date_changed(self, _date):
        """A date picked from the calendar is a single-date history filter."""
        self._history_filter = HISTORY_FILTER_DATE
        self._history_financial_year = None
        self._refresh_history()

    def _on_show_all_history(self):
        """Drop the filter and show every bill again (mode is kept)."""
        self._history_filter = HISTORY_FILTER_ALL
        self._history_financial_year = None
        self._refresh_history()

    def set_history_financial_year(self, year: dict | None):
        """View Counter Sale history for a whole financial year.

        Called by the top navigation's FY button.  This is a VIEW filter:
        the active financial year is never changed, no year is created,
        and nothing is written to the database.  The Date control is moved
        to 31 March of that year so the header shows where the view ends.
        """
        if not year or not year.get("start_date") or not year.get("end_date"):
            self._history_filter = HISTORY_FILTER_ALL
            self._history_financial_year = None
            self._refresh_history()
            return
        self._history_financial_year = dict(year)
        self._history_filter = HISTORY_FILTER_FY
        self._set_history_date_text(year["end_date"])
        self._refresh_history()

    def _set_history_date_text(self, iso_date: str):
        """Show an ISO date in the history control without re-filtering."""
        parsed = QDate.fromString(iso_date, "yyyy-MM-dd")
        if not parsed.isValid():
            return
        self._hist_date.blockSignals(True)
        self._hist_date.setDate(parsed)
        self._hist_date.blockSignals(False)

    def _viewed_financial_year(self) -> dict | None:
        """The FY currently chosen for viewing, or None."""
        if self._history_filter != HISTORY_FILTER_FY:
            return None
        return self._history_financial_year

    def _viewing_historical_financial_year(self) -> bool:
        """True when an old/expired FY is being viewed instead of the active one."""
        year = self._viewed_financial_year()
        if not year:
            return False
        active = financial_year.get_active_financial_year()
        return bool(active) and year.get("id") != active.get("id")

    def _confirm_new_sale_under_historical_fy(self) -> bool:
        """Warn before New Sale while an old FY is open.  True = go ahead.

        The history date and the viewed financial year are display state
        only, so the bill that is started still gets the live date and the
        active financial year from the existing sale logic.
        """
        if not self._viewing_historical_financial_year():
            return True
        year = self._viewed_financial_year()
        active = financial_year.get_active_financial_year()
        active_name = active["name"] if active else ""
        message = QMessageBox(self)
        message.setWindowTitle("Historical Financial Year")
        message.setIcon(QMessageBox.Information)
        message.setText(
            "Historical Financial Year selected.\n\n"
            f"You are viewing FY {year['name']}.\n\n"
            "New bills cannot be saved in this expired Financial Year.\n"
            "The new bill will be created using the current date\n"
            f"and current active Financial Year {active_name}."
        )
        continue_btn = message.addButton(
            "Continue", QMessageBox.ButtonRole.AcceptRole
        )
        cancel_btn = message.addButton(
            "Cancel", QMessageBox.ButtonRole.RejectRole
        )
        message.setDefaultButton(cancel_btn)
        message.exec()
        return message.clickedButton() is continue_btn

    def _on_history_mode_toggled(self, _checked: bool):
        if self._hist_bill_mode.isChecked():
            self._set_history_mode(HISTORY_MODE_BILL)
        elif self._hist_item_mode.isChecked():
            self._set_history_mode(HISTORY_MODE_ITEM)

    def _set_history_mode(self, mode: str):
        """Switch the grid between item-wise and bill-wise rows."""
        if mode not in _HISTORY_COLUMNS or mode == self._history_mode:
            return
        self._history_mode = mode
        self._apply_history_columns()
        self._refresh_history()

    def _history_mode_is_bill(self) -> bool:
        return self._history_mode == HISTORY_MODE_BILL

    def _apply_history_columns(self):
        """Re-label the history grid for the active mode."""
        labels = _HISTORY_COLUMNS[self._history_mode]
        table = self._hist_table
        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(0)
        table.setColumnCount(len(labels))
        table.setHorizontalHeaderLabels(labels)
        hv = table.horizontalHeader()
        stretch_col = _HISTORY_STRETCH_COLUMN[self._history_mode]
        hv.setSectionResizeMode(QHeaderView.ResizeToContents)
        for col in range(len(labels)):
            if col == stretch_col:
                hv.setSectionResizeMode(col, QHeaderView.Stretch)
        hv.setStretchLastSection(stretch_col != len(labels) - 1)
        table.setSortingEnabled(True)

    def _build_history_table(self) -> QTableWidget:
        """Region A table â€” height is controlled by _apply_history_height()."""
        table = QTableWidget()
        table.setColumnCount(13)
        table.setHorizontalHeaderLabels([
            "Bill No", "Type", "Item Name", "MRP", "Qty", "Amount",
            "Patient", "Pack Size", "Batch No", "Expiry", "Time",
            "Disc Amt", "Bill Amount"
        ])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(28)
        table.setShowGrid(True)
        table.setAlternatingRowColors(False)
        table.setSortingEnabled(True)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        hv = table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setMinimumHeight(30)
        for col in range(13):
            if col == 2:
                hv.setSectionResizeMode(col, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 6px; font-weight: bold;"
            f"  font-size: {TYPE_TABLE_HEADER}px;"
            f"  font-family: {FONT_FAMILY};"
            f"}}"
        )
        hv.setFont(readable_font(TYPE_TABLE_HEADER, bold=True))
        table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: {TYPE_TABLE_DATA}px; font-family: {FONT_FAMILY};"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 3px 5px; }}"
        )
        table.setFont(readable_font(TYPE_TABLE_DATA))
        return table

    def _build_bill_panel(self) -> QWidget:
        """Fixed right-side 'Bill' panel: actions + live bill totals."""
        panel = QWidget()
        panel.setObjectName("BillPanel")
        panel.setFixedWidth(236)
        panel.setStyleSheet(
            f"#BillPanel {{ background-color: {_SURFACE};"
            f"  border-left: 1px solid {_BORDER}; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Bill actions group
        actions = QGroupBox("Bill")
        self._bill_actions_group = actions
        actions.setStyleSheet(_GROUP_BOX)
        al = QVBoxLayout(actions)
        al.setContentsMargins(10, 18, 10, 10)
        al.setSpacing(6)
        for text, style, handler in (
            ("Edit", _BTN_SECONDARY, self._on_edit),
            ("Delete", _BTN_DANGER, self._on_delete),
            ("Print", _BTN_SECONDARY, self._on_direct_print),
            ("Print / PDF", _BTN_SECONDARY, self._on_print),
        ):
            btn = QPushButton(text)
            btn.setStyleSheet(style)
            btn.setFixedHeight(_ACTION_BUTTON_HEIGHT)
            btn.clicked.connect(handler)
            al.addWidget(btn)
        paper_label = QLabel(f"Paper: {a6_profile().size_label}")
        paper_label.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: {TYPE_HINT}px;"
            f"font-family: {FONT_FAMILY};"
            "background: transparent;"
        )
        paper_label.setAlignment(Qt.AlignCenter)
        al.addWidget(paper_label)
        layout.addWidget(actions)

        # + Add Bill button near the top, immediately above Open Bills section
        self._add_bill_btn = QPushButton("+ Add Bill")
        self._add_bill_btn.setStyleSheet(_BTN_SAVE)
        self._add_bill_btn.setFixedHeight(_ACTION_BUTTON_HEIGHT)
        self._add_bill_btn.setToolTip("Keep this draft open and start another independent bill")
        self._add_bill_btn.clicked.connect(self._on_add_bill)
        layout.addWidget(self._add_bill_btn)

        # Open Bills section - expands to use available space
        self._open_bills_group = QGroupBox("Open Bills")
        self._open_bills_group.setStyleSheet(_GROUP_BOX)
        open_bills = self._open_bills_group
        open_layout = QVBoxLayout(open_bills)
        # Tight top margin so the first card sits directly below the
        # heading (the group-box frame already reserves title space).
        open_layout.setContentsMargins(6, 6, 6, 6)
        open_layout.setSpacing(4)

        self._open_bills_scroll = QScrollArea()
        self._open_bills_scroll.setWidgetResizable(True)
        self._open_bills_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # REMOVED: setMaximumHeight(215) - was preventing cards from using available space
        self._open_bills_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Theme-safe viewport
        try:
            _p_live = palette()
            self._open_bills_scroll.setStyleSheet(
                f"QScrollArea {{ background-color: {_p_live['bg']}; border: none; }}"
                f"QScrollArea > QWidget > QWidget {{ background-color: {_p_live['bg']}; }}"
            )
        except Exception:
            pass
        self._open_bills_host = QWidget()
        try:
            self._open_bills_host.setStyleSheet("background: transparent;")
        except Exception:
            pass
        self._open_bills_layout = QVBoxLayout(self._open_bills_host)
        self._open_bills_layout.setContentsMargins(0, 0, 0, 0)
        self._open_bills_layout.setSpacing(4)
        self._open_bills_scroll.setWidget(self._open_bills_host)
        # Scroll area expands to fill the group box
        open_layout.addWidget(self._open_bills_scroll, 1)

        # Close Bill anchored at the bottom of the Open Bills section,
        # inside the group so it stays visually attached to the bill list
        # with the same group margins and spacing.
        self._close_bill_btn = QPushButton("Close Bill")
        self._close_bill_btn.setStyleSheet(_BTN_SECONDARY)
        self._close_bill_btn.setFixedHeight(_ACTION_BUTTON_HEIGHT)
        self._close_bill_btn.setToolTip("Discard the selected open bill (confirmed when it has items)")
        self._close_bill_btn.clicked.connect(self._cancel_active_open_bill)
        open_layout.addWidget(self._close_bill_btn)

        layout.addWidget(open_bills, 1)  # Open Bills group expands to fill panel

        # Live display only -- no logic attached.  The Open Bills cards and
        # the footer All-Bills summary refresh on every totals change.
        self._sale_panel.totals_changed.connect(lambda *_args: self._refresh_open_bill_cards())
        self._sale_panel.totals_changed.connect(lambda *_args: self._refresh_combined_summary())
        self._refresh_open_bill_cards()
        self._refresh_combined_summary()
        return panel

    # ------------------------------------------------------------------
    # Multiple in-memory Counter Sale drafts
    # ------------------------------------------------------------------

    def _store_active_open_bill(self) -> None:
        """Snapshot the active workspace without touching the database."""
        if getattr(self, "_active_open_bill_id", None) is not None:
            self._open_bills[self._active_open_bill_id] = self._sale_panel.draft_state()

    def _next_provisional_bill_no(self) -> str:
        """Unique in-memory CNo preview in bill-number format (no DB write).

        Starts from the database next number and advances past every
        preview already held by other open bills.
        """
        try:
            candidate = SalesDAO.generate_next_bill_no()
        except Exception:
            candidate = 'CS-0001'
        try:
            used = {
                str((s.get('bill_no') or '').strip())
                for did, s in self._open_bills.items()
                if did != self._active_open_bill_id and str((s.get('bill_no') or '').strip())
            }
            used.discard('')
            guard = 0
            while (candidate in used or SalesDAO.bill_no_exists(candidate)) and guard < 10000:
                candidate = _increment_bill_no(candidate)
                guard += 1
        except Exception:
            pass
        return candidate

    def _sync_provisional_bill_numbers(self) -> None:
        """Re-sequence provisional CNo previews for all in-memory open drafts.

        Committed invoices in the database determine the base sequence.
        Open drafts receive sequential provisional previews in order of draft_id,
        skipping any draft that is currently editing a saved invoice.
        Closing or cancelling an unsaved draft drops its preview and re-syncs,
        so the next draft or new bill is immediately eligible for the earliest
        free permanent number without gaps.
        """
        try:
            current_preview = SalesDAO.generate_next_bill_no()
        except Exception:
            current_preview = "CS-0001"
        for did in sorted(self._open_bills.keys()):
            draft = self._open_bills[did]
            if draft.get("invoice") is not None:
                continue
            draft["bill_no"] = current_preview
            draft["provisional_bill_no"] = True
            if did == self._active_open_bill_id:
                self._sale_panel.set_provisional_bill_no(current_preview)
            current_preview = _increment_bill_no(current_preview)

    def _assign_new_provisional_bill_no(self) -> None:
        """Show a fresh unique provisional CNo on the active workspace."""
        self._sale_panel.set_provisional_bill_no(self._next_provisional_bill_no())

    def _fix_conflicting_provisional_numbers(self) -> None:
        """Reassign only those provisional previews that collide with a committed invoice.

        After a save, one provisional number may now match a permanent invoice
        number in the database.  This method checks each remaining draft and
        replaces its preview only when a collision is found, leaving all
        non-conflicting previews untouched.  This keeps the cashier's view
        stable: the other open bills don't jump to new numbers just because
        one bill was saved.
        """
        # Collect all provisional bill_nos across open drafts to avoid
        # assigning a number that another draft already holds.
        used_previews = set()
        for did in sorted(self._open_bills.keys()):
            draft = self._open_bills[did]
            if draft.get("invoice") is not None:
                continue
            bno = (draft.get("bill_no") or "").strip()
            if bno:
                used_previews.add(bno)

        for did in sorted(self._open_bills.keys()):
            draft = self._open_bills[did]
            if draft.get("invoice") is not None:
                continue
            bno = (draft.get("bill_no") or "").strip()
            if not bno or not SalesDAO.bill_no_exists(bno):
                continue
            # This preview collides with a committed invoice — find a new one.
            used_previews.discard(bno)
            try:
                candidate = SalesDAO.generate_next_bill_no()
            except Exception:
                candidate = "CS-0001"
            guard = 0
            while (candidate in used_previews or SalesDAO.bill_no_exists(candidate)) and guard < 10000:
                candidate = _increment_bill_no(candidate)
                guard += 1
            draft["bill_no"] = candidate
            draft["provisional_bill_no"] = True
            used_previews.add(candidate)
            if did == self._active_open_bill_id:
                self._sale_panel.set_provisional_bill_no(candidate)

    def _combined_open_bill_totals(self) -> tuple:
        """(bill count, total qty, combined amount, combined net) over open bills.

        The active bill contributes its live panel figures; every other
        bill contributes its stored snapshot, each exactly once.  Paid
        amounts are never part of the combined figures.  UI-only: nothing
        here is written to any invoice or accounting table.
        """
        count = len(self._open_bills)
        qty = 0.0
        amount = 0.0
        net = 0.0
        for did, state in self._open_bills.items():
            try:
                if did == self._active_open_bill_id:
                    panel = self._sale_panel
                    rows = list(getattr(panel, '_item_rows', []) or [])
                    qty += sum(float(getattr(r, 'sale_qty', 0.0) or 0.0) for r in rows)
                    total = sum(float(getattr(r, 'amount', 0.0) or 0.0) for r in rows)
                    try:
                        disc = float(str(panel.bill_disc_edit.text()).strip() or 0.0)
                    except Exception:
                        disc = 0.0
                    amount += total
                    net += _round2(total - disc)
                else:
                    rows = state.get('rows') or []
                    qty += sum(float(r.get('sale_qty', 0.0) or 0.0) for r in rows)
                    total = sum(float(r.get('amount', 0.0) or 0.0) for r in rows)
                    try:
                        disc = float(str(state.get('bill_discount') or '0.00').strip() or 0.0)
                    except Exception:
                        disc = 0.0
                    amount += total
                    net += _round2(total - disc)
            except Exception:
                continue
        return count, qty, amount, net

    def _refresh_combined_summary(self, *_args) -> None:
        """Push the All-Open-Bills summary into the footer (UI-only)."""
        try:
            count, qty, amount, net = self._combined_open_bill_totals()
        except Exception:
            return
        try:
            self._sale_panel.set_combined_totals(count, qty, amount, net)
        except Exception:
            pass

    def _reserved_by_other_open_bills(self, batch_id: int) -> float:
        """Total unsaved reservation for *batch_id* outside the active bill."""
        total = 0.0
        for draft_id, state in self._open_bills.items():
            if draft_id == self._active_open_bill_id:
                continue
            original = state.get("original_batch_qty") or {}
            qty = sum(
                float(row.get("sale_qty", 0.0) or 0.0)
                for row in state.get("rows") or []
                if row.get("stock_batch_id") == batch_id
            )
            total += reserved_quantity(qty, original.get(batch_id, 0.0))
        return total

    def _open_bill_net_total(self, state: dict) -> str:
        """Net (Bill Total) for a stored draft snapshot, matching _recalc."""
        try:
            total = sum(float(row.get("amount", 0.0) or 0.0) for row in state.get("rows") or [])
        except Exception:
            total = 0.0
        try:
            discount = float(str(state.get("bill_discount") or "0.00").strip() or 0.0)
        except Exception:
            discount = 0.0
        try:
            net = _round2(total - discount + (_round2(total - discount) - (total - discount)))
        except Exception:
            net = total - discount
        return f"{net:.2f}"

    def _open_bill_card_text(self, draft_id: int, state: dict) -> str:
        """Compact three-line card for one open bill.

        Line 1: provisional CNo preview (bill-number format) + Active mark.
        Line 2: customer / patient name when entered.
        Line 3: current bill total.
        Internal draft ids are never shown.  Every line is kept short so
        nothing clips inside the fixed-width panel.
        """
        if draft_id == self._active_open_bill_id:
            live = self._sale_panel.draft_state()
            customer = self._sale_panel.customer_combo.currentText()
            patient = self._sale_panel.patient_name_edit.text().strip()
            bill_total = self._sale_panel.net_amt_label.text()
            cno = (live.get("bill_no") or "").strip() or "--"
        else:
            customer_index = self._sale_panel.customer_combo.findData(state.get("customer_id"))
            customer = (self._sale_panel.customer_combo.itemText(customer_index)
                        if customer_index >= 0 else "")
            patient = str(state.get("patient_name") or "").strip()
            bill_total = self._open_bill_net_total(state)
            cno = str(state.get("bill_no") or "").strip() or "--"
        cust_clean = (customer or "").strip()
        if cust_clean.upper().startswith("-- SELECT"):
            cust_clean = ""
        if patient:
            name_line = f"Patient: {patient}"
        elif cust_clean:
            name_line = f"Customer: {cust_clean}"
        else:
            name_line = "New customer"
        if len(name_line) > 26:
            name_line = name_line[:23] + "..."
        head = f"{cno} \u2022 Active" if draft_id == self._active_open_bill_id else cno
        if len(head) > 28:
            head = head[:25] + "..."
        return (f"{head}\n"
                f"{name_line}\n"
                f"Bill Total: \u20b9{bill_total}")

    def _refresh_open_bill_cards(self) -> None:
        """Rebuild the Open Bills card list, reusing card widgets.

        Cards are updated in place (text, highlight, tooltip) and only
        created or destroyed when the draft set itself changes.  Recreating
        every button on each keystroke left ``deleteLater``-pending cards
        painting over the new ones, which read as clipped/overlapping
        draft labels.  The draft snapshot stays the source of truth.
        """
        if not hasattr(self, "_open_bills_layout"):
            return
        # Detach live cards for reuse, keyed by their stable draft id.
        reusable: dict[int, object] = {}
        while self._open_bills_layout.count():
            item = self._open_bills_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            try:
                did = widget.property("draft_id")
            except Exception:
                did = None
            try:
                is_card = isinstance(widget, _OpenBillCard)
            except Exception:
                is_card = False
            if is_card and isinstance(did, int) and did in self._open_bills:
                reusable[did] = widget
            else:
                try:
                    widget.deleteLater()
                except Exception:
                    pass
        p = palette()
        for draft_id in sorted(self._open_bills.keys()):
            state = self._open_bills[draft_id]
            selected = draft_id == self._active_open_bill_id
            button = reusable.pop(draft_id, None)
            if button is None:
                button = _OpenBillCard(self._open_bill_card_text(draft_id, state))
                button.setObjectName("OpenBillCard")
                button.setCursor(Qt.PointingHandCursor)
                # Three compact lines (CNo / name / total): CARD_HEIGHT keeps
                # every line inside its own card; shorter clipped the last
                # lines so they painted over the next card.
                button.pin_height()
                try:
                    button.setProperty("draft_id", draft_id)
                except Exception:
                    pass
                button.clicked.connect(lambda _checked=False, did=draft_id: self._select_open_bill(did))
            else:
                button.setText(self._open_bill_card_text(draft_id, state))
            button.setStyleSheet(
                "QPushButton { text-align: left; padding: 5px 7px;"
                f" background-color: {p['selected'] if selected else p['surface_alt']};"
                f" color: {p['text']};"
                f" border: {'2px' if selected else '1px'} solid {p['accent'] if selected else p['border']};"
                " border-radius: 3px; font-size: 12px; font-family: 'Segoe UI'; }"
                f"QPushButton:hover {{ border: 2px solid {p['accent']}; }}"
            )
            # Bold the active card without rebuilding on every keystroke.
            try:
                font = button.font()
                font.setBold(selected)
                button.setFont(font)
            except Exception:
                pass
            try:
                _tip_head = self._open_bill_card_text(draft_id, state).split("\n")[0]
            except Exception:
                _tip_head = str(state.get("bill_no") or "")
            button.setToolTip(
                f"Open bill {_tip_head} -- items, customer and totals restored exactly"
            )
                        # Re-pin LAST (see pin_height): the updates above reset the
            # explicit minimum, which would let the scroll layout compress
            # the card and clip its last two lines.
            button.pin_height()
            self._open_bills_layout.addWidget(button)
        for stale in reusable.values():
            try:
                stale.deleteLater()
            except Exception:
                pass
        # One stretch only: leftovers from a previous build were detached
        # above (the stretch is a spacer, not a widget, so it is gone).
        self._open_bills_layout.addStretch()
        # Guarantee vertical room for every full-height card: the scroll
        # host keeps at least N * CARD_HEIGHT so the layout never has to
        # compress cards into its viewport (compression clipped the last
        # two lines).  Taller viewports simply leave the extra room to the
        # stretch above; shorter ones scroll.
        try:
            n = len(self._open_bills)
            spacing = self._open_bills_layout.spacing()
            self._open_bills_host.setMinimumHeight(
                n * _OpenBillCard.CARD_HEIGHT + max(0, n - 1) * spacing
            )
        except Exception:
            pass
        # Final sweep: re-pin every live card and re-run the layout so no
        # card keeps a style-reset minimum (~34 px) that would compress it
        # to ~49 px and clip its last two lines.
        try:
            for idx in range(self._open_bills_layout.count()):
                w = self._open_bills_layout.itemAt(idx).widget()
                if w is not None and isinstance(w, _OpenBillCard):
                    w.pin_height()
        except Exception:
            pass
        try:
            self._open_bills_layout.invalidate()
            self._open_bills_layout.activate()
        except Exception:
            pass
    def _select_open_bill(self, draft_id: int) -> None:
        if draft_id not in self._open_bills or draft_id == self._active_open_bill_id:
            return
        self._store_active_open_bill()
        self._active_open_bill_id = draft_id
        self._sale_panel.load_draft_state(self._open_bills[draft_id])
        self._sale_panel.set_other_draft_reservation_provider(self._reserved_by_other_open_bills)
        self._refresh_open_bill_cards()
        self._refresh_combined_summary()
        self._sale_panel.focus_item_name()

    def _on_add_bill(self) -> None:
        if not self._confirm_new_sale_under_historical_fy():
            return
        self._store_active_open_bill()
        draft_id = self._next_open_bill_id
        self._next_open_bill_id += 1
        self._active_open_bill_id = draft_id
        self._sale_panel.reset_for_new()
        # Unique in-memory CNo preview: no invoice record is written and the
        # permanent sequence is untouched until Save.
        self._assign_new_provisional_bill_no()
        self._open_bills[draft_id] = self._sale_panel.draft_state()
        self._sync_provisional_bill_numbers()
        self._refresh_open_bill_cards()
        self._refresh_combined_summary()
        self._sale_panel.focus_item_name()

    def _remove_active_open_bill(self) -> None:
        self._open_bills.pop(self._active_open_bill_id, None)
        if self._open_bills:
            self._active_open_bill_id = next(iter(self._open_bills))
            self._sale_panel.load_draft_state(self._open_bills[self._active_open_bill_id])
        else:
            self._active_open_bill_id = self._next_open_bill_id
            self._next_open_bill_id += 1
            self._sale_panel.reset_for_new()
            self._assign_new_provisional_bill_no()
            self._open_bills[self._active_open_bill_id] = self._sale_panel.draft_state()
        self._sync_provisional_bill_numbers()
        self._sale_panel.set_other_draft_reservation_provider(self._reserved_by_other_open_bills)
        self._refresh_open_bill_cards()
        self._refresh_combined_summary()
        self._sale_panel.focus_item_name()

    def _cancel_active_open_bill(self) -> None:
        state = self._sale_panel.draft_state()
        if state.get("rows"):
            answer = QMessageBox.question(
                self, "Close Bill", "Discard this open bill and its items? Other open bills are unchanged.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self._remove_active_open_bill()

    def _apply_history_height(self):
        """Keep the daily sales region compact to maximize billing area."""
        page_height = self.height()
        if page_height < 200:          # before the first real resize
            page_height = 720
        target = int(page_height * 0.22)
        target = max(110, min(target, 200))
        bar_height = self._history_filter_bar.sizeHint().height()
        if bar_height <= 0:
            bar_height = _HISTORY_FILTER_BAR_HEIGHT
        self._hist_table.setFixedHeight(max(70, target - bar_height))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_history_height()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_history_height()

    def _flbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    def refresh_theme(self) -> None:
        """Re-apply live Day/Night colours in place (state preserved).

        Refreshes the header strip, history filter bar + history table, the
        embedded sale panel (entry bar, Bill Items grid, totals) and the
        right-side Bill panel — without rebuilding, so bill drafts, history
        scroll position and focus survive the switch.
        """
        try:
            p = palette()
        except Exception:
            return
        try:
            self.setStyleSheet(f"background-color: {p['bg']};")
        except Exception:
            pass
        # Sale panel first (entry bar, Bill Items, totals).
        try:
            if hasattr(self, "_sale_panel") and hasattr(self._sale_panel, "refresh_theme"):
                self._sale_panel.refresh_theme()
        except Exception:
            pass
        # History table + header (controlled-height region above Bill Items).
        try:
            if hasattr(self, "_hist_table"):
                self._hist_table.setStyleSheet(_fresh_history_table_style(p))
                self._hist_table.horizontalHeader().setStyleSheet(
                    _fresh_history_header_style(p)
                )
        except Exception:
            pass
        # Radios, filter buttons, New Sale.
        try:
            if hasattr(self, "_hist_item_mode"):
                self._hist_item_mode.setStyleSheet(_fresh_radio_style(p))
            if hasattr(self, "_hist_bill_mode"):
                self._hist_bill_mode.setStyleSheet(_fresh_radio_style(p))
        except Exception:
            pass
        try:
            if hasattr(self, "_new_btn"):
                self._new_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
            for attr in ("_hist_all_btn", "_hist_refresh_btn"):
                btn = getattr(self, attr, None)
                if btn is not None:
                    btn.setStyleSheet(_fresh_btn_style(p["text_dim"], p))
        except Exception:
            pass
        # Right-side Bill panel: + Add Bill, Open Bills group, scroll
        # viewport/host and Close Bill — all live palette so no stale
        # Day/Night surface or black rectangle survives a switch.
        try:
            if hasattr(self, "_bill_panel"):
                self._bill_panel.setStyleSheet(
                    f"#BillPanel {{ background-color: {p['surface']};"
                    f"  border-left: 1px solid {p['border']}; }}"
                )
            for grp_attr in ("_bill_actions_group", "_open_bills_group"):
                grp = getattr(self, grp_attr, None)
                if grp is not None:
                    grp.setStyleSheet(_group_box_style(p))
            if hasattr(self, "_add_bill_btn"):
                self._add_bill_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
            if hasattr(self, "_close_bill_btn"):
                self._close_bill_btn.setStyleSheet(_fresh_btn_style(p["text_dim"], p))
            if hasattr(self, "_open_bills_scroll"):
                self._open_bills_scroll.setStyleSheet(
                    f"QScrollArea {{ background-color: {p['bg']}; border: none; }}"
                    f"QScrollArea > QWidget > QWidget {{ background-color: {p['bg']}; }}"
                )
            if hasattr(self, "_open_bills_host"):
                self._open_bills_host.setStyleSheet("background: transparent;")
        except Exception:
            pass
        try:
            self._refresh_open_bill_cards()
        except Exception:
            pass
        # Header strip + filter bar backgrounds.
        try:
            refresh_cs_tree(self)
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    def _refresh_history(self):
        self._history_offset = 0
        self._history_has_more = True
        self._history_loading = False
        self._hist_table.setRowCount(0)
        self._load_more_history()

    def _on_history_scroll(self, value: int):
        scrollbar = self._hist_table.verticalScrollBar()
        if (self._hist_table.rowCount() and self._history_has_more and
                not self._history_loading and value >= scrollbar.maximum()):
            self._load_more_history()

    def _load_more_history(self):
        if self._history_loading or not self._history_has_more:
            return
        self._history_loading = True
        sorting_enabled = self._hist_table.isSortingEnabled()
        bill_wise = self._history_mode_is_bill()
        start_date, end_date = self._history_filter_dates()
        try:
            if bill_wise:
                rows = SalesDAO.get_bill_history_page(
                    limit=self.HISTORY_PAGE_SIZE, offset=self._history_offset,
                    start_date=start_date, end_date=end_date,
                )
            else:
                rows = SalesDAO.get_history_page(
                    limit=self.HISTORY_PAGE_SIZE, offset=self._history_offset,
                    start_date=start_date, end_date=end_date,
                )
            if not rows:
                self._history_has_more = False
                return
            page_invoice_count = len({row["invoice_id"] for row in rows})
            self._history_has_more = page_invoice_count == self.HISTORY_PAGE_SIZE
            self._history_offset += self.HISTORY_PAGE_SIZE

            table = self._hist_table
            table.setSortingEnabled(False)
            first_row = table.rowCount()
            table.setRowCount(first_row + len(rows))
            for row_index, row in enumerate(rows, first_row):
                if bill_wise:
                    self._fill_bill_history_row(table, row_index, row)
                else:
                    self._fill_item_history_row(table, row_index, row)
            table.setSortingEnabled(sorting_enabled)
        finally:
            self._history_loading = False

    @staticmethod
    def _money_cell(value) -> QTableWidgetItem:
        cell = QTableWidgetItem(f"{float(value or 0):.2f}")
        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return cell

    def _fill_item_history_row(self, table: QTableWidget, row_index: int,
                               row: dict):
        """One row per sale item; the bill number repeats on each item row."""
        table.setItem(row_index, 0, QTableWidgetItem(row.get("bill_no") or ""))
        table.setItem(row_index, 1, QTableWidgetItem(row.get("sale_type") or ""))
        table.setItem(row_index, 2, QTableWidgetItem(row.get("item_name") or ""))
        table.setItem(row_index, 3, self._money_cell(row.get("mrp")))

        qty_item = QTableWidgetItem(f"{float(row.get('sale_qty') or 0):.0f}")
        qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        table.setItem(row_index, 4, qty_item)

        table.setItem(row_index, 5, self._money_cell(row.get("amount")))
        table.setItem(row_index, 6, QTableWidgetItem(row.get("patient_name") or ""))
        table.setItem(row_index, 7, QTableWidgetItem(row.get("pack_size") or ""))
        table.setItem(row_index, 8, QTableWidgetItem(row.get("batch_no") or ""))
        table.setItem(row_index, 9, QTableWidgetItem(row.get("expiry") or ""))
        table.setItem(row_index, 10, QTableWidgetItem(row.get("sale_time") or ""))
        table.setItem(row_index, 11,
                      self._money_cell(row.get("discount_amount")))
        table.setItem(row_index, 12, self._money_cell(row.get("net_amount")))
        table.item(row_index, 0).setData(Qt.UserRole, row["invoice_id"])

    def _fill_bill_history_row(self, table: QTableWidget, row_index: int,
                               row: dict):
        """Exactly one row per bill, from bill-level columns only."""
        table.setItem(row_index, 0, QTableWidgetItem(row.get("bill_no") or ""))
        table.setItem(row_index, 1, QTableWidgetItem(row.get("sale_type") or ""))
        table.setItem(row_index, 2, QTableWidgetItem(row.get("patient_name") or ""))
        table.setItem(row_index, 3, QTableWidgetItem(row.get("sale_date") or ""))
        table.setItem(row_index, 4, QTableWidgetItem(row.get("sale_time") or ""))
        table.setItem(row_index, 5,
                      QTableWidgetItem(str(row.get("item_count") or 0)))
        table.setItem(row_index, 6, self._money_cell(row.get("total_amount")))
        table.setItem(row_index, 7, self._money_cell(row.get("discount")))
        table.setItem(row_index, 8, self._money_cell(row.get("paid_amount")))
        table.setItem(row_index, 9, self._money_cell(row.get("net_amount")))
        table.item(row_index, 0).setData(Qt.UserRole, row["invoice_id"])

    def _selected_history_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self._hist_table.item(row, 0).data(Qt.UserRole)

    def _on_new(self):
        """Start a new sale inline: reset the form, focus Item Name."""
        if not self._confirm_new_sale_under_historical_fy():
            return
        self._start_new_sale()

    def _start_new_sale(self):
        """The single New Sale path, shared by the button and the guard."""
        # Multi-bill safety: New Sale clears the *active* draft only.  Other
        # open bills are untouched, but silently discarding the active bill's
        # items would lose data, so confirm first when it is non-empty.
        try:
            if self._sale_panel.draft_state().get("rows"):
                answer = QMessageBox.question(
                    self, "New Sale",
                    "Clear the active bill and start a new one? "
                    "Other open bills are unchanged.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
        except Exception:
            pass
        self._editing_invoice_id = None
        self._sale_panel.reset_for_new()
        # The new bill always carries the live date.  The history date and
        # the viewed financial year are display state only and must never
        # reach the new bill, so the live date is re-stamped here.
        self._sale_panel._set_current_datetime()
        self._assign_new_provisional_bill_no()
        self._open_bills[self._active_open_bill_id] = self._sale_panel.draft_state()
        self._sync_provisional_bill_numbers()
        self._sale_panel.set_other_draft_reservation_provider(self._reserved_by_other_open_bills)
        self._refresh_open_bill_cards()
        self._refresh_combined_summary()
        self._sale_panel.focus_item_name()

    def _on_edit(self):
        try:
            auth.session.require(auth.PERM_EDIT_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Edit Sale", "Please select a bill to edit.")
            return
        inv = SalesDAO.get_by_id(inv_id)
        if not inv:
            QMessageBox.warning(self, "Edit Sale", "Could not load bill data.")
            return
        # Do not silently discard an unsaved multi-bill draft.
        try:
            if self._sale_panel.draft_state().get("rows"):
                answer = QMessageBox.question(
                    self, "Edit Sale",
                    "Load the selected history bill into the active draft? "
                    "Unsaved items in the active bill will be replaced. "
                    "Other open bills are unchanged.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
        except Exception:
            pass
        self._editing_invoice_id = inv_id
        self._sale_panel.load_invoice(inv)
        # Keep the multi-bill workspace consistent: the edited invoice now
        # owns the active slot (non-provisional), reservations recalculated.
        try:
            self._open_bills[self._active_open_bill_id] = self._sale_panel.draft_state()
            self._sale_panel.set_other_draft_reservation_provider(
                self._reserved_by_other_open_bills
            )
            self._refresh_open_bill_cards()
        except Exception:
            pass
        self._sale_panel.focus_item_name()

    def _on_delete(self):
        try:
            auth.session.require(auth.PERM_DELETE_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Delete Sale", "Please select a bill to delete.")
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            "Are you sure you want to delete this sale? Stock will be restored.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                SalesDAO.delete_invoice(inv_id)
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete sale:\n{e}")

    def _on_print(self):
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Print Sale", "Please select a bill to print.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Sales Bill PDF", "sales_bill.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            output = generate_counter_sale_bill(inv_id, path)
            QMessageBox.information(self, "PDF Saved", f"A6 receipt saved to:\n{output}")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Sale", str(exc))

    def _on_direct_print(self):
        """Send the selected bill straight to the Windows print dialog on A6."""
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Print Sale", "Please select a bill to print.")
            return
        try:
            print_pharmacy_a6_bill(inv_id, self, "Counter Sale Bill")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Sale", str(exc))

    def _open_sale_dialog(self, invoice: dict | None = None,
                          hold_bill_data: dict | None = None):
        """Backwards-compatible entry point â€” the sale area is inline now.

        Kept so existing callers keep working; no dialog is opened and no
        transaction logic is duplicated.
        """
        # Resuming a held bill must never silently discard the active
        # multi-bill draft.  If the active workspace holds unsaved items,
        # keep it and open the held bill in a fresh draft slot instead.
        try:
            active_has_rows = bool(self._sale_panel.draft_state().get("rows"))
        except Exception:
            active_has_rows = False
        if (invoice is not None or hold_bill_data is not None) and active_has_rows:
            try:
                self._store_active_open_bill()
            except Exception:
                pass
            try:
                draft_id = self._next_open_bill_id
                self._next_open_bill_id += 1
                self._active_open_bill_id = draft_id
            except Exception:
                pass
        if invoice is not None:
            self._sale_panel.load_invoice(invoice)
        elif hold_bill_data is not None:
            self._sale_panel.load_hold(hold_bill_data)
        else:
            self._sale_panel.reset_for_new()
            self._assign_new_provisional_bill_no()
        self._open_bills[self._active_open_bill_id] = self._sale_panel.draft_state()
        self._sale_panel.set_other_draft_reservation_provider(self._reserved_by_other_open_bills)
        self._refresh_open_bill_cards()
        self._refresh_combined_summary()
        self._sale_panel.focus_item_name()

    def open_sale_dialog_with_hold(self, hold_bill_data: dict):
        """Load a held bill into the inline sale area (called from HoldBillPage).

        The resumed bill appears in the same Region B position as any new
        sale; Hold/Resume behaviour itself is unchanged.
        """
        self._open_sale_dialog(hold_bill_data=hold_bill_data)
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    # Inline sale-area lifecycle
    # ------------------------------------------------------------------

    def _on_sale_saved(self):
        # Commit applies to this workspace only.  Drop it after the existing
        # atomic DAO save, then restore another unsaved bill if one exists.
        # Unlike cancel/close, a save must NOT re-sequence every remaining
        # draft's provisional number: the cashier sees stable previews while
        # working with multiple open bills.  Only fix a preview that now
        # collides with a committed invoice in the database.
        self._editing_invoice_id = None
        self._refresh_history()
        self._open_bills.pop(self._active_open_bill_id, None)
        if self._open_bills:
            self._active_open_bill_id = next(iter(self._open_bills))
            self._sale_panel.load_draft_state(self._open_bills[self._active_open_bill_id])
        else:
            self._active_open_bill_id = self._next_open_bill_id
            self._next_open_bill_id += 1
            self._sale_panel.reset_for_new()
            self._assign_new_provisional_bill_no()
            self._open_bills[self._active_open_bill_id] = self._sale_panel.draft_state()
        # Fix only conflicting provisionals (preview now taken by a saved bill)
        # without reassigning every draft's number from scratch.
        self._fix_conflicting_provisional_numbers()
        self._sale_panel.set_other_draft_reservation_provider(self._reserved_by_other_open_bills)
        self._refresh_open_bill_cards()
        self._refresh_combined_summary()
        self._sale_panel.focus_item_name()

    def _on_sale_held(self):
        # Holding persists only the selected draft through the established
        # hold DAO; other open workspaces remain in memory unchanged.
        self._editing_invoice_id = None
        self._refresh_history()
        self._remove_active_open_bill()

    def _on_sale_cancelled(self):
        self._cancel_active_open_bill()
