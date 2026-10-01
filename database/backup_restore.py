"""Database Backup & Restore service — Phase 5F.

Scope: the NEW application's SQLite database ONLY (the file returned by
`database.connection.get_db_path()` — production: data/pharmacy.db).
The old Pharma-WINNER/MySQL database is never accessed, modified,
migrated or connected to by this module.

Safety model:
  - Backups are created with SQLite's online backup API
    (`sqlite3.Connection.backup`), which copies a consistent snapshot
    (schema + all data, including indexes and constraints) even while
    the database is being used — never a blind file copy.
  - Validation opens the backup READ-ONLY (`mode=ro` URI) and never
    writes to it.
  - Restore requires a validated backup, automatically creates a
    timestamped safety backup of the CURRENT database first, verifies
    the restored database afterwards, and recovers the original from
    the safety backup if anything fails.
  - The selected backup file is never deleted or modified.

SHA-256 checksums let the UI/user verify a backup file later (e.g.
after copying it to another drive).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from database.connection import get_db_path

# Every table created by database.connection.init_database().
# A backup missing any of these is not a valid pharmacy database.
EXPECTED_TABLES = [
    "account_groups",
    "account_ledgers",
    "categories",
    "companies",
    "credit_note_items",
    "credit_notes",
    "customer_receipts",
    "customers",
    "debit_note_items",
    "debit_notes",
    "doctors",
    "drugs",
    "financial_years",
    "item_ingredients",
    "items",
    "journal_entries",
    "journal_entry_items",
    "ledger_transactions",
    "purchase_invoice_items",
    "purchase_invoices",
    "sales_invoice_items",
    "sales_invoices",
    "stock_batches",
    "supplier_payments",
    "suppliers",
    "units",
]

BACKUP_NAME_FORMAT = "pharmacy_backup_%Y%m%d_%H%M%S.db"
SAFETY_NAME_FORMAT = "pharmacy_pre_restore_%Y%m%d_%H%M%S.db"
LAST_BACKUP_FILE = "last_backup.json"


class BackupError(Exception):
    """Raised when a backup/restore operation cannot complete safely."""


# ── helpers ──────────────────────────────────────────────────────────

def compute_sha256(path: str) -> str:
    """SHA-256 hex digest of a file (streamed; works for large files)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: str, expected_sha256: str) -> bool:
    """True when the file's current SHA-256 matches the expected value."""
    try:
        return compute_sha256(path) == expected_sha256
    except OSError:
        return False


def _timestamped_name(fmt: str) -> str:
    return datetime.now().strftime(fmt)


def _resolve_destination(destination: str) -> str:
    """Destination may be a folder (auto timestamped name) or a file path."""
    if os.path.isdir(destination) or not destination.lower().endswith(".db"):
        os.makedirs(destination, exist_ok=True)
        return os.path.join(destination, _timestamped_name(BACKUP_NAME_FORMAT))
    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    return destination


def _open_readonly(path: str) -> sqlite3.Connection:
    """Open a SQLite database read-only; never creates or modifies files."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _copy_db(src_path: str, dest_path: str) -> None:
    """Replace dest_path's content with src_path's content (SQLite API).

    Uses the online backup API — a consistent snapshot, not a file copy.
    Kept as a module-level function so failure injection in tests can
    simulate a failed restore deterministically.
    """
    src = sqlite3.connect(src_path)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
            dest.commit()
        finally:
            dest.close()
    finally:
        src.close()


def _last_backup_file() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(get_db_path())),
                        LAST_BACKUP_FILE)


def get_last_backup_info() -> dict | None:
    """Last recorded user backup (path, sha256, size, created_at), or None."""
    try:
        with open(_last_backup_file(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _record_last_backup(info: dict) -> None:
    try:
        with open(_last_backup_file(), "w", encoding="utf-8") as fh:
            json.dump(info, fh)
    except OSError:
        # Recording the info is best-effort; the backup itself succeeded.
        pass


# ── public API ───────────────────────────────────────────────────────

def get_database_info() -> dict:
    """Information about the CURRENT application database."""
    path = get_db_path()
    exists = os.path.isfile(path)
    info = {
        "path": path,
        "exists": exists,
        "size_bytes": 0,
        "table_count": 0,
    }
    if exists:
        info["size_bytes"] = os.path.getsize(path)
        try:
            conn = _open_readonly(path)
            try:
                info["table_count"] = len(
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                )
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            info["table_count"] = 0
    return info


def create_backup(destination: str, record_last: bool = True) -> dict:
    """Create a consistent backup of the current database.

    destination: folder path (auto `pharmacy_backup_YYYYMMDD_HHMMSS.db`)
    or an explicit .db file path.

    Returns {"path", "sha256", "size_bytes", "created_at", "table_count"}.
    Raises BackupError when the database file does not exist or the
    backup cannot be written. The source database is never modified.
    """
    db_path = get_db_path()
    if not os.path.isfile(db_path):
        raise BackupError(f"Database file not found: {db_path}")

    dest_path = _resolve_destination(destination)

    try:
        src = sqlite3.connect(db_path)
        try:
            dest = sqlite3.connect(dest_path)
            try:
                src.backup(dest)   # consistent snapshot via SQLite
                dest.commit()
            finally:
                dest.close()
        finally:
            src.close()
    except (sqlite3.Error, OSError) as e:
        raise BackupError(f"Backup failed: {e}")

    info = {
        "path": dest_path,
        "sha256": compute_sha256(dest_path),
        "size_bytes": os.path.getsize(dest_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    validation = validate_backup(dest_path)
    if not validation["valid"]:
        raise BackupError(
            f"Backup created but failed validation: {validation['reason']}"
        )
    info["table_count"] = len(validation["tables"])

    if record_last:
        _record_last_backup(info)
    return info


def validate_backup(backup_path: str) -> dict:
    """Validate a backup file WITHOUT modifying it.

    Returns:
        {"valid": bool, "reason": str ("" when valid), "path": str,
         "size_bytes": int, "sha256": str or None,
         "integrity": str, "tables": [...], "missing_tables": [...]}
    """
    result = {
        "valid": False,
        "reason": "",
        "path": backup_path,
        "size_bytes": 0,
        "sha256": None,
        "integrity": "",
        "tables": [],
        "missing_tables": [],
    }

    if not backup_path or not os.path.isfile(backup_path):
        result["reason"] = "File not found."
        return result

    result["size_bytes"] = os.path.getsize(backup_path)
    if result["size_bytes"] == 0:
        result["reason"] = "File is empty."
        return result

    result["sha256"] = compute_sha256(backup_path)

    try:
        conn = _open_readonly(backup_path)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            result["integrity"] = integrity
            if integrity != "ok":
                result["reason"] = f"Integrity check failed: {integrity}"
                return result

            tables = [
                r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            result["tables"] = tables
            result["missing_tables"] = [
                t for t in EXPECTED_TABLES if t not in tables
            ]
            if result["missing_tables"]:
                result["reason"] = (
                    "Not a pharmacy database — missing tables: "
                    + ", ".join(result["missing_tables"])
                )
                return result
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        result["reason"] = f"Not a valid SQLite database ({e})."
        return result

    result["valid"] = True
    return result


def restore_backup(backup_path: str) -> dict:
    """Restore the application database from a validated backup.

    Steps (all reversible on failure):
        1. Validate the backup — refuse invalid files.
        2. Create an automatic safety backup of the CURRENT database
           (timestamped pharmacy_pre_restore_*.db next to it).
        3. Replace the current database content via SQLite's backup API.
        4. Verify the restored database; on any failure recover the
           original from the safety backup.

    The selected backup file is never deleted or modified.

    Returns {"restored": True, "safety_backup": <path>, "source": <path>,
             "table_count": int}.
    Raises BackupError (and recovers the original) on failure.
    """
    validation = validate_backup(backup_path)
    if not validation["valid"]:
        raise BackupError(
            f"Restore refused — invalid backup: {validation['reason']}"
        )

    db_path = get_db_path()
    if not os.path.isfile(db_path):
        raise BackupError(f"Current database not found: {db_path}")

    # 1. Automatic safety backup of the CURRENT database
    try:
        safety = create_backup(
            os.path.dirname(os.path.abspath(db_path)),
            record_last=False,
        )
    except BackupError as e:
        raise BackupError(
            f"Restore aborted — could not create a safety backup of the "
            f"current database: {e}"
        )

    # 2. Replace the current database with the backup content
    try:
        _copy_db(backup_path, db_path)
    except Exception as e:
        recovery_error = _try_recover(safety["path"], db_path)
        if recovery_error:
            raise BackupError(
                f"Restore failed ({e}) AND recovery failed "
                f"({recovery_error}). The pre-restore safety backup is at "
                f"{safety['path']} — restore it manually."
            )
        raise BackupError(
            f"Restore failed ({e}). The original database was recovered "
            f"from the safety backup: {safety['path']}"
        )

    # 3. Verify the restored database
    check = validate_backup(db_path)
    if not check["valid"]:
        recovery_error = _try_recover(safety["path"], db_path)
        if recovery_error:
            raise BackupError(
                f"Restored database failed verification ({check['reason']}) "
                f"AND recovery failed ({recovery_error}). The pre-restore "
                f"safety backup is at {safety['path']} — restore it manually."
            )
        raise BackupError(
            f"Restored database failed verification "
            f"({check['reason']}). The original database was recovered "
            f"from the safety backup: {safety['path']}"
        )

    return {
        "restored": True,
        "source": backup_path,
        "safety_backup": safety["path"],
        "table_count": len(check["tables"]),
    }


def _try_recover(safety_path: str, db_path: str) -> str:
    """Best-effort recovery of the original database. Returns "" on success."""
    try:
        _copy_db(safety_path, db_path)
        return ""
    except Exception as e:  # pragma: no cover - catastrophic path
        return str(e)
