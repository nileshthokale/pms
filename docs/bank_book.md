# Bank Book — Phase 6B-4

**Date:** 2026-09-16  
**Menu:** Account → Bank Book  
**Files:** `database/bank_book_dao.py`, `screens/bank_book.py`, `test_bank_book.py`

## 1. Purpose

Provide a read-only Bank Book report over the existing accounting ledger.

## 2. BANK System Role

The report identifies the ledger by `account_ledgers.system_role = 'BANK'`. It never uses a hard-coded ledger ID or ledger name. If no BANK ledger exists, the page displays a configuration/empty state and does not create one.

## 3. Data Source

Only `ledger_transactions` belonging to the BANK system-role ledger are read. Source payment records, invoices, and journals are not queried for inclusion; the ledger is authoritative.

## 4. Debit/Credit Convention

The report follows Trial Balance and PostingEngine convention: net movement is `debit - credit`. Debit increases the running balance and credit decreases it.

## 5. Opening Balance

Opening balance is the stored BANK ledger opening balance, positive for Debit and negative for Credit, plus all BANK ledger debit-minus-credit movement strictly before From Date.

## 6. Running Balance

Rows are ordered by transaction date, time, and transaction ID. Each row calculates `previous balance + debit - credit`.

## 7. Closing Balance

Closing balance equals opening balance plus period total debit minus period total credit. It is calculated from the existing ledger rows and is not persisted.

## 8. Filters

From Date and To Date are validated ISO dates with From Date <= To Date. Both period boundaries are inclusive. Historical dates remain viewable even when another financial year is active.

## 9. Financial Year

Default filters use the active financial year start and end from the centralized service. The Bank Book does not modify financial-year records.

## 10. Transaction Inclusion

Bank Book naturally includes any existing posting that targets BANK, including bank receipts, supplier payments, bank purchases, supported bank sales, bank journals, and other legitimate BANK ledger effects.

## 11. Cash and Unrelated Exclusion

CASH ledger movements and unrelated ledgers are excluded because the query filters by the resolved BANK ledger ID. Payment labels alone do not cause inclusion.

## 12. Permissions

ADMIN and PHARMACIST/STAFF may view Bank Book using the existing report access policy. No role or permission was added.

## 13. Printing

Print / PDF reuses the existing read-only document renderer. Bank Book rows and totals are exported without database writes.

## 14. Read-Only Behavior

DAO operations are parameterized SELECTs. Opening, refreshing, filtering, printing, and repeated generation do not create postings, modify balances, change stock, or update financial-year records.

## 15. Testing

`test_bank_book.py` contains 51 isolated tests covering empty/configuration states, opening/running/closing balances, date boundaries, historical ranges, BANK-only selection, CASH exclusion, read-only behavior, persistence, and PDF content.

## 16. Limitations and Future Enhancements

This phase does not implement Day End, reconciliation, cheque clearing, exports beyond PDF, or any new accounting posting rule. Future work may add richer report export and bank reconciliation workflows.
