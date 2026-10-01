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
import shutil
import sys
import tempfile
import unittest


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))

    staging_db = None
    inherited_db = os.environ.get("PHARMACY_DB")
    if not inherited_db:
        source_db = root / "data" / "pharmacy.db"
        staging_db = pathlib.Path(tempfile.gettempdir()) / (
            f"pharmacy_full_suite_{os.getpid()}.db"
        )
        shutil.copy2(source_db, staging_db)
        os.environ["PHARMACY_DB"] = str(staging_db)

    try:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for file in sorted(root.glob("test_*.py")):
            suite.addTests(loader.loadTestsFromName(file.stem))

        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        if staging_db:
            for path in (staging_db, pathlib.Path(f"{staging_db}-wal"),
                         pathlib.Path(f"{staging_db}-shm")):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass


if __name__ == "__main__":
    sys.exit(main())
