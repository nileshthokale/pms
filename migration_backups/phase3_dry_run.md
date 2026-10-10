# Phase 3 Dry Run — Purchases + Stock (NO DB WRITES)

- Source: `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\PharmaWinner202610051955.sql` (35,462,774 bytes, READ-ONLY)

## 1. Table mappings

### Purchase headers (`invoicevhheader` → `purchase_invoices`)

- `ID` → `id` (preserved explicit)
- `AcYearID+VhType+VhNo` → `voucher_no` (FY name-Type-No composition)
- `VhDate` → `voucher_date` (verbatim (no bad dates found))
- `VhTime` → `voucher_time` (verbatim)
- `VhType` → `purchase_type` (verbatim Cash/Credit)
- `SuppID` → `supplier_id` (direct: ledger IDs preserved in Phase 2)
- `InvoiceNo` → `invoice_no` (verbatim)
- `InvoiceDate` → `invoice_date` (verbatim)
- `DueDate` → `due_date` (verbatim)
- `GrossAmount` → `total_amount` (verbatim)
- `DiscountEntered` → `NO TARGET` (free-text entry mode, no target)
- `DiscountPer` → `bill_discount` (verbatim percent)
- `DiscountAmt` → `NO TARGET` (header discount amount, no target column)
- `RoundOff` → `round_off` (verbatim)
- `LessDNAmount` → `NO TARGET` (debit-note allocation, no target)
- `AddCNAmount` → `NO TARGET` (credit-note allocation, no target)
- `AddTaxAmount` → `gst_amount` (verbatim header tax total)
- `PaidAmount` → `NO TARGET` (payments belong to a later phase)
- `VhAmount` → `invoice_net_amount` (verbatim voucher total)
- `VhNarration` → `remarks` (verbatim)

### Purchase lines (`invoiceitemdetail` → `purchase_invoice_items`)

- `ID` → `id` (preserved explicit)
- `VhID` → `purchase_invoice_id` (via preserved header IDs)
- `ItemID` → `item_id` (direct: item IDs preserved in Phase 1)
- `PackSize` → `pack_size` (smallint to TEXT)
- `PayPackQty` → `pay_qty` (packs, verbatim)
- `FreePackQty` → `free_qty` (packs, verbatim)
- `RcvdPackQty` → `NO TARGET` (equals pay+free; no target)
- `TotalLooseQty` → `NO TARGET` (loose units; new schema tracks packs only)
- `BatchNo` → `batch_no` (verbatim (never empty in source))
- `ExpiryDate` → `expiry` (verbatim YYYY-MM-DD)
- `Rate` → `rate` (verbatim)
- `MRP` → `mrp` (verbatim)
- `DiscEntered` → `NO TARGET` (free-text entry mode, no target)
- `DiscPer` → `discount` (verbatim percent)
- `DiscAmt` → `NO TARGET` (line discount amount, no target column)
- `Amount` → `amount` (verbatim)
- `TaxPer` → `gst_percent` (VERBATIM incl. VAT-era rates; never converted)
- `TaxAmt` → `gst_amount` (verbatim)
- `PurRate` → `purchase_rate` (verbatim)
- `NetRate` → `net_rate` (verbatim)
- `SaleRate` → `NO TARGET` (same-as-MRP duplicate, no target)
- `ChallanID` → `NO TARGET` (challans are a separate unmapped document type)

### Batches (`stockbalance` → `stock_batches`)

- `ItemID` → `item_id` (direct)
- `BatchNo` → `batch_no` (verbatim; (item,batch) unique in source)
- `ExpiryDate` → `expiry` (verbatim)
- `MRP` → `mrp` (verbatim)
- `Rate` → `purchase_rate` (verbatim)
- `NetPurRate` → `net_rate` (verbatim)
- `PackSize` → `pack_size` (smallint to TEXT)
- `TotalPurchaseQty-TotalSalesQty` → `stock_qty` (pack-unit net, verbatim)
- `NetSalesRate/TotalSalesQty` → `NO TARGET` (sales history, not a stock field)

## 2. Expected counts
- purchase headers: 5713
- purchase lines: 11891
- stock batches (stockbalance nets): 7793
- history-only zero batches: 4

## 3. Reference checks
- missing suppliers: []
- missing items: []
- orphan lines: 0
- duplicate bill numbers: 0
- duplicate vouchers: 0
- bad voucher dates: 0
- negative-pay lines: 0
- zero-qty lines: 0

## 4. Batch/stock quantities
- stockbalance keys: 7793
- zero nets: 5812, positive: 1967, negative: 14
- items unknown to Phase 1: []
- history-only batches: 4

## 5. Sales/returns/adjustment dependencies
- sales lines: 233598 (7479 batches, loose SalesQty converted via per-row PackSize)
- credit-note lines: 3329, debit-note lines: 20 (loose Qty converted via per-row PackSize)
- adjustments: 3406 rows (counted once as movement evidence; final rule needs owner decision (see reconciliation))
- challans: 80 headers / 142 lines (excluded as purchase documents (separate receipt type); no double counting)

## 6. VAT/GST handling
- line TaxPer distribution: {"0": 262, "12": 6939, "12.5": 108, "13.5": 57, "18": 476, "28": 9, "5": 2568, "5.5": 566, "6": 906}
- VAT-only rates (never converted): ['12.5', '13.5', '5.5', '6']
- dated line era split: {"VAT": 3181, "GST": 8710}

## 7. Reconciliation result
- matched: 5593, over: 1216, under: 998
- Rule: stockbalance nets are authoritative for current stock; purchases give history. Residuals (loose-unit rounding, unrecorded movements, opening stock) must NOT be forced to balance. Negative nets need an owner rule.

## 8. Schema compatibility: see schema_notes in JSON; no ID conflicts (targets empty).

## 9. Migration order
- purchase_invoices (headers, IDs preserved)
- purchase_invoice_items (lines, IDs preserved)
- stock_batches from stockbalance nets (authoritative current stock)
- zero-qty history batches for linked-but-absent (item,batch)
- sqlite_sequence cursors to max IDs

## 10. Validation checks
- header/line counts equal source
- voucher_no unique
- supplier/item refs resolve
- no negative pay/rate rows beyond reported list
- stock qty equals stockbalance nets exactly
- transaction tables for other phases still empty
- integrity_check ok, foreign_key_check 0

## Exceptions (first 30 over-balance keys)
- {"key": [491, "GOFZ0034"], "purch": 12.0, "sales_packs": 12.0, "cn": 0.2, "dn": 0, "adj": 0, "stockbalance": 2.0}
- {"key": [44, "NMF4001"], "purch": 18.0, "sales_packs": 18.4, "cn": 0.6, "dn": 0, "adj": 5.0, "stockbalance": 7.0}
- {"key": [812, "BHC-220400"], "purch": 142.0, "sales_packs": 28.0, "cn": 0, "dn": 104.0, "adj": 0, "stockbalance": 100.0}
- {"key": [563, "SIC2762A"], "purch": 10.0, "sales_packs": 9.5, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 5.0}
- {"key": [617, "CC16157"], "purch": 40.0, "sales_packs": 8.0, "cn": 2.6, "dn": 0, "adj": 0, "stockbalance": 346.0}
- {"key": [485, "BBT16L11"], "purch": 3.0, "sales_packs": 1.5, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 15.0}
- {"key": [712, "J202058"], "purch": 50.0, "sales_packs": 50.2, "cn": 0.5, "dn": 0, "adj": 0, "stockbalance": 3.0}
- {"key": [826, "TOF22008SH"], "purch": 3.0, "sales_packs": 2.5, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 5.0}
- {"key": [908, "02TOT26-41"], "purch": 107.0, "sales_packs": 99.9, "cn": 0.2, "dn": 0, "adj": 0, "stockbalance": 73.0}
- {"key": [227, "SU 10764"], "purch": 0, "sales_packs": 3.0, "cn": 0, "dn": 0, "adj": 2.0, "stockbalance": 0.0}
- {"key": [448, "PABBBZ08"], "purch": 10.0, "sales_packs": 9.6, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 4.0}
- {"key": [376, "CT15479"], "purch": 55.0, "sales_packs": 14.9, "cn": 0.8, "dn": 0, "adj": 0, "stockbalance": 409.0}
- {"key": [663, "1467"], "purch": 20.0, "sales_packs": 19.4, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 6.0}
- {"key": [125, "15TRB004A"], "purch": 5.0, "sales_packs": 4.6, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 4.0}
- {"key": [415, "FLB701A"], "purch": 10.0, "sales_packs": 9.8, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 2.0}
- {"key": [802, "FBAE2501"], "purch": 17.0, "sales_packs": 15.3, "cn": 0.2, "dn": 0, "adj": 1.0, "stockbalance": 20.0}
- {"key": [404, "E2101495"], "purch": 5.0, "sales_packs": 3.87, "cn": 0.13333333333333333, "dn": 0, "adj": 0, "stockbalance": 19.0}
- {"key": [605, "22490473"], "purch": 5.0, "sales_packs": 4.6, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 4.0}
- {"key": [499, "BC-278"], "purch": 30.0, "sales_packs": 30.5, "cn": 0.6, "dn": 0, "adj": 0, "stockbalance": 1.0}
- {"key": [588, "BSRO560"], "purch": 5.0, "sales_packs": 0, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 50.0}
- {"key": [745, "23SFC03"], "purch": 20.0, "sales_packs": 19.79, "cn": 0.2857142857142857, "dn": 0, "adj": 0, "stockbalance": 7.0}
- {"key": [360, "04033E"], "purch": 10.0, "sales_packs": 9.4, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 6.0}
- {"key": [513, "8517"], "purch": 20.0, "sales_packs": 18.6, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 14.0}
- {"key": [858, "23510389"], "purch": 3.0, "sales_packs": 2.67, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 4.0}
- {"key": [842, "23440479"], "purch": 3.0, "sales_packs": 0, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 30.0}
- {"key": [566, "86CRL021"], "purch": 30.0, "sales_packs": 30.1, "cn": 0.3, "dn": 0, "adj": 0, "stockbalance": 2.0}
- {"key": [6, "KBC676A"], "purch": 13.0, "sales_packs": 12.87, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 2.0}
- {"key": [566, "SGT0086"], "purch": 20.0, "sales_packs": 20.4, "cn": 0.5, "dn": 0, "adj": 0, "stockbalance": 1.0}
- {"key": [742, "LUP18417"], "purch": 10.0, "sales_packs": 2.0, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 80.0}
- {"key": [489, "86414009"], "purch": 10.0, "sales_packs": 4.1, "cn": 0, "dn": 0, "adj": 0, "stockbalance": 59.0}