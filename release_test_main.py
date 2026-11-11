"""Entry point for the isolated Pharmacy Management System TEST release.

This build behaves like the normal application (no STAGING / AUDIT MODE
branding) but is deliberately separated from every normal database:

* Runtime database:
      %LOCALAPPDATA%\\PharmacyManagementSystem-Test\\pharmacy.db
* Source snapshot bundled read-only inside the EXE:
      <application>\\_internal\\seed\\pharmacy_staging.db
* First launch: the snapshot is copied with SQLite's online-backup API into
  a temporary file, verified, and atomically renamed into place.
* Later launches: an existing test database is preserved byte-for-byte;
  it is never re-seeded or overwritten by an EXE update.The build refuses to fall back to ``data/pharmacy.db``,
``%LOCALAPPDATA%\\PharmacyManagementSystem\\pharmacy.db``, or to create a new
empty database.

``--self-check`` runs a non-GUI verification (seeding, integrity, counts,
isolation, a disposable audit row, persistence, and an offscreen UI smoke
test) and writes ``test_release_self_check.json`` beside the database.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

APP_DIR_NAME = "PharmacyManagementSystem-Test"
NORMAL_APP_DIR_NAME = "PharmacyManagementSystem"
DB_FILE_NAME = "pharmacy.db"
SEED_RELATIVE = Path("seed") / "pharmacy_staging.db"
MARKER_ACTION = "test_release_self_check"
EXPECTED_MIN_SALES = 72175
EXPECTED_MIN_ITEMS = 940
STATUS_FILE = "test_release_self_check.json"
LOG_FILE = "test_release.log"
TEST_BUILD_LABEL = "Test Build"


# ── paths ────────────────────────────────────────────────────────────


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_seed_path() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller --onedir: datas live under _internal/seed/.
        root = Path(getattr(sys, "_MEIPASS", _base_dir()))
        return root / SEED_RELATIVE
    # Development run of this entry point: use the project's staging file.
    return _base_dir() / "staging" / "pharmacy_staging.db"


def local_appdata_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base)


def normal_app_data_dir() -> Path:
    return local_appdata_dir() / NORMAL_APP_DIR_NAME


def test_app_data_dir() -> Path:
    override = os.environ.get("PHARMACY_TEST_DATA_DIR")
    if override:
        return Path(override)
    return local_appdata_dir() / APP_DIR_NAME


def test_db_path() -> Path:
    return test_app_data_dir() / DB_FILE_NAME


def production_db_path() -> Path:
    return _base_dir() / "data" / "pharmacy.db"


# ── helpers ──────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _log_path() -> Path:
    return test_app_data_dir() / LOG_FILE


def log(message: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [TEST-RELEASE] {message}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        _log_path().parent.mkdir(parents=True, exist_ok=True)
        with open(_log_path(), "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
    except OSError:
        pass


def _connect_read_only(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    if immutable:
        # The bundled snapshot never changes.  immutable=1 lets SQLite read
        # it even when the installation folder is read-only (Program Files)
        # and no -shm sidecar can be created.
        uri += "&immutable=1"
    return sqlite3.connect(uri, uri=True)


def inspect_database(path: Path, *, immutable: bool = False) -> dict:
    """Integrity, foreign keys and headline table counts (read-only)."""
    conn = _connect_read_only(path, immutable=immutable)
    try:
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = [
            "items",
            "suppliers",
            "customers",
            "doctors",
            "purchase_invoices",
            "purchase_invoice_items",
            "sales_invoices",
            "sales_invoice_items",
            "credit_notes",
            "stock_batches",
            "account_ledgers",
            "ledger_transactions",
            "app_users",
        ]
        counts = {}
        for table in tables:
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                counts[table] = None
        financial_years = conn.execute(
            "SELECT name FROM financial_years WHERE is_active = 1 ORDER BY name"
        ).fetchall()
        return {
            "integrity_check": integrity,
            "foreign_key_violations": len(foreign_keys),
            "counts": counts,
            "active_financial_years": [row[0] for row in financial_years],
        }
    finally:
        conn.close()


def _assert_healthy(info: dict, source: str) -> None:
    if info["integrity_check"] != ["ok"]:
        raise RuntimeError(f"{source} failed PRAGMA integrity_check: {info['integrity_check']}")
    if info["foreign_key_violations"]:
        raise RuntimeError(
            f"{source} has {info['foreign_key_violations']} foreign key violations"
        )
    counts = info["counts"]
    if (counts.get("sales_invoices") or 0) < EXPECTED_MIN_SALES:
        raise RuntimeError(
            f"{source} looks unmigrated: sales_invoices={counts.get('sales_invoices')}"
        )
    if (counts.get("items") or 0) < EXPECTED_MIN_ITEMS:
        raise RuntimeError(f"{source} looks unmigrated: items={counts.get('items')}")


def initialise_database(db_path: Path, seed_path: Path) -> str:
    """Create the isolated test database from the bundled snapshot once.

    Returns ``"seeded"`` or ``"preserved"``.  The copy is made with the
    SQLite online-backup API (consistent even if the source is in WAL
    mode), validated, then atomically renamed into place.
    """
    if db_path.is_file() and db_path.stat().st_size > 0:
        log(f"Existing test database preserved: {db_path}")
        return "preserved"

    if not seed_path.is_file():
        raise RuntimeError(
            f"Bundled staging snapshot not found at {seed_path}. "
            "Refusing to create an empty database."
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = db_path.with_name(f".{DB_FILE_NAME}.seed-{os.getpid()}.tmp")
    try:
        if temporary.exists():
            temporary.unlink()
        source = _connect_read_only(seed_path, immutable=True)
        try:
            destination = sqlite3.connect(str(temporary))
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
        finally:
            source.close()

        info = inspect_database(temporary, immutable=True)
        _assert_healthy(info, "Bundled staging snapshot")
        log(
            "Bundled snapshot verified: "
            f"sales={info['counts'].get('sales_invoices'):,}, "
            f"items={info['counts'].get('items'):,}, "
            f"purchases={info['counts'].get('purchase_invoices'):,}, "
            f"credit_notes={info['counts'].get('credit_notes'):,}"
        )

        if db_path.exists():
            # Another launch won the race; never overwrite it.
            temporary.unlink()
            log(f"Existing test database preserved (race): {db_path}")
            return "preserved"

        os.replace(temporary, db_path)
        log(f"Test database initialised from bundled snapshot: {db_path}")
        return "seeded"
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def configure_environment(db_path: Path, data_dir: Path) -> None:
    """Point every database consumer at the isolated test database."""
    os.environ["PHARMACY_DB"] = str(db_path)
    os.environ["PHARMACY_DATA_DIR"] = str(data_dir)
    os.environ["PHARMACY_TEST_RELEASE"] = "1"
    os.environ["PHARMACY_REQUIRE_EXISTING_DB"] = "1"
    # If PHARMACY_DB were ever lost, connection.get_db_path() maps the
    # normal per-user database onto this safe path instead of opening it.
    os.environ["PHARMACY_TEST_PROTECTED_DB"] = str(
        normal_app_data_dir() / DB_FILE_NAME
    )
    os.environ["PHARMACY_TEST_SAFE_DB"] = str(db_path)
    os.environ.pop("PHARMACY_STAGING_MODE", None)
    os.environ.pop("PHARMACY_DB_PATH", None)


def verify_resolution(expected: Path) -> None:
    from database.connection import get_db_path

    resolved = Path(get_db_path()).resolve()
    if resolved != expected.resolve():
        raise RuntimeError(
            f"Database resolution failed: expected {expected}, got {resolved}. "
            "Refusing to start the test release."
        )
    forbidden = {
        production_db_path().resolve(),
        (normal_app_data_dir() / DB_FILE_NAME).resolve(),
    }
    if resolved in forbidden:
        raise RuntimeError(
            f"Refusing to start: resolved database {resolved} is a normal database."
        )


def apply_test_branding() -> None:
    """Normal UI, but the version/About information names the test build."""
    import version

    version.APP_TITLE = f"{version.APP_NAME} v{version.APP_VERSION} ({TEST_BUILD_LABEL})"


# ── self-check ───────────────────────────────────────────────────────


def _marker_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM auth_audit_log WHERE action = ?",
            (MARKER_ACTION,),
        ).fetchone()[0]
    )


def _write_marker(db_path: Path) -> dict:
    """Write one disposable, non-business audit row into the test database."""
    conn = sqlite3.connect(str(db_path))
    try:
        before = _marker_count(conn)
        conn.execute(
            "INSERT INTO auth_audit_log (timestamp, username, action, success, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                "TEST-RELEASE",
                MARKER_ACTION,
                1,
                f"isolated test build self-check pid={os.getpid()}",
            ),
        )
        conn.commit()
        # Force the committed row into the main database file so the
        # before/after checksum comparison observes the isolated write.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after = _marker_count(conn)
    finally:
        conn.close()
    return {"before": before, "after": after}


def _packaged_smoke() -> dict:
    """Load the packaged UI modules and build every screen offscreen."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from database import auth
    from database.connection import get_db_path, init_database
    from database.financial_year import ensure_default_financial_year
    from screens.login import LoginDialog
    from ui import PharmacyMainWindow, theme
    from ui.input_rules import install_uppercase_input

    init_database()
    auth.ensure_auth_schema()
    ensure_default_financial_year()
    theme.apply_to_app(app)
    install_uppercase_input(app)

    dialog = LoginDialog()
    dialog.show()
    app.processEvents()
    dialog_geometry = dialog.geometry().getRect()
    dialog.hide()
    dialog.deleteLater()

    auth.session.user = {
        "id": 0,
        "username": "TEST-RELEASE",
        "role": auth.ROLE_ADMIN,
        "is_active": 1,
    }
    window = PharmacyMainWindow()
    window.show()
    app.processEvents()
    page_count = len(window._page_map)
    window_title = window.windowTitle()
    window.close()
    app.processEvents()

    return {
        "db_path_inside_process": get_db_path(),
        "login_dialog_built": True,
        "login_dialog_geometry": dialog_geometry,
        "main_window_built": True,
        "main_window_title": window_title,
        "pages_built": page_count,
        "platform": "offscreen",
    }


def run_self_check() -> int:
    data_dir = test_app_data_dir()
    db_path = test_db_path()
    seed_path = bundled_seed_path()
    status: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "test_data_dir": str(data_dir),
        "database_path": str(db_path),
        "seed_path": str(seed_path),
        "production_db_path": str(production_db_path()),
        "normal_app_db_path": str(normal_app_data_dir() / DB_FILE_NAME),
        "checks": {},
        "ok": False,
    }

    try:
        log("Self-check started")
        apply_test_branding()
        if not seed_path.is_file():
            raise RuntimeError(f"Bundled snapshot missing: {seed_path}")
        status["seed_sha256_before"] = sha256_file(seed_path)

        initialisation = initialise_database(db_path, seed_path)
        status["checks"]["database_initialisation"] = initialisation
        _assert_healthy(inspect_database(db_path), "Test database")

        status["database_info"] = inspect_database(db_path)
        status["database_sha256_before_marker"] = sha256_file(db_path)

        resolved = db_path.resolve()
        status["checks"]["isolated_from_production"] = resolved != production_db_path().resolve()
        status["checks"]["isolated_from_normal_app_data"] = (
            resolved != (normal_app_data_dir() / DB_FILE_NAME).resolve()
        )

        configure_environment(db_path, data_dir)
        verify_resolution(db_path)
        status["checks"]["runtime_db_resolution"] = True

        marker = _write_marker(db_path)
        status["checks"]["marker_transaction"] = marker
        status["database_sha256_after_marker"] = sha256_file(db_path)
        status["checks"]["marker_write_changed_test_db"] = (
            status["database_sha256_before_marker"]
            != status["database_sha256_after_marker"]
        )

        conn = sqlite3.connect(str(db_path))
        try:
            persisted = _marker_count(conn)
        finally:
            conn.close()
        status["checks"]["marker_persisted_after_reopen"] = persisted == marker["after"]
        status["marker_rows_persisted"] = persisted

        status["seed_sha256_after"] = sha256_file(seed_path)
        status["checks"]["seed_unchanged"] = (
            status["seed_sha256_before"] == status["seed_sha256_after"]
        )

        try:
            status["packaged_environment"] = _packaged_smoke()
            status["checks"]["packaged_ui_smoke"] = True
        except Exception as exc:  # UI smoke is reported, not fatal to data checks
            status["packaged_environment"] = {"error": repr(exc)}
            status["checks"]["packaged_ui_smoke"] = False

        status["ok"] = all(
            bool(status["checks"].get(key))
            for key in (
                "isolated_from_production",
                "isolated_from_normal_app_data",
                "runtime_db_resolution",
                "marker_transaction",
                "marker_write_changed_test_db",
                "marker_persisted_after_reopen",
                "seed_unchanged",
                "packaged_ui_smoke",
            )
        )
        log(f"Self-check completed: ok={status['ok']}")
        return 0 if status["ok"] else 1
    except Exception:
        status["error"] = traceback.format_exc()
        log(f"Self-check failed:\n{status['error']}")
        return 1
    finally:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            with open(data_dir / STATUS_FILE, "w", encoding="utf-8") as handle:
                json.dump(status, handle, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass


# ── normal application startup ───────────────────────────────────────


def run_application() -> int:
    data_dir = test_app_data_dir()
    db_path = test_db_path()
    seed_path = bundled_seed_path()

    log("Starting Pharmacy Management System (Test Build)")
    initialise_database(db_path, seed_path)
    configure_environment(db_path, data_dir)
    verify_resolution(db_path)
    apply_test_branding()
    log(f"Runtime database: {db_path}")

    try:
        from main import main as application_main

        application_main()
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:
        error = traceback.format_exc()
        log(f"Startup failure:\n{error}")
        try:
            (data_dir / "startup_error.log").write_text(error, encoding="utf-8")
        except OSError:
            pass
        raise


def main() -> int:
    if "--self-check" in sys.argv:
        return run_self_check()
    return run_application()


if __name__ == "__main__":
    sys.exit(main())
