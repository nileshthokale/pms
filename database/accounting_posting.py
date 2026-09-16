"""Centralized accounting posting engine — Phase 2C / 2D / 2E / 2F / 2G / 2H / 2J.

Supported source types:
    CUSTOMER_RECEIPT   — posted automatically by CustomerReceiptDAO
    SUPPLIER_PAYMENT   — posted automatically by SupplierPaymentDAO
    COUNTER_SALE       — posted automatically by SalesDAO
    PURCHASE_INVOICE   — posted automatically by PurchaseDAO
    CREDIT_NOTE        — posted automatically by CreditNoteDAO
    DEBIT_NOTE         — posted automatically by DebitNoteDAO
    JOURNAL_ENTRY      — posted automatically by JournalDAO

Approved entry shapes:

    Customer Receipt (docs/accounting_decisions.md):
        Cash mode:           Debit CASH  / Credit Customer Ledger
        Bank / Cheque / UPI: Debit BANK  / Credit Customer Ledger

    Supplier Payment (docs/accounting_decisions.md):
        Cash mode:           Debit Supplier Ledger / Credit CASH
        Bank / Cheque / UPI: Debit Supplier Ledger / Credit BANK

    Counter Sale (docs/accounting_decisions.md, Decisions 2/5/7 — NET
    posting, periodic inventory, walk-in fully-paid only):
        Customer-linked sale:
            Debit tender ledger (per sale_type) for paid_amount
            Debit Customer Ledger for (net_amount − paid_amount)
            Credit SALES for net_amount
            (zero-amount legs are omitted, so a pure credit sale posts
            Customer/SALES and a fully-paid sale posts tender/SALES)
        WALKIN sale (customer_id IS NULL, fully paid only):
            Debit CASH for net_amount
            Credit SALES for net_amount
            No walk-in customer ledger is ever created.

    Purchase Invoice (docs/accounting_decisions.md, Decision 1 Option B
    — NET posting, periodic inventory, no GST/Discount/Other ledgers):
        Debit PURCHASE system ledger for net_amount
        Credit Supplier Ledger for (net_amount − paid_amount)
        Credit Cash/Bank for paid_amount (per purchase_type mapping)
        (zero-amount legs are omitted, so a pure credit purchase posts
        Purchase/Supplier and a fully-paid purchase posts Purchase/Cash)

    Credit Note (docs/accounting_decisions.md, Decision 3 = total_amount
    — Sales Return contra-revenue, periodic inventory, no GST):
        Debit SALES_RETURN system ledger for total_amount
        Credit Customer Ledger for total_amount
        (exactly two rows; the credit reduces what the customer owes)

    Debit Note (docs/accounting_decisions.md, Decision 3 = total_amount
    — Purchase Return contra-expense, periodic inventory, no GST):
        Debit Supplier Ledger for total_amount
        Credit PURCHASE_RETURN system ledger for total_amount
        (exactly two rows; the debit reduces what we owe the supplier)

    GST: no GST ledger postings exist — the current Sales transaction
    contains no reliable GST fields (approved Decision 4a), and no GST
    amounts may be invented.

    Inventory: periodic (approved Decision 5) — no COGS and no Inventory
    ledger postings are created at sale time; stock quantity movement
    remains handled entirely by SalesDAO.

Party ledgers are resolved from customers.ledger_id / suppliers.ledger_id
(Phase 1) — the engine never creates a second party ledger.

Posting identity (idempotency) uses ledger_transactions.reference_type +
reference_id. Reversal uses the approved mirrored-rows strategy and is
computed per ledger net, so any sequence of post / reverse / repost /
delete stays mathematically correct.

All engine operations can join a caller's open transaction by passing the
caller's cursor (`cur=...`); when no cursor is given the engine opens and
manages its own transaction. The DAOs pass their cursor so source save +
accounting posting are atomic.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Optional

from database.connection import get_connection
from database.account_roles import (
    ROLE_BANK,
    ROLE_CASH,
    ROLE_PURCHASE,
    ROLE_PURCHASE_RETURN,
    ROLE_SALES,
    ROLE_SALES_RETURN,
)

# ── Source identity ───────────────────────────────────────────────────
SOURCE_CUSTOMER_RECEIPT = "CUSTOMER_RECEIPT"
SOURCE_SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"
SOURCE_COUNTER_SALE = "COUNTER_SALE"
SOURCE_PURCHASE_INVOICE = "PURCHASE_INVOICE"
SOURCE_CREDIT_NOTE = "CREDIT_NOTE"
SOURCE_DEBIT_NOTE = "DEBIT_NOTE"
SOURCE_JOURNAL_ENTRY = "JOURNAL_ENTRY"

# Voucher type labels written to ledger_transactions
VOUCHER_TYPE_CUSTOMER_RECEIPT = "Customer Receipt"
VOUCHER_TYPE_CUSTOMER_RECEIPT_REVERSAL = "Customer Receipt Reversal"
VOUCHER_TYPE_SUPPLIER_PAYMENT = "Supplier Payment"
VOUCHER_TYPE_SUPPLIER_PAYMENT_REVERSAL = "Supplier Payment Reversal"
VOUCHER_TYPE_COUNTER_SALE = "Counter Sale"
VOUCHER_TYPE_COUNTER_SALE_REVERSAL = "Counter Sale Reversal"
VOUCHER_TYPE_PURCHASE_INVOICE = "Purchase Invoice"
VOUCHER_TYPE_PURCHASE_INVOICE_REVERSAL = "Purchase Invoice Reversal"
VOUCHER_TYPE_CREDIT_NOTE = "Credit Note"
VOUCHER_TYPE_CREDIT_NOTE_REVERSAL = "Credit Note Reversal"
VOUCHER_TYPE_DEBIT_NOTE = "Debit Note"
VOUCHER_TYPE_DEBIT_NOTE_REVERSAL = "Debit Note Reversal"
VOUCHER_TYPE_JOURNAL_ENTRY = "Journal Entry"
VOUCHER_TYPE_JOURNAL_ENTRY_REVERSAL = "Journal Entry Reversal"

# Payment/receipt mode → system account role (approved decision: Cheque/UPI → BANK)
RECEIPT_MODE_TO_ROLE = {
    "Cash": ROLE_CASH,
    "Bank": ROLE_BANK,
    "Cheque": ROLE_BANK,
    "UPI": ROLE_BANK,
}

PAYMENT_MODE_TO_ROLE = {
    "Cash": ROLE_CASH,
    "Bank": ROLE_BANK,
    "Cheque": ROLE_BANK,
    "UPI": ROLE_BANK,
}

# Sale type → tender account role for the paid portion of a
# customer-linked sale (approved shape: "Cash/Bank (per sale_type)").
# Cash → CASH, Credit Card → BANK. A "Credit"-type sale that carries a
# partial paid_amount has no recorded instrument (specification §3 gap);
# the conservative counter default CASH is used for its paid portion.
# This is not a new payment-mode system — sale_type is the only
# instrument information the sale stores today.
SALE_TYPE_TO_ROLE = {
    "Cash": ROLE_CASH,
    "Credit Card": ROLE_BANK,
    "Credit": ROLE_CASH,
}

# Purchase type → system account role for the paid portion.
# Cash → CASH, Credit Card → BANK. "Credit"-type purchases with a
# paid portion have no instrument detail (specification §1B gap);
# the conservative default CASH is used for the paid portion.
PURCHASE_TYPE_TO_ROLE = {
    "Cash": ROLE_CASH,
    "Credit Card": ROLE_BANK,
    "Credit": ROLE_CASH,
}

# Registry of source types the engine currently understands.
_SOURCE_TYPES = {
    SOURCE_CUSTOMER_RECEIPT: {
        "label": "Customer Receipt",
        "voucher_type": VOUCHER_TYPE_CUSTOMER_RECEIPT,
        "reversal_voucher_type": VOUCHER_TYPE_CUSTOMER_RECEIPT_REVERSAL,
    },
    SOURCE_SUPPLIER_PAYMENT: {
        "label": "Supplier Payment",
        "voucher_type": VOUCHER_TYPE_SUPPLIER_PAYMENT,
        "reversal_voucher_type": VOUCHER_TYPE_SUPPLIER_PAYMENT_REVERSAL,
    },
    SOURCE_COUNTER_SALE: {
        "label": "Counter Sale",
        "voucher_type": VOUCHER_TYPE_COUNTER_SALE,
        "reversal_voucher_type": VOUCHER_TYPE_COUNTER_SALE_REVERSAL,
    },
    SOURCE_PURCHASE_INVOICE: {
        "label": "Purchase Invoice",
        "voucher_type": VOUCHER_TYPE_PURCHASE_INVOICE,
        "reversal_voucher_type": VOUCHER_TYPE_PURCHASE_INVOICE_REVERSAL,
    },
    SOURCE_CREDIT_NOTE: {
        "label": "Credit Note",
        "voucher_type": VOUCHER_TYPE_CREDIT_NOTE,
        "reversal_voucher_type": VOUCHER_TYPE_CREDIT_NOTE_REVERSAL,
    },
    SOURCE_DEBIT_NOTE: {
        "label": "Debit Note",
        "voucher_type": VOUCHER_TYPE_DEBIT_NOTE,
        "reversal_voucher_type": VOUCHER_TYPE_DEBIT_NOTE_REVERSAL,
    },
    SOURCE_JOURNAL_ENTRY: {
        "label": "Journal Entry",
        "voucher_type": VOUCHER_TYPE_JOURNAL_ENTRY,
        "reversal_voucher_type": VOUCHER_TYPE_JOURNAL_ENTRY_REVERSAL,
    },
}

# Float tolerance when comparing ledger amounts (amounts are 2-decimal)
_EPSILON = 0.005


class PostingError(Exception):
    """Raised when a posting operation cannot be completed safely.

    No ledger transaction rows are created or modified when this is
    raised inside an engine-managed or caller-managed transaction that
    is rolled back.
    """


class PostingEngine:
    """Reusable accounting posting service.

    Phase 2C implements Customer Receipt. Phase 2D adds Supplier Payment.
    The method shapes (post_<type> / repost_<type> / reverse) are the
    pattern future transaction types will follow.
    """

    # ── transaction scope ────────────────────────────────────────────
    @contextmanager
    def _transaction(self, cur: sqlite3.Cursor | None):
        """Run engine work inside ONE transaction.

        With `cur` given, the engine joins the caller's open transaction
        (never commits/rolls back on its own). Without `cur`, the engine
        opens its own connection and transaction.
        """
        if cur is not None:
            yield cur
            return
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute("BEGIN")
            yield c
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── public API: customer receipt ─────────────────────────────────
    def post_customer_receipt(
        self, receipt_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Post a Customer Receipt to the ledger.

        Creates exactly two ledger_transactions rows:
            Row 1: Debit CASH/BANK system ledger for receipt.amount
            Row 2: Credit the customer's linked ledger for receipt.amount

        Raises PostingError (creating no rows) when any validation fails:
        receipt missing, amount <= 0, unsupported mode, customer missing,
        customer without ledger_id, system role unconfigured, or an active
        posting already exists for this receipt.
        """
        with self._transaction(cur) as c:
            return self._post_customer_receipt_cur(c, receipt_id)

    def repost_customer_receipt(
        self, receipt_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Re-post after edit: reverse previous posting, post new state.

        Both steps run in one transaction. Safe for receipts that were
        never posted (reversal is a no-op) — e.g. legacy rows being
        edited for the first time since the integration.
        """
        with self._transaction(cur) as c:
            reversed_ids = self._reverse_cur(c, SOURCE_CUSTOMER_RECEIPT, receipt_id)
            posted_ids = self._post_customer_receipt_cur(c, receipt_id)
            return reversed_ids + posted_ids

    # ── public API: supplier payment ─────────────────────────────────
    def post_supplier_payment(
        self, payment_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Post a Supplier Payment to the ledger.

        Creates exactly two ledger_transactions rows:
            Row 1: Debit the supplier's linked ledger for payment.amount
            Row 2: Credit CASH/BANK system ledger for payment.amount

        Raises PostingError (creating no rows) when any validation fails:
        payment missing, supplier missing, supplier without ledger_id,
        amount <= 0, unsupported mode, system role unconfigured, or an
        active posting already exists for this payment.
        """
        with self._transaction(cur) as c:
            return self._post_supplier_payment_cur(c, payment_id)

    def repost_supplier_payment(
        self, payment_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Re-post after edit: reverse previous posting, post new state.

        Both steps run in one transaction. Safe for payments that were
        never posted (reversal is a no-op) — e.g. legacy rows being
        edited for the first time since the integration.
        """
        with self._transaction(cur) as c:
            reversed_ids = self._reverse_cur(c, SOURCE_SUPPLIER_PAYMENT, payment_id)
            posted_ids = self._post_supplier_payment_cur(c, payment_id)
            return reversed_ids + posted_ids

    # ── public API: counter sale ──────────────────────────────────────
    def post_counter_sale(
        self, sale_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Post a Counter Sale to the ledger.

        Customer-linked sale (NET posting, approved Decision 2 Option B):
            Debit tender ledger (per sale_type) for paid_amount
            Debit Customer Ledger for (net_amount − paid_amount)
            Credit SALES system ledger for net_amount
        Zero-amount legs are omitted (a pure credit sale posts exactly
        Customer debit + SALES credit; a fully-paid sale posts exactly
        tender debit + SALES credit).

        WALKIN sale (customer_id IS NULL, approved Decision 7 Option A):
            allowed only when fully paid (paid_amount >= net_amount);
            Debit CASH for net_amount / Credit SALES for net_amount.
            No walk-in customer ledger is ever created.

        Raises PostingError (creating no rows) when any validation fails:
        sale missing, net_amount <= 0, negative paid_amount, SALES role
        unconfigured, customer without ledger_id, unsupported sale_type,
        underpaid walk-in, or an active posting already exists.
        """
        with self._transaction(cur) as c:
            return self._post_counter_sale_cur(c, sale_id)

    def repost_counter_sale(
        self, sale_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Re-post after edit: reverse previous posting, post new state.

        Both steps run in one transaction. Safe for sales that were
        never posted (reversal is a no-op) — e.g. legacy rows being
        edited for the first time since the integration.
        """
        with self._transaction(cur) as c:
            reversed_ids = self._reverse_cur(c, SOURCE_COUNTER_SALE, sale_id)
            posted_ids = self._post_counter_sale_cur(c, sale_id)
            return reversed_ids + posted_ids

    # ── public API: purchase invoice ──────────────────────────────────
    def post_purchase_invoice(
        self, invoice_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Post a Purchase Invoice to the ledger.

        NET posting (approved Decision 1 Option B, §10A):
            Debit PURCHASE system ledger for net_amount
            Credit Supplier Ledger for (net_amount − paid_amount)
            Credit Cash/Bank for paid_amount (per purchase_type mapping)
        Zero-amount legs are omitted (a pure credit purchase posts
        exactly Purchase/Supplier; a fully-paid purchase posts
        exactly Purchase/Cash).

        Raises PostingError (creating no rows) when any validation fails:
        invoice missing, net_amount <= 0, negative paid_amount,
        paid_amount > net_amount, supplier missing, supplier without
        ledger_id, PURCHASE role unconfigured, purchase_type invalid or
        its tender role unconfigured (when paid_amount > 0), or an active
        posting already exists for this invoice.
        """
        with self._transaction(cur) as c:
            return self._post_purchase_invoice_cur(c, invoice_id)

    def repost_purchase_invoice(
        self, invoice_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Re-post after edit: reverse previous posting, post new state.

        Both steps run in one transaction. Safe for invoices that were
        never posted (reversal is a no-op) — e.g. legacy rows being
        edited for the first time since the integration.
        """
        with self._transaction(cur) as c:
            reversed_ids = self._reverse_cur(c, SOURCE_PURCHASE_INVOICE, invoice_id)
            posted_ids = self._post_purchase_invoice_cur(c, invoice_id)
            return reversed_ids + posted_ids

    # ── public API: credit note ──────────────────────────────────────
    def post_credit_note(
        self, note_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Post a Credit Note (Customer Return) to the ledger.

        Approved shape (Decision 3 = total_amount, specification §1C):
            Debit SALES_RETURN system ledger for total_amount
            Credit Customer Ledger for total_amount
        Exactly two rows when the customer has a linked ledger.

        Raises PostingError (creating no rows) when any validation fails:
        note missing, total_amount <= 0, customer missing, customer
        without ledger_id, SALES_RETURN role unconfigured, or an active
        posting already exists for this note.
        """
        with self._transaction(cur) as c:
            return self._post_credit_note_cur(c, note_id)

    def repost_credit_note(
        self, note_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Re-post after edit: reverse previous posting, post new state.

        Both steps run in one transaction. Safe for notes that were
        never posted (reversal is a no-op) — e.g. legacy rows being
        edited for the first time since the integration.
        """
        with self._transaction(cur) as c:
            reversed_ids = self._reverse_cur(c, SOURCE_CREDIT_NOTE, note_id)
            posted_ids = self._post_credit_note_cur(c, note_id)
            return reversed_ids + posted_ids

    # ── public API: debit note ──────────────────────────────────────
    def post_debit_note(
        self, note_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Post a Debit Note (Supplier Return) to the ledger.

        Approved shape (Decision 3 = total_amount, specification §1D):
            Debit Supplier Ledger for total_amount
            Credit PURCHASE_RETURN system ledger for total_amount
        Exactly two rows when the supplier has a linked ledger.

        Raises PostingError (creating no rows) when any validation fails:
        note missing, total_amount <= 0, supplier missing, supplier
        without ledger_id, PURCHASE_RETURN role unconfigured, or an
        active posting already exists for this note.
        """
        with self._transaction(cur) as c:
            return self._post_debit_note_cur(c, note_id)

    def repost_debit_note(
        self, note_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Re-post after edit: reverse previous posting, post new state.

        Both steps run in one transaction. Safe for notes that were
        never posted (reversal is a no-op) — e.g. legacy rows being
        edited for the first time since the integration.
        """
        with self._transaction(cur) as c:
            reversed_ids = self._reverse_cur(c, SOURCE_DEBIT_NOTE, note_id)
            posted_ids = self._post_debit_note_cur(c, note_id)
            return reversed_ids + posted_ids

    # ── public API: journal entry ───────────────────────────────────
    def post_journal_entry(
        self, entry_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Post a Journal Entry to the ledger.

        Journal entries are balanced manual vouchers whose lines already
        carry explicit ledger_id / debit / credit. The posting mirrors
        every journal line into ledger_transactions exactly as entered:

            One ledger_transactions row per journal_entry_item:
                ledger_id  = journal_entry_item.ledger_id
                debit      = journal_entry_item.debit
                credit     = journal_entry_item.credit

        Raises PostingError (creating no rows) when:
        entry missing, < 2 lines, unbalanced lines, any line references
        a missing ledger, or an active posting already exists.
        """
        with self._transaction(cur) as c:
            return self._post_journal_entry_cur(c, entry_id)

    def repost_journal_entry(
        self, entry_id: int, cur: sqlite3.Cursor | None = None
    ) -> list[int]:
        """Re-post after edit: reverse previous posting, post new state.

        Both steps run in one transaction. Safe for entries that were
        never posted (reversal is a no-op).
        """
        with self._transaction(cur) as c:
            reversed_ids = self._reverse_cur(c, SOURCE_JOURNAL_ENTRY, entry_id)
            posted_ids = self._post_journal_entry_cur(c, entry_id)
            return reversed_ids + posted_ids

    # ── public API: generic (identity-based) ─────────────────────────
    def reverse(
        self,
        source_type: str,
        source_id: int,
        cur: sqlite3.Cursor | None = None,
    ) -> list[int]:
        """Reverse the active posting of a source transaction.

        Mirrored-rows strategy: inserts one row per ledger equal to the
        opposite of that ledger's net posting effect, carrying the same
        reference_type / reference_id, the original voucher_no, a
        "... Reversal" voucher_type and an explicit "REVERSAL: ..."
        description marker. Historical rows are never deleted.

        No-op (returns []) when there is no posting at all or the posting
        is already fully reversed — this makes deletion of legacy
        (never-posted) receipts safe.

        Refuses unknown source types so it can never reverse an
        unrelated transaction.
        """
        if source_type not in _SOURCE_TYPES:
            raise PostingError(
                f"Unsupported source type '{source_type}'. "
                f"Supported: {', '.join(sorted(_SOURCE_TYPES))}."
            )
        with self._transaction(cur) as c:
            return self._reverse_cur(c, source_type, source_id)

    def is_posted(
        self,
        source_type: str,
        source_id: int,
        cur: sqlite3.Cursor | None = None,
    ) -> bool:
        """True when the source has an active (not fully reversed) posting."""
        with self._transaction(cur) as c:
            nets = self._active_nets_cur(c, source_type, source_id)
            return bool(nets)

    def get_posting_rows(
        self,
        source_type: str,
        source_id: int,
        cur: sqlite3.Cursor | None = None,
    ) -> list[dict]:
        """All ledger_transactions rows for a source identity (audit view)."""
        with self._transaction(cur) as c:
            rows = c.execute(
                "SELECT * FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? ORDER BY id",
                (source_type, source_id),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── customer receipt internals ───────────────────────────────────
    def _post_customer_receipt_cur(
        self, cur: sqlite3.Cursor, receipt_id: int
    ) -> list[int]:
        receipt = cur.execute(
            """
            SELECT cr.*, cu.customer_name, cu.ledger_id AS customer_ledger_id
            FROM customer_receipts cr
            LEFT JOIN customers cu ON cu.id = cr.customer_id
            WHERE cr.id = ?
            """,
            (receipt_id,),
        ).fetchone()
        if receipt is None:
            raise PostingError(f"Customer receipt {receipt_id} not found.")

        amount = receipt["amount"] or 0.0
        if amount <= 0:
            raise PostingError(
                f"Receipt {receipt['voucher_no']}: amount must be greater "
                f"than 0 (got {amount})."
            )

        mode = receipt["receipt_mode"] or ""
        role = RECEIPT_MODE_TO_ROLE.get(mode)
        if role is None:
            raise PostingError(
                f"Receipt {receipt['voucher_no']}: unsupported payment "
                f"mode '{mode}'. Supported: {', '.join(RECEIPT_MODE_TO_ROLE)}."
            )

        if not receipt["customer_ledger_id"]:
            raise PostingError(
                f"Receipt {receipt['voucher_no']}: customer "
                f"'{receipt['customer_name']}' has no linked Account Ledger."
            )

        role_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE system_role = ?", (role,)
        ).fetchone()
        if role_ledger is None:
            raise PostingError(
                f"Receipt {receipt['voucher_no']}: system account role "
                f"'{role}' is not configured. Initialize Account Roles first."
            )

        if self._active_nets_cur(cur, SOURCE_CUSTOMER_RECEIPT, receipt_id):
            raise PostingError(
                f"Receipt {receipt['voucher_no']} already has an active "
                f"accounting posting — duplicate posting refused."
            )

        description = (
            f"Receipt {receipt['voucher_no']} from "
            f"{receipt['customer_name']}"
        )
        if receipt["reference_no"]:
            description += f" - {receipt['receipt_mode']} {receipt['reference_no']}"

        common = {
            "transaction_date": receipt["receipt_date"],
            "transaction_time": receipt["receipt_time"] or "",
            "voucher_type": VOUCHER_TYPE_CUSTOMER_RECEIPT,
            "voucher_no": receipt["voucher_no"],
            "reference_type": SOURCE_CUSTOMER_RECEIPT,
            "reference_id": receipt_id,
            "description": description,
        }

        row_ids = [
            self._insert_posting_row(
                cur,
                {
                    **common,
                    "ledger_id": role_ledger["id"],
                    "debit": amount,
                    "credit": 0.0,
                },
            ),
            self._insert_posting_row(
                cur,
                {
                    **common,
                    "ledger_id": receipt["customer_ledger_id"],
                    "debit": 0.0,
                    "credit": amount,
                },
            ),
        ]
        return row_ids

    # ── supplier payment internals ───────────────────────────────────
    def _post_supplier_payment_cur(
        self, cur: sqlite3.Cursor, payment_id: int
    ) -> list[int]:
        payment = cur.execute(
            """
            SELECT sp.*, su.supplier_name, su.ledger_id AS supplier_ledger_id
            FROM supplier_payments sp
            LEFT JOIN suppliers su ON su.id = sp.supplier_id
            WHERE sp.id = ?
            """,
            (payment_id,),
        ).fetchone()
        if payment is None:
            raise PostingError(f"Supplier payment {payment_id} not found.")

        amount = payment["amount"] or 0.0
        if amount <= 0:
            raise PostingError(
                f"Payment {payment['voucher_no']}: amount must be greater "
                f"than 0 (got {amount})."
            )

        mode = payment["payment_mode"] or ""
        role = PAYMENT_MODE_TO_ROLE.get(mode)
        if role is None:
            raise PostingError(
                f"Payment {payment['voucher_no']}: unsupported payment "
                f"mode '{mode}'. Supported: {', '.join(PAYMENT_MODE_TO_ROLE)}."
            )

        if not payment["supplier_ledger_id"]:
            raise PostingError(
                f"Payment {payment['voucher_no']}: supplier "
                f"'{payment['supplier_name']}' has no linked Account Ledger."
            )

        role_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE system_role = ?", (role,)
        ).fetchone()
        if role_ledger is None:
            raise PostingError(
                f"Payment {payment['voucher_no']}: system account role "
                f"'{role}' is not configured. Initialize Account Roles first."
            )

        if self._active_nets_cur(cur, SOURCE_SUPPLIER_PAYMENT, payment_id):
            raise PostingError(
                f"Payment {payment['voucher_no']} already has an active "
                f"accounting posting — duplicate posting refused."
            )

        description = (
            f"Payment {payment['voucher_no']} to "
            f"{payment['supplier_name']}"
        )
        if payment["reference_no"]:
            description += f" - {payment['payment_mode']} {payment['reference_no']}"

        common = {
            "transaction_date": payment["payment_date"],
            "transaction_time": payment["payment_time"] or "",
            "voucher_type": VOUCHER_TYPE_SUPPLIER_PAYMENT,
            "voucher_no": payment["voucher_no"],
            "reference_type": SOURCE_SUPPLIER_PAYMENT,
            "reference_id": payment_id,
            "description": description,
        }

        row_ids = [
            self._insert_posting_row(
                cur,
                {
                    **common,
                    "ledger_id": payment["supplier_ledger_id"],
                    "debit": amount,
                    "credit": 0.0,
                },
            ),
            self._insert_posting_row(
                cur,
                {
                    **common,
                    "ledger_id": role_ledger["id"],
                    "debit": 0.0,
                    "credit": amount,
                },
            ),
        ]
        return row_ids

    # ── counter sale internals ───────────────────────────────────────
    def _post_counter_sale_cur(
        self, cur: sqlite3.Cursor, sale_id: int
    ) -> list[int]:
        sale = cur.execute(
            """
            SELECT si.*, c.customer_name, c.ledger_id AS customer_ledger_id
            FROM sales_invoices si
            LEFT JOIN customers c ON c.id = si.customer_id
            WHERE si.id = ?
            """,
            (sale_id,),
        ).fetchone()
        if sale is None:
            raise PostingError(f"Sale invoice {sale_id} not found.")

        net = sale["net_amount"] or 0.0
        if net <= _EPSILON:
            raise PostingError(
                f"Sale {sale['bill_no']}: net_amount must be greater "
                f"than 0 (got {net})."
            )

        paid = sale["paid_amount"] or 0.0
        if paid < -_EPSILON:
            raise PostingError(
                f"Sale {sale['bill_no']}: paid_amount cannot be negative "
                f"(got {paid})."
            )

        sales_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE system_role = ?",
            (ROLE_SALES,),
        ).fetchone()
        if sales_ledger is None:
            raise PostingError(
                f"Sale {sale['bill_no']}: system account role 'SALES' is "
                f"not configured. Initialize Account Roles first."
            )

        # Walk-in sales always post their tender to CASH per the approved
        # instruction, regardless of the sale_type label.
        if sale["customer_id"] is None:
            if paid + _EPSILON < net:
                raise PostingError(
                    f"Walk-in sale {sale['bill_no']} must be fully paid "
                    f"(net_amount {net:.2f}, paid_amount {paid:.2f})."
                )
            cash_ledger = cur.execute(
                "SELECT * FROM account_ledgers WHERE system_role = ?",
                (ROLE_CASH,),
            ).fetchone()
            if cash_ledger is None:
                raise PostingError(
                    f"Walk-in sale {sale['bill_no']}: system account role "
                    f"'CASH' is not configured. Initialize Account Roles "
                    f"first."
                )
            if self._active_nets_cur(cur, SOURCE_COUNTER_SALE, sale_id):
                raise PostingError(
                    f"Sale {sale['bill_no']} already has an active "
                    f"accounting posting — duplicate posting refused."
                )

            description = f"Walk-in sale {sale['bill_no']}"
            common = {
                "transaction_date": sale["sale_date"],
                "transaction_time": sale["sale_time"] or "",
                "voucher_type": VOUCHER_TYPE_COUNTER_SALE,
                "voucher_no": sale["bill_no"],
                "reference_type": SOURCE_COUNTER_SALE,
                "reference_id": sale_id,
                "description": description,
            }
            return [
                self._insert_posting_row(
                    cur,
                    {
                        **common,
                        "ledger_id": cash_ledger["id"],
                        "debit": round(net, 2),
                        "credit": 0.0,
                    },
                ),
                self._insert_posting_row(
                    cur,
                    {
                        **common,
                        "ledger_id": sales_ledger["id"],
                        "debit": 0.0,
                        "credit": round(net, 2),
                    },
                ),
            ]

        # Customer-linked sale: NET posting with tender/receivable split.
        if not sale["customer_ledger_id"]:
            raise PostingError(
                f"Sale {sale['bill_no']}: customer "
                f"'{sale['customer_name']}' has no linked Account Ledger."
            )

        role = SALE_TYPE_TO_ROLE.get(sale["sale_type"] or "")
        if role is None:
            raise PostingError(
                f"Sale {sale['bill_no']}: unsupported sale type "
                f"'{sale['sale_type']}'. Supported: "
                f"{', '.join(SALE_TYPE_TO_ROLE)}."
            )

        tender = round(min(paid, net), 2)
        receivable = round(net - tender, 2)

        if self._active_nets_cur(cur, SOURCE_COUNTER_SALE, sale_id):
            raise PostingError(
                f"Sale {sale['bill_no']} already has an active accounting "
                f"posting — duplicate posting refused."
            )

        description = f"Sale {sale['bill_no']} to {sale['customer_name']}"
        common = {
            "transaction_date": sale["sale_date"],
            "transaction_time": sale["sale_time"] or "",
            "voucher_type": VOUCHER_TYPE_COUNTER_SALE,
            "voucher_no": sale["bill_no"],
            "reference_type": SOURCE_COUNTER_SALE,
            "reference_id": sale_id,
            "description": description,
        }

        rows: list[dict] = []
        if tender > _EPSILON:
            tender_ledger = cur.execute(
                "SELECT * FROM account_ledgers WHERE system_role = ?",
                (role,),
            ).fetchone()
            if tender_ledger is None:
                raise PostingError(
                    f"Sale {sale['bill_no']}: system account role "
                    f"'{role}' is not configured. Initialize Account "
                    f"Roles first."
                )
            rows.append(
                {
                    **common,
                    "ledger_id": tender_ledger["id"],
                    "debit": tender,
                    "credit": 0.0,
                }
            )
        if receivable > _EPSILON:
            rows.append(
                {
                    **common,
                    "ledger_id": sale["customer_ledger_id"],
                    "debit": receivable,
                    "credit": 0.0,
                }
            )
        rows.append(
            {
                **common,
                "ledger_id": sales_ledger["id"],
                "debit": 0.0,
                "credit": round(net, 2),
            }
        )
        return [self._insert_posting_row(cur, r) for r in rows]

    # ── purchase invoice internals ───────────────────────────────────
    def _post_purchase_invoice_cur(
        self, cur: sqlite3.Cursor, invoice_id: int
    ) -> list[int]:
        invoice = cur.execute(
            """
            SELECT pi.*, s.supplier_name, s.ledger_id AS supplier_ledger_id
            FROM purchase_invoices pi
            LEFT JOIN suppliers s ON s.id = pi.supplier_id
            WHERE pi.id = ?
            """,
            (invoice_id,),
        ).fetchone()
        if invoice is None:
            raise PostingError(f"Purchase invoice {invoice_id} not found.")

        net = invoice["net_amount"] or 0.0
        if net <= _EPSILON:
            raise PostingError(
                f"Invoice {invoice['voucher_no']}: net_amount must be "
                f"greater than 0 (got {net})."
            )

        paid = invoice["paid_amount"] or 0.0
        if paid < -_EPSILON:
            raise PostingError(
                f"Invoice {invoice['voucher_no']}: paid_amount cannot be "
                f"negative (got {paid})."
            )
        if paid > net + _EPSILON:
            raise PostingError(
                f"Invoice {invoice['voucher_no']}: paid_amount ({paid}) "
                f"cannot exceed net_amount ({net})."
            )

        if not invoice["supplier_ledger_id"]:
            raise PostingError(
                f"Invoice {invoice['voucher_no']}: supplier "
                f"'{invoice['supplier_name']}' has no linked Account "
                f"Ledger."
            )

        # Verify the supplier's ledger exists in account_ledgers
        supplier_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE id = ?",
            (invoice["supplier_ledger_id"],),
        ).fetchone()
        if supplier_ledger is None:
            raise PostingError(
                f"Invoice {invoice['voucher_no']}: supplier ledger "
                f"id {invoice['supplier_ledger_id']} does not exist in "
                f"Account Ledgers."
            )

        purchase_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE system_role = ?",
            (ROLE_PURCHASE,),
        ).fetchone()
        if purchase_ledger is None:
            raise PostingError(
                f"Invoice {invoice['voucher_no']}: system account role "
                f"'PURCHASE' is not configured. Initialize Account Roles "
                f"first."
            )

        if self._active_nets_cur(cur, SOURCE_PURCHASE_INVOICE, invoice_id):
            raise PostingError(
                f"Invoice {invoice['voucher_no']} already has an active "
                f"accounting posting — duplicate posting refused."
            )

        description = (
            f"Purchase {invoice['voucher_no']} from "
            f"{invoice['supplier_name']}"
        )

        common = {
            "transaction_date": invoice["voucher_date"],
            "transaction_time": invoice["voucher_time"] or "",
            "voucher_type": VOUCHER_TYPE_PURCHASE_INVOICE,
            "voucher_no": invoice["voucher_no"],
            "reference_type": SOURCE_PURCHASE_INVOICE,
            "reference_id": invoice_id,
            "description": description,
        }

        rows: list[dict] = []

        # Debit: Purchase system ledger for full net_amount
        rows.append(
            {
                **common,
                "ledger_id": purchase_ledger["id"],
                "debit": round(net, 2),
                "credit": 0.0,
            }
        )

        # Credit: Cash/Bank for paid_amount (if paid)
        tender = round(paid, 2)
        if tender > _EPSILON:
            purchase_type = invoice["purchase_type"] or ""
            role = PURCHASE_TYPE_TO_ROLE.get(purchase_type)
            if role is None:
                raise PostingError(
                    f"Invoice {invoice['voucher_no']}: unsupported "
                    f"purchase type '{purchase_type}'. Supported: "
                    f"{', '.join(PURCHASE_TYPE_TO_ROLE)}."
                )
            tender_ledger = cur.execute(
                "SELECT * FROM account_ledgers WHERE system_role = ?",
                (role,),
            ).fetchone()
            if tender_ledger is None:
                raise PostingError(
                    f"Invoice {invoice['voucher_no']}: system account "
                    f"role '{role}' is not configured. Initialize Account "
                    f"Roles first."
                )
            rows.append(
                {
                    **common,
                    "ledger_id": tender_ledger["id"],
                    "debit": 0.0,
                    "credit": tender,
                }
            )

        # Credit: Supplier ledger for the remaining amount
        supplier_credit = round(net - paid, 2)
        if supplier_credit > _EPSILON:
            rows.append(
                {
                    **common,
                    "ledger_id": invoice["supplier_ledger_id"],
                    "debit": 0.0,
                    "credit": supplier_credit,
                }
            )

        return [self._insert_posting_row(cur, r) for r in rows]

    # ── credit note internals ────────────────────────────────────────
    def _post_credit_note_cur(
        self, cur: sqlite3.Cursor, note_id: int
    ) -> list[int]:
        note = cur.execute(
            """
            SELECT cn.*, cu.customer_name, cu.ledger_id AS customer_ledger_id
            FROM credit_notes cn
            LEFT JOIN customers cu ON cu.id = cn.customer_id
            WHERE cn.id = ?
            """,
            (note_id,),
        ).fetchone()
        if note is None:
            raise PostingError(f"Credit note {note_id} not found.")

        amount = note["total_amount"] or 0.0
        # A zero/negative-amount note creates no accounting rows (legacy
        # DAO behavior allows empty-heading notes; posting nothing keeps
        # that behaviour intact). No rows → no duplicate posting risk.
        if amount <= _EPSILON:
            return []

        if not note["customer_id"]:
            raise PostingError(
                f"Credit Note {note['voucher_no']}: customer is required "
                f"for Credit Note posting."
            )

        if not note["customer_ledger_id"]:
            raise PostingError(
                f"Credit Note {note['voucher_no']}: customer "
                f"'{note['customer_name']}' has no linked Account Ledger."
            )

        # Verify the customer's ledger exists in account_ledgers
        customer_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE id = ?",
            (note["customer_ledger_id"],),
        ).fetchone()
        if customer_ledger is None:
            raise PostingError(
                f"Credit Note {note['voucher_no']}: customer ledger id "
                f"{note['customer_ledger_id']} does not exist in Account "
                f"Ledgers."
            )

        sales_return_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE system_role = ?",
            (ROLE_SALES_RETURN,),
        ).fetchone()
        if sales_return_ledger is None:
            raise PostingError(
                f"Credit Note {note['voucher_no']}: system account role "
                f"'SALES_RETURN' is not configured. Initialize Account "
                f"Roles first."
            )

        if self._active_nets_cur(cur, SOURCE_CREDIT_NOTE, note_id):
            raise PostingError(
                f"Credit Note {note['voucher_no']} already has an active "
                f"accounting posting — duplicate posting refused."
            )

        description = (
            f"Credit Note {note['voucher_no']} - {note['customer_name']}"
        )

        common = {
            "transaction_date": note["voucher_date"],
            "transaction_time": note["voucher_time"] or "",
            "voucher_type": VOUCHER_TYPE_CREDIT_NOTE,
            "voucher_no": note["voucher_no"],
            "reference_type": SOURCE_CREDIT_NOTE,
            "reference_id": note_id,
            "description": description,
        }

        amt = round(amount, 2)
        return [
            self._insert_posting_row(
                cur,
                {
                    **common,
                    "ledger_id": sales_return_ledger["id"],
                    "debit": amt,
                    "credit": 0.0,
                },
            ),
            self._insert_posting_row(
                cur,
                {
                    **common,
                    "ledger_id": note["customer_ledger_id"],
                    "debit": 0.0,
                    "credit": amt,
                },
            ),
        ]

    # ── debit note internals ────────────────────────────────────────
    def _post_debit_note_cur(
        self, cur: sqlite3.Cursor, note_id: int
    ) -> list[int]:
        note = cur.execute(
            """
            SELECT dn.*, su.supplier_name, su.ledger_id AS supplier_ledger_id
            FROM debit_notes dn
            LEFT JOIN suppliers su ON su.id = dn.supplier_id
            WHERE dn.id = ?
            """,
            (note_id,),
        ).fetchone()
        if note is None:
            raise PostingError(f"Debit note {note_id} not found.")

        amount = note["total_amount"] or 0.0
        # A zero/negative-amount note creates no accounting rows (legacy
        # DAO behavior allows empty-heading notes; posting nothing keeps
        # that behaviour intact). No rows → no duplicate posting risk.
        if amount <= _EPSILON:
            return []

        if not note["supplier_id"]:
            raise PostingError(
                f"Debit Note {note['voucher_no']}: supplier is required "
                f"for Debit Note posting."
            )

        if not note["supplier_ledger_id"]:
            raise PostingError(
                f"Debit Note {note['voucher_no']}: supplier "
                f"'{note['supplier_name']}' has no linked Account Ledger."
            )

        # Verify the supplier's ledger exists in account_ledgers
        supplier_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE id = ?",
            (note["supplier_ledger_id"],),
        ).fetchone()
        if supplier_ledger is None:
            raise PostingError(
                f"Debit Note {note['voucher_no']}: supplier ledger id "
                f"{note['supplier_ledger_id']} does not exist in Account "
                f"Ledgers."
            )

        purchase_return_ledger = cur.execute(
            "SELECT * FROM account_ledgers WHERE system_role = ?",
            (ROLE_PURCHASE_RETURN,),
        ).fetchone()
        if purchase_return_ledger is None:
            raise PostingError(
                f"Debit Note {note['voucher_no']}: system account role "
                f"'PURCHASE_RETURN' is not configured. Initialize Account "
                f"Roles first."
            )

        if self._active_nets_cur(cur, SOURCE_DEBIT_NOTE, note_id):
            raise PostingError(
                f"Debit Note {note['voucher_no']} already has an active "
                f"accounting posting — duplicate posting refused."
            )

        description = (
            f"Debit Note {note['voucher_no']} - {note['supplier_name']}"
        )

        common = {
            "transaction_date": note["voucher_date"],
            "transaction_time": note["voucher_time"] or "",
            "voucher_type": VOUCHER_TYPE_DEBIT_NOTE,
            "voucher_no": note["voucher_no"],
            "reference_type": SOURCE_DEBIT_NOTE,
            "reference_id": note_id,
            "description": description,
        }

        amt = round(amount, 2)
        return [
            self._insert_posting_row(
                cur,
                {
                    **common,
                    "ledger_id": note["supplier_ledger_id"],
                    "debit": amt,
                    "credit": 0.0,
                },
            ),
            self._insert_posting_row(
                cur,
                {
                    **common,
                    "ledger_id": purchase_return_ledger["id"],
                    "debit": 0.0,
                    "credit": amt,
                },
            ),
        ]

    # ── journal entry internals ─────────────────────────────────────
    def _post_journal_entry_cur(
        self, cur: sqlite3.Cursor, entry_id: int
    ) -> list[int]:
        entry = cur.execute(
            "SELECT * FROM journal_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if entry is None:
            raise PostingError(f"Journal entry {entry_id} not found.")

        items = cur.execute(
            "SELECT * FROM journal_entry_items WHERE journal_entry_id = ? "
            "ORDER BY id",
            (entry_id,),
        ).fetchall()

        if len(items) < 2:
            raise PostingError(
                f"Journal {entry['voucher_no']}: at least 2 lines required "
                f"for posting (got {len(items)})."
            )

        total_debit = 0.0
        total_credit = 0.0
        for i, item in enumerate(items):
            d = item["debit"] or 0.0
            c = item["credit"] or 0.0
            total_debit += d
            total_credit += c

            if d < 0 or c < 0:
                raise PostingError(
                    f"Journal {entry['voucher_no']}: line {i+1} debit/credit "
                    f"cannot be negative."
                )
            if d > 0 and c > 0:
                raise PostingError(
                    f"Journal {entry['voucher_no']}: line {i+1} cannot "
                    f"have both debit and credit."
                )
            if d == 0 and c == 0:
                raise PostingError(
                    f"Journal {entry['voucher_no']}: line {i+1} must "
                    f"have either debit or credit."
                )

            # Verify the referenced ledger exists
            ledger = cur.execute(
                "SELECT id FROM account_ledgers WHERE id = ?",
                (item["ledger_id"],),
            ).fetchone()
            if ledger is None:
                raise PostingError(
                    f"Journal {entry['voucher_no']}: line {i+1} references "
                    f"ledger id {item['ledger_id']} which does not exist."
                )

        if total_debit <= 0:
            raise PostingError(
                f"Journal {entry['voucher_no']}: total debit must be "
                f"greater than 0."
            )
        if abs(total_debit - total_credit) > 0.001:
            raise PostingError(
                f"Journal {entry['voucher_no']}: lines are not balanced "
                f"(debit {total_debit:.2f}, credit {total_credit:.2f})."
            )

        if self._active_nets_cur(cur, SOURCE_JOURNAL_ENTRY, entry_id):
            raise PostingError(
                f"Journal {entry['voucher_no']} already has an active "
                f"accounting posting — duplicate posting refused."
            )

        common = {
            "transaction_date": entry["entry_date"],
            "transaction_time": entry["entry_time"] or "",
            "voucher_type": VOUCHER_TYPE_JOURNAL_ENTRY,
            "voucher_no": entry["voucher_no"],
            "reference_type": SOURCE_JOURNAL_ENTRY,
            "reference_id": entry_id,
        }

        row_ids: list[int] = []
        for item in items:
            desc = item["description"] or entry["narration"] or ""
            row_ids.append(
                self._insert_posting_row(
                    cur,
                    {
                        **common,
                        "ledger_id": item["ledger_id"],
                        "description": desc,
                        "debit": round(item["debit"] or 0.0, 2),
                        "credit": round(item["credit"] or 0.0, 2),
                    },
                )
            )
        return row_ids

    # ── reversal internals ───────────────────────────────────────────
    def _reverse_cur(
        self, cur: sqlite3.Cursor, source_type: str, source_id: int
    ) -> list[int]:
        rows = cur.execute(
            "SELECT * FROM ledger_transactions "
            "WHERE reference_type = ? AND reference_id = ? ORDER BY id",
            (source_type, source_id),
        ).fetchall()
        if not rows:
            return []

        nets = self._active_nets_cur(cur, source_type, source_id)
        if not nets:
            return []

        meta = _SOURCE_TYPES[source_type]
        latest = rows[-1]
        description = f"REVERSAL: {meta['label']} {latest['voucher_no']}"

        new_ids: list[int] = []
        for ledger_id, net in nets.items():
            if net > 0:  # ledger was debited → credit it back
                debit, credit = 0.0, round(net, 2)
            else:        # ledger was credited → debit it back
                debit, credit = round(-net, 2), 0.0
            new_ids.append(
                self._insert_posting_row(
                    cur,
                    {
                        "ledger_id": ledger_id,
                        "transaction_date": latest["transaction_date"],
                        "transaction_time": latest["transaction_time"] or "",
                        "voucher_type": meta["reversal_voucher_type"],
                        "voucher_no": latest["voucher_no"],
                        "reference_type": source_type,
                        "reference_id": source_id,
                        "description": description,
                        "debit": debit,
                        "credit": credit,
                    },
                )
            )
        return new_ids

    def _active_nets_cur(
        self, cur: sqlite3.Cursor, source_type: str, source_id: int
    ) -> dict[int, float]:
        """Per-ledger net (debit − credit) of a posting identity.

        Empty dict → no active posting (no rows at all, or fully
        reversed). Non-empty → active posting exists.
        """
        rows = cur.execute(
            "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
            "FROM ledger_transactions "
            "WHERE reference_type = ? AND reference_id = ? "
            "GROUP BY ledger_id",
            (source_type, source_id),
        ).fetchall()
        nets = {
            r["ledger_id"]: (r["net"] or 0.0)
            for r in rows
            if abs(r["net"] or 0.0) > _EPSILON
        }
        return nets

    # ── row writer ───────────────────────────────────────────────────
    @staticmethod
    def _insert_posting_row(cur: sqlite3.Cursor, row: dict) -> int:
        cursor = cur.execute(
            """
            INSERT INTO ledger_transactions
                (ledger_id, transaction_date, transaction_time,
                 voucher_type, voucher_no, reference_type,
                 reference_id, description, debit, credit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["ledger_id"],
                row["transaction_date"],
                row["transaction_time"],
                row["voucher_type"],
                row["voucher_no"],
                row["reference_type"],
                row["reference_id"],
                row["description"],
                row["debit"],
                row["credit"],
            ),
        )
        return cursor.lastrowid


# Module-level singleton used by the DAOs.
posting_engine = PostingEngine()
