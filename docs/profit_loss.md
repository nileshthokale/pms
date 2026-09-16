# Profit & Loss — Phase 4C

**Date:** 2026-09-15
**Menu:** Account → Profit & Loss
**Files:** `database/profit_loss_dao.py`, `screens/profit_loss.py`, `test_profit_loss.py`

---

## 1. Purpose

The Profit & Loss (P&L) statement shows the business performance over a user-defined period: total Income, total Expenses, and the resulting Net Profit or Net Loss. It is a **period report** — only current-period transaction activity is counted; opening balances are excluded.

> **Important:** The P&L reads only from the centralized accounting source (`account_ledgers` + `ledger_transactions` + `account_groups`). Source documents are never queried.

## 2. Authoritative Data Source

The P&L reads **exclusively** from:

- `account_ledgers` — ledger master, account group linkages
- `account_groups` — group name and `statement_type` (INCOME or EXPENSE)
- `ledger_transactions` — rows written by the PostingEngine for all 7 integrated source types

Source documents (`sales_invoices`, `purchase_invoices`, `customer_receipts`, `supplier_payments`, `credit_notes`, `debit_notes`, `journal_entries`) are **never** queried. The P&L shows the resulting ledger effects, not the business documents.

## 3. Period Logic

- **Default (UI):** From/To date filters, defaulting to empty (all activity).
- **Default (DAO, `from_date=None, to_date=None`):** no filter — all activity.
- With a from/to range, only transactions with `transaction_date >= from_date AND transaction_date <= to_date` are counted.
- **Date assumption:** `transaction_date` is stored as ISO `YYYY-MM-DD` TEXT, so filtering uses string comparison.

## 4. Income Calculation

Income ledgers are those with `account_groups.statement_type = 'INCOME'`.

For each income ledger within the period:

```
amount = Σ credits − Σ debits
```

Income is credit-positive: a sales transaction credits the Sales ledger, increasing income. A sales return debits the Sales Return ledger, reducing income. The net result reflects the actual revenue activity.

## 5. Expense Calculation

Expense ledgers are those with `account_groups.statement_type = 'EXPENSE'`.

For each expense ledger within the period:

```
amount = Σ debits − Σ credits
```

Expense is debit-positive: a purchase transaction debits the Purchase ledger, increasing expense. A purchase return credits the Purchase Return ledger, reducing expense.

## 6. Sales Treatment

The Sales system ledger (`system_role = 'SALES'`) is classified as INCOME via the `Sales Accounts` account group. Counter sale transactions credit the Sales ledger for `net_amount`, increasing income. Sales returns (Credit Notes) debit the Sales Return ledger, reducing income. The net effect on income reflects actual revenue after returns.

## 7. Purchase Treatment

The Purchase system ledger (`system_role = 'PURCHASE'`) is classified as EXPENSE via the `Purchase Accounts` account group. Purchase invoice transactions debit the Purchase ledger for `net_amount`, increasing expense. Purchase returns (Debit Notes) credit the Purchase Return ledger, reducing expense. The net effect on expense reflects actual cost of goods purchased after returns.

## 8. Sales Return Treatment

The Sales Return system ledger (`system_role = 'SALES_RETURN'`) is classified as INCOME via the `Sales Accounts` account group (contra-revenue). Credit Note transactions debit the Sales Return ledger for `total_amount`. Since income is calculated as `credits − debits`, the debit reduces total income, correctly reflecting returns against sales.

## 9. Purchase Return Treatment

The Purchase Return system ledger (`system_role = 'PURCHASE_RETURN'`) is classified as EXPENSE via the `Purchase Accounts` account group (contra-expense). Debit Note transactions credit the Purchase Return ledger for `total_amount`. Since expense is calculated as `debits − credits`, the credit reduces total expense, correctly reflecting returns against purchases.

## 10. Other Income

Other income (e.g., interest received, commission received) is recognized when a ledger is classified as INCOME via its account group. Any ledger whose `account_groups.statement_type = 'INCOME'` appears in the income section regardless of whether it is a system-role ledger or a custom user-created ledger.

## 11. Other Expense

Other expense (e.g., rent, salaries, utilities) is recognized when a ledger is classified as EXPENSE via its account group. Operating expenses recorded via Journal Entries to expense-classified ledgers correctly appear in the expense section.

## 12. Excluded Accounts

The following account types are **excluded** from P&L totals because they are Balance Sheet items (assets/liabilities), not income/expense:

| Account Group | Classification | Reason |
|---|---|---|
| Sundry Debtors (Customer ledgers) | Balance Sheet — Current Assets | Receivable, not income |
| Sundry Creditors (Supplier ledgers) | Balance Sheet — Current Liabilities | Payable, not expense |
| Cash-in-Hand (Cash ledger) | Balance Sheet — Current Assets | Cash asset |
| Bank Accounts (Bank ledger) | Balance Sheet — Current Assets | Bank asset |
| Capital Accounts | Balance Sheet — Equity | Owner's equity |

These ledgers have `statement_type` that is not INCOME or EXPENSE, so the P&L query classifies them as unclassified and excludes them from income/expense totals.

## 13. Reversal Handling

The P&L uses the same active-net concept as the PostingEngine and Trial Balance:

- Reversal rows are real accounting rows that offset their originals on the same ledger.
- When both original and reversal fall within the period, they net to zero.
- A ledger with zero net activity within the period (`abs(amount) <= EPSILON`) is **excluded** from the report entirely — it does not appear as a zero-amount row.
- A ledger whose original is within the period but whose reversal is outside the period will show the original amount only (correct behavior for period-based reporting).
- The `EPSILON = 0.005` tolerance matches the PostingEngine's float tolerance.

## 14. Unclassified Accounts

Ledgers with `account_group_id IS NULL` or whose group's `statement_type` is not INCOME or EXPENSE are classified as **unclassified**. They are:

1. Listed separately in the `unclassified` section of the report.
2. **Excluded** from both `total_income` and `total_expenses` calculations.
3. **Not** counted in the net result.

This ensures that only properly classified income and expense accounts affect the P&L.

## 15. Net Profit / Loss Calculation

```
net = total_income − total_expenses
```

- `net > +EPSILON` → "Net Profit"
- `net < -EPSILON` → "Net Loss"
- otherwise → "No Profit / No Loss"

The net result is purely informational — no transaction is created for it.

## 16. Inventory / COGS Limitation

The P&L does **not** include Cost of Goods Sold (COGS) or inventory valuation. This follows from the approved periodic inventory posture (Decision 5 in `accounting_decisions.md`):

- No Inventory or COGS ledger postings exist.
- Stock is valued at purchase rate; no automatic cost allocation occurs at sale time.
- The P&L reflects Sales minus Purchases (and their returns), not gross margin.
- This limitation is always flagged in the report (`has_cogs_limitation: True`).

## 17. GST Limitation

The P&L does **not** separate GST components. This follows from the approved gross posting decision (Decision 4a in `accounting_decisions.md`):

- Sales and Purchase transactions carry no reliable GST breakdown in the current schema.
- No GST ledger postings exist.
- Tax is embedded in the transaction amounts.
- This limitation is always flagged in the report (`has_gst_limitation: True`).

## 18. Trial Balance Relationship

The P&L and Trial Balance share the same data source (`account_ledgers` + `ledger_transactions`) but differ in scope:

| Aspect | Trial Balance | P&L |
|---|---|---|
| Period | As-of (cumulative) | From/To (period) |
| Opening balances | Included | Excluded |
| Account types | All ledgers | INCOME / EXPENSE only |
| Calculation | Debit vs Credit balance | Revenue − Expense per period |

A Trial Balance row for an income/expense ledger will differ from the P&L amount when:
- Opening balances are non-zero (TB includes them, P&L excludes them).
- Transactions exist outside the P&L period (TB includes all, P&L filters by date).

## 19. Balance Sheet Relationship

The P&L and Balance Sheet are complementary statements:

- **P&L** shows period performance (Income, Expenses, Net Profit/Loss).
- **Balance Sheet** shows position as of a date (Assets, Liabilities, Equity).

The P&L excludes Balance Sheet items (Cash, Bank, Customers, Suppliers, Capital) which appear on the Balance Sheet. The P&L's net result (profit/loss) flows into the Balance Sheet as retained earnings (future phase).

## 20. Known Limitations

1. **No COGS / Inventory valuation** — periodic inventory posture (§16).
2. **No GST separation** — gross posting, tax embedded (§17).
3. **No departmental / cost-center breakdown** — the P&L shows the full business, not per-department.
4. **No comparative period** — the report shows one period only; prior-period comparison is a future enhancement.
5. **Classification accuracy depends on account groups** — misclassified ledgers will appear in the wrong section.
6. The P&L reflects configured ledger postings, not professional accounting advice.

## 21. Running

```
python run_tests.py                              # full suite (730 tests)
python -m unittest test_profit_loss -v           # P&L tests only (50 tests)
```

The 4 UI tests (38–41) require PySide6 and skip with an explicit dependency reason in environments without it; they execute for real in the development environment.
