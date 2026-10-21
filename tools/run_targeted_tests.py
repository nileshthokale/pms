"""Run a targeted regression subset with full database isolation.

Mirrors ``run_tests.py``'s safety: the suite runs against a throwaway
SQLite copy of ``data/pharmacy.db`` and the guard variables prevent any
test from writing to the real application database.

Usage:
    .venv\\Scripts\\python.exe tools\\run_targeted_tests.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODULES = [
    "test_auth",
    "test_financial_year",
    "test_backup_restore",
    "test_theme",
    "test_theme_refresh",
    "test_uppercase_input",
    "test_phase6b_wiring",
    "test_test_release_isolation",
]


def main() -> int:
    source_db = ROOT / "data" / "pharmacy.db"
    handle, name = tempfile.mkstemp(prefix="pharmacy_targeted_", suffix=".db")
    os.close(handle)
    staging_db = Path(name)
    staging_db.unlink()

    source = sqlite3.connect(f"file:{source_db.resolve().as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(staging_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    inherited = {
        name: os.environ.get(name)
        for name in ("PHARMACY_DB", "PHARMACY_TEST_PROTECTED_DB", "PHARMACY_TEST_SAFE_DB")
    }
    os.environ["PHARMACY_DB"] = str(staging_db)
    os.environ["PHARMACY_TEST_PROTECTED_DB"] = str(source_db.resolve())
    os.environ["PHARMACY_TEST_SAFE_DB"] = str(staging_db)
    for name in ("PHARMACY_TEST_RELEASE", "PHARMACY_REQUIRE_EXISTING_DB", "PHARMACY_DB_PATH"):
        os.environ.pop(name, None)

    try:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for module in MODULES:
            if (ROOT / f"{module}.py").is_file():
                suite.addTests(loader.loadTestsFromName(module))
            else:
                print(f"[skip] {module}.py not found")
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        print()
        print(
            f"Targeted suite: run={result.testsRun} "
            f"failures={len(result.failures)} errors={len(result.errors)} "
            f"skipped={len(result.skipped)}"
        )
        return 0 if result.wasSuccessful() else 1
    finally:
        for name, value in inherited.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        try:
            staging_db.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
