# Legacy Data Migration Report

## Source

- File: `PharmaWinner202609142001.sql`
- Size: 35,325,237 bytes
- Format: MySQL 5.7 mysqldump (imported offline — no MySQL connection)

## Cleared demo/test business data

| Table | Rows removed |
| --- | ---: |

## Imported rows

| Source table | Rows | Target | Imported | Skipped |
| --- | ---: | --- | ---: | ---: |

- Total imported rows: 0
- Total skipped rows: 0
- Demo rows excluded: 0
- Warnings: 0

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

## Authentication

- Legacy `userinfo.UserPassword` hashes were **not** imported.
- Existing application accounts are preserved and login is unchanged.
- Legacy usernames, when imported, are inactive with an unusable password until an ADMIN resets them.
