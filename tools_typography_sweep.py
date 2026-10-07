"""One-off typography sweep across screens/ and ui/ (literal replacements).

Every rule is an exact, whole-string replacement — no regex — so the sweep
can only touch the intended declarations.  Run with ``--check`` to report
what would change without writing anything.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent

RULES: list[tuple[str, str, str]] = [
    (
        "table data 11px -> 13px",
        "f\"  font-size: 11px; font-family: 'Segoe UI';\"",
        "f\"  font-size: 13px; font-family: 'Segoe UI';\"",
    ),
    (
        "field captions: grey 11px -> black bold 12px",
        '_LABEL_DIM = f"color: {_TEXT_DIM}; font-size: 11px; '
        "font-family: 'Segoe UI'; background: transparent;\"",
        '_LABEL_DIM = f"color: {_TEXT}; font-size: 12px; font-weight: bold; '
        "font-family: 'Segoe UI'; background: transparent;\"",
    ),
    (
        "form captions 11px -> 12px",
        '_HEADER_LABEL = f"color: {_TEXT}; font-size: 11px; '
        "font-family: 'Segoe UI'; background: transparent; font-weight: bold;\"",
        '_HEADER_LABEL = f"color: {_TEXT}; font-size: 12px; '
        "font-family: 'Segoe UI'; background: transparent; font-weight: bold;\"",
    ),
    (
        "danger buttons 11px -> 12px",
        "f\"  font-weight: bold; font-size: 11px; font-family: 'Segoe UI'; }}\"",
        "f\"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}\"",
    ),
]


def main() -> int:
    check = "--check" in sys.argv
    total = 0
    for rule_index, (label, old, new) in enumerate(RULES, start=1):
        hits = 0
        for path in sorted(ROOT.glob("screens/*.py")) + sorted(ROOT.glob("ui/*.py")):
            text = path.read_text(encoding="utf-8")
            count = text.count(old)
            if not count:
                continue
            hits += count
            print(f"  rule {rule_index} [{label}] {path.name}: {count}")
            if not check:
                path.write_text(text.replace(old, new), encoding="utf-8")
        print(f"rule {rule_index} [{label}] -> {hits} replacement(s)")
        total += hits
    print(f"{'would replace' if check else 'replaced'} {total} declaration(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
