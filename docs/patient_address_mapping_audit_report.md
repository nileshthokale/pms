# Patient Name and Address Mapping Data Audit & Forensic Report

**Date:** 2026-10-23  
**Status:** Audit Complete — Pending User Review Prior to Write Operations  
**Reference Source:** `PharmaWinner202610231351.sql` (35.5 MB SQL dump)  
**Target Active Database:** `data/pharmacy.db` (45.3 MB SQLite database)  
**Deliverables:**
- Audit CSV: [`migration_backups/patient_address_mapping_audit.csv`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy%20Management%20System/migration_backups/patient_address_mapping_audit.csv) (23,496 patient rows)
- Reviewable Correction Tool: [`tools/correct_patient_address_mapping.py`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy%20Management%20System/tools/correct_patient_address_mapping.py)
- Automated Regression Test Suite: [`test_patient_address_mapping_and_schedule_h1.py`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy%20Management%20System/test_patient_address_mapping_and_schedule_h1.py)

---

## 1. Executive Summary

A forensic data audit was conducted to resolve why patient addresses fail to appear on sales reports (specifically the **Sales Item / Schedule H1 reports**).

### Key Findings
1. **Pharma-WINNER Patient Storage:** In the legacy Pharma-WINNER system, the master table `patientmaster` was **completely unused (0 rows)**. Patient names and addresses were stored directly on sales transactions in `salesvhheader.PatientName` and `salesvhheader.PatientAddress`.
2. **Migration Data Gap:** When `salesvhheader` was migrated to the new SQLite database (`sales_invoices`), only `PatientName` was imported into `sales_invoices.patient_name`. `sales_invoices` has no address column, and `salesvhheader.PatientAddress` was never migrated into any table.
3. **Empty Dedicated Address Table:** The dedicated patient lookup table `patient_addresses` was seeded strictly from the 29 account ledger customers in `customers` table (yielding only **24 records**). The 23,212 retail pharmacy patients were never populated.
4. **Schedule H1 Report Breakdown:** Schedule H1 queries `sales_invoices` and attempts a `LEFT JOIN patient_addresses pa ON UPPER(TRIM(pa.patient_name)) = UPPER(TRIM(si.patient_name))` with fallback to `customers.address`. Because `patient_addresses` is missing 99.9% of patients and retail sales use walk-in customer ID 159 (which has no address), **15,267 out of 15,319 Schedule H1 sales (99.66%) currently display blank addresses**.
5. **Cartesian Product Vulnerability:** 1,741 patients have multiple addresses across historical visits (e.g. spelling variants or different village locations). A naive `LEFT JOIN` on `patient_addresses` would duplicate sales item rows in the report.

---

## 2. Schema Comparison & Data Flow Analysis

### 2.1 Old Pharma-WINNER Schema
- **`salesvhheader`** (72,211 rows):
  - `ID`: Primary key integer (e.g. 10, 11, ..., 72347).
  - `PatientName` (varchar(50)): Patient name string.
  - `PatientAddress` (varchar(50)): Patient village / residential address string. 53,926 sales have non-empty addresses.
  - `CustID`: Foreign key to `ledger.ID` (159 = Walkin, or specific customer ledger).
  - `DoctID`: Foreign key to `doctormst.ID`.
- **`patientmaster`** (0 rows): Unused in legacy system.

### 2.2 New SQLite Schema (`data/pharmacy.db`)
- **`sales_invoices`** (72,194 rows):
  - Columns: `id`, `bill_no`, `sale_date`, `sale_time`, `sale_type`, `customer_id`, `patient_name`, `doctor_id`, `discount`, `paid_amount`, `total_amount`, `round_off`, `net_amount`, `remarks`.
  - Does **not** contain an address column.
- **`patient_addresses`** (24 rows):
  - Columns: `id`, `patient_name` (TEXT NOT NULL COLLATE NOCASE), `address` (TEXT NOT NULL), `customer_id` (INTEGER REFERENCES customers(id)), `updated_at` (TEXT), `UNIQUE(patient_name, address)`.
  - Intended by the application architecture to store all `patient_name -> address` mappings for Counter Sale autocompletion and schedule reporting.
- **`customers`** (29 rows):
  - Contains only ledger accounts (WALKIN + 28 credit ledger customers).
- **`legacy_id_map`**:
  - `entity = 'sale'`: Exactly maps every legacy `salesvhheader.ID` to `sales_invoices.id`.

### 2.3 Report Data Flow (`ScheduleReportsDAO.get_sales_schedule`)
```mermaid
flowchart TD
    SI[sales_invoices] -->|patient_name| JOIN[LEFT JOIN patient_addresses]
    C[customers] -->|fallback address| JOIN
    PA[patient_addresses (Only 24 rows)] -->|Match fails for 99.6% of patients| JOIN
    JOIN -->|Empty Address| H1[Schedule H1 Report Page]
```

---

## 3. Forensic Population Breakdown

An exhaustive analysis of all 72,211 historical sales records in `PharmaWinner202610231351.sql` reveals:

| Category | Count | Percentage | Description | Resolution Strategy |
|---|---|---|---|---|
| **Consistent Single-Address Patients** | **21,471** | **92.50%** | Patient has exactly one unambiguous address across all historical sales. | Insert into `patient_addresses` with 100% confidence. |
| **Dominant-Address Patients** | **487** | **2.10%** | Patient has a primary address used in $\ge 75\%$ of visits (e.g. 22 of 24 visits). | Insert primary address as dominant/most recent; store variants for autocomplete. |
| **Split-Address Patients** | **1,254** | **5.40%** | Patient visited from 2 or more different locations (e.g. common names or relocated patients). | Insert distinct pairs into `patient_addresses`; windowed join selects latest visit address. |
| **No Address Recorded** | **284** | **1.21%** | Historical sale records had no address entered. | Leave blank; never invent or infer addresses. |
| **Existing SQLite Matches** | **15** | **0.06%** | Already present in `patient_addresses` and matches historical source. | Retain existing record unchanged. |
| **Ledger vs Retail Discrepancies** | **6** | **0.03%** | Credit customer ledger address differs slightly from retail walk-in visit address. | Documented in audit CSV for review. |

### The 6 Ledger vs Retail Discrepancies
1. **MR BHAUSAHEB BHUJADI:** Ledger address = `MUSALWADI`, Retail sales address = `RAHURI` (5 of 5 visits).
2. **MR DATTA BELHEKAR:** Ledger address = `sonai belhekarwadi`, Retail sales address = `SONAI` (2 of 3 visits).
3. **MR GORAKSHANTH NIMSE:** Ledger address = `RAHU`, Retail sales address = `KALE AKHA` (1 visit).
4. **MR NANASAHEB MANE:** Ledger address = `MAHADUK CENTAR`, Retail sales address = `MAHADUK CENT` (31 of 31 visits).
5. **MR PRADIP BHUJADI:** Ledger address = `MUSLWADI` (typo), Retail sales address = `MUSALWADI` (2 of 2 visits).
6. **MRS SUNDARBAI GHORPADE:** Ledger address = `WARALE WASTI`, Retail sales address = `RAHURI` (1 visit).

---

## 4. Impact on Schedule H1 Reporting

Across all **15,319** sales invoices containing Schedule H1 items:

| Metric | Current State | Proposed Corrected State | Delta |
|---|---|---|---|
| **H1 Invoices with Address** | **52 (0.34%)** | **15,090 (98.51%)** | **+15,038 invoices resolved** |
| **H1 Invoices Missing Address** | **15,267 (99.66%)** | **229 (1.49%)** | Only genuine blanks in source |
| **Row Duplication Risk** | High (if unwindowed) | **0% (Deduplicated Join)** | Guaranteed 1-to-1 row preservation |

---

## 5. Proposed Correction Architecture & Safety Gates

### 5.1 Strictly Limited Scope
In accordance with mandatory safety rules:
- **No modification to `sales_invoices`:** Bill numbers, quantities, dates, times, amounts, items, and primary keys remain 100% untouched.
- **No modification to Stock, Batches, Accounting, or Ledgers.**
- **Safe population of `patient_addresses`:** Inserts verified `(patient_name, address, customer_id, updated_at)` records from the reference export.
- **Deduplicated Report Join in [`database/schedule_reports_dao.py`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy%20Management%20System/database/schedule_reports_dao.py):**
  ```sql
  LEFT JOIN (
      SELECT patient_name, address
      FROM (
          SELECT patient_name, address,
                 ROW_NUMBER() OVER (
                     PARTITION BY UPPER(TRIM(patient_name))
                     ORDER BY updated_at DESC, id DESC
                 ) as rn
          FROM patient_addresses
      ) WHERE rn = 1
  ) pa ON UPPER(TRIM(pa.patient_name)) = UPPER(TRIM(si.patient_name))
  ```

### 5.2 Verification Script Safety Protocol ([`tools/correct_patient_address_mapping.py`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy%20Management%20System/tools/correct_patient_address_mapping.py))
1. **Pre-Correction Backup:** Creates atomic SQLite backup in `migration_backups/pre_patient_address_correction_<timestamp>.db` and records pre-change SHA-256 hash.
2. **Transactional Integrity:** Runs under `BEGIN IMMEDIATE` transaction.
3. **Post-Write Assertions:**
   - `PRAGMA integrity_check` must return `ok`.
   - `PRAGMA foreign_key_check` must return 0 violations.
   - `sales_invoices` row count must equal exactly 72,194.
   - Any failure triggers immediate automatic rollback.

---

## 6. Verification Status

1. **Dry-Run Validated:** [`tools/correct_patient_address_mapping.py`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy%20Management%20System/tools/correct_patient_address_mapping.py) was executed in dry-run mode:
   - Extracted 23,212 unique patient names across 72,211 sales.
   - Identified 25,791 verified patient address pairs to insert.
   - Confirmed 0 modifications to `data/pharmacy.db`.
2. **Automated Tests Validated:** [`test_patient_address_mapping_and_schedule_h1.py`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy%20Management%20System/test_patient_address_mapping_and_schedule_h1.py) passes 5/5 tests in 1.19s, confirming deduplication, fallback, and zero-row-duplication invariants.
3. **Schedule Reports Suite:** All 13 tests in [`test_schedule_reports.py`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy%20Management%20System/test_schedule_reports.py) pass cleanly.
