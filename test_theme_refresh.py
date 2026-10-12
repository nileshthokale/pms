"""Day/Night rendering regression tests (black-rectangle fix).

Covers the shared theme system and in-place refresh:

* Centralized palettes + application QPalette follow the mode (no stale
  Fusion defaults, no hardcoded black backgrounds).
* Application stylesheet covers frames, scroll areas, viewports, calendar
  popups, combo/completer popups, group boxes (opaque bg), indicators,
  corner buttons and disabled states — all from centralized tokens.
* Counter Sale refreshes in place (Bill Items group + bill/history tables +
  completer popups) without rebuilding and without losing drafts; Day Mode
  never retains a dark ``background-color: #000000`` surface.
* Generic screen refresh fixes group boxes / tables / inputs / buttons /
  labels for all other screens while preserving padding and variant text
  (primary white-on-accent stays white).
* Repeated Day/Night switches are stable and preserve state.

Offscreen (QT_QPA_PLATFORM=offscreen); never touches the live database or
data/theme.json (persistence redirected to temp files where needed).
"""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtWidgets import QApplication, QGroupBox, QTableWidget
    from PySide6.QtGui import QPalette
    HAS_QT = True
except ImportError:
    HAS_QT = False

from ui import theme as live_theme


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    return app


@unittest.skipUnless(HAS_QT, "PySide6 not available")
class ThemeRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = _app()

    def setUp(self):
        # Never pollute the real theme file; each test restores light mode.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._theme_file = Path(self._tmp.name) / "theme.json"
        patcher = mock.patch.object(live_theme, "_THEME_FILE", self._theme_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        live_theme.theme_manager.set_mode("light", notify=False)
        live_theme.apply_to_app(self._app)

    def tearDown(self):
        try:
            live_theme.theme_manager.set_mode("light", notify=False)
            live_theme.apply_to_app(self._app)
        except Exception:
            pass

    # ── centralized colours ──────────────────────────────────────
    def test_01_no_hardcoded_black_background_in_app_stylesheet(self):
        for mode in ("light", "dark"):
            live_theme.theme_manager.set_mode(mode, notify=False)
            ss = live_theme.stylesheet().lower()
            # The only legitimate `#ffffff` text is pressed-button white on a
            # saturated accent fill and the light-yellow tooltip note.
            # There must be no accidental `background: black` / `rgb(0,0,0)`.
            self.assertNotIn("background: black", ss)
            self.assertNotIn("background-color: black", ss)
            self.assertNotIn("rgb(0,0,0)", ss)
            self.assertNotIn("rgb(0, 0, 0)", ss)

    def test_02_stylesheet_covers_popups_frames_and_viewports(self):
        live_theme.theme_manager.set_mode("light", notify=False)
        ss = live_theme.stylesheet()
        for selector in (
            "QFrame", "QScrollArea", "QAbstractScrollArea",
            "QCalendarWidget", "QComboBox QAbstractItemView",
            "QAbstractItemView", "QGroupBox", "QGroupBox::title",
            "QTableCornerButton::section", "QHeaderView::section:vertical",
            "QCheckBox::indicator", "QComboBox QLineEdit",
            "QTabWidget::pane", "QSplitter",
        ):
            self.assertIn(selector, ss, f"app stylesheet must cover {selector}")

    def test_03_groupbox_is_opaque_in_app_stylesheet(self):
        for mode in ("light", "dark"):
            live_theme.theme_manager.set_mode(mode, notify=False)
            p = live_theme.palette()
            ss = live_theme.stylesheet()
            self.assertIn("QGroupBox {", ss)
            self.assertIn(f"background-color: {p['bg']}", ss)

    def test_04_apply_palette_follows_mode(self):
        live_theme.theme_manager.set_mode("light", notify=False)
        live_theme.apply_palette(self._app)
        pal = self._app.palette()
        self.assertEqual(pal.color(QPalette.Window).name(), "#ffffff")
        self.assertEqual(pal.color(QPalette.Base).name(), "#ffffff")
        self.assertEqual(pal.color(QPalette.Text).name(), "#000000")
        live_theme.theme_manager.set_mode("dark", notify=False)
        live_theme.apply_palette(self._app)
        pal = self._app.palette()
        self.assertEqual(pal.color(QPalette.Window).name(), "#000000")
        self.assertEqual(pal.color(QPalette.Base).name(), "#000000")
        self.assertEqual(pal.color(QPalette.Text).name(), "#ffffff")

    # ── Counter Sale in-place refresh ────────────────────────────
    def test_05_counter_sale_refresh_removes_stale_black_in_day_mode(self):
        import screens.counter_sale as cs
        live_theme.theme_manager.set_mode("dark", notify=False)
        live_theme.apply_to_app(self._app)
        importlib.reload(cs)
        page = cs.CounterSalePage()
        page.resize(1366, 760)
        page.show()
        self._app.processEvents()
        try:
            bill_tables = [
                t for t in page.findChildren(QTableWidget) if t.columnCount() == 11
            ]
            self.assertTrue(bill_tables, "Bill Items table missing")
            for t in bill_tables:
                self.assertIn("#000000", t.styleSheet().lower())
            # Switch to Day WITHOUT rebuilding (the reported bug scenario).
            live_theme.theme_manager.set_mode("light", notify=False)
            live_theme.apply_to_app(self._app)
            page.refresh_theme()
            self._app.processEvents()
            for t in page.findChildren(QTableWidget):
                ss = t.styleSheet().lower()
                self.assertNotIn("background-color: #000000", ss,
                                 "Day Mode table must not keep a black background")
                self.assertNotIn("background-color:#000000", ss)
            groups = [g for g in page.findChildren(QGroupBox) if g.title() == "Bill Items"]
            self.assertTrue(groups, "Bill Items group missing")
            for g in groups:
                self.assertNotIn("background-color: #000000", g.styleSheet().lower())
                self.assertIn("#ffffff", g.styleSheet().lower())
        finally:
            page.hide()
            page.deleteLater()
            self._app.processEvents()

    def test_06_counter_sale_refresh_preserves_draft_and_history(self):
        import screens.counter_sale as cs
        live_theme.theme_manager.set_mode("light", notify=False)
        live_theme.apply_to_app(self._app)
        importlib.reload(cs)
        page = cs.CounterSalePage()
        page.resize(1366, 760)
        page.show()
        self._app.processEvents()
        try:
            hist_rows = page._hist_table.rowCount()
            # Add a draft row directly (no DB write).
            panel = page._sale_panel
            panel._item_rows.append(cs._BillItemRow(
                item_id=1, item_name="Test Item", stock_batch_id=1,
                pack_size="10", location="A", batch_no="B1", expiry="12/27",
                mrp=10.0, sale_qty=2.0, discount_amount=0.0, amount=20.0))
            panel._refresh_table()
            draft_rows = panel._table.rowCount()
            self.assertGreaterEqual(draft_rows, 1)
            live_theme.theme_manager.set_mode("dark", notify=False)
            live_theme.apply_to_app(self._app)
            page.refresh_theme()
            self._app.processEvents()
            live_theme.theme_manager.set_mode("light", notify=False)
            live_theme.apply_to_app(self._app)
            page.refresh_theme()
            self._app.processEvents()
            self.assertEqual(page._hist_table.rowCount(), hist_rows,
                             "history must survive theme refresh")
            self.assertEqual(panel._table.rowCount(), draft_rows,
                             "bill draft must survive theme refresh")
        finally:
            page.hide()
            page.deleteLater()
            self._app.processEvents()

    def test_07_completer_popup_follows_theme(self):
        import screens.counter_sale as cs
        live_theme.theme_manager.set_mode("dark", notify=False)
        live_theme.apply_to_app(self._app)
        importlib.reload(cs)
        page = cs.CounterSalePage()
        page.resize(1366, 760)
        page.show()
        self._app.processEvents()
        try:
            combo = page._sale_panel._entry_bar.item_combo
            popup = combo.completer().popup()
            self.assertIn("#000000", popup.styleSheet().lower())
            live_theme.theme_manager.set_mode("light", notify=False)
            live_theme.apply_to_app(self._app)
            page.refresh_theme()
            self._app.processEvents()
            pss = popup.styleSheet().lower()
            self.assertNotIn("background-color: #000000", pss)
            self.assertIn("#ffffff", pss)
        finally:
            page.hide()
            page.deleteLater()
            self._app.processEvents()

    # ── generic screens ──────────────────────────────────────────
    def test_08_generic_refresh_fixes_groupbox_and_table(self):
        from ui import components as comp
        import screens.purchase_invoice as pi
        live_theme.theme_manager.set_mode("dark", notify=False)
        live_theme.apply_to_app(self._app)
        importlib.reload(pi)
        page = pi.PurchaseInvoicePage()
        page.resize(1366, 760)
        page.show()
        self._app.processEvents()
        try:
            live_theme.theme_manager.set_mode("light", notify=False)
            live_theme.apply_to_app(self._app)
            n = comp.refresh_generic_screen(page)
            self._app.processEvents()
            self.assertGreater(n, 0, "generic refresh must update widgets")
            for t in page.findChildren(QTableWidget):
                ss = t.styleSheet().lower()
                if "qtablewidget" in ss:
                    self.assertNotIn("background-color: #000000", ss)
            for g in page.findChildren(QGroupBox):
                ss = g.styleSheet().lower()
                if "qgroupbox" in ss:
                    self.assertNotIn("background-color: #000000", ss)
        finally:
            page.hide()
            page.deleteLater()
            self._app.processEvents()

    def test_09_primary_button_text_stays_white(self):
        from ui import components as comp
        import screens.purchase_invoice as pi
        live_theme.theme_manager.set_mode("dark", notify=False)
        live_theme.apply_to_app(self._app)
        importlib.reload(pi)
        page = pi.PurchaseInvoicePage()
        page.resize(1366, 760)
        page.show()
        self._app.processEvents()
        try:
            live_theme.theme_manager.set_mode("light", notify=False)
            live_theme.apply_to_app(self._app)
            comp.refresh_generic_screen(page)
            self._app.processEvents()
            primaries = [b for b in page.findChildren(type(page.findChildren(
                __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)[0]))
                if "new purchase" in b.text().lower() or "save" in b.text().lower()]
            for b in primaries[:2]:
                ss = b.styleSheet().lower()
                if "qpushbutton" in ss and ("#2f6fb0" in ss or "#2e7d32" in ss):
                    self.assertIn("color: white", ss,
                                  "primary white-on-accent text must be preserved")
        finally:
            page.hide()
            page.deleteLater()
            self._app.processEvents()

    def test_10_repeated_switches_are_stable(self):
        import screens.counter_sale as cs
        live_theme.theme_manager.set_mode("light", notify=False)
        live_theme.apply_to_app(self._app)
        importlib.reload(cs)
        page = cs.CounterSalePage()
        page.resize(1366, 760)
        page.show()
        self._app.processEvents()
        try:
            for _ in range(3):
                live_theme.theme_manager.set_mode("dark", notify=False)
                live_theme.apply_to_app(self._app)
                page.refresh_theme()
                self._app.processEvents()
                live_theme.theme_manager.set_mode("light", notify=False)
                live_theme.apply_to_app(self._app)
                page.refresh_theme()
                self._app.processEvents()
            for t in page.findChildren(QTableWidget):
                self.assertNotIn("background-color: #000000",
                                 t.styleSheet().lower())
        finally:
            page.hide()
            page.deleteLater()
            self._app.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
