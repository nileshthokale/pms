# Legacy Migration — Dry Run

- Source dump: `PharmaWinner202609142001.sql`
- Dump size: 35,325,237 bytes
- Source tables: 52
- Source data rows: 502,534
- Demo rows excluded: 934

## Table plan

| Source table | Rows | Target | Status |
| --- | ---: | --- | --- |
| `accompany` | 0 | unsupported (legacy accounting company profile; no data) | unsupported |
| `acyear` | 12 | financial_years | mapped |
| `billsetting` | 1 | unsupported (print layout configuration) | unsupported |
| `challanitemdetail` | 142 | unsupported (challan document type) | unsupported |
| `challanvhheader` | 80 | unsupported (challan document type) | unsupported |
| `companymst` | 1,221 | companies | mapped |
| `countersaleitems` | 2 | unsupported (headerless counter-sale lines) | unsupported |
| `creditnoteitemdetail` | 3,318 | credit_note_items | mapped |
| `creditnotevhdetail` | 42 | ledger_transactions | mapped |
| `creditnotevhheader` | 1,345 | credit_notes | mapped |
| `debitnoteitemdetail` | 19 | debit_note_items | mapped |
| `debitnotevhdetail` | 2 | ledger_transactions | mapped |
| `debitnotevhheader` | 13 | debit_notes | mapped |
| `demosalescreditnote` | 0 | excluded (demo) | demo — excluded |
| `demosalesitemdetail` | 463 | excluded (demo) | demo — excluded |
| `demosalesvhdetail` | 314 | excluded (demo) | demo — excluded |
| `demosalesvhheader` | 157 | excluded (demo) | demo — excluded |
| `doctormst` | 8 | doctors | mapped |
| `drugmst` | 147 | drugs | mapped |
| `entryinvoicevhitem` | 0 | unsupported (no data / draft-entry document) | unsupported |
| `entryinvoicevhmst` | 0 | unsupported (no data / draft-entry document) | unsupported |
| `gpmst` | 22 | account_groups (classification) | mapped |
| `invoicedebitnote` | 10 | unsupported (no allocation table) | unsupported |
| `invoiceitemdetail` | 11,829 | purchase_invoice_items | mapped |
| `invoicevhdetail` | 11,362 | ledger_transactions | mapped |
| `invoicevhheader` | 5,681 | purchase_invoices | mapped |
| `itemdrugs` | 402 | item_ingredients | mapped |
| `itemmst` | 941 | items | mapped |
| `journalvhdetail` | 0 | journal_entry_items | mapped |
| `journalvhheader` | 0 | journal_entries | mapped |
| `ledger` | 123 | account_ledgers | mapped |
| `ledgeropbal` | 551 | unsupported (per-FY opening balances) | unsupported |
| `pathymst` | 6 | items.pathy (value lookup) | mapped |
| `patientmaster` | 0 | patients (no target table; no data) | mapped |
| `paymentinvoice` | 2,671 | unsupported (no allocation table) | unsupported |
| `paymentvhdetail` | 1,598 | ledger_transactions | mapped |
| `paymentvhheader` | 785 | supplier_payments | mapped |
| `receiptinvoice` | 114 | unsupported (no allocation table) | unsupported |
| `receiptvhdetail` | 88 | ledger_transactions | mapped |
| `receiptvhheader` | 44 | customer_receipts | mapped |
| `salescreditnote` | 527 | unsupported (no allocation table) | unsupported |
| `salesitemdetail` | 232,707 | sales_invoice_items | mapped |
| `salesvhdetail` | 143,624 | ledger_transactions | mapped |
| `salesvhheader` | 71,803 | sales_invoices | mapped |
| `softmaster` | 1 | unsupported (firm profile — no target table) | unsupported |
| `statemst` | 1 | customers.state / suppliers.state (value lookup) | mapped |
| `stockadjusted` | 3,397 | stock_batches (already reflected in stockbalance) | mapped |
| `stockbalance` | 7,764 | stock_batches | mapped |
| `sundaryinfo` | 113 | customers / suppliers | mapped |
| `sundrybillbybillopbal` | 0 | unsupported (bill-by-bill opening balances) | unsupported |
| `unitmst` | 16 | units | mapped |
| `userinfo` | 2 | app_users (usernames only, opt-in, inactive) | mapped |

## Findings

### duplicate_item_names (3)

- {"name": "POWERGESIC", "legacy_ids": [51, 920]}
- {"name": "VITOMIN-Z", "legacy_ids": [290, 303]}
- {"name": "CALTONVIT", "legacy_ids": [681, 869]}

### no_journal_records (1)

- "No journal records to migrate."

### stock_negative_batches (14)

- {"item_id": 47, "batch": "D300311", "qty": -2.0}
- {"item_id": 72, "batch": "146005EH", "qty": -42.0}
- {"item_id": 245, "batch": "466", "qty": -2.0}
- {"item_id": 511, "batch": "3115522", "qty": -3.0}
- {"item_id": 153, "batch": "CARE 1", "qty": -1.0}
- {"item_id": 89, "batch": "DH5004", "qty": -1.0}
- {"item_id": 600, "batch": "ST16-2195", "qty": -138.0}
- {"item_id": 642, "batch": "BT-286", "qty": -2.0}
- {"item_id": 629, "batch": "N022", "qty": -9.0}
- {"item_id": 670, "batch": "011E7ALB", "qty": -14.0}
- {"item_id": 630, "batch": "LMI931A", "qty": -3.0}
- {"item_id": 659, "batch": "E2000936", "qty": -60.0}
- {"item_id": 291, "batch": "4SB0416", "qty": -3.0}
- {"item_id": 885, "batch": "BR1E1445", "qty": -1.0}

## Compatibility notes

- `ledgeropbal` (per-FY/month opening balances) has no target column; `ledger.OpeningBal` becomes the single opening balance.
- `stockadjusted` is already reflected in `stockbalance` totals and is not summed again (no double counting).
- `challan*`, `entryinvoice*`, `countersaleitems`, `*invoice`/`*creditnote` allocation tables, `softmaster`, `billsetting` and `patientmaster` have no target tables and are reported as unsupported.
- Legacy `userinfo.UserPassword` is never imported.
- Legacy numeric foreign keys are never reused as new ids; every master record is remapped.
