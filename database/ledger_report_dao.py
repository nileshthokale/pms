"""Data access object for detailed ledger reports.

Provides transaction retrieval and balance calculation for:
1. Supplier Ledger (based on suppliers.ledger_id -> ledger_transactions)
2. Customer Ledger (based on customers.ledger_id -> ledger_transactions)
3. Itemwise Ledger (inventory transactions from purchase/sale/returns)

Conventions:
- Balance calculation strictly follows accounting standard and existing LedgerDAO:
  diff = debit - credit. diff >= 0 -> Debit (DR), diff < 0 -> Credit (CR).
- All stock movements use loose unit conventions:
  Purchase pay_qty/free_qty are packs, multiplied by pack_factor(pack_size).
  Sale and return quantities are loose units.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from database.connection import get_connection
from database.purchase_dao import pack_factor


class LedgerReportError(ValueError):
    """Raised when ledger report parameters are invalid."""


def _validate_dates(from_date: str, to_date: str) -> None:
    try:
        start = datetime.strptime(str(from_date), "%Y-%m-%d")
        end = datetime.strptime(str(to_date), "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise LedgerReportError("Dates must use YYYY-MM-DD format.") from exc
    if start > end:
        raise LedgerReportError("From Date must be on or before To Date.")


class LedgerReportDAO:
    """Read-only DAO for Supplier, Customer, and Itemwise detailed ledgers."""

    # ── Master options for dropdown selectors ──────────────────────────

    @staticmethod
    def get_supplier_options() -> list[dict[str, Any]]:
        """Return all suppliers ordered by name for dropdown selection."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT s.id, s.supplier_name, s.city, s.contact_no, s.ledger_id,
                       al.ledger_name
                FROM suppliers s
                LEFT JOIN account_ledgers al ON al.id = s.ledger_id
                ORDER BY s.supplier_name COLLATE NOCASE
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_customer_options() -> list[dict[str, Any]]:
        """Return all customers ordered by name for dropdown selection."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT c.id, c.customer_name, c.city, c.contact_no, c.ledger_id,
                       al.ledger_name
                FROM customers c
                LEFT JOIN account_ledgers al ON al.id = c.ledger_id
                ORDER BY c.customer_name COLLATE NOCASE
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_item_options() -> list[dict[str, Any]]:
        """Return all items ordered by name for dropdown selection."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT i.id, i.item_name, i.pack_size,
                       c.company_name, u.unit_name
                FROM items i
                LEFT JOIN companies c ON c.id = i.company_id
                LEFT JOIN units u ON u.id = i.unit_id
                ORDER BY i.item_name COLLATE NOCASE
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # ── Enrich particulars helper ─────────────────────────────────────

    @staticmethod
    def _enrich_particulars(conn, row: dict) -> str:
        """Resolve a human-readable particulars string for a ledger transaction."""
        desc = (row.get("description") or "").strip()
        if desc:
            return desc

        vtype = row.get("voucher_type") or "Transaction"
        vno = row.get("voucher_no") or ""
        ref_type = row.get("reference_type") or ""
        ref_id = row.get("reference_id")

        if ref_type == "PURCHASE_INVOICE" and ref_id:
            inv = conn.execute(
                "SELECT invoice_no FROM purchase_invoices WHERE id = ?", (ref_id,)
            ).fetchone()
            if inv and inv["invoice_no"]:
                return f"Purchase Inv #{inv['invoice_no']}"
            return f"Purchase Invoice {vno}".strip()

        if ref_type == "COUNTER_SALE" and ref_id:
            sale = conn.execute(
                "SELECT patient_name FROM sales_invoices WHERE id = ?", (ref_id,)
            ).fetchone()
            if sale and sale["patient_name"]:
                return f"Sale - {sale['patient_name']}"
            return f"Counter Sale {vno}".strip()

        if ref_type == "SUPPLIER_PAYMENT" and ref_id:
            sp = conn.execute(
                "SELECT payment_mode, reference_no FROM supplier_payments WHERE id = ?", (ref_id,)
            ).fetchone()
            if sp:
                parts = ["Payment", f"({sp['payment_mode']})"]
                if sp["reference_no"]:
                    parts.append(sp["reference_no"])
                return " ".join(parts)
            return f"Supplier Payment {vno}".strip()

        if ref_type == "CUSTOMER_RECEIPT" and ref_id:
            cr = conn.execute(
                "SELECT receipt_mode, reference_no FROM customer_receipts WHERE id = ?", (ref_id,)
            ).fetchone()
            if cr:
                parts = ["Receipt", f"({cr['receipt_mode']})"]
                if cr["reference_no"]:
                    parts.append(cr["reference_no"])
                return " ".join(parts)
            return f"Customer Receipt {vno}".strip()

        if ref_type == "CREDIT_NOTE" and ref_id:
            cn = conn.execute(
                "SELECT remarks FROM credit_notes WHERE id = ?", (ref_id,)
            ).fetchone()
            if cn and cn["remarks"]:
                return f"Credit Note - {cn['remarks']}"
            return f"Credit Note {vno}".strip()

        if ref_type == "DEBIT_NOTE" and ref_id:
            dn = conn.execute(
                "SELECT remarks FROM debit_notes WHERE id = ?", (ref_id,)
            ).fetchone()
            if dn and dn["remarks"]:
                return f"Debit Note - {dn['remarks']}"
            return f"Debit Note {vno}".strip()

        if ref_type == "JOURNAL_ENTRY" and ref_id:
            je = conn.execute(
                "SELECT narration FROM journal_entries WHERE id = ?", (ref_id,)
            ).fetchone()
            if je and je["narration"]:
                return f"Journal - {je['narration']}"
            return f"Journal Entry {vno}".strip()

        return f"{vtype} {vno}".strip()

    # ── Supplier Ledger ────────────────────────────────────────────────

    @staticmethod
    def get_supplier_ledger(
        supplier_id: int, from_date: str, to_date: str
    ) -> dict[str, Any]:
        """Detailed Supplier Ledger for a date range with running balance.

        Returns:
            supplier: dict of supplier master info
            ledger: dict of account_ledgers record
            from_date: str
            to_date: str
            opening_balance: float
            opening_balance_type: 'DR' or 'CR'
            rows: list of transaction dicts:
                - transaction_date
                - transaction_time
                - particulars
                - voucher_type
                - voucher_no
                - debit
                - credit
                - running_balance
                - running_balance_type
                - reference_type
                - reference_id
            total_debit: float
            total_credit: float
            closing_balance: float
            closing_balance_type: 'DR' or 'CR'
            warning: Optional[str]
        """
        _validate_dates(from_date, to_date)
        conn = get_connection()
        try:
            supp = conn.execute(
                """
                SELECT s.*, al.ledger_name, al.account_group
                FROM suppliers s
                LEFT JOIN account_ledgers al ON al.id = s.ledger_id
                WHERE s.id = ?
                """,
                (supplier_id,),
            ).fetchone()

            if not supp:
                raise LedgerReportError(f"Supplier ID {supplier_id} was not found.")

            supp_dict = dict(supp)
            ledger_id = supp_dict.get("ledger_id")

            if not ledger_id:
                return {
                    "supplier": supp_dict,
                    "ledger": None,
                    "from_date": from_date,
                    "to_date": to_date,
                    "opening_balance": 0.0,
                    "opening_balance_type": "CR",
                    "rows": [],
                    "total_debit": 0.0,
                    "total_credit": 0.0,
                    "closing_balance": 0.0,
                    "closing_balance_type": "CR",
                    "warning": f"Supplier '{supp_dict['supplier_name']}' has no linked Account Ledger in master data.",
                }

            ledger_row = conn.execute(
                "SELECT * FROM account_ledgers WHERE id = ?", (ledger_id,)
            ).fetchone()

            if not ledger_row:
                return {
                    "supplier": supp_dict,
                    "ledger": None,
                    "from_date": from_date,
                    "to_date": to_date,
                    "opening_balance": 0.0,
                    "opening_balance_type": "CR",
                    "rows": [],
                    "total_debit": 0.0,
                    "total_credit": 0.0,
                    "closing_balance": 0.0,
                    "closing_balance_type": "CR",
                    "warning": f"Linked Account Ledger ID {ledger_id} was not found in database.",
                }

            ledger_dict = dict(ledger_row)
            master_ob = ledger_dict.get("opening_balance", 0.0) or 0.0
            master_ob_type = ledger_dict.get("opening_balance_type", "Credit") or "Credit"
            normal_type = "CR" if master_ob_type.lower().startswith("c") else "DR"

            # 1. Opening balance as of from_date:
            # Net signed balance before from_date: Debit is positive, Credit is negative.
            prior = conn.execute(
                """
                SELECT COALESCE(SUM(debit), 0.0) AS d,
                       COALESCE(SUM(credit), 0.0) AS c
                FROM ledger_transactions
                WHERE ledger_id = ? AND transaction_date < ?
                """,
                (ledger_id, from_date),
            ).fetchone()

            debit_before = (master_ob if master_ob_type == "Debit" else 0.0) + (prior["d"] or 0.0)
            credit_before = (master_ob if master_ob_type == "Credit" else 0.0) + (prior["c"] or 0.0)
            net_running = debit_before - credit_before

            opening_bal = round(abs(net_running), 2)
            if opening_bal == 0.0:
                opening_bal_type = normal_type
            else:
                opening_bal_type = "DR" if net_running > 0 else "CR"

            # 2. Transactions within [from_date, to_date]:
            txn_rows = conn.execute(
                """
                SELECT id, ledger_id, transaction_date, transaction_time,
                       voucher_type, voucher_no, reference_type,
                       reference_id, description, debit, credit
                FROM ledger_transactions
                WHERE ledger_id = ? AND transaction_date >= ? AND transaction_date <= ?
                ORDER BY transaction_date, transaction_time, id
                """,
                (ledger_id, from_date, to_date),
            ).fetchall()

            rows = []
            period_debit = 0.0
            period_credit = 0.0

            for r in txn_rows:
                rd = dict(r)
                d = float(rd.get("debit") or 0.0)
                c = float(rd.get("credit") or 0.0)
                period_debit += d
                period_credit += c
                net_running = net_running + d - c

                bal_amount = round(abs(net_running), 2)
                if bal_amount == 0.0:
                    bal_type = normal_type
                else:
                    bal_type = "DR" if net_running > 0 else "CR"

                particulars = LedgerReportDAO._enrich_particulars(conn, rd)

                rows.append({
                    "id": rd["id"],
                    "transaction_date": rd.get("transaction_date", ""),
                    "transaction_time": rd.get("transaction_time", ""),
                    "particulars": particulars,
                    "voucher_type": rd.get("voucher_type", ""),
                    "voucher_no": rd.get("voucher_no", ""),
                    "debit": d,
                    "credit": c,
                    "running_balance": bal_amount,
                    "running_balance_type": bal_type,
                    "reference_type": rd.get("reference_type", ""),
                    "reference_id": rd.get("reference_id"),
                })

            closing_bal = round(abs(net_running), 2)
            if closing_bal == 0.0:
                closing_bal_type = normal_type
            else:
                closing_bal_type = "DR" if net_running > 0 else "CR"

            return {
                "supplier": supp_dict,
                "ledger": ledger_dict,
                "from_date": from_date,
                "to_date": to_date,
                "opening_balance": opening_bal,
                "opening_balance_type": opening_bal_type,
                "rows": rows,
                "total_debit": round(period_debit, 2),
                "total_credit": round(period_credit, 2),
                "closing_balance": closing_bal,
                "closing_balance_type": closing_bal_type,
                "warning": None,
            }
        finally:
            conn.close()

    # ── Customer Ledger ────────────────────────────────────────────────

    @staticmethod
    def get_customer_ledger(
        customer_id: int, from_date: str, to_date: str
    ) -> dict[str, Any]:
        """Detailed Customer Ledger for a date range with running balance.

        Returns:
            customer: dict of customer master info
            ledger: dict of account_ledgers record
            from_date: str
            to_date: str
            opening_balance: float
            opening_balance_type: 'DR' or 'CR'
            rows: list of transaction dicts
            total_debit: float
            total_credit: float
            closing_balance: float
            closing_balance_type: 'DR' or 'CR'
            warning: Optional[str]
        """
        _validate_dates(from_date, to_date)
        conn = get_connection()
        try:
            cust = conn.execute(
                """
                SELECT c.*, al.ledger_name, al.account_group
                FROM customers c
                LEFT JOIN account_ledgers al ON al.id = c.ledger_id
                WHERE c.id = ?
                """,
                (customer_id,),
            ).fetchone()

            if not cust:
                raise LedgerReportError(f"Customer ID {customer_id} was not found.")

            cust_dict = dict(cust)
            ledger_id = cust_dict.get("ledger_id")

            if not ledger_id:
                return {
                    "customer": cust_dict,
                    "ledger": None,
                    "from_date": from_date,
                    "to_date": to_date,
                    "opening_balance": 0.0,
                    "opening_balance_type": "DR",
                    "rows": [],
                    "total_debit": 0.0,
                    "total_credit": 0.0,
                    "closing_balance": 0.0,
                    "closing_balance_type": "DR",
                    "warning": f"Customer '{cust_dict['customer_name']}' has no linked Account Ledger in master data.",
                }

            ledger_row = conn.execute(
                "SELECT * FROM account_ledgers WHERE id = ?", (ledger_id,)
            ).fetchone()

            if not ledger_row:
                return {
                    "customer": cust_dict,
                    "ledger": None,
                    "from_date": from_date,
                    "to_date": to_date,
                    "opening_balance": 0.0,
                    "opening_balance_type": "DR",
                    "rows": [],
                    "total_debit": 0.0,
                    "total_credit": 0.0,
                    "closing_balance": 0.0,
                    "closing_balance_type": "DR",
                    "warning": f"Linked Account Ledger ID {ledger_id} was not found in database.",
                }

            ledger_dict = dict(ledger_row)
            master_ob = ledger_dict.get("opening_balance", 0.0) or 0.0
            master_ob_type = ledger_dict.get("opening_balance_type", "Debit") or "Debit"
            normal_type = "DR" if master_ob_type.lower().startswith("d") else "CR"

            # 1. Opening balance as of from_date:
            prior = conn.execute(
                """
                SELECT COALESCE(SUM(debit), 0.0) AS d,
                       COALESCE(SUM(credit), 0.0) AS c
                FROM ledger_transactions
                WHERE ledger_id = ? AND transaction_date < ?
                """,
                (ledger_id, from_date),
            ).fetchone()

            debit_before = (master_ob if master_ob_type == "Debit" else 0.0) + (prior["d"] or 0.0)
            credit_before = (master_ob if master_ob_type == "Credit" else 0.0) + (prior["c"] or 0.0)
            net_running = debit_before - credit_before

            opening_bal = round(abs(net_running), 2)
            if opening_bal == 0.0:
                opening_bal_type = normal_type
            else:
                opening_bal_type = "DR" if net_running > 0 else "CR"

            # 2. Transactions within [from_date, to_date]:
            txn_rows = conn.execute(
                """
                SELECT id, ledger_id, transaction_date, transaction_time,
                       voucher_type, voucher_no, reference_type,
                       reference_id, description, debit, credit
                FROM ledger_transactions
                WHERE ledger_id = ? AND transaction_date >= ? AND transaction_date <= ?
                ORDER BY transaction_date, transaction_time, id
                """,
                (ledger_id, from_date, to_date),
            ).fetchall()

            rows = []
            period_debit = 0.0
            period_credit = 0.0

            for r in txn_rows:
                rd = dict(r)
                d = float(rd.get("debit") or 0.0)
                c = float(rd.get("credit") or 0.0)
                period_debit += d
                period_credit += c
                net_running = net_running + d - c

                bal_amount = round(abs(net_running), 2)
                if bal_amount == 0.0:
                    bal_type = normal_type
                else:
                    bal_type = "DR" if net_running > 0 else "CR"

                particulars = LedgerReportDAO._enrich_particulars(conn, rd)

                rows.append({
                    "id": rd["id"],
                    "transaction_date": rd.get("transaction_date", ""),
                    "transaction_time": rd.get("transaction_time", ""),
                    "particulars": particulars,
                    "voucher_type": rd.get("voucher_type", ""),
                    "voucher_no": rd.get("voucher_no", ""),
                    "debit": d,
                    "credit": c,
                    "running_balance": bal_amount,
                    "running_balance_type": bal_type,
                    "reference_type": rd.get("reference_type", ""),
                    "reference_id": rd.get("reference_id"),
                })

            closing_bal = round(abs(net_running), 2)
            if closing_bal == 0.0:
                closing_bal_type = normal_type
            else:
                closing_bal_type = "DR" if net_running > 0 else "CR"

            return {
                "customer": cust_dict,
                "ledger": ledger_dict,
                "from_date": from_date,
                "to_date": to_date,
                "opening_balance": opening_bal,
                "opening_balance_type": opening_bal_type,
                "rows": rows,
                "total_debit": round(period_debit, 2),
                "total_credit": round(period_credit, 2),
                "closing_balance": closing_bal,
                "closing_balance_type": closing_bal_type,
                "warning": None,
            }
        finally:
            conn.close()

    # ── Itemwise Ledger ────────────────────────────────────────────────

    @staticmethod
    def reconcile_item_baseline_stock(
        conn: Any = None,
        overwrite: bool = False,
    ) -> int:
        """Compute and record baseline opening stock for items from batch stock and lifetime transactions.

        Formula:
            Baseline Stock = Current Batch Stock - (All Lifetime Inward - All Lifetime Outward)

        This guarantees the inventory identity:
            Opening Stock + Lifetime Inward - Lifetime Outward = Current Batch Stock
        """
        own_conn = conn is None
        if own_conn:
            conn = get_connection()
        try:
            # 1. Existing records check
            existing_ids = set()
            if not overwrite:
                try:
                    rows = conn.execute("SELECT item_id FROM item_opening_balances").fetchall()
                    existing_ids = {r[0] for r in rows}
                except Exception:
                    pass

            # 2. Get all items
            items = conn.execute("SELECT id, pack_size FROM items").fetchall()
            if not items:
                return 0

            # 3. Sum batch stock per item
            batch_stocks = dict(
                conn.execute(
                    "SELECT item_id, COALESCE(SUM(stock_qty), 0.0) FROM stock_batches GROUP BY item_id"
                ).fetchall()
            )

            # 4. Purchases inward per item
            pur_in = defaultdict(float)
            for p in conn.execute("SELECT item_id, pack_size, pay_qty, free_qty FROM purchase_invoice_items").fetchall():
                factor = pack_factor(p["pack_size"])
                pur_in[p["item_id"]] += round((float(p["pay_qty"] or 0.0) + float(p["free_qty"] or 0.0)) * factor, 2)

            # 5. Sales outward per item
            sal_out = defaultdict(float)
            for s in conn.execute("SELECT item_id, sale_qty FROM sales_invoice_items").fetchall():
                sal_out[s["item_id"]] += round(float(s["sale_qty"] or 0.0), 2)

            # 6. Credit notes inward per item
            cn_in = defaultdict(float)
            for c in conn.execute("SELECT item_id, return_qty FROM credit_note_items").fetchall():
                cn_in[c["item_id"]] += round(float(c["return_qty"] or 0.0), 2)

            # 7. Debit notes outward per item
            dn_out = defaultdict(float)
            dni_cols = {row[1] for row in conn.execute("PRAGMA table_info(debit_note_items)").fetchall()}
            has_free = "free_qty" in dni_cols
            has_pack = "is_pack_qty" in dni_cols
            query_dn = f"""
                SELECT item_id, pack_size, return_qty
                       {', free_qty' if has_free else ''}
                       {', is_pack_qty' if has_pack else ''}
                FROM debit_note_items
            """
            for d in conn.execute(query_dn).fetchall():
                f_qty = float(d["free_qty"] or 0.0) if has_free else 0.0
                is_pk = bool(d["is_pack_qty"]) if has_pack else False
                factor = pack_factor(d["pack_size"]) if is_pk else 1.0
                dn_out[d["item_id"]] += round((float(d["return_qty"] or 0.0) + f_qty) * factor, 2)

            # 8. Compute baseline and write
            updated_count = 0
            for it in items:
                iid = it["id"]
                if not overwrite and iid in existing_ids:
                    continue

                cbs = round(float(batch_stocks.get(iid, 0.0)), 2)
                tot_in = round(pur_in[iid] + cn_in[iid], 2)
                tot_out = round(sal_out[iid] + dn_out[iid], 2)
                lifetime_net = round(tot_in - tot_out, 2)
                baseline = round(cbs - lifetime_net, 2)

                try:
                    conn.execute(
                        """
                        INSERT INTO item_opening_balances (item_id, opening_date, opening_stock, source, notes)
                        VALUES (?, '2015-04-01', ?, 'reconstructed_baseline', 'Baseline stock reconstructed from batch on-hand stock and lifetime movements')
                        ON CONFLICT(item_id, opening_date) DO UPDATE SET
                            opening_stock = excluded.opening_stock,
                            source = excluded.source,
                            notes = excluded.notes
                        """,
                        (iid, baseline),
                    )
                except Exception:
                    pass

                try:
                    conn.execute(
                        "UPDATE items SET opening_stock = ? WHERE id = ?",
                        (baseline, iid),
                    )
                except Exception:
                    pass
                updated_count += 1

            if own_conn:
                conn.commit()
            return updated_count
        finally:
            if own_conn:
                conn.close()

    @staticmethod
    def get_item_ledger(
        item_id: int, from_date: str, to_date: str
    ) -> dict[str, Any]:
        """Detailed Itemwise inventory ledger showing chronological stock movements.

        Returns:
            item: dict of item master fields
            from_date: str
            to_date: str
            opening_stock: float (loose units as of from_date)
            rows: list of movement dicts:
                - date
                - time
                - particulars
                - voucher_no
                - voucher_type
                - batch_no
                - expiry
                - inward_qty (loose units)
                - outward_qty (loose units)
                - closing_stock (running stock in loose units)
                - reference
            total_inward: float
            total_outward: float
            closing_stock: float
            current_batch_stock: float (total stock currently on hand in stock_batches)
            warning: Optional[str]
        """
        _validate_dates(from_date, to_date)
        conn = get_connection()
        try:
            item_row = conn.execute(
                """
                SELECT i.*, c.company_name, u.unit_name
                FROM items i
                LEFT JOIN companies c ON c.id = i.company_id
                LEFT JOIN units u ON u.id = i.unit_id
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()

            if not item_row:
                raise LedgerReportError(f"Item ID {item_id} was not found.")

            item_dict = dict(item_row)

            # Current on-hand stock across all batches in stock_batches:
            batch_stock_row = conn.execute(
                "SELECT COALESCE(SUM(stock_qty), 0.0) AS total_stock FROM stock_batches WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            current_batch_stock = round(batch_stock_row["total_stock"] or 0.0, 2)

            # Baseline opening stock from item_opening_balances or items table:
            baseline_stock = 0.0
            baseline_date = "2015-04-01"
            try:
                ob_row = conn.execute(
                    """
                    SELECT opening_stock, opening_date
                    FROM item_opening_balances
                    WHERE item_id = ?
                    ORDER BY opening_date ASC
                    LIMIT 1
                    """,
                    (item_id,),
                ).fetchone()
                if ob_row is not None:
                    baseline_stock = float(ob_row["opening_stock"] or 0.0)
                    baseline_date = ob_row["opening_date"] or "2015-04-01"
                elif "opening_stock" in item_dict and item_dict["opening_stock"] is not None:
                    baseline_stock = float(item_dict["opening_stock"] or 0.0)
            except Exception:
                if "opening_stock" in item_dict and item_dict["opening_stock"] is not None:
                    baseline_stock = float(item_dict["opening_stock"] or 0.0)

            all_movements: list[dict[str, Any]] = []

            # 1. Purchases (Inward)
            purchases = conn.execute(
                """
                SELECT
                    pi.voucher_date AS txn_date,
                    pi.voucher_time AS txn_time,
                    pi.id AS ref_id,
                    'PURCHASE_INVOICE' AS ref_type,
                    'Purchase' AS voucher_type,
                    pi.voucher_no AS voucher_no,
                    pi.invoice_no AS invoice_no,
                    s.supplier_name AS party_name,
                    pii.batch_no AS batch_no,
                    pii.expiry AS expiry,
                    pii.pack_size AS pack_size,
                    pii.pay_qty AS pay_qty,
                    pii.free_qty AS free_qty
                FROM purchase_invoice_items pii
                JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id
                LEFT JOIN suppliers s ON s.id = pi.supplier_id
                WHERE pii.item_id = ?
                """,
                (item_id,),
            ).fetchall()

            for p in purchases:
                factor = pack_factor(p["pack_size"])
                in_qty = round((float(p["pay_qty"] or 0.0) + float(p["free_qty"] or 0.0)) * factor, 2)
                pname = p["party_name"] or "Supplier"
                inv_no = (p["invoice_no"] or "").strip()
                ref_text = f"Inv: {inv_no}" if inv_no else f"Vchr: {p['voucher_no']}"
                part = f"Purchase from {pname}"
                if inv_no:
                    part += f" (Inv: {inv_no})"

                all_movements.append({
                    "date": p["txn_date"] or "",
                    "time": p["txn_time"] or "",
                    "particulars": part,
                    "voucher_no": p["voucher_no"] or "",
                    "voucher_type": "Purchase",
                    "batch_no": p["batch_no"] or "",
                    "expiry": p["expiry"] or "",
                    "inward_qty": in_qty,
                    "outward_qty": 0.0,
                    "reference": ref_text,
                    "ref_id": p["ref_id"],
                })

            # 2. Sales (Outward)
            sales = conn.execute(
                """
                SELECT
                    si.sale_date AS txn_date,
                    si.sale_time AS txn_time,
                    si.id AS ref_id,
                    'COUNTER_SALE' AS ref_type,
                    'Sale' AS voucher_type,
                    si.bill_no AS voucher_no,
                    COALESCE(NULLIF(si.patient_name, ''), c.customer_name, 'WALKIN') AS party_name,
                    sii.batch_no AS batch_no,
                    sii.expiry AS expiry,
                    sii.pack_size AS pack_size,
                    sii.sale_qty AS sale_qty
                FROM sales_invoice_items sii
                JOIN sales_invoices si ON si.id = sii.sales_invoice_id
                LEFT JOIN customers c ON c.id = si.customer_id
                WHERE sii.item_id = ?
                """,
                (item_id,),
            ).fetchall()

            for s in sales:
                out_qty = round(float(s["sale_qty"] or 0.0), 2)
                pname = (s["party_name"] or "").strip() or "WALKIN"
                bill_no = s["voucher_no"] or ""
                part = f"Sale to {pname}"

                all_movements.append({
                    "date": s["txn_date"] or "",
                    "time": s["txn_time"] or "",
                    "particulars": part,
                    "voucher_no": bill_no,
                    "voucher_type": "Sale",
                    "batch_no": s["batch_no"] or "",
                    "expiry": s["expiry"] or "",
                    "inward_qty": 0.0,
                    "outward_qty": out_qty,
                    "reference": f"Bill #{bill_no}" if bill_no else "",
                    "ref_id": s["ref_id"],
                })

            # 3. Credit Notes (Sales Return -> Inward)
            cns = conn.execute(
                """
                SELECT
                    cn.voucher_date AS txn_date,
                    cn.voucher_time AS txn_time,
                    cn.id AS ref_id,
                    'CREDIT_NOTE' AS ref_type,
                    'Credit Note' AS voucher_type,
                    cn.voucher_no AS voucher_no,
                    c.customer_name AS party_name,
                    cni.batch_no AS batch_no,
                    cni.expiry AS expiry,
                    cni.pack_size AS pack_size,
                    cni.return_qty AS return_qty
                FROM credit_note_items cni
                JOIN credit_notes cn ON cn.id = cni.credit_note_id
                LEFT JOIN customers c ON c.id = cn.customer_id
                WHERE cni.item_id = ?
                """,
                (item_id,),
            ).fetchall()

            for c in cns:
                in_qty = round(float(c["return_qty"] or 0.0), 2)
                pname = (c["party_name"] or "").strip() or "Customer"
                part = f"Sales Return from {pname}"

                all_movements.append({
                    "date": c["txn_date"] or "",
                    "time": c["txn_time"] or "",
                    "particulars": part,
                    "voucher_no": c["voucher_no"] or "",
                    "voucher_type": "Credit Note",
                    "batch_no": c["batch_no"] or "",
                    "expiry": c["expiry"] or "",
                    "inward_qty": in_qty,
                    "outward_qty": 0.0,
                    "reference": f"CN #{c['voucher_no']}",
                    "ref_id": c["ref_id"],
                })

            # 4. Debit Notes (Purchase Return -> Outward)
            dni_cols = {row[1] for row in conn.execute("PRAGMA table_info(debit_note_items)").fetchall()}
            has_free = "free_qty" in dni_cols
            has_pack = "is_pack_qty" in dni_cols
            query_dns = f"""
                SELECT
                    dn.voucher_date AS txn_date,
                    dn.voucher_time AS txn_time,
                    dn.id AS ref_id,
                    'DEBIT_NOTE' AS ref_type,
                    'Debit Note' AS voucher_type,
                    dn.voucher_no AS voucher_no,
                    s.supplier_name AS party_name,
                    dni.batch_no AS batch_no,
                    dni.expiry AS expiry,
                    dni.pack_size AS pack_size,
                    dni.return_qty AS return_qty
                    {', COALESCE(dni.free_qty, 0.0) AS free_qty' if has_free else ''}
                    {', COALESCE(dni.is_pack_qty, 0) AS is_pack_qty' if has_pack else ''}
                FROM debit_note_items dni
                JOIN debit_notes dn ON dn.id = dni.debit_note_id
                LEFT JOIN suppliers s ON s.id = dn.supplier_id
                WHERE dni.item_id = ?
            """
            dns = conn.execute(query_dns, (item_id,)).fetchall()

            for d in dns:
                f_qty = float(d["free_qty"] or 0.0) if has_free else 0.0
                is_pk = bool(d["is_pack_qty"]) if has_pack else False
                factor = pack_factor(d["pack_size"]) if is_pk else 1.0
                out_qty = round((float(d["return_qty"] or 0.0) + f_qty) * factor, 2)
                pname = (d["party_name"] or "").strip() or "Supplier"
                part = f"Purchase Return to {pname}"

                all_movements.append({
                    "date": d["txn_date"] or "",
                    "time": d["txn_time"] or "",
                    "particulars": part,
                    "voucher_no": d["voucher_no"] or "",
                    "voucher_type": "Debit Note",
                    "batch_no": d["batch_no"] or "",
                    "expiry": d["expiry"] or "",
                    "inward_qty": 0.0,
                    "outward_qty": out_qty,
                    "reference": f"DN #{d['voucher_no']}",
                    "ref_id": d["ref_id"],
                })

            # Sort all movements chronologically
            all_movements.sort(key=lambda m: (m["date"], m["time"], m["voucher_no"], m["ref_id"]))

            # Partition movements into prior (< from_date) and period ([from_date, to_date])
            prior_in = 0.0
            prior_out = 0.0
            period_rows = []

            for m in all_movements:
                d = m["date"]
                if d < from_date:
                    prior_in += m["inward_qty"]
                    prior_out += m["outward_qty"]
                elif d <= to_date:
                    period_rows.append(m)

            # If from_date is on or after baseline_date, baseline_stock is part of opening balance
            if from_date >= baseline_date:
                opening_stock = round(baseline_stock + prior_in - prior_out, 2)
            else:
                opening_stock = round(prior_in - prior_out, 2)
                if baseline_date <= to_date and baseline_stock != 0.0:
                    period_rows.append({
                        "date": baseline_date,
                        "time": "00:00:00",
                        "particulars": "*** BASELINE / OPENING STOCK ***",
                        "voucher_no": "OPENING",
                        "voucher_type": "Opening",
                        "batch_no": "-",
                        "expiry": "-",
                        "inward_qty": baseline_stock if baseline_stock > 0 else 0.0,
                        "outward_qty": abs(baseline_stock) if baseline_stock < 0 else 0.0,
                        "reference": "Master OB",
                        "ref_id": 0,
                    })
                    period_rows.sort(key=lambda m: (m["date"], m["time"], m["voucher_no"], m["ref_id"]))

            running_stock = opening_stock
            period_in = 0.0
            period_out = 0.0

            rows = []
            for m in period_rows:
                in_q = m["inward_qty"]
                out_q = m["outward_qty"]
                period_in += in_q
                period_out += out_q
                running_stock = round(running_stock + in_q - out_q, 2)

                row_item = dict(m)
                row_item["closing_stock"] = running_stock
                rows.append(row_item)

            # Legacy Pharma-WINNER convention: Total Inward includes opening stock + period inward
            total_inward = round(opening_stock + period_in, 2)
            total_outward = round(period_out, 2)
            # Closing stock calculated as Total Inward - Total Outward (opening stock counted exactly once)
            closing_stock = round(total_inward - total_outward, 2)

            warning = None
            if opening_stock < 0:
                warning = f"Notice: Opening stock is negative ({opening_stock:g})."
            elif not all_movements and baseline_stock == 0.0 and current_batch_stock > 0:
                warning = f"Notice: No transaction history found, but batch stock shows {current_batch_stock:g} units on hand."
            elif period_rows and closing_stock < 0:
                warning = f"Notice: Closing stock is negative ({closing_stock:g}). Historical initial stock was not recorded in database."

            return {
                "item": item_dict,
                "from_date": from_date,
                "to_date": to_date,
                "opening_stock": opening_stock,
                "rows": rows,
                "total_inward": total_inward,
                "total_outward": total_outward,
                "period_inward": round(period_in, 2),
                "period_outward": round(period_out, 2),
                "closing_stock": closing_stock,
                "current_batch_stock": current_batch_stock,
                "warning": warning,
            }
        finally:
            conn.close()
