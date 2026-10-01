# Imported Data Verification

## Scope

This is a read-only verification of the live imported SQLite database used by the pharmacy application. The imported historical dataset was not re-imported, cleared, or reconnected to MySQL during this check.

## Live database evidence

- Database path: `data/pharmacy.db`
- Database exists: Yes
- SHA-256 (current SQLite file): `25baac356ba43c891c2f666793dfb5a6f7775fbc1d3c7bbb04a2733c3184a06c`
- Size: `42,602,496` bytes
- Tables present (non-SQLite system tables): `32`

## Major migrated table counts

| Table | Count |
| --- | ---: |
| companies | 1218 |
| units | 16 |
| drugs | 147 |
| doctors | 7 |
| suppliers | 85 |
| customers | 29 |
| items | 938 |
| item_ingredients | 402 |
| account_groups | 13 |
| account_ledgers | 123 |
| financial_years | 12 |
| purchase_invoices | 5681 |
| purchase_invoice_items | 11829 |
| sales_invoices | 71803 |
| sales_invoice_items | 232707 |
| credit_notes | 1345 |
| credit_note_items | 3318 |
| debit_notes | 13 |
| debit_note_items | 19 |
| customer_receipts | 44 |
| supplier_payments | 785 |
| stock_batches | 7765 |
| ledger_transactions | 156716 |

## Additional supporting tables

| Table | Count |
| --- | ---: |
| account_groups | 13 |
| account_ledgers | 123 |
| app_users | 1 |
| auth_audit_log | 20 |
| categories | 0 |
| companies | 1218 |
| credit_note_items | 3318 |
| credit_notes | 1345 |
| customer_receipts | 44 |
| customers | 29 |
| debit_note_items | 19 |
| debit_notes | 13 |
| doctors | 7 |
| drugs | 147 |
| financial_years | 12 |
| hold_bill_items | 0 |
| hold_bills | 0 |
| item_ingredients | 402 |
| items | 938 |
| journal_entries | 0 |
| journal_entry_items | 0 |
| legacy_id_map | 82282 |
| legacy_migration_meta | 117 |
| purchase_invoice_items | 11829 |
| purchase_invoices | 5681 |
| sales_invoice_items | 232707 |
| sales_invoices | 71803 |
| stock_batches | 7765 |
| supplier_payments | 785 |
| suppliers | 85 |
| units | 16 |

## Verification result

- Historic imported data is present in the active database.
- The database was checked in read-only mode only.
- No legacy import script was re-run.
- No database reset or destructive migration step was executed.
- The current file passes `PRAGMA integrity_check`.
- Ordered row-content hashes for the major migrated tables match the verified
	recovery copy at `data/backups/pharmacy_backup_20260918_102219.db`.
- The SQLite file hash can change when SQLite rewrites/checkpoints pages, even
	when the migrated table contents remain identical.

Status: PASS — imported data verified as present and preserved.
