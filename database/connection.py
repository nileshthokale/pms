import os
import sqlite3
import sys
from pathlib import Path

APP_DATA_DIR_NAME = "PharmacyManagementSystem"
APP_DB_FILE_NAME = "pharmacy.db"

_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_DB_PATH = os.path.join(_DB_DIR, "pharmacy.db")


def get_app_data_dir() -> str:
    """Per-user writable directory for the packaged application.

    Packaging-only helper: development (unfrozen) runs keep using
    ``data/`` next to the source tree.  A PyInstaller build (``sys.frozen``)
    resolves to ``%LOCALAPPDATA%\\PharmacyManagementSystem`` so the EXE
    never writes beside itself (Program Files is not writable) and never
    touches the development database.
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        # Non-standard Windows setups: fall back to ~/.AppData/Local.
        base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, APP_DATA_DIR_NAME)


def _default_db_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(get_app_data_dir(), APP_DB_FILE_NAME)
    return _DB_PATH


def get_db_path() -> str:
    """Resolve the database file path for connections.

    Honors the PHARMACY_DB environment variable when set — the test
    suite sets it per test class to a throwaway *_test_*.db file so the
    real application database is never touched by tests. The path is
    resolved on every call (not at import) so test classes can each
    point at their own database.

    Production code never sets PHARMACY_DB and always uses
    data/pharmacy.db (development) or the per-user app-data directory
    (packaged EXE — see get_app_data_dir()).
    """
    db_path = os.environ.get("PHARMACY_DB") or _default_db_path()
    # The full-suite runner sets this guard so a test that accidentally drops
    # PHARMACY_DB (or points it back at the app database) still cannot open
    # the real business database for writing.
    protected_path = os.environ.get("PHARMACY_TEST_PROTECTED_DB")
    safe_path = os.environ.get("PHARMACY_TEST_SAFE_DB")
    if protected_path and safe_path:
        if os.path.normcase(os.path.abspath(db_path)) == os.path.normcase(
            os.path.abspath(protected_path)
        ):
            return safe_path
    return db_path


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT    NOT NULL UNIQUE,
                short_name   TEXT    NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS units (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                unit_name TEXT    NOT NULL UNIQUE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drugs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                drug_name TEXT    NOT NULL UNIQUE
            )
            """
        )
        # Category is normal item master data.  It deliberately has no
        # accounting or stock-side relationship of its own.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT    NOT NULL,
                description   TEXT,
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # SQLite's ordinary UNIQUE constraint is case-sensitive and retains
        # surrounding whitespace.  This index protects normalized names too.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_normalized_name "
            "ON categories(lower(trim(category_name)))"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS suppliers (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_name    TEXT    NOT NULL UNIQUE,
                sales_tax_no     TEXT    DEFAULT '',
                vat_or_tin       TEXT    DEFAULT '',
                city             TEXT    DEFAULT '',
                contact_person   TEXT    DEFAULT '',
                contact_no       TEXT    DEFAULT '',
                address          TEXT    DEFAULT '',
                state            TEXT    DEFAULT '',
                discount         REAL    DEFAULT 0.0,
                credit_limit     REAL    DEFAULT 0.0,
                credit_period    INTEGER DEFAULT 0,
                vat_tin          TEXT    DEFAULT '',
                opening_balance  REAL    DEFAULT 0.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name    TEXT    NOT NULL UNIQUE,
                city             TEXT    DEFAULT '',
                contact_person   TEXT    DEFAULT '',
                contact_no       TEXT    DEFAULT '',
                address          TEXT    DEFAULT '',
                state            TEXT    DEFAULT '',
                discount         REAL    DEFAULT 0.0,
                credit_limit     REAL    DEFAULT 0.0,
                credit_period    INTEGER DEFAULT 0,
                opening_balance  REAL    DEFAULT 0.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS doctors (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_name  TEXT    NOT NULL UNIQUE,
                city         TEXT    DEFAULT '',
                specialty    TEXT    DEFAULT '',
                phone_no     TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name           TEXT    NOT NULL UNIQUE,
                unit_id             INTEGER REFERENCES units(id) ON DELETE SET NULL,
                company_id          INTEGER REFERENCES companies(id) ON DELETE SET NULL,
                category_id         INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                pack_size           TEXT    DEFAULT '',
                tax_structure       TEXT    DEFAULT '',
                discount            REAL    DEFAULT 0.0,
                mrp                 REAL    DEFAULT 0.0,
                rate                REAL    DEFAULT 0.0,
                reorder_stock_level INTEGER DEFAULT 0,
                scheduled           TEXT    DEFAULT '',
                location            TEXT    DEFAULT '',
                pathy               TEXT    DEFAULT '',
                dpco                TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS item_ingredients (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                drug_id INTEGER NOT NULL REFERENCES drugs(id) ON DELETE CASCADE,
                power   TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_invoices (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_no          TEXT    NOT NULL UNIQUE,
                voucher_date        TEXT    NOT NULL,
                voucher_time        TEXT    DEFAULT '',
                purchase_type       TEXT    DEFAULT 'Credit',
                supplier_id         INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                invoice_no          TEXT    DEFAULT '',
                invoice_date        TEXT    DEFAULT '',
                invoice_net_amount  REAL    DEFAULT 0.0,
                bill_discount       REAL    DEFAULT 0.0,
                due_date            TEXT    DEFAULT '',
                total_amount        REAL    DEFAULT 0.0,
                gst_amount          REAL    DEFAULT 0.0,
                debit_note_amount   REAL    DEFAULT 0.0,
                other_amount        REAL    DEFAULT 0.0,
                paid_amount         REAL    DEFAULT 0.0,
                round_off           REAL    DEFAULT 0.0,
                net_amount          REAL    DEFAULT 0.0,
                remarks             TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_invoice_items (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_invoice_id INTEGER NOT NULL REFERENCES purchase_invoices(id) ON DELETE CASCADE,
                item_id             INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                pack_size           TEXT    DEFAULT '',
                pay_qty             REAL    DEFAULT 0.0,
                free_qty            REAL    DEFAULT 0.0,
                batch_no            TEXT    DEFAULT '',
                expiry              TEXT    DEFAULT '',
                rate                REAL    DEFAULT 0.0,
                mrp                 REAL    DEFAULT 0.0,
                discount            REAL    DEFAULT 0.0,
                gst_percent         REAL    DEFAULT 0.0,
                gst_amount          REAL    DEFAULT 0.0,
                amount              REAL    DEFAULT 0.0,
                purchase_rate       REAL    DEFAULT 0.0,
                net_rate            REAL    DEFAULT 0.0,
                pp                  REAL    DEFAULT 0.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_batches (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                batch_no        TEXT    NOT NULL,
                expiry          TEXT    DEFAULT '',
                pack_size       TEXT    DEFAULT '',
                mrp             REAL    DEFAULT 0.0,
                purchase_rate   REAL    DEFAULT 0.0,
                net_rate        REAL    DEFAULT 0.0,
                stock_qty       REAL    DEFAULT 0.0,
                UNIQUE(item_id, batch_no)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_invoices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_no         TEXT    NOT NULL UNIQUE,
                sale_date       TEXT    NOT NULL,
                sale_time       TEXT    DEFAULT '',
                sale_type       TEXT    DEFAULT 'Cash',
                customer_id     INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                patient_name    TEXT    DEFAULT '',
                doctor_id       INTEGER REFERENCES doctors(id) ON DELETE SET NULL,
                discount        REAL    DEFAULT 0.0,
                paid_amount     REAL    DEFAULT 0.0,
                total_amount    REAL    DEFAULT 0.0,
                round_off       REAL    DEFAULT 0.0,
                net_amount      REAL    DEFAULT 0.0,
                remarks         TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sales_invoice_items (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                sales_invoice_id    INTEGER NOT NULL REFERENCES sales_invoices(id) ON DELETE CASCADE,
                item_id             INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                stock_batch_id      INTEGER NOT NULL REFERENCES stock_batches(id) ON DELETE CASCADE,
                pack_size           TEXT    DEFAULT '',
                location            TEXT    DEFAULT '',
                batch_no            TEXT    NOT NULL,
                expiry              TEXT    DEFAULT '',
                mrp                 REAL    DEFAULT 0.0,
                sale_qty            REAL    DEFAULT 0.0,
                discount_amount     REAL    DEFAULT 0.0,
                amount              REAL    DEFAULT 0.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_notes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_no      TEXT    NOT NULL UNIQUE,
                voucher_date    TEXT    NOT NULL,
                voucher_time    TEXT    DEFAULT '',
                cn_date         TEXT    DEFAULT '',
                cn_type         TEXT    DEFAULT 'Customer',
                customer_id     INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                total_amount    REAL    DEFAULT 0.0,
                ledger_amount   REAL    DEFAULT 0.0,
                remarks         TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_note_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                credit_note_id  INTEGER NOT NULL REFERENCES credit_notes(id) ON DELETE CASCADE,
                item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                stock_batch_id  INTEGER NOT NULL REFERENCES stock_batches(id) ON DELETE CASCADE,
                batch_no        TEXT    NOT NULL,
                expiry          TEXT    DEFAULT '',
                pack_size       TEXT    DEFAULT '',
                rate            REAL    DEFAULT 0.0,
                mrp             REAL    DEFAULT 0.0,
                return_qty      REAL    DEFAULT 0.0,
                less_amount     REAL    DEFAULT 0.0,
                amount          REAL    DEFAULT 0.0,
                return_reason   TEXT    DEFAULT '',
                price_factor    REAL    DEFAULT 1.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS debit_notes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_no      TEXT    NOT NULL UNIQUE,
                voucher_date    TEXT    NOT NULL,
                voucher_time    TEXT    DEFAULT '',
                dn_date         TEXT    DEFAULT '',
                dn_type         TEXT    DEFAULT 'Supplier',
                supplier_id     INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                total_amount    REAL    DEFAULT 0.0,
                ledger_amount   REAL    DEFAULT 0.0,
                remarks         TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS debit_note_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                debit_note_id   INTEGER NOT NULL REFERENCES debit_notes(id) ON DELETE CASCADE,
                item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                stock_batch_id  INTEGER NOT NULL REFERENCES stock_batches(id) ON DELETE CASCADE,
                batch_no        TEXT    NOT NULL,
                expiry          TEXT    DEFAULT '',
                pack_size       TEXT    DEFAULT '',
                rate            REAL    DEFAULT 0.0,
                mrp             REAL    DEFAULT 0.0,
                return_qty      REAL    DEFAULT 0.0,
                less_amount     REAL    DEFAULT 0.0,
                amount          REAL    DEFAULT 0.0,
                return_reason   TEXT    DEFAULT '',
                price_factor    REAL    DEFAULT 1.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS supplier_payments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_no      TEXT    NOT NULL UNIQUE,
                payment_date    TEXT    NOT NULL,
                payment_time    TEXT    DEFAULT '',
                supplier_id     INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                payment_mode    TEXT    DEFAULT 'Cash',
                amount          REAL    DEFAULT 0.0,
                reference_no    TEXT    DEFAULT '',
                remarks         TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_receipts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_no      TEXT    NOT NULL UNIQUE,
                receipt_date    TEXT    NOT NULL,
                receipt_time    TEXT    DEFAULT '',
                customer_id     INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                receipt_mode    TEXT    DEFAULT 'Cash',
                amount          REAL    DEFAULT 0.0,
                reference_no    TEXT    DEFAULT '',
                remarks         TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_ledgers (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_name             TEXT    NOT NULL UNIQUE,
                account_group           TEXT    DEFAULT '',
                opening_balance         REAL    DEFAULT 0.0,
                opening_balance_type    TEXT    DEFAULT 'Debit',
                discount                REAL    DEFAULT 0.0,
                credit_limit            REAL    DEFAULT 0.0,
                credit_period           INTEGER DEFAULT 0,
                address                 TEXT    DEFAULT '',
                city                    TEXT    DEFAULT '',
                state                   TEXT    DEFAULT '',
                contact_person          TEXT    DEFAULT '',
                contact_no              TEXT    DEFAULT '',
                tax_no                  TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_transactions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger_id           INTEGER NOT NULL REFERENCES account_ledgers(id) ON DELETE CASCADE,
                transaction_date    TEXT    NOT NULL,
                transaction_time    TEXT    DEFAULT '',
                voucher_type        TEXT    NOT NULL,
                voucher_no          TEXT    NOT NULL,
                reference_type      TEXT    DEFAULT '',
                reference_id        INTEGER,
                description         TEXT    DEFAULT '',
                debit               REAL    DEFAULT 0.0,
                credit              REAL    DEFAULT 0.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_entries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_no      TEXT    NOT NULL UNIQUE,
                entry_date      TEXT    NOT NULL,
                entry_time      TEXT    DEFAULT '',
                narration       TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_entry_items (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                journal_entry_id    INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
                ledger_id           INTEGER NOT NULL REFERENCES account_ledgers(id),
                description         TEXT    DEFAULT '',
                debit               REAL    DEFAULT 0.0,
                credit              REAL    DEFAULT 0.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS financial_years (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_year_active "
            "ON financial_years(is_active) WHERE is_active = 1"
        )

        # ── Phase 1: Customer/Supplier → Account Ledger mapping ──
        # Safe migration: only adds columns if they don't already exist.
        cur = conn.cursor()

        # Phase 6B-7: category is an optional item relationship.  ALTER TABLE
        # only adds the nullable column; it never rebuilds items or touches
        # stock, invoices, ledgers, or existing item values.
        cur.execute("PRAGMA table_info(items)")
        item_cols = {row[1] for row in cur.fetchall()}
        if "category_id" not in item_cols:
            cur.execute(
                "ALTER TABLE items ADD COLUMN category_id "
                "INTEGER REFERENCES categories(id) ON DELETE SET NULL"
            )

        # customers.ledger_id
        cur.execute("PRAGMA table_info(customers)")
        cust_cols = {row[1] for row in cur.fetchall()}
        if "ledger_id" not in cust_cols:
            cur.execute(
                "ALTER TABLE customers ADD COLUMN ledger_id "
                "INTEGER REFERENCES account_ledgers(id) ON DELETE SET NULL"
            )

        # suppliers.ledger_id
        cur.execute("PRAGMA table_info(suppliers)")
        sup_cols = {row[1] for row in cur.fetchall()}
        if "ledger_id" not in sup_cols:
            cur.execute(
                "ALTER TABLE suppliers ADD COLUMN ledger_id "
                "INTEGER REFERENCES account_ledgers(id) ON DELETE SET NULL"
            )

        # ── Phase 2B: Account Ledger system roles ──
        # Safe migration: adds a nullable system_role column (if missing) and a
        # partial unique index so each system role (e.g. 'CASH') can be assigned
        # to at most one ledger. Existing ledgers and transactions are untouched;
        # NULL system_role values are not constrained by the partial index.
        cur.execute("PRAGMA table_info(account_ledgers)")
        al_cols = {row[1] for row in cur.fetchall()}
        if "system_role" not in al_cols:
            cur.execute(
                "ALTER TABLE account_ledgers ADD COLUMN system_role TEXT"
            )

        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_account_ledgers_system_role "
            "ON account_ledgers(system_role) WHERE system_role IS NOT NULL"
        )

        # ── Phase 4A: Account Groups structured classification ──
        # account_groups table: hierarchical groups for financial-statement
        # classification.  Idempotent — CREATE IF NOT EXISTS.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_groups (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name          TEXT    NOT NULL UNIQUE,
                parent_group_id     INTEGER NULL
                                    REFERENCES account_groups(id) ON DELETE SET NULL,
                statement_type      TEXT    DEFAULT '',
                normal_balance      TEXT    DEFAULT '',
                is_system           BOOLEAN DEFAULT 0
            )
            """
        )

        # account_ledgers.account_group_id  (nullable FK → account_groups)
        cur.execute("PRAGMA table_info(account_ledgers)")
        al_cols = {row[1] for row in cur.fetchall()}
        if "account_group_id" not in al_cols:
            cur.execute(
                "ALTER TABLE account_ledgers ADD COLUMN account_group_id "
                "INTEGER NULL REFERENCES account_groups(id) ON DELETE SET NULL"
            )

        conn.commit()
    finally:
        conn.close()
