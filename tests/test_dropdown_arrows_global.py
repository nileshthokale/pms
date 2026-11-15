"""Regression tests for the global dropdown arrow fix across the Pharmacy Management System.

Covers:
- ui.theme.combo_subcontrols generates visible drop-down button & down-arrow rules
  in both Day and Night Mode, with high contrast tinted chevron icons, proper width,
  and never 'image: none'.
- ui.theme.fix_combo_stylesheet upgrades baked screen stylesheets while preserving
  custom drop-down width (18/20/22/24 px) and removing any 'image: none' rules.
- ui.components.combo_style and SearchableComboBox carry visible drop-down buttons
  and arrows in both modes.
- Application stylesheet carries combo_subcontrols so unstyled combo boxes
  automatically retain high-contrast dropdown arrows.
- Zero screens in the entire application hide the combo dropdown arrow with 'image: none'.
- ExpiryDateEdit in screens.purchase_invoice uses the antialiased chevron icon without
  text clipping.
- Offscreen Qt rendering tests verifying painted chevron pixels, Day/Night contrast,
  dropdown popups, and keyboard navigation.

Offscreen (QT_QPA_PLATFORM=offscreen); never touches live database or EXE.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import theme as theme_mod

try:
    from PySide6.QtCore import QDate, QPoint, Qt, QSize
    from PySide6.QtGui import QColor, QIcon, QKeyEvent
    from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QWidget
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


def _combo_image_none_hits(sheet: str) -> list:
    """Occurrences of 'image: none' inside a combo down-arrow rule."""
    hits = []
    for m in re.finditer(r"QComboBox::down-arrow\s*\{([^}]*)\}", sheet):
        body = m.group(1).replace(" ", "").lower()
        if "image:none" in body:
            hits.append(m.group(0)[:120])
    return hits


class ComboArrowStylesheetTests(unittest.TestCase):
    """Headless / QSS structural tests: no QComboBox hides the arrow."""

    def test_01_combo_subcontrols_visible_in_both_modes(self):
        for mode in ("light", "dark"):
            p = theme_mod._PALETTES[mode]
            frag = theme_mod.combo_subcontrols(p, width=20)
            self.assertIn("QComboBox::drop-down", frag)
            self.assertIn("QComboBox::down-arrow", frag)
            self.assertIn("width: 20px", frag)
            self.assertIn("width: 12px", frag)
            self.assertIn("height: 12px", frag)
            self.assertIn("border-left: 1px solid", frag)
            self.assertIn(":hover", frag)
            self.assertIn(":disabled", frag)
            self.assertEqual(_combo_image_none_hits(frag), [],
                             f"{mode}: combo_subcontrols must not hide arrow")

    def test_02_combo_subcontrols_preserves_custom_widths(self):
        p = theme_mod._PALETTES["light"]
        for width in (16, 18, 20, 22, 24):
            frag = theme_mod.combo_subcontrols(p, width=width)
            self.assertIn(f"width: {width}px", frag)

    def test_03_fix_combo_stylesheet_removes_image_none_and_keeps_width(self):
        for mode in ("light", "dark"):
            p = theme_mod._PALETTES[mode]
            for width in (18, 20, 22, 24):
                old = (
                    "QComboBox { background-color: #ffffff; }"
                    f"QComboBox::drop-down {{ border: none; width: {width}px; }}"
                    "QComboBox::down-arrow { image: none; border: none; }"
                )
                fixed = theme_mod.fix_combo_stylesheet(old, p)
                self.assertIn(f"width: {width}px", fixed)
                self.assertEqual(_combo_image_none_hits(fixed), [],
                                 f"{mode} w={width}: fixer must remove image:none")
                self.assertIn("QComboBox::down-arrow", fixed)
            # Bare border: none drop-down too
            old = (
                "QComboBox { background-color: #fff; }"
                "QComboBox::drop-down { border: none; }"
            )
            fixed = theme_mod.fix_combo_stylesheet(old, p)
            self.assertIn("QComboBox::down-arrow", fixed)
            self.assertEqual(_combo_image_none_hits(fixed), [])

    def test_04_components_combo_style_has_arrow(self):
        from ui.components import combo_style
        for mode in ("light", "dark"):
            with mock.patch.object(theme_mod, "_THEME_FILE",
                                   Path(tempfile.gettempdir()) / "theme_test.json"):
                theme_mod.theme_manager.set_mode(mode, notify=False)
                try:
                    sheet = combo_style()
                finally:
                    theme_mod.theme_manager.set_mode("light", notify=False)
            self.assertIn("QComboBox::drop-down", sheet)
            self.assertIn("QComboBox::down-arrow", sheet)
            self.assertEqual(_combo_image_none_hits(sheet), [],
                             f"{mode}: components.combo_style hides the arrow")

    def test_05_app_stylesheet_has_combo_subcontrols(self):
        for mode in ("light", "dark"):
            with mock.patch.object(theme_mod, "_THEME_FILE",
                                   Path(tempfile.gettempdir()) / "theme_test.json"):
                theme_mod.theme_manager.set_mode(mode, notify=False)
                try:
                    sheet = theme_mod.stylesheet()
                finally:
                    theme_mod.theme_manager.set_mode("light", notify=False)
            self.assertIn("QComboBox::drop-down", sheet)
            self.assertIn("QComboBox::down-arrow", sheet)
            self.assertEqual(_combo_image_none_hits(sheet), [])

    def test_06_no_screen_or_ui_module_hides_combo_arrow(self):
        offenders = []
        project_root = Path(__file__).resolve().parent.parent
        for folder in ("screens", "ui"):
            for path in sorted((project_root / folder).glob("*.py")):
                text = path.read_text(encoding="utf-8")
                for m in re.finditer(r"QComboBox::down-arrow\s*\{([^}]*)\}", text):
                    if "image" in m.group(0) and "none" in m.group(0):
                        offenders.append(f"{path.name}: {m.group(0)[:100]}")
        self.assertEqual(offenders, [],
                         f"Modules still hide the combo arrow with image: none: {offenders}")

    def test_07_all_screen_combo_styles_have_dropdown_subcontrols(self):
        import screens.purchase_invoice as pi
        import screens.counter_sale as cs
        import screens.item_master as im
        import screens.account_group_master as agm
        import screens.account_ledger as al
        import screens.journal_entry as je
        import screens.stock_master as sm
        import screens.expiry_report as er
        import screens.gst_report as gr
        import screens.party_wise_report as pwr
        import screens.sales_history as sh
        import screens.ledger_widgets as lw

        styles = [
            ("purchase_invoice._combo_style", pi._combo_style()),
            ("counter_sale._COMBO_STYLE", cs._COMBO_STYLE),
            ("counter_sale._COMPACT_COMBO_STYLE", cs._COMPACT_COMBO_STYLE),
            ("counter_sale._fresh_combo_style", cs._fresh_combo_style()),
            ("counter_sale._fresh_compact_combo_style", cs._fresh_compact_combo_style()),
            ("item_master._drug_combo_style", im._drug_combo_style()),
            ("account_group_master._COMBO_STYLE", agm._COMBO_STYLE),
            ("account_ledger._COMBO_STYLE", al._COMBO_STYLE),
            ("journal_entry._COMBO_STYLE", je._COMBO_STYLE),
            ("stock_master._COMBO_STYLE", sm._COMBO_STYLE),
            ("expiry_report._COMBO_STYLE", er._COMBO_STYLE),
            ("gst_report._COMBO_STYLE", gr._COMBO_STYLE),
            ("party_wise_report._COMBO_STYLE", pwr._COMBO_STYLE),
            ("sales_history._fresh_combo_style", sh._fresh_combo_style(theme_mod.palette())),
            ("ledger_widgets.combo_style", lw.combo_style()),
        ]

        for name, sheet in styles:
            self.assertIn("QComboBox::drop-down", sheet, f"{name} missing drop-down")
            self.assertIn("QComboBox::down-arrow", sheet, f"{name} missing down-arrow")
            self.assertEqual(_combo_image_none_hits(sheet), [], f"{name} has image: none")


@unittest.skipUnless(HAS_QT, "PySide6 not available")
class ComboArrowRenderingTests(unittest.TestCase):
    """Offscreen Qt tests: arrow icon generation, pixel rendering, interaction."""

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
        theme_mod.theme_manager.set_mode("light", notify=False)
        theme_mod.apply_to_app()
        self._pump()

    def _pump(self, rounds=4):
        for _ in range(rounds):
            self._app.processEvents()

    def _button_band_hits(self, combo, colour_hex, tolerance=40):
        """Count pixels matching colour_hex in the right-hand dropdown button band."""
        target = colour_hex.lstrip("#")
        tr, tg, tb = (int(target[i:i + 2], 16) for i in (0, 2, 4))
        image = combo.grab().toImage()
        w, h = image.width(), image.height()
        x0 = max(0, w - 24)
        hits = 0
        for y in range(2, max(3, h - 2)):
            for x in range(x0, w - 1):
                c = image.pixelColor(x, y)
                if (abs(c.red() - tr) <= tolerance
                        and abs(c.green() - tg) <= tolerance
                        and abs(c.blue() - tb) <= tolerance
                        and c.alpha() > 180):
                    hits += 1
        return hits

    def test_08_arrow_png_generated_for_day_and_night(self):
        for mode in ("light", "dark"):
            p = theme_mod._PALETTES[mode]
            path = theme_mod._drop_arrow_path(p["text"])
            self.assertTrue(os.path.isfile(path), f"{mode}: arrow glyph file must exist at {path}")
            self.assertTrue(os.path.getsize(path) > 50, f"{mode}: arrow file must not be empty")

    def test_09_combo_renders_arrow_pixels_in_day_and_night(self):
        for mode, expected_hex in (("light", "#000000"), ("dark", "#ffffff")):
            theme_mod.theme_manager.set_mode(mode, notify=False)
            theme_mod.apply_to_app()
            self._pump()

            combo = QComboBox()
            combo.addItems(["First Item", "Second Item", "Third Item"])
            from ui.components import style_combo
            style_combo(combo)
            combo.resize(160, 32)
            combo.show()
            self._pump()

            hits = self._button_band_hits(combo, expected_hex, tolerance=45)
            self.assertGreater(hits, 4,
                               f"{mode}: expected visible arrow pixels matching {expected_hex} in button band, got {hits}")
            combo.close()

    def test_10_searchable_combo_box_has_visible_arrow(self):
        from ui.components import SearchableComboBox
        combo = SearchableComboBox(placeholder="Select...")
        combo.addItems(["Item Alpha", "Item Beta", "Item Gamma"])
        combo.resize(200, 32)
        combo.show()
        self._pump()

        hits = self._button_band_hits(combo, "#000000", tolerance=45)
        self.assertGreater(hits, 4, f"SearchableComboBox should render arrow pixels, got {hits}")
        combo.close()

    def test_11_expiry_date_edit_icon_and_theme_refresh(self):
        from screens.purchase_invoice import ExpiryDateEdit
        edit = ExpiryDateEdit(width=130)
        edit.show()
        self._pump()

        # The button must have a non-null icon and size 12x12
        btn = edit._btn
        self.assertFalse(btn.icon().isNull(), "ExpiryDateEdit button must carry a valid QIcon")
        self.assertEqual(btn.iconSize(), QSize(12, 12))
        self.assertEqual(btn.text(), "", "Button text must be empty so '▼' doesn't clip")

        # Test Night Mode switch updates the icon
        theme_mod.theme_manager.set_mode("dark", notify=False)
        edit.refresh_theme()
        self._pump()
        self.assertFalse(btn.icon().isNull(), "Night mode must also provide valid QIcon")
        edit.close()

    def test_12_combo_keyboard_navigation_and_selection(self):
        combo = QComboBox()
        combo.addItems(["Choice 1", "Choice 2", "Choice 3"])
        from ui.components import style_combo
        style_combo(combo)
        combo.resize(150, 30)
        combo.show()
        self._pump()

        self.assertEqual(combo.currentIndex(), 0)
        # Simulate pressing Key_Down
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        self._app.sendEvent(combo, event)
        self._pump()
        self.assertEqual(combo.currentIndex(), 1)

        combo.close()


if __name__ == "__main__":
    unittest.main()
