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
import sys
import unittest


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for file in sorted(root.glob("test_*.py")):
        suite.addTests(loader.loadTestsFromName(file.stem))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
