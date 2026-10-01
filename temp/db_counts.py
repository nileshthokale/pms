"""Print row counts for major tables of a SQLite pharmacy database.

Usage:
    python temp/db_counts.py [path-to-db] [out-file]

Read-only; used to prove the production database was not modified by tests.
"""
import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    db_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/pharmacy.db")
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "select name from sqlite_master where type='table' order by name")]
    counts = {}
    for table in tables:
        try:
            counts[table] = cur.execute(
                f'select count(*) from "{table}"').fetchone()[0]
        except Exception as exc:  # pragma: no cover - defensive
            counts[table] = f"ERROR: {exc}"
    con.close()

    text = json.dumps(counts, indent=1, sort_keys=True)
    if out_path:
        out_path.write_text(text, encoding="utf-8")
        print(f"wrote {out_path}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
