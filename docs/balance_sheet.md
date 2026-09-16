# Balance Sheet — Phase 4D

**Date:** 2026-09-15
**Menu:** Account → Balance Sheet
**Files:** `database/balance_sheet_dao.py`, `screens/balance_sheet.py`, `test_balance_sheet.py`

---

## 1. Purpose

The Balance Sheet shows the financial position of the business as of a specific date: total Assets, total Liabilities, total Equity, and whether they balance. It is an **as-of-date report** — opening balances are included, and only transaction activity up to and including the as-of date is counted.

> **Important:** The Balance Sheet reads only from the centralized accounting source (`account_ledgers` + `ledger_transactions` + `account_groups`). Source documents are never queried. The Balance Sheet reflects configured ledger postings, not professional accounting advice.

## 2. Authoritative Data Source

The Balance Sheet reads **exclusively** from:

- `account_ledgers` — ledger master, opening balances, account group linkages
- `account_groups` — group name, `statement_type` (ASSET, LIABILITY, EQUITY), and `normal_balance`
- `ledger_transactions` — rows written by the PostingEngine for all 7 integrated source types

Source documents are never queried. The Balance Sheet shows the resulting ledger effects, not the business documents.

## 3. As-of-Date Behavior

- **Default (UI):** today's date. **Default (DAO, `as_of_date=None`):** no filter — all activity.
- With an as-of date, only transactions with `transaction_date <= as_of_date` are counted; future transactions never affect a historical as-of report.
- Opening balances are **always** included in as-of calculations (same as Trial Balance).
- **Date assumption:** `transaction_date` is stored as ISO `YYYY-MM-DD` TEXT, so filtering uses string comparison.

## 4. Asset Classification

Ledgers with `account_groups.statement_type = 'ASSET'` appear in the Assets section.

For each asset ledger:

```
amount = (Σ transaction debits + opening debit) − (Σ transaction credits + opening credit)
```

Assets are debit-normal: a positive net means a normal debit balance. An asset with a credit balance (unusual) is shown as a negative amount rather than silently reclassified.

**Examples:** Cash, Bank, Customer / Sundry Debtors, Fixed Assets.

## 5. Liability Classification

Ledgers with `account_groups.statement_type = 'LIABILITY'` appear in the Liabilities section.

For each liability ledger:

```
amount = −net  (where net = Σ debits − Σ credits, same formula as assets)
```

Liabilities are credit-normal: when credit exceeds debit, `net` is negative, so `−net` is positive. A liability with a debit balance (unusual) is shown as a negative amount.

**Examples:** Supplier / Sundry Creditors, Long Term Liabilities, Loans.

## 6. Equity Classification

Ledgers with `account_groups.statement_type = 'EQUITY'` appear in the Equity / Capital section.

For each equity ledger:

```
amount = −net  (same formula as liabilities)
```

Equity is credit-normal. **Examples:** Capital, Reserves.

**Current Profit/Loss:** The approved design does not yet define how current-period profit/loss flows into equity. The Balance Sheet documents this limitation rather than manufacturing a balancing amount. See §13.

## 7. Customer Classification

Customer ledgers are classified as **Current Assets** (statement_type = ASSET) via the `Sundry Debtors` → `Current Assets` mapping applied during `migrate_legacy_ledger_groups()`. They appear in the Assets section with their net debit balance.

No separate customer/supplier table queries are needed — the classification is stored on the ledger's `account_group_id`.

## 8. Supplier Classification

Supplier ledgers are classified as **Current Liabilities** (statement_type = LIABILITY) via the `Sundry Creditors` → `Current Liabilities` mapping. They appear in the Liabilities section with their net credit balance.

## 9. System Account Classification

System ledgers are classified according to their structured account groups (set during `migrate_legacy_ledger_groups()`):

| System Role | Ledger Name | Structured Group | Statement Type | Balance Sheet Section |
|---|---|---|---|---|
| CASH | Cash | Current Assets | ASSET | Assets |
| BANK | Bank | Current Assets | ASLET | Assets |
| SALES | Sales | Sales | INCOME | Not on Balance Sheet |
| PURCHASE | Purchase | Purchase-related | EXPENSE | Not on Balance Sheet |
| SALES_RETURN | Sales Return | Sales | INCOME | Not on Balance Sheet |
| PURCHASE_RETURN | Purchase Return | Purchase-related | EXPENSE | Not on Balance Sheet |

Sales, Purchase, Sales Return, and Purchase Return are **not** Balance Sheet accounts. Their effects appear on the P&L, not the Balance Sheet directly. The Balance Sheet does not hardcode by `system_role` — classification is driven entirely by `account_groups.statement_type`.

## 10. Normal-Balance Handling

Each account group carries a `normal_balance` (DEBIT or CREDIT):

- **DEBIT-normal accounts** (Assets, Expenses): debit increases the balance.
- **CREDIT-normal accounts** (Liabilities, Equity, Income): credit increases the balance.

The Balance Sheet respects the actual ledger balance sign:

- For ASSET accounts: `amount = net` (positive = normal debit balance)
- For LIABILITY accounts: `amount = −net` (positive = normal credit balance)
- For EQUITY accounts: `amount = −net` (positive = normal credit balance)

Unusual signs (e.g., an asset with a credit balance) are shown explicitly rather than silently converted.

## 11. Reversal Handling

The Balance Sheet uses the same active-net concept as the PostingEngine, Trial Balance, and P&L:

- Reversal rows are real accounting rows that offset their originals on the same ledger.
- When both original and reversal fall within the as-of period, they net to zero.
- A ledger with zero net activity within the period (`abs(amount) <= EPSILON`) is excluded from the report.
- Historical reversal rows are never double-counted.
- The `EPSILON = 0.005` tolerance matches the PostingEngine's float tolerance.

## 12. Unclassified-Account Handling

Ledgers with `account_group_id IS NULL` or whose group's `statement_type` is not ASSET, LIABILITY, or EQUITY are classified as **unclassified**. They are:

1. Listed separately in the `unclassified` section of the report.
2. **Excluded** from `total_assets`, `total_liabilities`, and `total_equity`.
3. **Not** counted in the balance difference.

This ensures that only properly classified ledgers affect the Balance Sheet totals.

## 13. P&L / Current-Result Treatment

The approved design does not yet define how current-period profit or loss enters equity. The Balance Sheet:

1. **Does** exclude Income and Expense accounts from the Assets/Liabilities/Equity sections (they are not permanent Balance Sheet accounts).
2. **Does not** automatically include the P&L net result in Equity.
3. **Does not** create closing journal entries or fiscal-year closing entries.

When the P&L shows a profit or loss, the Balance Sheet will be unbalanced (Assets ≠ Liabilities + Equity) because the income/expense effect is not captured in any equity account. This is the expected behavior until the P&L-to-equity treatment is formally defined.

## 14. Balance Calculation

```
total_assets      = Σ of all asset amounts
total_liabilities  = Σ of all liability amounts
total_equity       = Σ of all equity amounts
difference         = total_assets − (total_liabilities + total_equity)
```

## 15. Difference / Status

The report determines one of three statuses:

- **BALANCED**: `abs(difference) <= EPSILON` — Assets equals Liabilities + Equity.
- **UNBALANCED**: `abs(difference) > EPSILON` — Assets do not equal Liabilities + Equity. The difference amount is shown. This may occur when:
  - P&L result is not yet captured in equity (§13).
  - Data inconsistency exists in the ledger transactions.
  - The dataset is intentionally unbalanced.
- **EQUITY TREATMENT REQUIRED**: Reserved for when P&L-to-equity treatment is implemented but incomplete.

The report **never** inserts artificial balancing entries and never silently forces BALANCED.

## 16. Relationship to Trial Balance

| Aspect | Trial Balance | Balance Sheet |
|---|---|---|
| Report type | As-of-date | As-of-date |
| Opening balances | Included | Included |
| Account types | All ledgers | ASSET, LIABILITY, EQUITY only |
| Classification | None (raw balances) | By account_groups.statement_type |
| Balance check | Total Debit = Total Credit | Assets = Liabilities + Equity |
| Income/Expense | Listed as-is | Excluded (appear on P&L) |

For the same as-of date, the Balance Sheet ledger amounts for ASSET/LIABILITY/EQUITY accounts must agree with the Trial Balance for those same ledgers (verified by test 32).

## 17. Relationship to P&L

The P&L and Balance Sheet are complementary statements:

- **Balance Sheet** shows position as of a date (Assets, Liabilities, Equity).
- **P&L** shows period performance (Income, Expenses, Net Profit/Loss).

The Balance Sheet excludes Income and Expense accounts which appear on the P&L. The P&L's net result (profit/loss) should theoretically flow into Equity on the Balance Sheet, but this is not yet implemented (§13).

For the same date/period, the Balance Sheet's excluded accounts should match the P&L's included accounts (verified by test 34).

## 18. Known Limitations

1. **No P&L-to-equity mechanism** — current-period profit/loss is not captured in equity (§13).
2. **No COGS / Inventory valuation** — periodic inventory posture (no Inventory asset account).
3. **No GST separation** — gross posting, tax embedded (no Tax liability account).
4. **No fiscal-year closing** — no closing journal entries, no retained earnings accumulation.
5. **No comparative periods** — single as-of-date only.
6. **Classification accuracy depends on account groups** — misclassified ledgers appear in the wrong section.
7. The Balance Sheet reflects configured ledger postings, not professional accounting advice.

## 19. No Automatic Balancing Entries

The Balance Sheet **never**:

- Inserts artificial balancing entries.
- Creates closing journal entries for income/expense accounts.
- Silently forces BALANCED when the data is unbalanced.
- Manufactures a retained-earnings amount to balance the report.

An unbalanced result is displayed exactly as found, including the difference amount. This is explicit and visible — no hidden adjustments.

## Running

```
python run_tests.py                              # full suite (780 tests)
python -m unittest test_balance_sheet -v         # Balance Sheet tests only (50 tests)
```

The 5 UI tests (36–39, 50) require PySide6 and skip with an explicit dependency reason in environments without it; they execute for real in the development environment.
