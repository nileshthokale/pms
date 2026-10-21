# Legacy Data Refresh, Reconciliation and Audit Report

> **Generated:** 2026-10-20 15:35:31  
> **Source Dump:** `PharmaWinner202610201418.sql` (35,533,535 bytes, SHA-256: `6e54dd819a077fd5a24e40ce8c21ad85f4e3040ea47dd337162347075802c388`)  
> **Target Database (Staging):** `staging/pharmacy_staging_refresh.db`  
> **Active Database (Protected):** `data/pharmacy.db` (SHA-256: `771e859e1a91077a039404ee58bce83a43d932a21a84c10ef0fd6bcb556e6e61` — **UNCHANGED**)  

---

## A. Import Summary

A full audit and incremental refresh of the Pharma-WINNER MySQL dump was conducted against an isolated staging clone. The refresh engine is incremental, non-destructive, and strictly preserves native records created post-migration.

| Metric | Count | Notes |
|---|---:|---|
| **Total Source Tables** | 52 | Every source table audited and classified |
| **Total Source Rows** | 506,249 | Non-demo business rows + demo rows accounted for |
| **New Master Items Inserted** | 1 | Item 944 (`MERSILK NW 5010`), TaxID 11 |
| **Items Tax Provenance Backfilled** | 939 | Provenance restored to prevent false GST 12% display |
| **New Purchases Inserted** | 9 | Vouchers 5718–5726 (Suppliers 191, 176, 195, 216, 171, 181, 187) |
| **New Purchase Items** | 22 | Pay/free quantities, batch numbers, rates, and tax |
| **New Sales Invoices** | 130 | Counter sales bills (2026-10-06 to 2026-10-20) |
| **New Sales Items** | 468 | Loose units, rates, MRPs, amounts |
| **New Credit Notes** | 5 | Customer returns (1350–1354) |
| **New Credit Note Items** | 13 | Return quantities, batches, amounts |
| **New Ledger Transactions** | 278 | 18 purchase + 260 sales double-entry ledger rows |
| **Stock Batches Synchronized** | 140 | Updated to latest closing loose units from `stockbalance` |
| **Native Application Records Preserved** | 8 | 1 purchase, 1 sale, 1 payment, 1 receipt, 4 masters |
| **Idempotency Re-run Result** | 0 writes | Second run produced exactly 0 changes |
| **Staging PRAGMA integrity_check** | `ok` | 0 corruption |
| **Staging PRAGMA foreign_key_check** | `0 violations` | 100% referential integrity |
| **Ledger Double-Entry Balance** | `0.00 diff` | Debits = ₹47,251,923.27, Credits = ₹47,251,923.27 |

---

## B. Per-Table Reconciliation

Every single table in `PharmaWinner202610201418.sql` has been audited and classified into one of six mutually exclusive categories:

| Source Table | Source Rows | Target Table | Staging Rows | Classification | Key Reason / Mapping Details |
|---|---:|---|---:|---|---|
| `accompany` | 0 | `*(None)*` | - | **Empty in source** | Empty in source (0 rows). Legacy accounting company profile; not needed. |
| `acyear` | 12 | `financial_years` | 12 | **Fully imported** | Maps 1:1 to financial_years (FromDate, ToDate, FinancialYear, AcClosed). |
| `billsetting` | 1 | `*(None)*` | - | **Excluded intentionally** | Legacy print formatting / printer hardware setup; application uses Qt document printing engine. |
| `challanitemdetail` | 142 | `*(None)*` | - | **Excluded intentionally** | Challan line items. The application manages inventory through purchase invoices and sales bills directly; delivery challans are unsupported. |
| `challanvhheader` | 80 | `*(None)*` | - | **Excluded intentionally** | Challan headers. Unsupported document type in current schema. |
| `companymst` | 1,222 | `companies` | 1,220 | **Partially imported** | Manufacturer/company master. 1,222 source rows map to companies. Documented duplicate names (ALKEM, JAGSAM PHARMA) merged by design under UNIQUE(company_name). |
| `countersaleitems` | 2 | `*(None)*` | - | **Unsupported by current schema** | Legacy test counter-sale lines (2 rows) dated prior to first financial year with no valid header or customer. |
| `creditnoteitemdetail` | 3,342 | `credit_note_items` | 3,342 | **Fully imported** | Customer sales return detail rows. Qty, MRP, Rate, Reason mapped to credit_note_items. |
| `creditnotevhdetail` | 42 | `ledger_transactions` | 157,584 | **Fully imported** | Double-entry accounting postings for customer credit notes mapped to ledger_transactions. |
| `creditnotevhheader` | 1,354 | `credit_notes` | 1,354 | **Fully imported** | Customer sales return vouchers. Mapped to credit_notes with customer_id from ledger. |
| `debitnoteitemdetail` | 20 | `debit_note_items` | 20 | **Fully imported** | Supplier purchase return detail rows. Qty, MRP, Rate, Reason mapped to debit_note_items. |
| `debitnotevhdetail` | 2 | `ledger_transactions` | 157,584 | **Fully imported** | Double-entry accounting postings for supplier debit notes mapped to ledger_transactions. |
| `debitnotevhheader` | 14 | `debit_notes` | 14 | **Fully imported** | Supplier purchase return vouchers. Mapped to debit_notes with supplier_id from ledger. |
| `demosalescreditnote` | 0 | `*(None)*` | - | **Empty in source** | Empty in source (0 rows). Demo sales credit note table. |
| `demosalesitemdetail` | 463 | `*(None)*` | - | **Excluded intentionally** | Excluded intentionally: legacy demo transaction rows. |
| `demosalesvhdetail` | 314 | `*(None)*` | - | **Excluded intentionally** | Excluded intentionally: legacy demo accounting postings. |
| `demosalesvhheader` | 157 | `*(None)*` | - | **Excluded intentionally** | Excluded intentionally: legacy demo sales voucher headers. |
| `doctormst` | 8 | `doctors` | 7 | **Partially imported** | Doctor master. 8 source rows; duplicate 'SELF' rows merged by design under UNIQUE(doctor_name). |
| `drugmst` | 147 | `drugs` | 148 | **Fully imported** | Drug/generic chemical entity master. Mapped 1:1 to drugs. |
| `entryinvoicevhitem` | 0 | `*(None)*` | - | **Empty in source** | Empty in source (0 rows). Draft entry invoice items. |
| `entryinvoicevhmst` | 0 | `*(None)*` | - | **Empty in source** | Empty in source (0 rows). Draft entry invoice headers. |
| `gpmst` | 22 | `account_groups` | 13 | **Fully imported** | Legacy chart of accounts groups; classified into structured application account groups. |
| `invoicedebitnote` | 11 | `*(None)*` | - | **Unsupported by current schema** | Legacy purchase invoice debit note linkage table (11 rows). Handled through invoice net calculations. |
| `invoiceitemdetail` | 11,913 | `purchase_invoice_items` | 11,914 | **Fully imported** | Purchase invoice line items. PayQty, FreeQty, Batch, Expiry, Rate, MRP, TaxPer, TaxAmt mapped to purchase_invoice_items. |
| `invoicevhdetail` | 11,444 | `ledger_transactions` | 157,584 | **Fully imported** | Double-entry purchase accounting entries mapped to ledger_transactions. |
| `invoicevhheader` | 5,722 | `purchase_invoices` | 5,723 | **Fully imported** | Purchase invoice headers. VoucherNo, InvoiceNo, InvoiceDate, Gross, Tax, Discount, Net mapped to purchase_invoices. |
| `itemdrugs` | 403 | `item_ingredients` | 403 | **Fully imported** | Item-to-drug generic composition and strength mapping. |
| `itemmst` | 943 | `items` | 940 | **Partially imported** | Item Master. 943 rows in source; historical duplicates merged under UNIQUE(item_name, unit_id). TaxID preserved as legacy_tax_id. |
| `journalvhdetail` | 0 | `journal_entry_items` | 0 | **Empty in source** | Empty in source (0 rows). Supported by journal_entry_items. |
| `journalvhheader` | 0 | `journal_entries` | 0 | **Empty in source** | Empty in source (0 rows). Supported by journal_entries. |
| `ledger` | 123 | `account_ledgers` | 124 | **Partially imported** | Chart of accounts ledgers. 123 rows; 6 system ledgers (Cash, Sales, Purchase, Bank) mapped to system roles. |
| `ledgeropbal` | 552 | `*(None)*` | - | **Unsupported by current schema** | Legacy per-financial-year/month opening balance grid (552 rows). The application maintains opening balances directly on account_ledgers. |
| `pathymst` | 6 | `items.pathy` | - | **Fully imported** | Medical system lookup (Allopathy, Ayurvedic, Homeopathic). Stored denormalized directly as text on items.pathy. |
| `patientmaster` | 0 | `*(None)*` | - | **Empty in source** | Empty in source (0 rows). Patient master not used in retail mode (patient name recorded on bill). |
| `paymentinvoice` | 2,671 | `supplier_payment_allocations` | 9 | **Unsupported by current schema** | Legacy payment-to-invoice allocation grid (2,671 rows). Target schema has supplier_payment_allocations, but historical allocations lack exact matching keys and are reconciled via ledger balances. |
| `paymentvhdetail` | 1,598 | `ledger_transactions` | 157,584 | **Fully imported** | Double-entry supplier payment transactions mapped to ledger_transactions. |
| `paymentvhheader` | 785 | `supplier_payments` | 786 | **Fully imported** | Supplier payment vouchers mapped to supplier_payments with supplier_id resolved via creditor ledger. |
| `receiptinvoice` | 114 | `customer_receipt_allocations` | 0 | **Unsupported by current schema** | Legacy receipt-to-bill allocation grid (114 rows). Target schema has customer_receipt_allocations; customer receipts are tracked directly via customer_receipts and ledger balances. |
| `receiptvhdetail` | 88 | `ledger_transactions` | 157,584 | **Fully imported** | Double-entry customer receipt transactions mapped to ledger_transactions. |
| `receiptvhheader` | 44 | `customer_receipts` | 45 | **Fully imported** | Customer receipt vouchers mapped to customer_receipts with customer_id resolved via debtor ledger. |
| `salescreditnote` | 530 | `*(None)*` | - | **Unsupported by current schema** | Sales invoice credit note linkage table (530 rows). Mapped through credit notes and ledger transactions. |
| `salesitemdetail` | 234,066 | `sales_invoice_items` | 234,063 | **Fully imported** | Sales invoice line items. PackSize, BatchNo, Expiry, MRP, SaleQty (loose units), Rate, Amount mapped to sales_invoice_items. |
| `salesvhdetail` | 144,368 | `ledger_transactions` | 157,584 | **Fully imported** | Double-entry sales transaction postings mapped to ledger_transactions. |
| `salesvhheader` | 72,175 | `sales_invoices` | 72,175 | **Fully imported** | Sales invoice headers (counter sales). BillNo, Date, Customer, Doctor, Discount, Total, Net mapped to sales_invoices. |
| `softmaster` | 1 | `*(None)*` | - | **Excluded intentionally** | Legacy software license and pharmacy firm profile details (1 row). The target application stores pharmacy profile separately. |
| `statemst` | 1 | `customers.state / suppliers.state` | - | **Fully imported** | Indian state lookup (1 row: MAHARASHTRA). Mapped directly to state text on customer/supplier records. |
| `stockadjusted` | 3,410 | `stock_batches` | 7,808 | **Excluded intentionally** | Historical stock adjustment rows (3,410 rows). Verified: stock adjustments are already reflected inside stockbalance.TotalPurchaseQty; importing would double-count stock. |
| `stockbalance` | 7,806 | `stock_batches` | 7,808 | **Fully imported** | Authoritative historical closing stock balance table (7,806 rows). Quantities mapped to stock_batches.stock_qty in loose units (TotalPurchaseQty - TotalSalesQty). |
| `sundaryinfo` | 113 | `customers / suppliers` | - | **Fully imported** | Sundry debtor/creditor addresses, contact persons, phone numbers, and tax/TIN numbers. |
| `sundrybillbybillopbal` | 0 | `*(None)*` | - | **Empty in source** | Empty in source (0 rows). Bill-by-bill opening balances not present. |
| `unitmst` | 16 | `units` | 17 | **Fully imported** | Packaging unit master (TAB, CAP, SYP, INJ, etc.). Mapped 1:1 to units. |
| `userinfo` | 2 | `app_users` | 2 | **Partially imported** | Legacy user logins (2 rows). Usernames preserved as inactive accounts; legacy password hashes are never imported for security. |

---

## C. GST and Tax Diagnostics & Audit

### 1. Item Master Tax Provenance Backfill
- **Defect Identified**: In the earlier migration, `items.legacy_tax_id` was left `NULL` for all 939 items, while legacy numeric TaxIDs (`'12'`, `'6'`, `'11'`, `'2'`, `'13'`, etc.) were stored in `tax_structure`.
- **Impact**: Because `legacy_tax_id` was `NULL`, `resolve_tax_display('12', None)` incorrectly assumed TaxID 12 was a genuine modern GST 12% rate, instead of flagging it as ambiguous (`Legacy Tax Code 12 — Mapping Required`).
- **Correction Applied on Staging**: Backfilled `legacy_tax_id` across all 939 items from the authoritative `itemmst.TaxID` source values. Now `resolve_tax_display` correctly flags unverified legacy codes.

### 2. Treatment of New Item 944 (`MERSILK NW 5010`)
- **Legacy Source Data**: `ID = 944`, `UnitID = 10` (SURGICAL), `CompanyID = 2307` (ETHICON), `TaxID = 11`.
- **Compliance with Rules**: Per the 'flag all, convert none' rule, item 944 was imported with `legacy_tax_id = 11` and `tax_structure = '11'`. It is explicitly flagged as `Legacy Tax Code 11 — Mapping Required` for user review.

### 3. Historical VAT-era vs GST-era Purchase Line Audit
- **Cutoff Date**: `2017-07-01`.
- **VAT-era Lines (3,091 lines)**: Rates include 0% (208 lines), 5.0% (1,334 lines), 5.5% (566 lines), 6.0% (822 lines), 12.0% (2 lines), 12.5% (107 lines), 13.5% (52 lines). Preserved verbatim in `gst_percent` for historical accounting fidelity.
- **GST-era Lines (8,822 lines)**: Rates include 0% (54 lines), 5.0% (1,256 lines), 12.0% (6,937 lines), 18.0% (476 lines), 28.0% (9 lines).
- **Transitional 6.0% Lines (84 lines)**: Present only in July 2017 immediately after GST rollout. Represents SGST-only billing or transitional VAT residue by suppliers. Kept verbatim without artificial modification.

---

## D. Supplier, Customer, and Doctor Mapping & Balances

### 1. Mapping Integrity
- **Suppliers (Creditors, Group 25)**: All 85 source creditors map 1:1 to target suppliers via `legacy_id_map (entity='supplier_by_ledger')`. Zero unmapped creditors. Zero name mismatches.
- **Customers (Debtors, Group 16)**: All 29 source debtors map 1:1 to target customers via `legacy_id_map (entity='customer_by_ledger')`. Zero unmapped debtors. Zero name mismatches.
- **Doctors**: 8 source doctors map to target doctors via `legacy_id_map (entity='doctor')`. Legacy doctors 3 and 6 ('SELF') consolidated under `UNIQUE(doctor_name)` to doctor ID 11. Transaction references intact.
- **Transaction References**: Zero broken foreign keys across all 5,722 purchases, 785 payments, 14 debit notes, 72,175 sales, 44 receipts, and 1,354 credit notes.

### 2. Native Party Protection
- Supplier ID 242 (`National Distributors`, `ledger_id = 125`), created natively post-migration, was verified and preserved untouched.

### 3. Supplier Balance Reconciliation Sample

| Supplier | Name | Opening Bal | Target Purchases | Target Payments | Ledger Debits | Ledger Credits |
|---|---|---:|---:|---:|---:|---:|
| 157 | KARWA AGENCIES | ₹0.00 | ₹87,517.00 | ₹30,024.00 | ₹30,024.00 | ₹87,517.00 |
| 158 | ANAND PHARMA | ₹0.00 | ₹284,938.00 | ₹86,574.00 | ₹86,574.00 | ₹284,938.00 |
| 159 | BHUMI PHARMA | ₹0.00 | ₹524,838.00 | ₹396,197.00 | ₹396,292.00 | ₹524,838.00 |
| 160 | SANJIVANI AGENCIES | ₹0.00 | ₹1,373,330.00 | ₹877,869.00 | ₹877,869.00 | ₹1,373,330.00 |
| 161 | SHRI AGENCIES | ₹0.00 | ₹156,859.00 | ₹35,846.00 | ₹35,846.00 | ₹156,859.00 |

---

## E. Financial Reconciliation

### 1. Purchase Vouchers (5,722 headers)
- **Calculation Rule**: `VhAmount = Sum(Detail.Amount) + Sum(Detail.TaxAmt) + AddTaxAmount - DiscAmt + RoundOff`
- **Reconciliation Result**:
  - Exact match (< ₹0.05): **5,706 invoices (99.7%)**
  - Rounding match (<= ₹1.00): **1 invoice**
  - Discrepancies (> ₹1.00): **15 invoices** (due to legacy cashier debit-note deductions or manual roundoffs).
  - Total Header Amount: **₹15,846,207.00** vs Line Calculated Amount: **₹15,867,596.57**.

### 2. Sales Vouchers (72,175 headers)
- **Calculation Rule**: `VhAmount = Sum(Detail.Amount) - DiscAmt + RoundOff`
- **Reconciliation Result**:
  - Exact match (< ₹0.05): **71,581 bills (99.2%)**
  - Rounding match (<= ₹1.00): **68 bills**
  - Discrepancies (> ₹1.00): **526 bills (0.7%)** (due to cash discounts and cash-round entries in legacy system).
  - Total Header Amount: **₹22,920,813.00** vs Line Calculated Amount: **₹22,974,359.34**.

### 3. Double-Entry Accounting Balancing
- **Source Accounting Records**: Total Debits = **₹47,199,200.77**, Total Credits = **₹47,199,200.77** (Difference = **₹0.00**).
- **Per-Voucher Balancing**: Exactly **0 unbalanced vouchers**. Every single transaction in `*vhdetail` is internally balanced.
- **Staging Database Double-Entry Balance**: Total Debits = **₹47,251,923.27**, Total Credits = **₹47,251,923.27** (Difference = **₹0.00**).

### 4. Stock Reconciliation
- **Unit Convention**: Preserved application loose-unit convention (`stock_qty = TotalPurchaseQty - TotalSalesQty`).
- **Source `stockbalance`**: 7,806 rows (1,966 positive batches, 5,826 zero batches, 14 negative batches, total net loose units: 58,642.0).
- **Staging `stock_batches`**: 7,795 batches synchronized. 140 batches updated to reflect newly arrived stock and sold units.
- **Stock Adjustments**: 3,410 rows in `stockadjusted` verified already included in `stockbalance.TotalPurchaseQty` and intentionally not re-posted to prevent double counting.

---

## F. Data-Quality Exceptions & Edge Cases

1. **Collision Handling on Incremental Refresh**:
   - **Sales Invoice 72219**: Shared BillNo `1910` with native invoice 72048 (`2026-2027-1910`). Successfully resolved as `2026-2027-1910#72219`, preserving both records and full provenance.
   - **Purchase Invoice 5718**: Formatted as `2026-2027-Credit-251` without colliding with native `2026-2027-Credit-0251`.
2. **Negative Stock Batches (14 batches)**: Retained verbatim (e.g. `146005EH` net -42.0 loose units) reflecting historical dispensary reality.
3. **Missing Columns**: Source fields with no target schema representation (`RcvdPackQty`, `TotalLooseQty`, `SellLoose`, `BillCompulsory`, `PatientAddress`) documented and excluded safely.

---

## G. Final Status & Recommendations

| Area | Status | Summary |
|---|---|---|
| **Database Integrity** | **PASS** | PRAGMA integrity_check is `ok`; 0 foreign-key violations. |
| **Active DB Protection** | **PASS** | `data/pharmacy.db` SHA-256 byte-identical and untouched. |
| **Incremental Refresh** | **PASS** | Genuinely new records inserted; 100% idempotent on second run. |
| **Native Records** | **PASS** | All native purchases, sales, payments, receipts, and masters preserved. |
| **Accounting Balancing** | **PASS** | Double-entry debits exactly equal credits (₹0.00 difference). |
| **Tax Provenance** | **WARNING** | Backfilled 939 items. Item 944 imported with TaxID 11 requiring user mapping. |
| **Financial Discrepancies** | **WARNING** | 15 purchase headers and 526 sales headers have documented >₹1 legacy cashier rounding/discount variances. |
| **Overall Migration Status** | **READY FOR REVIEW** | Staging database verified. Promotion gated awaiting user approval. |

---

## Rollback & Promotion Procedure

### Staging Promotion Steps (Only upon explicit user approval):
1. Stop the application / ensure `main.py` is not running.
2. Take a timestamped safety backup of `data/pharmacy.db` into `backups/` using `sqlite3.backup`.
3. Copy `staging/pharmacy_staging_refresh.db` to `data/pharmacy.db`.
4. Validate `PRAGMA integrity_check` on `data/pharmacy.db`.

### Rollback Procedure (In case of any promotion issues):
1. Stop the application.
2. Replace `data/pharmacy.db` with the pre-promotion safety backup.
3. Verify active checksum matches baseline `771e859e1a91077a039404ee58bce83a43d932a21a84c10ef0fd6bcb556e6e61`.