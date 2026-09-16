"""
Migration: Customer/Supplier → Account Ledger Mapping

Phase 1 of Accounting Integration.

This module:
1. Detects whether ledger_id columns already exist on customers/suppliers.
2. Adds the columns if missing (safe for existing databases).
3. For each Customer without a ledger_id, creates an Account Ledger and links it.
4. For each Supplier without a ledger_id, creates an Account Ledger and links it.
5. Migrates opening_balance from customers/suppliers into their linked ledger.

Ledger naming convention:
    Customer: "Customer - <customer_name>"
    Supplier: "Supplier - <supplier_name>"

Safety:
- Uses transactions — rolls back completely on failure.
- Never deletes existing customers, suppliers, or ledgers.
- Idempotent: running twice produces no duplicates.
"""

from __future__ import annotations

from database.connection import get_connection


def _ledger_name_for_customer(customer_name: str) -> str:
    return f"Customer - {customer_name}"


def _ledger_name_for_supplier(supplier_name: str) -> str:
    return f"Supplier - {supplier_name}"


def _ensure_columns(conn) -> None:
    """Add ledger_id columns if they don't exist."""
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(customers)")
    cust_cols = {row[1] for row in cur.fetchall()}
    if "ledger_id" not in cust_cols:
        cur.execute(
            "ALTER TABLE customers ADD COLUMN ledger_id "
            "INTEGER REFERENCES account_ledgers(id) ON DELETE SET NULL"
        )

    cur.execute("PRAGMA table_info(suppliers)")
    sup_cols = {row[1] for row in cur.fetchall()}
    if "ledger_id" not in sup_cols:
        cur.execute(
            "ALTER TABLE suppliers ADD COLUMN ledger_id "
            "INTEGER REFERENCES account_ledgers(id) ON DELETE SET NULL"
        )


def _migrate_customers(conn) -> int:
    """Create ledgers for customers that don't have one yet. Returns count."""
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, customer_name, opening_balance FROM customers "
        "WHERE ledger_id IS NULL"
    ).fetchall()

    count = 0
    for row in rows:
        cust_id = row["id"]
        cust_name = row["customer_name"]
        opening_balance = row["opening_balance"] or 0.0

        ledger_name = _ledger_name_for_customer(cust_name)

        # Check if a ledger with this name already exists (idempotency)
        existing = cur.execute(
            "SELECT id FROM account_ledgers WHERE ledger_name = ?",
            (ledger_name,),
        ).fetchone()

        if existing:
            ledger_id = existing["id"]
        else:
            # Determine opening balance type for the ledger
            # Customers typically have Debit opening balances (they owe us)
            ob_type = "Debit" if opening_balance >= 0 else "Credit"
            ob_amount = abs(opening_balance)

            cur.execute(
                """INSERT INTO account_ledgers
                    (ledger_name, account_group, opening_balance,
                     opening_balance_type, address, city, state,
                     contact_person, contact_no)
                SELECT ?, 'Sundry Debtors', ?, ?, address, city, state,
                       contact_person, contact_no
                FROM customers WHERE id = ?""",
                (ledger_name, ob_amount, ob_type, cust_id),
            )
            ledger_id = cur.lastrowid

        # Link customer to ledger (only if not already linked)
        cur.execute(
            "UPDATE customers SET ledger_id = ? WHERE id = ? AND ledger_id IS NULL",
            (ledger_id, cust_id),
        )
        count += 1

    return count


def _migrate_suppliers(conn) -> int:
    """Create ledgers for suppliers that don't have one yet. Returns count."""
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, supplier_name, opening_balance FROM suppliers "
        "WHERE ledger_id IS NULL"
    ).fetchall()

    count = 0
    for row in rows:
        sup_id = row["id"]
        sup_name = row["supplier_name"]
        opening_balance = row["opening_balance"] or 0.0

        ledger_name = _ledger_name_for_supplier(sup_name)

        # Check if a ledger with this name already exists (idempotency)
        existing = cur.execute(
            "SELECT id FROM account_ledgers WHERE ledger_name = ?",
            (ledger_name,),
        ).fetchone()

        if existing:
            ledger_id = existing["id"]
        else:
            # Determine opening balance type for the ledger
            # Suppliers typically have Credit opening balances (we owe them)
            ob_type = "Credit" if opening_balance >= 0 else "Debit"
            ob_amount = abs(opening_balance)

            cur.execute(
                """INSERT INTO account_ledgers
                    (ledger_name, account_group, opening_balance,
                     opening_balance_type, address, city, state,
                     contact_person, contact_no)
                SELECT ?, 'Sundry Creditors', ?, ?, address, city, state,
                       contact_person, contact_no
                FROM suppliers WHERE id = ?""",
                (ledger_name, ob_amount, ob_type, sup_id),
            )
            ledger_id = cur.lastrowid

        # Link supplier to ledger (only if not already linked)
        cur.execute(
            "UPDATE suppliers SET ledger_id = ? WHERE id = ? AND ledger_id IS NULL",
            (ledger_id, sup_id),
        )
        count += 1

    return count


def run_migration() -> dict:
    """Run the full migration. Returns a summary dict.

    Safe to run multiple times (idempotent).
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN")

        _ensure_columns(conn)
        customers_migrated = _migrate_customers(conn)
        suppliers_migrated = _migrate_suppliers(conn)

        conn.commit()
        return {
            "customers_migrated": customers_migrated,
            "suppliers_migrated": suppliers_migrated,
            "status": "success",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
