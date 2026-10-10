"""Phase 1 — Item Master ONLY migration from Pharma-WINNER MySQL 5.7 dump.

Controlled LOCAL DEVELOPMENT migration.  Reads the READ-ONLY source dump
``PharmaWinner202610051955.sql`` OFFLINE (never connects to MySQL, never
writes to the source file) and imports ONLY the minimum reference/master
data required for Item Master validity:

    companymst  -> companies   (ONLY rows referenced by itemmst, IDs preserved)
    unitmst     -> units       (ONLY rows referenced by itemmst, IDs preserved)
    pathymst    -> items.pathy (value lookup, NO separate table)
    drugmst     -> drugs       (ONLY rows referenced by itemdrugs, IDs preserved)
    itemmst     -> items       (IDs + values preserved verbatim)
    itemdrugs   -> item_ingredients (item/drug IDs preserved, Power verbatim)

Explicitly NEVER imports transactions: purchases, sales, counter sales,
stock, receipts, payments, credit/debit notes, journals, ledgers,
opening balances.  Apply mode verifies all transaction tables are empty
afterwards and aborts otherwise.

Modes:
    --dry-run   Parse the dump, compute counts, report blockers.
                Performs ZERO database writes (target is never opened).
    --apply     Backup target, clear ONLY Phase-1 tables, import in ONE
                transaction (rollback on any error), then validate.
                Requires --confirm-local-dev.

Safety:
    * Refuses to run frozen (packaged EXE).
    * Refuses any target inside the per-user app-data dir (production EXE DB).
    * Default target is the local dev DB from database.connection.get_db_path().
    * Source SQL is opened read-only and never modified.

Mapping (OLD -> NEW, verbatim unless noted):
    companymst.ID          -> companies.id (explicit, preserved)
    companymst.CompanyName -> companies.company_name (verbatim)
    companymst.ShortName   -> companies.short_name (verbatim, [:10] safety)
    unitmst.ID            -> units.id (explicit, preserved)
    unitmst.ItemUnit      -> units.unit_name (verbatim)
    drugmst.ID            -> drugs.id (explicit, preserved)
    drugmst.DrugName      -> drugs.drug_name (verbatim)
    pathymst.ID/Pathy     -> items.pathy TEXT (PathyID resolved to Pathy string)
    itemmst.ID            -> items.id (explicit, preserved)
    itemmst.ItemName      -> items.item_name (verbatim, incl. spaces)
    itemmst.UnitID        -> items.unit_id (preserved ID, direct FK)
    itemmst.CompanyID     -> items.company_id (preserved ID, direct FK)
    itemmst.PackSize      -> items.pack_size TEXT (str(int))
    itemmst.DiscountPer   -> items.discount REAL
    itemmst.ReorderStockLevel -> items.reorder_stock_level INT
    itemmst.Rate          -> items.rate REAL
    itemmst.MRP           -> items.mrp REAL
    itemmst.TaxID         -> items.tax_structure TEXT (str verbatim, UNKNOWN)
    itemmst.Location      -> items.location TEXT (verbatim)
    itemmst.SheduledID    -> items.scheduled TEXT (str verbatim)
    itemmst.SellLoose     -> UNSUPPORTED (no target column)
    itemmst.BillCompulsory-> UNSUPPORTED (no target column)
    itemmst.DPCO           -> items.dpco TEXT (verbatim 'Y'/'N')
    itemdrugs.ItemID      -> item_ingredients.item_id (preserved)
    itemdrugs.DrugID      -> item_ingredients.drug_id (preserved)
    itemdrugs.Power       -> item_ingredients.power (verbatim)
    itemdrugs.ID          -> (no target; item_ingredients.id is new)
    items.category_id     -> always NULL in Phase 1 (not invented)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_app_data_dir, get_db_path, init_database
from database.legacy_migration import LegacyDump  # offline dump parser (read-only)

DEFAULT_SOURCE = ROOT / "PharmaWinner202610051955.sql"

# Tables that must remain EMPTY after Phase 1 (spec section 11).
TRANSACTION_TABLES = (
    "purchase_invoices",
    "purchase_invoice_items",
    "stock_batches",
    "sales_invoices",
    "sales_invoice_items",
    "customer_receipts",
    "supplier_payments",
    "credit_notes",
    "credit_note_items",
    "debit_notes",
    "debit_note_items",
    "journal_entries",
    "journal_entry_items",
    "ledger_transactions",
)

# Phase-1 tables in FK-safe clear order (children first).
PHASE1_CLEAR_ORDER = (
    "item_ingredients",
    "items",
    "drugs",
    "units",
    "companies",
)


def _text(value) -> str:
    if value is None:
        return ""
    return str(value)


def _verbatim_name(value) -> str:
    """Item/company/unit/drug names: preserved byte-for-byte (no strip)."""
    if value is None:
        return ""
    return str(value)


def _pack(value) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _num(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


def resolve_target(explicit: str | None) -> str:
    if explicit:
        return os.path.abspath(explicit)
    return os.path.abspath(get_db_path())


def guard_target(target: str) -> str | None:
    """Return an error message if the target is not a safe local-dev DB."""
    if getattr(sys, "frozen", False):
        return "refusing to run inside a frozen (packaged EXE) process"
    app_dir = os.path.abspath(get_app_data_dir())
    if os.path.normcase(target).startswith(os.path.normcase(app_dir + os.sep)) or os.path.normcase(target) == os.path.normcase(app_dir):
        return (
            f"refusing target inside production app-data dir ({app_dir}). "
            "Phase 1 is LOCAL DEVELOPMENT ONLY."
        )
    if os.path.abspath(str(DEFAULT_SOURCE)) == target:
        return "target must never be the source SQL file"
    return None


def build_dry_run(dump: LegacyDump) -> dict:
    counts = dump.count_rows()
    cols = dump.table_columns

    def rows(t):
        return list(dump.iter_rows(t))

    company_rows = rows("companymst")
    unit_rows = rows("unitmst")
    pathy_rows = rows("pathymst")
    drug_rows = rows("drugmst")
    item_rows = rows("itemmst")
    link_rows = rows("itemdrugs")

    company_by_id = {r[0]: r for r in company_rows}
    unit_by_id = {r[0]: r for r in unit_rows}
    pathy_by_id = {r[0]: r[1] for r in pathy_rows}
    drug_by_id = {r[0]: r for r in drug_rows}

    # ---- references required by items ----
    ref_company_ids = sorted({r[4] for r in item_rows if r[4] is not None})
    ref_unit_ids = sorted({r[2] for r in item_rows if r[2] is not None})
    ref_pathy_ids = sorted({r[3] for r in item_rows if r[3] is not None})
    ref_drug_ids = sorted({r[2] for r in link_rows})

    missing_company = [c for c in ref_company_ids if c not in company_by_id]
    missing_unit = [u for u in ref_unit_ids if u not in unit_by_id]
    missing_pathy = [p for p in ref_pathy_ids if p not in pathy_by_id]
    item_ids = {r[0] for r in item_rows}
    drug_ids = set(drug_by_id)
    orphan_links_item = [r for r in link_rows if r[1] not in item_ids]
    orphan_links_drug = [r for r in link_rows if r[2] not in drug_ids]

    # ---- duplicate / UNIQUE analysis (composite UNIQUE(item_name, unit_id):
    #      SQLite semantics are case-sensitive and whitespace-sensitive, and
    #      names are preserved verbatim — no normalization) ----
    exact_item_names: dict[str, list] = defaultdict(list)
    norm_item_names: dict[str, list] = defaultdict(list)
    composite_keys: dict[tuple, list] = defaultdict(list)
    for r in item_rows:
        exact_item_names[_verbatim_name(r[1])].append(r[0])
        norm_item_names[(_verbatim_name(r[1]).strip().upper())].append(r[0])
        composite_keys[(_verbatim_name(r[1]), r[2])].append(r[0])
    exact_dup_items = {k: v for k, v in exact_item_names.items() if len(v) > 1}
    norm_dup_items = {k: v for k, v in norm_item_names.items() if len(v) > 1}
    composite_dup_items = {k: v for k, v in composite_keys.items() if len(v) > 1}

    ref_company_names: dict[str, list] = defaultdict(list)
    for cid in ref_company_ids:
        row = company_by_id.get(cid)
        if row is not None:
            ref_company_names[_verbatim_name(row[1])].append(cid)
    exact_dup_ref_companies = {k: v for k, v in ref_company_names.items() if len(v) > 1}

    # ---- tax analysis: NO tax master table exists in the dump ----
    tax_values = sorted({r[10] for r in item_rows}, key=lambda v: (v is None, v))
    tax_dist = dict(Counter(r[10] for r in item_rows))
    from database import tax_structures as _ts

    tax_mapping = []
    for t in tax_values:
        s = "" if t is None else str(t)
        if _ts.is_gst_rate(s):
            status = "AMBIGUOUS-NUMERIC-OVERLAP"
            note = (
                "numerically equals a GST rate but old meaning is UNKNOWN "
                "(no tax master in dump); preserved verbatim, never converted"
            )
        else:
            status = "UNKNOWN"
            note = "no tax master table in source dump; preserved verbatim"
        tax_mapping.append(
            {
                "old_tax_id": t,
                "old_meaning": None,
                "new_value": s,
                "mapping_status": status,
                "note": note,
            }
        )

    # ---- invalid / limit checks ----
    null_item_names = [r[0] for r in item_rows if not _verbatim_name(r[1])]
    negative_mrp = [r[0] for r in item_rows if _num(r[9]) < 0]
    negative_rate = [r[0] for r in item_rows if _num(r[8]) < 0]
    # NEW schema TEXT columns have no length CHECK; old maxima reported only.
    max_lengths = {
        "companymst.CompanyName": max((len(_verbatim_name(r[1])) for r in company_rows), default=0),
        "itemmst.ItemName": max((len(_verbatim_name(r[1])) for r in item_rows), default=0),
        "drugmst.DrugName": max((len(_verbatim_name(r[1])) for r in drug_rows), default=0),
        "itemdrugs.Power": max((len(_text(r[3])) for r in link_rows), default=0),
        "itemmst.Location": max((len(_text(r[11])) for r in item_rows), default=0),
    }
    sched_values = sorted({r[12] for r in item_rows}, key=lambda v: (v is None, v))

    # ---- target expected (required-only imports) ----
    target_expected = {
        "companies": len(ref_company_ids),
        "units": len(ref_unit_ids),
        "drugs": len(ref_drug_ids),
        "items": len(item_rows),
        "item_ingredients": len(link_rows),
    }

    blockers: list[str] = []
    if composite_dup_items:
        blockers.append(
            "duplicate (item_name, unit_id) values violate NEW "
            "UNIQUE(item_name, unit_id): "
            + json.dumps({f"{k[0]!r} unit={k[1]!r}": v for k, v in composite_dup_items.items()})
            + ". Phase 1 preserves names verbatim and will NOT merge; "
              "apply would roll back on UNIQUE constraint."
        )
    if exact_dup_ref_companies:
        blockers.append(
            "duplicate company_name among REQUIRED companies: "
            + json.dumps(exact_dup_ref_companies)
        )
    if missing_company or missing_unit or missing_pathy:
        blockers.append("missing master references detected")
    if orphan_links_item or orphan_links_drug:
        blockers.append("orphan itemdrugs rows detected")

    report = {
        "source_file": str(dump.path),
        "source_bytes": dump.size_bytes,
        "source_counts": {
            "companymst": len(company_rows),
            "unitmst": len(unit_rows),
            "pathymst": len(pathy_rows),
            "drugmst": len(drug_rows),
            "itemmst": len(item_rows),
            "itemdrugs": len(link_rows),
        },
        "target_expected": target_expected,
        "references": {
            "required_company_ids": ref_company_ids,
            "required_company_count": len(ref_company_ids),
            "required_unit_ids": ref_unit_ids,
            "required_unit_count": len(ref_unit_ids),
            "required_pathy_ids": ref_pathy_ids,
            "required_drug_ids": ref_drug_ids,
            "required_drug_count": len(ref_drug_ids),
            "unreferenced_units_skipped": sorted(set(unit_by_id) - set(ref_unit_ids)),
            "unreferenced_drugs_skipped": len(set(drug_by_id) - set(ref_drug_ids)),
            "unreferenced_companies_skipped": len(set(company_by_id) - set(ref_company_ids)),
        },
        "missing_references": {
            "companies": missing_company,
            "units": missing_unit,
            "pathy": missing_pathy,
            "itemdrugs_missing_item": [r[0] for r in orphan_links_item],
            "itemdrugs_missing_drug": [r[0] for r in orphan_links_drug],
        },
        "duplicate_item_names_exact": exact_dup_items,
        "duplicate_item_names_normalized": norm_dup_items,
        "duplicate_item_name_unit_composite": {
            f"{k[0]!r} unit={k[1]!r}": v for k, v in composite_dup_items.items()
        },
        "duplicate_required_company_names": exact_dup_ref_companies,
        "tax": {
            "has_tax_master_table": False,
            "distinct_tax_ids": tax_values,
            "distribution": {str(k): v for k, v in tax_dist.items()},
            "mapping": tax_mapping,
        },
        "scheduled_ids": sched_values,
        "unsupported_fields": [
            "itemmst.SellLoose (no target column; all values "
            + json.dumps(dict(Counter(r[13] for r in item_rows))) + ")",
            "itemmst.BillCompulsory (no target column; all values "
            + json.dumps(dict(Counter(r[14] for r in item_rows))) + ")",
            "itemdrugs.ID (no target; item_ingredients.id is newly generated)",
            "items.category_id (always NULL in Phase 1; never invented)",
        ],
        "invalid_values": {
            "empty_item_names": null_item_names,
            "negative_mrp_item_ids": negative_mrp,
            "negative_rate_item_ids": negative_rate,
            "missing_item_id_198_gap": 198 not in item_ids,
        },
        "max_source_lengths": max_lengths,
        "pathy_values": [{"id": r[0], "pathy": r[1]} for r in pathy_rows],
        "unit_values": [{"id": r[0], "unit": r[1]} for r in unit_rows],
        "blockers": blockers,
        "internally_consistent": len(blockers) == 0,
        "mapping": {
            "companymst.ID->companies.id": "preserved explicit",
            "companymst.CompanyName->companies.company_name": "verbatim",
            "companymst.ShortName->companies.short_name": "verbatim",
            "unitmst.ID->units.id": "preserved explicit",
            "unitmst.ItemUnit->units.unit_name": "verbatim",
            "drugmst.ID->drugs.id": "preserved explicit",
            "drugmst.DrugName->drugs.drug_name": "verbatim",
            "pathymst->items.pathy": "PathyID resolved to Pathy string",
            "itemmst.ID->items.id": "preserved explicit",
            "itemmst.ItemName->items.item_name": "verbatim",
            "itemmst.UnitID->items.unit_id": "preserved direct FK",
            "itemmst.CompanyID->items.company_id": "preserved direct FK",
            "itemmst.PackSize->items.pack_size": "smallint to TEXT",
            "itemmst.DiscountPer->items.discount": "float to REAL",
            "itemmst.ReorderStockLevel->items.reorder_stock_level": "smallint to INT",
            "itemmst.Rate->items.rate": "float to REAL",
            "itemmst.MRP->items.mrp": "float to REAL",
            "itemmst.TaxID->items.tax_structure": "verbatim TEXT, UNKNOWN meaning",
            "itemmst.Location->items.location": "verbatim TEXT",
            "itemmst.SheduledID->items.scheduled": "verbatim TEXT",
            "itemmst.DPCO->items.dpco": "verbatim TEXT",
            "itemdrugs.ItemID->item_ingredients.item_id": "preserved",
            "itemdrugs.DrugID->item_ingredients.drug_id": "preserved",
            "itemdrugs.Power->item_ingredients.power": "verbatim",
        },
    }
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# Phase 1 Dry Run — Item Master ONLY",
        "",
        f"- Source: `{report['source_file']}` ({report['source_bytes']:,} bytes, READ-ONLY)",
        "",
        "## Source counts",
        "",
    ]
    for k, v in report["source_counts"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Target expected (required-only)", ""]
    for k, v in report["target_expected"].items():
        lines.append(f"- {k}: {v}")
    lines += [
        "",
        "## References",
        f"- required companies: {report['references']['required_company_count']}",
        f"- required units: {report['references']['required_unit_count']} "
        f"(skip unreferenced unit IDs {report['references']['unreferenced_units_skipped']})",
        f"- required drugs: {report['references']['required_drug_count']} "
        f"(skip {report['references']['unreferenced_drugs_skipped']} unreferenced)",
        f"- skip {report['references']['unreferenced_companies_skipped']} unreferenced companies",
        f"- pathy IDs referenced: {report['references']['required_pathy_ids']}",
        "",
        "## Missing references (must all be empty)",
        f"- {json.dumps(report['missing_references'])}",
        "",
        "## Duplicate item names (composite UNIQUE(item_name, unit_id))",
        f"- exact name duplicates (informational only): {json.dumps(report['duplicate_item_names_exact'])}",
        f"- normalized name duplicates (informational only): {json.dumps(report['duplicate_item_names_normalized'])}",
        f"- composite (name, unit) conflicts (blockers): {json.dumps(report['duplicate_item_name_unit_composite'])}",
        "",
        "## Tax mapping (no master table in dump — all UNKNOWN)",
    ]
    for m in report["tax"]["mapping"]:
        lines.append(
            f"- TaxID={m['old_tax_id']!r} -> {m['new_value']!r}: "
            f"{m['mapping_status']} ({m['note']})"
        )
    lines += [
        "",
        "## Unsupported fields",
    ]
    for u in report["unsupported_fields"]:
        lines.append(f"- {u}")
    lines += [
        "",
        "## Invalid values",
        f"- {json.dumps(report['invalid_values'])}",
        "",
        "## BLOCKERS" if report["blockers"] else "## Blockers: none",
        "",
    ]
    for b in report["blockers"]:
        lines.append(f"- BLOCKER: {b}")
    if not report["blockers"]:
        lines.append("- none — internally consistent")
    lines += [
        "",
        f"Internally consistent: {report['internally_consistent']}",
        "",
    ]
    return "\n".join(lines)


def do_apply(source: Path, target: str, backup_dir: str | None, no_backup: bool) -> dict:
    err = guard_target(target)
    if err:
        raise SystemExit(f"SAFETY REFUSAL: {err}")
    dump = LegacyDump(source)
    plan = build_dry_run(dump)
    if plan["blockers"]:
        raise SystemExit(
            "REFUSING TO APPLY: dry-run blockers present:\n"
            + "\n".join(f" - {b}" for b in plan["blockers"])
        )

    init_database()
    os.environ["PHARMACY_DB"] = target

    backup_info: dict | None = None
    if not no_backup:
        from database import backup_restore

        dest = backup_dir or str(Path(target).parent / "backups")
        backup_info = backup_restore.create_backup(dest, record_last=False)
        validation = backup_restore.validate_backup(backup_info["path"])
        if not validation.get("valid"):
            raise SystemExit(f"pre-migration backup failed validation: {validation}")

    conn = sqlite3.connect(target)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        # Clear ONLY Phase-1 tables (children first). Everything else
        # (financial_years, users, ledgers, transactions) is preserved, and
        # transaction tables are verified empty afterwards.
        for table in PHASE1_CLEAR_ORDER:
            conn.execute(f'DELETE FROM "{table}"')

        company_by_id = {r[0]: r for r in dump.iter_rows("companymst")}
        unit_by_id = {r[0]: r for r in dump.iter_rows("unitmst")}
        pathy_by_id = {r[0]: _text(r[1]) for r in dump.iter_rows("pathymst")}
        drug_by_id = {r[0]: r for r in dump.iter_rows("drugmst")}
        item_rows = sorted(dump.iter_rows("itemmst"), key=lambda r: r[0])
        link_rows = sorted(dump.iter_rows("itemdrugs"), key=lambda r: r[0])

        ref_company_ids = {r[4] for r in item_rows if r[4] is not None}
        ref_unit_ids = {r[2] for r in item_rows if r[2] is not None}
        ref_drug_ids = {r[2] for r in link_rows}

        imported = Counter()
        for cid in sorted(ref_company_ids):
            src_row = company_by_id[cid]
            conn.execute(
                "INSERT INTO companies (id, company_name, short_name) VALUES (?, ?, ?)",
                (src_row[0], _verbatim_name(src_row[1]), _verbatim_name(src_row[2])[:10]),
            )
            imported["companies"] += 1
        for uid in sorted(ref_unit_ids):
            src_row = unit_by_id[uid]
            conn.execute(
                "INSERT INTO units (id, unit_name) VALUES (?, ?)",
                (src_row[0], _verbatim_name(src_row[1])),
            )
            imported["units"] += 1
        for did in sorted(ref_drug_ids):
            src_row = drug_by_id[did]
            conn.execute(
                "INSERT INTO drugs (id, drug_name) VALUES (?, ?)",
                (src_row[0], _verbatim_name(src_row[1])),
            )
            imported["drugs"] += 1
        for r in item_rows:
            conn.execute(
                """INSERT INTO items (id, item_name, unit_id, company_id,
                    category_id, pack_size, tax_structure, discount, mrp, rate,
                    reorder_stock_level, scheduled, location, pathy, dpco,
                    legacy_tax_id)
                    VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r[0], _verbatim_name(r[1]), r[2], r[4],
                    _pack(r[5]), _text(r[10]), _num(r[6]), _num(r[9]),
                    _num(r[8]), int(_num(r[7])), _text(r[12]), _text(r[11]),
                    pathy_by_id.get(r[3], ""), _text(r[15]), r[10],
                ),
            )
            imported["items"] += 1
        for r in link_rows:
            conn.execute(
                "INSERT INTO item_ingredients (item_id, drug_id, power) VALUES (?, ?, ?)",
                (r[1], r[2], _text(r[3])),
            )
            imported["item_ingredients"] += 1

        # Keep AUTOINCREMENT cursors above preserved IDs.
        for table in ("companies", "units", "drugs", "items", "item_ingredients"):
            row = conn.execute(f'SELECT MAX(id) FROM "{table}"').fetchone()
            if row and row[0]:
                conn.execute(
                    "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                    (row[0], table),
                )
                if conn.total_changes == 0:
                    conn.execute(
                        "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                        (table, row[0]),
                    )

        # ---- post-import validation BEFORE commit ----
        problems: list[str] = []
        for table, expected in plan["target_expected"].items():
            got = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if got != expected:
                problems.append(f"{table}: expected {expected}, found {got}")
        for table in TRANSACTION_TABLES:
            try:
                got = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except sqlite3.OperationalError:
                continue  # table absent in older schema variants
            if got != 0:
                problems.append(f"transaction table {table} not empty ({got})")
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            problems.append(f"foreign_key_check violations: {len(fk)}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            problems.append("integrity_check failed")
        orphans = conn.execute(
            """SELECT COUNT(*) FROM items WHERE unit_id IS NOT NULL
               AND unit_id NOT IN (SELECT id FROM units)"""
        ).fetchone()[0]
        if orphans:
            problems.append(f"{orphans} items with orphan unit_id")
        orphans = conn.execute(
            """SELECT COUNT(*) FROM items WHERE company_id IS NOT NULL
               AND company_id NOT IN (SELECT id FROM companies)"""
        ).fetchone()[0]
        if orphans:
            problems.append(f"{orphans} items with orphan company_id")
        orphans = conn.execute(
            """SELECT COUNT(*) FROM item_ingredients WHERE item_id NOT IN
               (SELECT id FROM items) OR drug_id NOT IN (SELECT id FROM drugs)"""
        ).fetchone()[0]
        if orphans:
            problems.append(f"{orphans} orphan item_ingredients")
        missing_prov = conn.execute(
            "SELECT COUNT(*) FROM items WHERE legacy_tax_id IS NULL"
        ).fetchone()[0]
        if missing_prov:
            problems.append(f"{missing_prov} items without legacy_tax_id provenance")
        if problems:
            conn.rollback()
            raise SystemExit("VALIDATION FAILED (rolled back):\n" + "\n".join(f" - {p}" for p in problems))

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    # File-level verification after commit.
    conn = sqlite3.connect(target)
    try:
        final_counts = {
            t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for t in ("companies", "units", "drugs", "items", "item_ingredients")
        }
        tran_counts = {}
        for t in TRANSACTION_TABLES:
            try:
                tran_counts[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.OperationalError:
                tran_counts[t] = "no-table"
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    finally:
        conn.close()
    return {
        "target": target,
        "backup": backup_info,
        "imported": dict(imported),
        "final_counts": final_counts,
        "transaction_counts": tran_counts,
        "integrity_check": integrity,
        "foreign_key_violations": fk_violations,
        "sha256": hashlib.sha256(Path(target).read_bytes()).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1 Item-Master-only migration (local dev only).")
    parser.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
    parser.add_argument("--target", default=None, help="target SQLite DB (default: local dev DB)")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--confirm-local-dev", action="store_true", default=False)
    parser.add_argument("--report", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--backup-dir", default=None)
    parser.add_argument("--no-backup", action="store_true", default=False)
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_file():
        return _fail(f"source SQL not found: {source}")
    target = resolve_target(args.target)

    if args.apply:
        if not args.confirm_local_dev:
            return _fail("apply requires --confirm-local-dev (local development ONLY)")
        err = guard_target(target)
        if err:
            return _fail(f"SAFETY REFUSAL: {err}")
        try:
            result = do_apply(source, target, args.backup_dir, args.no_backup)
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        if args.json:
            Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0

    # Default / --dry-run: never opens the target DB.
    err = guard_target(target)
    dump = LegacyDump(source)
    report = build_dry_run(dump)
    report["target_db"] = target
    report["target_guard"] = err or "ok (dry-run performs zero writes)"
    md = render_markdown(report)
    print(md)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(md, encoding="utf-8")
        print(f"\nwritten: {args.report}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"written: {args.json}")
    if err:
        print(f"\nNOTE: target guard would refuse apply: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
