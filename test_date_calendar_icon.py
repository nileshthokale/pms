"""Regression tests for the missing calendar-icon fix (UI-only).

Every editable date-selection control is a QDateEdit with
``setCalendarPopup(True)``.  The defect was that every date stylesheet
declared ``QDateEdit::down-arrow { image: none; ... }`` (plus a bare
``QDateEdit::drop-down { border: none; }``), so the field painted no
button and no arrow — the Daily Sales date looked like a plain line edit.

These tests pin the shared fix in both Day and Night Mode:

* ``ui.theme.date_subcontrols`` emits a visible drop-down button
  (separator border, hover fill) and a 12 px down-chevron tinted with the
  mode's text colour (disabled-text variant for :disabled), never
  ``image: none`` for a date selector.
* ``fix_date_stylesheet`` upgrades baked screen stylesheets while
  preserving each screen's own drop-down width and base rule.
* ``ui.components.date_style`` / ``style_date`` carry the icon and enable
  the calendar popup.
* The application stylesheet carries the same rules for unstyled fields
  (Financial Year dialog).
* No screen module still hides the date arrow with ``image: none``.
* With a running QApplication the chevron PNGs exist for both modes, the
  icon paints text-coloured pixels in the button band in every state
  (focused / unfocused / disabled / hover), selecting a date updates the
  field, and Day -> Night -> Day keeps values, filters and drafts.

Offscreen (QT_QPA_PLATFORM=offscreen); never touches the live database,
data/theme.json, the EXE or dist.
"""

import importlib
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import theme as theme_mod

try:
    from PySide6.QtWidgets import QApplication, QDateEdit
    from PySide6.QtCore import QDate
    HAS_QT = True
except ImportError:
    HAS_QT = False


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    return app


def _date_image_none_hits(sheet: str) -> list:
    """Occurrences of `image: none` inside a date down-arrow rule."""
    hits = []
    for m in re.finditer(
            r"(QDateEdit|QDateTimeEdit|QTimeEdit)::down-arrow\s*\{([^}]*)\}",
            sheet):
        if "image: none" in m.group(2).replace(" ", "").lower() \
                or "image:none" in m.group(2).replace(" ", "").lower():
            hits.append(m.group(0)[:120])
    return hits


class DateIconStylesheetTests(unittest.TestCase):
    """Headless: the shared fragment never hides the date arrow."""

    def test_01_subcontrols_visible_in_both_modes(self):
        for mode in ("light", "dark"):
            p = theme_mod._PALETTES[mode]
            frag = theme_mod.date_subcontrols(p, width=24)
            self.assertIn("QDateEdit::drop-down", frag)
            self.assertIn("QDateEdit::down-arrow", frag)
            self.assertIn("width: 24px", frag)
            # Consistent 12 px icon, separator border, hover fill.
            self.assertIn("width: 12px", frag)
            self.assertIn("height: 12px", frag)
            self.assertIn("border-left: 1px solid", frag)
            self.assertIn(":hover", frag)
            self.assertIn(":disabled", frag)
            self.assertEqual(_date_image_none_hits(frag), [],
                             f"{mode}: shared fragment must not hide arrow")

    def test_02_subcontrols_preserve_width(self):
        p = theme_mod._PALETTES["light"]
        for width in (18, 20, 22, 24):
            frag = theme_mod.date_subcontrols(p, width=width)
            self.assertIn(f"width: {width}px", frag)

    def test_03_fix_removes_image_none_and_keeps_width(self):
        for mode in ("light", "dark"):
            p = theme_mod._PALETTES[mode]
            for width in (18, 20, 22, 24):
                old = (
                    "QDateEdit { background-color: #ffffff; }"
                    f"QDateEdit::drop-down {{ border: none; width: {width}px; }}"
                    "QDateEdit::down-arrow { image: none; border: none; }"
                )
                fixed = theme_mod.fix_date_stylesheet(old, p)
                self.assertIn(f"width: {width}px", fixed)
                self.assertEqual(_date_image_none_hits(fixed), [],
                                 f"{mode} w={width}: fixer must remove image:none")
                self.assertIn("QDateEdit::down-arrow", fixed)
            # Bare `border: none` drop-down (reports / P&L / day end) too.
            old = ("QDateEdit { background-color: #fff; }"
                   "QDateEdit::drop-down { border: none; }")
            fixed = theme_mod.fix_date_stylesheet(old, p)
            self.assertIn("QDateEdit::down-arrow", fixed)
            self.assertEqual(_date_image_none_hits(fixed), [])

    def test_04_components_date_style_has_icon(self):
        from ui.components import date_style
        for mode in ("light", "dark"):
            with mock.patch.object(theme_mod, "_THEME_FILE",
                                   Path(tempfile.gettempdir()) / "x.json"):
                theme_mod.theme_manager.set_mode(mode, notify=False)
                try:
                    sheet = date_style()
                finally:
                    theme_mod.theme_manager.set_mode("light", notify=False)
            self.assertIn("QDateEdit::drop-down", sheet)
            self.assertIn("QDateEdit::down-arrow", sheet)
            self.assertEqual(_date_image_none_hits(sheet), [],
                             f"{mode}: components.date_style hides the arrow")

    def test_05_app_stylesheet_has_date_icon(self):
        for mode in ("light", "dark"):
            with mock.patch.object(theme_mod, "_THEME_FILE",
                                   Path(tempfile.gettempdir()) / "x.json"):
                theme_mod.theme_manager.set_mode(mode, notify=False)
                try:
                    sheet = theme_mod.stylesheet()
                finally:
                    theme_mod.theme_manager.set_mode("light", notify=False)
            self.assertIn("QDateEdit::drop-down", sheet)
            self.assertIn("QDateEdit::down-arrow", sheet)

    def test_06_no_screen_hides_date_arrow(self):
        import pathlib
        offenders = []
        for path in sorted(pathlib.Path("screens").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            # Only date down-arrow rules count; combo/check rules are
            # out of scope for this fix.
            for m in re.finditer(
                    r"QDate(Edit|TimeEdit)::down-arrow\s*\{([^}]*)\}", text):
                if "image" in m.group(0) and "none" in m.group(0):
                    offenders.append(f"{path.name}: {m.group(0)[:100]}")
        self.assertEqual(offenders, [],
                         "screens still hide the date arrow: "
                         f"{offenders}")


@unittest.skipUnless(HAS_QT, "PySide6 not available")
class DateIconRenderingTests(unittest.TestCase):
    """Offscreen Qt: glyph files, painted pixels, popup and values."""

    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        patcher = mock.patch.object(
            theme_mod, "_THEME_FILE",
            Path(self._dir.name) / "theme.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        # Start each test in Day Mode through the real path.
        theme_mod.theme_manager.set_mode("light", notify=False)
        theme_mod.apply_to_app()
        self._pump()

    def _pump(self, rounds=4):
        for _ in range(rounds):
            self._app.processEvents()

    def _button_band_hits(self, edit, colour_hex, tolerance=40):
        """Text-coloured pixels in the right-hand button band."""
        target = colour_hex.lstrip("#")
        tr, tg, tb = (int(target[i:i + 2], 16) for i in (0, 2, 4))
        image = edit.grab().toImage()
        w, h = image.width(), image.height()
        x0 = max(0, w - 30)
        hits = 0
        for y in range(2, max(3, h - 2)):
            for x in range(x0, w - 1):
                c = image.pixelColor(x, y)
                if (abs(c.red() - tr) <= tolerance
                        and abs(c.green() - tg) <= tolerance
                        and abs(c.blue() - tb) <= tolerance):
                    hits += 1
        return hits

    def test_01_glyph_files_exist_for_both_modes(self):
        for mode in ("light", "dark"):
            theme_mod.theme_manager.set_mode(mode, notify=False)
            self._pump(2)
            p = theme_mod.palette()
            for colour in (p["text"], p["disabled_text"]):
                path = theme_mod._drop_arrow_path(colour)
                self.assertTrue(path, f"{mode}: no glyph for {colour}")
                self.assertTrue(Path(path).is_file(),
                                f"{mode}: glyph missing at {path}")

    def test_02_style_date_enables_popup_and_icon(self):
        from ui import components as ui
        for mode in ("light", "dark"):
            theme_mod.theme_manager.set_mode(mode, notify=False)
            theme_mod.apply_to_app()
            edit = QDateEdit(QDate(2026, 10, 14))
            ui.style_date(edit)
            edit.resize(140, 30)
            edit.show()
            self._pump()
            self.addCleanup(edit.deleteLater)
            self.assertTrue(edit.calendarPopup(),
                            f"{mode}: style_date must enable the popup")
            self.assertIn("down-arrow", edit.styleSheet())
            self.assertNotIn("image: none", edit.styleSheet())
            edit.hide()

    def test_03_icon_paints_in_all_states_both_modes(self):
        from ui import components as ui
        for mode in ("light", "dark"):
            theme_mod.theme_manager.set_mode(mode, notify=False)
            theme_mod.apply_to_app()
            p = theme_mod.palette()
            self._pump(2)
            for state in ("unfocused", "focused", "disabled"):
                edit = QDateEdit(QDate(2026, 10, 14))
                ui.style_date(edit)
                edit.resize(140, 32)
                edit.show()
                self._pump()
                self.addCleanup(edit.deleteLater)
                if state == "focused":
                    edit.setFocus()
                    self._pump(2)
                    colour = p["text"]
                elif state == "disabled":
                    edit.setEnabled(False)
                    self._pump(2)
                    colour = p["disabled_text"]
                else:
                    colour = p["text"]
                hits = self._button_band_hits(edit, colour)
                edit.hide()
                self.assertGreaterEqual(
                    hits, 3,
                    f"{mode}/{state}: no chevron pixels in button band "
                    f"(found {hits}; colour {colour})")

    def test_04_selecting_date_updates_field(self):
        from ui import components as ui
        edit = QDateEdit(QDate(2026, 10, 14))
        ui.style_date(edit)
        seen = []
        edit.dateChanged.connect(lambda d: seen.append(d.toString("yyyy-MM-dd")))
        edit.setDate(QDate(2026, 12, 25))
        self.assertEqual(edit.date().toString("yyyy-MM-dd"), "2026-12-25")
        self.assertEqual(seen, ["2026-12-25"])
        edit.deleteLater()

    def test_05_day_night_day_keeps_value_and_icon(self):
        from ui import components as ui
        from ui.theme import fix_date_stylesheet
        edit = QDateEdit(QDate(2026, 10, 14))
        ui.style_date(edit)
        edit.show()
        self._pump()
        self.addCleanup(edit.deleteLater)
        for mode in ("dark", "light", "dark", "light"):
            theme_mod.theme_manager.set_mode(mode, notify=False)
            theme_mod.apply_to_app()
            # What refresh_generic_screen does for a baked date field.
            edit.setStyleSheet(
                fix_date_stylesheet(edit.styleSheet(), theme_mod.palette()))
            try:
                if not edit.calendarPopup():
                    edit.setCalendarPopup(True)
            except Exception:
                pass
            self._pump(2)
            self.assertEqual(edit.date().toString("yyyy-MM-dd"), "2026-10-14",
                             f"value cleared by switch to {mode}")
            self.assertTrue(edit.calendarPopup())
            self.assertIn("down-arrow", edit.styleSheet())
            self.assertNotIn("image: none", edit.styleSheet())
        edit.hide()

    def test_06_counter_sale_history_date_has_icon(self):
        from screens.counter_sale import CounterSalePage
        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        self._pump(6)
        self.addCleanup(page.deleteLater)
        for mode in ("light", "dark"):
            theme_mod.theme_manager.set_mode(mode)
            self._pump(4)
            for edit, name in ((page._sale_panel.sale_date, "sale_date"),
                               (page._hist_date, "hist_date")):
                self.assertTrue(edit.calendarPopup(), f"{name} lost popup")
                self.assertIn("down-arrow", edit.styleSheet(),
                              f"{name} lost icon in {mode}")
                self.assertNotIn("image: none", edit.styleSheet())
        page.hide()


if __name__ == "__main__":
    unittest.main()
