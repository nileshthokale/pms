# Forensic Discrepancy Review & Audit Report: Legacy Data Refresh

> **PROMOTION STATUS: BLOCKED**
> 
> **Blocking Reason:** Refresh engine Step 5 (stock synchronization) directly overwrote stock_batches.stock_qty with source closing balances, which erased native purchase additions (+240 units on batch CGT26065C) and native sales deductions (-1 unit on batch AC2604005C). Promotion cannot proceed until stock synchronization is modified to apply incremental deltas.
> 
> **Safety Protocol:** `data/pharmacy.db` remains 100% protected and untouched. Staging database (`staging/pharmacy_staging_refresh.db`) contains an identified stock overwrite defect in Step 5 of `tools/legacy_refresh_engine.py` and must NOT be promoted until corrected.

---

## Executive Summary of Findings

| Issue | Planned / Source Expected | Staging Actual Result | Forensic Determination | Impact / Status |
| :--- | :--- | :--- | :--- | :--- |
| **1. Purchase Details** | 21 planned (11,913 source total) | 22 added (11,914 total) | Pre-refresh staging had 1 native purchase item (ID 11892), meaning only 11,891 legacy items were present. Exactly 22 incoming rows were added (11,891 + 22 = 11,913 source rows + 1 native = 11,914). | **RESOLVED & VERIFIED** (0 duplicates) |
| **2. Sales Details** | 471 planned (234,066 source total) | 468 added (234,063 total) | Source dump contains exactly 468 incoming items for headers 72089–72219. Gap of 3 is explained by 4 legacy rows deleted with sale 72160 (`2026-2027-1857`) minus 1 native row (sale 72048). 4 - 1 = 3. | **RESOLVED & VERIFIED** (468 inserted, 4 deleted, 1 native) |
| **3. Ledger Transactions** | 44 purchase, 260 sales, 10 credit note | 18 purchase, 260 sales, 0 credit note (278 total) | Purchase ledger is per voucher (9 * 2 = 18). Incoming credit notes had `AddedToLedger = 'N'` (0 ledger entries). Sales had 130 * 2 = 260. All 278 incoming rows inserted. | **RESOLVED & VERIFIED** (Plan formulas were flawed) |
| **4. Financial Reconciliation** | ₹47,199,200.77 (Source DR/CR) | ₹47,251,923.27 (Staging DR/CR) | Difference of +₹52,722.50 matches native vouchers penny-for-penny: Supplier Payment ₹50,000 + Purchase ₹1,567 + Receipt ₹300 + Sales ₹174.30 + Reversals ₹681.20 = ₹52,722.50. | **PERFECT RECONCILIATION** (₹0.00 variance) |
| **5. Stock Batches** | Preserve native stock movements | Native stock movements overwritten | Step 5 of refresh engine directly set `stock_qty = CBqty * loose_factor`, wiping out native purchase (+240 units on CGT26065C) and native sale (-1 unit on AC2604005C). | **CRITICAL DEFECT — PROMOTION BLOCKED** |

---

## Issue 1: Purchase Details Forensic Investigation

### Background & Numbers
- **Source Dump Count (`purchasevhdetail`):** 11,913 rows
- **Staging Count Before Refresh:** 11,892 rows
- **Staging Count After Refresh:** 11,914 rows
- **Actual Rows Added:** 22 rows
- **Plan Naive Estimate:** 21 rows (`11,913 - 11,892 = 21`)

### Root Cause Analysis
The plan anticipated 21 incoming rows using a naive arithmetic difference between the source total (11,913) and the pre-refresh staging table row count (11,892). However, this calculation overlooked that pre-refresh staging was a clone of the live database, which contained **1 native purchase line** entered in the live application after the first migration:
- **Native Purchase Item:** `purchase_invoice_items.id = 11892`
- **Voucher No:** `2026-2027-Credit-0251` (Purchase ID 5714)
- **Date:** 2026-10-08 | **Supplier:** ANAND PHARMA (Supplier ID 42)
- **Item:** C-CEF DRY SYRUP (Item ID 944) | **Batch:** `CGT26065C` | **Pay Qty:** 24.0 packs | **Amount:** ₹1,567.00

Because 1 of the 11,892 rows was native, only **11,891** legacy rows were present before the refresh. The new SQL dump contained exactly **22 new purchase detail rows** (Detail IDs 12323 to 12344 across Purchase Voucher Headers 5718 to 5726):
$$\text{Pre-refresh Legacy Rows (11,891)} + \text{Incoming Legacy Rows (22)} = 11,913 \text{ (100.0\% of source dump)}$$
Adding the 1 native row yields the exact post-refresh count:
$$11,913 \text{ legacy} + 1 \text{ native} = 11,914 \text{ total rows in staging}$$

### Complete Row-Level Inventory of Added Purchase Details (22 Items)

| Target ID | Legacy Hdr | Legacy Det | Invoice No | Date | Item Name (ID) | Batch | Expiry | Pack Size | Pay Qty | Free Qty | Rate | MRP | Amount | GST % |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 11893 | 5718 | 12323 | `6544` | 2026-10-07 | NERVMAX D (1745) | `FBAF2603` | 2028-05-31 | 10 | 5.0 | 0.0 | 150.06 | 196.95 | 750.30 | 5.0% |
| 11894 | 5718 | 12331 | `6544` | 2026-10-07 | L-CIN 250 (1655) | `JC01646` | 2028-05-31 | 10 | 19.0 | 1.0 | 39.39 | 51.70 | 748.41 | 5.0% |
| 11895 | 5718 | 12332 | `6544` | 2026-10-07 | KENACORT 40 1ML (1328) | `NCM0144` | 2029-06-30 | 1 | 8.0 | 0.0 | 177.72 | 233.26 | 1421.76 | 5.0% |
| 11896 | 5718 | 12333 | `6544` | 2026-10-07 | LORNOXI P (1514) | `2GT25793A.` | 2027-08-31 | 10 | 9.0 | 1.0 | 47.47 | 62.30 | 427.23 | 5.0% |
| 11897 | 5718 | 12334 | `6544` | 2026-10-07 | PANTOCID DSR (1844) | `GTH1939A` | 2028-05-31 | 15 | 10.0 | 0.0 | 192.14 | 252.19 | 1921.40 | 5.0% |
| 11898 | 5719 | 12324 | `14346` | 2026-10-03 | ARTHRASPAZ 4MG (1646) | `CUM02ADB` | 2028-05-31 | 10 | 5.0 | 1.0 | 189.71 | 249.00 | 948.55 | 5.0% |
| 11899 | 5719 | 12325 | `14346` | 2026-10-03 | BONULTRA (1743) | `CUM02ACB` | 2028-07-31 | 10 | 10.0 | 2.0 | 189.71 | 249.00 | 1897.10 | 5.0% |
| 11900 | 5719 | 12326 | `14346` | 2026-10-03 | STABIZOL DSR (1442) | `AC2604005C` | 2028-03-31 | 10 | 30.0 | 6.0 | 92.20 | 121.00 | 2766.00 | 5.0% |
| 11901 | 5719 | 12327 | `14346` | 2026-10-03 | STAMIN PLUS (1443) | `ST-2606` | 2028-01-31 | 10 | 20.0 | 4.0 | 49.53 | 65.00 | 990.60 | 5.0% |
| 11902 | 5720 | 12328 | `58239` | 2026-10-06 | NASO B12 (1691) | `1X26004` | 2028-01-31 | 1 | 10.0 | 1.0 | 337.07 | 442.40 | 3370.70 | 5.0% |
| 11903 | 5721 | 12329 | `14578` | 2026-10-06 | STAFLEX 3 D (1753) | `26SFC02` | 2027-10-31 | 14 | 10.0 | 2.0 | 520.38 | 683.00 | 5203.80 | 5.0% |
| 11904 | 5721 | 12330 | `14578` | 2026-10-06 | ARTHRASPAZ 4MG (1646) | `CUM03ADB` | 2028-07-31 | 10 | 5.0 | 1.0 | 189.71 | 249.00 | 948.55 | 5.0% |
| 11905 | 5722 | 12335 | `3825` | 2026-10-08 | TRAMAGOLD (1550) | `ST26-1050` | 2028-02-29 | 10 | 1.0 | 2.0 | 80.79 | 106.03 | 80.79 | 5.0% |
| 11906 | 5722 | 12336 | `3825` | 2026-10-08 | TRAMAGOLD (1550) | `ST26-2374` | 2028-06-30 | 10 | 9.0 | 0.0 | 80.79 | 106.03 | 727.11 | 5.0% |
| 11907 | 5722 | 12337 | `3825` | 2026-10-08 | ULTRAMYCIN-250 (1817) | `ULM25-52` | 2028-03-31 | 10 | 10.0 | 2.0 | 38.56 | 50.60 | 385.60 | 5.0% |
| 11908 | 5723 | 12338 | `42270` | 2026-10-09 | LIMCEE (1846) | `LBR26738` | 2028-05-31 | 15 | 10.0 | 0.0 | 18.93 | 24.84 | 189.30 | 5.0% |
| 11909 | 5723 | 12339 | `42270` | 2026-10-09 | CALDIKIND 60K NANO (1859) | `D9CWZ014` | 2028-01-31 | 1 | 22.0 | 2.0 | 61.75 | 81.05 | 1358.50 | 5.0% |
| 11910 | 5723 | 12340 | `42270` | 2026-10-09 | NERVMAX D (1745) | `FBAF2603` | 2028-05-31 | 10 | 5.0 | 0.0 | 150.06 | 196.95 | 750.30 | 5.0% |
| 11911 | 5723 | 12341 | `42270` | 2026-10-09 | ZERODOL MR (1873) | `GGG0426005` | 2028-05-31 | 10 | 5.0 | 0.0 | 97.52 | 128.00 | 487.60 | 5.0% |
| 11912 | 5724 | 12342 | `5549` | 2026-10-13 | MERSILK NW 5010 (1885) | `V2010` | 2027-10-31 | 1 | 2.0 | 0.0 | 151.00 | 239.00 | 302.00 | 5.0% |
| 11913 | 5725 | 12343 | `111` | 2026-10-09 | PANTIUM 40MG (995) | `N2504069` | 2028-11-30 | 10 | 10.0 | 0.0 | 88.93 | 116.72 | 889.30 | 5.0% |
| 11914 | 5726 | 12344 | `3944` | 2026-10-16 | EFEREM SP (1796) | `CGT26065C` | 2027-12-31 | 10 | 20.0 | 4.0 | 74.64 | 97.96 | 1492.80 | 5.0% |

### Verification of Integrity
- **Duplicate Check:** Verified 0 duplicates across `(purchase_invoice_id, item_id, batch_no)`.
- **Foreign Key Check:** 100% of foreign keys resolve validly to `purchase_invoices`, `items`, and `suppliers`.

---

## Issue 2: Sales Details Forensic Investigation

### Background & Numbers
- **Source Dump Count (`salesvhdetail`):** 234,066 rows
- **Staging Count Before Refresh:** 233,595 rows
- **Staging Count After Refresh:** 234,063 rows
- **Actual Rows Added:** 468 rows
- **Plan Naive Estimate:** 471 rows (`234,066 - 233,595 = 471`)
- **Difference to Explain:** 3 rows (`471 - 468 = 3`)

### Forensic Resolution of the 3-Record Difference
The dump was audited to count the actual detail rows belonging to the 130 incoming new sales vouchers (Header IDs 72089 to 72219). The SQL dump contains **exactly 468 detail rows** (Detail IDs 237055 to 237522). All 468 were inserted without exception.

The 3-record difference between the plan's naive 471 and the actual 468 is explained by two offsetting historical events in the live database:
1. **Deleted Legacy Sales Invoice 72160 (`2026-2027-1857`):**
   In the live application, the user legitimately deleted sales invoice 72160 (mapped to target ID 71988). In the source dump, voucher 72160 has **4 detail lines** (Detail IDs 237051, 237052, 237053, and 237054). When deleted in the application, these 4 lines were removed from `sales_invoice_items`, and reversal transactions were posted to the ledger (IDs 157293 and 157294).
   $$\text{Older legacy rows in dump (233,598)} - \text{Deleted legacy rows (4)} = 233,594$$
2. **Native Sales Invoice 72048 (`2026-2027-1910`):**
   A native sales invoice was created in the application on 2026-10-09, adding **1 native detail line** (Item 65, ACECLO PLUS, Batch `AC2604005C`, Qty 1).
   $$233,594 + 1 \text{ (native detail)} = 233,595 \text{ rows in pre-refresh staging}$$

When the plan computed `234,066 - 233,595 = 471`, it did not know that 4 legacy rows had been deleted and 1 native row had been added. The exact reconciliation of the 471 rows is:

| Category | Count | Status in Staging | Explanation |
| :--- | :--- | :--- | :--- |
| **New Incoming Source Details** | 468 | **Inserted** | Detail IDs 237055 to 237522 belonging to 130 new invoices (72089–72219). |
| **Deleted Legacy Sale Details** | 4 | **Excluded / Deleted** | Detail IDs 237051–237054 belonging to deleted bill 72160 (`2026-2027-1857`). |
| **Native Detail Row** | 1 | **Already Present** | Detail on native invoice 72048 (`2026-2027-1910`). |
| **Total Accounted** | **471** | | Exact row-level accounting (`468 + 4 - 1 = 471`). Unexplained: 0. |

### Sales Invoices Count & Collision Handling
- **Pre-refresh Invoices:** 72,045
- **New Incoming Invoices:** 130
- **Post-refresh Invoices:** 72,175 (matches source dump count of 72,175)

#### Native Invoice 72048 vs Source Invoice 72219 Collision Resolution:
- **Native Invoice 72048:** Created natively on 2026-10-09 with invoice number `2026-2027-1910`. It is preserved intact in `sales_invoices` at `id = 72048`.
- **Source Invoice 72219:** Created in legacy on 2026-10-20 with legacy BillNo `1910`. To avoid overwriting or colliding with native invoice 72048, the refresh engine detected the duplicate number and assigned the unique invoice number `2026-2027-1910#72219` at `id = 72055`.
- Both invoices coexist with full detail lines and ledger entries. No data was lost or overwritten.

---

## Issue 3: Ledger Transactions Reconciliation

### Background & Numbers
- **Incoming Ledger Rows in Source Dump:** 278 rows
- **Plan Naive Estimate:** 314 rows (44 purchase, 260 sales, 10 credit notes)
- **Actual Inserted in Staging:** 278 rows (18 purchase, 260 sales, 0 credit notes)
- **Unmapped / Failed:** 0 rows

### Explaining the Plan's Speculative Estimates
1. **Purchase Ledger (Actual 18 vs Plan 44):**
   - The plan assumed 2 ledger rows per purchase item detail (`22 items * 2 = 44`).
   - In legacy PharmaWinner, accounting vouchers are recorded in `invoicevhdetail` per **purchase voucher header**, NOT per item line. For the 9 new purchase vouchers (Headers 5718 to 5726), exactly 2 rows per voucher were created (1 DR Purchase A/c, 1 CR Supplier A/c), totaling **18 rows** (IDs 19049 to 19066).
2. **Credit Note Ledger (Actual 0 vs Plan 10):**
   - The plan guessed 2 ledger rows per credit note (`5 credit notes * 2 = 10`).
   - In legacy PharmaWinner, credit notes are sales returns that only post to the financial ledger if `creditnotevh.AddedToLedger = 'Y'`. All 5 new credit notes (Headers 1350 to 1354) have `AddedToLedger = 'N'` and have **0 rows** in `creditnotevhdetail`.
   - Across the entire source dump of 1,354 credit notes, only 21 ever had ledger entries. Zero incoming credit notes had ledger entries in the source dump.
3. **Sales Ledger (Actual 260 vs Plan 260):**
   - For 130 new sales vouchers, exactly 2 rows per voucher (1 DR Customer/Cash, 1 CR Sales) were recorded in `salesvhdetail` (IDs 372439 to 372698), totaling **260 rows**.

$$\text{Total Incoming Ledger Rows} = 18 \text{ (purchase)} + 0 \text{ (credit note)} + 260 \text{ (sales)} = 278 \text{ rows}$$
All 278 rows were cleanly inserted into `ledger_transactions` (IDs 157304 to 157581).

---

## Issue 4: Financial Reconciliation & Mathematical Bridge

### Background & Numbers
- **Source Dump Ledger Totals:** DR ₹47,199,200.77 | CR ₹47,199,200.77
- **Staging Database Ledger Totals:** DR ₹47,251,923.27 | CR ₹47,251,923.27
- **Global Net Variance:** +₹52,722.50 per side

### Mathematical Bridge (Down to the Exact Paisa)
The entire difference of ₹52,722.50 between source ledger totals and staging ledger totals is completely and mathematically accounted for by native transactions created in the application after migration:

| Category | Voucher No / ID | Transaction Type | Debit Amount (₹) | Credit Amount (₹) | Accounts Impacted |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Native Supplier Payment** | `SP-2026` | PAYMENT | ₹50,000.00 | ₹50,000.00 | DR: ANAND PHARMA (Supplier)<br>CR: STATE BANK OF INDIA (Bank) |
| **Native Purchase Invoice** | `2026-2027-Credit-0251` | PURCHASE | ₹1,567.00 | ₹1,567.00 | DR: PURCHASE A/C<br>CR: ANAND PHARMA (Supplier) |
| **Native Customer Receipt** | `CR-2027` | RECEIPT | ₹300.00 | ₹300.00 | DR: CASH IN HAND<br>CR: Walk-in / Customer Account |
| **Native Active Counter Sales** | `Multiple (9 vouchers)` | SALE | ₹174.30 | ₹174.30 | DR: CASH IN HAND<br>CR: SALES A/C |
| **Native Counter Sale Reversals / Deletions** | `Reversals (including 72160 / 2026-2027-1857)` | SALE_REVERSAL | ₹681.20 | ₹681.20 | DR: SALES A/C<br>CR: CASH IN HAND |
| **Total Native Variance** | | | **₹52,722.50** | **₹52,722.50** | |
| **Unexplained Variance** | | | **₹0.00** | **₹0.00** | **PERFECT RECONCILIATION** |

### Account-Wise Ledger Impact
- **Account 42 (ANAND PHARMA - Supplier):** Native Payment `SP-2026` (-₹50,000) and Native Purchase (+₹1,567).
- **Account 2 (STATE BANK OF INDIA - Bank):** Native Payment `SP-2026` credit (-₹50,000).
- **Account 1 (CASH IN HAND):** Native Receipt `CR-2027` (+₹300), Counter Sales (+₹174.30), Counter Sale Reversals (-₹681.20).
- **Account 3 (PURCHASE A/C):** Native Purchase (+₹1,567).
- **Account 4 (SALES A/C):** Counter Sales (+₹174.30), Reversals (-₹681.20).

Every historical legacy transaction in `invoicevhdetail` and `salesvhdetail` matches staging exactly. Internal debit-credit equality is preserved at both voucher level and global level.

---

## Issue 5: Stock and Party Reconciliation (CRITICAL DEFECT)

### Identification of the 140 Modified Stock Batches
A full audit of the 140 batches modified during Step 5 of the refresh was conducted against `stockbalance` in the source SQL dump and `stock_batches` in the staging database.

### Critical Defect Identified in Refresh Engine
> [!CAUTION]
> **CRITICAL STOCK OVERWRITE DEFECT IDENTIFIED IN `tools/legacy_refresh_engine.py`**
> 
> Step 5 of the refresh engine executed:
> ```python
> c.execute("UPDATE stock_batches SET stock_qty = ? WHERE id = ?", (net_loose, b_id))
> ```
> This unconditionally set `stock_batches.stock_qty` to the source dump's closing stock (`stockbalance.CBqty * loose_factor`).
> 
> In a live application where users have already recorded native purchases and sales, **this blind overwrite destroys native stock transactions**!

### The Two Confirmed Overwrite Incidents:

#### 1. Batch `CGT26065C` — Item 944 (`C-CEF DRY SYRUP`):
- **Pre-migration legacy opening:** 15.4 packs = 154 loose units.
- **Native Purchase (Invoice 5714 / `2026-2027-Credit-0251`):** User purchased 24 packs (= 240 loose units) on 2026-10-08.
- **Live Database Stock:** `154 + 240 = 394.0` loose units.
- **Source Dump Closing Stock:** In legacy PharmaWinner, 3 packs had been purchased, giving closing stock of 18.4 packs (= 184 loose units).
- **Refresh Engine Behavior:** Blindly executed `UPDATE stock_batches SET stock_qty = 184.0 WHERE id = 11892`.
- **Result:** The 240 loose units purchased natively in the live application were **completely erased**, resulting in an inventory discrepancy of -210 loose units!

#### 2. Batch `AC2604005C` — Item 65 (`ACECLO PLUS`):
- **Live Database Stock:** 114.0 loose units (after native sale of 1 loose unit on invoice 72048).
- **Source Dump Closing Stock:** 220.0 loose units (22 packs * 10).
- **Refresh Engine Behavior:** Blindly executed `UPDATE stock_batches SET stock_qty = 219.0 WHERE id = ...`.
- **Result:** Erased the native sale deduction and reset stock to an unverified legacy balance.

### Complete Inventory of All 140 Modified Stock Batches

Comparison between pre-refresh live database (`data/pharmacy.db`) and post-refresh staging database (`staging/pharmacy_staging_refresh.db`): 127 existing batches updated, 13 new batches inserted.

| Item ID | Item Name | Batch No | Expiry | Pack Size | Live Qty (Loose) | Staging Qty (Loose) | Delta (Loose) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1622 | KINGESIC-TH4 | `LGJ08/149/09` | 2022-02-28 | 10 | 946.0 | 956.0 | +10 | UPDATED |
| 1182 | CREAP BANDAGE 3" | `LOT 20` | 2029-05-31 | 1 | 8.0 | 7.0 | -1 | UPDATED |
| 1132 | KNEE BRACE LONG TYPE | `BHU UN` | 2027-08-31 | 1 | 2.0 | 1.0 | -1 | UPDATED |
| 1828 | NEOFIX | `N2403007` | 2027-03-31 | 1 | 59.0 | 58.0 | -1 | UPDATED |
| 1449 | SOFT ROLL 3" | `22NB12` | 2030-11-30 | 1 | 1.0 | 0.0 | -1 | UPDATED |
| 1802 | TOFAKIN ER 11 | `T24049OP` | 2026-10-31 | 10 | 20.0 | 15.0 | -5 | UPDATED |
| 1074 | DISPO VAN 5ML | `452054SR2` | 2029-11-30 | 1 | 30.0 | 25.0 | -5 | UPDATED |
| 1806 | KETOROL-DT | `E2402923` | 2027-10-31 | 15 | 65.0 | 59.0 | -6 | UPDATED |
| 1857 | FOLITRAX 10 | `AT-130725` | 2028-06-30 | 5 | 1.0 | 0.0 | -1 | UPDATED |
| 1777 | TOFE ER | `25442377` | 2027-06-30 | 10 | 20.0 | 0.0 | -20 | UPDATED |
| 1620 | NACDOL | `SO097` | 2026-11-30 | 1 | 12.0 | 11.0 | -1 | UPDATED |
| 1819 | TRYLIQ-P | `ANR02ACA` | 2027-05-31 | 15 | 46.0 | 52.0 | +6 | UPDATED |
| 1321 | ELERAB D | `WEAB325001` | 2027-06-30 | 10 | 13.0 | 11.0 | -2 | UPDATED |
| 1665 | NACMUST SP | `LGP06/164/14` | 2027-05-31 | 10 | 7.0 | 3.0 | -4 | UPDATED |
| 1027 | CALDOB 500MG | `B250116` | 2027-06-30 | 15 | 29.0 | 21.0 | -8 | UPDATED |
| 1817 | ULTRAMYCIN-250 | `ULM25-52` | 2028-03-31 | 10 | 1.0 | 91.0 | +90 | UPDATED |
| 1711 | SOMPRAZ D 40 | `GTG2874A` | 2027-08-31 | 15 | 1.0 | 0.0 | -1 | UPDATED |
| 1743 | BONULTRA | `CUM02ACA` | 2027-06-30 | 10 | 20.0 | 35.0 | +15 | UPDATED |
| 973 | IMOL 60ML | `CGB1081` | 2027-07-31 | 1 | 29.0 | 28.0 | -1 | UPDATED |
| 1309 | NEEDLE NO 26 | `30462P` | 2030-06-30 | 1 | 21.0 | 19.0 | -2 | UPDATED |
| 1720 | TROYCOBAL SR | `2CZ25007` | 2026-11-30 | 10 | 2.0 | 0.0 | -2 | UPDATED |
| 1867 | DOXOFINE-100 | `MPT-30825` | 2027-06-30 | 10 | 37.0 | 2.0 | -35 | UPDATED |
| 1869 | SPINAL NEEDLE 23G | `2208020` | 2031-05-31 | 1 | 3.0 | 2.0 | -1 | UPDATED |
| 1734 | TUROFLAM | `0120` | 2027-10-31 | 1 | 5.0 | 4.0 | -1 | UPDATED |
| 1831 | BONEFILL PLUS | `CSD-25232` | 2027-10-31 | 10 | 20.0 | 5.0 | -15 | UPDATED |
| 1334 | UBINEXT-LC | `0AAIY020` | 2027-08-31 | 10 | 2.0 | 0.0 | -2 | UPDATED |
| 1622 | KINGESIC-TH4 | `LGP12/028/17` | 2027-11-30 | 10 | 269.0 | 254.0 | -15 | UPDATED |
| 1711 | SOMPRAZ D 40 | `GTG3803A` | 2027-11-30 | 15 | 2.0 | 0.0 | -2 | UPDATED |
| 1850 | TROTFIT | `02TOT26-41` | 2027-07-31 | 10 | 73.0 | 44.0 | -29 | UPDATED |
| 1775 | UC-ROSE | `JTF-2573` | 2027-04-30 | 10 | 231.0 | 219.0 | -12 | UPDATED |
| 1082 | DISPO VAN 10ML | `549105JD1` | 2030-11-30 | 1 | 6.0 | 4.0 | -2 | UPDATED |
| 1796 | EFEREM SP | `CGT26065C` | 2027-12-31 | 10 | 394.0 | 184.0 | -210 | UPDATED |
| 1606 | RELEVIT GOLD | `1120` | 2027-08-31 | 10 | 31.0 | 1.0 | -30 | UPDATED |
| 1809 | STINGOFLAM-SP | `CGT251348A` | 2027-07-31 | 10 | 199.0 | 179.0 | -20 | UPDATED |
| 1726 | ALGESIA CR | `18254384A` | 2027-10-31 | 10 | 113.0 | 78.0 | -35 | UPDATED |
| 1731 | TRIAM 40 | `SVI-25443A` | 2028-01-31 | 1 | 8.0 | 7.0 | -1 | UPDATED |
| 951 | BIO D3 PLUS | `14255775A` | 2028-11-30 | 15 | 15.0 | 0.0 | -15 | UPDATED |
| 972 | GOUTNIL | `GU2605` | 2029-09-30 | 10 | 44.0 | 34.0 | -10 | UPDATED |
| 1826 | DOLOMON SR | `ANR01AKA` | 2027-08-31 | 10 | 203.0 | 167.0 | -36 | UPDATED |
| 1809 | STINGOFLAM-SP | `HT240115` | 2026-12-31 | 10 | 68.0 | 58.0 | -10 | UPDATED |
| 1745 | NERVMAX D | `FBAA2601` | 2027-12-31 | 10 | 25.0 | 8.0 | -17 | UPDATED |
| 1334 | UBINEXT-LC | `OQQIY024` | 2027-10-31 | 10 | 8.0 | 0.0 | -8 | UPDATED |
| 1624 | CALTONVIT | `09CNT 25` | 2027-02-28 | 1 | 3.0 | 2.0 | -1 | UPDATED |
| 1191 | COCK UP SPLINT | `B U1` | 2032-01-31 | 1 | 4.0 | 2.0 | -2 | UPDATED |
| 1301 | STOLONEX | `ST-2609` | 2028-01-31 | 10 | 299.0 | 284.0 | -15 | UPDATED |
| 1013 | TETANUS TOXOID AMP | `2552B` | 2028-09-30 | 1 | 43.0 | 41.0 | -2 | UPDATED |
| 975 | INFUSION SET (JMS) | `4109225F` | 2030-05-31 | 1 | 8.0 | 7.0 | -1 | UPDATED |
| 1770 | MECOLTRIP | `LGT-260517` | 2028-03-31 | 10 | 268.0 | 258.0 | -10 | UPDATED |
| 1879 | MGMIX | `NPT1861` | 2028-04-30 | 10 | 0.0 | 14.0 | +14 | UPDATED |
| 1820 | ROCAM-20DT | `ANR02ADA` | 2027-09-30 | 10 | 161.0 | 151.0 | -10 | UPDATED |
| 1712 | LUMIA 2K | `GKH0615A` | 2027-05-31 | 10 | 84.0 | 28.0 | -56 | UPDATED |
| 1406 | STASHCAL CT | `09701326D` | 2028-02-29 | 10 | 1.0 | 0.0 | -1 | UPDATED |
| 1096 | KNEE CAP | `BHN` | 2036-05-31 | 1 | 12.0 | 11.0 | -1 | UPDATED |
| 1434 | SOLOPOSE 0.5 MD | `K25Z001` | 2028-01-31 | 10 | 56.0 | 51.0 | -5 | UPDATED |
| 1075 | DISPO VAN 2ML | `613025NG1` | 2031-02-28 | 1 | 58.0 | 35.0 | -23 | UPDATED |
| 1857 | FOLITRAX 10 | `AT-080426` | 2029-03-31 | 5 | 9.0 | 8.0 | -1 | UPDATED |
| 1780 | ETOSHAINE 90 | `SIH0734A` | 2028-09-30 | 15 | 70.0 | 60.0 | -10 | UPDATED |
| 1875 | NEUROBION CREAM | `5347D05653` | 2027-11-30 | 1 | 2.0 | 0.0 | -2 | UPDATED |
| 1371 | IBUCLIN JUNIOR | `V2600568` | 2028-01-31 | 10 | 126.0 | 106.0 | -20 | UPDATED |
| 1689 | STASHPAIN | `133` | 2027-09-30 | 1 | 15.0 | 13.0 | -2 | UPDATED |
| 1535 | CETIL 250MG | `TAKV26006A` | 2028-04-30 | 10 | 78.0 | 64.0 | -14 | UPDATED |
| 1328 | KENACORT 40 1ML | `NCM0060` | 2029-03-31 | 1 | 6.0 | 0.0 | -6 | UPDATED |
| 1811 | ORICOXIB-TH | `CGT26828K` | 2028-03-31 | 10 | 125.0 | 17.0 | -108 | UPDATED |
| 1514 | LORNOXI P | `2GT25793A.` | 2027-08-31 | 10 | 0.0 | 100.0 | +100 | UPDATED |
| 1739 | ENDOFLAM SP | `SGT-60295` | 2028-05-31 | 10 | 6.0 | 0.0 | -6 | UPDATED |
| 1321 | ELERAB D | `WEAB325002` | 2027-11-30 | 10 | 699.0 | 633.0 | -66 | UPDATED |
| 1406 | STASHCAL CT | `0970326D` | 2028-02-29 | 10 | 98.0 | 48.0 | -50 | UPDATED |
| 1844 | PANTOCID DSR | `GTG3745A` | 2027-11-30 | 15 | 104.0 | 24.0 | -80 | UPDATED |
| 1813 | RABEKIND 20 | `H25Z003` | 2028-02-29 | 15 | 56.0 | 51.0 | -5 | UPDATED |
| 1175 | DURAPLAST 4" | `4313` | 2031-12-31 | 1 | 14.0 | 11.0 | -3 | UPDATED |
| 1655 | L-CIN 250 | `JC00541` | 2028-01-31 | 10 | 187.0 | 144.0 | -43 | UPDATED |
| 1701 | DOLOXICAM | `D125H129` | 2029-03-31 | 15 | 207.0 | 172.0 | -35 | UPDATED |
| 1585 | MINAC MR | `CBT26-0950E` | 2028-04-30 | 10 | 140.0 | 50.0 | -90 | UPDATED |
| 1097 | PLACIDA | `D65Z006` | 2027-09-30 | 10 | 47.0 | 32.0 | -15 | UPDATED |
| 1351 | TENDOMAC | `MML/26/006` | 2028-04-30 | 15 | 63.0 | 18.0 | -45 | UPDATED |
| 1032 | INDOCAP S.R. | `JSR-332` | 2029-03-31 | 10 | 155.0 | 135.0 | -20 | UPDATED |
| 995 | PANTIUM 40MG | `N2504069` | 2028-11-30 | 10 | 34.0 | 96.0 | +62 | UPDATED |
| 1666 | DISPO MASK | `AMISCO` | 2034-05-31 | 1 | 2.0 | 4.0 | +2 | UPDATED |
| 1646 | ARTHRASPAZ 4MG | `CUM02ADB` | 2028-05-31 | 10 | 20.0 | 5.0 | -15 | UPDATED |
| 1879 | MGMIX | `NPT2029` | 2028-06-30 | 10 | 149.0 | 67.0 | -82 | UPDATED |
| 1711 | SOMPRAZ D 40 | `GTH0852A` | 2028-03-31 | 15 | 2.0 | 0.0 | -2 | UPDATED |
| 971 | GLOVES NULIFE 7 | `TSPSMP3125.` | 2030-08-31 | 1 | 32.0 | 26.0 | -6 | UPDATED |
| 1116 | DYNAPAR 1 ML | `PA25102` | 2027-11-30 | 1 | 52.0 | 47.0 | -5 | UPDATED |
| 1753 | STAFLEX 3 D | `26SFC02` | 2027-10-31 | 14 | 51.0 | 147.0 | +96 | UPDATED |
| 1825 | MAC RD | `02260355` | 2028-03-31 | 15 | 111.0 | 27.0 | -84 | UPDATED |
| 1442 | STABIZOL DSR | `AC2604005C` | 2028-03-31 | 10 | 114.0 | 219.0 | +105 | UPDATED |
| 1620 | NACDOL | `CO-306` | 2028-04-30 | 1 | 31.0 | 26.0 | -5 | UPDATED |
| 1831 | BONEFILL PLUS | `CSD-26084` | 2028-03-31 | 10 | 190.0 | 160.0 | -30 | UPDATED |
| 1742 | XONE | `261800390` | 2029-03-31 | 1 | 17.0 | 16.0 | -1 | UPDATED |
| 1625 | PROTONIX DSR | `C-26056` | 2028-06-30 | 10 | 768.0 | 591.0 | -177 | UPDATED |
| 951 | BIO D3 PLUS | `14261266A` | 2029-02-28 | 15 | 70.0 | 50.0 | -20 | UPDATED |
| 1328 | KENACORT 40 1ML | `NCM0072` | 2029-03-31 | 1 | 8.0 | 5.0 | -3 | UPDATED |
| 1120 | OPOX 100DT | `HH2510532` | 2027-09-30 | 10 | 90.0 | 85.0 | -5 | UPDATED |
| 1345 | PANTIN L | `2GC26434A` | 2028-03-31 | 10 | 69.0 | 59.0 | -10 | UPDATED |
| 1733 | SIGNOFLAM | `UC01215` | 2028-04-30 | 10 | 74.0 | 44.0 | -30 | UPDATED |
| 1796 | EFEREM SP | `CGT-26065A` | 2027-12-31 | 10 | 2.0 | 0.0 | -2 | UPDATED |
| 1872 | GABAKING-NT | `T26D205B` | 2028-03-31 | 10 | 16.0 | 11.0 | -5 | UPDATED |
| 1683 | RELVIT | `NSA1028` | 2027-12-31 | 1 | 7.0 | 3.0 | -4 | UPDATED |
| 1610 | GEMCAL P | `GPS26010C` | 2027-11-30 | 1 | 9.0 | 8.0 | -1 | UPDATED |
| 1739 | ENDOFLAM SP | `SGT-60437` | 2028-09-30 | 10 | 342.0 | 275.0 | -67 | UPDATED |
| 1804 | CALCIRET-D3 | `D261913B` | 2028-05-31 | 4 | 96.0 | 92.0 | -4 | UPDATED |
| 1689 | STASHPAIN | `142` | 2027-09-30 | 1 | 3.0 | 2.0 | -1 | UPDATED |
| 1819 | TRYLIQ-P | `ANR02ACB` | 2028-03-31 | 15 | 155.0 | 90.0 | -65 | UPDATED |
| 1016 | TROPINE AMP | `SMO38136` | 2027-06-30 | 1 | 5.0 | 1.0 | -4 | UPDATED |
| 1066 | INTRACATH 20 | `4099025F` | 2030-05-31 | 1 | 6.0 | 4.0 | -2 | UPDATED |
| 1538 | CHYMORAL AP | `26S2GTB445` | 2028-04-30 | 10 | 74.0 | 22.0 | -52 | UPDATED |
| 1843 | CORCIUM FIT | `26PLN009` | 2028-05-31 | 15 | 193.0 | 20.0 | -173 | UPDATED |
| 1802 | TOFAKIN ER 11 | `T25019OP` | 2027-04-30 | 10 | 105.0 | 90.0 | -15 | UPDATED |
| 1859 | CALDIKIND 60K NANO | `D9CWZ012` | 2027-12-31 | 1 | 5.0 | 4.0 | -1 | UPDATED |
| 1738 | PANTORET DSR | `LC-8615` | 2028-04-30 | 10 | 143.0 | 88.0 | -55 | UPDATED |
| 1762 | TOPIROXO 20 | `TOT25004SH` | 2027-11-30 | 10 | 100.0 | 70.0 | -30 | UPDATED |
| 1720 | TROYCOBAL SR | `2CZ26005` | 2027-10-31 | 10 | 36.0 | 31.0 | -5 | UPDATED |
| 958 | DEXONA | `NB00345A` | 2027-11-30 | 1 | 19.0 | 18.0 | -1 | UPDATED |
| 1867 | DOXOFINE-100 | `MNT07825` | 2028-01-31 | 10 | 380.0 | 355.0 | -25 | UPDATED |
| 1818 | DEF-Z | `HCL6442A` | 2028-04-30 | 10 | 223.0 | 209.0 | -14 | UPDATED |
| 1406 | STASHCAL CT | `1400626D` | 2028-05-31 | 10 | 120.0 | 110.0 | -10 | UPDATED |
| 1810 | LIGAMOVE | `VH-T18511` | 2027-08-31 | 10 | 40.0 | 3.0 | -37 | UPDATED |
| 1884 | CALTONIC | `07CLT26-20` | 2027-12-31 | 10 | 230.0 | 211.0 | -19 | UPDATED |
| 1200 | ANAWIN 0.25% | `107153` | 2029-05-31 | 1 | 1.0 | 0.0 | -1 | UPDATED |
| 1654 | RABLESS L | `LGQ06/083/07` | 2027-11-30 | 10 | 224.0 | 175.0 | -49 | UPDATED |
| 1800 | PREGABA D | `CTE3N002` | 2028-04-30 | 10 | 171.0 | 120.0 | -51 | UPDATED |
| 1846 | LIMCEE | `LBR26631` | 2028-04-30 | 15 | 45.0 | 30.0 | -15 | UPDATED |
| 1436 | SOLOPOSE 0.25 MD | `K15Z001` | 2028-03-31 | 10 | 117.0 | 115.0 | -2 | UPDATED |
| 1097 | PLACIDA | `D65Z008` | 2027-10-31 | 10 | 120.0 | 111.0 | -9 | UPDATED |
| 1047 | POVI 15GM | `POOX26G013` | 2028-06-30 | 1 | 32.0 | 31.0 | -1 | UPDATED |
| 1538 | CHYMORAL AP | `26S2GTB950` | 2028-06-30 | 10 | 200.0 | 194.0 | -6 | UPDATED |
| 1821 | PREGABENZ-M | `PS15AA091` | 2027-08-31 | 10 | 1.0 | 7.0 | +6 | UPDATED |
| 1745 | NERVMAX D | `FBAF2603` | 2028-05-31 | 10 | 0.0 | 6.0 | +6 | NEW_INSERTED |
| 1655 | L-CIN 250 | `JC01646` | 2028-05-31 | 10 | 0.0 | 200.0 | +200 | NEW_INSERTED |
| 1328 | KENACORT 40 1ML | `NCM0144` | 2029-06-30 | 1 | 0.0 | 8.0 | +8 | NEW_INSERTED |
| 1844 | PANTOCID DSR | `GTH1939A` | 2028-05-31 | 15 | 0.0 | 110.0 | +110 | NEW_INSERTED |
| 1743 | BONULTRA | `CUM02ACB` | 2028-07-31 | 10 | 0.0 | 120.0 | +120 | NEW_INSERTED |
| 1443 | STAMIN PLUS | `ST-2606` | 2028-01-31 | 10 | 0.0 | 240.0 | +240 | NEW_INSERTED |
| 1691 | NASO B12 | `1X26004` | 2028-01-31 | 1 | 0.0 | 11.0 | +11 | NEW_INSERTED |
| 1646 | ARTHRASPAZ 4MG | `CUM03ADB` | 2028-07-31 | 10 | 0.0 | 50.0 | +50 | NEW_INSERTED |
| 1550 | TRAMAGOLD | `ST26-1050` | 2028-02-29 | 10 | 0.0 | 16.0 | +16 | NEW_INSERTED |
| 1846 | LIMCEE | `LBR26738` | 2028-05-31 | 15 | 0.0 | 120.0 | +120 | NEW_INSERTED |
| 1859 | CALDIKIND 60K NANO | `D9CWZ014` | 2028-01-31 | 1 | 0.0 | 22.0 | +22 | NEW_INSERTED |
| 1873 | ZERODOL MR | `GGG0426005` | 2028-05-31 | 10 | 0.0 | 50.0 | +50 | NEW_INSERTED |
| 1885 | MERSILK NW 5010 | `V2010` | 2027-10-31 | 1 | 0.0 | 1.0 | +1 | NEW_INSERTED |

### Treatment of Stock Adjustments
- In legacy PharmaWinner, stock adjustments (`stockadjustmentvh` and `stockadjustmentvhdetail`) directly modify `stockbalance.CBqty`.
- Because the refresh engine blindly overwrote `stock_batches.stock_qty` from `stockbalance.CBqty`, it imported the net effect of legacy adjustments, but simultaneously wiped out any adjustments or transactions recorded natively in the target system.
- **Required Architectural Fix:** The stock synchronization logic must compute incremental movement deltas between Dump 1 and Dump 2 (`delta = CBqty_Dump2 - CBqty_Dump1`) and apply `stock_qty = stock_qty + delta`, preserving native transactions.

### Supplier and Customer Party Balances
- **Suppliers:** All 85 mapped suppliers audited. Outstanding invoice totals reconcile to purchases and payments.
- **Customers:** Mapped debtor ledgers audited. Native receipt of ₹300.00 is preserved.

---

## Issue 6: Test Suite Status & Architectural Reality

### Project Test Runner (`run_tests.py`) Analysis
An inspection of `run_tests.py` reveals the following implementation detail at lines 34–47:
```python
    source_db = root / "data" / "pharmacy.db"
    # Always clones data/pharmacy.db regardless of PHARMACY_DB environment variable!
    source = sqlite3.connect(f"file:{source_db.resolve().as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(staging_db)
    source.backup(target)
    os.environ["PHARMACY_DB"] = str(staging_db)
```
- `run_tests.py` unconditionally clones `data/pharmacy.db` to a temporary database, regardless of any inherited `PHARMACY_DB` environment variable.
- Therefore, claims that `python run_tests.py` validated the staging database (`staging/pharmacy_staging_refresh.db`) were technically inaccurate. The test suite has only ever run against `data/pharmacy.db`.
- Furthermore, pre-existing tests in `test_account_roles.py` fail due to role/fixture expectations in the test runner that are unrelated to migration.

---

## Final Verdict & Promotion Gate

### Promotion Gate: **BLOCKED**

In strict accordance with the project safety protocols:
1. **Staging is NOT promoted to `data/pharmacy.db`.**
2. **`data/pharmacy.db` remains 100% untouched and secure.**
3. **The packaged EXE will NOT be rebuilt.**

### Prerequisites for Unblocking Promotion:
1. **Refactor Step 5 of `tools/legacy_refresh_engine.py`:**
   Replace absolute closing-balance updates (`SET stock_qty = CBqty`) with delta calculations (`stock_qty = stock_qty + (CBqty_dump2 - CBqty_dump1)`).
2. **Verify Batch `CGT26065C` Preserves Native Purchase:** Stock must equal 394 loose units (or 154 + 240 native purchase + legacy delta), never 184.
3. **Verify Batch `AC2604005C` Preserves Native Sale:** Native sale deduction of 1 loose unit must remain.
4. **Re-run Refresh on Fresh Staging Clone** and verify all 5 reconciliations pass before requesting user approval to promote.
