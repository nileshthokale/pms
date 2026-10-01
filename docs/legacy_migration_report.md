# Legacy Data Migration Report

## Source

- File: `PharmaWinner202609142001.sql`
- Size: 35,325,237 bytes
- Format: MySQL 5.7 mysqldump (imported offline — no MySQL connection)

## Pre-migration backup

- Path: `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\data\backups\pharmacy_backup_20260918_102219.db`
- SHA-256: `93258007b42484dedab9e6eed029664b91a706c373317c3e4483dfe90329f2d8`
- Size: 42,602,496 bytes
- Validated: True (ok)

## Production database state

| Item | Before | After |
| --- | --- | --- |
| Tables | 33 | 33 |
| Size (bytes) | 42,602,496 | 42,864,640 |
| SHA-256 | `7ffc9f1eccb893fe…` | `8b22a819afe500eb…` |

| Table | Before | After |
| --- | ---: | ---: |
| account_ledgers | 123 | 123 |
| companies | 1,218 | 1,218 |
| credit_note_items | 3,318 | 3,318 |
| credit_notes | 1,345 | 1,345 |
| customer_receipts | 44 | 44 |
| customers | 29 | 29 |
| debit_note_items | 19 | 19 |
| debit_notes | 13 | 13 |
| doctors | 7 | 7 |
| drugs | 147 | 147 |
| financial_years | 12 | 12 |
| item_ingredients | 402 | 402 |
| items | 938 | 938 |
| ledger_transactions | 156,716 | 156,716 |
| purchase_invoice_items | 11,829 | 11,829 |
| purchase_invoices | 5,681 | 5,681 |
| sales_invoice_items | 232,707 | 232,707 |
| sales_invoices | 71,803 | 71,803 |
| stock_batches | 7,765 | 7,765 |
| supplier_payments | 785 | 785 |
| suppliers | 85 | 85 |
| units | 16 | 16 |

## Cleared demo/test business data

| Table | Rows removed |
| --- | ---: |
| account_ledgers | 117 |
| companies | 1,218 |
| credit_note_items | 3,318 |
| credit_notes | 1,345 |
| customer_receipts | 44 |
| customers | 29 |
| debit_note_items | 19 |
| debit_notes | 13 |
| doctors | 7 |
| drugs | 147 |
| financial_years | 12 |
| item_ingredients | 402 |
| items | 938 |
| ledger_transactions | 156,716 |
| purchase_invoice_items | 11,829 |
| purchase_invoices | 5,681 |
| sales_invoice_items | 232,707 |
| sales_invoices | 71,803 |
| stock_batches | 7,765 |
| supplier_payments | 785 |
| suppliers | 85 |
| units | 16 |

## Imported rows

| Source table | Rows | Target | Imported | Skipped |
| --- | ---: | --- | ---: | ---: |
| `acyear` | 12 | financial_years | 12 | 0 |
| `companymst` | 1,221 | companies | 1,218 | 3 |
| `unitmst` | 16 | units | 16 | 0 |
| `drugmst` | 147 | drugs | 147 | 0 |
| `doctormst` | 8 | doctors | 7 | 1 |
| `itemmst` | 941 | items | 938 | 3 |
| `itemdrugs` | 402 | item_ingredients | 402 | 0 |
| `ledger` | 123 | account_ledgers | 117 | 6 |
| `sundaryinfo` | 113 | customers / suppliers | 114 | 0 |
| `stockbalance` | 7,764 | stock_batches | 7,763 | 1 |
| `invoicevhheader` | 5,681 | purchase_invoices | 5,681 | 0 |
| `invoiceitemdetail` | 11,829 | purchase_invoice_items | 11,829 | 0 |
| `invoicevhdetail` | 11,362 | ledger_transactions | 11,362 | 0 |
| `salesvhheader` | 71,803 | sales_invoices | 71,803 | 0 |
| `salesitemdetail` | 232,707 | sales_invoice_items | 232,707 | 0 |
| `salesvhdetail` | 143,624 | ledger_transactions | 143,624 | 0 |
| `creditnotevhheader` | 1,345 | credit_notes | 1,345 | 0 |
| `creditnoteitemdetail` | 3,318 | credit_note_items | 3,318 | 0 |
| `creditnotevhdetail` | 42 | ledger_transactions | 42 | 0 |
| `debitnotevhheader` | 13 | debit_notes | 13 | 0 |
| `debitnoteitemdetail` | 19 | debit_note_items | 19 | 0 |
| `debitnotevhdetail` | 2 | ledger_transactions | 2 | 0 |
| `receiptvhheader` | 44 | customer_receipts | 44 | 0 |
| `receiptvhdetail` | 88 | ledger_transactions | 88 | 0 |
| `paymentvhheader` | 785 | supplier_payments | 785 | 0 |
| `paymentvhdetail` | 1,598 | ledger_transactions | 1,598 | 0 |

- Total imported rows: 494,994
- Total skipped rows: 14
- Demo rows excluded: 934
- Warnings: 14

## Duplicate / merged legacy records

Legacy records whose unique name already existed are merged (never silently dropped); the legacy id still maps to the merged record so transactions resolve.

| Source table | Legacy id | Name | Merged into |
| --- | ---: | --- | ---: |
| `companymst` | 2541 | ALKEM | 12953 |
| `companymst` | 2568 | JAGSAM PHARMA | 12979 |
| `companymst` | 2569 | JAGSAM PHARMA | 12979 |
| `doctormst` | 6 | SELF | 10273 |
| `itemmst` | 303 | VITOMIN-Z | 11462 |
| `itemmst` | 869 | CALTONVIT | 11852 |
| `itemmst` | 920 | POWERGESIC | 11224 |
| `ledger` | 2 | CASH | 69273 |
| `ledger` | 3 | CASH PURCHASE | 69276 |
| `ledger` | 4 | CREDIT PURCHASE | 69276 |
| `ledger` | 5 | CASH SALE | 69275 |
| `ledger` | 6 | CREDIT SALE | 69275 |
| `ledger` | 36 | SBI AC NO 33822385323 | 69274 |

## Unsupported fields (source value not stored)

| Field | Rows |
| --- | ---: |
| `creditnoteitemdetail.ReasonID` | 3,318 |
| `debitnoteitemdetail.ReasonID` | 19 |
| `itemmst.BillCompulsory` | 941 |
| `itemmst.SellLoose` | 941 |

## Unsupported tables

| Table | Reason |
| --- | --- |
| `ledgeropbal` | The new account_ledgers stores a single opening balance; the legacy per-financial-year/month opening-balance grid has no target. ledger.OpeningBal is preserved as the opening balance. |
| `invoicedebitnote` | No allocation table exists in the new schema. |
| `salescreditnote` | No allocation table exists in the new schema. |
| `receiptinvoice` | No allocation table exists in the new schema. |
| `paymentinvoice` | No allocation table exists in the new schema. |
| `challanvhheader` | The new application has no challan document type. |
| `challanitemdetail` | The new application has no challan document type. |
| `entryinvoicevhmst` | Draft entry-invoice document; not mapped. |
| `entryinvoicevhitem` | Draft entry-invoice document; not mapped. |
| `countersaleitems` | Headerless counter-sale lines dated before the first legacy financial year; no safe purchase/sale header to attach them to. |
| `softmaster` | The new application has no firm-profile table. |
| `billsetting` | Legacy bill print-layout configuration; not migrated. |
| `patientmaster` | The new application has no patient master table. |
| `sundrybillbybillopbal` | Bill-by-bill opening balances have no target in the new schema. |
| `accompany` | Legacy accounting company profile; no target table. |
| `stockadjusted` | Adjustments are already reflected in stockbalance totals (verified: batches exist whose TotalPurchaseQty equals their total adjustment with no purchases); imported as stock only. |

## Warnings

- duplicate_company_name: 'ALKEM' legacy id 2541 merged into 12953
- duplicate_company_name: 'JAGSAM PHARMA' legacy id 2568 merged into 12979
- duplicate_company_name: 'JAGSAM PHARMA' legacy id 2569 merged into 12979
- duplicate_doctor_name: 'SELF' legacy id 6 merged into 10273
- duplicate_item_name: 'VITOMIN-Z' legacy id 303 merged into 11462
- duplicate_item_name: 'CALTONVIT' legacy id 869 merged into 11852
- duplicate_item_name: 'POWERGESIC' legacy id 920 merged into 11224
- ledger_merged_into_system_role: 'CASH' → role CASH
- ledger_merged_into_system_role: 'CASH PURCHASE' → role PURCHASE
- ledger_merged_into_system_role: 'CREDIT PURCHASE' → role PURCHASE
- ledger_merged_into_system_role: 'CASH SALE' → role SALES
- ledger_merged_into_system_role: 'CREDIT SALE' → role SALES
- ledger_merged_into_system_role: 'SBI AC NO 33822385323' → role BANK (primary bank account)
- duplicate_stock_balance_row: item=238 batch=CARE

## Authentication

- Legacy `userinfo.UserPassword` hashes were **not** imported.
- Existing application accounts are preserved and login is unchanged.
- Legacy usernames, when imported, are inactive with an unusable password until an ADMIN resets them.
