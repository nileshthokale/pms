"""Real-rendering visual acceptance capture for the typography pass.

Renders the live application on the real Qt ``windows`` platform (not
offscreen) and writes a screenshot per page at each target desktop size, so
the rendered text can actually be looked at instead of inferred from
geometry.

Safety:
  * the production database is opened **read-only** and cloned with SQLite's
    backup API; every write goes to the throwaway clone,
  * ``PHARMACY_TEST_PROTECTED_DB`` / ``PHARMACY_TEST_SAFE_DB`` are set so a
    stray reference back to production is rewritten onto the clone anyway,
  * the clone is deleted at the end unless ``--keep`` is passed.

Usage:
    python tools_visual_acceptance.py [--out docs/typography_screenshots]
                                      [--sizes 1366x768,1920x1080]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

VISUAL_USER = "visualacceptance"
VISUAL_PASS = "visual-acceptance-1"

PAGES = [
    ("Sales", "New Bill", "counter_sale"),
    ("Purchase", "New Purchase", "purchase"),
    ("Master", "Item Master", "item_master"),
    ("Master", "Customer Master", "customer_master"),
    ("Reports", "Sales Report", "sales_report"),
    ("Account", "Trial Balance", "trial_balance"),
]


def clone_production_db() -> pathlib.Path:
    """Consistent read-only snapshot of the business database."""
    source_path = (ROOT / "data" / "pharmacy.db").resolve()
    if not source_path.exists():
        raise SystemExit(f"production database not found: {source_path}")
    fd, name = tempfile.mkstemp(prefix="pharmacy_visual_", suffix=".db")
    os.close(fd)
    dest = pathlib.Path(name)
    dest.unlink()
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return dest


def install_isolated_environment(clone: pathlib.Path) -> pathlib.Path:
    protected = (ROOT / "data" / "pharmacy.db").resolve()
    os.environ["PHARMACY_DB"] = str(clone)
    os.environ["PHARMACY_TEST_PROTECTED_DB"] = str(protected)
    os.environ["PHARMACY_TEST_SAFE_DB"] = str(clone)

    from database.connection import get_db_path

    resolved = pathlib.Path(get_db_path()).resolve()
    if os.path.normcase(str(resolved)) == os.path.normcase(str(protected)):
        raise SystemExit("refusing to run: resolved database is production")
    return resolved


def provision_admin() -> None:
    """Add a throwaway ADMIN to the clone so pages can be opened."""
    from database import auth
    from database.connection import get_connection

    auth.ensure_auth_schema()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM app_users WHERE username = ?", (VISUAL_USER,))
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO app_users"
            " (username, password_hash, role, is_active, created_at, updated_at)"
            " VALUES (?, ?, 'ADMIN', 1, ?, ?)",
            (VISUAL_USER, auth.hash_password(VISUAL_PASS), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    if not auth.session.login(VISUAL_USER, VISUAL_PASS):
        raise SystemExit("could not sign in as the visual-acceptance ADMIN")


def capture(out_dir: pathlib.Path, sizes: list[tuple[int, int]]) -> int:
    from PySide6.QtTest import QTest

    from database.connection import init_database
    from database import financial_year
    from ui import theme
    from PySide6.QtWidgets import QApplication

    init_database()
    financial_year.ensure_default_financial_year()
    provision_admin()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())

    from ui import PharmacyMainWindow

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    # ── login dialog (its own window, captured once per size) ─────────
    from screens.login import LoginDialog

    window = PharmacyMainWindow()
    window.resize(*sizes[0])
    window.show()
    QTest.qWait(400)

    for width, height in sizes:
        dialog = LoginDialog()
        dialog.show()
        QTest.qWait(250)
        dialog.grab().save(
            str(out_dir / f"typography_login_{width}x{height}.png"))
        dialog.close()
        written += 1

    # ── main pages ────────────────────────────────────────────────────
    for width, height in sizes:
        window.resize(width, height)
        QTest.qWait(300)
        for menu, action, slug in PAGES:
            window._on_menu_action(menu, action)
            QTest.qWait(500)
            app.processEvents()
            path = out_dir / f"typography_{slug}_{width}x{height}.png"
            if window.grab().save(str(path)):
                written += 1
                print(f"  captured {path.relative_to(ROOT)}")
            else:
                print(f"  FAILED to save {path}")

    window.close()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/typography_screenshots")
    parser.add_argument("--sizes", default="1366x768,1920x1080")
    parser.add_argument("--keep", action="store_true",
                        help="keep the cloned database for inspection")
    args = parser.parse_args()

    sizes = []
    for token in args.sizes.split(","):
        width, height = token.strip().lower().split("x")
        sizes.append((int(width), int(height)))

    clone = clone_production_db()
    resolved = install_isolated_environment(clone)
    print(f"isolated database: {resolved}")

    try:
        written = capture(ROOT / args.out, sizes)
    finally:
        for suffix in ("", "-wal", "-shm"):
            sidecar = pathlib.Path(f"{clone}{suffix}")
            if sidecar.exists():
                if args.keep:
                    print(f"kept clone: {sidecar}")
                else:
                    sidecar.unlink()

    print(f"\n{written} screenshot(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
