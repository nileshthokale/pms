"""Phase 1: Environment protection, database identification, baseline hashing, and fresh isolated staging creation.

This script:
1. Verifies that the application (main.py) is not running.
2. Dynamically resolves the active application database via database.connection.get_db_path().
3. Computes the T0 SHA-256 and byte size of the active database immediately before staging initialization.
4. Computes the SHA-256 and byte size of the source SQL dump (strictly read-only).
5. Creates a fresh isolated staging database at staging/pharmacy_staging.db using SQLite's online backup API.
6. Verifies PRAGMA integrity_check and PRAGMA foreign_key_check on the staging database.
7. Confirms the active database SHA-256 is unchanged (T1 == T0).
8. Records baseline metadata to migration_backups/phase1_stage_baseline.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database.connection as db_conn


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_app_closed() -> bool:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name LIKE '%python%'\" | Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=15)
        for line in (out.stdout or "").splitlines():
            if "main.py" in line:
                print(f"ERROR: Application process is running: {line.strip()}")
                return False
    except Exception as e:
        print(f"Warning: Could not check running processes ({e}), continuing.")
    return True


def main() -> int:
    print("=== Phase 1: Environment Protection & Baseline Identification ===")

    if not check_app_closed():
        print("CRITICAL BLOCKER: Close the application before taking the staging snapshot.")
        return 1

    active_db_path = Path(db_conn.get_db_path()).resolve()
    print(f"Active application database path: {active_db_path}")
    if not active_db_path.exists():
        print(f"ERROR: Active database not found at {active_db_path}")
        return 1

    active_size = active_db_path.stat().st_size
    t0_active_sha256 = compute_sha256(active_db_path)
    print(f"Active DB size: {active_size:,} bytes")
    print(f"Active DB T0 SHA-256: {t0_active_sha256}")

    source_dump_path = (ROOT / "PharmaWinner202610201418.sql").resolve()
    print(f"\nSource SQL dump path: {source_dump_path}")
    if not source_dump_path.exists():
        print(f"ERROR: Source dump not found at {source_dump_path}")
        return 1

    dump_size = source_dump_path.stat().st_size
    dump_sha256 = compute_sha256(source_dump_path)
    print(f"Source dump size: {dump_size:,} bytes")
    print(f"Source dump SHA-256: {dump_sha256}")

    # Isolated staging database path (strictly fresh staging/pharmacy_staging.db)
    staging_dir = ROOT / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_db_path = staging_dir / "pharmacy_staging.db"

    # Remove any existing staging file and WAL sidecars for a clean fresh backup
    for p in (staging_db_path, Path(f"{staging_db_path}-wal"), Path(f"{staging_db_path}-shm")):
        if p.exists():
            p.unlink()

    print(f"\nCreating fresh isolated staging database: {staging_db_path}")
    # SQLite online backup API
    src_conn = sqlite3.connect(f"file:{active_db_path.as_posix()}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(str(staging_db_path))
    try:
        src_conn.backup(dst_conn)
        dst_conn.commit()
    finally:
        dst_conn.close()
        src_conn.close()

    staging_size = staging_db_path.stat().st_size
    staging_sha256 = compute_sha256(staging_db_path)
    print(f"Staging DB created: {staging_size:,} bytes, SHA-256: {staging_sha256}")

    # Integrity & FK checks on staging
    print("\nRunning integrity and foreign-key checks on staging database...")
    check_conn = sqlite3.connect(f"file:{staging_db_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity_res = check_conn.execute("PRAGMA integrity_check").fetchall()
        print(f"PRAGMA integrity_check: {integrity_res}")
        if integrity_res != [("ok",)]:
            print("ERROR: Staging integrity check failed!")
            return 1

        fk_violations = check_conn.execute("PRAGMA foreign_key_check").fetchall()
        print(f"PRAGMA foreign_key_check: {len(fk_violations)} violations")
        if fk_violations:
            print(f"ERROR: Foreign key violations detected: {fk_violations}")
            return 1
    finally:
        check_conn.close()

    # Re-verify active database checksum to prove zero writes
    active_sha256_after = compute_sha256(active_db_path)
    if active_sha256_after != t0_active_sha256:
        print("CRITICAL ERROR: Active database was modified during backup!")
        return 1
    print("\nActive database verified UNCHANGED (T1 SHA-256 == T0 SHA-256 byte-identical).")

    # Save Phase 1 verification metadata
    meta = {
        "active_db": {
            "path": str(active_db_path),
            "size_bytes": active_size,
            "t0_sha256": t0_active_sha256,
            "t1_sha256_post_backup": active_sha256_after,
        },
        "source_dump": {
            "path": str(source_dump_path),
            "size_bytes": dump_size,
            "sha256": dump_sha256,
        },
        "staging_db": {
            "path": str(staging_db_path),
            "size_bytes": staging_size,
            "sha256": staging_sha256,
            "integrity": "ok",
            "fk_violations": 0,
        },
    }
    meta_path = ROOT / "migration_backups" / "phase1_stage_baseline.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Phase 1 baseline metadata saved to {meta_path}")
    print("=== Phase 1 Completed Successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
