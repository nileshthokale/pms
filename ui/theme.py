"""Central theme (light / night mode) manager for the application UI.

Phase 6E — Pharma-WINNER style light desktop theme
--------------------------------------------------
This module owns the ONE centralized palette used by the whole
application. Every screen reads its colours from here (directly through
`palette()` or through the reusable helpers in `ui.components`) instead
of hard-coding colours locally.

Design goals (see docs/phase6e_ui_redesign.md):

* Light, traditional Windows pharmacy/accounting look is the DEFAULT.
* White workspace/table bodies, very light blue panels and table header
  rows, soft blue-grey borders, dark navy text, restrained semantic
  colours, compact controls.
* Night mode is kept as an optional feature and must not affect any
  business logic.

The module is importable without PySide6 (headless) so the persistence,
palette and change-notification logic can be unit-tested. Qt-dependent
behaviour (screen module reload, signal emission) degrades gracefully
when PySide6 is unavailable.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    from PySide6.QtCore import QObject, Signal
    _HAS_QT = True
except ImportError:  # headless (e.g. test environments)
    _HAS_QT = False


# ── Central palettes ──────────────────────────────────────────────────
# The first seven keys are the legacy contract every screen module binds
# at import time:  bg / surface / border / accent / accent_hover / text /
# text_dim.  The remaining keys are the richer Phase 6E tokens consumed
# by ui/components.py.
#
# "light" is the primary visual reference (traditional pharmacy desktop
# software).  "night" keeps the original dark look as an option.
_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        # legacy keys -------------------------------------------------
        "bg": "#ffffff",            # white main workspace / table body
        "surface": "#dce9f6",       # very light blue panels, page header strip,
                                    # filter bars and table header rows
        "border": "#9db6cc",        # soft blue-grey border
        "accent": "#2f6fb0",        # classic desktop blue (primary actions)
        "accent_hover": "#255d94",
        # Normal readable text is TRUE BLACK in the light theme: table data,
        # headers, labels, input values and totals must all read as solid
        # black on the white workspace, not as a washed-out navy.
        "text": "#000000",          # primary text (black)
        "text_dim": "#55677a",      # dark grey secondary text (hints only)
        # extended Phase 6E tokens -----------------------------------
        "surface_alt": "#f3f8fc",   # barely-tinted panel / zebra row
        "table_header": "#dce9f6",  # table header row
        "header_text": "#000000",   # page/table header text (black)
        "grid": "#c5d4e2",          # table grid lines
        "selected": "#cfe2f3",      # selected row (light blue)
        "selected_text": "#000000",
        "accent_pressed": "#1d4a78",
        "success": "#2e7d32",
        "success_hover": "#24662a",
        "danger": "#b23a3a",
        "danger_hover": "#8f2d2d",
        "warning": "#b26a00",
        "warning_hover": "#8f5500",
        "focus": "#2f6fb0",
        "disabled_text": "#9aa7b4",
        "disabled_bg": "#e9eef3",
        # Tooltip note.  Day Mode keeps the classic light-yellow note with
        # dark text: readable over the light workspace.  These three values
        # are deliberately distinct from every other palette entry so the
        # role-based colour migration used by the refresh pass can never
        # mistake them for a surface or text role.
        "tooltip_bg": "#ffffe1",
        "tooltip_text": "#14212e",
        "tooltip_border": "#b8b88a",
    },
    "dark": {
        # legacy keys (original night look, unchanged) ---------------
        "bg": "#000000",
        "surface": "#1a1a1a",
        "border": "#333333",
        "accent": "#2e7d32",
        "accent_hover": "#388e3c",
        "text": "#ffffff",
        "text_dim": "#aaaaaa",
        # extended Phase 6E tokens -----------------------------------
        "surface_alt": "#141414",
        "table_header": "#1a1a1a",
        "header_text": "#ffffff",
        "grid": "#333333",
        "selected": "#2e7d32",
        "selected_text": "#ffffff",
        "accent_pressed": "#1b5e20",
        "success": "#2e7d32",
        "success_hover": "#388e3c",
        "danger": "#c62828",
        "danger_hover": "#d32f2f",
        "warning": "#ff9800",
        "warning_hover": "#e68a00",
        "focus": "#388e3c",
        "disabled_text": "#777777",
        "disabled_bg": "#242424",
        # Night Mode tooltip: dark note, light text.  The old light-yellow
        # note was unreadable against the dark workspace.
        "tooltip_bg": "#2b2b2b",
        "tooltip_text": "#e8e8e8",
        "tooltip_border": "#4a4a4a",
    },
}

# Backwards-compatible alias for the night mode name.
_PALETTES["night"] = _PALETTES["dark"]


# Single desktop-friendly font family for the whole application.
# Lives in the theme (the lowest UI layer) so both the application-wide
# stylesheet and every screen/component resolve the same family.
FONT_FAMILY = "'Segoe UI', 'Tahoma', sans-serif"
# Concrete family name for building QFont objects (QFont takes one family,
# not a CSS font stack).  Kept next to FONT_FAMILY so the two never drift.
FONT_NAME = "Segoe UI"


# ── Typography scale (px) ─────────────────────────────────────────────
# ONE shared type scale for the whole application, so every screen renders
# the same readable hierarchy: a classic pharmacy/ERP desktop look with
# large, bold, black text inside the existing (unchanged) spacing.
#
# Sizes are CSS **px** (Qt stylesheet units), never **pt**: a stylesheet
# ``10pt`` renders at 10 x 96/72 ~= 13.3 px, so mixing the two units in the
# same UI made the same nominal "size" render at two different heights.
# Everything below is the single source of truth — screens must not invent
# their own numbers.
#
# Minimum sizes are guarded by tests (see test_ui_typography.py): table data
# never drops below ``TABLE_DATA``, table headers never below ``TABLE_HEADER``.
# Baseline is ~11-12 pt for ordinary UI text (≈15-16 px at 96 dpi), with larger
# section headings and totals.  Hierarchy is preserved: titles outweigh
# section headers, which outweigh table text; values outweigh plain data.
TYPE_PAGE_TITLE = 22        # "Sales / Counter Sale", "Item Master", APP_TITLE
TYPE_SECTION_HEADER = 17    # "Bill History", "Bill Items", report sections
TYPE_TABLE_HEADER = 15      # column captions (bold, black)
TYPE_TABLE_DATA = 15        # cell values — the most important size
TYPE_FORM_LABEL = 15        # "Bill No", "Item", "MRP", "Qty" captions
TYPE_INPUT = 15             # roomy inputs (entry bar, forms, dialogs)
TYPE_INPUT_COMPACT = 14     # inputs inside a fixed 30 px control box
TYPE_VALUE = 17             # totals / important values (bold)
TYPE_VALUE_EMPHASIS = 20    # NET AMT and other headline figures (bold)
TYPE_BUTTON = 15            # button captions
TYPE_HINT = 13              # genuinely secondary hints (dimmed)

# Ordering the hierarchy depends on: a page title must always outweigh
# table text, and table text must never collapse below the readable floor.
assert TYPE_TABLE_DATA >= 12, "table data must stay readable"
assert TYPE_TABLE_HEADER >= 12, "table headers must stay readable"
assert TYPE_PAGE_TITLE > TYPE_TABLE_DATA, "page title must outrank table text"

_THEME_FILE = Path(__file__).resolve().parent.parent / "data" / "theme.json"


def _resolve_theme_file() -> Path:
    """Packaging-aware theme file location (test-patch compatible).

    Development runs use ``data/theme.json`` (the patchable ``_THEME_FILE``).
    A PyInstaller build (``sys.frozen``) stores the theme next to the
    per-user database so the EXE never writes beside itself.
    Unit tests patch ``_THEME_FILE`` with ``sys.frozen`` unset, so they
    always resolve to the patched path.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        return Path(base) / "PharmacyManagementSystem" / "theme.json"
    return Path(_THEME_FILE)

# Light mode is the default; night mode is opt-in.  Kept as a constant so
# the default is stated once and reused by tests.
DEFAULT_MODE = "light"

# Navigation / header chrome per mode.  Keys are part of the public
# contract (test_theme.py) and must stay stable.
_NAV_SCHEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#2e7d32",
        "border": "#1b5e20",
        "text": "#ffffff",
        "hover": "#388e3c",
        "pressed": "#1b5e20",
        "theme_btn_bg": "#1b5e20",
        "theme_btn_text": "#ffffff",
        "theme_btn_hover": "#388e3c",
    },
    "light": {
        "bg": "#dce9f6",            # light blue menu strip
        "border": "#9db6cc",
        "text": "#14212e",
        "hover": "#c6dbf0",
        "pressed": "#b3cee8",
        "theme_btn_bg": "#2f6fb0",  # classic blue mode button
        "theme_btn_text": "#ffffff",
        "theme_btn_hover": "#255d94",
    },
}


def _load_mode() -> str:
    try:
        with open(_resolve_theme_file(), "r", encoding="utf-8") as fh:
            mode = json.load(fh).get("mode")
        # Accept the legacy "night" spelling too.
        if mode == "night":
            return "dark"
        if mode in _PALETTES:
            return mode
    except (OSError, ValueError):
        pass
    return DEFAULT_MODE


def _save_mode(mode: str) -> None:
    theme_file = _resolve_theme_file()
    theme_file.parent.mkdir(parents=True, exist_ok=True)
    with open(theme_file, "w", encoding="utf-8") as fh:
        json.dump({"mode": mode}, fh)


def _reload_screen_modules() -> None:
    """Reload screen modules so their palette reads pick up the new mode.

    Only possible when PySide6 is available (screens import it at module
    level). Submodules are reloaded first, then the screens package so
    its class re-exports point at the reloaded classes.
    """
    if not _HAS_QT:
        return
    import importlib

    subs = [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("screens.") and module is not None
    ]
    for module in subs:
        importlib.reload(module)
    pkg = sys.modules.get("screens")
    if pkg is not None:
        importlib.reload(pkg)


class ThemeManager:
    """Application-wide light / night theme manager."""

    def __init__(self):
        self._mode = _load_mode()
        self._callbacks: list = []

    # ── queries ──────────────────────────────────────────────────────
    def mode(self) -> str:
        return self._mode

    def is_dark(self) -> bool:
        return self._mode == "dark"

    def palette(self) -> dict[str, str]:
        return _PALETTES[self._mode]

    # ── commands ─────────────────────────────────────────────────────
    def set_mode(self, mode: str, notify: bool = True) -> None:
        if mode == "night":
            mode = "dark"
        if mode not in _PALETTES:
            raise ValueError(f"Unknown theme mode '{mode}'.")
        if mode == self._mode and notify is False:
            return
        self._mode = mode
        _save_mode(mode)
        if notify:
            self.apply()

    def toggle(self) -> str:
        self.set_mode("light" if self.is_dark() else "dark")
        return self._mode

    def apply(self) -> None:
        """Propagate the current mode to the live application.

        Order matters for the black-rectangle fix:

        1. Application palette + stylesheet first, so dialogs, menus,
           tooltips, combo dropdowns, completer popups, calendar popups
           and any widget following the app theme refresh immediately.
        2. Reload screen modules (best effort) so widgets created AFTER
           the switch bake the new centralized colours at construction.
        3. Notify listeners for IN-PLACE refresh of existing widgets
           (pages, navigation bar, open dialogs/popups).  Existing widgets
           must not retain stale baked hex values (dark ``#000000`` in Day
           Mode or light ``#ffffff`` in Night Mode).
        """
        try:
            apply_to_app()
        except Exception:
            pass
        try:
            _reload_screen_modules()
        except Exception:
            pass
        try:
            self._notify()
        finally:
            try:
                repolish_all()
            except Exception:
                pass

    # ── change notification ──────────────────────────────────────────
    def on_changed(self, callback) -> None:
        """Register a callback invoked as callback(mode) after a change."""
        self._callbacks.append(callback)

    def _notify(self) -> None:
        for callback in list(self._callbacks):
            callback(self._mode)


def palette() -> dict[str, str]:
    """Return the color palette of the current theme mode.

    Module-level convenience used by every screen module at import:
        from ui.theme import palette
    """
    return theme_manager.palette()


def nav_palette() -> dict[str, str]:
    """Return the navigation bar color scheme for the current mode.

    Night mode: green bar, white text (the original look).
    Light mode: light blue menu strip, dark text.
    """
    return _NAV_SCHEMES[theme_manager.mode()]


def apply_palette(app=None) -> None:
    """Apply the centralized theme colours to the application QPalette.

    Stylesheets cover widgets that declare explicit colours, but plain
    containers (QFrame, QScrollArea viewports, QCalendarWidget internals,
    table corner buttons, header views and any widget without its own
    stylesheet) paint from the QPalette.  Without this, those surfaces keep
    the Fusion light defaults in Night Mode (white flashes) or retain a
    stale dark Window colour in Day Mode (black rectangles).  Every colour
    comes from the centralized palette — nothing is hardcoded.
    """
    try:
        from PySide6.QtGui import QPalette, QColor
        from PySide6.QtWidgets import QApplication
    except ImportError:  # headless
        return
    if app is None:
        try:
            app = QApplication.instance()
        except Exception:
            return
    if app is None:
        return
    p = palette()
    try:
        bg = QColor(p["bg"])
        surface = QColor(p["surface"])
        surface_alt = QColor(p.get("surface_alt", p["bg"]))
        text = QColor(p["text"])
        text_dim = QColor(p["text_dim"])
        accent = QColor(p["accent"])
        selected = QColor(p["selected"])
        selected_text = QColor(p["selected_text"])
        border = QColor(p["border"])
        disabled_bg = QColor(p.get("disabled_bg", p["bg"]))
        disabled_text = QColor(p.get("disabled_text", p["text_dim"]))
        grid = QColor(p.get("grid", p["border"]))
    except Exception:
        return
    pal = QPalette()
    # Base window / text roles — the source of truth for unstyled widgets.
    pal.setColor(QPalette.Window, bg)
    pal.setColor(QPalette.WindowText, text)
    pal.setColor(QPalette.Base, bg)
    pal.setColor(QPalette.AlternateBase, surface_alt)
    pal.setColor(QPalette.Text, text)
    pal.setColor(QPalette.Button, surface)
    pal.setColor(QPalette.ButtonText, text)
    pal.setColor(QPalette.Highlight, selected)
    pal.setColor(QPalette.HighlightedText, selected_text)
    pal.setColor(QPalette.Light, surface_alt)
    pal.setColor(QPalette.Midlight, surface)
    pal.setColor(QPalette.Mid, border)
    pal.setColor(QPalette.Dark, border)
    pal.setColor(QPalette.Shadow, border)
    # Grid / placeholder text follows the dim token, never pure black.
    try:
        pal.setColor(QPalette.PlaceholderText, text_dim)
        pal.setColor(QPalette.BrightText, selected_text)
        pal.setColor(QPalette.Link, accent)
        pal.setColor(QPalette.LinkVisited, accent)
    except Exception:
        pass
    # Tooltips follow the mode: a light note in Day Mode, a dark note with
    # light text in Night Mode.  Both come from the centralized palette so
    # the QPalette path and the stylesheet path can never disagree.
    try:
        pal.setColor(QPalette.ToolTipBase, QColor(p["tooltip_bg"]))
        pal.setColor(QPalette.ToolTipText, QColor(p["tooltip_text"]))
    except Exception:
        pass
    # Disabled state stays legible (dim text on muted bg, never black).
    pal.setColor(QPalette.Disabled, QPalette.Window, disabled_bg)
    pal.setColor(QPalette.Disabled, QPalette.Base, disabled_bg)
    pal.setColor(QPalette.Disabled, QPalette.Button, disabled_bg)
    pal.setColor(QPalette.Disabled, QPalette.AlternateBase, disabled_bg)
    pal.setColor(QPalette.Disabled, QPalette.WindowText, disabled_text)
    pal.setColor(QPalette.Disabled, QPalette.Text, disabled_text)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, disabled_text)
    pal.setColor(QPalette.Disabled, QPalette.Highlight, disabled_bg)
    pal.setColor(QPalette.Disabled, QPalette.HighlightedText, disabled_text)
    try:
        app.setPalette(pal)
    except Exception:
        pass


def apply_to_app(app=None) -> None:
    """Apply the full theme (palette + application stylesheet) to the app.

    Central entry point used at startup and on every Day/Night switch so
    dialogs, message boxes, menus, tooltips, combo dropdowns, completer
    popups, calendar popups and any widget without its own stylesheet all
    follow the centralized colours immediately.
    """
    apply_palette(app)
    try:
        from PySide6.QtWidgets import QApplication
        if app is None:
            app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet())
            _install_tooltip_filter(app)
    except Exception:
        pass


def repolish_all() -> None:
    """Force every existing widget to re-evaluate style/palette.

    Required after a Day/Night switch: widgets that rely on the application
    stylesheet or the QPalette (popups, calendar views, scroll-area
    viewports, menus, tooltips) only repaint with the new colours once they
    are unpolished/polished and updated.  Widget-level stylesheets with
    baked hex values are refreshed separately by their owners (see
    ``ui.components.refresh_tree`` and each screen's ``refresh_theme``);
    this handles everything that follows the application theme.
    """
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        widgets = list(app.allWidgets())
    except Exception:
        return
    for widget in widgets:
        try:
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
        except Exception:
            continue
    for widget in widgets:
        try:
            widget.update()
        except Exception:
            continue


def refresh_application() -> None:
    """Refresh the whole application for the current mode (palette + ss)."""
    apply_to_app()
    repolish_all()


def tooltip_declarations() -> str:
    """Bare (selector-less) tooltip declarations for the current mode."""
    p = palette()
    return (
        f"background-color: {p['tooltip_bg']};"
        f"color: {p['tooltip_text']};"
        f"border: 1px solid {p['tooltip_border']};"
        "padding: 2px 4px;"
    )


def tooltip_rule(scope: str = "") -> str:
    """Return the ``QToolTip`` stylesheet rule for the current mode.

    ``scope`` optionally names an ancestor (e.g. ``"#SalePanel"``) so the
    rule has the same specificity as the local ``#SalePanel QLabel`` rule it
    has to outrank; emitting it afterwards makes the tooltip rule win.

    Tooltips need their own rule in *widget-level* stylesheets, not only in
    the application stylesheet: Qt resolves a tooltip's style from the
    widget that owns it, so any widget-level rule that matches a bare
    ``QLabel`` — ``QLabel { color: …; background: transparent; }`` is used
    all over this codebase — also matches the tooltip, and a widget-level
    rule outranks the application stylesheet.  That is what turned the
    tooltip into a transparent black box.
    """
    selector = f"{scope} QToolTip".strip() if scope else "QToolTip"
    return f"{selector} {{ {tooltip_declarations()} }}"


def _is_tooltip_widget(widget) -> bool:
    """True for Qt's tooltip label (``QTipLabel``), in any Qt spelling."""
    try:
        name = widget.metaObject().className()
    except Exception:
        return False
    if name in ("QTipLabel", "QToolTip"):
        return True
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        return (isinstance(widget, QLabel)
                and bool(widget.windowType() & Qt.WindowType.ToolTip))
    except Exception:
        return False


if _HAS_QT:
    from PySide6.QtCore import QEvent

    class _TooltipStyleFilter(QObject):
        """Force the centralized tooltip colours onto every tooltip.

        A widget-level ``QLabel`` rule beats the application stylesheet, so
        the only rule that reliably wins is the tooltip's *own* stylesheet.
        Qt builds the tooltip widget itself on each show, so the style is
        re-applied here as it appears.  Nothing else about the tooltip —
        text, position, timing, ownership — is touched.
        """

        def eventFilter(self, watched, event):
            try:
                # ``Show`` only.  Qt destroys or hides the tip label between
                # shows, so a ``Show`` always precedes the paint; handling
                # ``Polish`` as well would re-enter this filter from inside
                # our own ``setStyleSheet``.  A tooltip that is already
                # visible when the mode changes is restyled directly by
                # ``_install_tooltip_filter`` instead.
                if event.type() == QEvent.Show and _is_tooltip_widget(watched):
                    declarations = tooltip_declarations()
                    if watched.styleSheet() != declarations:
                        watched.setStyleSheet(declarations)
            except Exception:
                pass
            return False

    _tooltip_filter: "_TooltipStyleFilter | None" = None

    def _install_tooltip_filter(app) -> None:
        """Install the tooltip styler once, and restyle any visible tip."""
        global _tooltip_filter
        try:
            if _tooltip_filter is None:
                _tooltip_filter = _TooltipStyleFilter()
                app.installEventFilter(_tooltip_filter)
            for widget in app.topLevelWidgets():
                if _is_tooltip_widget(widget):
                    declarations = tooltip_declarations()
                    if widget.styleSheet() != declarations:
                        widget.setStyleSheet(declarations)
        except Exception:
            pass

else:  # pragma: no cover - headless
    def _install_tooltip_filter(app) -> None:
        return


# ── In-place colour migration for baked screen stylesheets ────────────
# Screens build their stylesheets once at import from module-level palette
# constants (``_SURFACE``, ``_BORDER``, ``_TEXT`` …).  After a Day/Night
# switch those baked hex values are stale, so the in-place refresh pass
# rewrites them to the SAME ROLE in the live palette.
#
# Grouping the roles — and never matching on the raw hex alone — is what
# keeps ``#ffffff`` / ``#000000`` unambiguous: a value under
# ``background-color`` can only be a background role, a value under
# ``color`` only a text role.
_ROLE_GROUPS: dict[str, tuple[str, ...]] = {
    "bg": ("bg", "surface", "surface_alt", "table_header", "disabled_bg",
           "selected"),
    "text": ("text", "header_text", "text_dim", "selected_text",
             "disabled_text"),
    "border": ("border", "grid"),
    "accent": ("accent", "accent_hover", "accent_pressed", "focus",
               "success", "success_hover", "danger", "danger_hover",
               "warning", "warning_hover"),
}


def _groups_for_property(prop: str) -> tuple[str, ...]:
    """Ordered role groups a declaration of ``prop`` may reference."""
    name = prop.strip().lower()
    if name == "color" or name.startswith("selection-color"):
        return ("text",)
    if name.startswith("selection-background") or name.startswith("background"):
        return ("bg", "accent")
    if name.startswith("gridline") or name.startswith("outline"):
        return ("accent", "border")
    if name.startswith("border"):
        return ("border", "accent")
    return ()


_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
_DECL_RE = re.compile(r"(?P<prop>[A-Za-z][A-Za-z-]*)\s*:\s*(?P<val>[^;{}]*)")


def _role_map(groups: tuple[str, ...]) -> dict[str, str]:
    """old hex (from either mode) -> live hex for the given role groups."""
    live = palette()
    mapping: dict[str, str] = {}
    for group in groups:
        for role in _ROLE_GROUPS.get(group, ()):
            new = live.get(role)
            if not new:
                continue
            for mode in ("light", "dark"):
                old = _PALETTES[mode].get(role)
                if old:
                    mapping[str(old).lower()] = new
    return mapping


def remap_baked_colors(stylesheet: str, *, only: tuple[str, ...] | None = None
                       ) -> str:
    """Rewrite baked palette hexes in ``stylesheet`` to the live tokens.

    Only hex values that appear as the *same role* in one of the
    centralized palettes are rewritten, and only under a declaration whose
    property names that role's group.  Screen-specific colours that are not
    part of the palette (e.g. the Counter Sale error red) are left exactly
    as they are, and no layout, font or padding declaration is touched.

    ``only`` restricts the work to a subset of property prefixes — the
    container pass uses it to rewrite backgrounds and borders without
    touching deliberately hardcoded foreground text (a white caption on a
    blue bill header must stay white in both modes).
    """
    if not stylesheet or "#" not in stylesheet:
        return stylesheet
    cache: dict[tuple[str, ...], dict[str, str]] = {}

    def replace_declaration(match: "re.Match[str]") -> str:
        prop = match.group("prop")
        value = match.group("val")
        unchanged = match.group(0)
        if only is not None and not any(
            prop.lower().startswith(prefix) for prefix in only
        ):
            return unchanged
        groups = _groups_for_property(prop)
        if not groups:
            return unchanged
        if groups not in cache:
            cache[groups] = _role_map(groups)
        mapping = cache[groups]

        def replace_hex(hex_match: "re.Match[str]") -> str:
            old = hex_match.group(0).lower()
            return mapping.get(old, hex_match.group(0))

        new_value = _HEX_RE.sub(replace_hex, value)
        if new_value == value:
            # Nothing to migrate: return the declaration byte for byte, so
            # callers can compare strings to decide whether the widget
            # actually needs re-styling (a needless setStyleSheet is a
            # needless repolish of the whole subtree).
            return unchanged
        head = match.string[match.start():match.start("val")]
        tail = match.string[match.end("val"):match.end()]
        return head + new_value + tail

    return _DECL_RE.sub(replace_declaration, stylesheet)


# ── Checkbox / radio indicators ───────────────────────────────────────
# Qt stops drawing the native check mark the moment any stylesheet rule
# matches the ``::indicator`` sub-control.  A stylesheet that only sets a
# size, a border and a background therefore leaves a *checked* box looking
# exactly like an unchecked one: a plain square.  In Night Mode that square
# is ``bg`` (``#000000``) with a ``#333333`` border, which is the black box
# reported beside Item Wise / Bill Wise — and those two widgets were radio
# buttons whose local stylesheet set only ``width``/``height``, so nothing
# changed at all when they were checked.
#
# The check mark and the radio dot are therefore generated as small PNGs
# from the live palette and referenced from the stylesheet.  Generating
# them keeps the glyph visible in both modes and free of any platform
# style dependency (Fusion draws its own indicator colours, which the
# application palette cannot reach once a stylesheet owns the sub-control).
#
# The tint follows the mode: a dark tick on the light Day Mode box, a
# bright tick on the dark Night Mode box.

_INDICATOR_SIZE = 13
_INDICATOR_DIR: Path | None = None
_INDICATOR_FILES: dict[tuple[str, str], str] = {}


def _indicator_dir() -> Path:
    """Directory holding the generated indicator glyphs."""
    global _INDICATOR_DIR
    if _INDICATOR_DIR is None:
        import tempfile
        _INDICATOR_DIR = (Path(tempfile.gettempdir())
                          / "pharmacy_theme_indicators")
    return _INDICATOR_DIR


def _glyph_path(colour: str, kind: str) -> str:
    """Path to a generated glyph PNG, or "" when it cannot be produced.

    ``kind`` is ``"check"`` (a check mark) or ``"dot"`` (a filled circle for
    radio buttons).  Results are cached per (colour, kind); a cached file
    that has since been removed is regenerated.

    Painting needs a running ``QGuiApplication``.  ``stylesheet()`` is also
    called at import time (screen modules build their styles from it before
    ``main()`` creates the application), so in that window this returns ""
    **without caching the failure** — the caller falls back to a plainly
    different checked fill, and the next call with an application present
    produces the real glyph.
    """
    key = (str(colour).lower(), kind)
    cached = _INDICATOR_FILES.get(key)
    if cached and Path(cached).is_file():
        return cached
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance() is None:
            return ""
    except Exception:
        return ""
    path = _paint_glyph(colour, kind)
    _INDICATOR_FILES[key] = path
    return path


def _paint_glyph(colour: str, kind: str) -> str:
    """Draw one indicator glyph and save it as a PNG ("" on failure)."""
    try:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen

        directory = _indicator_dir()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{kind}_{str(colour).lstrip('#').lower()}.png"
        size = _INDICATOR_SIZE
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        if not painter.isActive():
            # Without an active painter every draw call is a silent no-op,
            # which would save a blank glyph and leave the control looking
            # unchecked.  Report failure so the caller uses the fallback.
            return ""
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            glyph = QColor(colour)
            if kind == "dot":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(glyph))
                painter.drawEllipse(QPointF(size / 2.0, size / 2.0), 3.2, 3.2)
            else:
                pen = QPen(glyph, 2.0)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawPolyline([
                    QPointF(3.0, 6.8), QPointF(5.6, 9.4), QPointF(10.0, 4.0),
                ])
        finally:
            painter.end()
        if not _image_has_ink(image):
            return ""
        if image.save(str(target), "PNG"):
            return target.as_posix()
    except Exception:
        pass
    return ""


def _image_has_ink(image) -> bool:
    """True when the glyph image contains at least one painted pixel.

    Guards against a silently blank glyph (an inactive painter, a missing
    font/graphics backend) which would leave a checked control looking
    exactly like an unchecked one — the defect this module fixes.
    """
    try:
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() > 0:
                    return True
    except Exception:
        return False
    return False


def indicator_style(*, checkbox: bool = True, radio: bool = True,
                    size: int = _INDICATOR_SIZE) -> str:
    """Return the complete ``::indicator`` styling for the current mode.

    Covers the plain, hover, focus, checked and disabled states for both
    ``QCheckBox`` and ``QRadioButton``.  Every colour comes from the
    centralized palette, and the check mark / dot comes from a generated
    glyph so a checked control is unmistakable in either mode.
    """
    p = palette()
    tick = _glyph_path(p["text"], "check")
    tick_off = _glyph_path(p["disabled_text"], "check")
    dot = _glyph_path(p["text"], "dot")
    dot_off = _glyph_path(p["disabled_text"], "dot")

    widgets = []
    if checkbox:
        widgets.append("QCheckBox")
    if radio:
        widgets.append("QRadioButton")
    if not widgets:
        return ""
    # Every pseudo-state has to be repeated on each class: a selector such
    # as ``QCheckBox, QRadioButton::indicator`` would style whole check
    # boxes rather than their indicators.
    indicators = [f"{name}::indicator" for name in widgets]
    # NOTE: the focus pseudo-state belongs AFTER the sub-control
    # (``QRadioButton::indicator:focus``).  The previous spelling
    # (``QRadioButton:focus::indicator``) is mis-parsed by Qt: the border
    # lands on the whole button (indicator + label) as a persistent outer
    # rectangle — green in Night Mode, blue in Day Mode — instead of on the
    # small indicator.  That outer rectangle is the reported defect.
    focused = [f"{name}::indicator:focus" for name in widgets]

    def select(selectors, state: str = "") -> str:
        return ", ".join(f"{selector}{state}" for selector in selectors)

    def checked_image(glyph: str, fallback_bg: str) -> str:
        """Checked state: keep the mode's box colour and draw the glyph.

        Without a usable glyph the fill still changes, so checked never
        renders identically to unchecked.
        """
        if glyph:
            return (f"background-color: {p['bg']};"
                    f" border: 1px solid {p['accent']};"
                    f' image: url("{glyph}");')
        return (f"background-color: {fallback_bg};"
                f" border: 1px solid {p['accent']}; image: none;")

    rules = [
        # The button itself (indicator + label) is borderless: no outer
        # rectangle in any state.  Only the small ::indicator box carries a
        # border, so checked/unchecked stays visible via the glyph + the
        # indicator's own edge.  Without this, a widget-level focus border
        # paints as a full-width rectangle around text and indicator.
        f"{', '.join(widgets)} {{"
        "  background: transparent; border: none; outline: none;"
        "}",
        f"{', '.join(f'{w}:focus' for w in widgets)} {{"
        "  background: transparent; border: none; outline: none;"
        "}",
        f"{', '.join(f'{w}:hover' for w in widgets)} {{"
        "  background: transparent; border: none;"
        "}",
        # A square box for check boxes, a circle for radio buttons: the two
        # are distinguishable at a glance, as they are natively.
        f"{select(indicators)} {{"
        f"  width: {size}px; height: {size}px;"
        f"  border: 1px solid {p['border']};"
        f"  background-color: {p['bg']};"
        f"}}",
    ]
    if checkbox:
        rules.append("QCheckBox::indicator { border-radius: 3px; }")
    if radio:
        rules.append(
            f"QRadioButton::indicator {{ border-radius: {max(1, size // 2)}px; }}"
        )
    rules += [
        f"{select(indicators, ':hover')} {{ border: 1px solid {p['focus']}; }}",
        f"{select(focused)} {{ border: 1px solid {p['focus']}; }}",
        f"{select(indicators, ':unchecked')} {{ image: none; }}",
        f"{select(indicators, ':disabled')} {{"
        f"  background-color: {p['disabled_bg']};"
        f"  border: 1px solid {p['border']};"
        f"}}",
    ]
    if checkbox:
        rules.append(
            "QCheckBox::indicator:checked {"
            f"  {checked_image(tick, p['selected'])}"
            "}"
        )
        rules.append(
            "QCheckBox::indicator:checked:disabled {"
            f"  {checked_image(tick_off, p['disabled_bg'])}"
            "}"
        )
    if radio:
        rules.append(
            "QRadioButton::indicator:checked {"
            f"  {checked_image(dot, p['selected'])}"
            "}"
        )
        rules.append(
            "QRadioButton::indicator:checked:disabled {"
            f"  {checked_image(dot_off, p['disabled_bg'])}"
            "}"
        )
    return "".join(rule for rule in rules if rule)


# ── Date-picker drop-down / calendar indicator ────────────────────────
# Every editable date field in the application is a QDateEdit (no
# QDateTimeEdit/QTimeEdit is currently used for date selection, but the
# same rules cover them).  All of them set ``setCalendarPopup(True)`` so
# clicking the drop-down button opens a QCalendarWidget.
#
# Root cause of the missing-icon defect: every date stylesheet in the
# codebase declared
#     QDateEdit::down-arrow { image: none; border: none; }
# which tells Qt to paint NO indicator, and
#     QDateEdit::drop-down { border: none; ... }
# which leaves the button area as an empty, borderless strip.  The field
# still opened its popup when the empty strip was clicked, but there was
# no visible affordance — the Daily Sales date looked like a plain line
# edit.
#
# The fix mirrors the checkbox/radio indicator approach above: the
# down-chevron is generated as a small PNG tinted with the live palette's
# text colour (bright on the dark Night Mode field, dark on the light Day
# Mode field), with a disabled-text variant for the disabled state.  The
# drop-down button gets an explicit width, a left separator border and a
# hover fill so the clickable area reads as a button in both modes.  When
# no QApplication exists yet (import time) the glyph path is "" and the
# rules fall back to a sized, image-less ::down-arrow so the native arrow
# paints instead of nothing.

_DATE_DROP_WIDTH = 24
_DATE_ARROW_SIZE = 12
_DATE_ARROW_IMAGE_SIZE = 16
_DATE_ARROW_FILES: dict[str, str] = {}


def _drop_arrow_path(colour: str) -> str:
    """Path to a generated down-chevron PNG, or "" when unavailable.

    Same headless contract as _glyph_path: returns "" without caching the
    failure when no QGuiApplication exists yet, so import-time stylesheets
    use the native-arrow fallback and the next call with an application
    produces the real tinted glyph.
    """
    key = str(colour).lower()
    cached = _DATE_ARROW_FILES.get(key)
    if cached and Path(cached).is_file():
        return cached
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance() is None:
            return ""
    except Exception:
        return ""
    path = _paint_drop_arrow(colour)
    _DATE_ARROW_FILES[key] = path
    return path


def _paint_drop_arrow(colour: str) -> str:
    """Draw one down-chevron glyph and save it as a PNG ("" on failure)."""
    try:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QImage, QPainter, QPen

        directory = _indicator_dir()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"drop_{str(colour).lstrip('#').lower()}.png"
        size = _DATE_ARROW_IMAGE_SIZE
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        if not painter.isActive():
            return ""
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(QColor(colour), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            # Thick down-chevron, centred with side margins so it never
            # touches the button edge or the date text.
            painter.drawPolyline([
                QPointF(3.5, 6.0), QPointF(8.0, 10.5), QPointF(12.5, 6.0),
            ])
        finally:
            painter.end()
        if not _image_has_ink(image):
            return ""
        if image.save(str(target), "PNG"):
            return target.as_posix()
    except Exception:
        pass
    return ""


def date_subcontrols(p: dict | None = None, *, width: int = _DATE_DROP_WIDTH) -> str:
    """QSS fragment for the date-picker button + arrow in the given palette.

    Covers QDateEdit, QDateTimeEdit and QTimeEdit together so every date
    field shares one icon size (12 px), one right-side button width and one
    alignment.  The button carries a left separator border and a hover fill;
    the arrow uses the generated chevron in the palette's text colour with
    a disabled-text variant, falling back to the native arrow when the
    glyph cannot be produced.
    """
    pal = p if p is not None else palette()
    arrow = _drop_arrow_path(pal["text"])
    arrow_off = _drop_arrow_path(pal.get("disabled_text", pal["text_dim"]))

    def arrow_decl(glyph: str) -> str:
        if glyph:
            return f'image: url("{glyph}"); width: {_DATE_ARROW_SIZE}px; height: {_DATE_ARROW_SIZE}px;'
        # Fallback: sized but image-less, so Qt paints the native arrow
        # instead of nothing (never `image: none` here).
        return f"width: {_DATE_ARROW_SIZE}px; height: {_DATE_ARROW_SIZE}px;"

    drops = ("QDateEdit::drop-down", "QDateTimeEdit::drop-down",
             "QTimeEdit::drop-down")
    arrows = ("QDateEdit::down-arrow", "QDateTimeEdit::down-arrow",
              "QTimeEdit::down-arrow")
    arrows_off = tuple(f"{a}:disabled" for a in arrows)
    return (
        f"{', '.join(drops)} {{"
        "  subcontrol-origin: padding; subcontrol-position: top right;"
        f"  width: {int(width)}px;"
        f"  border-left: 1px solid {pal['border']};"
        "  border-top-right-radius: 2px; border-bottom-right-radius: 2px;"
        f"  background: {pal['surface']}; margin: 0px;"
        "}"
        f"{', '.join(f'{d}:hover' for d in drops)} {{"
        f"  background: {pal['selected']};"
        "}"
        f"{', '.join(f'{d}:disabled' for d in drops)} {{"
        f"  background: {pal['disabled_bg']};"
        f"  border-left: 1px solid {pal['border']};"
        "}"
        f"{', '.join(arrows)} {{ {arrow_decl(arrow)} }}"
        f"{', '.join(arrows_off)} {{ {arrow_decl(arrow_off)} }}"
    )


def fix_date_stylesheet(stylesheet_text: str, p: dict | None = None) -> str:
    """Replace icon-hiding date rules in a baked sheet with the shared icon.

    Preserves each screen's own drop-down width (18/20/22/24 px) so layout
    never shifts; only the invisible button/arrow becomes the shared
    visible one.  Sheets without any QDateEdit rule are returned untouched.
    """
    import re as _re

    if not stylesheet_text or "QDateEdit" not in stylesheet_text:
        return stylesheet_text
    pal = p if p is not None else palette()
    width = _DATE_DROP_WIDTH
    try:
        m = _re.search(
            r"QDateEdit::drop-down\s*\{[^}]*?width:\s*(\d+)px", stylesheet_text)
        if m:
            width = max(18, min(28, int(m.group(1))))
    except Exception:
        pass
    fresh = date_subcontrols(pal, width=width)
    # Remove every baked drop-down / down-arrow rule for the date classes
    # (including QDateTimeEdit/QTimeEdit variants), then append the shared
    # fragment once.  The base QDateEdit/QDateTimeEdit/QTimeEdit rules
    # (background, padding, fonts) are left byte-for-byte.
    pattern = _re.compile(
        r"QDateEdit::(?:drop-down|down-arrow)[^{]*\{[^}]*\}"
        r"|QDateTimeEdit::(?:drop-down|down-arrow)[^{]*\{[^}]*\}"
        r"|QTimeEdit::(?:drop-down|down-arrow)[^{]*\{[^}]*\}"
    )
    stripped = pattern.sub("", stylesheet_text).strip()
    return (stripped + fresh) if stripped else fresh


def stylesheet() -> str:
    """Return the application-wide stylesheet for the current mode.

    Applied once to the QApplication so widgets that are not individually
    styled (dialogs, message boxes, plain tables, unstyled screens such
    as User Management) still follow the centralized light theme.
    Widget-level stylesheets always take precedence over this one.

    Every colour comes from the centralized palette — the only hardcoded
    colours are the light-yellow tooltip note (readable in both modes) and
    the white pressed-button text (white on a saturated accent fill).
    """
    p = palette()
    return (
        "QMainWindow, QDialog {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        "}"
        "QWidget {"
        f"  font-family: {FONT_FAMILY};"
        f"  font-size: {TYPE_TABLE_DATA}px;"
        "}"
        # Plain containers must be opaque in the theme bg; otherwise an
        # unstyled QFrame/QWidget shows the backing store (black) through.
        "QFrame {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        "}"
        "QStackedWidget {"
        f"  background-color: {p['bg']};"
        "}"
        "QScrollArea {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "}"
        # Viewports of scroll areas / item views follow the workspace bg.
        "QAbstractScrollArea::viewport {"
        f"  background-color: {p['bg']};"
        "}"
        "QSplitter::handle {"
        f"  background-color: {p['border']};"
        "}"
        "QTabWidget::pane {"
        f"  background-color: {p['bg']};"
        f"  border: 1px solid {p['border']};"
        "}"
        "QTabBar::tab {"
        f"  background-color: {p['surface']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  padding: 4px 12px;"
        "}"
        "QTabBar::tab:selected {"
        f"  background-color: {p['bg']};"
        "}"
        "QLabel {"
        f"  color: {p['text']};"
        "  background: transparent;"
        # Captions, field labels and read-outs are business text: they are
        # bold everywhere.  Qt merges declarations across rules, so a
        # screen's own ``QLabel { color: …; font-size: … }`` rule keeps its
        # size and colour and still picks this weight up — which is what
        # makes the weight consistent across 37 screens without editing
        # each one.  A genuinely secondary hint says ``font-weight: normal``
        # itself (see ui.components.label_style).
        "  font-weight: bold;"
        "}"
        "QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  border-radius: 2px;"
        "  padding: 4px 7px;"
        f"  font-size: {TYPE_INPUT}px;"
        "  font-weight: bold;"
        "  selection-background-color: " + p["selected"] + ";"
        f"  selection-color: {p['selected_text']};"
        "}"
        "QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,"
        "QSpinBox:focus, QDoubleSpinBox:focus {"
        f"  border: 1px solid {p['focus']};"
        "}"
        "QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,"
        "QSpinBox:disabled, QDoubleSpinBox:disabled {"
        f"  background-color: {p['disabled_bg']};"
        f"  color: {p['disabled_text']};"
        "}"
        "QComboBox, QDateEdit, QTimeEdit, QDateTimeEdit {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  border-radius: 2px;"
        "  padding: 4px 7px;"
        f"  font-size: {TYPE_INPUT}px;"
        "  font-weight: bold;"
        "}"
        "QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {"
        f"  border: 1px solid {p['focus']};"
        "}"
        "QComboBox:disabled, QDateEdit:disabled {"
        f"  background-color: {p['disabled_bg']};"
        f"  color: {p['disabled_text']};"
        "}"
        # Date-picker button + calendar chevron.  Without an explicit
        # ::down-arrow image Qt still paints the native arrow for unstyled
        # fields, but any widget-level `image: none` hides it — so the
        # shared fragment pins a tinted, high-contrast glyph here for every
        # field that follows the application stylesheet (e.g. the
        # Financial Year dialog).  Fields with their own stylesheet get the
        # same fragment from date_subcontrols()/fix_date_stylesheet().
        + date_subcontrols(p) +
        # Editable combo text field must not render as a nested white box.
        "QComboBox QLineEdit {"
        "  background: transparent;"
        "  border: none;"
        "  padding: 0px;"
        f"  color: {p['text']};"
        f"  font-size: {TYPE_INPUT}px;"
        "  selection-background-color: " + p["selected"] + ";"
        f"  selection-color: {p['selected_text']};"
        "}"
        "QComboBox QAbstractItemView {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        "  outline: none;"
        "}"
        "QComboBox QAbstractItemView::item {"
        "  min-height: 24px;"
        "  padding: 2px 6px;"
        "}"
        "QComboBox QAbstractItemView::item:selected {"
        f"  background-color: {p['selected']};"
        f"  color: {p['selected_text']};"
        "}"
        # Standalone completer / item-view popups (QCompleter owns a
        # top-level QListView): same item-view colours as combo dropdowns.
        "QAbstractItemView {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        "  outline: none;"
        "  font-weight: bold;"
        "}"
        "QAbstractItemView::item:selected {"
        f"  background-color: {p['selected']};"
        f"  color: {p['selected_text']};"
        "}"
        "QPushButton {"
        f"  background-color: {p['surface']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  border-radius: 2px;"
        "  padding: 6px 14px;"
        "  min-height: 22px;"
        f"  font-size: {TYPE_BUTTON}px;"
        "  font-weight: bold;"
        "}"
        "QPushButton:hover {"
        f"  background-color: {p['selected']};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {p['accent_pressed']};"
        "  color: #ffffff;"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {p['disabled_bg']};"
        f"  color: {p['disabled_text']};"
        f"  border: 1px solid {p['border']};"
        "}"
        "QPushButton:focus {"
        f"  border: 1px solid {p['focus']};"
        "}"
        "QGroupBox {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  border-radius: 2px;"
        "  margin-top: 12px;"
        "  padding-top: 14px;"
        "}"
        "QGroupBox::title {"
        "  subcontrol-origin: margin;"
        "  left: 8px;"
        "  padding: 0 5px;"
        f"  color: {p['text']};"
        f"  background-color: {p['bg']};"
        "}"
        "QCheckBox, QRadioButton {"
        f"  color: {p['text']};"
        "  background: transparent;"
        "  border: none; outline: none;"
        "  spacing: 5px;"
        "}"
        "QCheckBox:focus, QRadioButton:focus {"
        "  background: transparent;"
        "  border: none; outline: none;"
        "}"
        "QCheckBox:hover, QRadioButton:hover {"
        "  background: transparent;"
        "  border: none;"
        "}"
        # The indicator sub-control, including a real check mark / radio dot
        # drawn in the mode's text colour — see ``indicator_style``.  A
        # stylesheet that only sets a border and a background makes Qt stop
        # drawing the native glyph, leaving a checked box indistinguishable
        # from an unchecked one.
        + indicator_style()
        + "QTableWidget, QTableView, QTreeWidget, QListWidget {"
        f"  background-color: {p['bg']};"
        f"  alternate-background-color: {p['surface_alt']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        f"  gridline-color: {p['grid']};"
        "  outline: none;"
        f"  font-size: {TYPE_TABLE_DATA}px;"
        "  font-weight: bold;"
        "  selection-background-color: " + p["selected"] + ";"
        f"  selection-color: {p['selected_text']};"
        "}"
        "QTableWidget::item, QTableView::item {"
        "  padding: 3px 6px;"
        "}"
        "QTableWidget::item:selected, QTableView::item:selected {"
        f"  background-color: {p['selected']};"
        f"  color: {p['selected_text']};"
        "}"
        "QTableCornerButton::section {"
        f"  background-color: {p['table_header']};"
        f"  border: none;"
        f"  border-right: 1px solid {p['border']};"
        f"  border-bottom: 1px solid {p['border']};"
        "}"
        "QHeaderView::section {"
        f"  background-color: {p['table_header']};"
        f"  color: {p['header_text']};"
        f"  border: none;"
        f"  border-right: 1px solid {p['border']};"
        f"  border-bottom: 1px solid {p['border']};"
        "  padding: 4px 8px;"
        "  font-weight: bold;"
        f"  font-size: {TYPE_TABLE_HEADER}px;"
        "}"
        "QHeaderView::section:vertical {"
        f"  background-color: {p['surface']};"
        f"  color: {p['text']};"
        "}"
        # Calendar popup (QDateEdit with CalendarPopup): navigation + grid
        # must follow the theme instead of the platform defaults.
        "QCalendarWidget {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "}"
        "QCalendarWidget QToolButton {"
        f"  background-color: {p['surface']};"
        f"  color: {p['text']};"
        "  border: none;"
        "  padding: 4px;"
        "}"
        "QCalendarWidget QToolButton:hover {"
        f"  background-color: {p['selected']};"
        f"  color: {p['selected_text']};"
        "}"
        "QCalendarWidget QSpinBox {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  selection-background-color: " + p["selected"] + ";"
        f"  selection-color: {p['selected_text']};"
        "}"
        "QCalendarWidget QAbstractItemView {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        "  outline: none;"
        "}"
        "QMenuBar {"
        f"  background-color: {p['surface']};"
        f"  color: {p['text']};"
        "}"
        "QMenuBar::item:selected {"
        f"  background-color: {p['selected']};"
        "}"
        "QMenu {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  padding: 2px 0;"
        "}"
        "QMenu::item {"
        "  padding: 4px 22px;"
        "}"
        "QMenu::item:selected {"
        f"  background-color: {p['selected']};"
        f"  color: {p['selected_text']};"
        "}"
        "QStatusBar {"
        f"  background-color: {p['surface']};"
        f"  color: {p['text']};"
        "}"
        "QScrollBar:vertical, QScrollBar:horizontal {"
        f"  background: {p['surface_alt']};"
        "  border: none;"
        "  width: 14px;"
        "  height: 14px;"
        "}"
        "QScrollBar::handle:vertical, QScrollBar::handle:horizontal {"
        f"  background: {p['border']};"
        "  border-radius: 2px;"
        "  min-height: 24px;"
        "  min-width: 24px;"
        "}"
        "QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {"
        f"  background: {p['accent']};"
        "}"
        "QScrollBar::add-line, QScrollBar::sub-line {"
        "  width: 0; height: 0;"
        "}"
        "QHeaderView::section:checked {"
        f"  background-color: {p['selected']};"
        "}"
        # Emitted LAST on purpose.  ``QTipLabel`` — the tooltip's own widget
        # — is a QLabel, so the earlier ``QLabel`` rule above matches it
        # too; on an equal-specificity tie Qt lets the last rule win.
        + tooltip_rule()
    )


# Module-level singleton used across the application.
theme_manager = ThemeManager()
