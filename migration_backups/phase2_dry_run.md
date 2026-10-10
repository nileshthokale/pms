# Phase 2 Dry Run — Party/Reference Masters ONLY

- Source: `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\PharmaWinner202610051955.sql` (35,462,774 bytes, READ-ONLY)

## Source counts

- ledger: 123
- debtors: 29
- creditors: 85
- sundaryinfo: 113
- doctormst: 8

## Target expected

- customers: 29
- suppliers: 85
- doctors: 8

## Missing info rows (defaults): [7]
## Orphan info rows: []
## Duplicate doctors: {"SELF": [3, 6]}
## Duplicate debtors/customers: {}
## Duplicate creditors/suppliers: {}
## Opening balances NOT imported: 32 parties

## Unsupported fields
- ledger.OpeningBal (opening balances forbidden in Phase 2)
- ledger.AdminCreated / gpmst (no target; groups not imported)
- ledger.SGpID beyond debtor/creditor split (system ledgers excluded)
- sundaryinfo.StateID=0/unknown -> state '' (no invention)
- suppliers/customers.ledger_id stays NULL (no ledgers in Phase 2)
- customers have no sales_tax_no/vat columns in new schema

## Blockers: none

- none — internally consistent

Internally consistent: True
