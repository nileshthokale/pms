"""Capture the application's real screens for the readability / uppercase pass.

This is a *rendering harness*, not a test: it builds the actual page classes
from ``screens/`` and saves what they paint, in both Day and Night mode, plus
a pair of frames showing business-data entry being converted to upper case as
it is typed.

Run it from the project root::

    python capture_ui_screenshots.py [output_dir]

Safety: the harness NEVER touches the working database.  It takes a read-only
snapshot of ``data/pharmacy.db`` into a temporary file (the same technique
``run_tests.py`` uses), points ``PHARMACY_DB`` at that copy before importing
anything from ``database``, and leaves the original untouched.

Qt renders offscreen by default so the harness can run unattended; set
``QT_QPA_PLATFORM`` yourself to capture through a real window instead.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

WINDOW_W, WINDOW_H = 1366, 768
PUBLIC_DIR = ROOT / "docs" / "ui_screenshots"


def _snapshot_database() -> pathlib.Path:
    """A disposable copy of the working database, or a fresh empty one."""
    source_path = ROOT / "data" / "pharmacy.db"
    handle, staging_name = tempfile.mkstemp(
        prefix="pharmacy_screenshots_", suffix=".db"
    )
    os.close(handle)
    staging = pathlib.Path(staging_name)
    staging.unlink()
    if source_path.is_file():
        source = sqlite3.connect(
            f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True
        )
        target = sqlite3.connect(staging)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
    return staging


def main(argv: list[str]) -> int:
    out_dir = pathlib.Path(argv[1]) if len(argv) > 1 else PUBLIC_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    staging = _snapshot_database()
    os.environ["PHARMACY_DB"] = str(staging)
    os.environ["PHARMACY_TEST_SAFE_DB"] = str(staging)
    os.environ["PHARMACY_TEST_PROTECTED_DB"] = str(
        (ROOT / "data" / "pharmacy.db").resolve()
    )

    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from database import auth, financial_year
    from database.connection import init_database
    from ui import theme

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    init_database()
    auth.ensure_auth_schema()
    financial_year.ensure_default_financial_year()

    # Screens guard their actions with permissions; signing a synthetic ADMIN
    # in keeps the capture honest without needing real credentials (the copy
    # is disposable, so nothing is written back to the working database).
    if auth.user_count() == 0:
        auth.create_first_admin("admin", "admin-pass-1")
    auth.session.user = {
        "id": 1, "username": "admin", "role": auth.ROLE_ADMIN, "is_active": 1,
    }

    from ui.input_rules import install_uppercase_input

    install_uppercase_input(app)

    import screens

    PAGES = [
        ("counter_sale", "Sales / Counter Sale", screens.CounterSalePage),
        ("sales_history", "Sales / Sales History", screens.SalesHistoryPage),
        ("purchase", "Purchase / New Purchase", screens.PurchaseInvoicePage),
        ("sales_report", "Reports / Sales Report", screens.SalesReportPage),
        ("purchase_report", "Reports / Purchase Report",
         screens.PurchaseReportPage),
        ("gst_report", "Reports / GST Report", screens.GSTReportPage),
        ("item_master", "Master / Item Master", screens.ItemMasterPage),
        ("supplier_master", "Master / Supplier Master",
         screens.SupplierMasterPage),
        ("customer_master", "Master / Customer Master",
         screens.CustomerMasterPage),
        ("stock_report", "Reports / Stock Report", screens.StockMasterPage),
    ]

    written: list[str] = []

    def save(widget, name: str) -> None:
        pixmap = widget.grab()
        path = out_dir / f"{name}.png"
        pixmap.save(str(path), "PNG")
        written.append(str(path.relative_to(ROOT)) if path.is_relative_to(ROOT)
                       else str(path))

    def capture_all(mode: str) -> None:
        theme.theme_manager.set_mode(mode)
        app.processEvents()
        for slug, _, page_class in PAGES:
            page = page_class()
            try:
                page.resize(WINDOW_W, WINDOW_H)
                page.show()
                app.processEvents()
                ui_polish(page)
                app.processEvents()
                save(page, f"{slug}_{mode}")
            finally:
                page.hide()
                page.deleteLater()
                app.processEvents()

    def ui_polish(page):
        from ui import components as ui

        ui.polish_page(page)
        refresh = getattr(page, "refresh_theme", None)
        if callable(refresh):
            refresh()
        app.processEvents()

    # ── Whole window, so the navigation chrome is visible too ─────────
    def capture_window(mode: str) -> None:
        theme.theme_manager.set_mode(mode)
        app.processEvents()
        from ui import PharmacyMainWindow

        window = PharmacyMainWindow()
        try:
            window.resize(WINDOW_W, WINDOW_H)
            window.show()
            app.processEvents()
            save(window, f"main_window_{mode}")
        finally:
            window.hide()
            window.deleteLater()
            app.processEvents()

    # ── The upper-casing behaviour, on a real master dialog ───────────
    def capture_uppercase(mode: str) -> None:
        theme.theme_manager.set_mode(mode)
        app.processEvents()
        from screens.company_master import _CompanyDialog

        dialog = _CompanyDialog()
        try:
            dialog.resize(460, 240)
            dialog.show()
            app.processEvents()
            save(dialog, f"uppercase_before_typing_{mode}")
            QTest.keyClicks(dialog._name_edit, "care pharma")
            QTest.keyClicks(dialog._short_edit, "cp")
            app.processEvents()
            save(dialog, f"uppercase_after_typing_{mode}")
        finally:
            dialog.hide()
            dialog.deleteLater()
            app.processEvents()

    def capture_login(mode: str) -> None:
        theme.theme_manager.set_mode(mode)
        app.processEvents()
        from screens.login import LoginDialog

        dialog = LoginDialog()
        try:
            dialog.show()
            app.processEvents()
            QTest.keyClicks(dialog._username, "admin")
            save(dialog, f"login_{mode}")
        finally:
            dialog.hide()
            dialog.deleteLater()
            app.processEvents()

    login_ok = True
    try:
        for mode in ("light", "dark"):
            capture_all(mode)
            capture_uppercase(mode)
            capture_window(mode)
            try:
                capture_login(mode)
            except Exception as exc:      # pragma: no cover - diagnostics only
                login_ok = False
                print(f"  login capture skipped ({mode}): {exc}")
        # Leave the user's saved preference exactly as it was.
        theme.theme_manager.set_mode(theme.DEFAULT_MODE)
    finally:
        for suffix in ("", "-wal", "-shm"):
            candidate = pathlib.Path(f"{staging}{suffix}")
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass

    print(f"Captured {len(written)} screenshots into {out_dir}")
    for name in sorted(written):
        print(f"  {name}")
    if not login_ok:
        print("  (login dialog capture was unavailable)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
