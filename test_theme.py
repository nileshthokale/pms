"""Day/night theme manager tests (headless — no PySide6 required).

ui/theme.py is deliberately importable without Qt so the palette,
persistence, toggle, and change-notification logic can be tested here.
All writes are redirected to a temp theme file so the application's own
data/theme.json is never touched.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ui/__init__ imports the Qt main window; theme.py itself is Qt-free, so
# load it directly from its file to keep these tests headless.
_spec = importlib.util.spec_from_file_location(
    "ui_theme_standalone",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "ui", "theme.py"),
)
theme_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(theme_mod)

ThemeManager = theme_mod.ThemeManager
theme_manager = theme_mod.theme_manager


class TestTheme(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._theme_file = Path(self._tmp.name) / "theme.json"
        # Redirect persistence to the temp file for every operation.
        patcher = mock.patch.object(theme_mod, "_THEME_FILE", self._theme_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    # ── palettes ─────────────────────────────────────────────────────
    def test_01_dark_palette_matches_current_app_colors(self):
        p = theme_manager.palette() if theme_manager.is_dark() else \
            theme_mod._PALETTES["dark"]
        self.assertEqual(p["bg"], "#000000")
        self.assertEqual(p["surface"], "#1a1a1a")
        self.assertEqual(p["border"], "#333333")
        self.assertEqual(p["accent"], "#2e7d32")
        self.assertEqual(p["accent_hover"], "#388e3c")
        self.assertEqual(p["text"], "#ffffff")
        self.assertEqual(p["text_dim"], "#aaaaaa")

    def test_02_light_palette_is_light_and_complete(self):
        p = theme_mod._PALETTES["light"]
        for key in ("bg", "surface", "border", "accent", "accent_hover",
                    "text", "text_dim"):
            self.assertIn(key, p)
        # Light mode: light surfaces, dark text
        self.assertNotEqual(p["bg"], "#000000")
        self.assertNotEqual(p["text"], "#ffffff")

    def test_03_both_modes_keep_brand_accent(self):
        # Phase 6E: light mode uses the classic desktop blue accent;
        # night mode keeps its original green accent.  Both must define a
        # valid accent/hover pair so screens always resolve a colour.
        for mode in ("light", "dark"):
            p = theme_mod._PALETTES[mode]
            for key in ("accent", "accent_hover"):
                self.assertRegex(p[key], r"^#[0-9a-fA-F]{6}$", f"{mode}:{key}")
        self.assertEqual(theme_mod._PALETTES["light"]["accent"], "#2f6fb0")

    # ── mode handling ────────────────────────────────────────────────
    def test_04_toggle_flips_mode(self):
        mgr = ThemeManager()
        mgr.set_mode("dark", notify=False)
        self.assertTrue(mgr.is_dark())
        mgr.toggle()
        self.assertEqual(mgr.mode(), "light")
        mgr.toggle()
        self.assertEqual(mgr.mode(), "dark")

    def test_05_invalid_mode_rejected(self):
        mgr = ThemeManager()
        with self.assertRaises(ValueError):
            mgr.set_mode("blue")

    # ── persistence ──────────────────────────────────────────────────
    def test_06_mode_persists_to_disk(self):
        mgr = ThemeManager()
        mgr.set_mode("dark", notify=False)
        mgr.toggle()  # -> light (writes file)
        self.assertTrue(self._theme_file.exists())
        with open(self._theme_file, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["mode"], "light")

    def test_07_new_manager_loads_persisted_mode(self):
        mgr = ThemeManager()
        mgr.set_mode("light", notify=False)
        fresh = ThemeManager()
        self.assertEqual(fresh.mode(), "light")
        self.assertFalse(fresh.is_dark())

    def test_08_missing_file_defaults_to_light(self):
        self.assertFalse(self._theme_file.exists())
        mgr = ThemeManager()
        self.assertEqual(mgr.mode(), "light")

    def test_09_corrupt_file_defaults_to_light(self):
        self._theme_file.parent.mkdir(parents=True, exist_ok=True)
        self._theme_file.write_text("{not json", encoding="utf-8")
        mgr = ThemeManager()
        self.assertEqual(mgr.mode(), "light")

    # ── change notification ──────────────────────────────────────────
    def test_10_on_changed_fires_on_toggle(self):
        mgr = ThemeManager()
        mgr.set_mode("dark", notify=False)
        events = []
        mgr.on_changed(events.append)
        mgr.toggle()
        self.assertEqual(events, ["light"])

    def test_11_palette_reflects_current_mode(self):
        mgr = ThemeManager()
        mgr.set_mode("light", notify=False)
        self.assertEqual(mgr.palette()["bg"],
                         theme_mod._PALETTES["light"]["bg"])
        mgr.toggle()
        self.assertEqual(mgr.palette()["bg"],
                         theme_mod._PALETTES["dark"]["bg"])

    # ── navigation bar scheme (day-mode visibility fix) ──────────────
    def test_12_nav_scheme_dark_keeps_original_look(self):
        nav = theme_mod._NAV_SCHEMES["dark"]
        self.assertEqual(nav["bg"], "#2e7d32")     # green bar
        self.assertEqual(nav["text"], "#ffffff")   # white text

    def test_13_nav_scheme_light_uses_dark_text(self):
        nav = theme_mod._NAV_SCHEMES["light"]
        self.assertEqual(nav["bg"], "#dce9f6")     # light blue strip
        self.assertEqual(nav["text"], "#14212e")   # DARK text — readable

    def test_14_nav_text_changes_with_mode(self):
        # Regression: the nav bar font color must NOT stay white in
        # day mode.
        self.assertNotEqual(theme_mod._NAV_SCHEMES["dark"]["text"],
                            theme_mod._NAV_SCHEMES["light"]["text"])

    def test_15_nav_schemes_have_all_keys(self):
        keys = {"bg", "border", "text", "hover", "pressed",
                "theme_btn_bg", "theme_btn_text", "theme_btn_hover"}
        for mode, nav in theme_mod._NAV_SCHEMES.items():
            self.assertEqual(set(nav.keys()), keys, f"mode={mode}")

    def test_16_nav_palette_follows_manager_mode(self):
        mgr = ThemeManager()
        mgr.set_mode("light", notify=False)
        with mock.patch.object(theme_mod, "theme_manager", mgr):
            self.assertEqual(theme_mod.nav_palette()["text"], "#14212e")
        mgr.set_mode("dark", notify=False)
        with mock.patch.object(theme_mod, "theme_manager", mgr):
            self.assertEqual(theme_mod.nav_palette()["text"], "#ffffff")


if __name__ == "__main__":
    unittest.main(verbosity=2)
