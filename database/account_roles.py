"""Centralized account-role configuration for the Accounting Posting Engine.

Phase 2B / Phase 4A.  The roles defined here are exactly those supported
by the approved accounting decisions (docs/accounting_decisions.md, §16
table) and the accounting posting specification
(docs/accounting_posting_specification.md, §11 "Required Account Roles"):

- CASH, BANK              (Decisions 7/8 — Cheque/UPI post to the Bank account;
                            no separate Cheque or UPI ledgers)
- SALES, PURCHASE         (Decisions 1/2 — net posting; no Discount / Round-Off
                            / Other accounts)
- SALES_RETURN, PURCHASE_RETURN

Explicitly NOT defined (per approved decisions): GST accounts (Decision 4a —
no GST ledgers), Inventory / COGS (Decision 5 — periodic inventory).

Phase 4A adds a structured account-group hierarchy that can safely classify
every ledger for future financial statements.  The hierarchy is stored in
the ``account_groups`` table and linked to ledgers via
``account_ledgers.account_group_id``.

This module is the single source of truth for role keys and their configured
ledger names.  The posting engine must resolve accounts via
LedgerDAO.get_by_system_role("CASH") etc., never by searching ledger names.
"""

from __future__ import annotations

from database.connection import get_connection
from database.ledger_dao import LedgerDAO

# ── Role keys (single source of truth — do not scatter literals) ──────
ROLE_CASH = "CASH"
ROLE_BANK = "BANK"
ROLE_SALES = "SALES"
ROLE_PURCHASE = "PURCHASE"
ROLE_SALES_RETURN = "SALES_RETURN"
ROLE_PURCHASE_RETURN = "PURCHASE_RETURN"

# ── Role registry ─────────────────────────────────────────────────────
# role key → {name: ledger display name, account_group: legacy text,
#             description: purpose of the role}
ACCOUNT_ROLES: dict[str, dict] = {
    ROLE_CASH: {
        "name": "Cash",
        "account_group": "Cash-in-Hand",
        "description": "Cash tender for sales, purchases, receipts and payments.",
    },
    ROLE_BANK: {
        "name": "Bank",
        "account_group": "Bank Accounts",
        "description": "Bank, Cheque and UPI tender (approved decision: Cheque/UPI post to the Bank account).",
    },
    ROLE_SALES: {
        "name": "Sales",
        "account_group": "Sales Accounts",
        "description": "Revenue account credited by future counter-sale posting.",
    },
    ROLE_PURCHASE: {
        "name": "Purchase",
        "account_group": "Purchase Accounts",
        "description": "Expense account debited by future purchase-invoice posting (periodic inventory).",
    },
    ROLE_SALES_RETURN: {
        "name": "Sales Return",
        "account_group": "Sales Accounts",
        "description": "Contra-revenue account debited by future customer credit-note posting.",
    },
    ROLE_PURCHASE_RETURN: {
        "name": "Purchase Return",
        "account_group": "Purchase Accounts",
        "description": "Contra-expense account credited by future supplier debit-note posting.",
    },
}

# Every role in the registry is required before automatic posting can operate.
REQUIRED_ROLES: tuple[str, ...] = tuple(ACCOUNT_ROLES.keys())


def ensure_system_ledgers() -> dict:
    """Ensure every required system ledger exists and carries its role.

    Idempotent and transactional (all roles are ensured in ONE database
    transaction — any failure rolls back the whole batch):

    - Role already assigned   → reused as-is (no writes).
    - Unassigned ledger with  → the role is assigned to it (reuse; the
      the exact configured     ledger itself is never modified otherwise).
      ledger name
    - Neither                 → a new ledger is created with the configured
                               name, account group and role.

    Returns a summary dict:
        {"status": "success",
         "created": [role, ...],           # newly created ledgers
         "reused": [role, ...],            # existing ledgers that received the role
         "already_configured": [role, ...]}  # role was already assigned
    """
    created: list[str] = []
    reused: list[str] = []
    already: list[str] = []

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for role, cfg in ACCOUNT_ROLES.items():
            _ledger_id, outcome = LedgerDAO._ensure_system_ledger_cur(
                cur, role, cfg["name"], cfg["account_group"]
            )
            if outcome == "created":
                created.append(role)
            elif outcome == "reused":
                reused.append(role)
            else:
                already.append(role)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "success",
        "created": created,
        "reused": reused,
        "already_configured": already,
    }


# ══════════════════════════════════════════════════════════════════════
# Phase 4A — Structured Account-Group Hierarchy
# ══════════════════════════════════════════════════════════════════════

# Statement types accepted by account_groups.statement_type
STMT_ASSET = "ASSET"
STMT_LIABILITY = "LIABILITY"
STMT_EQUITY = "EQUITY"
STMT_INCOME = "INCOME"
STMT_EXPENSE = "EXPENSE"

# Normal balances
NORMAL_DEBIT = "DEBIT"
NORMAL_CREDIT = "CREDIT"

# ── Structured group definitions ─────────────────────────────────────
# Each entry: (group_name, parent_name_or_None, statement_type,
#              normal_balance)
# Parent references are resolved by name during ensure_account_groups().
_STRUCTURED_GROUPS: list[tuple[str, str | None, str, str]] = [
    # ── Root groups ───────────────────────────────────────────────
    ("Assets",       None,           STMT_ASSET,     NORMAL_DEBIT),
    ("Liabilities",  None,           STMT_LIABILITY, NORMAL_CREDIT),
    ("Equity",       None,           STMT_EQUITY,    NORMAL_CREDIT),
    ("Income",       None,           STMT_INCOME,    NORMAL_CREDIT),
    ("Expenses",     None,           STMT_EXPENSE,   NORMAL_DEBIT),

    # ── Asset children ───────────────────────────────────────────
    ("Current Assets",     "Assets", STMT_ASSET,     NORMAL_DEBIT),
    ("Fixed Assets",       "Assets", STMT_ASSET,     NORMAL_DEBIT),

    # ── Liability children ───────────────────────────────────────
    ("Current Liabilities",  "Liabilities", STMT_LIABILITY, NORMAL_CREDIT),
    ("Long Term Liabilities","Liabilities", STMT_LIABILITY, NORMAL_CREDIT),

    # ── Equity children ──────────────────────────────────────────
    ("Capital",  "Equity", STMT_EQUITY, NORMAL_CREDIT),

    # ── Income children ──────────────────────────────────────────
    ("Sales",  "Income", STMT_INCOME, NORMAL_CREDIT),

    # ── Expense children ─────────────────────────────────────────
    ("Purchase-related",  "Expenses", STMT_EXPENSE, NORMAL_DEBIT),
    ("Operating Expenses","Expenses", STMT_EXPENSE, NORMAL_DEBIT),
]


def ensure_account_groups() -> dict:
    """Create the structured account-group hierarchy if it does not exist.

    Idempotent and transactional.  Each group is created only if it
    does not already exist (by name).  Returns a summary dict:
        {"status": "success", "created": [...], "already_configured": [...]}
    """
    created: list[str] = []
    already: list[str] = []

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")

        # Build name → id map for existing groups
        existing = cur.execute(
            "SELECT id, group_name FROM account_groups"
        ).fetchall()
        name_to_id: dict[str, int] = {r["group_name"]: r["id"] for r in existing}

        # Insert groups in order so parents exist before children
        for group_name, parent_name, stmt, normal in _STRUCTURED_GROUPS:
            if group_name in name_to_id:
                already.append(group_name)
                continue
            parent_id = name_to_id.get(parent_name) if parent_name else None
            cur.execute(
                """INSERT INTO account_groups
                    (group_name, parent_group_id, statement_type,
                     normal_balance, is_system)
                VALUES (?, ?, ?, ?, 1)""",
                (group_name, parent_id, stmt, normal),
            )
            name_to_id[group_name] = cur.lastrowid
            created.append(group_name)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"status": "success", "created": created, "already_configured": already}


# ── Legacy-group → structured-group mapping ─────────────────────────
# Only entries where the mapping is unambiguous are listed.
# Unmapped legacy text is preserved as-is; the migration never guesses.

_CLASSIFICATION_MAP: dict[str, str] = {
    # legacy account_group text  →  structured group_name
    "Cash-in-Hand":      "Current Assets",
    "Bank Accounts":     "Current Assets",
    "Sales Accounts":    "Sales",
    "Purchase Accounts": "Purchase-related",
    # Phase 4B — resolved party classifications (approved decisions)
    "Sundry Debtors":    "Current Assets",
    "Sundry Creditors":  "Current Liabilities",
}


def migrate_legacy_ledger_groups() -> dict:
    """Migrate legacy free-text account_group → structured account_group_id.

    Rules:
    1. Preserve existing account_group text (do not delete it).
    2. Map to structured group ONLY when unambiguous (see _CLASSIFICATION_MAP).
    3. Unmapped ledgers keep account_group_id = NULL — they are unresolved.
    4. Never silently classify a ledger incorrectly.
    5. Transactional — all changes in one commit.

    Returns a summary dict:
        {"status": "success",
         "migrated": int,
         "skipped_unmapped": int,
         "already_migrated": int}
    """
    from database.account_group_dao import AccountGroupDAO

    migrated = 0
    skipped = 0
    already = 0

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")

        # Build name → id map for structured groups
        group_rows = cur.execute(
            "SELECT id, group_name FROM account_groups"
        ).fetchall()
        name_to_id = {r["group_name"]: r["id"] for r in group_rows}

        # Process every ledger
        ledger_rows = cur.execute(
            "SELECT id, account_group, account_group_id FROM account_ledgers"
        ).fetchall()

        for ledger in ledger_rows:
            lid = ledger["id"]

            # Already migrated — skip
            if ledger["account_group_id"] is not None:
                already += 1
                continue

            legacy_text = (ledger["account_group"] or "").strip()
            if not legacy_text:
                skipped += 1
                continue

            structured_name = _CLASSIFICATION_MAP.get(legacy_text)
            if structured_name and structured_name in name_to_id:
                cur.execute(
                    "UPDATE account_ledgers SET account_group_id = ? WHERE id = ?",
                    (name_to_id[structured_name], lid),
                )
                migrated += 1
            else:
                # Unmapped — leave account_group_id as NULL
                skipped += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "success",
        "migrated": migrated,
        "skipped_unmapped": skipped,
        "already_migrated": already,
    }


def get_role_status() -> list[dict]:
    """Return one row per required role for display/validation.

    Row shape: {role, name, account_group, description,
                ledger_id, ledger_name, status}
    where status is "Configured" or "Missing".
    """
    rows: list[dict] = []
    for role, cfg in ACCOUNT_ROLES.items():
        ledger = LedgerDAO.get_by_system_role(role)
        rows.append(
            {
                "role": role,
                "name": cfg["name"],
                "account_group": cfg["account_group"],
                "description": cfg["description"],
                "ledger_id": ledger["id"] if ledger else None,
                "ledger_name": ledger["ledger_name"] if ledger else "",
                "status": "Configured" if ledger else "Missing",
            }
        )
    return rows


def all_roles_configured() -> bool:
    """True when every required system role is assigned to a ledger."""
    return all(r["status"] == "Configured" for r in get_role_status())
