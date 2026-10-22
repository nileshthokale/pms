from __future__ import annotations

from database.connection import get_connection


class CustomerDAO:

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT c.*, al.ledger_name
                   FROM customers c
                   LEFT JOIN account_ledgers al ON al.id = c.ledger_id
                   ORDER BY c.customer_name"""
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(customer_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT c.*, al.ledger_name
                   FROM customers c
                   LEFT JOIN account_ledgers al ON al.id = c.ledger_id
                   WHERE c.id = ?""",
                (customer_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def name_exists(name: str, exclude_id: int | None = None) -> bool:
        conn = get_connection()
        try:
            if exclude_id is not None:
                row = conn.execute(
                    "SELECT 1 FROM customers WHERE customer_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM customers WHERE customer_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def search(name: str) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT c.*, al.ledger_name
                   FROM customers c
                   LEFT JOIN account_ledgers al ON al.id = c.ledger_id
                   WHERE c.customer_name LIKE ?
                   ORDER BY c.customer_name""",
                (f"%{name}%",),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ── ledger mapping helpers ──────────────────────────────────────
    @staticmethod
    def get_ledger_id(customer_id: int) -> int | None:
        """Return the ledger_id linked to this customer, or None."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT ledger_id FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone()
            return row["ledger_id"] if row else None
        finally:
            conn.close()

    @staticmethod
    def get_customer_by_ledger(ledger_id: int) -> dict | None:
        """Return the customer linked to this ledger, or None."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM customers WHERE ledger_id = ?",
                (ledger_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_or_create_walkin() -> int:
        """Return the id of an existing WALKIN customer, or create one if none exists."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM customers WHERE UPPER(TRIM(customer_name)) = 'WALKIN' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT id FROM customers WHERE UPPER(TRIM(customer_name)) = 'WALKIN CUSTOMER' ORDER BY id ASC LIMIT 1"
                ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT id FROM customers WHERE UPPER(TRIM(customer_name)) LIKE 'WALKIN%' ORDER BY id ASC LIMIT 1"
                ).fetchone()
            if row:
                return row["id"]
        finally:
            conn.close()
        return CustomerDAO.insert("WALKIN")

    @staticmethod
    def _ensure_patient_addresses_table():
        conn = get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS patient_addresses (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_name TEXT    NOT NULL COLLATE NOCASE,
                    address      TEXT    NOT NULL,
                    customer_id  INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                    updated_at   TEXT    DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(patient_name, address)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_patient_addresses_pat "
                "ON patient_addresses(patient_name COLLATE NOCASE)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_patient_addresses_addr "
                "ON patient_addresses(address COLLATE NOCASE)"
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO patient_addresses (patient_name, address, customer_id)
                SELECT customer_name, address, id
                FROM customers
                WHERE address IS NOT NULL AND TRIM(address) <> ''
                  AND UPPER(TRIM(customer_name)) NOT IN ('WALKIN', 'WALKIN CUSTOMER')
                """
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    @staticmethod
    def get_saved_addresses_for_patient(patient_name: str) -> list[str]:
        """Return distinct saved addresses for the specified patient name.

        Normalizes names (collapsing whitespace, ignoring case) and matches
        strictly to avoid false-positive address selection.
        """
        raw = (patient_name or "").strip()
        if not raw:
            return []
        norm = " ".join(raw.split()).upper()
        if norm in ("WALKIN", "WALKIN CUSTOMER"):
            return []

        CustomerDAO._ensure_patient_addresses_table()

        import sqlite3
        conn = get_connection()
        addresses: list[str] = []
        seen: set[str] = set()

        def _add(addr: str | None):
            if not addr:
                return
            cleaned = " ".join(str(addr).split()).strip()
            if not cleaned:
                return
            key = cleaned.upper()
            if key not in seen:
                seen.add(key)
                addresses.append(cleaned)

        try:
            # 1. From dedicated patient_addresses table
            cur = conn.execute(
                """
                SELECT address
                FROM patient_addresses
                WHERE UPPER(TRIM(patient_name)) = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (norm,),
            )
            for row in cur.fetchall():
                _add(row["address"] if isinstance(row, sqlite3.Row) else row[0])

            # 2. Direct matches from customers table
            cur = conn.execute(
                """
                SELECT address
                FROM customers
                WHERE address IS NOT NULL AND TRIM(address) <> ''
                  AND UPPER(TRIM(customer_name)) = ?
                  AND UPPER(TRIM(customer_name)) NOT IN ('WALKIN', 'WALKIN CUSTOMER')
                ORDER BY id DESC
                """,
                (norm,),
            )
            for row in cur.fetchall():
                _add(row["address"] if isinstance(row, sqlite3.Row) else row[0])

            # 3. Historical sales where patient_name matches
            cur = conn.execute(
                """
                SELECT c.address
                FROM sales_invoices si
                JOIN customers c ON si.customer_id = c.id
                WHERE c.address IS NOT NULL AND TRIM(c.address) <> ''
                  AND UPPER(TRIM(c.customer_name)) NOT IN ('WALKIN', 'WALKIN CUSTOMER')
                  AND UPPER(TRIM(si.patient_name)) = ?
                ORDER BY si.sale_date DESC, si.id DESC
                LIMIT 100
                """,
                (norm,),
            )
            for row in cur.fetchall():
                _add(row["address"] if isinstance(row, sqlite3.Row) else row[0])
        finally:
            conn.close()

        return addresses

    @staticmethod
    def get_distinct_addresses(query: str = "") -> list[tuple[str, str]]:
        """Return distinct saved addresses matching query as (clean_address, display_text).

        Includes matching address and associated patient/customer name for context.
        """
        CustomerDAO._ensure_patient_addresses_table()

        text = " ".join((query or "").split()).strip()
        pattern = f"%{text}%" if text else "%"

        import sqlite3
        conn = get_connection()
        results: list[tuple[str, str]] = []
        seen: set[str] = set()

        def _add(clean_addr: str, person_name: str | None = None):
            clean = " ".join((clean_addr or "").split()).strip()
            if not clean:
                return
            p_name = " ".join((person_name or "").split()).strip()
            if p_name and p_name.upper() not in ("WALKIN", "WALKIN CUSTOMER"):
                disp = f"{clean}  ({p_name})"
            else:
                disp = clean
            key = (clean.upper(), disp.upper())
            if key not in seen:
                seen.add(key)
                results.append((clean, disp))

        try:
            # 1. From patient_addresses table
            cur = conn.execute(
                """
                SELECT address, patient_name
                FROM patient_addresses
                WHERE address IS NOT NULL AND TRIM(address) <> ''
                  AND (address COLLATE NOCASE LIKE ? OR patient_name COLLATE NOCASE LIKE ?)
                ORDER BY updated_at DESC, id DESC
                LIMIT 50
                """,
                (pattern, pattern),
            )
            for row in cur.fetchall():
                c_addr = row["address"] if isinstance(row, sqlite3.Row) else row[0]
                p_name = row["patient_name"] if isinstance(row, sqlite3.Row) else row[1]
                _add(c_addr, p_name)

            # 2. From customers table
            cur = conn.execute(
                """
                SELECT address, customer_name
                FROM customers
                WHERE address IS NOT NULL AND TRIM(address) <> ''
                  AND (address COLLATE NOCASE LIKE ? OR customer_name COLLATE NOCASE LIKE ?)
                  AND UPPER(TRIM(customer_name)) NOT IN ('WALKIN', 'WALKIN CUSTOMER')
                ORDER BY address ASC
                LIMIT 50
                """,
                (pattern, pattern),
            )
            for row in cur.fetchall():
                c_addr = row["address"] if isinstance(row, sqlite3.Row) else row[0]
                c_name = row["customer_name"] if isinstance(row, sqlite3.Row) else row[1]
                _add(c_addr, c_name)
        finally:
            conn.close()

        # Prioritize addresses that start with the query
        if text:
            upper_q = text.upper()
            starts = [r for r in results if r[0].upper().startswith(upper_q)]
            others = [r for r in results if not r[0].upper().startswith(upper_q)]
            return (starts + others)[:50]

        return results[:50]

    @staticmethod
    def save_patient_address(
        patient_name: str,
        address: str,
        customer_id: int | None = None,
    ) -> None:
        """Preserve the patient's address in accordance with the existing data model."""
        clean_addr = " ".join((address or "").split()).strip()
        if not clean_addr:
            return
        clean_pat = " ".join((patient_name or "").split()).strip()

        CustomerDAO._ensure_patient_addresses_table()

        import sqlite3
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            walkin_ids = set()
            for r in cur.execute(
                "SELECT id FROM customers WHERE UPPER(TRIM(customer_name)) IN ('WALKIN', 'WALKIN CUSTOMER')"
            ).fetchall():
                walkin_ids.add(r[0] if not isinstance(r, sqlite3.Row) else r["id"])

            is_named_customer = customer_id is not None and customer_id not in walkin_ids

            # 1. Dedicated patient_addresses persistence
            if clean_pat and clean_pat.upper() not in ("WALKIN", "WALKIN CUSTOMER"):
                cur.execute(
                    """
                    INSERT OR REPLACE INTO patient_addresses (patient_name, address, customer_id, updated_at)
                    VALUES (?, ?, ?, datetime('now', 'localtime'))
                    """,
                    (clean_pat, clean_addr, customer_id),
                )

            # 2. If customer_id is a named customer, update their registered address
            if is_named_customer:
                cur.execute(
                    "UPDATE customers SET address = ? WHERE id = ?",
                    (clean_addr, customer_id),
                )
                cur.execute(
                    """
                    UPDATE account_ledgers SET address = ?
                    WHERE id = (SELECT ledger_id FROM customers WHERE id = ?)
                    """,
                    (clean_addr, customer_id),
                )
                conn.commit()
                return

            # 3. If patient name matches an existing registered customer, keep their address updated
            if clean_pat and clean_pat.upper() not in ("WALKIN", "WALKIN CUSTOMER"):
                cur.execute(
                    "SELECT id, ledger_id FROM customers WHERE UPPER(TRIM(customer_name)) = UPPER(TRIM(?))",
                    (clean_pat,),
                )
                existing = cur.fetchone()
                if existing:
                    cid = existing[0] if not isinstance(existing, sqlite3.Row) else existing["id"]
                    lid = existing[1] if not isinstance(existing, sqlite3.Row) else existing["ledger_id"]
                    cur.execute(
                        "UPDATE customers SET address = ? WHERE id = ?",
                        (clean_addr, cid),
                    )
                    if lid:
                        cur.execute(
                            "UPDATE account_ledgers SET address = ? WHERE id = ?",
                            (clean_addr, lid),
                        )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── create / update ─────────────────────────────────────────────
    @staticmethod
    def insert(
        customer_name: str,
        city: str = "",
        contact_person: str = "",
        contact_no: str = "",
        address: str = "",
        state: str = "",
        discount: float = 0.0,
        credit_limit: float = 0.0,
        credit_period: int = 0,
        opening_balance: float = 0.0,
    ) -> int:
        """Insert a new customer and automatically create + link an Account Ledger.

        Returns the new customer id.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # 1. Create the customer
            cur.execute(
                """INSERT INTO customers (
                    customer_name, city, contact_person, contact_no,
                    address, state, discount, credit_limit,
                    credit_period, opening_balance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    customer_name, city, contact_person, contact_no,
                    address, state, discount, credit_limit,
                    credit_period, opening_balance,
                ),
            )
            customer_id = cur.lastrowid

            # 2. Create linked Account Ledger (idempotent: reuse if name exists)
            ledger_name = f"Customer - {customer_name}"
            ob_type = "Debit" if opening_balance >= 0 else "Credit"
            ob_amount = abs(opening_balance)

            existing = cur.execute(
                "SELECT id FROM account_ledgers WHERE ledger_name = ?",
                (ledger_name,),
            ).fetchone()

            if existing:
                ledger_id = existing["id"]
            else:
                cur.execute(
                    """INSERT INTO account_ledgers
                        (ledger_name, account_group, opening_balance,
                         opening_balance_type, credit_limit, credit_period,
                         address, city, state, contact_person, contact_no)
                    VALUES (?, 'Sundry Debtors', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ledger_name, ob_amount, ob_type,
                        credit_limit, credit_period,
                        address, city, state, contact_person, contact_no,
                    ),
                )
                ledger_id = cur.lastrowid

            # 3. Link customer to ledger
            cur.execute(
                "UPDATE customers SET ledger_id = ? WHERE id = ?",
                (ledger_id, customer_id),
            )

            conn.commit()
            return customer_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update(
        customer_id: int,
        customer_name: str,
        city: str = "",
        contact_person: str = "",
        contact_no: str = "",
        address: str = "",
        state: str = "",
        discount: float = 0.0,
        credit_limit: float = 0.0,
        credit_period: int = 0,
        opening_balance: float = 0.0,
    ) -> None:
        """Update customer and sync the linked ledger name/details.

        Does NOT create a second ledger. If no ledger exists yet, creates one.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # 1. Update the customer record
            cur.execute(
                """UPDATE customers SET
                    customer_name = ?,
                    city = ?,
                    contact_person = ?,
                    contact_no = ?,
                    address = ?,
                    state = ?,
                    discount = ?,
                    credit_limit = ?,
                    credit_period = ?,
                    opening_balance = ?
                WHERE id = ?""",
                (
                    customer_name, city, contact_person, contact_no,
                    address, state, discount, credit_limit,
                    credit_period, opening_balance,
                    customer_id,
                ),
            )

            # 2. Sync linked ledger (create if missing)
            row = cur.execute(
                "SELECT ledger_id FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone()
            ledger_id = row["ledger_id"] if row else None

            if ledger_id:
                # Update existing ledger
                ledger_name = f"Customer - {customer_name}"
                cur.execute(
                    """UPDATE account_ledgers SET
                        ledger_name = ?,
                        credit_limit = ?,
                        credit_period = ?,
                        address = ?,
                        city = ?,
                        state = ?,
                        contact_person = ?,
                        contact_no = ?
                    WHERE id = ?""",
                    (
                        ledger_name, credit_limit, credit_period,
                        address, city, state, contact_person, contact_no,
                        ledger_id,
                    ),
                )
            else:
                # Create new ledger and link
                ledger_name = f"Customer - {customer_name}"
                ob_type = "Debit" if opening_balance >= 0 else "Credit"
                ob_amount = abs(opening_balance)

                cur.execute(
                    """INSERT INTO account_ledgers
                        (ledger_name, account_group, opening_balance,
                         opening_balance_type, credit_limit, credit_period,
                         address, city, state, contact_person, contact_no)
                    VALUES (?, 'Sundry Debtors', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ledger_name, ob_amount, ob_type,
                        credit_limit, credit_period,
                        address, city, state, contact_person, contact_no,
                    ),
                )
                ledger_id = cur.lastrowid
                cur.execute(
                    "UPDATE customers SET ledger_id = ? WHERE id = ?",
                    (ledger_id, customer_id),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete(customer_id: int) -> bool:
        """Delete customer. Does NOT delete the linked ledger if it has transactions.

        Returns True if deleted, False if blocked (ledger has transactions).
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Check if linked ledger has transactions
            row = cur.execute(
                "SELECT ledger_id FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone()

            if row and row["ledger_id"]:
                txn_count = cur.execute(
                    "SELECT COUNT(*) FROM ledger_transactions WHERE ledger_id = ?",
                    (row["ledger_id"],),
                ).fetchone()[0]
                if txn_count > 0:
                    conn.rollback()
                    return False

            cur.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
