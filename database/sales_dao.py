from __future__ import annotations

import sqlite3
from datetime import datetime
from database.connection import get_connection
from database.accounting_posting import SOURCE_COUNTER_SALE, posting_engine


class SalesDAO:
    """Data access for sales invoices, invoice items, and stock deduction."""

    # ------------------------------------------------------------------
    # Bill number generation
    # ------------------------------------------------------------------

    @staticmethod
    def display_bill_no(bill_no: str, active_fy_name: str | None = None) -> str:
        """Short display form for a stored bill number.

        Bills belonging to the active financial year that use the
        ``<FY>-<digits>`` convention (e.g. ``2026-2027-1910``) display as
        the simple sequential number (``1910``).  Every other stored value
        — older FY-prefixed bills, legacy ``Cash-`` imports, ``CS-`` bills
        and plain numbers — is returned unchanged so different financial
        years stay distinguishable.  Stored database values are never
        altered here; this is display only.
        """
        text = (bill_no or "").strip()
        if not text:
            return text
        if active_fy_name is None:
            try:
                from database import financial_year as _fy

                _active = _fy.get_active_financial_year()
                active_fy_name = (_active.get("name") if _active else "") or ""
            except Exception:
                active_fy_name = ""
        active_fy_name = (active_fy_name or "").strip()
        if active_fy_name and text.startswith(active_fy_name + "-"):
            suffix = text[len(active_fy_name) + 1 :]
            if suffix.isdigit():
                return suffix
        return text

    @staticmethod
    def generate_next_bill_no(cur: sqlite3.Cursor | None = None) -> str:
        should_close = False
        if cur is None:
            conn = get_connection()
            cur = conn.cursor()
            should_close = True
        try:
            # New bills use the simple sequential number without the
            # financial-year prefix (e.g. "1911" instead of
            # "2026-2027-1911").  The sequence continues from the highest
            # numeric suffix already used in the ACTIVE financial year plus
            # any plain numbers already saved, so 2026-2027-1910 -> 1911.
            # Historical rows are never rewritten; uniqueness is enforced by
            # the UNIQUE(bill_no) constraint plus the guard loop below.
            try:
                from database import financial_year as _fy

                _active = _fy.get_active_financial_year()
                active_name = (_active.get("name") if _active else "") or ""
            except Exception:
                active_name = ""
            active_name = (active_name or "").strip()
            max_num: int | None = None
            if active_name:
                try:
                    cur.execute(
                        "SELECT bill_no FROM sales_invoices WHERE bill_no LIKE ?",
                        (f"{active_name}-%",),
                    )
                    for r in cur.fetchall():
                        last = r["bill_no"] or ""
                        prefix = active_name + "-"
                        if last.startswith(prefix):
                            suffix = last[len(prefix) :]
                            if suffix.isdigit():
                                val = int(suffix)
                                max_num = val if max_num is None else max(max_num, val)
                except Exception:
                    pass
                try:
                    cur.execute(
                        "SELECT bill_no FROM sales_invoices "
                        "WHERE bill_no NOT GLOB '*[^0-9]*' AND bill_no != ''"
                    )
                    for r in cur.fetchall():
                        last = (r["bill_no"] or "").strip()
                        if last.isdigit():
                            val = int(last)
                            max_num = val if max_num is None else max(max_num, val)
                except Exception:
                    pass
                if max_num is not None:
                    next_num = max_num + 1
                    candidate = str(next_num)
                    cur.execute(
                        "SELECT 1 FROM sales_invoices WHERE bill_no = ? LIMIT 1",
                        (candidate,),
                    )
                    guard = 0
                    while cur.fetchone() is not None and guard < 10000:
                        next_num += 1
                        candidate = str(next_num)
                        cur.execute(
                            "SELECT 1 FROM sales_invoices WHERE bill_no = ? LIMIT 1",
                            (candidate,),
                        )
                        guard += 1
                    return candidate
            # Fallback: legacy convention (CS-0001 style) for databases with
            # no active-FY numeric history (fresh installs, isolated tests).
            cur.execute(
                "SELECT bill_no FROM sales_invoices ORDER BY id DESC LIMIT 50"
            )
            rows = cur.fetchall()
            if not rows:
                return "CS-0001"
            prefix = "CS-"
            num = None
            width = 4
            for r in rows:
                last = r["bill_no"] or ""
                idx = last.rfind("-")
                if idx >= 0:
                    cand_prefix = last[: idx + 1]
                    num_part = last[idx + 1 :]
                    if num_part.isdigit():
                        prefix = cand_prefix
                        num = int(num_part)
                        width = max(4, len(num_part))
                        break
            if num is None:
                last = rows[0]["bill_no"] or ""
                idx = last.rfind("-")
                if idx >= 0:
                    prefix = last[: idx + 1]
                    num_part = last[idx + 1 :]
                else:
                    prefix = "CS-"
                    num_part = last
                try:
                    num = int(num_part)
                    width = max(4, len(num_part))
                except ValueError:
                    num = 0
                    width = 4
            next_num = num + 1
            candidate = f"{prefix}{next_num:0{width}d}"
            cur.execute("SELECT 1 FROM sales_invoices WHERE bill_no = ? LIMIT 1", (candidate,))
            guard = 0
            while cur.fetchone() is not None and guard < 10000:
                next_num += 1
                candidate = f"{prefix}{next_num:0{width}d}"
                cur.execute("SELECT 1 FROM sales_invoices WHERE bill_no = ? LIMIT 1", (candidate,))
                guard += 1
            return candidate
        finally:
            if should_close:
                cur.connection.close()

    @staticmethod
    def bill_no_exists(bill_no: str, cur: sqlite3.Cursor | None = None) -> bool:
        """True when *bill_no* is already used by a saved invoice.

        Read-only helper for the Counter Sale multi-bill flow: an in-memory
        provisional preview is validated against this before commit, so a
        stale preview can never collide with a permanent number.
        """
        if not (bill_no or "").strip():
            return False
        should_close = False
        if cur is None:
            conn = get_connection()
            cur = conn.cursor()
            should_close = True
        try:
            cur.execute(
                "SELECT 1 FROM sales_invoices WHERE bill_no = ? LIMIT 1",
                ((bill_no or "").strip(),),
            )
            return cur.fetchone() is not None
        finally:
            if should_close:
                cur.connection.close()

    # ------------------------------------------------------------------
    # Invoice CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT si.*, c.customer_name, d.doctor_name
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                LEFT JOIN doctors d ON d.id = si.doctor_id
                ORDER BY si.id DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def _history_date_clause(start_date: str = "", end_date: str = "",
                             prefix: str = "") -> tuple[str, list]:
        """Build the inclusive sale_date range used by the history queries.

        ``prefix`` is the table alias to qualify the column with.  An empty
        bound is ignored, so empty dates simply mean "no date filter".
        """
        column = f"{prefix}sale_date" if prefix else "sale_date"
        clauses: list[str] = []
        params: list = []
        if start_date:
            clauses.append(f"{column} >= ?")
            params.append(start_date)
        if end_date:
            clauses.append(f"{column} <= ?")
            params.append(end_date)
        if not clauses:
            return "", []
        return " AND ".join(clauses), params

    @staticmethod
    def get_history_page(*, limit: int, offset: int = 0,
                         start_date: str = "", end_date: str = "") -> list[dict]:
        """Return item-wise bill-history rows for a page of invoices.

        One row per sale item, with the parent bill's number repeated on
        every item row.  ``start_date``/``end_date`` (YYYY-MM-DD, inclusive)
        optionally restrict the invoices; empty values mean no date filter.
        """
        conn = get_connection()
        try:
            date_clause, date_params = SalesDAO._history_date_clause(
                start_date, end_date
            )
            inner_where = f"WHERE {date_clause}" if date_clause else ""
            rows = conn.execute(
                f"""
                SELECT
                    si.id AS invoice_id,
                    si.bill_no,
                    si.sale_type,
                    si.patient_name,
                    si.sale_date,
                    si.sale_time,
                    si.net_amount,
                    sii.item_id,
                    i.item_name,
                    sii.mrp,
                    sii.sale_qty,
                    sii.amount,
                    sii.pack_size,
                    sii.batch_no,
                    sii.expiry,
                    sii.discount_amount
                FROM sales_invoices si
                LEFT JOIN sales_invoice_items sii
                    ON sii.sales_invoice_id = si.id
                LEFT JOIN items i ON i.id = sii.item_id
                WHERE si.id IN (
                    SELECT id FROM sales_invoices
                    {inner_where}
                    ORDER BY id DESC LIMIT ? OFFSET ?
                )
                ORDER BY si.id DESC, sii.id
                """,
                (*date_params, limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_bill_history_page(*, limit: int, offset: int = 0,
                              start_date: str = "", end_date: str = "") -> list[dict]:
        """Return bill-wise bill-history rows: exactly one row per invoice.

        Only bill-level columns are selected (no item join), so a bill can
        never be duplicated in the grid.  The item count comes from a
        correlated sub-select, not a per-bill round trip.
        """
        conn = get_connection()
        try:
            date_clause, date_params = SalesDAO._history_date_clause(
                start_date, end_date, "si."
            )
            where = f"WHERE {date_clause}" if date_clause else ""
            rows = conn.execute(
                f"""
                SELECT
                    si.id AS invoice_id,
                    si.bill_no,
                    si.sale_type,
                    si.patient_name,
                    si.sale_date,
                    si.sale_time,
                    si.total_amount,
                    si.discount,
                    si.paid_amount,
                    si.round_off,
                    si.net_amount,
                    (
                        SELECT COUNT(*)
                        FROM sales_invoice_items sii
                        WHERE sii.sales_invoice_id = si.id
                    ) AS item_count
                FROM sales_invoices si
                {where}
                ORDER BY si.id DESC
                LIMIT ? OFFSET ?
                """,
                (*date_params, limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(invoice_id: int) -> dict | None:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT si.*, c.customer_name, d.doctor_name
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                LEFT JOIN doctors d ON d.id = si.doctor_id
                WHERE si.id = ?
                """,
                (invoice_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_invoice_items(invoice_id: int) -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sii.*, i.item_name
                FROM sales_invoice_items sii
                LEFT JOIN items i ON i.id = sii.item_id
                WHERE sii.sales_invoice_id = ?
                ORDER BY sii.id
                """,
                (invoice_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_all_filtered(start_date: str = "", end_date: str = "",
                         customer_id: int | None = None) -> list[dict]:
        conn = get_connection()
        try:
            clauses: list[str] = []
            params: list = []
            if start_date:
                clauses.append("si.sale_date >= ?")
                params.append(start_date)
            if end_date:
                clauses.append("si.sale_date <= ?")
                params.append(end_date)
            if customer_id is not None:
                clauses.append("si.customer_id = ?")
                params.append(customer_id)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            cur = conn.execute(
                f"""
                SELECT si.*, c.customer_name, d.doctor_name
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                LEFT JOIN doctors d ON d.id = si.doctor_id
                {where}
                ORDER BY si.id DESC
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def insert_invoice(*, bill_no: str, sale_date: str, sale_time: str,
                       sale_type: str, customer_id: int | None,
                       patient_name: str, doctor_id: int | None,
                       discount: float, paid_amount: float,
                       total_amount: float, round_off: float,
                       net_amount: float, remarks: str,
                       items: list[dict]) -> int:
        """Insert sales invoice + items + stock deduction in a single transaction.

        Each dict in *items* must contain:
        item_id, stock_batch_id, pack_size, location, batch_no, expiry,
        mrp, sale_qty, discount_amount, amount.
        Returns the new invoice id.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")

            # Transactional uniqueness check: if bill_no already exists,
            # advance to the next sequential free bill_no within this transaction.
            guard = 0
            while guard < 10000:
                cur.execute("SELECT 1 FROM sales_invoices WHERE bill_no = ? LIMIT 1", (bill_no,))
                if cur.fetchone() is None:
                    break
                bill_no = SalesDAO.generate_next_bill_no(cur=cur)
                guard += 1

            # Insert invoice header
            cur.execute(
                """
                INSERT INTO sales_invoices (
                    bill_no, sale_date, sale_time, sale_type,
                    customer_id, patient_name, doctor_id,
                    discount, paid_amount, total_amount, round_off,
                    net_amount, remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bill_no, sale_date, sale_time, sale_type,
                    customer_id, patient_name, doctor_id,
                    discount, paid_amount, total_amount, round_off,
                    net_amount, remarks,
                ),
            )
            invoice_id = cur.lastrowid

            # Insert items and deduct stock
            for item in items:
                cur.execute(
                    """
                    INSERT INTO sales_invoice_items (
                        sales_invoice_id, item_id, stock_batch_id,
                        pack_size, location, batch_no, expiry,
                        mrp, sale_qty, discount_amount, amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id, item["item_id"], item["stock_batch_id"],
                        item.get("pack_size", ""), item.get("location", ""),
                        item["batch_no"], item.get("expiry", ""),
                        item["mrp"], item["sale_qty"],
                        item.get("discount_amount", 0.0), item["amount"],
                    ),
                )

                # Verify stock, expiry and deduct
                cur.execute(
                    "SELECT id, stock_qty, expiry FROM stock_batches WHERE id = ?",
                    (item["stock_batch_id"],),
                )
                batch = cur.fetchone()
                if not batch:
                    raise ValueError(
                        f"Stock batch id {item['stock_batch_id']} not found."
                    )
                if SalesDAO.is_expired(batch["expiry"] or ""):
                    raise ValueError(
                        f"Batch {item['batch_no']} expired on "
                        f"{batch['expiry']}; expired stock cannot be sold."
                    )
                if batch["stock_qty"] < item["sale_qty"]:
                    raise ValueError(
                        f"Insufficient stock for batch {item['batch_no']}. "
                        f"Available: {batch['stock_qty']}, Requested: {item['sale_qty']}"
                    )
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                    (item["sale_qty"], item["stock_batch_id"]),
                )

            # Accounting posting joins THIS transaction (atomic with save).
            posting_engine.post_counter_sale(invoice_id, cur=cur)

            conn.commit()
            return invoice_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_invoice(*, invoice_id: int, bill_no: str, sale_date: str,
                       sale_time: str, sale_type: str,
                       customer_id: int | None, patient_name: str,
                       doctor_id: int | None, discount: float,
                       paid_amount: float, total_amount: float,
                       round_off: float, net_amount: float, remarks: str,
                       items: list[dict]) -> None:
        """Update sale header/items, adjust stock, and repost accounting.

        Runs in ONE transaction:
            1. Reverse the previous accounting posting (no-op if the
               sale was never posted).
            2. Reverse the previous stock deduction.
            3. Replace the item rows.
            4. Update the header.
            5. Insert new items and deduct stock (same checks as
               insert_invoice).
            6. Post the updated accounting effect.
        Any failure rolls back everything (sale, stock, accounting).
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse previous accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_COUNTER_SALE, invoice_id, cur=cur)

            # Reverse previous stock deduction
            cur.execute(
                "SELECT stock_batch_id, sale_qty FROM sales_invoice_items "
                "WHERE sales_invoice_id = ?",
                (invoice_id,),
            )
            for old in cur.fetchall():
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? "
                    "WHERE id = ?",
                    (old["sale_qty"], old["stock_batch_id"]),
                )

            # Replace item rows
            cur.execute(
                "DELETE FROM sales_invoice_items WHERE sales_invoice_id = ?",
                (invoice_id,),
            )

            # Update header
            cur.execute(
                """
                UPDATE sales_invoices SET
                    bill_no = ?, sale_date = ?, sale_time = ?, sale_type = ?,
                    customer_id = ?, patient_name = ?, doctor_id = ?,
                    discount = ?, paid_amount = ?, total_amount = ?,
                    round_off = ?, net_amount = ?, remarks = ?
                WHERE id = ?
                """,
                (
                    bill_no, sale_date, sale_time, sale_type,
                    customer_id, patient_name, doctor_id,
                    discount, paid_amount, total_amount, round_off,
                    net_amount, remarks, invoice_id,
                ),
            )

            # Insert new items and deduct stock (same checks as insert)
            for item in items:
                cur.execute(
                    """
                    INSERT INTO sales_invoice_items (
                        sales_invoice_id, item_id, stock_batch_id,
                        pack_size, location, batch_no, expiry,
                        mrp, sale_qty, discount_amount, amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id, item["item_id"], item["stock_batch_id"],
                        item.get("pack_size", ""), item.get("location", ""),
                        item["batch_no"], item.get("expiry", ""),
                        item["mrp"], item["sale_qty"],
                        item.get("discount_amount", 0.0), item["amount"],
                    ),
                )
                cur.execute(
                    "SELECT id, stock_qty, expiry FROM stock_batches WHERE id = ?",
                    (item["stock_batch_id"],),
                )
                batch = cur.fetchone()
                if not batch:
                    raise ValueError(
                        f"Stock batch id {item['stock_batch_id']} not found."
                    )
                if SalesDAO.is_expired(batch["expiry"] or ""):
                    raise ValueError(
                        f"Batch {item['batch_no']} expired on "
                        f"{batch['expiry']}; expired stock cannot be sold."
                    )
                if batch["stock_qty"] < item["sale_qty"]:
                    raise ValueError(
                        f"Insufficient stock for batch {item['batch_no']}. "
                        f"Available: {batch['stock_qty']}, Requested: {item['sale_qty']}"
                    )
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                    (item["sale_qty"], item["stock_batch_id"]),
                )

            # Post the updated accounting effect inside THIS transaction
            posting_engine.post_counter_sale(invoice_id, cur=cur)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_invoice(invoice_id: int) -> None:
        """Delete sales invoice, restore stock, and clean up empty batches."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Restore stock for each item
            cur.execute(
                "SELECT stock_batch_id, sale_qty FROM sales_invoice_items WHERE sales_invoice_id = ?",
                (invoice_id,),
            )
            for old in cur.fetchall():
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                    (old["sale_qty"], old["stock_batch_id"]),
                )

            # Reverse the accounting posting inside THIS transaction so no
            # active accounting effect survives the deletion (no-op for
            # sales that were never posted).
            posting_engine.reverse(SOURCE_COUNTER_SALE, invoice_id, cur=cur)

            # Delete items
            cur.execute(
                "DELETE FROM sales_invoice_items WHERE sales_invoice_id = ?",
                (invoice_id,),
            )
            # Delete invoice
            cur.execute("DELETE FROM sales_invoices WHERE id = ?", (invoice_id,))

            # NOTE: zero/negative stock batches are intentionally preserved:
            # historical sales/return rows reference them, negative balances
            # are legitimate exceptions, and depleted batches remain visible
            # in the Expiry Report / stock master for write-off.

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Stock batch helpers (for item selection in counter sale)
    # ------------------------------------------------------------------

    @staticmethod
    def get_stock_batches_for_item(item_id: int) -> list[dict]:
        """Return the batches an item can actually be sold from.

        A batch is offerable only when it holds stock **and** has not
        expired.  Expired stock is never offered for a new sale: it stays
        visible in the Expiry Report and the stock master so it can be
        written off, but it never reaches the Counter Sale batch list.

        Batches come back in expiry order (first-expiry-first-out), so
        keyboard selection (Down, Enter) and the batch popup always reach
        a batch that can actually be sold.
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sb.*, i.item_name, i.location
                FROM stock_batches sb
                LEFT JOIN items i ON i.id = sb.item_id
                WHERE sb.item_id = ? AND sb.stock_qty > 0
                ORDER BY sb.expiry, sb.batch_no
                """,
                (item_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        batches = [
            b for b in rows
            if not SalesDAO.is_expired(b.get("expiry") or "")
        ]
        batches.sort(
            key=lambda b: (b.get("expiry") or "", b.get("batch_no") or "")
        )
        return batches

    @staticmethod
    def get_all_stock_batches() -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sb.*, i.item_name, i.location
                FROM stock_batches sb
                LEFT JOIN items i ON i.id = sb.item_id
                WHERE sb.stock_qty > 0
                ORDER BY i.item_name, sb.batch_no
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def is_expired(expiry: str) -> bool:
        """Check migrated YYYY-MM-DD and legacy MM/YY expiry values."""
        if not expiry:
            return False
        value = expiry.strip()
        try:
            expiry_date = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            try:
                month_text, year_text = value.split("/", 1)
                expiry_date = datetime(
                    2000 + int(year_text), int(month_text), 1
                ).date()
            except (ValueError, IndexError):
                return False
        return expiry_date < datetime.now().date()

    @staticmethod
    def get_total_stock_for_item(item_id: int) -> float:
        """Return total stock across all batches for an item."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT COALESCE(SUM(stock_qty), 0) as total FROM stock_batches WHERE item_id = ?",
                (item_id,),
            )
            row = cur.fetchone()
            return float(row["total"]) if row else 0.0
        finally:
            conn.close()

    @staticmethod
    def get_batch_by_id(batch_id: int) -> dict | None:
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM stock_batches WHERE id = ?", (batch_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_batch_by_item_and_batch_no(item_id: int, batch_no: str) -> dict | None:
        """Find a stock batch by item_id and batch_no (for hold bill resume)."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM stock_batches WHERE item_id = ? AND batch_no = ?",
                (item_id, batch_no),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def search_sales_history(
        *,
        patient_name: str = "",
        customer_name: str = "",
        customer_id: int | None = None,
        bill_no: str = "",
        start_date: str = "",
        end_date: str = "",
        doctor_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Search sales history across financial years with pagination.

        Returns (rows, total_count).
        """
        conn = get_connection()
        try:
            clauses: list[str] = []
            params: list = []
            if patient_name and patient_name.strip():
                clauses.append("si.patient_name LIKE ?")
                params.append(f"%{patient_name.strip()}%")
            if customer_id is not None:
                clauses.append("si.customer_id = ?")
                params.append(customer_id)
            elif customer_name and customer_name.strip():
                clauses.append("c.customer_name LIKE ?")
                params.append(f"%{customer_name.strip()}%")
            if bill_no and bill_no.strip():
                clauses.append("si.bill_no LIKE ?")
                params.append(f"%{bill_no.strip()}%")
            if start_date and start_date.strip():
                clauses.append("si.sale_date >= ?")
                params.append(start_date.strip())
            if end_date and end_date.strip():
                clauses.append("si.sale_date <= ?")
                params.append(end_date.strip())
            if doctor_id is not None:
                clauses.append("si.doctor_id = ?")
                params.append(doctor_id)

            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

            count_cur = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                {where}
                """,
                params,
            )
            total_count = count_cur.fetchone()[0]

            cur = conn.execute(
                f"""
                SELECT si.id, si.bill_no, si.sale_date, si.sale_time, si.sale_type,
                       si.customer_id, c.customer_name, si.patient_name,
                       si.doctor_id, d.doctor_name,
                       si.total_amount, si.discount, si.paid_amount,
                       si.round_off, si.net_amount, si.remarks
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                LEFT JOIN doctors d ON d.id = si.doctor_id
                {where}
                ORDER BY si.sale_date DESC, si.id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            )
            rows = [dict(r) for r in cur.fetchall()]
            return rows, total_count
        finally:
            conn.close()

    @staticmethod
    def get_distinct_patient_names(search: str = "", limit: int = 50) -> list[str]:
        """Return distinct non-empty patient names for compact autocomplete."""
        conn = get_connection()
        try:
            if search and search.strip():
                cur = conn.execute(
                    """
                    SELECT DISTINCT patient_name FROM sales_invoices
                    WHERE patient_name IS NOT NULL AND patient_name != ''
                      AND patient_name LIKE ?
                    ORDER BY patient_name LIMIT ?
                    """,
                    (f"%{search.strip()}%", limit),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT DISTINCT patient_name FROM sales_invoices
                    WHERE patient_name IS NOT NULL AND patient_name != ''
                    ORDER BY patient_name LIMIT ?
                    """,
                    (limit,),
                )
            return [r[0] for r in cur.fetchall() if r[0]]
        finally:
            conn.close()
