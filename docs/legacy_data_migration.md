# Legacy Data Migration — Pharma-WINNER → Pharmacy Management System

Phase 6F, one-time controlled migration of historical business data from
the legacy Pharma-WINNER MySQL 5.7 database dump into the new SQLite
application.

> **Safety summary:** the legacy `.sql` dump is read **offline**. No MySQL
> server is ever contacted, the dump is never executed against MySQL, the
> old installation is never modified, legacy password hashes are never
> imported, demo rows are never imported, and the production database is
> backed up and validated before any change.

---

## 1. Purpose

The pharmacy has years of trading history in the old Pharma-WINNER
system. This migration moves that history into the new application so
that masters, transactions, accounting, stock and reports continue
seamlessly, without re-entering data and without recomputing historical
accounting under today's rules.

Scope: data migration only. No new features, no schema redesign, no
changes to the new application's business logic.

## 2. Source dump

| Item | Value |
| --- | --- |
| File | `PharmaWinner202609142001.sql` |
| Format | MySQL 5.7 `mysqldump` text (InnoDB, utf8) |
| Size | ~35.3 MB |
| Source tables | 52 |
| Data rows (non-demo) | 502,541 |
| Demo rows | 934 (`demosales*`, excluded) |
| Data rows imported | 494,994 |

The dump contains `CREATE TABLE`, `INSERT` and `CREATE TRIGGER`
statements. Trigger bodies contain `INSERT ... NEW.column` fragments that
look like data; the parser detects and skips them (verified: exactly
503,468 data rows parsed with zero column-count mismatches).

## 3. Supported tables

Mapped (see `SOURCE_TARGETS` in `database/legacy_migration.py`):

- **Financial years:** `acyear`
- **Masters:** `companymst`, `unitmst`, `drugmst`, `doctormst`,
  `itemmst`, `itemdrugs`, `pathymst` (value lookup)
- **Accounting:** `gpmst` (classification), `ledger`, `sundaryinfo`,
  `statemst` (state lookup)
- **Purchases:** `invoicevhheader`, `invoiceitemdetail`,
  `invoicevhdetail`
- **Sales:** `salesvhheader`, `salesitemdetail`, `salesvhdetail`
- **Customer returns:** `creditnotevhheader`, `creditnoteitemdetail`,
  `creditnotevhdetail`
- **Supplier returns:** `debitnotevhheader`, `debitnoteitemdetail`,
  `debitnotevhdetail`
- **Receipts / payments:** `receiptvhheader`, `receiptvhdetail`,
  `paymentvhheader`, `paymentvhdetail`
- **Stock:** `stockbalance` (authoritative current stock)
- **Users:** `userinfo` (usernames only, opt-in, inactive)

Explicitly excluded as demo: `demosalesvhheader`, `demosalesvhdetail`,
`demosalesitemdetail`, `demosalescreditnote`.

Unsupported (no target in the new schema, recorded in the report):
`ledgeropbal`, `challanvhheader`, `challanitemdetail`,
`entryinvoicevhmst`, `entryinvoicevhitem`, `invoicedebitnote`,
`salescreditnote`, `receiptinvoice`, `paymentinvoice`,
`countersaleitems`, `softmaster`, `billsetting`, `patientmaster`,
`sundrybillbybillopbal`, `accompany`.

## 4. Source → target mapping

| Legacy | New | Notes |
| --- | --- | --- |
| `acyear` | `financial_years` | name, start, end; one active year |
| `companymst` | `companies` | `CompanyName`, `ShortName` |
| `unitmst` | `units` | `ItemUnit` |
| `drugmst` | `drugs` | `DrugName` |
| `doctormst` | `doctors` | name, `Specality`→specialty, city, phone |
| `pathymst` | `items.pathy` | Pathy **text** preserved |
| `itemmst` | `items` | see §8 |
| `itemdrugs` | `item_ingredients` | deduplicated on (item, drug) |
| `gpmst` | `account_groups` | classification only |
| `ledger` | `account_ledgers` | names/opening balances preserved |
| `sundaryinfo` | `customers` / `suppliers` | party detail fields |
| `invoicevhheader` | `purchase_invoices` | voucher/date/invoice/amounts |
| `invoiceitemdetail` | `purchase_invoice_items` | qty/rates/GST/discount |
| `salesvhheader` | `sales_invoices` | bill/date/customer/doctor |
| `salesitemdetail` | `sales_invoice_items` | qty/rate/MRP/amount |
| `creditnote*` | `credit_notes` / `credit_note_items` | customer returns |
| `debitnote*` | `debit_notes` / `debit_note_items` | supplier returns |
| `receiptvh*` | `customer_receipts` | customer receipts |
| `paymentvh*` | `supplier_payments` | supplier payments |
| `*vhdetail` | `ledger_transactions` | historical double entry, as stored |
| `stockbalance` | `stock_batches` | current stock, authoritative |

**Legacy numeric ids are never reused as foreign keys.** Every master
record is remapped through an in-memory dictionary and persisted to
`legacy_id_map` (`entity`, `legacy_id`, `new_id`) for verification.

### Voucher numbers

Legacy vouchers are unique per `(financial year, VhType, VhNo)`. The new
`voucher_no`/`bill_no` therefore composes all three
(`"2015-2016-Credit-1"`), guaranteeing global uniqueness while preserving
every source component. Any residual collision gets a `#<legacy id>`
suffix and is reported.

## 5. Demo exclusion

`demosalesvhheader`, `demosalesvhdetail`, `demosalesitemdetail` and
`demosalescreditnote` are never read for import. The dry-run and migration
reports state **"Demo rows excluded: 934"**. Demo ids never enter the id
maps, so no demo transaction can be referenced by imported accounting.

The current application's own demo/test **business** data is cleared
before import (§17); system configuration, authentication and the
database schema are preserved.

## 6. Authentication treatment

- `userinfo.UserPassword` is **never** imported, copied, cracked or
  migrated. The legacy `*XXXX` hashes are ignored entirely.
- The existing new-application accounts (including the ADMIN) are
  preserved; login continues to work before and after migration.
- Legacy usernames can optionally be imported as **inactive** accounts
  with an unusable random hash (`--import-legacy-users`); an ADMIN must
  explicitly reset the password before they can be used. Roles are
  restricted to the two existing roles: `ADMIN` and `PHARMACIST/STAFF`.
- Verification fails if any `legacy-migration-disabled*` account is
  active.

## 7. Financial years

All 12 legacy years (2015-2016 … 2026-2027) are imported with their exact
`FromDate`/`ToDate` and name. Overlapping/invalid years would be reported
as findings. The year containing today's date (2026-2027) is marked
active, matching the new application's rule; the partial unique index
`idx_financial_year_active` guarantees a single active year.

## 8. Masters

- **Items:** `ItemName`, `UnitID`→unit map, `CompanyID`→company map,
  `PackSize`, `DiscountPer`→discount, `ReorderStockLevel`, `Rate`, `MRP`,
  `TaxID`→`tax_structure` (raw legacy tax code preserved; no tax master
  exists in the dump), `Location`, `SheduledID`→`scheduled`, `DPCO`,
  `PathyID`→pathy text. `category_id` stays **NULL** — the legacy dump has
  no category master, so categories are never invented.
- Duplicate legacy item names (the new `items.item_name` is UNIQUE) are
  merged into the first imported item and recorded in the report; the
  duplicate legacy id maps to the merged item so transaction FKs resolve.
  Real dataset: 3 duplicates (POWERGESIC, VITOMIN-Z, CALTONVIT).
- `SellLoose` and `BillCompulsory` have no target column and are listed as
  unsupported fields.
- **Ingredients:** `itemdrugs` → `item_ingredients` with resolved ids and
  deduplication.
- **Doctors:** duplicate names (e.g. `SELF` twice) merge and are reported.

## 9. Parties

Parties are derived from `ledger` + `gpmst` + `sundaryinfo`:

- `SUNDRY DEBTORS` → `customers` (including the legacy `WALKIN` ledger as
  a single WALKIN customer).
- `SUNDRY CREDITORS` → `suppliers`.
- Each party's account ledger is created first (legacy name preserved)
  and linked via `customers.ledger_id` / `suppliers.ledger_id`; no
  duplicate `"Customer - X"` ledgers are created.
- Preserved: name, address, city, state (`StateID`→`statemst`), contact
  person, contact number, sales tax no, VAT/TIN, discount, credit limit,
  credit period, opening balance (sign → Debit/Credit).
- Parties with no `sundaryinfo` row are still created from the ledger.
- Real dataset: 29 debtor ledgers → 29 customers (27 named + WALKIN),
  85 creditor ledgers → 85 suppliers. No fake walk-in customers.

## 10. Account groups and ledgers

- Legacy groups are mapped to the new canonical group text: `CASH-IN-HAND`
  → Cash-in-Hand, `BANK ACCOUNTS`/`HDFC` → Bank Accounts,
  `SUNDRY DEBTORS` → Sundry Debtors, `SUNDRY CREDITORS` → Sundry
  Creditors, `SALES ACCOUNT` → Sales Accounts, `PURCHASE ACCOUNT` →
  Purchase Accounts. Unknown groups keep their legacy text and remain
  unclassified (`account_group_id = NULL`) — the migration never guesses.
- Ledgers whose legacy role is a system role are consolidated into the new
  system ledgers so reports stay coherent: `CASH` → **Cash** (role CASH);
  `CASH SALE`/`CREDIT SALE` → **Sales** (SALES); `CASH PURCHASE`/`CREDIT
  PURCHASE` → **Purchase** (PURCHASE); the busiest legacy bank account →
  **Bank** (BANK, keeps its legacy name). Other bank accounts remain
  separate ledgers in Bank Accounts.
- `ledger.OpeningBal` becomes the single opening balance
  (`opening_balance` + `opening_balance_type`); per-FY/month grids in
  `ledgeropbal` have no target and are reported as unsupported.
- Real dataset: 123 legacy ledgers → 123 `account_ledgers` rows
  (6 system + 117 imported/merged).

## 11. Purchases

`invoicevhheader` → `purchase_invoices` (voucher/date/time, type, supplier
via ledger map, invoice no/date, due date, gross, bill discount, round
off, debit-note amount, CN amount, tax amount, paid, narration);
`invoiceitemdetail` → `purchase_invoice_items` (pay/free qty, batch,
expiry, rate, MRP, discount amount, GST %, GST amount, amount, purchase
rate, net rate). `DiscPer` has no column and is reported as an unsupported
field. Historical values are stored as-is; totals are never recomputed.
`invoicevhdetail` lines become `ledger_transactions` (§14).

Real dataset: 5,681 headers, 11,829 lines.

## 12. Sales

`salesvhheader` → `sales_invoices` (bill no, date/time, type, customer,
patient name, doctor, discount, paid, gross, round off, net);
`salesitemdetail` → `sales_invoice_items` (item, batch link, pack,
expiry, MRP, qty, discount amount, amount). Legacy `SalesRate` /
`NetSalesRate` are not separate columns in the new schema; the stored
`Amount`/`DiscountAmt` values are preserved and the rate columns are
listed as unsupported fields.

Walk-in: legacy sales referencing the `WALKIN` ledger map to the single
imported WALKIN customer; unknown party ids fall back to WALKIN and are
warned (real dataset: none).

Real dataset: 71,803 invoices, 232,707 lines.

## 13. Returns, receipts, payments

- **Customer returns:** `creditnotevhheader`/`creditnoteitemdetail` →
  `credit_notes`/`credit_note_items` (voucher, dates, type, customer,
  price factor preserved in `return_reason`, qty, rate, MRP, discount,
  amount). `ReasonID` has no target and is reported. 1,345 headers /
  3,318 lines.
- **Supplier returns:** `debitnote*` → `debit_notes`/`debit_note_items`
  with the same field treatment. 13 headers / 19 lines.
- **Customer receipts:** `receiptvhheader` → `customer_receipts`
  (voucher, date/time, customer, amount, Cash/Bank from the legacy
  cash/bank ledger). 44 receipts.
- **Supplier payments:** `paymentvhheader` → `supplier_payments`
  (voucher, date/time, supplier, amount, mode, `PaymentRefNo` →
  `reference_no`). 785 payments.
- Allocation tables (`receiptinvoice`, `paymentinvoice`,
  `salescreditnote`, `invoicedebitnote`) have no target and are reported
  as unsupported (2,671 + 114 + 527 + 10 rows).

## 14. Accounting history

Historical double entry is imported from the six `*vhdetail` tables into
`ledger_transactions` exactly as stored:

- `TrnType` `DR` → debit, `CR` → credit (amounts are positive in the
  source).
- date, narration, voucher number and ledger come from the source; the
  new record is linked to the imported document via
  `reference_type`/`reference_id` using the application's existing posting
  source constants (`COUNTER_SALE`, `PURCHASE_INVOICE`, `CREDIT_NOTE`,
  `DEBIT_NOTE`, `CUSTOMER_RECEIPT`, `SUPPLIER_PAYMENT`).
- **The PostingEngine is never replayed.** No `post_*` call and no
  `SalesDAO`/`PurchaseDAO.insert_invoice` is used for history (asserted by
  tests). Nothing is recomputed from today's business rules.

Real dataset: 156,716 ledger transaction rows, all mapped.

## 15. Stock

- The **authoritative** current stock is `stockbalance`. For every
  `(ItemID, BatchNo)` the new `stock_batches.stock_qty` is
  `TotalPurchaseQty − TotalSalesQty`, with MRP, purchase rate
  (`Rate`), net rate (`NetPurRate`), expiry and pack size preserved.
- Historical purchase/sales lines are imported as history only; stock is
  **not** replayed through those transactions, so nothing is
  double-counted.
- `stockadjusted` is **already reflected** in `stockbalance` totals —
  evidence: batches exist whose `TotalPurchaseQty` exactly equals their
  total adjustment with no purchase rows. It is therefore not summed again
  (documented as such in the reports).
- Batches referenced only by historical transactions (e.g. sold-out
  batches absent from `stockbalance`) are created with `stock_qty = 0` so
  `sales_invoice_items.stock_batch_id` can link them; the count is
  recorded in the migration metadata.
- Real dataset: 7,763 distinct legacy batches (7,764 rows, one duplicate
  summed) + 2 history-only batches → 7,765 new batches.

## 16. Stock reconciliation

`verify_migration()` compares every legacy `(item, batch)` balance with
the imported batch and reports legacy qty, new qty and difference:

```
legacy_batches: 7763   duplicate_legacy_rows: 1
imported_batches: 7765
mismatches: 0          missing: 0
```

14 legacy batches have a negative computed balance (sales exceed
purchases in the source data, typically unit/pack-size data entry in the
old system). They are preserved exactly as stored and listed in the
dry-run report — differences are never hidden.

## 17. Demo data removal

Before import (and only after the backup has been created and validated):

1. Business tables are cleared in dependency order
   (`CLEAR_ORDER`): sales/credit/debit/purchase items and headers,
   receipts, payments, journals, `ledger_transactions`, hold bills,
   `stock_batches`, items/ingredients, parties, masters, categories,
   import history, financial years.
2. Non-system `account_ledgers` and non-system `account_groups` are
   removed; ledgers carrying a system role and the structured system
   groups are **preserved**.
3. `app_users`, `auth_audit_log`, the schema and the migration tables are
   never touched.

Every cleared table and the number of removed rows is recorded in the
migration report. Real production pre-state: 1 company, 1 unit, 1 drug,
1 doctor, 1 item, 1 customer (TestCustomer), 1 supplier (TestSupplier),
8 ledgers (2 legacy demo + 6 system), 1 demo financial year; 0
transactions.

## 18. Rollback

The migration is reversible with the pre-migration backup:

1. `database/backup_restore.py` copies the database (`sqlite3.backup`,
   consistent snapshot) to `backups/pharmacy_backup_YYYYMMDD_HHMMSS.db`.
2. The backup is validated immediately (integrity check, table presence)
   and its SHA-256 is recorded in the report and in
   `legacy_migration_meta`.
3. To roll back: restore that backup with the application's
   Backup & Restore screen or `backup_restore.restore_backup(path)`.

The migration also refuses to run if the backup cannot be created or
validated (unless `--no-backup` is used for a throwaway staging copy).

## 19. Backup

- Created with `create_backup()` (never modifies the source database).
- Validated with `validate_backup()` (`integrity_check = ok`); SHA-256 and
  size recorded before and after the import (§21).
- The backup is never deleted by the migration.
- `--backup-dir` chooses the destination; the default is
  `<database directory>/backups`.

## 20. Dry run

```bash
python -m database.legacy_migration --dry-run PharmaWinner202609142001.sql
```

- Parses the dump, resolves relationships, computes counts, and reports
  unmapped records, missing references, duplicate conflicts, unsupported
  fields/tables and demo rows.
- Performs **zero** database writes: it does not open, create or modify any
  SQLite database (asserted by tests).
- Writes `docs/legacy_migration_dry_run.md` (and `.json`).

## 21. Verification

```bash
python -m database.legacy_migration --verify PharmaWinner202609142001.sql
```

Checks (all read-only):

- `PRAGMA integrity_check` = `ok`
- `PRAGMA foreign_key_check` = no rows
- no orphan rows (sales/purchase items, batches, ledger transactions,
  party↔ledger links)
- target row counts reconcile with the import metadata
  (`source_rows − skipped = imported`, per table)
- every legacy item/company/unit/drug/doctor/ledger id has a mapping entry
- stock reconciliation with zero differences
- no active legacy (disabled) accounts

Pre/post production state is recorded as SHA-256, size, table count and
important row counts. The hash **changes** because new data is imported;
data preservation is proven by counts, mappings and reconciliation, not by
the hash.

## 22. Running the import

```bash
# 1. Dry run (no writes)
python -m database.legacy_migration --dry-run PharmaWinner202609142001.sql

# 2. Staging import into a copy (no production DB touched)
python -m database.legacy_migration --import --db staging/pharmacy_staging.db PharmaWinner202609142001.sql

# 3. Verify the staging copy
python -m database.legacy_migration --verify --db staging/pharmacy_staging.db PharmaWinner202609142001.sql

# 4. Production import (backup + validation are automatic)
python -m database.legacy_migration --import --confirm-production PharmaWinner202609142001.sql
```

Notes:

- `--import` refuses to run against `data/pharmacy.db` without
  `--confirm-production`.
- `--limit N` limits rows per source table (staging/debug only).
- `--import-legacy-users` imports legacy usernames as inactive accounts.
- `--no-backup` skips the backup (throwaway staging only).
- The CLI is developer/ADMIN-facing; the UI does not expose it.

## 23. Limitations

- **Structural differences** are preserved honestly rather than forced:
  per-FY opening balances, challans, allocation tables, bill print
  settings, the firm profile, patient master and counter-sale leftovers
  have no target and are reported as unsupported.
- Legacy `DiscPer`, `SalesRate`/`NetSalesRate` on sales lines, `ReasonID`
  and `TaxID` masters have no dedicated columns; stored amounts/totals are
  preserved and the raw codes are kept where a safe column exists.
- One bank ledger receives the BANK role (the busiest legacy bank
  account); other bank accounts remain separate ledgers.
- Negative legacy stock balances are preserved as-is.
- The legacy item duplicate names are merged (3 in the real data).
- Night mode and UI behaviour are unaffected by the migration.

## 24. Future migration procedure

For a future legacy dump (another shop, another year, or a re-run):

1. Back up the current database (Backup & Restore screen).
2. Run `--dry-run` and review `docs/legacy_migration_dry_run.md`; resolve
   unexpected findings (new tables, changed columns, new duplicates).
3. Run the import into a staging database and `--verify` it; spot-check
   Item/Supplier/Customer/Purchase/Sales/Stock/Cash Book/Bank Book and the
   reports in the UI.
4. Run the full automated test suite (`python run_tests.py`).
5. Import into production with `--confirm-production`, then run
   `--verify` again and review `docs/legacy_migration_report.md`.

The migration is idempotent: a re-run clears business data first, so
repeating it produces the same result rather than duplicating rows.
