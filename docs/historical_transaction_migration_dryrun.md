# Historical Transaction Migration — Dry Run (read-only)

**Date:** 2026-10-10
**Source dump (read-only):** `PharmaWinner202610051955.sql` — 35,462,774 bytes, MySQL 5.7 `mysqldump` text, 52 source tables
**Target (not modified):** `data/pharmacy.db` (development database, read with `SELECT` only)
**Mode:** Phase 1 dry run only. No imports, no writes, no stock changes, no posting-engine replay.

**Safety applied in this step:**
- Source dump opened read-only via streaming parser (`LegacyDump`); never executed, never modified.
- Target inspected with `SELECT` only; `init_database()` was never run against `data/pharmacy.db` in this task.
- Production database, EXE, and `dist/` were not touched (no paths referenced, no files written there).
- Phase 3 stock reconciliation was not applied; `stock_batches` were not created, updated, or overwritten.
- Historical accounting is proposed from `*vhdetail` exactly as stored; PostingEngine replay is explicitly forbidden.
- No missing values were invented; unmatched records are listed as excluded with reasons, never silently discarded.
- Future import is designed idempotent: `CLEAR_ORDER` clear + `legacy_id_map` remap + `_unique_voucher(...#legacy_id)` suffix (see §8).

**STOP after this report. Wait for approval before any `--import`.**

---

## 1. Real source tables identified (from dump `CREATE TABLE`, not guessed)

All header tables carry `AcYearID` + `VhDate` (+ `VhType`, `VhNo`). Detail tables carry own `VhDate`. Line tables join via `VhID`.

| Purpose | Legacy header | Date col | Legacy lines | Line join | Legacy accounting | Target |
|---|---|---|---|---|---|---|
| Financial years | `acyear` | `FromDate`/`ToDate` | — | — | — | `financial_years` |
| Companies | `companymst` (`ID, CompanyName, ShortName`) | — | — | — | — | `companies` |
| Units | `unitmst` (`ID, ItemUnit`) | — | — | — | — | `units` |
| Drugs | `drugmst` (`ID, DrugName`) | — | — | — | — | `drugs` |
| Doctors | `doctormst` (`ID, DoctorName, Specality, City, PhoneNo`) | — | — | — | — | `doctors` |
| Items | `itemmst` (16 cols: `ID, ItemName, UnitID, PathyID, CompanyID, PackSize, DiscountPer, ReorderStockLevel, Rate, MRP, TaxID, Location, SheduledID, SellLoose, BillCompulsory, DPCO`) | — | `itemdrugs` (`ID, ItemID, DrugID, Power`) | `ItemID` | — | `items` + `item_ingredients` (`pathy` text from `pathymst`) |
| Ledgers/groups/parties | `ledger` (`ID, LedHead, SGpID, AdminCreated, OpeningBal`), `gpmst` (`ID, SGpHead, ...`), `sundaryinfo` (12 cols incl. `LedID, StateID`), `statemst` | — | — | — | — | `account_ledgers` + `account_groups` + `customers`/`suppliers` |
| Purchases | `invoicevhheader` (21 cols, `VhDate` idx 4) | `VhDate` | `invoiceitemdetail` (22 cols) | `VhID` | `invoicevhdetail` (`AcYearID, VhDate, VhID, TrnType, LedID, LedAmount, LedNarration`) | `purchase_invoices` + `purchase_invoice_items` + `ledger_transactions` |
| Sales | `salesvhheader` (22 cols, `VhDate` idx 4, plus `BillNo` idx 8, `CustID` idx 9, `DoctID` idx 13) | `VhDate` | `salesitemdetail` (14 cols) | `VhID` | `salesvhdetail` (same 8-col shape) | `sales_invoices` + `sales_invoice_items` + `ledger_transactions` |
| Customer returns | `creditnotevhheader` (15 cols) | `VhDate` | `creditnoteitemdetail` (19 cols) | `VhID` | `creditnotevhdetail` | `credit_notes` + `credit_note_items` + `ledger_transactions` |
| Supplier returns | `debitnotevhheader` (15 cols) | `VhDate` | `debitnoteitemdetail` (19 cols) | `VhID` | `debitnotevhdetail` | `debit_notes` + `debit_note_items` + `ledger_transactions` |
| Receipts | `receiptvhheader` (10 cols incl. `CashBankID`) | `VhDate` | — | — | `receiptvhdetail` | `customer_receipts` + `ledger_transactions` |
| Payments | `paymentvhheader` (11 cols incl. `CashBankID, PaymentRefNo`) | `VhDate` | — | — | `paymentvhdetail` | `supplier_payments` + `ledger_transactions` |
| Journals | `journalvhheader` / `journalvhdetail` (8 cols each) | `VhDate` | — | — | — | `journal_entries` / `journal_entry_items` (0 rows in source) |
| Stock (out of scope here) | `stockbalance` (10 cols, no date), `stockadjusted` (`AdjustedDate`) | — | — | — | — | `stock_batches` (NOT imported in this transaction task) |

Target date columns (from `database/connection.init_database`, read-only reference): `sales_invoices.sale_date`, `purchase_invoices.voucher_date`, `credit_notes.voucher_date`, `debit_notes.voucher_date`, `customer_receipts.receipt_date`, `supplier_payments.payment_date`, `journal_entries.entry_date`, `ledger_transactions.transaction_date`. All filters are inclusive string `>=`/`<=` on ISO `YYYY-MM-DD`; original values are preserved verbatim.

Demo (never imported): `demosalesvhheader` 157, `demosalesvhdetail` 314, `demosalesitemdetail` 463, `demosalescreditnote` 0 → **934 demo rows excluded**.

---

## 2. Source row counts (actual dump, `count_rows()`)

`source_tables 52, source_rows 504,369, demo 934`.

| Legacy table | Rows |
|---|---:|
| `acyear` | 12 |
| `companymst` | 1222 |
| `unitmst` | 16 |
| `drugmst` | 147 |
| `doctormst` | 8 |
| `itemmst` | 942 |
| `itemdrugs` | 402 |
| `pathymst` | 6 |
| `ledger` | 123 (29 SUNDRY DEBTORS, 85 SUNDRY CREDITORS, rest system/income/expense/bank/cash) |
| `gpmst` | 22 |
| `sundaryinfo` | 113 |
| `statemst` | 1 |
| `salesvhheader` / `salesitemdetail` / `salesvhdetail` | 72,045 / 233,598 / 144,108 |
| `invoicevhheader` / `invoiceitemdetail` / `invoicevhdetail` | 5,713 / 11,891 / 11,426 |
| `creditnotevhheader` / `creditnoteitemdetail` / `creditnotevhdetail` | 1,349 / 3,329 / 42 |
| `debitnotevhheader` / `debitnoteitemdetail` / `debitnotevhdetail` | 14 / 20 / 2 |
| `receiptvhheader` / `receiptvhdetail` | 44 / 88 |
| `paymentvhheader` / `paymentvhdetail` | 785 / 1,598 |
| `journalvhheader` / `journalvhdetail` | 0 / 0 |
| `stockbalance` / `stockadjusted` | 7,793 / 3,406 |
| `countersaleitems` (headerless, unsupported) | 2 |
| `challanvhheader` / `challanitemdetail` | 80 / 142 |
| `paymentinvoice` / `receiptinvoice` / `salescreditnote` / `invoicedebitnote` | 2,671 / 114 / 528 / 11 |
| `ledgeropbal` | 552 |
| `userinfo` | 2 |
| rest (`accompany` 0, `billsetting` 1, `softmaster` 1, `patientmaster` 0, `sundrybillbybillopbal` 0, `entryinvoice*` 0) | see table |

---

## 3. Counts grouped by financial year (by `VhDate`; lines via header `VhID` join)

`acyear` ranges verified: `2015-2016` 2015-04-01..2016-03-31, `2016-2017` 2016-04-01..2017-03-31, **`2017-2018` 2017-04-01..2018-03-31**, **`2018-2019` 2018-04-01..2019-03-31**, `2019-2020` … `2026-2027` 2026-04-01..2027-03-31. Zero header/detail rows with `INVALID_OR_EMPTY` or `OUTSIDE_ALL_YEARS`; `AcYearID` vs `VhDate` mismatch 0/72,045 sales and 0/5,713 purchases.

### 3a. Headers by FY

| FY | Sales | Purchases | Credit notes | Debit notes | Receipts | Payments | Journals |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2015-2016 | 9,507 | 668 | 196 | 2 | 12 | 390 | 0 |
| 2016-2017 | 8,778 | 605 | 179 | 1 | 19 | 102 | 0 |
| **2017-2018** | **8,311** | **657** | **154** | **0** | **3** | **32** | **0** |
| **2018-2019** | **8,051** | **567** | **162** | **0** | **3** | **9** | **0** |
| 2019-2020 | 7,170 | 507 | 121 | 2 | 3 | 2 | 0 |
| 2020-2021 | 5,119 | 351 | 108 | 0 | 1 | 1 | 0 |
| 2021-2022 | 4,595 | 352 | 80 | 2 | 0 | 0 | 0 |
| 2022-2023 | 4,450 | 419 | 64 | 2 | 0 | 5 | 0 |
| 2023-2024 | 4,566 | 439 | 83 | 1 | 0 | 22 | 0 |
| 2024-2025 | 4,724 | 459 | 78 | 3 | 1 | 222 | 0 |
| 2025-2026 | 4,462 | 439 | 82 | 0 | 2 | 0 | 0 |
| 2026-2027 | 2,312 | 250 | 42 | 1 | 0 | 0 | 0 |
| **Total** | **72,045** | **5,713** | **1,349** | **14** | **44** | **785** | **0** |

### 3b. Lines by FY (via header join; orphans 0 for all four)

| FY | Sales lines | Purchase lines | Credit lines | Debit lines |
|---|---:|---:|---:|---:|
| 2015-2016 | 28,218 | 1,551 | 426 | 3 |
| 2016-2017 | 26,027 | 1,223 | 440 | 2 |
| **2017-2018** | **26,077** | **1,303** | **400** | **0** |
| **2018-2019** | **25,744** | **1,075** | **394** | **0** |
| 2019-2020 | 23,419 | 1,024 | 320 | 4 |
| 2020-2021 | 16,754 | 682 | 266 | 0 |
| 2021-2022 | 15,593 | 717 | 199 | 2 |
| 2022-2023 | 15,451 | 926 | 166 | 4 |
| 2023-2024 | 15,793 | 975 | 203 | 1 |
| 2024-2025 | 16,746 | 1,003 | 203 | 3 |
| 2025-2026 | 15,579 | 886 | 209 | 0 |
| 2026-2027 | 8,197 | 526 | 103 | 1 |
| **Total (orphans 0)** | **233,598** | **11,891** | **3,329** | **20** |

### 3c. Accounting details by FY (own `VhDate`; proposed `ledger_transactions`)

| FY | `salesvhdetail` | `invoicevhdetail` | `creditnotevhdetail` | `debitnotevhdetail` | `receiptvhdetail` | `paymentvhdetail` | **Proposed ledger rows** |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2015-2016 | 19,014 | 1,336 | 30 | 0 | 24 | 798 | 21,202 |
| 2016-2017 | 17,558 | 1,210 | 8 | 0 | 38 | 214 | 19,028 |
| **2017-2018** | **16,622** | **1,314** | **4** | **0** | **6** | **64** | **18,010** |
| **2018-2019** | **16,104** | **1,134** | **0** | **0** | **6** | **18** | **17,262** |
| 2019-2020 | 14,340 | 1,014 | 0 | 2 | 6 | 4 | 15,366 |
| 2020-2021 | 10,240 | 702 | 0 | 0 | 2 | 2 | 10,946 |
| 2021-2022 | 9,190 | 704 | 0 | 0 | 0 | 0 | 9,894 |
| 2022-2023 | 8,902 | 838 | 0 | 0 | 0 | 10 | 9,750 |
| 2023-2024 | 9,132 | 878 | 0 | 0 | 0 | 44 | 10,054 |
| 2024-2025 | 9,452 | 918 | 0 | 0 | 2 | 444 | 10,816 |
| 2025-2026 | 8,926 | 878 | 0 | 0 | 4 | 0 | 9,808 |
| 2026-2027 | 4,628 | 500 | 0 | 0 | 0 | 0 | 5,128 |
| **Total** | **144,108** | **11,426** | **42** | **2** | **88** | **1,598** | **157,264** |

Preservation: dates (`VhDate`→`sale_date`/`voucher_date`/`receipt_date`/`payment_date`/`transaction_date`), voucher components (`AcYearID→FY name`, `VhType`, `VhNo`), supplier/customer via ledger maps, invoice nos (`InvoiceNo`/`InvoiceDate`/`DueDate`), line qty/rate/MRP/discount/GST/amount, payment `CashBankID`→mode and `PaymentRefNo`→`reference_no`, narration→remarks. `0000-00-00`/`0001-01-01` normalize to `""` (seen in purchase `DueDate`); no `VhDate` needed normalization.

---

## 4. Master mapping to already-imported dev data

Dev (`SELECT` only): `financial_years 1`, `companies 219`, `units 14`, `drugs 137`, `doctors 7 rows (8 legacy with duplicate SELF)`, `items 942`, `item_ingredients 402`, `customers 29`, `suppliers 85`, `account_ledgers 0`, `account_groups 0`, all transaction tables 0, `stock_batches 0`.

| Legacy master | Source rows | Dev rows | Overlap (read-only check) | Implication |
|---|---:|---:|---|---|
| `companymst` 1222 (1219 normalized) | 1222 | 219 | 219/219 dev names ⊆ legacy; 1000 legacy-only | Partial. Transactions join via items, so import must bring all 1222 (merge 3 dupes) then remap. |
| `unitmst` 16 | 16 | 14 | 14 overlap; missing `drop`, `scrub` | Partial. No current item uses missing units (items 942/942 match by name+unit), but full import needed for safety. |
| `drugmst` 147 | 147 | 137 | 137 overlap; 10 legacy-only | Partial. `itemdrugs` 402 currently match, but full import needed. |
| `doctormst` 8 | 8 | 7 normalized | 7 overlap (`SELF`×2 merges to 1) | Matches expected merge; full import merges duplicate. |
| `itemmst` 942 | 942 | 942 | 942/942 by `(item_name, unit_name)` | Full. Legacy numeric IDs will still be remapped (never reused). |
| `itemdrugs` 402 | 402 | 402 | counts match | Full, but re-import deduplicates on `(item, drug)`. |
| `ledger` 123 / `gpmst` 22 / `sundaryinfo` 113 | 123/22/113 | customers 29, suppliers 85, ledgers 0, groups 0 | Counts match expected 29 debtors→customers, 85 creditors→suppliers; dev `ledger_id` all NULL | Parties present by name but ledgers/groups not imported. Full ledger+party import required with `customers.ledger_id`/`suppliers.ledger_id` links. |
| `pathymst` 6 / `statemst` 1 | 6/1 | — (values, not tables) | — | Lookups only; `pathy` text and `state` text preserved. |

`build_plan` findings on this dump: **zero** `missing_item_unit`, `missing_item_company`, `missing_item_pathy`, `ingredient_missing_*`, `party_info_orphan`, `ledger_unknown_group`, `sale_missing_*`, `purchase_missing_*`, `*_orphans`, `*_unmapped_ledgers`. All FKs resolve. Only findings: `duplicate_item_names` 3, `no_journal_records`, `stock_negative_batches` 14, plus stock/batch notes below.

---

## 5. Issues, excluded records, unsupported fields (nothing silently discarded)

1. **Sales voucher collisions (needs decision).** `(AcYearID,VhType,VhNo)` unique 4,283 of 72,045 → 67,762 collisions. `VhNo` has 366 distinct values (top ~250 each); `VhType` 71,922 `Cash` + 123 `Credit`. Current migrator composes `bill_no = FY-VhType-VhNo` + `#legacy_id` suffix on collision (idempotent). Works but loses customer-facing `BillNo`.
2. **Sales `BillNo` handling (needs decision).** `BillNo` unique 6,325 of 72,045 → 65,720 dups; 17,853 rows `BillNo=0`; `(AcYearID,BillNo)` unique 54,081 → 17,964 dups. Migrator currently ignores `BillNo` (stores `VhNarration` as remarks, not `BillNo`). Preserving `BillNo` where supported requires a rule: e.g. keep `fy-VhType-VhNo#id` as `bill_no` for uniqueness and stash legacy `BillNo` in remarks, or switch to `fy-BillNo` with suffix. **Do not decide here — needs approval.**
3. **Purchases/returns/receipts/payments vouchers (ready).** `(AcYearID,VhType,VhNo)` unique 5,713/5,713 purchases, 1,349/1,349 credit, 14/14 debit, 44/44 receipts, 785/785 payments → no suffix needed except pathological collision.
4. **Headerless lines (ready, none).** `salesitemdetail`, `invoiceitemdetail`, `creditnoteitemdetail`, `debitnoteitemdetail` orphans all 0.
5. **`countersaleitems` 2 (excluded, needs decision noted).** Headerless counter-sale lines, no header to attach; 1 row `OUTSIDE_ALL_YEARS`, 1 in 2015-2016. Status: unsupported, will not import.
6. **Allocation tables (excluded).** `paymentinvoice` 2,671, `receiptinvoice` 114, `salescreditnote` 528, `invoicedebitnote` 11 → no target table, reported only.
7. **`ledgeropbal` 552 (excluded).** Per-FY/month opening grid; new `account_ledgers` holds single opening from `ledger.OpeningBal`. Reported only.
8. **`challan*` 80+142, `entryinvoice*` 0, `softmaster` 1, `billsetting` 1, `patientmaster` 0, `sundrybillbybillopbal` 0, `accompany` 0 (excluded).** No target document type/table.
9. **Journals 0 (nothing to do).** `journalvhheader/detail` both 0 → no rows to import; flagged `no_journal_records`.
10. **`userinfo` 2 (opt-in only).** Usernames only, inactive, random hash; `UserPassword` (`*XXXX` hashes) never imported. Default: skip unless `--import-legacy-users` approved.
11. **Duplicate masters (ready, merged with report).** Item names 3 (`POWERGESIC` [51,920], `VITOMIN-Z` [290,303], `CALTONVIT` [681,869]) → merged, duplicate id mapped to surviving item. Doctor `SELF`×2 → merged.
12. **Unsupported columns (reported, values preserved where a column exists).** `itemmst.SellLoose`/`BillCompulsory` (no column), purchase `DiscPer` (stored `DiscAmt` kept), sales `SalesRate`/`NetSalesRate` (stored `Amount`/`DiscAmt` kept), `credit/debitnoteitemdetail.ReasonID` (no column; `PriceFactor` kept), `TaxID` raw code kept as `tax_structure` text (no tax master in dump), `category_id` stays NULL (no legacy category — never invented).
13. **Dates (ready).** No invalid `VhDate`; purchase `DueDate 0001-01-01` → `""` via `_date()`; `InvoiceDate` preserved as stored.
14. **Stock notes (out of scope, no action here).** `stockbalance` 7,793 rows → 7,793 distinct `(ItemID,BatchNo)`; `sales_batches` 7,479 with 2 missing from balance (history-only batches would be created qty 0 on import); 14 negative balances preserved as-is; `stockadjusted` 3,406 already reflected in balance (10 keys not in balance, not summed again). **Phase 3 reconciliation not applied in this task.**

---

## 6. Financial-year records to create

Dev has only `2026-2027` (2026-04-01..2027-03-31, active). Proposed: import all 12 legacy `acyear` rows with exact `FinancialYear`/`FromDate`/`ToDate`; mark active the year containing today (`2026-2027`), matching existing active. Net: **create 11 missing years**, keep active unchanged.

Required (exact):
- `2017-2018`: 2017-04-01 through 2018-03-31
- `2018-2019`: 2018-04-01 through 2019-03-31
- plus `2015-2016`, `2016-2017`, `2019-2020`, `2020-2021`, `2021-2022`, `2022-2023`, `2023-2024`, `2024-2025`, `2025-2026` with dump dates above.

Validation: non-overlapping, single active via `idx_financial_year_active`; invalid/duplicate years would abort with finding (none in this dump: `_financial_years_valid 12`).

---

## 7. Proposed import sequence (for future approval only — not run)

From `LegacyMigrator._import_all` + `CLEAR_ORDER` (business tables cleared only after verified backup; `app_users`, `auth_audit_log`, schema, migration tables preserved; system ledgers/groups preserved, non-system removed):

1. Verified backup of dev DB (`backup_restore.create_backup` + `validate_backup`, SHA-256 recorded) — refuse without it (unless throwaway staging with `--no-backup`).
2. `financial_years` (12 rows, 11 new).
3. `companies` (1222, merge 3 dupes) → `units` (16) → `drugs` (147) → `doctors` (8→7 merged) → `items` (942) → `item_ingredients` (402, dedup).
4. Ledgers+parties: `account_groups` (22 classified), `account_ledgers` (123: 6 system consolidated + 117), `customers` (29) + `suppliers` (85) with `ledger_id` links.
5. Purchases (5,713 headers + 11,891 lines) → sales (72,045 + 233,598) → credit (1,349 + 3,329) → debit (14 + 20) → receipts (44) → payments (785). Each header stores original `VhDate`/`VhTime`/voucher components/invoice nos/amounts as-is; each line stores qty/batch/expiry/rate/MRP/discount/GST/amount as-is; each `*vhdetail` row becomes `ledger_transactions` as stored (`DR`→debit, `CR`→credit, with `reference_type`/`reference_id` link). **No `PostingEngine.post_*`, no `SalesDAO`/`PurchaseDAO.insert` for history.**
6. Stock explicitly skipped in this transaction task (no `stock_batches` overwrite).
7. Optional `userinfo` only with `--import-legacy-users` (inactive, passwords never).
8. `--verify` read-only: `integrity_check ok`, `foreign_key_check` empty, counts (`source−skipped=imported`), every legacy id mapped, orphans none, no active disabled accounts. Stock reconciliation deferred to Phase 3 (unapplied).

Idempotency: re-run clears business data first (`CLEAR_ORDER`), remaps all legacy IDs fresh, reuses deterministic `_unique_voucher` + `#legacy_id` suffix, records `legacy_migration_meta` + `legacy_id_map`. Repeating produces same rows, never duplicates.

Staging first: `--import --db staging/...` + `--verify` + UI spot-checks (Sales/Purchase/Party/GST/Trial/P&L/Balance/Cash/Bank per FY) + `run_tests.py`, then production only with `--confirm-production`.

---

## 8. Ready to import vs needs decision

**Ready (pending approval, no open mapping question):**
- 12 FYs (11 to create), all masters (1222+16+147+8+942+402+6), ledgers/groups/parties (123+22+29+85), purchases (5,713+11,891+11,426 detail), credit (1,349+3,329+42), debit (14+20+2), receipts (44+88), payments (785+1,598), sales lines/details with 0 orphans and 0 unmapped ledgers, per-FY totals in §3.

**Needs decision (do not import until answered):**
1. Sales `bill_no` rule: keep `FY-VhType-VhNo#id` (current, collides 67k) or switch to `BillNo`-based with `0`-handling? Legacy `BillNo` cannot be silently dropped per requirements.
2. `countersaleitems` 2, allocation tables (2,671+114+528+11), `ledgeropbal` 552, `challan*`, `softmaster`/`billsetting`/`patientmaster`/`sundrybillbybillopbal`/`accompany`: confirm exclude (no target).
3. `stockbalance`/`stockadjusted`: confirm **exclude from this transaction migration** (Phase 3 unapplied).
4. `userinfo` 2: confirm skip (default) vs opt-in inactive import.
5. Negative stock batches (14) and 2 history-only batches: confirm preserve-as-stored with qty 0 for history-only (no stock overwrite now).
6. Confirm staging DB path + production backup dir + `--confirm-production` gatekeeper.

---

## 9. Reconciliation totals (expected on approved import)

- Source data rows 504,369 (demo 934 excluded) → mapped targets per §2/§3 plus masters; skipped = merges (3 item dupes + doctor SELF) + opt-outs above; `source−skipped=imported` verified per table in `--verify`.
- FY 2017-2018 expected: sales 8,311+26,077 lines, purchases 657+1,303, credit 154+400, debit 0+0, receipts 3, payments 32, ledger rows 18,010.
- FY 2018-2019 expected: sales 8,051+25,744, purchases 567+1,075, credit 162+394, debit 0+0, receipts 3, payments 9, ledger rows 17,262.
- Historical display is **not claimed** until import + `--verify` pass on dev/staging. Current dev counts remain 0 for all transaction tables.

---

## 10. Approval gate

- [ ] Approve sales `BillNo` preservation rule (Q1 above).
- [ ] Approve exclusion list (§5/§8) and stock deferral.
- [ ] Approve staging import + verify + UI FY checks (2017-2018 vs 2018-2019 filter switching already proven by `test_financial_year_switch_1718_1819.py`).
- [ ] Then (separate task): verified backup → staging import → verify → production `--confirm-production` → verify again.

*End of dry run. No database was written, no dump was modified, no stock was touched.*
