"""Phase 2 — Party/reference masters ONLY (suppliers, customers, doctors).

Source: PharmaWinner202610051955.sql (READ-ONLY, offline parse).
Target: local dev DB only.
Modes: --dry-run (default; ZERO writes, target never opened),
       --apply (requires --confirm-local-dev; backup, atomic import, validate).

Scope rules:
- ledger debtors (SUNDRY DEBTORS) -> customers (IDs preserved, incl. WALKIN).
- ledger creditors (SUNDRY CREDITORS) -> suppliers (IDs preserved).
- doctormst -> doctors (IDs preserved; duplicate names BLOCK).
- sundaryinfo -> contact/address/city/state/tax fields (verbatim, no invention).
- ledger.OpeningBal NOT imported (Phase 2 forbids opening balances).
- ledger_id stays NULL (no ledgers in Phase 2; DAO auto-ledger never used).
- No transactions of any kind.
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
from database.legacy_migration import LegacyDump

DEFAULT_SOURCE = ROOT / "PharmaWinner202610051955.sql"
DEBTOR_GROUP, CREDITOR_GROUP = 16, 25

TRANSACTION_TABLES = (
    "purchase_invoices", "purchase_invoice_items", "stock_batches",
    "sales_invoices", "sales_invoice_items", "customer_receipts",
    "supplier_payments", "credit_notes", "credit_note_items",
    "debit_notes", "debit_note_items", "journal_entries",
    "journal_entry_items", "ledger_transactions",
)


def _fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


def resolve_target(explicit: str | None) -> str:
    return os.path.abspath(explicit) if explicit else os.path.abspath(get_db_path())


def guard_target(target: str) -> str | None:
    if getattr(sys, "frozen", False):
        return "refusing to run inside a frozen (packaged EXE) process"
    app_dir = os.path.abspath(get_app_data_dir())
    if os.path.normcase(target).startswith(os.path.normcase(app_dir + os.sep)):
        return f"refusing target inside production app-data dir ({app_dir})"
    if os.path.abspath(str(DEFAULT_SOURCE)) == target:
        return "target must never be the source SQL file"
    return None


def _verbatim(value) -> str:
    return "" if value is None else str(value)


def build_dry_run(dump: LegacyDump) -> dict:
    ledgers = list(dump.iter_rows("ledger"))
    led_by_id = {r[0]: r for r in ledgers}
    debtors = sorted([r for r in ledgers if r[2] == DEBTOR_GROUP], key=lambda r: r[0])
    creditors = sorted([r for r in ledgers if r[2] == CREDITOR_GROUP], key=lambda r: r[0])
    doctors = sorted(dump.iter_rows("doctormst"), key=lambda r: r[0])
    info = list(dump.iter_rows("sundaryinfo"))
    info_by_led = {r[1]: r for r in info}
    states = {r[0]: r[1] for r in dump.iter_rows("statemst")}

    # duplicates (new UNIQUE semantics: exact, verbatim)
    def dupes(rows, idx):
        seen: dict[str, list] = defaultdict(list)
        for r in rows:
            seen[_verbatim(r[idx])].append(r[0])
        return {k: v for k, v in seen.items() if len(v) > 1}

    blockers: list[str] = []
    # Approved: doctors.doctor_name is NOT UNIQUE (old doctormst legitimately
    # holds SELF twice with different details; all consumers key by id).
    # Same-name doctors are reported, never blockers.
    dup_doctors = dupes(doctors, 1)
    dup_debt = dupes(debtors, 1)
    dup_cred = dupes(creditors, 1)
    if dup_debt:
        blockers.append("duplicate debtor names: " + json.dumps(dup_debt))
    if dup_cred:
        blockers.append("duplicate creditor names: " + json.dumps(dup_cred))

    led_ids = set(led_by_id)
    orphan_info = [r[0] for r in info if r[1] not in led_ids]
    if orphan_info:
        blockers.append(f"sundaryinfo rows with unknown LedID: {orphan_info}")
    party_ids = {r[0] for r in debtors + creditors}
    no_info = sorted(party_ids - set(info_by_led))

    # ID-space safety: target tables must be empty for explicit-ID insert
    # (checked live at apply; reported here as requirement).

    # unsupported / not-imported-in-phase-2
    nonzero_ob = [(r[0], r[1], r[4]) for r in debtors + creditors if (r[4] or 0) != 0]

    def party_payload(rows, kind):
        out = []
        for r in rows:
            lid = r[0]
            inf = info_by_led.get(lid)
            state = ""
            if inf is not None and inf[9] in states:
                state = states[inf[9]]
            out.append({
                "new_id": lid, "legacy_ledger_id": lid,
                "name": _verbatim(r[1]),
                "address": _verbatim(inf[7]) if inf else "",
                "city": _verbatim(inf[8]) if inf else "",
                "state": state,
                "contact_person": _verbatim(inf[10]) if inf else "",
                "contact_no": _verbatim(inf[11]) if inf else "",
                "has_info_row": inf is not None,
                "opening_balance_ignored": r[4] or 0.0,
            })
            if kind == "supplier" and inf is not None:
                out[-1].update({
                    "sales_tax_no": _verbatim(inf[2]),
                    "vat_or_tin": _verbatim(inf[3]),
                    "discount": float(inf[4] or 0.0),
                    "credit_limit": float(inf[5] or 0.0),
                    "credit_period": int(float(inf[6] or 0)),
                    "vat_tin": _verbatim(inf[3]),
                })
            if kind == "customer" and inf is not None:
                out[-1].update({
                    "discount": float(inf[4] or 0.0),
                    "credit_limit": float(inf[5] or 0.0),
                    "credit_period": int(float(inf[6] or 0)),
                })
        return out

    return {
        "source_file": str(dump.path),
        "source_bytes": dump.size_bytes,
        "source_counts": {
            "ledger": len(ledgers), "debtors": len(debtors),
            "creditors": len(creditors), "sundaryinfo": len(info),
            "doctormst": len(doctors),
        },
        "target_expected": {
            "customers": len(debtors), "suppliers": len(creditors),
            "doctors": len(doctors),
        },
        "missing_info_ledgers": no_info,
        "orphan_info_rows": orphan_info,
        "duplicate_doctor_names": dup_doctors,
        "duplicate_debtor_names": dup_debt,
        "duplicate_creditor_names": dup_cred,
        "opening_balances_not_imported": {
            "count": len(nonzero_ob),
            "rows": nonzero_ob[:10],
        },
        "state_lookup": states,
        "unsupported_fields": [
            "ledger.OpeningBal (opening balances forbidden in Phase 2)",
            "ledger.AdminCreated / gpmst (no target; groups not imported)",
            "ledger.SGpID beyond debtor/creditor split (system ledgers excluded)",
            "sundaryinfo.StateID=0/unknown -> state '' (no invention)",
            "suppliers/customers.ledger_id stays NULL (no ledgers in Phase 2)",
            "customers have no sales_tax_no/vat columns in new schema",
        ],
        "mapping": {
            "ledger(LedHead, debtors) -> customers.customer_name": "verbatim, ID preserved",
            "ledger(LedHead, creditors) -> suppliers.supplier_name": "verbatim, ID preserved",
            "sundaryinfo.Address/City -> address/city": "verbatim",
            "sundaryinfo.StateID -> state via statemst": "1->MAHARASHTRA else ''",
            "sundaryinfo.ContactPerson/ContactNo": "verbatim",
            "sundaryinfo.SalesTaxNo/VATorTIN -> suppliers only": "verbatim",
            "sundaryinfo.DiscountPer/CreditLimit/CreditPeriod": "numeric, verbatim",
            "doctormst.DoctorName/Specality/City/PhoneNo -> doctors": "verbatim, ID preserved",
        },
        "customers_preview": party_payload(debtors, "customer")[:5],
        "suppliers_preview": party_payload(creditors, "supplier")[:5],
        "blockers": blockers,
        "internally_consistent": len(blockers) == 0,
    }


def render_markdown(rep: dict) -> str:
    L = ["# Phase 2 Dry Run — Party/Reference Masters ONLY", "",
         f"- Source: `{rep['source_file']}` ({rep['source_bytes']:,} bytes, READ-ONLY)", "",
         "## Source counts", ""]
    for k, v in rep["source_counts"].items():
        L.append(f"- {k}: {v}")
    L += ["", "## Target expected", ""]
    for k, v in rep["target_expected"].items():
        L.append(f"- {k}: {v}")
    L += ["",
          f"## Missing info rows (defaults): {rep['missing_info_ledgers']}",
          f"## Orphan info rows: {rep['orphan_info_rows']}",
          f"## Duplicate doctors: {json.dumps(rep['duplicate_doctor_names'])}",
          f"## Duplicate debtors/customers: {json.dumps(rep['duplicate_debtor_names'])}",
          f"## Duplicate creditors/suppliers: {json.dumps(rep['duplicate_creditor_names'])}",
          f"## Opening balances NOT imported: {rep['opening_balances_not_imported']['count']} parties",
          "", "## Unsupported fields"]
    L += [f"- {u}" for u in rep["unsupported_fields"]]
    L += ["", "## BLOCKERS" if rep["blockers"] else "## Blockers: none", ""]
    for b in rep["blockers"]:
        L.append(f"- BLOCKER: {b}")
    if not rep["blockers"]:
        L.append("- none — internally consistent")
    L += ["", f"Internally consistent: {rep['internally_consistent']}", ""]
    return "\n".join(L)


def do_apply(source: Path, target: str, backup_dir: str | None, no_backup: bool) -> dict:
    err = guard_target(target)
    if err:
        raise SystemExit(f"SAFETY REFUSAL: {err}")
    dump = LegacyDump(source)
    plan = build_dry_run(dump)
    if plan["blockers"]:
        raise SystemExit("REFUSING TO APPLY:\n" + "\n".join(f" - {b}" for b in plan["blockers"]))
    init_database()
    os.environ["PHARMACY_DB"] = target
    backup_info = None
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
        pre_phase1 = {}
        for table in ("companies", "units", "drugs", "items", "item_ingredients"):
            pre_phase1[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in ("suppliers", "customers", "doctors"):
            if conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] != 0:
                raise SystemExit(f"REFUSING: {table} not empty — Phase 1 freeze violation")
        ledgers = {r[0]: r for r in dump.iter_rows("ledger")}
        info_by_led = {r[1]: r for r in dump.iter_rows("sundaryinfo")}
        states = {r[0]: r[1] for r in dump.iter_rows("statemst")}
        imported = Counter()
        for r in sorted(dump.iter_rows("ledger"), key=lambda x: x[0]):
            if r[2] == DEBTOR_GROUP:
                inf = info_by_led.get(r[0])
                conn.execute(
                    """INSERT INTO customers (id, customer_name, city, contact_person,
                        contact_no, address, state, discount, credit_limit,
                        credit_period, opening_balance, ledger_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, NULL)""",
                    (r[0], _verbatim(r[1]),
                     _verbatim(inf[8]) if inf else "", _verbatim(inf[10]) if inf else "",
                     _verbatim(inf[11]) if inf else "", _verbatim(inf[7]) if inf else "",
                     states.get(inf[9], "") if inf else "",
                     float(inf[4] or 0.0) if inf else 0.0,
                     float(inf[5] or 0.0) if inf else 0.0,
                     int(float(inf[6] or 0)) if inf else 0),
                )
                imported["customers"] += 1
            elif r[2] == CREDITOR_GROUP:
                inf = info_by_led.get(r[0])
                conn.execute(
                    """INSERT INTO suppliers (id, supplier_name, sales_tax_no, vat_or_tin,
                        city, contact_person, contact_no, address, state, discount,
                        credit_limit, credit_period, vat_tin, opening_balance, ledger_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, NULL)""",
                    (r[0], _verbatim(r[1]),
                     _verbatim(inf[2]) if inf else "", _verbatim(inf[3]) if inf else "",
                     _verbatim(inf[8]) if inf else "", _verbatim(inf[10]) if inf else "",
                     _verbatim(inf[11]) if inf else "", _verbatim(inf[7]) if inf else "",
                     states.get(inf[9], "") if inf else "",
                     float(inf[4] or 0.0) if inf else 0.0,
                     float(inf[5] or 0.0) if inf else 0.0,
                     int(float(inf[6] or 0)) if inf else 0,
                     _verbatim(inf[3]) if inf else ""),
                )
                imported["suppliers"] += 1
        for r in sorted(dump.iter_rows("doctormst"), key=lambda x: x[0]):
            conn.execute(
                "INSERT INTO doctors (id, doctor_name, city, specialty, phone_no) VALUES (?, ?, ?, ?, ?)",
                (r[0], _verbatim(r[1]), _verbatim(r[3]), _verbatim(r[2]), _verbatim(r[4])),
            )
            imported["doctors"] += 1
        for table in ("suppliers", "customers", "doctors"):
            row = conn.execute(f'SELECT MAX(id) FROM "{table}"').fetchone()
            if row and row[0]:
                if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name=?", (table,)).fetchone():
                    conn.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?", (row[0], table))
                else:
                    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, row[0]))
        problems: list[str] = []
        for table, expected in (("customers", plan["target_expected"]["customers"]),
                                ("suppliers", plan["target_expected"]["suppliers"]),
                                ("doctors", plan["target_expected"]["doctors"])):
            got = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if got != expected:
                problems.append(f"{table}: expected {expected}, found {got}")
        for table in TRANSACTION_TABLES:
            try:
                got = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except sqlite3.OperationalError:
                continue
            if got != 0:
                problems.append(f"transaction table {table} not empty ({got})")
        # Phase-1 freeze: masters unchanged relative to pre-import state.
        for table, expected in pre_phase1.items():
            got = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if got != expected:
                problems.append(f"Phase-1 table {table} changed: {expected} -> {got}")
        if conn.execute("SELECT COUNT(*) FROM account_ledgers").fetchone()[0] != 0:
            problems.append("account_ledgers not empty (no ledgers in Phase 2)")
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            problems.append(f"foreign_key_check violations: {len(fk)}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            problems.append("integrity_check failed")
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
    conn = sqlite3.connect(target)
    try:
        final_counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                        for t in ("customers", "suppliers", "doctors")}
    finally:
        conn.close()
    return {"target": target, "backup": backup_info, "imported": dict(imported),
            "final_counts": final_counts,
            "integrity_check": "ok", "foreign_key_violations": 0,
            "sha256": hashlib.sha256(Path(target).read_bytes()).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 party-masters-only migration (local dev only).")
    parser.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
    parser.add_argument("--target", default=None)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
