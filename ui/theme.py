"""Central theme (day/night mode) manager for the application UI.

Owns the color palette for both modes, persists the current mode to
data/theme.json, and notifies listeners when the mode changes.

Every screen module binds its module-level color constants from
`palette()` at import time. Switching modes at runtime reloads the
screen modules (so their constants AND prebuilt stylesheet strings are
rebuilt from the new palette) and emits `changed`; the main window then
rebuilds its page stack with the freshly reloaded page classes.

The module is importable without PySide6 (headless) so the persistence
and palette logic can be unit-tested — Qt-dependent behaviour (screen
module reload, signal emission) is skipped or degraded gracefully when
PySide6 is unavailable.
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


# ── Palettes ──────────────────────────────────────────────────────────
# Keys map onto the module-level constants every screen defines:
# _DARK_BG, _SURFACE, _BORDER, _ACCENT, _ACCENT_HOVER, _TEXT, _TEXT_DIM
_PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#000000",
        "surface": "#1a1a1a",
        "border": "#333333",
        "accent": "#2e7d32",
        "accent_hover": "#388e3c",
        "text": "#ffffff",
        "text_dim": "#aaaaaa",
    },
    "light": {
        "bg": "#11b3db",
        "surface": "#ffffff",
        "border": "#c8ccd0",
        "accent": "#2e7d32",
        "accent_hover": "#1b5e20",
        "text": "#1a1a1a",
        "text_dim": "#5f6368",
    },
}

_THEME_FILE = Path(__file__).resolve().parent.parent / "data" / "theme.json"

# Navigation bar color scheme per mode. Dark keeps the original green
# bar with white text; light uses a white bar with DARK text so the bar
# stays readable in day mode — the text color always contrasts the
# bar background in both modes.
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
        "bg": "#ffffff",
        "border": "#c8ccd0",
        "text": "#1a1a1a",
        "hover": "#e6f2e6",
        "pressed": "#cde3cd",
        "theme_btn_bg": "#2e7d32",
        "theme_btn_text": "#ffffff",
        "theme_btn_hover": "#388e3c",
    },
}


def _load_mode() -> str:
    try:
        with open(_THEME_FILE, "r", encoding="utf-8") as fh:
            mode = json.load(fh).get("mode")
        if mode in _PALETTES:
            return mode
    except (OSError, ValueError):
        pass
    return "dark"


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
    """Application-wide day/night theme manager."""

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

    Dark mode: green bar, white text (the original look).
    Light mode: white bar, dark text — so the nav bar text is always
    readable and changes color with the theme.
    """
    return _NAV_SCHEMES[theme_manager.mode()]


# Module-level singleton used across the application.
theme_manager = ThemeManager()
