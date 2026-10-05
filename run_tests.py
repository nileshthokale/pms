"""Project test runner — reproducible full-suite baseline.

Runs every top-level test_*.py module WITHOUT recursing into the
application packages (screens/, ui/, database/). This matters in two
ways:

1. `unittest discover` imports every package it walks; in environments
   without PySide6 the screens/ui package imports fail and pollute the
   result with 2 environmental loader "errors" that are not test
   failures. This runner loads only the actual test modules.
2. GUI-dependent tests inside the test modules already skip themselves
   with an explicit dependency reason when PySide6 is unavailable, and
   run for real when it is installed (the development environment).

Usage:
    python run_tests.py           # full suite, verbose
"""

import pathlib
import os
import sqlite3
import sys
import tempfile
import unittest


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))

    # Never let an inherited PHARMACY_DB direct tests at a user or production
    # database.  Always run the suite against a disposable copy, regardless
    # of the caller's environment.  Preserve the caller's setting afterward.
    source_db = root / "data" / "pharmacy.db"
    fd, staging_name = tempfile.mkstemp(prefix="pharmacy_full_suite_", suffix=".db")
    os.close(fd)
    staging_db = pathlib.Path(staging_name)
    staging_db.unlink()
    inherited_db = os.environ.get("PHARMACY_DB")
    inherited_protected_db = os.environ.get("PHARMACY_TEST_PROTECTED_DB")
    inherited_safe_db = os.environ.get("PHARMACY_TEST_SAFE_DB")
    # SQLite's backup API takes a consistent snapshot, including any committed
    # data that is still represented in a WAL sidecar.
    source = sqlite3.connect(f"file:{source_db.resolve().as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(staging_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    os.environ["PHARMACY_DB"] = str(staging_db)
    os.environ["PHARMACY_TEST_PROTECTED_DB"] = str(source_db.resolve())
    os.environ["PHARMACY_TEST_SAFE_DB"] = str(staging_db)

    try:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for file in sorted(root.glob("test_*.py")):
            suite.addTests(loader.loadTestsFromName(file.stem))

        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        for path in (staging_db, pathlib.Path(f"{staging_db}-wal"),
                     pathlib.Path(f"{staging_db}-shm")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if inherited_db is None:
            os.environ.pop("PHARMACY_DB", None)
        else:
            os.environ["PHARMACY_DB"] = inherited_db
        if inherited_protected_db is None:
            os.environ.pop("PHARMACY_TEST_PROTECTED_DB", None)
        else:
            os.environ["PHARMACY_TEST_PROTECTED_DB"] = inherited_protected_db
        if inherited_safe_db is None:
            os.environ.pop("PHARMACY_TEST_SAFE_DB", None)
        else:
            os.environ["PHARMACY_TEST_SAFE_DB"] = inherited_safe_db


if __name__ == "__main__":
    sys.exit(main())
