# Trial Balance — Phase 3

**Date:** 2026-09-15
**Menu:** Account → Trial Balance
**Files:** `database/trial_balance_dao.py`, `screens/trial_balance.py`, `test_trial_balance.py`

---

## 1. Purpose

The Trial Balance is the first accounting report of the application. It lists every Account Ledger with its closing Debit or Credit balance and verifies the fundamental double-entry invariant: **Total Debit = Total Credit**.

> **Important:** The Trial Balance verifies only that the configured ledger postings balance. It does **not** prove that the underlying business accounting rules are economically correct (chart-of-accounts classification, revenue recognition, valuation, etc. — see §10).

## 2. Source of Accounting Data

The report reads **exclusively** from the centralized accounting source:

- `account_ledgers` (ledger master, opening balances, account groups, system roles)
- `ledger_transactions` (rows written by the PostingEngine for all 7 integrated source types: CUSTOMER_RECEIPT, SUPPLIER_PAYMENT, COUNTER_SALE, PURCHASE_INVOICE, CREDIT_NOTE, DEBIT_NOTE, JOURNAL_ENTRY)

The Trial Balance **never** queries source documents (`sales_invoices`, `purchase_invoices`, `customer_receipts`, `supplier_payments`, `credit_notes`, `debit_notes`, `journal_entries`). Those are inputs to the PostingEngine; the report shows the resulting ledger effects. One grouped LEFT-JOIN query produces the whole report (no N+1).

## 3. Opening Balance Treatment

Each ledger's `opening_balance` (with `opening_balance_type`) is **always** included, regardless of the as-of date:

- Opening type `Debit` → added to the ledger's debit side
- Opening type `Credit` → added to the ledger's credit side

Note: opening balances are entered per ledger and are **not** automatically balanced among themselves. A Trial Balance over ledgers whose openings do not sum to zero on both sides will legitimately report UNBALANCED until balanced opening entries (e.g., an opening Journal Entry) are recorded.

## 4. Active Transaction Treatment

A ledger's transaction effect is the per-ledger **net** of all its `ledger_transactions` rows — the same active-net concept the PostingEngine uses (`PostingEngine._active_nets_cur`): reversal rows are real accounting rows that offset their originals, so a fully reversed transaction contributes zero. This means:

- Historical reversal rows are **never double-counted** (they net against the original on the same ledger).
- A net within `EPSILON = 0.005` (the engine's tolerance) of zero is presented as a zero balance.
- Deleted/edited transactions produce the correct current net (reverse-old + post-new rows net to the new state).

## 5. As-of-Date Behavior

- **Default (UI):** today's date. **Default (DAO, `as_of_date=None`):** no filter — all activity.
- With an as-of date, only transactions with `transaction_date <= as_of_date` are counted; future transactions never affect a historical as-of report.
- Opening balances are **always** included in historical as-of calculations (§3).
- **Date assumption:** `transaction_date` is stored as ISO `YYYY-MM-DD` TEXT, so filtering uses string comparison, which is correct for ISO dates.

## 6. Debit/Credit Calculation

For each ledger:

```
debit_total  = Σ transaction debits  + opening (if opening type = Debit)
credit_total = Σ transaction credits + opening (if opening type = Credit)

net = debit_total − credit_total

net > +EPSILON  →  Debit column  = net,  Credit column = 0
net < −EPSILON  →  Debit column  = 0,    Credit column = −net
otherwise       →  both columns 0 (zero balance)
```

Exactly one of Debit/Credit is ever non-zero for a ledger (never both). Per-ledger figures and totals are computed from raw sums; values are rounded to 2 decimals only for presentation. The global difference is never rounded away.

## 7. Zero-Balance Behavior

Following the Account Ledger screen convention (all ledgers listed), the Trial Balance **shows every ledger by default**, including zero-balance ones, with a "Show Zero Balance" checkbox to hide them. Hiding zero balances does not affect totals (hidden ledgers are zero by definition).

## 8. Balance Invariant

```
Total Debit  = Σ of all closing Debit columns
Total Credit = Σ of all closing Credit columns
Difference   = Total Debit − Total Credit
Status       = BALANCED  when |Difference| <= 0.005
               UNBALANCED otherwise
```

The report **never** inserts artificial balancing entries and never silently adjusts an imbalance. An UNBALANCED result is displayed exactly as found (with the difference amount), including its cause class: unbalanced manual `ledger_transactions` rows or unbalanced opening balances. Balanced posted data (all 7 source types post balanced vouchers by construction) yields Difference = 0.

## 9. Relationship to Account Ledger

The per-ledger logic is shared, not duplicated: `LedgerDAO.get_balance(ledger_id)` delegates to the new `LedgerDAO.get_balance_as_of(ledger_id, as_of_date)` (identical formula, optional ISO date filter). The Trial Balance's as-of row for any ledger equals the Account Ledger detail balance for the same date (verified by test 23). System-role ledgers (CASH, BANK, SALES, PURCHASE, SALES_RETURN, PURCHASE_RETURN) and customer/supplier ledgers appear exactly like any other ledger — nothing is excluded based on `system_role`, and no customers/suppliers tables are queried.

## 10. Known Accounting Limitations

Inherited from the approved Phase 2 decisions (docs/accounting_decisions.md):

1. **No GST ledgers** — sales carry no tax data (Decision 4a); tax is embedded in amounts.
2. **Periodic inventory** — no Inventory/COGS accounts (Decision 5); the Balance Sheet side of the TB has no stock asset, and margins are Sales − Purchases.
3. **NET posting** — discounts and round-off are absorbed into Sales/Purchase amounts (Decisions 1/2).
4. **Opening balances are manual** — they balance only if entered balanced (§3).
5. The TB proves **arithmetic balance of postings**, not economic correctness of the accounting policy.

## 11. Future Relationship to P&L and Balance Sheet

The Trial Balance is the foundation for the future statements:

- **Profit & Loss** = TB rows for income/expense ledgers (Sales, Sales Return, Purchase, Purchase Return) classified by account group over a period.
- **Balance Sheet** = TB rows for asset/liability ledgers (Cash, Bank, Sundry Debtors, Sundry Creditors) as of a date.

Both will consume the same `ledger_transactions` + `account_ledgers` source and the same as-of filtering. A prerequisite surfaced there (not blocking the TB): `account_group` is free text today, so a group→statement-section classification will be needed before P&L/Balance Sheet can be generated reliably.

## Running

```
python run_tests.py                                  # full suite
python -m unittest test_trial_balance -v             # TB tests only
```

The 4 UI tests (38–41) require PySide6 and skip with an explicit dependency reason in environments without it; they execute for real in the development environment.
