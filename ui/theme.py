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
        "text": "#14212e",          # dark navy primary text
        "text_dim": "#55677a",      # dark grey secondary text
        # extended Phase 6E tokens -----------------------------------
        "surface_alt": "#f3f8fc",   # barely-tinted panel / zebra row
        "table_header": "#dce9f6",  # table header row
        "header_text": "#14212e",   # page/table header text
        "grid": "#c5d4e2",          # table grid lines
        "selected": "#cfe2f3",      # selected row (light blue)
        "selected_text": "#0f1c29",
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
    },
}

# Backwards-compatible alias for the night mode name.
_PALETTES["night"] = _PALETTES["dark"]

_THEME_FILE = Path(__file__).resolve().parent.parent / "data" / "theme.json"

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
        with open(_THEME_FILE, "r", encoding="utf-8") as fh:
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
    _THEME_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_THEME_FILE, "w", encoding="utf-8") as fh:
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
        """Propagate the current mode: reload screens, notify listeners."""
        _reload_screen_modules()
        self._notify()

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


def stylesheet() -> str:
    """Return the application-wide stylesheet for the current mode.

    Applied once to the QApplication so widgets that are not individually
    styled (dialogs, message boxes, plain tables, unstyled screens such
    as User Management) still follow the centralized light theme.
    Widget-level stylesheets always take precedence over this one.
    """
    p = palette()
    return (
        "QMainWindow, QDialog {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        "}"
        "QWidget {"
        f"  font-family: 'Segoe UI', 'Tahoma', sans-serif;"
        f"  font-size: 12px;"
        "}"
        "QLabel {"
        f"  color: {p['text']};"
        "  background: transparent;"
        "}"
        "QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  border-radius: 2px;"
        "  padding: 3px 5px;"
        "  selection-background-color: " + p["selected"] + ";"
        f"  selection-color: {p['selected_text']};"
        "}"
        "QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,"
        "QSpinBox:focus, QDoubleSpinBox:focus {"
        f"  border: 1px solid {p['focus']};"
        "}"
        "QComboBox, QDateEdit, QTimeEdit, QDateTimeEdit {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  border-radius: 2px;"
        "  padding: 3px 5px;"
        "}"
        "QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {"
        f"  border: 1px solid {p['focus']};"
        "}"
        "QComboBox QAbstractItemView {"
        f"  background-color: {p['bg']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        "  outline: none;"
        "}"
        "QPushButton {"
        f"  background-color: {p['surface']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        "  border-radius: 2px;"
        "  padding: 4px 12px;"
        "  min-height: 18px;"
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
        "}"
        "QCheckBox, QRadioButton {"
        f"  color: {p['text']};"
        "  background: transparent;"
        "  spacing: 5px;"
        "}"
        "QTableWidget, QTableView, QTreeWidget, QListWidget {"
        f"  background-color: {p['bg']};"
        f"  alternate-background-color: {p['surface_alt']};"
        f"  color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        f"  gridline-color: {p['grid']};"
        "  outline: none;"
        "  selection-background-color: " + p["selected"] + ";"
        f"  selection-color: {p['selected_text']};"
        "}"
        "QTableWidget::item, QTableView::item {"
        "  padding: 1px 4px;"
        "}"
        "QTableWidget::item:selected, QTableView::item:selected {"
        f"  background-color: {p['selected']};"
        f"  color: {p['selected_text']};"
        "}"
        "QHeaderView::section {"
        f"  background-color: {p['table_header']};"
        f"  color: {p['header_text']};"
        f"  border: none;"
        f"  border-right: 1px solid {p['border']};"
        f"  border-bottom: 1px solid {p['border']};"
        "  padding: 3px 6px;"
        "  font-weight: bold;"
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
        "QToolTip {"
        f"  background-color: #ffffe1;"
        "  color: #14212e;"
        f"  border: 1px solid {p['border']};"
        "  padding: 2px 4px;"
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
    )


# Module-level singleton used across the application.
theme_manager = ThemeManager()
