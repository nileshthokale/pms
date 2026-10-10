"""Phase 6F — Legacy Pharma-WINNER data migration into the new SQLite system.

This module reads a legacy Pharma-WINNER **MySQL 5.7 dump** (``.sql`` text)
OFFLINE and transforms the historical business data into the new SQLite
schema.  It never connects to MySQL and never executes the dump against a
server.  It never reads global/installation settings from the old
application.

Modes
-----
``--dry-run``
    Parse the dump, resolve relationships, compute counts, and report
    unmapped/duplicate/unsupported/demo findings.  Performs **zero**
    database writes (the target database is not even opened).

``--import``
    Back up the target database, clear the current demo/test business
    data, then import the legacy data in controlled, batched
    transactions using migration-specific historical inserts — the
    application's PostingEngine is never replayed for historical data.

``--verify``
    Read-only reconciliation of the target database against the dump:
    integrity_check, foreign_key_check, counts, mappings and the stock
    reconciliation.

Safety
------
* Historical accounting is imported from the legacy accounting detail
  tables (``*vhdetail``) exactly as stored; nothing is recomputed.
* Legacy passwords (``userinfo.UserPassword``) are never imported.
* Demo sales (``demosales*``) are never imported.
* Production import additionally requires ``--confirm-production``.

The utility is developer/ADMIN-facing; the UI does not expose it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from database.connection import get_connection, get_db_path, init_database
from database import account_roles

# ══════════════════════════════════════════════════════════════════════
# Classification / mapping metadata (also drives the migration report)
# ══════════════════════════════════════════════════════════════════════

#: Legacy tables that contain demo data and must never be imported.
DEMO_TABLES: tuple[str, ...] = (
    "demosalesvhheader",
    "demosalesvhdetail",
    "demosalesitemdetail",
    "demosalescreditnote",
)

#: Legacy table → new target (report metadata; ``None`` = not mapped).
SOURCE_TARGETS: dict[str, str | None] = {
    # financial years / masters
    "acyear": "financial_years",
    "companymst": "companies",
    "unitmst": "units",
    "drugmst": "drugs",
    "doctormst": "doctors",
    "itemmst": "items",
    "itemdrugs": "item_ingredients",
    "pathymst": "items.pathy (value lookup)",
    "ledger": "account_ledgers",
    "ledgeropbal": "unsupported (per-FY opening balances)",
    "gpmst": "account_groups (classification)",
    "sundaryinfo": "customers / suppliers",
    # purchases
    "invoicevhheader": "purchase_invoices",
    "invoiceitemdetail": "purchase_invoice_items",
    "invoicevhdetail": "ledger_transactions",
    "invoicedebitnote": "unsupported (no allocation table)",
    "challanvhheader": "unsupported (challan document type)",
    "challanitemdetail": "unsupported (challan document type)",
    "entryinvoicevhmst": "unsupported (no data / draft-entry document)",
    "entryinvoicevhitem": "unsupported (no data / draft-entry document)",
    # sales
    "salesvhheader": "sales_invoices",
    "salesitemdetail": "sales_invoice_items",
    "salesvhdetail": "ledger_transactions",
    "salescreditnote": "unsupported (no allocation table)",
    "countersaleitems": "unsupported (headerless counter-sale lines)",
    # customer returns
    "creditnotevhheader": "credit_notes",
    "creditnoteitemdetail": "credit_note_items",
    "creditnotevhdetail": "ledger_transactions",
    # supplier returns
    "debitnotevhheader": "debit_notes",
    "debitnoteitemdetail": "debit_note_items",
    "debitnotevhdetail": "ledger_transactions",
    "invoicedebitnote": "unsupported (no allocation table)",
    # receipts / payments
    "receiptvhheader": "customer_receipts",
    "receiptvhdetail": "ledger_transactions",
    "receiptinvoice": "unsupported (no allocation table)",
    "paymentvhheader": "supplier_payments",
    "paymentvhdetail": "ledger_transactions",
    "paymentinvoice": "unsupported (no allocation table)",
    # journals
    "journalvhheader": "journal_entries",
    "journalvhdetail": "journal_entry_items",
    # stock
    "stockbalance": "stock_batches",
    "stockadjusted": "stock_batches (already reflected in stockbalance)",
    # misc / configuration
    "softmaster": "unsupported (firm profile — no target table)",
    "billsetting": "unsupported (print layout configuration)",
    "statemst": "customers.state / suppliers.state (value lookup)",
    "patientmaster": "patients (no target table; no data)",
    "sundrybillbybillopbal": "unsupported (bill-by-bill opening balances)",
    "accompany": "unsupported (legacy accounting company profile; no data)",
    "userinfo": "app_users (usernames only, opt-in, inactive)",
}

#: Reasons for unsupported legacy tables (report text).
UNSUPPORTED_TABLES: dict[str, str] = {
    "ledgeropbal": (
        "The new account_ledgers stores a single opening balance; the "
        "legacy per-financial-year/month opening-balance grid has no "
        "target. ledger.OpeningBal is preserved as the opening balance."
    ),
    "invoicedebitnote": "No allocation table exists in the new schema.",
    "salescreditnote": "No allocation table exists in the new schema.",
    "receiptinvoice": "No allocation table exists in the new schema.",
    "paymentinvoice": "No allocation table exists in the new schema.",
    "challanvhheader": "The new application has no challan document type.",
    "challanitemdetail": "The new application has no challan document type.",
    "entryinvoicevhmst": "Draft entry-invoice document; not mapped.",
    "entryinvoicevhitem": "Draft entry-invoice document; not mapped.",
    "countersaleitems": (
        "Headerless counter-sale lines dated before the first legacy "
        "financial year; no safe purchase/sale header to attach them to."
    ),
    "softmaster": "The new application has no firm-profile table.",
    "billsetting": "Legacy bill print-layout configuration; not migrated.",
    "patientmaster": "The new application has no patient master table.",
    "sundrybillbybillopbal": (
        "Bill-by-bill opening balances have no target in the new schema."
    ),
    "accompany": "Legacy accounting company profile; no target table.",
    "stockadjusted": (
        "Adjustments are already reflected in stockbalance totals "
        "(verified: batches exist whose TotalPurchaseQty equals their "
        "total adjustment with no purchases); imported as stock only."
    ),
}

#: Legacy account groups (gpmst.SGpHead) → new canonical account_group text.
LEGACY_GROUP_TEXT: dict[str, str] = {
    "CASH-IN-HAND": "Cash-in-Hand",
    "BANK ACCOUNTS": "Bank Accounts",
    "HDFC": "Bank Accounts",
    "SUNDRY DEBTORS": "Sundry Debtors",
    "SUNDRY CREDITORS": "Sundry Creditors",
    "SALES ACCOUNT": "Sales Accounts",
    "PURCHASE ACCOUNT": "Purchase Accounts",
}

#: Legacy system-ish groups that consolidate into a new system ledger role.
LEGACY_GROUP_TO_ROLE: dict[str, str] = {
    "CASH-IN-HAND": account_roles.ROLE_CASH,
    "SALES ACCOUNT": account_roles.ROLE_SALES,
    "PURCHASE ACCOUNT": account_roles.ROLE_PURCHASE,
}

#: Accounting detail table → (reference_type, voucher_type)
ACCOUNTING_SOURCES: dict[str, tuple[str, str]] = {
    "salesvhdetail": ("COUNTER_SALE", "SALE"),
    "invoicevhdetail": ("PURCHASE_INVOICE", "PURCHASE"),
    "creditnotevhdetail": ("CREDIT_NOTE", "CREDIT_NOTE"),
    "debitnotevhdetail": ("DEBIT_NOTE", "DEBIT_NOTE"),
    "receiptvhdetail": ("CUSTOMER_RECEIPT", "RECEIPT"),
    "paymentvhdetail": ("SUPPLIER_PAYMENT", "PAYMENT"),
}

#: Business tables cleared before the import, in dependency-safe order.
CLEAR_ORDER: tuple[str, ...] = (
    "sales_invoice_items", "sales_invoices",
    "credit_note_items", "credit_notes",
    "debit_note_items", "debit_notes",
    "purchase_invoice_items", "purchase_invoices",
    "supplier_payments", "customer_receipts",
    "journal_entry_items", "journal_entries",
    "ledger_transactions",
    "hold_bill_items", "hold_bills",
    "stock_batches",
    "item_ingredients", "items",
    "customers", "suppliers", "doctors", "drugs", "units",
    "companies", "categories",
    "import_history",
    "financial_years",
)

#: Tables that are never cleared (infrastructure / authentication).
PROTECTED_TABLES: tuple[str, ...] = (
    "app_users", "auth_audit_log", "account_groups", "account_ledgers",
    "legacy_id_map", "legacy_migration_meta", "sqlite_sequence",
)


class LegacyMigrationError(Exception):
    """Raised when the migration cannot proceed safely."""


# ══════════════════════════════════════════════════════════════════════
# MySQL dump parsing (offline, streaming)
# ══════════════════════════════════════════════════════════════════════

_INSERT_RE = re.compile(
    r"^\s*INSERT\s+INTO\s+`?([A-Za-z0-9_]+)`?"
    r"(?:\s*\(([^)]*)\))?\s*VALUES\s*(.*)$",
    re.I,
)
_CREATE_RE = re.compile(r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([A-Za-z0-9_]+)`?", re.I)
_COLUMN_RE = re.compile(r"^\s*`([^`]+)`\s+(.+)$")
_TRIGGER_RE = re.compile(r"TRIGGER\s+`", re.I)
#: MySQL identifiers that can never appear in a literal VALUES row.
_IDENTIFIER_RE = re.compile(r"^(NEW|OLD)\.[A-Za-z0-9_]+$", re.I)


def _column_list(raw: str | None) -> list[str]:
    """Parse an optional explicit INSERT column list."""
    if not raw:
        return []
    names = []
    for part in raw.split(","):
        name = part.strip().strip("`").strip()
        if name:
            names.append(name)
    return names


def _is_literal_row(raw: list[str]) -> bool:
    """True when every raw token is a literal (NULL / number / string).

    Trigger bodies contain expressions such as ``NEW.AcYearID`` which are
    not data rows; those are rejected here.
    """
    for token in raw:
        token = token.strip()
        if not token or token.upper() == "NULL" or token[0] == "'":
            continue
        if _IDENTIFIER_RE.match(token):
            return False
    return True


def _reorder(explicit: list[str], values: list, columns: list[str]) -> list:
    """Map an explicit column list onto the table's physical column order."""
    row = [None] * len(columns)
    for index, value in enumerate(values):
        if index >= len(explicit):
            break
        try:
            row[columns.index(explicit[index])] = value
        except ValueError:
            continue
    return row

# MySQL backslash escapes used by mysqldump.
_ESCAPES = {
    "0": "\0", "'": "'", '"': '"', "b": "\b", "n": "\n",
    "r": "\r", "t": "\t", "Z": "\x1a", "\\": "\\", "%": "%", "_": "_",
}


def decode_token(token: str):
    """Decode one MySQL VALUES token into a Python value.

    ``NULL`` → None, quoted strings are unescaped, numbers become
    int/float, anything else is returned verbatim.
    """
    token = token.strip()
    if not token:
        return ""
    if token.upper() == "NULL":
        return None
    if token[0] == "'":
        body = token[1:-1] if len(token) >= 2 and token[-1] == "'" else token[1:]
        out = []
        i = 0
        while i < len(body):
            char = body[i]
            if char == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                out.append(_ESCAPES.get(nxt, nxt))
                i += 2
                continue
            if char == "'" and i + 1 < len(body) and body[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            out.append(char)
            i += 1
        return "".join(out)
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        return token


def split_value_tuples(blob: str) -> list[list[str]]:
    """Split ``(a,b),(c,d)`` into a list of raw token lists.

    Quote- and escape-aware; string contents are never split.
    """
    tuples: list[list[str]] = []
    i = 0
    length = len(blob)
    while i < length:
        if blob[i] != "(":
            i += 1
            continue
        i += 1
        current: list[str] = []
        buffer: list[str] = []
        in_string = False
        while i < length:
            char = blob[i]
            if in_string:
                if char == "\\":
                    buffer.append(char)
                    i += 1
                    if i < length:
                        buffer.append(blob[i])
                        i += 1
                    continue
                buffer.append(char)
                i += 1
                if char == "'":
                    in_string = False
                continue
            if char == "'":
                in_string = True
                buffer.append(char)
                i += 1
                continue
            if char == ",":
                current.append("".join(buffer).strip())
                buffer = []
                i += 1
                continue
            if char == ")":
                current.append("".join(buffer).strip())
                buffer = []
                i += 1
                break
            buffer.append(char)
            i += 1
        if current:
            tuples.append(current)
    return tuples


class LegacyDump:
    """Streaming reader for a mysqldump file.

    The dump is never loaded into memory as a whole: schema discovery is
    one pass and rows are streamed per table on demand.
    """

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        if not self.path.is_file():
            raise LegacyMigrationError(f"SQL dump not found: {self.path}")
        self.size_bytes = self.path.stat().st_size
        self.table_columns: "OrderedDict[str, list[str]]" = OrderedDict()
        #: Line numbers that belong to TRIGGER definitions (their bodies
        #: contain INSERT statements that must never be treated as data).
        self.trigger_lines: set[int] = set()
        #: Rows skipped because their VALUES contained non-literal tokens.
        self.invalid_rows: list[dict] = []
        self._discover_schema()

    # ── construction ─────────────────────────────────────────────────
    @classmethod
    def from_text(cls, text: str, name: str = "<memory>") -> "LegacyDump":
        """Build an in-memory dump (used by tests)."""
        obj = cls.__new__(cls)
        obj.path = Path(name)
        obj.size_bytes = len(text)
        obj._memory_text = text
        obj.table_columns = OrderedDict()
        obj.trigger_lines = set()
        obj.invalid_rows = []
        obj._discover_schema_text(text)
        return obj

    def _open(self):
        if hasattr(self, "_memory_text"):
            import io

            return io.StringIO(self._memory_text)
        return self.path.open("r", encoding="utf-8", errors="replace")

    # ── schema ───────────────────────────────────────────────────────
    def _discover_schema(self) -> None:
        with self._open() as handle:
            self._discover_schema_stream(handle)

    def _discover_schema_text(self, text: str) -> None:
        import io

        self._discover_schema_stream(io.StringIO(text))

    def _discover_schema_stream(self, handle) -> None:
        capturing: list[str] = []
        depth = 0
        table = None
        in_trigger = False
        trigger_start = 0
        for lineno, line in enumerate(handle, 1):
            if in_trigger:
                # mysqldump terminates a trigger block with "DELIMITER ;"
                # (or a "*/;;" terminator in some versions).
                if "DELIMITER ;" in line or "*/;;" in line:
                    in_trigger = False
                    self.trigger_lines.update(range(trigger_start, lineno + 1))
                continue
            if _TRIGGER_RE.search(line):
                in_trigger = True
                trigger_start = lineno
                continue
            match = _CREATE_RE.match(line)
            if match and not capturing:
                table = match.group(1)
                capturing = [line]
                depth = line.count("(") - line.count(")")
                if depth <= 0:
                    self._finish_table(table, capturing)
                    capturing = []
                    table = None
                continue
            if capturing:
                capturing.append(line)
                depth += line.count("(") - line.count(")")
                if depth <= 0:
                    self._finish_table(table, capturing)
                    capturing = []
                    table = None

    def _finish_table(self, table: str, lines: list[str]) -> None:
        columns: list[str] = []
        for line in lines:
            match = _COLUMN_RE.match(line)
            if match:
                columns.append(match.group(1))
        self.table_columns[table] = columns

    # ── rows ─────────────────────────────────────────────────────────
    def iter_rows(self, table: str):
        """Yield decoded rows for ``table`` as lists (streaming).

        Rows from TRIGGER definition bodies and rows whose VALUES contain
        non-literal tokens are skipped (recorded in ``invalid_rows``).
        """
        columns = self.table_columns.get(table)
        with self._open() as handle:
            for lineno, line in enumerate(handle, 1):
                if lineno in self.trigger_lines:
                    continue
                if not line.lstrip().upper().startswith("INSERT INTO"):
                    continue
                match = _INSERT_RE.match(line)
                if not match or match.group(1) != table:
                    continue
                blob = match.group(3).strip()
                if blob.endswith(";"):
                    blob = blob[:-1]
                if not blob.startswith("("):
                    # e.g. INSERT ... SELECT inside a trigger body
                    continue
                explicit = _column_list(match.group(2))
                for raw in split_value_tuples(blob):
                    decoded = [decode_token(token) for token in raw]
                    if not _is_literal_row(raw):
                        if len(self.invalid_rows) < 200:
                            self.invalid_rows.append(
                                {"table": table, "line": lineno,
                                 "values": raw[:4]}
                            )
                        continue
                    if explicit and columns:
                        yield _reorder(explicit, decoded, columns)
                    else:
                        yield decoded

    def table_names(self) -> list[str]:
        return list(self.table_columns.keys())

    def count_rows(self) -> dict[str, int]:
        """Count data rows per table (single streaming pass)."""
        counts: dict[str, int] = defaultdict(int)
        for name in self.table_columns:
            counts[name] = 0
        with self._open() as handle:
            for lineno, line in enumerate(handle, 1):
                if lineno in self.trigger_lines:
                    continue
                if not line.lstrip().upper().startswith("INSERT INTO"):
                    continue
                match = _INSERT_RE.match(line)
                if not match:
                    continue
                blob = match.group(3).strip()
                if blob.endswith(";"):
                    blob = blob[:-1]
                if not blob.startswith("("):
                    continue
                counts[match.group(1)] += len(split_value_tuples(blob))
        return dict(counts)

    def sample(self, table: str, limit: int = 1) -> list[list]:
        rows = []
        for row in self.iter_rows(table):
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows


# ══════════════════════════════════════════════════════════════════════
# Inventory / dry-run planning
# ══════════════════════════════════════════════════════════════════════

@dataclass
class TablePlan:
    source: str
    target: str
    source_rows: int = 0
    demo: bool = False
    unsupported: bool = False
    note: str = ""


@dataclass
class DryRunPlan:
    dump_path: str
    dump_bytes: int
    tables: "OrderedDict[str, TablePlan]" = field(default_factory=OrderedDict)
    counts: dict[str, int] = field(default_factory=dict)
    findings: dict[str, list] = field(default_factory=lambda: defaultdict(list))
    demo_rows: int = 0
    total_rows: int = 0

    def summary(self) -> dict:
        return {
            "dump": self.dump_path,
            "dump_bytes": self.dump_bytes,
            "source_tables": len(self.tables),
            "source_rows": self.total_rows,
            "demo_rows_excluded": self.demo_rows,
            "unsupported_tables": [
                t.source for t in self.tables.values() if t.unsupported
            ],
            "findings": {k: len(v) for k, v in self.findings.items()},
        }


def build_plan(dump: LegacyDump) -> DryRunPlan:
    """Parse the dump and produce a full migration plan (no writes)."""
    started = time.time()
    counts = dump.count_rows()
    plan = DryRunPlan(dump_path=str(dump.path), dump_bytes=dump.size_bytes)
    plan.counts = counts

    for name in dump.table_names():
        rows = counts.get(name, 0)
        if name in DEMO_TABLES:
            plan.tables[name] = TablePlan(name, "excluded (demo)", rows, demo=True,
                                          note="Demo rows excluded.")
            plan.demo_rows += rows
            continue
        target = SOURCE_TARGETS.get(name, None)
        plan.tables[name] = TablePlan(
            name,
            target or "unsupported",
            rows,
            unsupported=(target is None or str(target).startswith("unsupported")),
            note=UNSUPPORTED_TABLES.get(name, ""),
        )
        plan.total_rows += rows

    _analyse_masters(dump, plan)
    _analyse_parties(dump, plan)
    _analyse_transactions(dump, plan)
    _analyse_stock(dump, plan)
    _analyse_financial_years(dump, plan)

    plan.findings["elapsed_seconds"].append(round(time.time() - started, 2))
    return plan


def _add(plan: DryRunPlan, key: str, item) -> None:
    plan.findings[key].append(item)


def _analyse_financial_years(dump: LegacyDump, plan: DryRunPlan) -> None:
    seen: dict[str, int] = {}
    for row in dump.iter_rows("acyear"):
        row_id, start, end, name = row[0], row[1], row[2], row[3]
        if name in seen:
            _add(plan, "duplicate_financial_years", {"id": row_id, "name": name})
        seen[name] = row_id
        if not start or not end or str(start) >= str(end) or str(end) <= str(start):
            _add(plan, "invalid_financial_years", {"id": row_id, "name": name})
    plan.counts["_financial_years_valid"] = len(seen)


def _analyse_masters(dump: LegacyDump, plan: DryRunPlan) -> None:
    item_ids = set()
    names: dict[str, list] = defaultdict(list)
    for row in dump.iter_rows("itemmst"):
        item_id = row[0]
        item_ids.add(item_id)
        name = (row[1] or "").strip()
        names[name.upper()].append(item_id)
    duplicates = {k: v for k, v in names.items() if len(v) > 1}
    for name, ids in duplicates.items():
        _add(plan, "duplicate_item_names", {"name": name, "legacy_ids": ids})
    plan.counts["_item_ids"] = len(item_ids)
    plan.counts["_duplicate_item_names"] = len(duplicates)

    unit_ids = {row[0] for row in dump.iter_rows("unitmst")}
    company_ids = {row[0] for row in dump.iter_rows("companymst")}
    pathy = {row[0]: row[1] for row in dump.iter_rows("pathymst")}
    scheme = {"unit": unit_ids, "company": company_ids}
    for row in dump.iter_rows("itemmst"):
        item_id = row[0]
        if row[2] not in unit_ids and row[2] is not None:
            _add(plan, "missing_item_unit", {"item_id": item_id, "unit_id": row[2]})
        if row[4] not in company_ids and row[4] is not None:
            _add(plan, "missing_item_company", {"item_id": item_id, "company_id": row[4]})
        if row[3] is not None and row[3] not in pathy:
            _add(plan, "missing_item_pathy", {"item_id": item_id, "pathy_id": row[3]})
    plan.counts["_unit_ids"] = len(unit_ids)
    plan.counts["_company_ids"] = len(company_ids)
    plan.counts["_pathy_values"] = len(pathy)

    drug_ids = {row[0] for row in dump.iter_rows("drugmst")}
    for row in dump.iter_rows("itemdrugs"):
        if row[1] not in item_ids:
            _add(plan, "ingredient_missing_item", {"id": row[0], "item_id": row[1]})
        if row[2] not in drug_ids:
            _add(plan, "ingredient_missing_drug", {"id": row[0], "drug_id": row[2]})
    plan.counts["_drug_ids"] = len(drug_ids)


def _analyse_parties(dump: LegacyDump, plan: DryRunPlan) -> None:
    groups = {row[0]: (row[1] or "").strip().upper() for row in dump.iter_rows("gpmst")}
    ledger_rows = list(dump.iter_rows("ledger"))
    plan.counts["_ledgers"] = len(ledger_rows)
    ledger_ids = {row[0] for row in ledger_rows}
    debtors = creditors = 0
    for row in ledger_rows:
        group = groups.get(row[2], "")
        if group == "SUNDRY DEBTORS":
            debtors += 1
        elif group == "SUNDRY CREDITORS":
            creditors += 1
    plan.counts["_debtor_ledgers"] = debtors
    plan.counts["_creditor_ledgers"] = creditors

    for row in dump.iter_rows("sundaryinfo"):
        if row[1] not in ledger_ids:
            _add(plan, "party_info_orphan", {"id": row[0], "ledger_id": row[1]})
    known_groups = {row[0] for row in dump.iter_rows("gpmst")}
    for row in ledger_rows:
        if row[2] not in known_groups:
            _add(plan, "ledger_unknown_group", {"id": row[0], "group_id": row[2]})


def _analyse_transactions(dump: LegacyDump, plan: DryRunPlan) -> None:
    item_ids = {row[0] for row in dump.iter_rows("itemmst")}
    ledger_ids = {row[0] for row in dump.iter_rows("ledger")}
    doctor_ids = {row[0] for row in dump.iter_rows("doctormst")}

    checks = (
        ("salesvhheader", "sales", {"item": None}),
        ("invoicevhheader", "purchases", {}),
    )
    sales_ids = set()
    unmapped_customers = set()
    for row in dump.iter_rows("salesvhheader"):
        sales_ids.add(row[0])
        if row[9] not in ledger_ids:
            unmapped_customers.add(row[9])
        if row[13] is not None and row[13] not in doctor_ids:
            _add(plan, "sale_missing_doctor", {"sale_id": row[0], "doctor_id": row[13]})
    for cust in sorted(unmapped_customers, key=lambda v: str(v)):
        _add(plan, "sale_missing_customer", {"legacy_customer_id": cust})
    plan.counts["_sales_headers"] = len(sales_ids)

    missing_sale_items = 0
    for row in dump.iter_rows("salesitemdetail"):
        if row[1] not in sales_ids:
            missing_sale_items += 1
        if row[2] not in item_ids:
            missing_sale_items += 1
    plan.counts["_sales_items_unresolved"] = missing_sale_items

    purchase_ids = set()
    unmapped_suppliers = set()
    for row in dump.iter_rows("invoicevhheader"):
        purchase_ids.add(row[0])
        if row[8] not in ledger_ids:
            unmapped_suppliers.add(row[8])
    for sup in sorted(unmapped_suppliers, key=lambda v: str(v)):
        _add(plan, "purchase_missing_supplier", {"legacy_supplier_id": sup})
    plan.counts["_purchase_headers"] = len(purchase_ids)

    missing_purchase_items = 0
    for row in dump.iter_rows("invoiceitemdetail"):
        if row[1] not in purchase_ids:
            missing_purchase_items += 1
        if row[2] not in item_ids:
            missing_purchase_items += 1
    plan.counts["_purchase_items_unresolved"] = missing_purchase_items

    for table, header_id_index in (
        ("creditnoteitemdetail", 1),
        ("debitnoteitemdetail", 1),
    ):
        header_table = "creditnotevhheader" if table.startswith("credit") else "debitnotevhheader"
        headers = {row[0] for row in dump.iter_rows(header_table)}
        missing = sum(1 for row in dump.iter_rows(table) if row[header_id_index] not in headers)
        plan.counts[f"_{table}_orphans"] = missing

    journal_headers = plan.counts.get("journalvhheader", 0)
    if journal_headers == 0:
        _add(plan, "no_journal_records", "No journal records to migrate.")

    # accounting detail coverage
    for table in ACCOUNTING_SOURCES:
        unmapped = 0
        for row in dump.iter_rows(table):
            if row[5] not in ledger_ids:
                unmapped += 1
        plan.counts[f"_{table}_unmapped_ledgers"] = unmapped


def _analyse_stock(dump: LegacyDump, plan: DryRunPlan) -> None:
    batches: dict[tuple, float] = {}
    for row in dump.iter_rows("stockbalance"):
        key = (row[0], row[1])
        qty = _number(row[6]) - _number(row[9])
        batches[key] = batches.get(key, 0.0) + qty
    plan.counts["_stock_batches"] = len(batches)
    negatives = {k: v for k, v in batches.items() if v < 0}
    plan.counts["_stock_negative"] = len(negatives)
    for key, qty in list(negatives.items())[:50]:
        _add(plan, "stock_negative_batches", {"item_id": key[0], "batch": key[1], "qty": qty})

    adjustments = 0
    adj_keys = set()
    for row in dump.iter_rows("stockadjusted"):
        adjustments += 1
        adj_keys.add((row[3], row[4]))
    plan.counts["_stock_adjustments"] = adjustments
    plan.counts["_stock_adjustment_keys"] = len(adj_keys)
    plan.counts["_stock_adjustment_keys_not_in_balance"] = len(adj_keys - set(batches))

    sales_batches = set()
    for row in dump.iter_rows("salesitemdetail"):
        sales_batches.add((row[2], row[4]))
    plan.counts["_sales_batches"] = len(sales_batches)
    plan.counts["_sales_batches_missing_from_stockbalance"] = len(
        sales_batches - set(batches)
    )


def _number(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ══════════════════════════════════════════════════════════════════════
# Report writers
# ══════════════════════════════════════════════════════════════════════

def plan_to_dict(plan: DryRunPlan) -> dict:
    return {
        "dump_path": plan.dump_path,
        "dump_bytes": plan.dump_bytes,
        "source_tables": len(plan.tables),
        "source_rows": plan.total_rows,
        "demo_rows_excluded": plan.demo_rows,
        "counts": plan.counts,
        "findings": {k: v for k, v in plan.findings.items()},
        "tables": [
            {
                "source": t.source,
                "target": t.target,
                "rows": t.source_rows,
                "demo": t.demo,
                "unsupported": t.unsupported,
                "note": t.note,
            }
            for t in plan.tables.values()
        ],
    }


def render_dry_run_markdown(plan: DryRunPlan) -> str:
    lines = [
        "# Legacy Migration — Dry Run",
        "",
        f"- Source dump: `{plan.dump_path}`",
        f"- Dump size: {plan.dump_bytes:,} bytes",
        f"- Source tables: {len(plan.tables)}",
        f"- Source data rows: {plan.total_rows:,}",
        f"- Demo rows excluded: {plan.demo_rows:,}",
        "",
        "## Table plan",
        "",
        "| Source table | Rows | Target | Status |",
        "| --- | ---: | --- | --- |",
    ]
    for table in plan.tables.values():
        if table.demo:
            status = "demo — excluded"
        elif table.unsupported:
            status = "unsupported"
        else:
            status = "mapped"
        lines.append(
            f"| `{table.source}` | {table.source_rows:,} | {table.target} | {status} |"
        )

    lines += ["", "## Findings", ""]
    for key in sorted(plan.findings):
        values = plan.findings[key]
        if key == "elapsed_seconds":
            continue
        lines.append(f"### {key} ({len(values)})")
        lines.append("")
        for item in values[:25]:
            lines.append(f"- {json.dumps(item, default=str)}")
        if len(values) > 25:
            lines.append(f"- … and {len(values) - 25} more")
        lines.append("")

    lines += [
        "## Compatibility notes",
        "",
        "- `ledgeropbal` (per-FY/month opening balances) has no target column; "
        "`ledger.OpeningBal` becomes the single opening balance.",
        "- `stockadjusted` is already reflected in `stockbalance` totals and is "
        "not summed again (no double counting).",
        "- `challan*`, `entryinvoice*`, `countersaleitems`, `*invoice`/`*creditnote` "
        "allocation tables, `softmaster`, `billsetting` and `patientmaster` have "
        "no target tables and are reported as unsupported.",
        "- Legacy `userinfo.UserPassword` is never imported.",
        "- Legacy numeric foreign keys are never reused as new ids; every master "
        "record is remapped.",
        "",
    ]
    return "\n".join(lines)


def write_dry_run_reports(plan: DryRunPlan, markdown_path: str,
                          json_path: str | None = None) -> dict:
    md_path = Path(markdown_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_dry_run_markdown(plan), encoding="utf-8")
    written = {"markdown": str(md_path)}
    if json_path:
        item = Path(json_path)
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text(json.dumps(plan_to_dict(plan), indent=2, default=str),
                        encoding="utf-8")
        written["json"] = str(item)
    return written


# ══════════════════════════════════════════════════════════════════════
# Import
# ══════════════════════════════════════════════════════════════════════

BATCH_SIZE = 1000

#: New canonical account groups used for parties.
GROUP_DEBTORS = "Sundry Debtors"
GROUP_CREDITORS = "Sundry Creditors"


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _pack(value) -> str:
    """Legacy PackSize is a smallint; the new column is text."""
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _date(value) -> str:
    value = _text(value)
    if value in ("0000-00-00", "0001-01-01"):
        return ""
    return value


@dataclass
class TableStats:
    source: str
    target: str
    source_rows: int = 0
    imported: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "source_rows": self.source_rows,
            "imported": self.imported,
            "skipped": self.skipped,
            "failed": self.failed,
        }


class LegacyMigrator:
    """Offline legacy → new SQLite migration engine."""

    def __init__(self, dump_path: str | os.PathLike[str], *,
                 db_path: str | None = None,
                 limit: int | None = None,
                 import_legacy_users: bool = False,
                 skip_stock: bool = False,
                 progress=None):
        self.dump = LegacyDump(dump_path)
        self.db_path = str(db_path) if db_path else get_db_path()
        # Every database helper in the application resolves its path
        # through PHARMACY_DB, so point it at the requested target.
        os.environ["PHARMACY_DB"] = self.db_path
        self.limit = limit
        self.import_legacy_users = import_legacy_users
        self.skip_stock = skip_stock
        self.progress = progress
        self.stats: "OrderedDict[str, TableStats]" = OrderedDict()
        self.warnings: list[dict] = []
        self.maps: dict[str, dict] = defaultdict(dict)
        self.pre_state: dict = {}
        self.post_state: dict = {}
        self.backup: dict | None = None
        self.conn: sqlite3.Connection | None = None
        self._existing_items: dict[str, int] = {}
        self._existing_ledgers: dict[str, int] = {}
        self._batch_cache: dict[tuple, int] = {}
        self._duplicates: list[dict] = []
        self._extra_batches = 0
        self._stock_loaded = False
        self._unsupported_fields: dict[str, int] = defaultdict(int)
        self._voucher_seen: set[str] = set()
        self._fy_map: dict[int, str] = {}

    # ── small helpers ────────────────────────────────────────────────
    def _stats(self, source: str) -> TableStats:
        if source not in self.stats:
            self.stats[source] = TableStats(source, SOURCE_TARGETS.get(source) or "unsupported")
        return self.stats[source]

    def _rows(self, source: str, *, target: str | None = None):
        stats = self._stats(source)
        if target:
            stats.target = target
        for index, row in enumerate(self.dump.iter_rows(source)):
            if self.limit and index >= self.limit:
                break
            stats.source_rows += 1
            yield row

    def _warn(self, kind: str, detail: str, **extra) -> None:
        self.warnings.append({"kind": kind, "detail": detail, **extra})

    def _note_unsupported(self, field: str) -> None:
        self._unsupported_fields[field] += 1

    def _table_exists(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def _table_count(self, name: str) -> int:
        if not self._table_exists(name):
            return 0
        return self.conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]

    def _unique_voucher(self, base: str, legacy_id) -> str:
        candidate = base
        if candidate in self._voucher_seen:
            candidate = f"{base}#{legacy_id}"
        self._voucher_seen.add(candidate)
        return candidate

    def _get_or_create(self, table: str, key_col: str, key_value: str,
                      columns: dict) -> int:
        cache_name = f"__{table}"
        cache: dict = self.maps.setdefault(cache_name, {})
        cached = cache.get(key_value)
        if cached is not None:
            return cached
        row = self.conn.execute(
            f'SELECT id FROM "{table}" WHERE {key_col} = ?', (key_value,)
        ).fetchone()
        if row:
            cache[key_value] = row[0]
            return row[0]
        names = [key_col] + list(columns.keys())
        placeholders = ", ".join("?" for _ in names)
        cur = self.conn.execute(
            f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({placeholders})',
            [key_value] + list(columns.values()),
        )
        new_id = cur.lastrowid
        cache[key_value] = new_id
        return new_id

    def _insert_or_merge(self, source: str, table: str, key_col: str,
                         key_value: str, columns: dict, legacy_id):
        """Insert unique master data, merging duplicate legacy names.

        Returns ``(new_id, created)``.  A legacy name that maps onto an
        already-imported record is merged (never silently dropped) and
        recorded in the report.
        """
        cache: dict = self.maps.setdefault(f"__{table}", {})
        existing = cache.get(key_value)
        if existing is None:
            row = self.conn.execute(
                f'SELECT id FROM "{table}" WHERE {key_col} = ?', (key_value,)
            ).fetchone()
            existing = row[0] if row else None
        if existing is not None:
            cache[key_value] = existing
            self._note_duplicate(source, legacy_id, key_value, existing)
            return existing, False
        return self._get_or_create(table, key_col, key_value, columns), True

    def _note_duplicate(self, source: str, legacy_id, name: str, new_id: int) -> None:
        self._duplicates.append(
            {"source": source, "legacy_id": legacy_id, "name": name,
             "merged_into": new_id}
        )

    def _get_or_create_unique(self, source: str, table: str, key_col: str,
                              key_value: str, columns: dict,
                              legacy_id) -> int:
        """Insert unique master data, recording duplicate legacy names."""
        new_id, created = self._insert_or_merge(
            source, table, key_col, key_value, columns, legacy_id
        )
        if not created:
            self._warn("duplicate_master_name",
                       f"{source}: '{key_value}' legacy id {legacy_id} "
                       f"merged into {new_id}")
        return new_id

    # ── public API ───────────────────────────────────────────────────
    def import_data(self, *, do_backup: bool = True,
                    backup_dir: str | None = None) -> dict:
        """Back up, clear demo business data, then import the legacy data."""
        init_database()
        from database import auth

        auth.ensure_auth_schema()
        self.conn = get_connection()
        try:
            self.pre_state = database_state(self.conn)
            if do_backup and self._table_exists("companies"):
                self.backup = self._create_backup(backup_dir)
            self._clear_business_data()
            self._prepare_configuration()
            self._import_all()
            self._finalize()
            self.post_state = database_state(self.conn)
        finally:
            self.conn.close()
            self.conn = None
        return self.report()

    def _create_backup(self, backup_dir: str | None) -> dict:
        from database import backup_restore

        destination = backup_dir or os.path.join(
            os.path.dirname(os.path.abspath(self.db_path)), "backups"
        )
        info = backup_restore.create_backup(destination, record_last=False)
        validation = backup_restore.validate_backup(info["path"])
        if not validation.get("valid"):
            raise LegacyMigrationError(
                f"Pre-migration backup failed validation: {validation.get('reason')}"
            )
        return {**info, "validated": True, "integrity": validation.get("integrity")}

    # ── clearing ─────────────────────────────────────────────────────
    def _clear_business_data(self) -> dict:
        cleared: dict[str, int] = {}
        for table in CLEAR_ORDER:
            if not self._table_exists(table):
                continue
            count = self._table_count(table)
            if count:
                self.conn.execute(f'DELETE FROM "{table}"')
                cleared[table] = count
        # Ledgers: keep system-role ledgers; remove demo/business ledgers.
        if self._table_exists("account_ledgers"):
            cur = self.conn.execute(
                "DELETE FROM account_ledgers WHERE system_role IS NULL"
            )
            if cur.rowcount:
                cleared["account_ledgers"] = cur.rowcount
        # Non-system account groups only; structured groups are preserved.
        if self._table_exists("account_groups"):
            cur = self.conn.execute("DELETE FROM account_groups WHERE COALESCE(is_system,0)=0")
            if cur.rowcount:
                cleared["account_groups"] = cur.rowcount
        self.conn.commit()
        self.cleared = cleared
        return cleared

    # ── configuration ────────────────────────────────────────────────
    def _prepare_configuration(self) -> None:
        account_roles.ensure_account_groups()
        account_roles.ensure_system_ledgers()
        from database.ledger_dao import LedgerDAO

        self.role_ledger: dict[str, int] = {}
        for role in account_roles.REQUIRED_ROLES:
            ledger = LedgerDAO.get_by_system_role(role)
            if ledger:
                self.role_ledger[role] = ledger["id"]

    # ── orchestration ────────────────────────────────────────────────
    def _import_all(self) -> None:
        self._import_financial_years()
        self._import_companies()
        self._import_units()
        self._import_drugs()
        self._import_doctors()
        self._import_items()
        self._import_item_ingredients()
        self._import_ledgers_and_parties()
        if self.skip_stock:
            # Staging transaction migration: defer stockbalance/stockadjusted
            # to a separate phase. History-only batches (qty 0) are still
            # created via _ensure_batch for FK linkage; no quantities set.
            stats = self._stats("stockbalance")
            stats.target = "stock_batches (deferred — separate phase)"
            stats.source_rows = self.dump.count_rows().get("stockbalance", 0)
            stats.imported = 0
            stats.skipped = stats.source_rows
            self._warn("stock_deferred_to_separate_phase",
                       f"{stats.source_rows} stockbalance rows deferred")
            stats2 = self._stats("stockadjusted")
            stats2.target = "stock_batches (already reflected; deferred)"
            stats2.source_rows = self.dump.count_rows().get("stockadjusted", 0)
            stats2.imported = 0
            stats2.skipped = stats2.source_rows
        else:
            self._import_stock_balance()
        self._import_purchases()
        self._import_sales()
        self._import_credit_notes()
        self._import_debit_notes()
        self._import_receipts()
        self._import_payments()
        if self.import_legacy_users:
            self._import_legacy_usernames()

    # ══════════════════════════════════════════════════════════════════
    # Masters
    # ══════════════════════════════════════════════════════════════════
    def _import_financial_years(self) -> None:
        import datetime as _dt

        stats = self._stats("acyear")
        stats.target = "financial_years"
        rows = []
        for row in self._rows("acyear"):
            name = _text(row[3])
            start, end = _date(row[1]), _date(row[2])
            if not name or not start or not end:
                stats.skipped += 1
                self._warn("invalid_financial_year", name or str(row[0]))
                continue
            rows.append((row[0], name, start, end))
            self._fy_map[row[0]] = name
        today = _dt.date.today().isoformat()
        active_name = None
        for _legacy, name, start, end in rows:
            if start <= today <= end:
                active_name = name
        if active_name is None and rows:
            active_name = sorted(rows, key=lambda r: r[2])[-1][1]
        for legacy_id, name, start, end in rows:
            if self.conn.execute(
                "SELECT 1 FROM financial_years WHERE name = ?", (name,)
            ).fetchone():
                existing = self.conn.execute(
                    "SELECT id FROM financial_years WHERE name = ?", (name,)
                ).fetchone()
                self.maps["financial_year"][legacy_id] = existing[0]
                stats.skipped += 1
                continue
            cur = self.conn.execute(
                "INSERT INTO financial_years (name, start_date, end_date, is_active, created_at)"
                " VALUES (?, ?, ?, ?, datetime('now'))",
                (name, start, end, 1 if name == active_name else 0),
            )
            self.maps["financial_year"][legacy_id] = cur.lastrowid
            stats.imported += 1
        self.conn.commit()

    def _import_companies(self) -> None:
        for row in self._rows("companymst", target="companies"):
            stats = self._stats("companymst")
            name = _text(row[1])
            if not name:
                stats.skipped += 1
                self._warn("empty_company_name", f"legacy id {row[0]}")
                continue
            new_id, created = self._insert_or_merge(
                "companymst", "companies", "company_name", name,
                {"short_name": _text(row[2])[:10]}, row[0],
            )
            self.maps["company"][row[0]] = new_id
            if created:
                stats.imported += 1
            else:
                stats.skipped += 1
                self._warn("duplicate_company_name",
                           f"'{name}' legacy id {row[0]} merged into {new_id}")
        self.conn.commit()

    def _import_units(self) -> None:
        for row in self._rows("unitmst", target="units"):
            stats = self._stats("unitmst")
            name = _text(row[1])
            if not name:
                stats.skipped += 1
                self._warn("empty_unit_name", f"legacy id {row[0]}")
                continue
            new_id, created = self._insert_or_merge(
                "unitmst", "units", "unit_name", name, {}, row[0]
            )
            self.maps["unit"][row[0]] = new_id
            if created:
                stats.imported += 1
            else:
                stats.skipped += 1
                self._warn("duplicate_unit_name",
                           f"'{name}' legacy id {row[0]} merged into {new_id}")
        self.conn.commit()

    def _import_drugs(self) -> None:
        for row in self._rows("drugmst", target="drugs"):
            stats = self._stats("drugmst")
            name = _text(row[1])
            if not name:
                stats.skipped += 1
                self._warn("empty_drug_name", f"legacy id {row[0]}")
                continue
            new_id, created = self._insert_or_merge(
                "drugmst", "drugs", "drug_name", name, {}, row[0]
            )
            self.maps["drug"][row[0]] = new_id
            if created:
                stats.imported += 1
            else:
                stats.skipped += 1
                self._warn("duplicate_drug_name",
                           f"'{name}' legacy id {row[0]} merged into {new_id}")
        self.conn.commit()

    def _import_doctors(self) -> None:
        for row in self._rows("doctormst", target="doctors"):
            stats = self._stats("doctormst")
            name = _text(row[1])
            if not name:
                stats.skipped += 1
                self._warn("empty_doctor_name", f"legacy id {row[0]}")
                continue
            new_id, created = self._insert_or_merge(
                "doctormst", "doctors", "doctor_name", name,
                {
                    "specialty": _text(row[2]),
                    "city": _text(row[3]),
                    "phone_no": _text(row[4]),
                }, row[0],
            )
            self.maps["doctor"][row[0]] = new_id
            if created:
                stats.imported += 1
            else:
                stats.skipped += 1
                self._warn("duplicate_doctor_name",
                           f"'{name}' legacy id {row[0]} merged into {new_id}")
        self.conn.commit()

    def _import_items(self) -> None:
        pathy = {row[0]: _text(row[1]) for row in self.dump.iter_rows("pathymst")}
        for row in self._rows("itemmst", target="items"):
            stats = self._stats("itemmst")
            legacy_id = row[0]
            name = _text(row[1])
            if not name:
                stats.skipped += 1
                self._warn("empty_item_name", f"legacy id {legacy_id}")
                continue
            # SellLoose / BillCompulsory have no target column.
            if _text(row[13]):
                self._note_unsupported("itemmst.SellLoose")
            if _text(row[14]):
                self._note_unsupported("itemmst.BillCompulsory")
            existing = self._existing_items.get(name.upper())
            if existing:
                self.maps["item"][legacy_id] = existing
                self._note_duplicate("itemmst", legacy_id, name, existing)
                stats.skipped += 1
                self._warn("duplicate_item_name",
                           f"'{name}' legacy id {legacy_id} merged into {existing}")
                continue
            cur = self.conn.execute(
                """INSERT INTO items (
                       item_name, unit_id, company_id, category_id, pack_size,
                       tax_structure, discount, mrp, rate, reorder_stock_level,
                       scheduled, location, pathy, dpco)
                   VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name,
                    self.maps["unit"].get(row[2]),
                    self.maps["company"].get(row[4]),
                    _pack(row[5]),
                    _text(row[10]),
                    _number(row[6]),
                    _number(row[9]),
                    _number(row[8]),
                    int(_number(row[7])),
                    _text(row[12]),
                    _text(row[11]),
                    pathy.get(row[3], ""),
                    _text(row[15]),
                ),
            )
            new_id = cur.lastrowid
            self.maps["item"][legacy_id] = new_id
            self._existing_items[name.upper()] = new_id
            stats.imported += 1
        self.conn.commit()

    def _import_item_ingredients(self) -> None:
        seen = set()
        for row in self._rows("itemdrugs", target="item_ingredients"):
            stats = self._stats("itemdrugs")
            item_id = self.maps["item"].get(row[1])
            drug_id = self.maps["drug"].get(row[2])
            if item_id is None or drug_id is None:
                stats.skipped += 1
                self._warn("ingredient_unmapped",
                           f"item={row[1]} drug={row[2]}")
                continue
            key = (item_id, drug_id)
            if key in seen:
                stats.skipped += 1
                continue
            seen.add(key)
            self.conn.execute(
                "INSERT INTO item_ingredients (item_id, drug_id, power) VALUES (?, ?, ?)",
                (item_id, drug_id, _text(row[3])),
            )
            stats.imported += 1
        self.conn.commit()

    # ══════════════════════════════════════════════════════════════════
    # Ledgers, customers, suppliers
    # ══════════════════════════════════════════════════════════════════
    def _import_ledgers_and_parties(self) -> None:
        stats = self._stats("ledger")
        stats.target = "account_ledgers"
        groups = {row[0]: _text(row[1]).upper() for row in self.dump.iter_rows("gpmst")}
        info_rows = list(self.dump.iter_rows("sundaryinfo"))
        info_by_ledger = {row[1]: row for row in info_rows}
        states = {row[0]: _text(row[1]) for row in self.dump.iter_rows("statemst")}
        ledger_rows = list(self.dump.iter_rows("ledger"))
        stats.source_rows = len(ledger_rows)

        # Pick the busiest legacy bank ledger for the new BANK role.
        bank_counts: dict = defaultdict(int)
        for row in ledger_rows:
            if groups.get(row[2], "") in ("BANK ACCOUNTS", "HDFC"):
                bank_counts[row[0]] = 0
        if bank_counts:
            for row in self.dump.iter_rows("paymentvhdetail"):
                if row[5] in bank_counts:
                    bank_counts[row[5]] += 1
            for row in self.dump.iter_rows("receiptvhdetail"):
                if row[5] in bank_counts:
                    bank_counts[row[5]] += 1
            for row in self.dump.iter_rows("invoicevhdetail"):
                if row[5] in bank_counts:
                    bank_counts[row[5]] += 1
            for row in self.dump.iter_rows("salesvhdetail"):
                if row[5] in bank_counts:
                    bank_counts[row[5]] += 1
        primary_bank = max(bank_counts, key=lambda k: bank_counts[k]) if bank_counts else None

        for row in ledger_rows:
            legacy_id = row[0]
            name = _text(row[1])
            if not name:
                stats.skipped += 1
                continue
            group = groups.get(row[2], "")
            opening = _number(row[4])
            info = info_by_ledger.get(legacy_id)
            payload = {
                "account_group": LEGACY_GROUP_TEXT.get(group, group.title()),
                "opening_balance": abs(opening),
                "opening_balance_type": "Debit" if opening >= 0 else "Credit",
                "discount": _number(info[4]) if info else 0.0,
                "credit_limit": _number(info[5]) if info else 0.0,
                "credit_period": int(_number(info[6])) if info else 0,
                "address": _text(info[7]) if info else "",
                "city": _text(info[8]) if info else "",
                "state": states.get(info[9], "") if info else "",
                "contact_person": _text(info[10]) if info else "",
                "contact_no": _text(info[11]) if info else "",
                "tax_no": (_text(info[2]) or _text(info[3])) if info else "",
            }

            role = LEGACY_GROUP_TO_ROLE.get(group)
            if group in ("BANK ACCOUNTS", "HDFC"):
                role = account_roles.ROLE_BANK if legacy_id == primary_bank else None
            if role and role in self.role_ledger:
                if group == "CASH-IN-HAND" or role != account_roles.ROLE_BANK:
                    self.maps["ledger"][legacy_id] = self.role_ledger[role]
                    stats.skipped += 1
                    self._warn("ledger_merged_into_system_role",
                               f"'{name}' → role {role}")
                    self._note_duplicate("ledger", legacy_id, name,
                                         self.role_ledger[role])
                    continue
                # Non-primary bank ledgers keep their own ledger.
            if role == account_roles.ROLE_BANK and role in self.role_ledger:
                # Map the primary bank ledger onto the BANK role ledger,
                # preserving its name in the ledger list.
                self.conn.execute(
                    "UPDATE account_ledgers SET ledger_name = ? WHERE id = ?",
                    (name, self.role_ledger[role]),
                )
                self._existing_ledgers[name.upper()] = self.role_ledger[role]
                self.maps["ledger"][legacy_id] = self.role_ledger[role]
                stats.skipped += 1
                self._warn("ledger_merged_into_system_role",
                           f"'{name}' → role {role} (primary bank account)")
                self._note_duplicate("ledger", legacy_id, name,
                                     self.role_ledger[role])
                continue

            existing = self._existing_ledgers.get(name.upper())
            if existing is None:
                existing = self.conn.execute(
                    "SELECT id FROM account_ledgers WHERE ledger_name = ?", (name,)
                ).fetchone()
                existing = existing[0] if existing else None
            if existing is not None:
                self.maps["ledger"][legacy_id] = existing
                stats.skipped += 1
                self._warn("ledger_name_reused",
                           f"'{name}' reused existing ledger {existing}")
                self._note_duplicate("ledger", legacy_id, name, existing)
                continue
            cur = self.conn.execute(
                """INSERT INTO account_ledgers (
                       ledger_name, account_group, opening_balance,
                       opening_balance_type, discount, credit_limit,
                       credit_period, address, city, state, contact_person,
                       contact_no, tax_no)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, payload["account_group"], payload["opening_balance"],
                 payload["opening_balance_type"], payload["discount"],
                 payload["credit_limit"], payload["credit_period"],
                 payload["address"], payload["city"], payload["state"],
                 payload["contact_person"], payload["contact_no"],
                 payload["tax_no"]),
            )
            new_id = cur.lastrowid
            self._existing_ledgers[name.upper()] = new_id
            self.maps["ledger"][legacy_id] = new_id
            stats.imported += 1

        # ── customers (SUNDRY DEBTORS) and suppliers (SUNDRY CREDITORS) ──
        cust_stats = self._stats("sundaryinfo")
        cust_stats.target = "customers / suppliers"
        cust_stats.source_rows = len(info_rows)
        for row in ledger_rows:
            legacy_id = row[0]
            name = _text(row[1])
            group = groups.get(row[2], "")
            if not name or legacy_id not in self.maps["ledger"]:
                continue
            ledger_id = self.maps["ledger"][legacy_id]
            info = info_by_ledger.get(legacy_id)
            opening = _number(row[4])
            if group == "SUNDRY DEBTORS":
                existing = self.conn.execute(
                    "SELECT id FROM customers WHERE customer_name = ?", (name,)
                ).fetchone()
                if existing:
                    new_id = existing[0]
                    cust_stats.skipped += 1
                else:
                    cur = self.conn.execute(
                        """INSERT INTO customers (
                               customer_name, city, contact_person, contact_no,
                               address, state, discount, credit_limit,
                               credit_period, opening_balance, ledger_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (name,
                         _text(info[8]) if info else "",
                         _text(info[10]) if info else "",
                         _text(info[11]) if info else "",
                         _text(info[7]) if info else "",
                         states.get(info[9], "") if info else "",
                         _number(info[4]) if info else 0.0,
                         _number(info[5]) if info else 0.0,
                         int(_number(info[6])) if info else 0,
                         opening,
                         ledger_id),
                    )
                    new_id = cur.lastrowid
                    cust_stats.imported += 1
                self.maps["customer_ledger"][legacy_id] = new_id
                self.maps["customer_by_ledger"][legacy_id] = new_id
            elif group == "SUNDRY CREDITORS":
                existing = self.conn.execute(
                    "SELECT id FROM suppliers WHERE supplier_name = ?", (name,)
                ).fetchone()
                if existing:
                    new_id = existing[0]
                    cust_stats.skipped += 1
                else:
                    cur = self.conn.execute(
                        """INSERT INTO suppliers (
                               supplier_name, sales_tax_no, vat_or_tin, city,
                               contact_person, contact_no, address, state,
                               discount, credit_limit, credit_period,
                               vat_tin, opening_balance, ledger_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (name,
                         _text(info[2]) if info else "",
                         _text(info[3]) if info else "",
                         _text(info[8]) if info else "",
                         _text(info[10]) if info else "",
                         _text(info[11]) if info else "",
                         _text(info[7]) if info else "",
                         states.get(info[9], "") if info else "",
                         _number(info[4]) if info else 0.0,
                         _number(info[5]) if info else 0.0,
                         int(_number(info[6])) if info else 0,
                         _text(info[3]) if info else "",
                         opening,
                         ledger_id),
                    )
                    new_id = cur.lastrowid
                    cust_stats.imported += 1
                self.maps["supplier_by_ledger"][legacy_id] = new_id
        self.conn.commit()
        account_roles.migrate_legacy_ledger_groups()

    # ══════════════════════════════════════════════════════════════════
    # Stock
    # ══════════════════════════════════════════════════════════════════
    def _ensure_batch(self, item_id: int | None, batch_no: str, *,
                      expiry: str = "", pack_size: str = "", mrp: float = 0.0,
                      rate: float = 0.0, net_rate: float = 0.0) -> int | None:
        if item_id is None or not batch_no:
            return None
        key = (item_id, batch_no)
        cached = self._batch_cache.get(key)
        if cached is not None:
            return cached
        row = self.conn.execute(
            "SELECT id FROM stock_batches WHERE item_id = ? AND batch_no = ?",
            key,
        ).fetchone()
        if row:
            self._batch_cache[key] = row[0]
            return row[0]
        cur = self.conn.execute(
            """INSERT INTO stock_batches
                   (item_id, batch_no, expiry, pack_size, mrp,
                    purchase_rate, net_rate, stock_qty)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (item_id, batch_no, expiry, pack_size, mrp, rate, net_rate),
        )
        if getattr(self, "_stock_loaded", False):
            # Batch referenced by a historical transaction but absent from
            # stockbalance (zero stock) — created for history linkage.
            self._extra_batches += 1
        self._batch_cache[key] = cur.lastrowid
        return cur.lastrowid

    def _import_stock_balance(self) -> None:
        stats = self._stats("stockbalance")
        stats.target = "stock_batches"
        seen: set = set()
        for row in self._rows("stockbalance"):
            item_id = self.maps["item"].get(row[0])
            batch_no = _text(row[1])
            if item_id is None or not batch_no:
                stats.skipped += 1
                self._warn("stock_unmapped", f"item={row[0]} batch={row[1]}")
                continue
            key = (item_id, batch_no)
            if key in seen:
                # The legacy table has no unique key: duplicate (item,
                # batch) rows are merged into one batch (quantities summed).
                stats.skipped += 1
                self._warn("duplicate_stock_balance_row",
                           f"item={row[0]} batch={batch_no}")
                existing = self.conn.execute(
                    "SELECT id, stock_qty FROM stock_batches WHERE item_id = ? AND batch_no = ?",
                    key,
                ).fetchone()
                if existing:
                    self.conn.execute(
                        "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                        (_number(row[6]) - _number(row[9]), existing[0]),
                    )
                continue
            seen.add(key)
            qty = _number(row[6]) - _number(row[9])
            key = (item_id, batch_no)
            existing = self.conn.execute(
                "SELECT id, stock_qty FROM stock_batches WHERE item_id = ? AND batch_no = ?",
                key,
            ).fetchone()
            if existing:
                self.conn.execute(
                    "UPDATE stock_batches SET stock_qty = ? WHERE id = ?",
                    (qty, existing[0]),
                )
                self._batch_cache[key] = existing[0]
            else:
                cur = self.conn.execute(
                    """INSERT INTO stock_batches
                           (item_id, batch_no, expiry, pack_size, mrp,
                            purchase_rate, net_rate, stock_qty)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item_id, batch_no, _date(row[2]), _pack(row[7]),
                     _number(row[3]), _number(row[4]), _number(row[5]),
                     qty),
                )
                self._batch_cache[key] = cur.lastrowid
            stats.imported += 1
        self._stock_loaded = True
        self.conn.commit()

    # ══════════════════════════════════════════════════════════════════
    # Purchases
    # ══════════════════════════════════════════════════════════════════
    def _import_purchases(self) -> None:
        headers = self._stats("invoicevhheader")
        headers.target = "purchase_invoices"
        vouchers: dict = {}
        for row in self._rows("invoicevhheader"):
            legacy_id = row[0]
            fy_name = self._fy_map.get(row[1], "")
            voucher_no = self._unique_voucher(
                f"{fy_name}-{_text(row[2])}-{row[3]}", legacy_id
            )
            supplier_id = self.maps["supplier_by_ledger"].get(row[8])
            if supplier_id is None:
                headers.skipped += 1
                self._warn("purchase_missing_supplier",
                           f"legacy id {legacy_id} supplier ledger {row[8]}")
                continue
            cur = self.conn.execute(
                """INSERT INTO purchase_invoices (
                       voucher_no, voucher_date, voucher_time, purchase_type,
                       supplier_id, invoice_no, invoice_date,
                       invoice_net_amount, bill_discount, due_date,
                       total_amount, gst_amount, debit_note_amount,
                       other_amount, paid_amount, round_off, net_amount,
                       remarks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (voucher_no, _date(row[4]), _text(row[5]), _text(row[2]) or "Credit",
                 supplier_id, _text(row[9]), _date(row[10]),
                 _number(row[12]), _number(row[15]), _date(row[11]),
                 _number(row[12]), _number(row[19]), _number(row[17]),
                 _number(row[18]), _number(row[20]), _number(row[16]),
                 _number(row[7]), _text(row[6])),
            )
            new_id = cur.lastrowid
            self.maps["purchase"][legacy_id] = new_id
            vouchers[legacy_id] = (new_id, voucher_no, _date(row[4]), _text(row[5]))
            headers.imported += 1
        self.conn.commit()
        self.purchase_vouchers = vouchers

        items = self._stats("invoiceitemdetail")
        items.target = "purchase_invoice_items"
        for row in self._rows("invoiceitemdetail"):
            invoice_id = self.maps["purchase"].get(row[1])
            item_id = self.maps["item"].get(row[2])
            if invoice_id is None or item_id is None:
                items.skipped += 1
                self._warn("purchase_item_unmapped",
                           f"vh={row[1]} item={row[2]}")
                continue
            self._ensure_batch(
                item_id, _text(row[3]), expiry=_date(row[5]),
                pack_size=_pack(row[4]), mrp=_number(row[11]),
                rate=_number(row[10]), net_rate=_number(row[19]),
            )
            self.conn.execute(
                """INSERT INTO purchase_invoice_items (
                       purchase_invoice_id, item_id, pack_size, pay_qty,
                       free_qty, batch_no, expiry, rate, mrp, discount,
                       gst_percent, gst_amount, amount, purchase_rate,
                       net_rate, pp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (invoice_id, item_id, _pack(row[4]), _number(row[6]),
                 _number(row[7]), _text(row[3]), _date(row[5]),
                 _number(row[10]), _number(row[11]), _number(row[14]),
                 _number(row[16]), _number(row[17]), _number(row[15]),
                 _number(row[18]), _number(row[19])),
            )
            items.imported += 1
        self.conn.commit()
        self._import_accounting("invoicevhdetail", self.maps["purchase"],
                                vouchers)

    # ══════════════════════════════════════════════════════════════════
    # Sales
    # ══════════════════════════════════════════════════════════════════
    def _import_sales(self) -> None:
        headers = self._stats("salesvhheader")
        headers.target = "sales_invoices"
        # BillNo preservation counters (staging approval: preserve original
        # BillNo whenever present; never invent or silently discard).
        preserved = getattr(self, "_sales_bill_preserved", 0)
        fallback_missing = getattr(self, "_sales_bill_fallback_missing", 0)
        collisions = getattr(self, "_sales_bill_collisions", 0)
        vouchers: dict = {}
        for row in self._rows("salesvhheader"):
            legacy_id = row[0]
            fy_name = self._fy_map.get(row[1], "")
            bill_raw = row[8]
            bill_str = str(bill_raw).strip() if bill_raw is not None else ""
            if bill_str in ("", "0", "0.0"):
                # Missing BillNo: stable fallback containing source table
                # identity (S + legacy ID). Never invents a BillNo and never
                # collides (legacy ID unique). Listed, not discarded.
                base = f"{fy_name}-{_text(row[2])}-{row[3]}-S{legacy_id}"
                fallback_missing += 1
                if fallback_missing <= 50:
                    self._warn("sale_bill_missing_fallback",
                               f"legacy id {legacy_id} BillNo={bill_raw!r} "
                               f"fallback {base}")
            else:
                # Preserve original BillNo with FY prefix for global
                # uniqueness (BillNo repeats across years). Idempotent:
                # same legacy row always yields same base; residual
                # collisions get deterministic #legacy_id suffix.
                base = f"{fy_name}-{bill_str}"
                preserved += 1
            will_collide = base in self._voucher_seen
            voucher_no = self._unique_voucher(base, legacy_id)
            if will_collide:
                collisions += 1
                if collisions <= 50:
                    self._warn("sale_bill_collision_suffix",
                               f"legacy id {legacy_id} base {base} "
                               f"stored {voucher_no}")
            # Provenance is kept in remarks so the original numbers are never
            # lost even when a suffix is required for uniqueness.
            provenance = (
                f"Legacy salesvhheader ID {legacy_id}; "
                f"Vh {_text(row[2])} {row[3]}; BillNo "
                f"{bill_str if bill_str else '(missing)'}"
            )
            narration = _text(row[6])
            remarks = provenance + (f"; {narration}" if narration else "")
            customer_id = self.maps["customer_by_ledger"].get(row[9])
            if customer_id is None:
                # Unknown party: fall back to the legacy walk-in account and
                # record it instead of inventing a customer.
                customer_id = self.maps["customer_by_ledger"].get(7)
                if customer_id is None:
                    headers.skipped += 1
                    self._warn("sale_missing_customer",
                               f"legacy id {legacy_id} customer ledger {row[9]}")
                    continue
                self._warn("sale_customer_fallback_walkin",
                           f"legacy id {legacy_id} customer ledger {row[9]}")
            cur = self.conn.execute(
                """INSERT INTO sales_invoices (
                       bill_no, sale_date, sale_time, sale_type, customer_id,
                       patient_name, doctor_id, discount, paid_amount,
                       total_amount, round_off, net_amount, remarks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (voucher_no, _date(row[4]), _text(row[5]), _text(row[2]) or "Cash",
                  customer_id, _text(row[10]),
                  self.maps["doctor"].get(row[13]),
                  _number(row[16]), _number(row[21]),
                  _number(row[14]), _number(row[18]), _number(row[7]),
                  remarks),
            )
            new_id = cur.lastrowid
            self.maps["sale"][legacy_id] = new_id
            vouchers[legacy_id] = (new_id, voucher_no, _date(row[4]), _text(row[5]))
            headers.imported += 1
        self._sales_bill_preserved = preserved
        self._sales_bill_fallback_missing = fallback_missing
        self._sales_bill_collisions = collisions
        self.conn.commit()
        self.sale_vouchers = vouchers

        items = self._stats("salesitemdetail")
        items.target = "sales_invoice_items"
        for row in self._rows("salesitemdetail"):
            invoice_id = self.maps["sale"].get(row[1])
            item_id = self.maps["item"].get(row[2])
            if invoice_id is None or item_id is None:
                items.skipped += 1
                self._warn("sale_item_unmapped", f"vh={row[1]} item={row[2]}")
                continue
            batch_id = self._ensure_batch(
                item_id, _text(row[4]), expiry=_date(row[5]),
                pack_size=_pack(row[3]), mrp=_number(row[6]),
                rate=_number(row[8]),
            )
            if batch_id is None:
                items.skipped += 1
                self._warn("sale_item_missing_batch", f"vh={row[1]} item={row[2]}")
                continue
            self.conn.execute(
                """INSERT INTO sales_invoice_items (
                       sales_invoice_id, item_id, stock_batch_id, pack_size,
                       location, batch_no, expiry, mrp, sale_qty,
                       discount_amount, amount)
                   VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)""",
                (invoice_id, item_id, batch_id, _pack(row[3]), _text(row[4]),
                 _date(row[5]), _number(row[6]), _number(row[7]),
                 _number(row[12]), _number(row[13])),
            )
            items.imported += 1
        self.conn.commit()
        self._import_accounting("salesvhdetail", self.maps["sale"], vouchers)

    # ══════════════════════════════════════════════════════════════════
    # Returns: credit notes (customer) / debit notes (supplier)
    # ══════════════════════════════════════════════════════════════════
    def _import_credit_notes(self) -> None:
        headers = self._stats("creditnotevhheader")
        headers.target = "credit_notes"
        vouchers: dict = {}
        for row in self._rows("creditnotevhheader"):
            legacy_id = row[0]
            fy_name = self._fy_map.get(row[1], "")
            customer_id = self.maps["customer_by_ledger"].get(row[8])
            if customer_id is None:
                headers.skipped += 1
                self._warn("credit_note_missing_customer",
                           f"legacy id {legacy_id} ledger {row[8]}")
                continue
            voucher_no = self._unique_voucher(
                f"{fy_name}-{_text(row[2])}-{row[3]}", legacy_id
            )
            cur = self.conn.execute(
                """INSERT INTO credit_notes (
                       voucher_no, voucher_date, voucher_time, cn_date,
                       cn_type, customer_id, total_amount, ledger_amount,
                       remarks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (voucher_no, _date(row[4]), _text(row[5]), _date(row[12]),
                 _text(row[13]) or "Customer", customer_id,
                 _number(row[7]), _number(row[7]), _text(row[6])),
            )
            self.maps["credit_note"][legacy_id] = cur.lastrowid
            vouchers[legacy_id] = (cur.lastrowid, voucher_no, _date(row[4]), _text(row[5]))
            headers.imported += 1
        self.conn.commit()

        items = self._stats("creditnoteitemdetail")
        items.target = "credit_note_items"
        for row in self._rows("creditnoteitemdetail"):
            note_id = self.maps["credit_note"].get(row[1])
            item_id = self.maps["item"].get(row[4])
            if note_id is None or item_id is None:
                items.skipped += 1
                self._warn("credit_note_item_unmapped", f"vh={row[1]} item={row[4]}")
                continue
            batch_id = self._ensure_batch(
                item_id, _text(row[5]), expiry=_date(row[7]),
                pack_size=_pack(row[6]), mrp=_number(row[11]),
                rate=_number(row[12]), net_rate=_number(row[14]),
            )
            if batch_id is None:
                items.skipped += 1
                continue
            self.conn.execute(
                """INSERT INTO credit_note_items (
                       credit_note_id, item_id, stock_batch_id, batch_no,
                       expiry, pack_size, rate, mrp, return_qty,
                       less_amount, amount, return_reason, price_factor)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0)""",
                (note_id, item_id, batch_id, _text(row[5]), _date(row[7]),
                 _pack(row[6]), _number(row[12]), _number(row[11]),
                 _number(row[8]), _number(row[17]), _number(row[18]),
                 _text(row[3])),
            )
            self._note_unsupported("creditnoteitemdetail.ReasonID")
            items.imported += 1
        self.conn.commit()
        self._import_accounting("creditnotevhdetail", self.maps["credit_note"],
                                vouchers)

    def _import_debit_notes(self) -> None:
        headers = self._stats("debitnotevhheader")
        headers.target = "debit_notes"
        vouchers: dict = {}
        for row in self._rows("debitnotevhheader"):
            legacy_id = row[0]
            fy_name = self._fy_map.get(row[1], "")
            supplier_id = self.maps["supplier_by_ledger"].get(row[8])
            if supplier_id is None:
                headers.skipped += 1
                self._warn("debit_note_missing_supplier",
                           f"legacy id {legacy_id} ledger {row[8]}")
                continue
            voucher_no = self._unique_voucher(
                f"{fy_name}-{_text(row[2])}-{row[3]}", legacy_id
            )
            cur = self.conn.execute(
                """INSERT INTO debit_notes (
                       voucher_no, voucher_date, voucher_time, dn_date,
                       dn_type, supplier_id, total_amount, ledger_amount,
                       remarks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (voucher_no, _date(row[4]), _text(row[5]), _date(row[12]),
                 _text(row[13]) or "Supplier", supplier_id,
                 _number(row[7]), _number(row[7]), _text(row[6])),
            )
            self.maps["debit_note"][legacy_id] = cur.lastrowid
            vouchers[legacy_id] = (cur.lastrowid, voucher_no, _date(row[4]), _text(row[5]))
            headers.imported += 1
        self.conn.commit()

        items = self._stats("debitnoteitemdetail")
        items.target = "debit_note_items"
        for row in self._rows("debitnoteitemdetail"):
            note_id = self.maps["debit_note"].get(row[1])
            item_id = self.maps["item"].get(row[4])
            if note_id is None or item_id is None:
                items.skipped += 1
                self._warn("debit_note_item_unmapped", f"vh={row[1]} item={row[4]}")
                continue
            batch_id = self._ensure_batch(
                item_id, _text(row[5]), expiry=_date(row[7]),
                pack_size=_pack(row[6]), mrp=_number(row[11]),
                rate=_number(row[12]), net_rate=_number(row[14]),
            )
            if batch_id is None:
                items.skipped += 1
                continue
            self.conn.execute(
                """INSERT INTO debit_note_items (
                       debit_note_id, item_id, stock_batch_id, batch_no,
                       expiry, pack_size, rate, mrp, return_qty,
                       less_amount, amount, return_reason, price_factor)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0)""",
                (note_id, item_id, batch_id, _text(row[5]), _date(row[7]),
                 _pack(row[6]), _number(row[12]), _number(row[11]),
                 _number(row[8]), _number(row[16]), _number(row[18]),
                 _text(row[3])),
            )
            self._note_unsupported("debitnoteitemdetail.ReasonID")
            items.imported += 1
        self.conn.commit()
        self._import_accounting("debitnotevhdetail", self.maps["debit_note"],
                                vouchers)

    # ══════════════════════════════════════════════════════════════════
    # Receipts / payments
    # ══════════════════════════════════════════════════════════════════
    def _import_receipts(self) -> None:
        headers = self._stats("receiptvhheader")
        headers.target = "customer_receipts"
        vouchers: dict = {}
        for row in self._rows("receiptvhheader"):
            legacy_id = row[0]
            fy_name = self._fy_map.get(row[1], "")
            customer_id = self.maps["customer_by_ledger"].get(row[8])
            if customer_id is None:
                headers.skipped += 1
                self._warn("receipt_missing_customer",
                           f"legacy id {legacy_id} ledger {row[8]}")
                continue
            voucher_no = self._unique_voucher(
                f"{fy_name}-{_text(row[2])}-{row[3]}", legacy_id
            )
            mode = self._tender_mode(row[9])
            cur = self.conn.execute(
                """INSERT INTO customer_receipts (
                       voucher_no, receipt_date, receipt_time, customer_id,
                       receipt_mode, amount, reference_no, remarks)
                   VALUES (?, ?, ?, ?, ?, ?, '', ?)""",
                (voucher_no, _date(row[4]), _text(row[5]), customer_id,
                 mode, _number(row[7]), _text(row[6])),
            )
            self.maps["receipt"][legacy_id] = cur.lastrowid
            vouchers[legacy_id] = (cur.lastrowid, voucher_no, _date(row[4]), _text(row[5]))
            headers.imported += 1
        self.conn.commit()
        self._import_accounting("receiptvhdetail", self.maps["receipt"], vouchers)

    def _import_payments(self) -> None:
        headers = self._stats("paymentvhheader")
        headers.target = "supplier_payments"
        vouchers: dict = {}
        for row in self._rows("paymentvhheader"):
            legacy_id = row[0]
            fy_name = self._fy_map.get(row[1], "")
            supplier_id = self.maps["supplier_by_ledger"].get(row[8])
            if supplier_id is None:
                headers.skipped += 1
                self._warn("payment_missing_supplier",
                           f"legacy id {legacy_id} ledger {row[8]}")
                continue
            voucher_no = self._unique_voucher(
                f"{fy_name}-{_text(row[2])}-{row[3]}", legacy_id
            )
            mode = self._tender_mode(row[9])
            cur = self.conn.execute(
                """INSERT INTO supplier_payments (
                       voucher_no, payment_date, payment_time, supplier_id,
                       payment_mode, amount, reference_no, remarks)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (voucher_no, _date(row[4]), _text(row[5]), supplier_id,
                 mode, _number(row[7]), _text(row[10]), _text(row[6])),
            )
            self.maps["payment"][legacy_id] = cur.lastrowid
            vouchers[legacy_id] = (cur.lastrowid, voucher_no, _date(row[4]), _text(row[5]))
            headers.imported += 1
        self.conn.commit()
        self._import_accounting("paymentvhdetail", self.maps["payment"], vouchers)

    def _tender_mode(self, legacy_ledger_id) -> str:
        """Cash vs Bank from the legacy cash/bank ledger reference."""
        role = None
        for legacy_id, new_id in self.maps["ledger"].items():
            if legacy_id == legacy_ledger_id:
                for role_name, role_id in self.role_ledger.items():
                    if role_id == new_id:
                        role = role_name
                        break
                break
        if role == account_roles.ROLE_BANK:
            return "Bank"
        return "Cash"

    # ══════════════════════════════════════════════════════════════════
    # Historical accounting (no PostingEngine replay)
    # ══════════════════════════════════════════════════════════════════
    def _import_accounting(self, source: str, reference_map: dict,
                           vouchers: dict) -> None:
        reference_type, voucher_type = ACCOUNTING_SOURCES[source]
        stats = self._stats(source)
        stats.target = "ledger_transactions"
        for row in self._rows(source):
            header = reference_map.get(row[3])
            ledger_id = self.maps["ledger"].get(row[5])
            if header is None:
                stats.skipped += 1
                self._warn("accounting_missing_header", f"{source} vh={row[3]}")
                continue
            if ledger_id is None:
                stats.skipped += 1
                self._warn("accounting_unmapped_ledger", f"{source} led={row[5]}")
                continue
            _new_id, voucher_no, date, time_value = vouchers.get(row[3], (None, "", "", ""))
            transaction_date = _date(row[2]) or date
            amount = _number(row[6])
            is_debit = _text(row[4]).upper() == "DR"
            self.conn.execute(
                """INSERT INTO ledger_transactions (
                       ledger_id, transaction_date, transaction_time,
                       voucher_type, voucher_no, reference_type,
                       reference_id, description, debit, credit)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ledger_id, transaction_date, time_value, voucher_type,
                 voucher_no, reference_type, header, _text(row[7]),
                 amount if is_debit else 0.0,
                 0.0 if is_debit else amount),
            )
            stats.imported += 1
        self.conn.commit()

    # ══════════════════════════════════════════════════════════════════
    # Legacy usernames (opt-in, inactive, no password hashes)
    # ══════════════════════════════════════════════════════════════════
    def _import_legacy_usernames(self) -> None:
        stats = self._stats("userinfo")
        stats.target = "app_users (inactive)"
        import secrets as _secrets

        from database import auth as auth_module

        for row in self._rows("userinfo"):
            username = _text(row[1])
            if not username:
                stats.skipped += 1
                continue
            existing = self.conn.execute(
                "SELECT id FROM app_users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
            if existing:
                stats.skipped += 1
                continue
            # The legacy hash is deliberately NOT imported: an unusable
            # random hash is stored and the account stays inactive until an
            # ADMIN resets the password.
            unusable = f"legacy-migration-disabled${_secrets.token_hex(24)}"
            role = (auth_module.ROLE_ADMIN if _text(row[3]).upper() == "Y"
                    else auth_module.ROLE_PHARMACIST_STAFF)
            self.conn.execute(
                """INSERT INTO app_users (username, password_hash, role,
                                          is_active, created_at, updated_at)
                   VALUES (?, ?, ?, 0, datetime('now'), datetime('now'))""",
                (username, unusable, role),
            )
            stats.imported += 1
        self.conn.commit()

    # ══════════════════════════════════════════════════════════════════
    # Finalize / report
    # ══════════════════════════════════════════════════════════════════
    def _finalize(self) -> None:
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS legacy_id_map (
                   entity TEXT NOT NULL,
                   legacy_id TEXT NOT NULL,
                   new_id INTEGER NOT NULL,
                   PRIMARY KEY (entity, legacy_id)
               )"""
        )
        self.conn.execute("DELETE FROM legacy_id_map")
        for entity, mapping in self.maps.items():
            if entity.startswith("__"):
                continue
            rows = [(entity, str(legacy), int(new)) for legacy, new in mapping.items()]
            self.conn.executemany(
                "INSERT OR REPLACE INTO legacy_id_map (entity, legacy_id, new_id)"
                " VALUES (?, ?, ?)",
                rows,
            )
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS legacy_migration_meta (
                   key TEXT PRIMARY KEY, value TEXT
               )"""
        )
        self.conn.execute("DELETE FROM legacy_migration_meta")
        meta = {
            "source_dump": str(self.dump.path),
            "source_bytes": str(self.dump.size_bytes),
            "migrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dry_run_rows": str(sum(s.source_rows for s in self.stats.values())),
            "imported_rows": str(sum(s.imported for s in self.stats.values())),
            "skipped_rows": str(sum(s.skipped for s in self.stats.values())),
            "warnings": str(len(self.warnings)),
            "legacy_passwords_imported": "0",
            "demo_rows_imported": "0",
        }
        for source, stats in self.stats.items():
            meta[f"stat.{source}.rows"] = str(stats.source_rows)
            meta[f"stat.{source}.imported"] = str(stats.imported)
            meta[f"stat.{source}.skipped"] = str(stats.skipped)
            if stats.target and stats.target != "unsupported":
                meta[f"target.{source}"] = stats.target
        meta["system_ledgers"] = str(len(getattr(self, "role_ledger", {})))
        meta["extra_stock_batches"] = str(self._extra_batches)
        meta["skip_stock"] = str(bool(getattr(self, "skip_stock", False)))
        meta["sales_bill_preserved"] = str(getattr(self, "_sales_bill_preserved", 0))
        meta["sales_bill_fallback_missing"] = str(
            getattr(self, "_sales_bill_fallback_missing", 0)
        )
        meta["sales_bill_collisions"] = str(
            getattr(self, "_sales_bill_collisions", 0)
        )
        if self.backup:
            meta["pre_migration_backup"] = self.backup["path"]
            meta["pre_migration_backup_sha256"] = self.backup["sha256"]
        self.conn.executemany(
            "INSERT INTO legacy_migration_meta (key, value) VALUES (?, ?)",
            list(meta.items()),
        )
        self.conn.commit()

    def report(self) -> dict:
        return {
            "source_dump": str(self.dump.path),
            "source_bytes": self.dump.size_bytes,
            "target_db": self.db_path,
            "backup": self.backup,
            "cleared": getattr(self, "cleared", {}),
            "pre_state": self.pre_state,
            "post_state": self.post_state,
            "tables": [s.as_dict() for s in self.stats.values()],
            "imported_rows": sum(s.imported for s in self.stats.values()),
            "skipped_rows": sum(s.skipped for s in self.stats.values()),
            "warnings": self.warnings,
            "item_duplicates_merged": self._duplicates,
            "unsupported_fields": dict(self._unsupported_fields),
            "skip_stock": bool(getattr(self, "skip_stock", False)),
            "sales_bill_preserved": getattr(self, "_sales_bill_preserved", 0),
            "sales_bill_fallback_missing": getattr(
                self, "_sales_bill_fallback_missing", 0
            ),
            "sales_bill_collisions": getattr(self, "_sales_bill_collisions", 0),
            "demo_rows_excluded": sum(
                self.dump.count_rows().get(name, 0) for name in DEMO_TABLES
            ),
        }


# ══════════════════════════════════════════════════════════════════════
# Database state / verification
# ══════════════════════════════════════════════════════════════════════

IMPORTANT_TABLES: tuple[str, ...] = (
    "companies", "units", "drugs", "doctors", "items", "item_ingredients",
    "customers", "suppliers", "account_ledgers", "ledger_transactions",
    "purchase_invoices", "purchase_invoice_items",
    "sales_invoices", "sales_invoice_items",
    "credit_notes", "credit_note_items",
    "debit_notes", "debit_note_items",
    "customer_receipts", "supplier_payments",
    "stock_batches", "financial_years",
)


def migration_meta(conn: sqlite3.Connection) -> dict:
    """Return the recorded migration metadata (empty when not migrated)."""
    try:
        rows = conn.execute(
            "SELECT key, value FROM legacy_migration_meta"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {row[0]: row[1] for row in rows}


def database_state(conn: sqlite3.Connection) -> dict:
    """SHA-256, size, table count and important row counts of the database."""
    import hashlib

    # Flush the write-ahead log so the hash reflects the committed data.
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        conn.commit()
    except sqlite3.Error:
        pass

    path = None
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            path = row[2]
    state = {"path": path, "tables": 0, "rows": {}}
    if path and os.path.isfile(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        state["sha256"] = digest.hexdigest()
        state["size_bytes"] = os.path.getsize(path)
    tables = [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    ]
    state["tables"] = len(tables)
    for name in IMPORTANT_TABLES:
        if name in tables:
            state["rows"][name] = conn.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()[0]
    return state


def verify_migration(dump_path: str | os.PathLike[str], *,
                     db_path: str | None = None,
                     limit: int | None = None) -> dict:
    """Read-only verification of an imported database against the dump."""
    if db_path:
        os.environ["PHARMACY_DB"] = str(db_path)
    dump = LegacyDump(dump_path)
    source_counts = dump.count_rows()
    conn = get_connection()
    try:
        result: dict = {"ok": True, "checks": [], "issues": []}

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        result["integrity_check"] = integrity
        result["checks"].append({"name": "integrity_check", "value": integrity,
                                 "ok": integrity == "ok"})
        if integrity != "ok":
            result["ok"] = False
            result["issues"].append(f"integrity_check={integrity}")

        foreign = list(conn.execute("PRAGMA foreign_key_check"))
        result["foreign_key_violations"] = len(foreign)
        result["checks"].append({"name": "foreign_key_check",
                                 "value": len(foreign), "ok": not foreign})
        if foreign:
            result["ok"] = False
            for row in foreign[:20]:
                result["issues"].append(f"fk: {tuple(row)}")

        expectations = [
            ("companies", "companymst"),
            ("units", "unitmst"),
            ("drugs", "drugmst"),
            ("doctors", "doctormst"),
            ("items", "itemmst"),
            ("item_ingredients", "itemdrugs"),
            ("purchase_invoices", "invoicevhheader"),
            ("purchase_invoice_items", "invoiceitemdetail"),
            ("sales_invoices", "salesvhheader"),
            ("sales_invoice_items", "salesitemdetail"),
            ("credit_notes", "creditnotevhheader"),
            ("credit_note_items", "creditnoteitemdetail"),
            ("debit_notes", "debitnotevhheader"),
            ("debit_note_items", "debitnoteitemdetail"),
            ("customer_receipts", "receiptvhheader"),
            ("supplier_payments", "paymentvhheader"),
            ("stock_batches", "stockbalance"),
            ("financial_years", "acyear"),
        ]
        meta = migration_meta(conn)
        for target, source in expectations:
            actual = conn.execute(f'SELECT COUNT(*) FROM "{target}"').fetchone()[0]
            if meta:
                # Target rows equal the rows that were imported (legacy
                # duplicates were merged and counted as skipped).
                expected = int(meta.get(f"stat.{source}.imported", 0))
                if target == "stock_batches":
                    # Batches referenced only by historical transactions are
                    # created with zero stock in addition to stockbalance.
                    expected += int(meta.get("extra_stock_batches", 0))
            else:
                expected = source_counts.get(source, 0)
            if limit and not meta:
                expected = min(expected, limit)
            check = {
                "name": f"count:{target}",
                "source": source,
                "expected": expected,
                "actual": actual,
                "ok": actual == expected,
            }
            result["checks"].append(check)
            if not check["ok"]:
                result["ok"] = False
                result["issues"].append(
                    f"{target}: expected {expected} from {source}, found {actual}"
                )

        # account ledgers: system ledgers + imported legacy ledgers
        if meta:
            system_ledgers = int(meta.get("system_ledgers", 0))
            if not system_ledgers:
                system_ledgers = conn.execute(
                    "SELECT COUNT(*) FROM account_ledgers WHERE system_role IS NOT NULL"
                ).fetchone()[0]
            expected_ledgers = system_ledgers + int(meta.get("stat.ledger.imported", 0))
            actual_ledgers = conn.execute(
                "SELECT COUNT(*) FROM account_ledgers"
            ).fetchone()[0]
            check = {
                "name": "count:account_ledgers",
                "expected": expected_ledgers,
                "actual": actual_ledgers,
                "ok": actual_ledgers >= expected_ledgers,
            }
            result["checks"].append(check)
            if not check["ok"]:
                result["ok"] = False
                result["issues"].append(
                    f"account_ledgers: expected at least {expected_ledgers}, "
                    f"found {actual_ledgers}"
                )

        # accounting lines
        if meta:
            detail_total = sum(
                int(meta.get(f"stat.{table}.imported", 0))
                for table in ACCOUNTING_SOURCES
            )
        else:
            detail_total = sum(
                source_counts.get(table, 0) for table in ACCOUNTING_SOURCES
            )
        actual_ledger_rows = conn.execute(
            "SELECT COUNT(*) FROM ledger_transactions"
        ).fetchone()[0]
        result["checks"].append({
            "name": "count:ledger_transactions",
            "expected": detail_total,
            "actual": actual_ledger_rows,
            "ok": actual_ledger_rows == detail_total,
        })
        if actual_ledger_rows != detail_total:
            result["ok"] = False
            result["issues"].append(
                f"ledger_transactions: expected {detail_total}, "
                f"found {actual_ledger_rows}"
            )

        # ledger id mapping coverage
        if meta:
            mapping = conn.execute(
                "SELECT COUNT(*) FROM legacy_id_map WHERE entity = 'ledger'"
            ).fetchone()[0]
            legacy_ledgers = source_counts.get("ledger", 0)
            check = {
                "name": "mapping:ledger_ids",
                "expected": legacy_ledgers,
                "actual": mapping,
                "ok": mapping == legacy_ledgers,
            }
            result["checks"].append(check)
            if not check["ok"]:
                result["ok"] = False
                result["issues"].append(
                    f"ledger id mapping: expected {legacy_ledgers}, found {mapping}"
                )
            for entity, source in (("item", "itemmst"), ("company", "companymst"),
                                   ("unit", "unitmst"), ("drug", "drugmst"),
                                   ("doctor", "doctormst")):
                mapped = conn.execute(
                    "SELECT COUNT(*) FROM legacy_id_map WHERE entity = ?", (entity,)
                ).fetchone()[0]
                expected = source_counts.get(source, 0)
                if limit:
                    expected = min(expected, limit)
                ok = mapped == expected
                result["checks"].append({
                    "name": f"mapping:{entity}_ids",
                    "expected": expected, "actual": mapped, "ok": ok,
                })
                if not ok:
                    result["ok"] = False
                    result["issues"].append(
                        f"{entity} id mapping: expected {expected}, found {mapped}"
                    )

        # demo / auth safety
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_users'"
        ).fetchone():
            demo_present = conn.execute(
                "SELECT COUNT(*) FROM app_users WHERE password_hash LIKE 'legacy-migration%'"
                " AND is_active = 0"
            ).fetchone()[0]
            active_legacy = conn.execute(
                "SELECT COUNT(*) FROM app_users WHERE password_hash LIKE 'legacy-migration%'"
                " AND is_active = 1"
            ).fetchone()[0]
        else:
            demo_present = 0
            active_legacy = 0
        result["legacy_users_imported"] = demo_present
        result["checks"].append({
            "name": "no_legacy_password_hashes_active",
            "value": active_legacy,
            "ok": active_legacy == 0,
        })
        if active_legacy:
            result["ok"] = False
            result["issues"].append("legacy users imported as active accounts")

        # stock reconciliation
        reconciliation = stock_reconciliation(conn, dump)
        result["stock_reconciliation"] = reconciliation
        if reconciliation["mismatches"]:
            result["ok"] = False
            result["issues"].append(
                f"stock reconciliation mismatches: {reconciliation['mismatches']}"
            )

        # orphans (defensive; FK check already covers the common cases)
        orphans = orphan_report(conn)
        result["orphans"] = orphans
        for name, count in orphans.items():
            if count:
                result["ok"] = False
                result["issues"].append(f"orphans in {name}: {count}")
        return result
    finally:
        conn.close()


def stock_reconciliation(conn: sqlite3.Connection, dump: LegacyDump) -> dict:
    """Compare every legacy batch balance with the imported batch."""
    legacy: dict[tuple, float] = {}
    duplicate_rows = 0
    for row in dump.iter_rows("stockbalance"):
        key = (row[0], _text(row[1]))
        if key in legacy:
            duplicate_rows += 1
        legacy[key] = legacy.get(key, 0.0) + (_number(row[6]) - _number(row[9]))
    item_map = {
        str(row[1]): row[0] for row in conn.execute("SELECT id, id FROM items")
    }
    del item_map
    rows = conn.execute(
        "SELECT item_id, batch_no, stock_qty FROM stock_batches"
    ).fetchall()
    imported = {(row[0], row[1]): row[2] for row in rows}
    # legacy item id → new item id
    mapping: dict = {}
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_id_map'"
    ).fetchone():
        mapping = {
            int(row[1]): int(row[2])
            for row in conn.execute(
                "SELECT entity, legacy_id, new_id FROM legacy_id_map WHERE entity='item'"
            )
        }
    mismatches = 0
    missing = 0
    details = []
    for (legacy_item, batch), qty in legacy.items():
        new_item = mapping.get(int(legacy_item))
        if new_item is None:
            missing += 1
            details.append({"legacy_item": legacy_item, "batch": batch,
                            "legacy_qty": qty, "new_qty": None,
                            "reason": "item not mapped"})
            continue
        new_qty = imported.get((new_item, batch))
        if new_qty is None:
            missing += 1
            details.append({"legacy_item": legacy_item, "batch": batch,
                            "legacy_qty": qty, "new_qty": None,
                            "reason": "batch not imported"})
            continue
        if abs(new_qty - qty) > 1e-6:
            mismatches += 1
            details.append({"legacy_item": legacy_item, "batch": batch,
                            "legacy_qty": qty, "new_qty": new_qty,
                            "reason": "quantity differs"})
    return {
        "legacy_batches": len(legacy),
        "duplicate_legacy_rows": duplicate_rows,
        "imported_batches": len(imported),
        "mismatches": mismatches,
        "missing": missing,
        "details": details[:100],
    }


def orphan_report(conn: sqlite3.Connection) -> dict:
    checks = {
        "sales_invoice_items_without_invoice": (
            "SELECT COUNT(*) FROM sales_invoice_items si LEFT JOIN "
            "sales_invoices s ON s.id = si.sales_invoice_id WHERE s.id IS NULL"
        ),
        "sales_invoice_items_without_item": (
            "SELECT COUNT(*) FROM sales_invoice_items si LEFT JOIN "
            "items i ON i.id = si.item_id WHERE i.id IS NULL"
        ),
        "sales_invoice_items_without_batch": (
            "SELECT COUNT(*) FROM sales_invoice_items si LEFT JOIN "
            "stock_batches b ON b.id = si.stock_batch_id WHERE b.id IS NULL"
        ),
        "purchase_invoice_items_without_invoice": (
            "SELECT COUNT(*) FROM purchase_invoice_items pi LEFT JOIN "
            "purchase_invoices p ON p.id = pi.purchase_invoice_id WHERE p.id IS NULL"
        ),
        "ledger_transactions_without_ledger": (
            "SELECT COUNT(*) FROM ledger_transactions lt LEFT JOIN "
            "account_ledgers al ON al.id = lt.ledger_id WHERE al.id IS NULL"
        ),
        "customers_without_ledger": (
            "SELECT COUNT(*) FROM customers WHERE ledger_id IS NULL"
        ),
        "suppliers_without_ledger": (
            "SELECT COUNT(*) FROM suppliers WHERE ledger_id IS NULL"
        ),
    }
    out = {}
    for name, sql in checks.items():
        try:
            out[name] = conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            out[name] = 0
    return out


# ══════════════════════════════════════════════════════════════════════
# Report rendering
# ══════════════════════════════════════════════════════════════════════

def render_migration_report(report: dict) -> str:
    lines = [
        "# Legacy Data Migration Report",
        "",
        "## Source",
        "",
        f"- File: `{report['source_dump']}`",
        f"- Size: {report['source_bytes']:,} bytes",
        "- Format: MySQL 5.7 mysqldump (imported offline — no MySQL connection)",
        "",
    ]
    if report.get("backup"):
        backup = report["backup"]
        lines += [
            "## Pre-migration backup",
            "",
            f"- Path: `{backup['path']}`",
            f"- SHA-256: `{backup['sha256']}`",
            f"- Size: {backup['size_bytes']:,} bytes",
            f"- Validated: {backup.get('validated')} ({backup.get('integrity')})",
            "",
        ]
    pre = report.get("pre_state") or {}
    post = report.get("post_state") or {}
    if pre:
        lines += [
            "## Production database state",
            "",
            "| Item | Before | After |",
            "| --- | --- | --- |",
            f"| Tables | {pre.get('tables')} | {post.get('tables')} |",
            f"| Size (bytes) | {pre.get('size_bytes', 0):,} | {post.get('size_bytes', 0):,} |",
            f"| SHA-256 | `{pre.get('sha256', '')[:16]}…` | `{post.get('sha256', '')[:16]}…` |",
            "",
            "| Table | Before | After |",
            "| --- | ---: | ---: |",
        ]
        for name in sorted(set(pre.get("rows", {})) | set(post.get("rows", {}))):
            lines.append(
                f"| {name} | {pre.get('rows', {}).get(name, 0):,} "
                f"| {post.get('rows', {}).get(name, 0):,} |"
            )
        lines.append("")

    lines += [
        "## Cleared demo/test business data",
        "",
        "| Table | Rows removed |",
        "| --- | ---: |",
    ]
    for name, count in sorted((report.get("cleared") or {}).items()):
        lines.append(f"| {name} | {count:,} |")
    lines += ["", "## Imported rows", "",
              "| Source table | Rows | Target | Imported | Skipped |",
              "| --- | ---: | --- | ---: | ---: |"]
    for entry in report["tables"]:
        lines.append(
            f"| `{entry['source']}` | {entry['source_rows']:,} | {entry['target']} "
            f"| {entry['imported']:,} | {entry['skipped']:,} |"
        )
    lines += [
        "",
        f"- Total imported rows: {report['imported_rows']:,}",
        f"- Total skipped rows: {report['skipped_rows']:,}",
        f"- Demo rows excluded: {report['demo_rows_excluded']:,}",
        f"- Warnings: {len(report['warnings']):,}",
        "",
    ]
    if report.get("item_duplicates_merged"):
        lines += ["## Duplicate / merged legacy records", "",
                  "Legacy records whose unique name already existed are merged "
                  "(never silently dropped); the legacy id still maps to the "
                  "merged record so transactions resolve.", "",
                  "| Source table | Legacy id | Name | Merged into |",
                  "| --- | ---: | --- | ---: |"]
        for entry in report["item_duplicates_merged"]:
            lines.append(
                f"| `{entry.get('source', 'itemmst')}` | {entry['legacy_id']} "
                f"| {entry['name']} | {entry['merged_into']} |"
            )
        lines.append("")
    if report.get("unsupported_fields"):
        lines += ["## Unsupported fields (source value not stored)", "",
                  "| Field | Rows |", "| --- | ---: |"]
        for name, count in sorted(report["unsupported_fields"].items()):
            lines.append(f"| `{name}` | {count:,} |")
        lines.append("")
    lines += ["## Unsupported tables", "",
              "| Table | Reason |", "| --- | --- |"]
    for name, reason in UNSUPPORTED_TABLES.items():
        lines.append(f"| `{name}` | {reason} |")
    lines.append("")
    if report["warnings"]:
        lines += ["## Warnings", ""]
        for warning in report["warnings"][:200]:
            lines.append(f"- {warning['kind']}: {warning['detail']}")
        if len(report["warnings"]) > 200:
            lines.append(f"- … and {len(report['warnings']) - 200} more")
        lines.append("")
    lines += [
        "## Authentication",
        "",
        "- Legacy `userinfo.UserPassword` hashes were **not** imported.",
        "- Existing application accounts are preserved and login is unchanged.",
        "- Legacy usernames, when imported, are inactive with an unusable "
        "password until an ADMIN resets them.",
        "",
    ]
    return "\n".join(lines)


def write_migration_report(report: dict, path: str, json_path: str | None = None) -> dict:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_migration_report(report), encoding="utf-8")
    written = {"markdown": str(target)}
    if json_path:
        item = Path(json_path)
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        written["json"] = str(item)
    return written


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

DEFAULT_DRY_RUN_MD = "docs/legacy_migration_dry_run.md"
DEFAULT_DRY_RUN_JSON = "docs/legacy_migration_dry_run.json"
DEFAULT_REPORT_MD = "docs/legacy_migration_report.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m database.legacy_migration",
        description="Offline legacy Pharma-WINNER SQL dump migration utility.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="Parse and report only; never writes to a database.")
    mode.add_argument("--import", dest="do_import", action="store_true",
                      help="Back up, clear demo data and import the dump.")
    mode.add_argument("--verify", action="store_true",
                      help="Read-only verification of an imported database.")
    parser.add_argument("dump", help="Path to the legacy .sql dump")
    parser.add_argument("--db", default=None,
                        help="Target SQLite database (default: PHARMACY_DB / data/pharmacy.db)")
    parser.add_argument("--report", default=None, help="Markdown report path")
    parser.add_argument("--json", default=None, help="JSON report path")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip the pre-import backup (staging only).")
    parser.add_argument("--backup-dir", default=None,
                        help="Directory for the pre-import backup.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit rows per source table (staging/debug).")
    parser.add_argument("--import-legacy-users", action="store_true",
                        help="Import legacy usernames as INACTIVE accounts "
                             "(no password hashes).")
    parser.add_argument("--skip-stock", action="store_true",
                        help="Defer stockbalance/stockadjusted to a separate "
                             "phase (history-only batches qty 0 for FK).")
    parser.add_argument("--confirm-production", action="store_true",
                        help="Required when importing into the real "
                             "data/pharmacy.db.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parent.parent
    default_db = str(project_root / "data" / "pharmacy.db")

    if args.do_import:
        target = os.path.abspath(args.db or get_db_path())
        if target == os.path.abspath(default_db) and not args.confirm_production:
            print("Refusing to import into the production database without "
                  "--confirm-production (use --db for a staging copy).",
                  file=sys.stderr)
            return 2
    if args.db:
        os.environ["PHARMACY_DB"] = os.path.abspath(args.db)

    if args.dry_run:
        plan = build_plan(LegacyDump(args.dump))
        md = args.report or str(project_root / DEFAULT_DRY_RUN_MD)
        js = args.json or str(project_root / DEFAULT_DRY_RUN_JSON)
        written = write_dry_run_reports(plan, md, js)
        summary = plan.summary()
        print(json.dumps(summary, indent=2))
        print("written:", written)
        return 0

    if args.verify:
        result = verify_migration(args.dump, db_path=args.db, limit=args.limit)
        print(json.dumps({k: v for k, v in result.items() if k != "checks"},
                         indent=2, default=str))
        md = args.report or str(project_root / "docs" / "legacy_migration_verification.md")
        js = args.json
        write_migration_report({"source_dump": str(args.dump),
                                "source_bytes": Path(args.dump).stat().st_size,
                                "tables": [], "imported_rows": 0,
                                "skipped_rows": 0, "demo_rows_excluded": 0,
                                "warnings": [], "verification": result}, md, js)
        return 0 if result["ok"] else 1

    migrator = LegacyMigrator(
        args.dump,
        db_path=args.db,
        limit=args.limit,
        import_legacy_users=args.import_legacy_users,
        skip_stock=args.skip_stock,
    )
    report = migrator.import_data(
        do_backup=not args.no_backup, backup_dir=args.backup_dir
    )
    md = args.report or str(project_root / DEFAULT_REPORT_MD)
    js = args.json or str(project_root / "docs" / "legacy_migration_report.json")
    write_migration_report(report, md, js)
    verification = verify_migration(args.dump, db_path=args.db, limit=args.limit)
    print(json.dumps({
        "imported_rows": report["imported_rows"],
        "skipped_rows": report["skipped_rows"],
        "warnings": len(report["warnings"]),
        "backup": (report.get("backup") or {}).get("path"),
        "verification_ok": verification["ok"],
        "issues": verification["issues"][:20],
    }, indent=2, default=str))
    return 0 if verification["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

