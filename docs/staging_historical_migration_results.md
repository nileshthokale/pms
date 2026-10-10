# Staging Historical Migration — Results (staging only, do not merge)

**Date:** 2026-10-10
**Source (read-only):** `PharmaWinner202610051955.sql` (35,462,774 bytes, 52 tables)
**Original dev DB (untouched):** `data/pharmacy.db` — SHA256 `6d3731590af7ae34921e7ea982e8fc39ffd0ed7f02ceef58694cc7c71080493d`, 372,736 bytes, `integrity_check ok`, 1 FY (`2026-2027` active), 0 transactions before and after.
**Staging copy only:** `staging/pharmacy_staging.db` (via `sqlite3.backup`), pre-migration `integrity_check ok`, post-migration backup `staging/backups/pharmacy_backup_20261010_102540.db` (validated by migrator).
**Code changed (no DBs touched by edits):** `database/legacy_migration.py` — BillNo-preserving sales vouchers + `--skip-stock` flag (see §2). Existing `test_legacy_migration` 215 pass.

**STOP. Do not merge staging into dev. Waiting for approval.**

---

## 1. Invoice-number handling decision (approved BillNo rule implemented)

Target constraints inspected (`database/connection.py`): `sales_invoices.bill_no UNIQUE NOT NULL`, `purchase_invoices.voucher_no UNIQUE NOT NULL`, same `UNIQUE NOT NULL` for credit/debit/receipt/payment/journal vouchers. No separate legacy-BillNo column; only `bill_no`/`voucher_no` + `remarks`.

Dry-run problem: `FY-VhType-VhNo` collides 67,762× for sales (`VhNo` 366 values) and discards customer-facing `BillNo`.

Staging rule implemented in `_import_sales`:
- `BillNo` present (not `""`/`"0"`/`"0.0"`): `bill_no = FY-BillNo` (e.g. `2017-2018-1`). Preserves original visibly; FY prefix resolves cross-year dups. Residual 123 collisions → deterministic `#legacy_id` suffix (idempotent, listed).
- `BillNo` missing (`0`/empty, 17,853 rows): `bill_no = FY-VhType-VhNo-S<legacy_id>` (e.g. `2015-2016-Cash-1-S13`). Never invents a BillNo; stable via source-table + legacy ID; `UNIQUE`/`NOT NULL` satisfied.
- Provenance in `remarks`: `Legacy salesvhheader ID <id>; Vh <type> <no>; BillNo <raw>` + original narration. Original numbers never overwritten or discarded.
- Idempotency: `CLEAR_ORDER` clear + deterministic base/suffix + `legacy_id_map(entity='sale', legacy_id→new_id, PK)`. Rerun proven identical (see §5).

Purchases/returns/receipts/payments: `FY-VhType-VhNo` already unique (0 collisions) so kept; supplier `InvoiceNo` preserved separately as `invoice_no`; same `#legacy_id` fallback on pathological collision.

---

## 2. Staging import summary (`skip_stock=True`, users skipped, no posting replay)

`imported_rows 489,025 / skipped_rows 11,212` (skipped = 7,793 stockbalance + 3,406 stockadjusted deferred + 3 company dupes + 1 doctor SELF + 3 item dupes + 6 system-consolidated ledgers). Warnings 114 (dupes + 50+50 sampled BillNo fallback/collision notes). `demo_rows_excluded 934`, `legacy_passwords_imported 0`.

| Source → target | Source rows | Imported | Skipped | Notes |
|---|---:|---:|---:|---|
| `acyear` → `financial_years` | 12 | 12 | 0 | 11 created, active `2026-2027` |
| `companymst` → `companies` | 1222 | 1219 | 3 | `ALKEM`, `JAGSAM PHARMA`×2 merged |
| `unitmst` → `units` | 16 | 16 | 0 | — |
| `drugmst` → `drugs` | 147 | 147 | 0 | — |
| `doctormst` → `doctors` | 8 | 7 | 1 | `SELF`×2 merged |
| `itemmst` → `items` | 942 | 939 | 3 | `POWERGESIC`, `VITOMIN-Z`, `CALTONVIT` merged, ids remapped |
| `itemdrugs` → `item_ingredients` | 402 | 402 | 0 | deduped |
| `ledger` → `account_ledgers` | 123 | 117 | 6 | 6 system roles consolidated; total ledgers 123 with preserved system rows |
| `sundaryinfo` → `customers`/`suppliers` | 113 | 114 | 0 | 29 customers + 85 suppliers (WALKIN included) |
| `stockbalance`/`stockadjusted` | 7793/3406 | 0/0 | 7793/3406 | **Deferred to separate phase** |
| `invoicevhheader`/`itemdetail`/`vhdetail` | 5713/11891/11426 | 5713/11891/11426 | 0 | purchase + lines + ledger |
| `salesvhheader`/`itemdetail`/`vhdetail` | 72045/233598/144108 | 72045/233598/144108 | 0 | BillNo rule §1; `preserved 54,192 / fallback 17,853 / collisions 123` |
| `creditnotevhheader`/`itemdetail`/`vhdetail` | 1349/3329/42 | same | 0 | — |
| `debitnotevhheader`/`itemdetail`/`vhdetail` | 14/20/2 | same | 0 | — |
| `receiptvhheader`/`vhdetail` | 44/88 | same | 0 | `CashBankID`→mode preserved |
| `paymentvhheader`/`vhdetail` | 785/1598 | same | 0 | `PaymentRefNo`→`reference_no` preserved |
| `journal*` | 0/0 | 0/0 | 0 | nothing to import |
| `ledger_transactions` (sum details) | 157,264 | 157,264 | 0 | as stored (`DR`→debit, `CR`→credit, `reference_type/id` linked); PostingEngine never called |
| History batches (`stock_batches`) | — | 7,616 | — | qty 0 FK linkage only; nonzero-qty count 0 (no stock modification) |

Original dates, voucher components, invoice nos/dates, qty/rate/MRP/discount/GST/amount, payment mode/refs, narration all stored as-is; `0001-01-01`→`""`.

---

## 3. Exclusions and separately-investigated records (listed, not silently discarded)

- **Headerless Counter Sale `countersaleitems` 2:** no header to attach (1 `OUTSIDE_ALL_YEARS`, 1 in 2015-2016). Unsupported, not imported. Purchase/sales displays read headers only, so no display loss.
- **Unmatched references:** none. Orphans 0 for all line tables; `*_unmapped_ledgers` 0; `AcYearID` vs `VhDate` mismatch 0. `sale_customer_fallback_walkin` only for truly unknown ledgers (none in full dump beyond WALKIN mapping; 71,922/72,045 already WALKIN).
- **Challans `challanvhheader` 80 + `challanitemdetail` 142:** no challan document type in new schema. Purchase (`purchase_invoices`) and sales (`sales_invoices`) reports do not read challans, so historical purchase/sales displays lose nothing. Listed for separate review if challan display ever needed.
- **Patient refs:** 54,193 nonempty `PatientName` preserved as `patient_name`; 17,852 empty (same rows as `BillNo=0` incomplete bills). `PatientAddress`/`Phone` have no target column (target only `patient_name`); sales report shows `patient_name` only, so no report loss. Listed as unsupported fields.
- **`ledgeropbal` 552 investigated separately:** columns `ID, AcYearID, LedID, oldOpBal, months 1..12` (e.g. `[1,1,8,-652,542,0,...]`). Per-FY/month grid incompatible with single `opening_balance`/`opening_balance_type` from `ledger.OpeningBal`. **Not imported, not excluded automatically — held for accounting reconciliation.** No action taken here.
- **Allocations:** `paymentinvoice` 2,671, `receiptinvoice` 114, `salescreditnote` 528, `invoicedebitnote` 11 — no allocation table in new schema, reported only.
- **`softmaster` 1, `billsetting` 1, `patientmaster` 0, `sundrybillbybillopbal` 0, `accompany` 0, `entryinvoice*` 0:** no target / no data, reported only.
- **Users:** `userinfo` 2 skipped by default; staging has only original admin `pratap` active. New user-management system used.
- **Stock:** deferred (see §2). `verify_migration` stock check fails as expected (see §4) — transaction checks all pass.

---

## 4. Accounting exceptions and integrity

`verify_migration` on staging: `integrity_check ok`, `foreign_key_violations 0`, orphans all 0 (`sales/purchase items`, `ledger_transactions`, `customers/suppliers`↔ledger). `ok=False` **solely** due to deferred stock: `stock_batches: expected 0, found 7616` (history qty-0 linkage) and `mismatches 1866 / missing 178` (quantities not imported by design). No transaction issues.

---

## 5. Tests

- `test_legacy_migration` 215 pass (5 skipped) after BillNo/`--skip-stock` change.
- Idempotency rerun on staging: before/after counts identical (`sales 72,045`, lines `233,598`, purchases `5,713`, ledger `157,264`, FYs 12, first/last `bill_no` identical), second run `imported 489,025 / skipped 11,212` — no duplicates.
- FY verification on staging (read-only, env restored after):
  - Active `2026-2027` before and after switching; original DB still 0 sales / 1 FY.
  - DAO: 2017-2018 sales 26,077 rows / 8,311 bills, purchases 657 bills; 2018-2019 sales 25,744 / 8,051, purchases 567 bills; ledger 18,010 / 17,262. Boundaries inclusive (`2017-04-01` 28, `2018-03-31` 28, `2018-04-01` 14, `2019-03-31` 12); `2018-03-31` only in 2017-2018, `2018-04-01` only in 2018-2019; `2017-03-31` 22 rows stay in prior FY.
  - All 9 pages switch: period reports `2017-04-01..2018-03-31` → `2018-04-01..2019-03-31`; position reports `2018-03-31` → `2019-03-31`.
  - BillNo uniqueness: distinct 72,045/72,045, dups 0; fallback `-S` 17,853; suffix `#` 123.

---

## 6. Artifacts (staging only)

- `staging/pharmacy_staging.db` (migrated copy) + `staging/backups/pharmacy_backup_*.db` (pre-migration snapshot) + `staging/staging_migration_report.json` + `staging/staging_verification.json`.
- Original `data/pharmacy.db` unchanged (SHA256 above). No merge performed.

**Next approval needed:** BillNo rule (§1), exclusion/stock-deferral list (§3), and promotion plan (staging→dev with fresh verified backup + verify). Stopped here.
