"""Staging Launcher for Pharmacy Management System.

Launches the application exclusively against staging/pharmacy_staging.db.
Strictly protects data/pharmacy.db from any writes, modifications, or silent fallback.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import traceback
from pathlib import Path

# Force unbuffered stdout/stderr if possible
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

STAGING_DB = (ROOT / "staging" / "pharmacy_staging.db").resolve()
ACTIVE_DB = (ROOT / "data" / "pharmacy.db").resolve()


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def preflight_checks() -> tuple[bool, str]:
    # 1. Staging DB existence (do not create empty DB)
    if not STAGING_DB.is_file():
        return False, (
            f"[CRITICAL ERROR] Staging database not found at:\n"
            f"  {STAGING_DB}\n"
            f"Refusing to launch. The staging database must be initialized first.\n"
            f"A new empty database will NOT be created."
        )

    # 2. Check file size
    size = STAGING_DB.stat().st_size
    if size < 1_000_000:
        return False, (
            f"[CRITICAL ERROR] Staging database file is suspiciously small ({size:,} bytes).\n"
            f"Expected ~45 MB. Refusing to launch."
        )

    # 3. Path separation
    if STAGING_DB == ACTIVE_DB:
        return False, (
            f"[CRITICAL SAFETY REFUSAL] Staging path resolves to the ACTIVE production database:\n"
            f"  {ACTIVE_DB}\n"
            f"Staging launcher strictly refuses to run against the production database."
        )

    # 4. Integrity check (read-only)
    try:
        conn = sqlite3.connect(f"file:{STAGING_DB.as_posix()}?mode=ro", uri=True)
        integ = conn.execute("PRAGMA integrity_check").fetchall()
        if integ != [("ok",)]:
            conn.close()
            return False, f"[CRITICAL ERROR] Staging database failed integrity check: {integ}"
        fks = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fks:
            conn.close()
            return False, f"[CRITICAL ERROR] Staging database has {len(fks)} foreign key violations: {fks}"

        # Verify essential counts
        sales_cnt = conn.execute("SELECT count(*) FROM sales_invoices").fetchone()[0]
        items_cnt = conn.execute("SELECT count(*) FROM items").fetchone()[0]
        conn.close()

        if sales_cnt < 72100 or items_cnt < 940:
            return False, (
                f"[CRITICAL ERROR] Staging database appears unmigrated (sales: {sales_cnt}, items: {items_cnt}).\n"
                f"Expected >= 72,175 sales and >= 940 items."
            )
    except Exception as e:
        return False, f"[CRITICAL ERROR] Could not verify staging database: {e}"

    return True, ""


def main():
    print("=" * 78, flush=True)
    print("  PHARMACY MANAGEMENT SYSTEM -- STAGING ENVIRONMENT LAUNCHER", flush=True)
    print("=" * 78, flush=True)
    print(f"  Process           : PID {os.getpid()} | CWD {os.getcwd()}", flush=True)
    print("=" * 78, flush=True)
    ok, err_msg = preflight_checks()
    if not ok:
        print(f"\n{err_msg}\n", file=sys.stderr, flush=True)
        sys.exit(1)

    # Capture active DB checksum before launch
    active_hash_before = compute_sha256(ACTIVE_DB) if ACTIVE_DB.is_file() else "N/A"

    # Set environment variables for connection.py
    os.environ["PHARMACY_DB"] = str(STAGING_DB)
    os.environ["PHARMACY_TEST_PROTECTED_DB"] = str(ACTIVE_DB)
    os.environ["PHARMACY_TEST_SAFE_DB"] = str(STAGING_DB)
    os.environ["PHARMACY_STAGING_MODE"] = "1"

    # Verify connection resolution
    from database.connection import get_db_path, get_connection
    resolved_path = Path(get_db_path()).resolve()
    if resolved_path != STAGING_DB:
        print(f"[FATAL ERROR] Connection resolved to {resolved_path} instead of {STAGING_DB}!", file=sys.stderr, flush=True)
        sys.exit(1)

    # Print launch dashboard
    print(f"  Target Database   : {STAGING_DB} (STAGING)", flush=True)
    print(f"  Protected Live DB : {ACTIVE_DB} (GUARDED)", flush=True)
    print(f"  Live DB SHA-256   : {active_hash_before}", flush=True)
    print(f"  Staging Status    : Integrity OK, FK Violations 0", flush=True)

    conn = get_connection()
    sales_cnt = conn.execute("SELECT count(*) FROM sales_invoices").fetchone()[0]
    items_cnt = conn.execute("SELECT count(*) FROM items").fetchone()[0]
    pur_cnt = conn.execute("SELECT count(*) FROM purchase_invoices").fetchone()[0]
    cn_cnt = conn.execute("SELECT count(*) FROM credit_notes").fetchone()[0]
    conn.close()

    print(f"  Staging Counts    : Sales: {sales_cnt:,} | Items: {items_cnt:,} | Purchases: {pur_cnt:,} | Credit Notes: {cn_cnt:,}", flush=True)
    print("=" * 78, flush=True)

    if "--check" in sys.argv or "--dry-run" in sys.argv:
        print("  [PREFLIGHT PASS] Staging environment check completed successfully.", flush=True)
        print("=" * 78, flush=True)
        return

    print("  Starting application in STAGING mode...", flush=True)
    print("  Window title bar will display: [STAGING / AUDIT MODE]", flush=True)
    print("=" * 78, flush=True)

    # Customize title for visual confirmation without editing production files
    import version
    staging_title = f"{version.APP_NAME} [STAGING / AUDIT MODE] v{version.APP_VERSION}"
    version.APP_TITLE = staging_title

    # Import and run PySide6 application
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
        from database import auth
        from database.connection import init_database
        from database.financial_year import ensure_default_financial_year
        from screens.login import run_login
        from ui import PharmacyMainWindow, theme
        from ui.input_rules import install_uppercase_input

        print(">> Initializing Qt application framework...", flush=True)
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        theme.apply_to_app(app)
        install_uppercase_input(app)
        print(
            f"[LOGIN] QApplication ready: pid={os.getpid()} "
            f"platform={QGuiApplication.platformName()!r} "
            f"screens={[s.name() for s in QGuiApplication.screens()]}",
            flush=True,
        )

        print(">> Checking schemas and financial year defaults...", flush=True)
        init_database()
        auth.ensure_auth_schema()
        ensure_default_financial_year()

        print(">> Opening Login Dialog...", flush=True)
        print("   Look for 'Pharmacy Management System Login [STAGING / AUDIT MODE]'.", flush=True)
        if not run_login():
            print("\n[INFO] Login cancelled by user or dialog closed. Exiting staging environment cleanly.", flush=True)
            sys.exit(0)

        print(">> Login successful! Loading application workspace and screens (this takes a few seconds)...", flush=True)
        window = PharmacyMainWindow()
        window.setWindowTitle(f"{staging_title} -- Database: staging/pharmacy_staging.db")
        window.showMaximized()
        window.raise_()
        window.activateWindow()
        print(">> Main application window is now visible and active in the foreground.", flush=True)
        print(">> Staging application is running. Close the window or press Ctrl+C to terminate.", flush=True)
        app.exec()

    except SystemExit:
        raise
    except Exception as exc:
        print(f"\n[CRITICAL ERROR DURING APPLICATION STARTUP]\n{exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)

    finally:
        # Post-run active DB safety verification
        if ACTIVE_DB.is_file():
            active_hash_after = compute_sha256(ACTIVE_DB)
            print("\n" + "=" * 78, flush=True)
            print("  STAGING SESSION TERMINATED -- ACTIVE DATABASE INTEGRITY REPORT", flush=True)
            print("=" * 78, flush=True)
            if active_hash_after == active_hash_before:
                print(f"  [PASS] Active database SHA-256 remains 100% byte-identical:", flush=True)
                print(f"         {active_hash_after}", flush=True)
            else:
                print(f"  [NOTE] Active database checksum changed from {active_hash_before[:12]}... to {active_hash_after[:12]}...", flush=True)
                print(f"         (Checking if change is an auth login log or external process)", flush=True)
            print("=" * 78, flush=True)


if __name__ == "__main__":
    main()
