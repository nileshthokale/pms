# Pharmacy Management System — Final Read-Only Legacy Migration Reconciliation Review

> **Date:** 2026-10-20 18:03:00  
> **Source Snapshot:** `PharmaWinner202610201418.sql` (35,533,535 bytes, SHA-256: `6e54dd819a077fd5a24e40ce8c21ad85f4e3040ea47dd337162347075802c388`)  
> **Isolated Staging Database:** `staging/pharmacy_staging.db` (PRAGMA integrity_check = `ok`, 0 foreign-key violations)  
> **Active Production Database:** `data/pharmacy.db` (**100% UNTOUCHED BUSINESS DATA**)  
> **Status:** GATED / STOP ENFORCED (No staging promotion, no live modifications, no EXE rebuild)

---

## Executive Summary & Direct Answers to Inconsistencies

A comprehensive, strictly read-only audit of all reports, scripts, source SQL rows, and staging database records was conducted to investigate the five reported inconsistencies.

```
+----------------------------------------------------------------------------------------------------+
| Discrepancy               | Previous Report | Verified Truth | Net Diff | Primary Cause            |
+---------------------------+-----------------+----------------+----------+--------------------------+
| 1. IMPORTED Rows          | 939             | 940            | +1       | itemdrugs col index bug  |
| 2. MERGED Rows            | 4               | 7 source rows  | +3       | itemmst unit_id mismatch |
| 3. VERIFIED_UPDATE Rows   | 1,069           | 1,066          | -3       | 3 merged items recategorized |
| 4. ALREADY_MATCHED Rows   | 495,785         | 495,784        | -1       | itemdrugs 413 reclassed  |
| 5. UNUSED-DATA CSV Rows   | 8,456           | 8,459          | +3       | Includes all 7 merged    |
| TOTAL SOURCE ROWS         | 506,249         | 506,249        | 0        | Exact dump total match   |
+----------------------------------------------------------------------------------------------------+
```

---

## Investigation 1: IMPORTED Row Count (939 vs 940)

- **Prior State**: The earlier implementation plan estimated 940 imported rows, but the generated report listed 939.
- **Root Cause Identified**:
  In `tools/build_row_level_ledger.py` line 270:
  ```python
  for r in dump.iter_rows("itemdrugs"):
      it_id = str(r[0])
      if it_id == "944":
          disposition_counts["IMPORTED"] += 1
  ```
  In `itemdrugs`, the column schema is `['ID', 'ItemID', 'DrugID', 'Power']`.
  `r[0]` is the primary key `ID` (value `413`).
  `r[1]` is the foreign key `ItemID` (value `944`).
  Because the script checked `r[0] == "944"`, row 413 evaluated to `False` and was incorrectly classified as `ALREADY_MATCHED`.
- **Physical Verification in Staging Database**:
  - Legacy `itemdrugs` row `[413, 944, 11, '1 PCS']` was physically migrated into target table `item_ingredients` as ID `813` (`item_id = 1885, drug_id = 281, power = '1 PCS'`).
  - In `data/pharmacy.db`, max `item_ingredients.id` is 812; row 813 is genuinely newly imported.
- **Resolution**:
  Row 413 belongs in **`IMPORTED`**. Correcting the index check brings the verified count to exactly **940 rows**, in 100% agreement with the physical database insertions.

---

## Investigation 2: MERGED Row Count (4 vs 6 vs 7)

- **Prior State**: The final report claimed 4 merged rows, whereas the earlier plan expected 6 (referencing duplicate companies, doctors, and items).
- **Physical Verification of Source & Target Mappings**:
  Querying `legacy_id_map` for all target entities receiving multiple legacy source IDs establishes the exact ground truth:

  1. **Company Duplicates (3 source rows $\rightarrow$ 2 target entities)**:
     - Legacy Company `2541` (`ALKEM`): Merged with legacy `2540` into target company `3761`.
     - Legacy Company `2568` (`JAGSAM PHARMA`): Merged with legacy `2567` into target company `3787`.
     - Legacy Company `2569` (`JAGSAM PHARMA`): Merged with legacy `2567` into target company `3787`.
  2. **Doctor Duplicates (1 source row $\rightarrow$ 1 target entity)**:
     - Legacy Doctor `6` (`SELF`): Merged with legacy `3` into target doctor `11`.
  3. **Item Duplicates (3 source rows $\rightarrow$ 3 target entities)**:
     - Legacy Item `920` (`POWERGESIC`, unit 15): Merged with legacy `51` (unit 12) into target item `996`.
     - Legacy Item `303` (`VITOMIN-Z`, unit 12): Merged with legacy `290` (unit 11) into target item `1234`.
     - Legacy Item `869` (`CALTONVIT`, unit 5): Merged with legacy `681` (unit 12) into target item `1624`.

- **Explanation of Differences**:
  - The plan described **6 target merged entities** (2 companies + 1 doctor + 3 items).
  - At the source-row level, `JAGSAM PHARMA` has **2** duplicate rows (`2568` and `2569`), so companies contribute 3 merged rows, not 2.
  - `tools/build_row_level_ledger.py` previously evaluated `key = (name, unit_id)`. Because items 920, 303, and 869 had different legacy `UnitID`s from their counterparts, the composite key test missed them, finding only the 3 company rows and 1 doctor row ($3 + 1 = 4$).
- **Resolution**:
  The verified number of merged source rows is **7 source rows** (consolidated into 6 target entities).

---

## Investigation 3: VERIFIED UPDATE Count (1,069 vs 1,066)

- **Prior State**: The report claimed 1,069 verified updates, while the plan expected 1,066 (939 item tax backfills + 127 stock-batch balance updates).
- **Audit of Physical Records**:
  - `itemmst` has **943 source rows**:
    - $1$ row is newly imported (Item 944).
    - $3$ rows are merged duplicates (Items 920, 303, 869).
    - Exactly **939 distinct items** exist in target `items` table and received `legacy_tax_id` provenance backfill.
    - The previous report counted $943 - 1 = 942$ as updates because the 3 merged items were not deducted.
  - `stockbalance` has **7,806 source rows**:
    - **13 new batches** are imported (12 for purchases + 1 for Item 944).
    - **127 existing batches** had quantity differences between dump closing balance and baseline, and were synchronized.
    - **7,666 existing batches** already had identical stock quantities in the baseline.
- **Resolution**:
  $$\text{Verified Updates} = 939 (\text{distinct items tax backfill}) + 127 (\text{stock batches updated}) = \mathbf{1,066}\text{ rows}$$
  The 3-row variance between 1,069 and 1,066 was the exact 3 merged items (920, 303, 869) that belonged in `MERGED_WITH_REASON`.

---

## Investigation 4: UNUSED-DATA CSV Count (8,456 vs 8,452 vs 8,459)

- **Prior State**: The report cited 8,456 non-operational rows, whereas 4,102 archive rows + 4,350 excluded rows equals 8,452.
- **Content Inspection of `legacy_data_unused_rows.csv`**:
  - The CSV ledger collects all legacy records that do not have an independent, 1:1 operational representation in target.
  - The previous CSV contained:
    - 4,102 `PRESERVED_IN_ARCHIVE`
    - 4,350 `EXCLUDED_WITH_REASON`
    - 4 `MERGED_WITH_REASON` (Companies 2541, 2568, 2569; Doctor 6)
    - Total: $4,102 + 4,350 + 4 = \mathbf{8,456}$ entries.
  - The report text had summarized this as "8,456 non-operational rows", but omitted explaining that the 4 merged rows were included in the CSV.
- **Resolution**:
  With the 3 merged duplicate item rows (920, 303, 869) correctly routed to the unused data ledger, `legacy_data_unused_rows.csv` now contains:
  $$\begin{aligned}
  \text{PRESERVED\_IN\_ARCHIVE} &= 4,102 \\
  \text{EXCLUDED\_WITH\_REASON} &= 4,350 \\
  \text{MERGED\_WITH\_REASON} &= 7 \\
  \hline
  \mathbf{TOTAL\ CSV\ ENTRIES} &= \mathbf{8,459}
  \end{aligned}$$
  - **Key Verification**: `(source_table, source_legacy_id)` has been verified across all 8,459 rows. There are **0 duplicate keys**.

---

## Investigation 5: Source-Row Mutually Exclusive Partition

Every single row in `PharmaWinner202610201418.sql` (52 tables, 506,249 rows) is assigned to exactly one primary disposition:

| Primary Disposition | Verified Row Count | Percentage | Scope |
|---|---:|---:|---|
| **`ALREADY_MATCHED`** | 495,784 | 97.93% | Historical verified operational rows identical in baseline and dump. |
| **`EXCLUDED_WITH_REASON`** | 4,350 | 0.86% | 4,346 table-level exclusions + 4 detail lines of deleted sale 72160. |
| **`PRESERVED_IN_ARCHIVE`** | 4,102 | 0.81% | 8 unsupported legacy tables stored in staging `legacy_archive_*`. |
| **`VERIFIED_UPDATE`** | 1,066 | 0.21% | 939 distinct item tax backfills + 127 stock-batch balance updates. |
| **`IMPORTED`** | 940 | 0.19% | Item 944, itemdrugs 413, 9 Purchases, 130 Sales, 5 Credit Notes, items, ledgers, 13 batches. |
| **`MERGED_WITH_REASON`** | 7 | 0.00% | 3 company rows, 1 doctor row, 3 item rows merged into target entities. |
| **`UNRESOLVED`** | 0 | 0.00% | Zero unclassified or orphaned rows. |
| **TOTAL** | **506,249** | **100.00%** | **Exact match to parsed MySQL dump.** |

---

## Investigation 6: Stock & Financial Safety Verification

All safety invariants have been re-verified using strictly read-only queries against `staging/pharmacy_staging.db`:

1. **Native Stock Movements**:
   - `CGT26065C` (Target Item 1796 `EFEREM SP`): Dump closing $184.0$ + Native Purchase 5714 ($+240.0$) = **$424.0$ loose units** (PASS).
   - `AC2604005C` (Target Item 1442 `STABIZOL DSR`): Dump closing $219.0$ - Native Sale 72048 ($-1.0$) = **$218.0$ loose units** (PASS).
   - `146005EH` (Negative batch): Preserved verbatim at **$-42.0$ loose units** (PASS).
2. **Credit Note Safety**:
   - Headers 1350–1354 in `credit_notes` have `remarks` containing `AddedToLedger='N' (Unposted in legacy source)`.
   - Query: `SELECT count(*) FROM ledger_transactions WHERE reference_type = 'CREDIT_NOTE' AND reference_id >= 1350` yields **0 rows** (PASS).
3. **Double-Entry Equality**:
   - Staging Ledger: Debits = **₹47,251,923.27**, Credits = **₹47,251,923.27** (Difference = **₹0.00**).
4. **Native Transactions**:
   - Native Purchase 5714 (`2026-2027-Credit-0251`, supplier 216), Native Sale 72048 (`2026-2027-1910`), Native Supplier 242 (`National Distributors`), Native Payment 786, and Native Receipt 45 are intact.
5. **Active Database Integrity & Hash Investigation**:
   - Baseline $T_0$ captured prior to staging creation: `5a8f768322d00e42184be70d519b65b0871c7cdf54376b078b395d5ff808fb32`.
   - At `2026-10-20T12:21:24Z` (17:51:24 local time), user `pratap` logged in via the UI, appending row 190 to `auth_audit_log` in `data/pharmacy.db`:
     `(190, '2026-10-20T12:21:24.283687+00:00', 'pratap', 'login', 1, '')`.
   - Current file hash: `673aed780ee2d89b1ead216db10b7edd2acebdc44b43ea875b683f8a48ce8a97`.
   - **Verification**: Every single business data table (`items`, `purchase_invoices`, `sales_invoices`, `credit_notes`, `stock_batches`, `ledger_transactions`, `suppliers`) remains 100% byte-identical to the baseline. Zero migration operations touched `data/pharmacy.db`.

---

## Investigation 7: Test Suite Status

The automated test suite was executed across all unit and regression test modules:
```powershell
python -m unittest test_legacy_refresh_verification.py test_accounting_posting.py test_counter_sale_posting.py test_purchase_posting.py test_purchase_free_qty.py test_legacy_stock_resolution.py
```
- **Total Tests**: **178 tests**
- **Passed**: **178 passed**
- **Failures / Errors**: **0**
- **Execution Time**: **17.67 seconds**

---

## Mandatory Safety Protocol Adherence

- Staging promotion has **NOT** been performed.
- `data/pharmacy.db` has **NOT** been modified by migration scripts.
- No database records in `staging/pharmacy_staging.db` were altered during this reconciliation review.
- Packaged EXE and `dist/` remain untouched.
- Promotion to production remains gated awaiting explicit user approval.
