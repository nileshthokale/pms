"""Focused typography tests for the readable-text pass.

This is the guard for the "larger, bolder, blacker" UI contract.  It checks
three layers, because a stylesheet declaration alone proves nothing:

1. the shared type scale in ``ui.theme`` (sizes, ordering, black text),
2. the real rendered ``QFont`` on live widgets (pixel size + weight), and
3. a source audit of every screen, so a new screen cannot quietly reintroduce
   an 11 px table or a grey caption.

GUI tests skip only when PySide6 is unavailable.
"""

import importlib.util
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = Path(__file__).resolve().parent

# ui/theme.py is deliberately Qt-free, so load it straight from its file:
# the type scale and the palette contract are then checkable headlessly,
# exactly like test_theme.py does.
_spec = importlib.util.spec_from_file_location(
    "ui_theme_typography", ROOT / "ui" / "theme.py"
)
theme = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(theme)

try:
    from PySide6.QtWidgets import QApplication, QTableWidget

    from ui import components as ui_components

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


def _declared_px(stylesheet: str) -> int | None:
    """Font size declared in a stylesheet, normalised to px at 96 dpi."""
    match = re.search(r"font-size:\s*(\d+)(px|pt)", stylesheet)
    if not match:
        return None
    value = int(match.group(1))
    return value if match.group(2) == "px" else round(value * 96 / 72)


# ── 1. Shared type scale ──────────────────────────────────────────────

class TypeScaleTests(unittest.TestCase):
    """The single source of truth must express the required hierarchy."""

    def setUp(self):
        # The stylesheet follows the persisted theme mode; force light mode
        # in memory (never on disk) so the light-theme contract is what is
        # asserted, whatever the developer's last toggle was.
        self._original_mode = theme.theme_manager._mode
        theme.theme_manager._mode = "light"
        self.addCleanup(setattr, theme.theme_manager, "_mode",
                        self._original_mode)

    def test_01_scale_is_defined(self):
        for name in ("TYPE_PAGE_TITLE", "TYPE_SECTION_HEADER",
                     "TYPE_TABLE_HEADER", "TYPE_TABLE_DATA",
                     "TYPE_FORM_LABEL", "TYPE_INPUT", "TYPE_INPUT_COMPACT",
                     "TYPE_VALUE", "TYPE_VALUE_EMPHASIS", "TYPE_BUTTON",
                     "TYPE_HINT"):
            value = getattr(theme, name, None)
            self.assertIsInstance(value, int, f"{name} missing from the scale")
            self.assertGreaterEqual(value, 11, f"{name} below the readable floor")

    def test_02_table_text_meets_the_minimum(self):
        self.assertGreaterEqual(theme.TYPE_TABLE_DATA, 12,
                                "table data must be at least 12 px")
        self.assertGreaterEqual(theme.TYPE_TABLE_HEADER, 12,
                                "table headers must be at least 12 px")

    def test_03_hierarchy_is_ordered(self):
        self.assertGreater(theme.TYPE_PAGE_TITLE, theme.TYPE_SECTION_HEADER)
        self.assertGreaterEqual(theme.TYPE_SECTION_HEADER,
                                theme.TYPE_TABLE_HEADER)
        self.assertGreaterEqual(theme.TYPE_VALUE_EMPHASIS, theme.TYPE_VALUE)
        self.assertGreaterEqual(theme.TYPE_VALUE, theme.TYPE_TABLE_DATA)

    def test_04_light_palette_is_black_text(self):
        light = theme._PALETTES["light"]
        for key in ("text", "header_text", "selected_text"):
            self.assertEqual(light[key], "#000000",
                             f"{key} must be true black in the light theme")

    def test_05_light_backgrounds_are_untouched(self):
        """The black-text pass must not have flattened the light design."""
        light = theme._PALETTES["light"]
        self.assertEqual(light["bg"], "#ffffff")
        self.assertEqual(light["surface"], "#dce9f6")
        self.assertEqual(light["table_header"], "#dce9f6")
        self.assertEqual(light["accent"], "#2f6fb0")
        self.assertEqual(light["danger"], "#b23a3a")
        self.assertEqual(light["selected"], "#cfe2f3")

    def test_06_dim_text_is_only_for_hints(self):
        """``text_dim`` stays available for hints but is not the data colour."""
        light = theme._PALETTES["light"]
        self.assertNotEqual(light["text"], light["text_dim"])
        self.assertNotIn(light["text_dim"],
                         ("#777777", "#888888", "#999999"))

    def test_07_application_stylesheet_sets_the_floor(self):
        sheet = theme.stylesheet()
        for selector in ("QTableWidget", "QHeaderView::section"):
            self.assertIn(selector, sheet)
        # table body / header sizes appear in the global sheet
        self.assertIn(f"font-size: {theme.TYPE_TABLE_DATA}px", sheet)
        self.assertIn(f"font-size: {theme.TYPE_TABLE_HEADER}px", sheet)
        self.assertIn(f"color: {theme._PALETTES['light']['text']}", sheet)

    def test_08_stylesheet_never_uses_point_sizes(self):
        """One unit everywhere: pt/px drift was the original inconsistency."""
        self.assertNotRegex(theme.stylesheet(), r"font-size:\s*\d+pt")


# ── 2. Shared components ──────────────────────────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class SharedComponentTypographyTests(unittest.TestCase):
    """``ui.components`` must express the scale in px and expose real fonts."""

    def setUp(self):
        # ui.components reads the *live* palette; pin light mode in memory so
        # the black-text assertions cannot be flipped by a saved night-mode
        # preference.
        from ui import theme as live_theme
        self._original_mode = live_theme.theme_manager._mode
        live_theme.theme_manager._mode = "light"
        self.addCleanup(setattr, live_theme.theme_manager, "_mode",
                        self._original_mode)

    def test_01_components_styles_are_pixel_sized(self):
        for name, style in (
            ("label", ui_components.label_style()),
            ("section", ui_components.section_title_style()),
            ("table", ui_components.table_style()),
            ("table header", ui_components.table_header_style()),
            ("edit", ui_components.edit_style()),
            ("combo", ui_components.combo_style()),
            ("date", ui_components.date_style()),
            ("spin", ui_components.spin_style()),
            ("button", ui_components.btn_primary_style()),
        ):
            self.assertNotRegex(style, r"font-size:\s*\d+pt",
                                f"{name} style still uses pt")

    def test_02_component_sizes_match_the_scale(self):
        self.assertEqual(_declared_px(ui_components.label_style()),
                         theme.TYPE_FORM_LABEL)
        self.assertEqual(_declared_px(ui_components.table_style()),
                         theme.TYPE_TABLE_DATA)
        self.assertEqual(_declared_px(ui_components.table_header_style()),
                         theme.TYPE_TABLE_HEADER)
        self.assertEqual(_declared_px(ui_components.btn_primary_style()),
                         theme.TYPE_BUTTON)

    def test_03_header_style_is_bold_and_black(self):
        style = ui_components.table_header_style()
        self.assertIn("font-weight: bold", style)
        self.assertIn("#000000", style)

    def test_04_readable_font_builds_the_exact_size(self):
        for size in (11, 12, 13, 14, 18):
            font = ui_components.readable_font(size)
            self.assertEqual(font.pixelSize(), size)
            self.assertFalse(font.bold())
            self.assertTrue(ui_components.readable_font(size, bold=True).bold())

    def test_05_style_data_table_sets_the_real_font(self):
        app = QApplication.instance() or QApplication([])
        table = QTableWidget(2, 2)
        try:
            ui_components.style_data_table(table)
            self.assertEqual(table.font().pixelSize(), theme.TYPE_TABLE_DATA,
                             "cell font must be the real data size")
            header = table.horizontalHeader()
            self.assertEqual(header.font().pixelSize(),
                             theme.TYPE_TABLE_HEADER,
                             "header font must be the real header size")
            self.assertTrue(header.font().bold(),
                            "header font must be bold")
        finally:
            table.deleteLater()
            app.processEvents()

    def test_06_polish_page_lifts_an_unstyled_table(self):
        app = QApplication.instance() or QApplication([])
        table = QTableWidget(1, 1)
        try:
            self.assertEqual(table.font().pixelSize(), -1)
            ui_components.polish_page(table)
            self.assertEqual(table.font().pixelSize(), theme.TYPE_TABLE_DATA)
            self.assertEqual(table.horizontalHeader().font().pixelSize(),
                             theme.TYPE_TABLE_HEADER)
        finally:
            table.deleteLater()
            app.processEvents()

    def test_07_polish_page_respects_a_screen_that_declares_its_own_size(self):
        """A screen that pins a larger size keeps it."""
        app = QApplication.instance() or QApplication([])
        table = QTableWidget(1, 1)
        try:
            table.setStyleSheet("QTableWidget { font-size: 15px; }")
            ui_components.polish_page(table)
            self.assertEqual(table.font().pixelSize(), 15)
        finally:
            table.deleteLater()
            app.processEvents()

    def test_08_page_header_title_is_the_largest_text(self):
        header = ui_components.PageHeader("Sales / Counter Sale")
        try:
            title = header._title
            size = _declared_px(title.styleSheet())
            self.assertEqual(size, theme.TYPE_PAGE_TITLE)
            self.assertIn("font-weight: bold", title.styleSheet())
            self.assertIn("#000000", title.styleSheet())
        finally:
            header.deleteLater()


# ── 3. Source audit of every screen ───────────────────────────────────

class ScreenSourceTypographyTests(unittest.TestCase):
    """Every screen must respect the floor, without needing a GUI."""

    # The shared idiom every screen uses for its table body text:
    #     f"  font-size: 13px; font-family: 'Segoe UI';"
    _TABLE_BODY_RE = re.compile(
        r"font-size:\s*(\d+)(px|pt);\s*font-family:\s*'Segoe UI';"
    )
    _HEADER_SECTION_RE = re.compile(
        r"QHeaderView::section\s*\{\{.*?font-size:\s*(\d+)(px|pt).*?\}\}",
        re.DOTALL,
    )

    @staticmethod
    def _to_px(value: str, unit: str) -> int:
        number = int(value)
        return number if unit == "px" else round(number * 96 / 72)

    def _screen_files(self):
        return sorted(ROOT.glob("screens/*.py"))

    def test_01_no_screen_declares_small_table_data(self):
        offenders = []
        for path in self._screen_files():
            text = path.read_text(encoding="utf-8")
            for match in self._TABLE_BODY_RE.finditer(text):
                px = self._to_px(match.group(1), match.group(2))
                line_start = text.rfind("\n", 0, match.start()) + 1
                line = text[line_start:text.find("\n", match.start())]
                # Only the table-body declarations carry the two-space indent
                # before the size (combo/edit/dialog styles are one line too,
                # so confirm we are inside a QTableWidget block).
                head = text[max(0, match.start() - 300):match.start()]
                if "QTableWidget" not in head and "QComboBox" not in head:
                    continue
                if "QComboBox" in line or "QLineEdit" in line:
                    continue
                if px < 12:
                    offenders.append(f"{path.name}: {px}px table data")
        self.assertEqual(offenders, [],
                         "table data below the 12 px floor: " + ", ".join(offenders))

    def test_02_no_screen_declares_small_table_headers(self):
        offenders = []
        for path in self._screen_files():
            text = path.read_text(encoding="utf-8")
            for match in self._HEADER_SECTION_RE.finditer(text):
                px = self._to_px(match.group(1), match.group(2))
                if px < 12:
                    offenders.append(f"{path.name}: {px}px header")
        self.assertEqual(offenders, [],
                         "table headers below the 12 px floor: "
                         + ", ".join(offenders))

    def test_03_table_headers_are_bold_everywhere(self):
        offenders = []
        for path in self._screen_files():
            text = path.read_text(encoding="utf-8")
            for match in self._HEADER_SECTION_RE.finditer(text):
                if "font-weight: bold" not in match.group(0):
                    offenders.append(path.name)
        self.assertEqual(offenders, [],
                         "table headers must stay bold: " + ", ".join(offenders))

    def test_04_field_captions_are_not_grey(self):
        """A ``_lbl`` field-caption helper must not render dim grey text."""
        offenders = []
        for path in self._screen_files():
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(
                r"_LABEL_DIM = f\"color: \{_TEXT_DIM\}", text
            ):
                if path.name == "counter_sale.py":
                    continue  # reserved there for the dim "Paper: A6" note
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         "field captions must be black, not dim: "
                         + ", ".join(sorted(set(offenders))))

    def test_05_counter_sale_captions_use_the_shared_scale(self):
        text = (ROOT / "screens" / "counter_sale.py").read_text(encoding="utf-8")
        self.assertNotIn("font.setPixelSize(10)", text,
                         "counter sale captions must use the shared scale, "
                         "not a hard-coded 10 px font")
        for constant in ("TYPE_TABLE_DATA", "TYPE_TABLE_HEADER",
                         "TYPE_FORM_LABEL", "TYPE_VALUE",
                         "TYPE_VALUE_EMPHASIS", "TYPE_SECTION_HEADER"):
            self.assertIn(constant, text,
                          f"counter_sale must use {constant} from the scale")

    def test_06_no_screen_reintroduces_point_sizes(self):
        offenders = []
        for path in list(self._screen_files()) + sorted(ROOT.glob("ui/*.py")):
            if path.name == "theme.py":
                continue  # documented conversions live here
            text = path.read_text(encoding="utf-8")
            if re.search(r"font-size:\s*\d+pt", text):
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         "styles must use px, not pt: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
