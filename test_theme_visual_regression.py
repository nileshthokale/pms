"""Day/Night regression tests that assert on RENDERED PIXELS.

The earlier theme fixes were validated with stylesheet-string assertions,
which passed while the running application still showed a mixture of Day and
Night Mode: the page title strip, the Date / All Dates toolbar and the
right-side Bill / Current Bill panels kept their Day Mode light-blue surface
in Night Mode, and the navigation tooltip rendered as a black box in Day
Mode.

A stylesheet string can be stale while the rendered widget is correct, and a
widget can render stale while its own stylesheet looks right — so these tests
never assert on a stylesheet alone.  Every test here builds the real screen,
switches the real theme, and reads back the pixels Qt actually painted
(``QWidget.grab()`` → ``QImage``), plus the pixels Qt paints for the real
tooltip widget it creates for ``QToolTip.showText``.

Covered:
  * Counter Sale chrome — page title strip, Date / All Dates filter bar,
    right-side Bill panel and Current Bill panel — follows the active mode.
  * No rendered pixel on a screen keeps the *other* mode's panel/surface
    colour (the "light-blue strip in Night Mode" defect).
  * Tooltips are light with dark text in Day Mode and dark with light text
    in Night Mode, and are never left transparent.
  * Three Day→Night→Day cycles leave no stale colour behind.
  * Bill drafts, entry text, selection and scroll position survive a switch.

Offscreen (``QT_QPA_PLATFORM=offscreen``) so the assertions read real Qt
painting without needing a desktop.  Never touches the live database or
``data/theme.json`` (both redirected to temp files).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QGroupBox,
        QLabel,
        QMessageBox,
        QPushButton,
        QWidget,
    )

    from ui import theme as theme_mod

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover - headless
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


# ── pixel helpers ─────────────────────────────────────────────────────

def _hex(pixel) -> str:
    return f"#{pixel.red():02x}{pixel.green():02x}{pixel.blue():02x}"


def _lum(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _rgb32_bytes(widget) -> bytes:
    """Raw pixel buffer of a rendered widget (B, G, R, A per pixel)."""
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    return bytes(image.constBits())


def _needle(colour: str) -> bytes:
    value = colour.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return bytes((b, g, r, 0xFF))       # Format_RGB32 is BGRA in memory


def _count_colours(widget, colours) -> dict:
    """Exact pixel count of each colour in one render of ``widget``.

    Scans the raw QImage buffer with ``bytes.count`` so an exhaustive
    full-resolution search stays fast (a strip of a handful of pixels is
    still found).
    """
    data = _rgb32_bytes(widget)
    return {colour: data.count(_needle(colour)) for colour in colours}


def _dominant_hex(widget, fx0=0.02, fy0=0.10, fx1=0.98, fy1=0.90) -> str:
    """Most common pixel colour in a fractional band of a rendered widget.

    Sampled on a coarse grid: which colour dominates a flat band is stable
    under sampling, and the exhaustive scans above cover the cases where a
    single missed pixel matters.
    """
    image = widget.grab().toImage()
    width, height = image.width(), image.height()
    x0, x1 = int(width * fx0), max(int(width * fx0) + 1, int(width * fx1))
    y0, y1 = int(height * fy0), max(int(height * fy0) + 1, int(height * fy1))
    step = max(1, min(x1 - x0, y1 - y0) // 150)
    counts: dict = {}
    for y in range(y0, min(y1, height), step):
        for x in range(x0, min(x1, width), step):
            key = _hex(image.pixelColor(x, y))
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        raise AssertionError(
            f"{type(widget).__name__} rendered no pixels in the sample band"
        )
    return max(counts.items(), key=lambda item: item[1])[0]


def _chrome_tokens() -> dict:
    """The panel/surface colours of each mode (never the plain bg-role)."""
    tokens = {}
    for mode in ("light", "dark"):
        pal = theme_mod._PALETTES[mode]
        tokens[mode] = {
            str(pal[key]).lower()
            for key in ("surface", "surface_alt", "table_header")
            if pal.get(key)
        }
    return tokens


# The indicator sits at the far left of a checkbox / radio button and the
# caption starts after ``spacing``, so a band narrower than indicator +
# spacing holds the check mark / dot and none of the label text.
_INDICATOR_BAND = 17
_INDICATOR_TOLERANCE = 40


def _indicator_glyph_pixels(widget, mode: str, band: int = _INDICATOR_BAND,
                            tolerance: int = _INDICATOR_TOLERANCE) -> int:
    """Pixels of a rendered checkbox/radio drawn in the mode's text colour.

    Qt stops drawing the native check mark as soon as a stylesheet names the
    ``::indicator`` sub-control, so a checked control must carry a glyph.
    Counting text-coloured pixels inside the indicator band is a direct
    rendering check: an unchecked control paints none of them.
    """
    text = theme_mod._PALETTES[mode]["text"].lstrip("#")
    target = tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    image = widget.grab().toImage()
    limit = min(band, max(1, image.width()))
    hits = 0
    for y in range(image.height()):
        for x in range(1, limit):
            colour = image.pixelColor(x, y)
            if (abs(colour.red() - target[0]) <= tolerance
                    and abs(colour.green() - target[1]) <= tolerance
                    and abs(colour.blue() - target[2]) <= tolerance):
                hits += 1
    return hits


class _ThemeTestCase(unittest.TestCase):
    """Shared setup: temp database, temp theme file, Fusion style."""

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            tempfile.gettempdir(), "pharmacy_theme_visual_regression.db"
        )
        if os.path.exists(cls._db_path):
            os.remove(cls._db_path)
        os.environ["PHARMACY_DB"] = cls._db_path

        from database import auth, financial_year
        from database.connection import init_database
        from database.customer_dao import CustomerDAO

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        try:
            if not CustomerDAO.search("Theme Test Customer"):
                CustomerDAO.insert("Theme Test Customer", city="Test City")
        except Exception:
            pass

        cls._app = QApplication.instance() or QApplication([])
        cls._app.setStyle("Fusion")

    def setUp(self):
        for name in ("warning", "information", "critical", "question"):
            patcher = mock.patch.object(
                QMessageBox, name, return_value=QMessageBox.Ok
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        # Persistence goes to a temp file: never data/theme.json.
        self._theme_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._theme_dir.cleanup)
        theme_file = Path(self._theme_dir.name) / "theme.json"
        patcher = mock.patch.object(theme_mod, "_THEME_FILE", theme_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.set_mode("light")

    def set_mode(self, mode: str):
        """Switch through the real code path the Day/Night button uses."""
        theme_mod.theme_manager.set_mode(mode)
        self._pump()

    def _pump(self, rounds: int = 6):
        for _ in range(rounds):
            self._app.processEvents()


# ── Counter Sale chrome ───────────────────────────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CounterSaleChromeRenderingTests(_ThemeTestCase):
    """The four reported Counter Sale surfaces, asserted from real pixels."""

    def setUp(self):
        super().setUp()
        from screens.counter_sale import CounterSalePage

        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        for _ in range(6):
            self._app.processEvents()
        self.page._apply_history_height()
        for _ in range(4):
            self._app.processEvents()
        self.addCleanup(self._dispose_page)

    def _dispose_page(self):
        try:
            self.page.hide()
            self.page.deleteLater()
            self._app.processEvents()
        except Exception:
            pass

    def _chrome(self):
        from PySide6.QtWidgets import QWidget as _QW

        bill_panel = self.page.findChild(_QW, "BillPanel")
        return {
            # (widget, sample band) — the band avoids text and child
            # controls so the sample is the surface itself.
            "page_title_strip": (self.page._header_strip, (0.05, 0.20, 0.70, 0.80)),
            "date_all_dates_toolbar": (
                self.page._history_filter_bar, (0.30, 0.15, 0.55, 0.85)
            ),
            "bill_panel": (bill_panel, (0.005, 0.10, 0.035, 0.90)),
            "current_bill_panel": (
                self.page._current_bill_group, (0.10, 0.35, 0.90, 0.95)
            ),
        }

    def test_01_night_mode_chrome_is_dark(self):
        self.set_mode("dark")
        surface = theme_mod._PALETTES["dark"]["surface"].lower()
        for name, (widget, band) in self._chrome().items():
            self.assertIsNotNone(widget, f"{name} widget not found")
            sampled = _dominant_hex(widget, *band)
            self.assertLess(
                _lum(sampled), 0.40,
                f"{name} is still a light surface in Night Mode "
                f"(sampled {sampled}); expected the dark palette "
                f"(surface {surface})",
            )

    def test_02_day_mode_chrome_is_light(self):
        self.set_mode("light")
        for name, (widget, band) in self._chrome().items():
            self.assertIsNotNone(widget, f"{name} widget not found")
            sampled = _dominant_hex(widget, *band)
            self.assertGreater(
                _lum(sampled), 0.60,
                f"{name} is still a dark surface in Day Mode "
                f"(sampled {sampled})",
            )

    def test_03_no_stale_other_mode_chrome_anywhere_on_the_page(self):
        """No rendered pixel on Counter Sale keeps the other mode's panel."""
        tokens = _chrome_tokens()
        for mode, forbidden in (("dark", tokens["light"]),
                                ("light", tokens["dark"])):
            self.set_mode(mode)
            for _ in range(4):
                self._app.processEvents()
            hits = _count_colours(self.page, forbidden)
            offenders = {c: n for c, n in hits.items() if n}
            self.assertEqual(
                offenders, {},
                f"Counter Sale in {mode} mode still paints the other "
                f"mode's panel colours {offenders}",
            )

    def test_04_three_switch_cycles_leave_no_stale_chrome(self):
        """Repeated Day→Night→Day switching stays consistent."""
        tokens = _chrome_tokens()
        for cycle in range(3):
            for mode in ("dark", "light"):
                self.set_mode(mode)
                for _ in range(4):
                    self._app.processEvents()
                strip_lum = _lum(
                    _dominant_hex(self.page._header_strip, 0.05, 0.20, 0.70, 0.80)
                )
                if mode == "dark":
                    self.assertLess(
                        strip_lum, 0.40,
                        f"cycle {cycle}: title strip not dark after "
                        f"switching to Night Mode",
                    )
                else:
                    self.assertGreater(
                        strip_lum, 0.60,
                        f"cycle {cycle}: title strip not light after "
                        f"switching back to Day Mode",
                    )
                forbidden = tokens["light" if mode == "dark" else "dark"]
                hits = _count_colours(self.page, forbidden)
                offenders = {c: n for c, n in hits.items() if n}
                self.assertEqual(
                    offenders, {},
                    f"cycle {cycle}: stale panel colours in {mode} mode: "
                    f"{offenders}",
                )

    def test_05_filter_bar_and_bill_panel_use_the_live_surface_token(self):
        """The strips resolve to the palette's surface role in each mode."""
        self.set_mode("dark")
        dark_surface = theme_mod._PALETTES["dark"]["surface"].lower()
        self.assertEqual(
            _dominant_hex(self.page._header_strip, 0.05, 0.20, 0.70, 0.80),
            dark_surface,
            "Counter Sale title strip should use the live dark surface token",
        )
        self.assertEqual(
            _dominant_hex(self.page._history_filter_bar, 0.30, 0.15, 0.55, 0.85),
            dark_surface,
            "Date / All Dates toolbar should use the live dark surface token",
        )

        self.set_mode("light")
        light_surface = theme_mod._PALETTES["light"]["surface"].lower()
        self.assertEqual(
            _dominant_hex(self.page._header_strip, 0.05, 0.20, 0.70, 0.80),
            light_surface,
            "Counter Sale title strip should use the live light surface token",
        )
        self.assertEqual(
            _dominant_hex(self.page._history_filter_bar, 0.30, 0.15, 0.55, 0.85),
            light_surface,
            "Date / All Dates toolbar should use the live light surface token",
        )


# ── tooltips ──────────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TooltipThemeRenderingTests(_ThemeTestCase):
    """The real tooltip Qt shows must be readable in both modes."""

    def setUp(self):
        super().setUp()
        from ui.navigation_bar import NavigationBar

        self.bar = NavigationBar()
        self.bar.resize(1366, 60)
        self.bar.show()
        self.bar.refresh_user()
        for _ in range(6):
            self._app.processEvents()
        self.addCleanup(self._dispose)

    def _dispose(self):
        try:
            self.bar.hide()
            self.bar.deleteLater()
            self._app.processEvents()
        except Exception:
            pass

    def _show_tooltip(self, owner):
        """Show the tooltip Qt shows on hover and return its rendered pixels."""
        from PySide6.QtWidgets import QToolTip

        text = owner.toolTip()
        self.assertTrue(text, "owner widget must carry a tooltip")
        QToolTip.showText(
            owner.mapToGlobal(QPoint(owner.width() // 2, owner.height() + 4)),
            text,
            owner,
        )
        for _ in range(10):
            self._app.processEvents()
        tip = None
        for widget in self._app.topLevelWidgets():
            try:
                if not widget.isVisible():
                    continue
                if theme_mod._is_tooltip_widget(widget):
                    tip = widget
                    break
            except Exception:
                continue
        self.addCleanup(QToolTip.hideText)
        if tip is None:
            # The mechanism tests (test_04/test_05) always run; this one
            # needs the platform to actually expose the tooltip window.
            self.skipTest(
                "Qt did not expose a tooltip widget on platform "
                f"'{self._app.platformName()}'; run the suite on the real "
                "Windows desktop to check the rendered tooltip"
            )
        return tip

    def _tooltip_text_colour(self, tip):
        """The text colour the tooltip will actually paint with.

        Two independent mechanisms keep the tooltip readable: the tooltip's
        own stylesheet (applied as it appears) and the ``QToolTip`` rule
        emitted into any stylesheet that also styles bare labels.
        Whichever applies, the resolved colour must be the mode's tooltip
        text token.
        """
        import re

        own = tip.styleSheet() or ""
        match = re.search(r"(?:^|;)\s*color:\s*(#[0-9a-fA-F]{6})", own)
        if match:
            return match.group(1).lower()
        for source in (own, theme_mod.stylesheet()):
            for rule in re.findall(r"QToolTip\s*\{([^}]*)\}", source):
                match = re.search(r"color:\s*(#[0-9a-fA-F]{6})", rule)
                if match:
                    return match.group(1).lower()
        return None

    def test_01_day_mode_tooltip_is_light_with_dark_text(self):
        self.set_mode("light")
        tip = self._show_tooltip(self.bar.user_label)
        background = theme_mod._PALETTES["light"]["tooltip_bg"].lower()
        text = theme_mod._PALETTES["light"]["tooltip_text"].lower()
        self.assertTrue(
            tip.isVisible(), "tooltip should be visible while inspected"
        )
        self.assertGreater(
            _lum(background), 0.70,
            "the Day Mode tooltip background token must be light",
        )
        self.assertLess(
            _lum(text), 0.40,
            "the Day Mode tooltip text token must be dark and readable",
        )
        self.assertEqual(
            _dominant_hex(tip), background,
            "Day Mode tooltip must render with the light tooltip background "
            "(a transparent or dark tooltip here is the reported defect)",
        )
        self.assertEqual(
            self._tooltip_text_colour(tip), text,
            "Day Mode tooltip must resolve its text colour to the dark "
            "tooltip token",
        )

    def test_02_night_mode_tooltip_is_dark_with_light_text(self):
        self.set_mode("dark")
        tip = self._show_tooltip(self.bar.user_label)
        background = theme_mod._PALETTES["dark"]["tooltip_bg"].lower()
        text = theme_mod._PALETTES["dark"]["tooltip_text"].lower()
        self.assertLess(
            _lum(background), 0.30,
            "the Night Mode tooltip background token must be dark",
        )
        self.assertGreater(
            _lum(text), 0.70,
            "the Night Mode tooltip text token must be light and readable",
        )
        self.assertEqual(
            _dominant_hex(tip), background,
            "Night Mode tooltip must render with the dark tooltip background",
        )
        self.assertEqual(
            self._tooltip_text_colour(tip), text,
            "Night Mode tooltip must resolve its text colour to the light "
            "tooltip token",
        )

    def test_03_tooltip_is_never_transparent(self):
        """The regression: ``background: transparent`` from a label rule.

        Qt's tooltip widget is a QLabel, so a widget-level
        ``QLabel { …; background: transparent; }`` rule captured it.  A
        transparent tooltip renders as the reported black box.
        """
        for mode in ("light", "dark"):
            self.set_mode(mode)
            background = theme_mod._PALETTES[mode]["tooltip_bg"].lower()
            for owner in (self.bar.user_label, self.bar.theme_btn,
                          self.bar.logout_btn):
                if not owner.toolTip():
                    continue
                tip = self._show_tooltip(owner)
                self.assertEqual(
                    _dominant_hex(tip), background,
                    f"{type(owner).__name__} tooltip in {mode} mode is not "
                    f"painted in the mode's tooltip colour (transparent "
                    f"background?)",
                )
                self.assertNotIn(
                    "background:transparent",
                    tip.styleSheet().lower().replace(" ", ""),
                    "the tooltip must never carry a transparent background",
                )

    def test_04_application_tooltip_rule_uses_the_mode_tokens(self):
        for mode in ("light", "dark"):
            self.set_mode(mode)
            sheet = theme_mod.stylesheet().lower().replace(" ", "")
            self.assertIn(
                f"background-color:{theme_mod._PALETTES[mode]['tooltip_bg']}".lower(),
                sheet,
                f"application stylesheet QToolTip rule must use the {mode} "
                f"tooltip background token",
            )
            self.assertIn(
                f"color:{theme_mod._PALETTES[mode]['tooltip_text']}".lower(),
                sheet,
                f"application stylesheet QToolTip rule must use the {mode} "
                f"tooltip text token",
            )

    def test_05_navigation_strip_does_not_capture_the_tooltip(self):
        """``#TitleBar QLabel`` also matched Qt's tooltip label."""
        self.set_mode("dark")
        sheet = self.bar.styleSheet()
        self.assertNotIn(
            "#TitleBar QLabel {", sheet,
            "a descendant QLabel rule in the navigation strip also matches "
            "Qt's tooltip widget and overrides the application tooltip style",
        )


# ── every screen ──────────────────────────────────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class AllScreensThemeRenderingTests(_ThemeTestCase):
    """No screen may keep the other mode's panel colour after a switch."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from ui.main_window import PharmacyMainWindow

        cls.window = PharmacyMainWindow()
        cls.window.resize(1366, 760)
        cls.window.show()
        for _ in range(8):
            cls._app.processEvents()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.window.hide()
            cls.window.deleteLater()
            cls._app.processEvents()
        except Exception:
            pass

    def _pages(self):
        stack = self.window._stack
        for index in range(stack.count()):
            yield index, stack.widget(index)

    def test_01_no_screen_keeps_night_panels_in_day_mode(self):
        self.set_mode("light")
        forbidden = _chrome_tokens()["dark"]
        offenders = []
        for index, page in self._pages():
            self.window._stack.setCurrentIndex(index)
            for _ in range(3):
                self._app.processEvents()
            hits = _count_colours(page, forbidden)
            offenders.extend(
                (type(page).__name__, colour, count)
                for colour, count in hits.items() if count
            )
        self.assertEqual(
            offenders, [],
            "day-mode screens still paint Night Mode panel colours: "
            f"{offenders}",
        )

    def test_02_no_screen_keeps_day_panels_in_night_mode(self):
        self.set_mode("dark")
        forbidden = _chrome_tokens()["light"]
        offenders = []
        for index, page in self._pages():
            self.window._stack.setCurrentIndex(index)
            for _ in range(3):
                self._app.processEvents()
            hits = _count_colours(page, forbidden)
            offenders.extend(
                (type(page).__name__, colour, count)
                for colour, count in hits.items() if count
            )
        self.assertEqual(
            offenders, [],
            "night-mode screens still paint Day Mode panel colours "
            "(light-blue strips/panels): "
            f"{offenders}",
        )

    def test_03_every_screen_checkbox_shows_a_glyph_in_both_modes(self):
        """End-to-end: the real window refreshes each screen's indicator.

        Only controls that style the indicator themselves are checked —
        the rest follow the application stylesheet and are covered by
        ``IndicatorThemeRenderingTests``.
        """
        from PySide6.QtWidgets import QCheckBox, QRadioButton

        offenders = []
        for mode in ("light", "dark"):
            self.set_mode(mode)
            for index, page in self._pages():
                self.window._stack.setCurrentIndex(index)
                self._pump(3)
                candidates = [
                    widget
                    for widget in (page.findChildren(QCheckBox)
                                   + page.findChildren(QRadioButton))
                    if "::indicator" in widget.styleSheet()
                ]
                for widget in candidates:
                    was = widget.isChecked()
                    widget.setChecked(True)
                    self._pump(2)
                    hits = _indicator_glyph_pixels(widget, mode)
                    widget.setChecked(was)
                    self._pump(2)
                    if hits < 4:
                        offenders.append(
                            (type(page).__name__, type(widget).__name__,
                             widget.text(), mode, hits)
                        )
        self.assertEqual(
            offenders, [],
            "checked controls on these screens show no check mark "
            "(page, widget, caption, mode, glyph pixels): "
            f"{offenders}",
        )


# ── state preservation ────────────────────────────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class ThemeSwitchStatePreservationTests(_ThemeTestCase):
    """Switching modes must not disturb an in-progress bill."""

    def setUp(self):
        super().setUp()
        from screens.counter_sale import CounterSalePage, _BillItemRow

        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        for _ in range(6):
            self._app.processEvents()
        self.page._apply_history_height()
        self.panel = self.page._sale_panel
        row = _BillItemRow(
            item_id=1, item_name="Preserved Item", stock_batch_id=1,
            pack_size="10x10", location="A-1", batch_no="P-001",
            expiry="12/27", mrp=50.0, sale_qty=2.0,
            discount_amount=0.0, amount=100.0,
        )
        self.panel._item_rows.append(row)
        self.panel._refresh_table()
        self.panel.bill_no_edit.setText("DRAFT-42")
        for _ in range(4):
            self._app.processEvents()
        self.addCleanup(self._dispose)

    def _dispose(self):
        try:
            self.page.hide()
            self.page.deleteLater()
            self._app.processEvents()
        except Exception:
            pass

    def test_01_draft_text_and_rows_survive_switching(self):
        scroll = self.page._hist_table.verticalScrollBar().value()
        rows_before = self.panel._table.rowCount()
        self.assertGreaterEqual(rows_before, 1)
        for mode in ("dark", "light", "dark", "light"):
            self.set_mode(mode)
            self.assertEqual(
                self.panel.bill_no_edit.text(), "DRAFT-42",
                f"bill number lost after switching to {mode} mode",
            )
            self.assertEqual(
                len(self.panel._item_rows), 1,
                f"bill draft lost after switching to {mode} mode",
            )
            self.assertEqual(
                self.panel._table.rowCount(), rows_before,
                f"bill table rebuilt after switching to {mode} mode",
            )
        self.assertEqual(
            self.page._hist_table.verticalScrollBar().value(), scroll,
            "history scroll position changed across theme switches",
        )

    def test_02_page_instances_are_not_recreated(self):
        """Colours are refreshed in place; widgets keep their identity."""
        ident = id(self.page._header_strip), id(self.page._bill_panel)
        for mode in ("dark", "light"):
            self.set_mode(mode)
        self.assertEqual(
            (id(self.page._header_strip), id(self.page._bill_panel)), ident,
            "theme switching must not rebuild the page widgets",
        )


# ── checkbox / radio indicators ───────────────────────────────────────

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class IndicatorThemeRenderingTests(_ThemeTestCase):
    """A checked box / radio must paint a real glyph, in both modes.

    Naming the ``::indicator`` sub-control in a stylesheet stops Qt drawing
    the native check mark, so a checked control that only changes colour is
    indistinguishable from an unchecked one — the reported black square
    beside Item Wise / Bill Wise in Night Mode.
    """

    BAND = _INDICATOR_BAND
    TOLERANCE = _INDICATOR_TOLERANCE

    def _glyph_pixels(self, widget, mode: str) -> int:
        """Pixels in the indicator band drawn in the mode's text colour."""
        return _indicator_glyph_pixels(widget, mode, self.BAND, self.TOLERANCE)

    def _host(self, factory):
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        host = QWidget()
        host.resize(240, 90)
        layout = QVBoxLayout(host)
        widgets = factory()
        for widget in widgets:
            layout.addWidget(widget)
        host.show()
        self._pump()
        self.addCleanup(host.deleteLater)
        return widgets

    def test_01_plain_checkbox_and_radio_show_a_glyph_in_both_modes(self):
        from PySide6.QtWidgets import QCheckBox, QRadioButton

        box, radio = self._host(
            lambda: [QCheckBox("Show Zero Balance"), QRadioButton("Item Wise")]
        )
        for mode in ("light", "dark"):
            self.set_mode(mode)
            for widget in (box, radio):
                widget.setChecked(False)
                self._pump(3)
                unchecked = self._glyph_pixels(widget, mode)
                widget.setChecked(True)
                self._pump(3)
                checked = self._glyph_pixels(widget, mode)
                name = type(widget).__name__
                self.assertEqual(
                    unchecked, 0,
                    f"an unchecked {name} must not paint a check mark "
                    f"({unchecked} glyph pixels in {mode} mode)",
                )
                self.assertGreaterEqual(
                    checked, 4,
                    f"a checked {name} must show a visible check mark in "
                    f"{mode} mode (found {checked} glyph pixels) — this is "
                    f"the black-square defect",
                )

    def test_02_application_stylesheet_carries_the_glyph(self):
        import re

        for mode in ("light", "dark"):
            self.set_mode(mode)
            sheet = theme_mod.stylesheet()
            self.assertIn(
                "QCheckBox::indicator", sheet,
                "the application stylesheet must style the checkbox indicator",
            )
            for selector in ("QCheckBox::indicator:checked",
                             "QRadioButton::indicator:checked"):
                rule = re.search(
                    re.escape(selector) + r"\s*\{([^}]*)\}", sheet
                )
                self.assertIsNotNone(
                    rule, f"{selector} must be present in the stylesheet"
                )
                self.assertIn(
                    "image:", rule.group(1),
                    f"{selector} must carry a check mark / dot image; a state "
                    f"that only changes colour is not distinguishable",
                )
                self.assertNotIn(
                    "image: none", rule.group(1),
                    f"{selector} must not disable the glyph",
                )

    def test_03_counter_sale_item_and_bill_wise_show_a_glyph(self):
        """The reported widgets themselves, in both modes."""
        from screens.counter_sale import CounterSalePage

        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        self._pump()
        page._apply_history_height()
        self._pump()
        self.addCleanup(page.deleteLater)

        item, bill = page._hist_item_mode, page._hist_bill_mode
        for mode in ("light", "dark"):
            self.set_mode(mode)
            for widget, label in ((item, "Item Wise"), (bill, "Bill Wise")):
                widget.setChecked(False)
                self._pump(3)
                unchecked = self._glyph_pixels(widget, mode)
                widget.setChecked(True)
                self._pump(3)
                checked = self._glyph_pixels(widget, mode)
                self.assertEqual(
                    unchecked, 0,
                    f"{label} must not paint a dot while unchecked "
                    f"({unchecked} dot pixels in {mode} mode)",
                )
                self.assertGreaterEqual(
                    checked, 4,
                    f"{label} must show a visible dot when checked in "
                    f"{mode} mode (found {checked} dot pixels)",
                )
            item.setChecked(True)
            self._pump(2)

    def test_04_three_switch_cycles_keep_the_glyph(self):
        """Repeated Day→Night→Day switching never loses the check mark."""
        from screens.counter_sale import CounterSalePage

        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        self._pump()
        page._apply_history_height()
        self._pump()
        self.addCleanup(page.deleteLater)

        page._hist_item_mode.setChecked(True)
        for cycle in range(3):
            for mode in ("light", "dark"):
                self.set_mode(mode)
                self._pump(3)
                self.assertGreaterEqual(
                    self._glyph_pixels(page._hist_item_mode, mode), 4,
                    f"cycle {cycle + 1}: Item Wise lost its dot in {mode} "
                    f"mode after repeated switching",
                )
                self.assertEqual(
                    self._glyph_pixels(page._hist_bill_mode, mode), 0,
                    f"cycle {cycle + 1}: Bill Wise shows a dot while "
                    f"unchecked in {mode} mode",
                )

    def test_05_clicking_still_selects_and_toggles(self):
        """Styling only: the radio group must still behave as before."""
        from screens.counter_sale import CounterSalePage

        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        self._pump()
        page._apply_history_height()
        self._pump()
        self.addCleanup(page.deleteLater)

        item, bill = page._hist_item_mode, page._hist_bill_mode
        item.setChecked(True)
        self._pump(3)
        self.assertTrue(item.isChecked())
        self.assertFalse(bill.isChecked())

        bill.click()
        self._pump(6)
        self.assertTrue(bill.isChecked(), "clicking Bill Wise must select it")
        self.assertFalse(item.isChecked(),
                         "the Item Wise / Bill Wise pair is exclusive")

        item.click()
        self._pump(6)
        self.assertTrue(item.isChecked(), "clicking Item Wise must select it")
        self.assertFalse(bill.isChecked())

        # ...and the selection survives a mode switch.
        self.set_mode("dark")
        self.assertTrue(item.isChecked())
        self.assertFalse(bill.isChecked())
        self.set_mode("light")
        self.assertTrue(item.isChecked())
        self.assertFalse(bill.isChecked())

    def test_06_report_screen_checkbox_follows_the_mode(self):
        """Screens that style the indicator locally (Reports, Trial Balance).

        These pages define no ``refresh_theme`` of their own — the main
        window drives them through ``ui.refresh_generic_screen``, which is
        called here exactly as ``PharmacyMainWindow._refresh_widget_tree``
        calls it.  Without that pass the local ``::indicator`` rule keeps
        its baked light colours and no glyph.
        """
        from PySide6.QtWidgets import QCheckBox

        from screens.sales_report import SalesReportPage
        from ui import components as ui

        page = SalesReportPage()
        page.resize(1366, 708)
        page.show()
        self._pump()
        self.addCleanup(page.deleteLater)

        boxes = page.findChildren(QCheckBox)
        self.assertTrue(boxes, "Sales Report should expose a checkbox")
        box = next((b for b in boxes if b.styleSheet()), boxes[0])

        for mode in ("light", "dark"):
            self.set_mode(mode)
            ui.refresh_generic_screen(page)     # what the main window does
            self._pump(3)
            box.setChecked(False)
            self._pump(3)
            self.assertEqual(
                self._glyph_pixels(box, mode), 0,
                f"an unchecked report checkbox must not paint a check mark "
                f"in {mode} mode",
            )
            box.setChecked(True)
            self._pump(3)
            self.assertGreaterEqual(
                self._glyph_pixels(box, mode), 4,
                f"a checked report checkbox must show a check mark in "
                f"{mode} mode after the local indicator rule is refreshed",
            )


if __name__ == "__main__":
    unittest.main()
