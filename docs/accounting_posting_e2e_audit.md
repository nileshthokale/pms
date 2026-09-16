# Accounting Posting End-to-End Audit

## Overview

This document describes the end-to-end audit test suite (`test_accounting_end_to_end.py`) that verifies all 7 accounting source types post correctly and coexist without interference.

## Source Types Under Test

| # | Source Type | Debit | Credit | Entry Shape |
|---|---|---|---|---|
| 1 | CUSTOMER_RECEIPT | CASH or BANK | Customer Ledger | 2 rows |
| 2 | SUPPLIER_PAYMENT | Supplier Ledger | CASH or BANK | 2 rows |
| 3 | COUNTER_SALE | CASH (walk-in) or Tender+Customer | SALES | 2-3 rows |
| 4 | PURCHASE_INVOICE | PURCHASE | Supplier + CASH/BANK | 2-3 rows |
| 5 | CREDIT_NOTE | SALES_RETURN | Customer Ledger | 2 rows |
| 6 | DEBIT_NOTE | Supplier Ledger | PURCHASE_RETURN | 2 rows |
| 7 | JOURNAL_ENTRY | Mirrors journal lines exactly | Mirrors journal lines exactly | N rows (one per journal line) |

## Audit Scenarios (11 Classes, 29 Tests)

### Scenario 1: Customer Receipt Posting
- **Tests 01-03**: Verifies cash receipt debits CASH ledger, bank receipt debits BANK ledger, and reference fields (reference_type, voucher_no, voucher_type) are correct.

### Scenario 2: Supplier Payment Posting
- **Tests 04-05**: Verifies cash payment credits CASH ledger, bank payment credits BANK ledger, and amounts match.

### Scenario 3: Counter Sale (Walk-in Cash) Posting
- **Tests 06-07**: Verifies walk-in cash sale debits CASH and credits SALES for net_amount, and voucher_type is "Counter Sale".

### Scenario 4: Purchase Invoice (Credit) Posting
- **Tests 08-09**: Verifies credit purchase debits PURCHASE and credits Supplier Ledger; partial payment produces 3 rows (PURCHASE debit, CASH credit, Supplier credit).

### Scenario 5: Credit Note Posting
- **Test 10**: Verifies credit note debits SALES_RETURN and credits Customer Ledger for total_amount.

### Scenario 6: Debit Note Posting
- **Test 11**: Verifies debit note debits Supplier Ledger and credits PURCHASE_RETURN for total_amount.

### Scenario 7: Journal Entry Posting
- **Tests 12-13**: Verifies journal entry posts N rows (one per journal line) mirroring the journal lines exactly, and reference_type is "JOURNAL_ENTRY" with voucher_type "Journal Entry".

### Scenario 8: Edit-and-Repost Lifecycle
- **Tests 14-18**: For customer receipt, supplier payment, credit note, debit note, and journal entry: insert -> verify -> edit amount -> verify new posting matches updated amount. Old posting is reversed, new posting is created.

### Scenario 9: Delete (Reversal) Lifecycle
- **Tests 19-23**: For customer receipt, supplier payment, credit note, debit note, and journal entry: insert -> verify posted -> delete -> verify is_posted() returns False and nets are zero.

### Scenario 10: Cross-Module Independence
- **Tests 24-25**: Creates all 7 source types in the same database and verifies each posts independently without affecting others. Checks global balance invariant: SUM(all debits) == SUM(all credits).

### Scenario 11: Persistence and Balance Consistency
- **Tests 26-29**: Verifies posting rows are visible via get_posting_rows(), LedgerDAO.get_transactions(), and fresh sqlite3 connections. Verifies multiple receipts accumulate correctly.

## How to Run

```bash
python run_tests.py
```

Or run just the audit tests:

```bash
python -m unittest test_accounting_end_to_end -v
```

## Expected Results

All 29 tests should pass with 0 failures and 0 errors.

## Files

| File | Purpose |
|---|---|
| `test_accounting_end_to_end.py` | 11 audit test classes, 29 tests |
| `docs/accounting_posting_e2e_audit.md` | This documentation |
