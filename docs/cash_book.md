# Cash Book — Phase 6B-3

**Date:** 2026-09-16  
**Menu:** Account → Cash Book  
**Files:** `database/cash_book_dao.py`, `screens/cash_book.py`, `test_cash_book.py`

## 1. Purpose

Provide a read-only Cash Book report over the application's authoritative accounting ledger data.

## 2. Data Source

The report reads `ledger_transactions` joined conceptually to the `account_ledgers` row whose `system_role = 'CASH'`. It does not read source invoices directly and does not maintain a second cash balance.

## 3. CASH System Role

Cash is identified by the existing structured `system_role` value `CASH`, never by a numeric ledger ID or ledger display name. If no CASH ledger exists, the report shows a clear configuration/empty state and does not create one.

## 4. Debit/Credit Convention

The report follows the existing Trial Balance and PostingEngine convention: ledger net movement is `debit - credit`. A debit increases the running cash balance; a credit decreases it.

## 5. Opening Balance

For `From Date`, opening balance is the CASH ledger's stored opening balance, positive for Debit and negative for Credit, plus all CASH ledger transaction debit-minus-credit movement strictly before the selected start date.

## 6. Running Balance

Rows are ordered by transaction date, time, and transaction ID. Each row updates `running balance = previous balance + debit - credit`.

## 7. Closing Balance

Closing balance is `opening balance + period total debit - period total credit`. It is read from the same ledger rows and is not manually persisted or adjusted.

## 8. Date Filters

From Date and To Date are validated as ISO dates and require From Date <= To Date. Both boundaries are inclusive for displayed transactions. Historical periods remain viewable even when another FY is active.

## 9. Financial Year

The initial report range comes from the active financial year service: active FY start through active FY end. Manual date changes are preserved until the page is recreated/refreshed with new defaults. The Cash Book never changes FY records.

## 10. Transaction Inclusion

Any posting whose ledger is the CASH system ledger appears naturally, including cash sales, purchases, receipts, supplier payments, notes, and journals when the existing PostingEngine posts them to CASH.

## 11. Bank Exclusion

Bank transactions are excluded unless they were actually posted to the CASH ledger. Payment labels alone do not determine inclusion; the ledger ID resolved from `system_role = 'CASH'` is authoritative.

## 12. Permissions

Both ADMIN and PHARMACIST/STAFF retain the existing report-view permission and may view Cash Book. Printing follows the existing report/document behavior; no new role or permission was introduced.

## 13. Printing

The page offers Print / PDF and reuses the existing read-only document renderer. It exports the selected report values without inserting or changing ledger rows.

## 14. Read-Only Behavior

The DAO performs parameterized SELECT queries only. Opening, refreshing, filtering, printing, and repeated generation do not create postings, alter balances, change stock, or update the database.

## 15. Testing

`test_cash_book.py` contains 50 isolated tests covering empty/configuration states, opening and closing balances, boundaries, historical periods, debit/credit totals, running balances, non-cash exclusion, FY defaults, read-only behavior, persistence, and integrity of stored references.

## 16. Limitations and Future Enhancements

The report does not implement Bank Book, day-end closing, reconciliation, cheque-clearing workflows, or automatic cash adjustments. Future work may add richer PDF table headers, account-level drill-down, and reconciliation/export formats.
