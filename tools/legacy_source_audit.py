"""Phase 2 — full source-to-target audit of the Pharma-WINNER dump.

Read-only.  Walks **every** table in the legacy ``.sql`` dump and places it in
exactly one bucket:

* ``imported``      — has a target table; source and target row counts agree.
* ``partial``       — imported, but the counts differ (merges/exclusions).
* ``missing``       — supported mapping exists but the target is empty.
* ``excluded``      — deliberately not migrated, with the documented reason.
* ``unresolved``    — no mapping and no documented reason: needs investigation.

Nothing is imported, cleared or modified.  The dump is opened read-only and
the target database is opened with SQLite ``mode=ro``.

Usage
-----
    python tools/legacy_source_audit.py
    python tools/legacy_source_audit.py --db staging/pharmacy_staging.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import (  # noqa: E402
    SOURCE_TARGETS,
    UNSUPPORTED_TABLES,
    LegacyDump,
)

DEFAULT_SOURCE = ROOT / "PharmaWinner202610051955.sql"
DEFAULT_DB = ROOT / "data" / "pharmacy.db"
OUT_JSON = ROOT / "migration_backups" / "phase2_source_audit.json"
OUT_MD = ROOT / "migration_backups" / "phase2_source_audit.md"

#: Source tables whose target count legitimately differs because rows merge.
MERGE_TOLERANCE: dict[str, int] = {
    "companymst": 3,     # ALKEM, JAGSAM PHARMA x2 merged
    "doctormst": 1,      # SELF x2 merged
    "itemmst": 3,        # POWERGESIC, VITOMIN-Z, CALTONVIT merged
    "ledger": 6,         # system ledgers consolidated into roles
}

#: Tables which hold only "history linkage" rows on the stock side and whose
#: real quantities come from Phase 3.
STOCK_DEFERRED = {"stockbalance", "stockadjusted"}


def connect_ro(path: Path) -> sqlite3.Connection:
    uri = "file:" + str(path).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (name,)).fetchone() is not None


def count(conn: sqlite3.Connection, name: str) -> int | None:
    if not table_exists(conn, name):
        return None
    return int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])


def classify(source_table: str, source_rows: int, target_table: str | None,
             target_rows: int | None, mapped: int | None) -> tuple[str, str]:
    if target_table is None:
        reason = UNSUPPORTED_TABLES.get(
            source_table, "No target table in the new schema.")
        return "excluded", reason
    if target_rows is None:
        return "unresolved", f"target table `{target_table}` does not exist"
    if source_table in STOCK_DEFERRED:
        return "excluded", UNSUPPORTED_TABLES.get(source_table, "Stock deferred.")
    tolerance = MERGE_TOLERANCE.get(source_table, 0)
    if target_rows == source_rows:
        return "imported", ""
    if 0 < source_rows - target_rows <= tolerance:
        return "partial", (f"{source_rows - target_rows} row(s) merged during "
                           f"import (documented duplicate masters)")
    if target_rows == 0 and source_rows > 0:
        return "missing", "supported mapping, but the target table is empty"
    if target_rows < source_rows:
        return "partial", (f"{source_rows - target_rows} source row(s) not "
                           f"present in the target")
    return "unresolved", (f"target has {target_rows - source_rows} more row(s) "
                          f"than the source")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    args = ap.parse_args(argv)

    db_path = Path(args.db).resolve()
    src_path = Path(args.source).resolve()

    dump = LegacyDump(src_path)
    src_counts = dump.count_rows()

    conn = connect_ro(db_path)
    try:
        # legacy_id_map coverage per entity, if present
        entity_rows: dict[str, int] = {}
        if table_exists(conn, "legacy_id_map"):
            for r in conn.execute(
                    "SELECT entity, COUNT(*) AS n FROM legacy_id_map"
                    " GROUP BY entity"):
                entity_rows[str(r["entity"])] = int(r["n"])

        rows = []
        for table in sorted(src_counts):
            n = int(src_counts[table])
            mapped_to = SOURCE_TARGETS.get(table)
            target_name = None
            if mapped_to and "(" not in mapped_to and " " not in mapped_to:
                target_name = mapped_to
            target_rows = count(conn, target_name) if target_name else None
            bucket, reason = classify(table, n, target_name, target_rows, None)
            if mapped_to is None:
                bucket, reason = ("unresolved",
                                  "table present in the dump but not listed in "
                                  "SOURCE_TARGETS and not documented as excluded")
            rows.append({
                "source_table": table,
                "source_rows": n,
                "target_table": target_name,
                "target_rows": target_rows,
                "bucket": bucket,
                "reason": reason,
            })

        # target tables that exist but have no source at all (app-only data)
        app_only = []
        if table_exists(conn, "sqlite_master"):
            known_targets = {r["target_table"] for r in rows if r["target_table"]}
            for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                    " ORDER BY name"):
                name = r["name"]
                if name.startswith("sqlite_") or name in known_targets:
                    continue
                app_only.append({"table": name, "rows": count(conn, name)})

        totals = conn.execute(
            """SELECT COUNT(*) AS n,
                      SUM(CASE WHEN stock_qty > 0 THEN 1 ELSE 0 END) AS pos
                 FROM stock_batches""").fetchone() \
            if table_exists(conn, "stock_batches") else {"n": 0, "pos": 0}

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_file": str(src_path),
            "db_path": str(db_path),
            "source_tables": len(src_counts),
            "source_rows_total": sum(int(v) for v in src_counts.values()),
            "legacy_id_map_entities": entity_rows,
            "buckets": rows,
            "app_only_tables": app_only,
            "stock_batches_total": int(totals["n"] or 0),
            "stock_batches_positive": int(totals["pos"] or 0),
        }
    finally:
        conn.close()

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str),
                        encoding="utf-8")

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["bucket"]] = counts.get(r["bucket"], 0) + 1

    lines = [
        "# Phase 2 — Source-to-Target Audit",
        "",
        f"- Source: `{src_path}` ({src_path.stat().st_size:,} bytes, READ-ONLY)",
        f"- Target: `{db_path}`",
        f"- Source tables: {len(src_counts)}  ·  total source rows: "
        f"{report['source_rows_total']:,}",
        "",
        "| Bucket | Tables |",
        "| --- | ---: |",
    ]
    for b in ("imported", "partial", "missing", "excluded", "unresolved"):
        lines.append(f"| {b} | {counts.get(b, 0)} |")
    lines += ["", "## Per-table classification", ""]
    for bucket in ("imported", "partial", "missing", "excluded", "unresolved"):
        subset = [r for r in rows if r["bucket"] == bucket]
        if not subset:
            continue
        lines += [f"### {bucket.upper()} ({len(subset)})", "",
                  "| source | rows | target | rows | note |",
                  "| --- | ---: | --- | ---: | --- |"]
        for r in subset:
            lines.append(
                f"| `{r['source_table']}` | {r['source_rows']:,} | "
                f"`{r['target_table'] or '—'}` | "
                f"{'' if r['target_rows'] is None else format(r['target_rows'], ',')} | "
                f"{r['reason']} |")
        lines.append("")

    if app_only:
        lines += ["## Target tables with no source counterpart (application data)", "",
                  "| table | rows |", "| --- | ---: |"]
        for a in app_only:
            lines.append(f"| `{a['table']}` | {a['rows']} |")
        lines.append("")

    lines += [
        "## Stock state in this target",
        "",
        f"- `stock_batches` rows: {report['stock_batches_total']:,}",
        f"- with `stock_qty > 0`: **{report['stock_batches_positive']:,}**",
        "",
        "Counter Sale only offers batches with `stock_qty > 0`. If the number",
        "above is 0, every item shows `-- Select Batch --`; run",
        "`tools/legacy_stock_migration.py` to import real quantities.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("=" * 78)
    print(f"source : {src_path}  ({len(src_counts)} tables, "
          f"{report['source_rows_total']:,} rows)")
    print(f"target : {db_path}")
    print("-" * 78)
    for b in ("imported", "partial", "missing", "excluded", "unresolved"):
        print(f"  {b:<11} : {counts.get(b, 0)} table(s)")
    print("-" * 78)
    for b in ("missing", "unresolved"):
        for r in rows:
            if r["bucket"] == b:
                print(f"  [{b}] {r['source_table']} "
                      f"({r['source_rows']:,} rows) -> {r['target_table']} "
                      f":: {r['reason']}")
    print("-" * 78)
    print(f"stock_batches: {report['stock_batches_total']:,} rows, "
          f"{report['stock_batches_positive']:,} with stock_qty > 0")
    print("=" * 78)
    print(f"reports: {OUT_MD}\n         {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
