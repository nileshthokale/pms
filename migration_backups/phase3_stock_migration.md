# Phase 3 — Legacy Stock-Balance Migration

- Source: `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\PharmaWinner202610051955.sql` (35,462,774 bytes, READ-ONLY)
- Target: `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\staging\stock_final_verify.db`
- Mode: `verify`

## Unit conversion

```
net_loose_units  = stockbalance.TotalPurchaseQty - stockbalance.TotalSalesQty
target_stock_qty = net_loose_units / stockbalance.PackSize
```

`stockadjusted` is already inside `TotalPurchaseQty` via the source
triggers, so adjustments are never added a second time.  Positive,
zero and negative nets are all preserved exactly.

## Plan

- source rows: 7793
- distinct target keys: 7792
- keys written to the plan: 7776
- keys WITHHELD as unresolved: 16
- duplicate source rows collapsed: 0
- positive: 1965
- zero: 5797
- negative (preserved as stored): 14
- legacy items with no mapping: 0
- **blocking normalised batch-key collisions: 7**
- **blocking unresolved pack sizes: 0**
- blocking merged-id collisions: 0
- metadata drift reported (non-blocking): 0

> **PLAN BLOCKED — `--apply` will refuse.** 7 unresolved key(s). Details below.

## BLOCKING — normalised batch-key collisions

Source batches that are distinct strings but collapse to the
same key once whitespace is stripped (for example `CARE` and
`' CARE'`). They are **never merged and never silently
dropped** — every compared field is listed so the difference
is on the record.

### target item 961 · normalised key `N 142033` — 2 raw variants (internal whitespace), metadata CONFLICTS

| raw batch | expiry | pack size | mrp | purchase rate | net rate | net loose |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `N  142033` | 2017-05-31 | 1.0 | 270.0 | 72.0 | 72.0 | 0.0 |
| `N 142033` | 2017-05-31 | 1.0 | 210.0 | 72.0 | 72.0 | 0.0 |

- conflicting fields: `mrp`
- agreeing fields: `expiry, pack_size, purchase_rate, net_rate`
- legacy items: ['16']
- source rows: 2

### target item 1094 · normalised key `KR 2923` — 2 raw variants (internal whitespace), metadata CONFLICTS

| raw batch | expiry | pack size | mrp | purchase rate | net rate | net loose |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `KR  2923` | 2016-11-30 | 10.0 | 46.5 | 35.8 | 37.59 | 0.0 |
| `KR 2923` | 2016-11-30 | 10.0 | 46.5 | 36.49 | 38.31 | 0.0 |

- conflicting fields: `purchase_rate, net_rate`
- agreeing fields: `expiry, pack_size, mrp`
- legacy items: ['149']
- source rows: 2

### target item 1134 · normalised key `CARE UNI` — 2 raw variants (internal whitespace), metadata CONFLICTS

| raw batch | expiry | pack size | mrp | purchase rate | net rate | net loose |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `CARE  UNI` | 2017-05-31 | 1.0 | 230.0 | 110.0 | 110.0 | 9.0 |
| `CARE UNI` | 2017-05-31 | 1.0 | 260.0 | 95.0 | 107.44 | 0.0 |

- conflicting fields: `mrp, purchase_rate, net_rate`
- agreeing fields: `expiry, pack_size`
- legacy items: ['189']
- source rows: 2

### target item 1182 · normalised key `CARE` — 2 raw variants (surrounding whitespace), metadata CONFLICTS

| raw batch | expiry | pack size | mrp | purchase rate | net rate | net loose |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ` CARE` | 2018-05-31 | 1.0 | 125.0 | 52.0 | 50.0 | 0.0 |
| `CARE` | 2017-05-31 | 1.0 | 125.0 | 52.0 | 52.0 | 0.0 |

- conflicting fields: `expiry, net_rate`
- agreeing fields: `pack_size, mrp, purchase_rate`
- legacy items: ['238']
- source rows: 2

### target item 1294 · normalised key `CARE 1` — 3 raw variants (internal whitespace), metadata CONFLICTS

| raw batch | expiry | pack size | mrp | purchase rate | net rate | net loose |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `CARE   1` | 2017-05-31 | 1.0 | 75.0 | 15.0 | 15.0 | 0.0 |
| `CARE  1` | 2017-05-31 | 1.0 | 55.0 | 15.0 | 15.0 | 0.0 |
| `CARE 1` | 2017-05-31 | 1.0 | 65.0 | 15.0 | 15.0 | 0.0 |

- conflicting fields: `mrp`
- agreeing fields: `expiry, pack_size, purchase_rate, net_rate`
- legacy items: ['351']
- source rows: 3

### target item 1524 · normalised key `LA 60709` — 2 raw variants (internal whitespace), metadata CONFLICTS

| raw batch | expiry | pack size | mrp | purchase rate | net rate | net loose |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `LA  60709` | 2019-06-30 | 5.0 | 23.0 | 17.36 | 19.09 | 0.0 |
| `LA 60709` | 2019-06-30 | 5.0 | 23.0 | 17.36 | 10.95 | 0.0 |

- conflicting fields: `net_rate`
- agreeing fields: `expiry, pack_size, mrp, purchase_rate`
- legacy items: ['581']
- source rows: 2

### target item 1543 · normalised key `ST16 2195` — 2 raw variants (internal whitespace), metadata CONFLICTS

| raw batch | expiry | pack size | mrp | purchase rate | net rate | net loose |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `ST16  2195` | 2018-09-30 | 10.0 | 71.0 | 50.71 | 53.25 | 0.0 |
| `ST16 2195` | 2018-09-30 | 10.0 | 71.0 | 50.71 | 52.07 | 0.0 |

- conflicting fields: `net_rate`
- agreeing fields: `expiry, pack_size, mrp, purchase_rate`
- legacy items: ['600']
- source rows: 2

## Negative balances (preserved, never clamped)

- item 992 batch `D300311`: -2.0 loose / pack 10.0 = -0.2000 packs
- item 1017 batch `146005EH`: -42.0 loose / pack 10.0 = -4.2000 packs
- item 1189 batch `466`: -2.0 loose / pack 1.0 = -2.0000 packs
- item 1454 batch `3115522`: -3.0 loose / pack 5.0 = -0.6000 packs
- item 1098 batch `CARE 1`: -1.0 loose / pack 1.0 = -1.0000 packs
- item 1034 batch `DH5004`: -1.0 loose / pack 1.0 = -1.0000 packs
- item 1543 batch `ST16-2195`: -138.0 loose / pack 10.0 = -13.8000 packs
- item 1585 batch `BT-286`: -2.0 loose / pack 10.0 = -0.2000 packs
- item 1572 batch `N022`: -9.0 loose / pack 15.0 = -0.6000 packs
- item 1613 batch `011E7ALB`: -14.0 loose / pack 10.0 = -1.4000 packs
- item 1573 batch `LMI931A`: -3.0 loose / pack 10.0 = -0.3000 packs
- item 1602 batch `E2000936`: -60.0 loose / pack 15.0 = -4.0000 packs
- item 1235 batch `4SB0416`: -3.0 loose / pack 10.0 = -0.3000 packs
- item 1827 batch `BR1E1445`: -1.0 loose / pack 1.0 = -1.0000 packs

## Verification

- plan rows: 7776
- quantity mismatches: 1864
- missing batches: 178
- duplicate (item, batch) keys: 0
- orphan batches: 0
- `stock_batches` total: 7616
- positive: 0
- zero: 7616
- negative: 0
- integrity_check: ok
- foreign-key violations: 0
- **ok: False**

## UC-ROSE trace

- legacy `itemmst.ID`: 832
- mapped target `items.id`: 1775
- target item row: `{"id": 1775, "item_name": "UC-ROSE", "unit_id": 31, "company_id": 3792, "category_id": null, "pack_size": "10", "tax_structure": "11", "discount": 0.0, "mrp": 350.0, "rate": 237.29, "reorder_stock_level": 30, "scheduled": "1", "location": "", "pathy": "ALLOPATHIC MEDICINES", "dpco": "N", "legacy_tax_id": null}`
- source `stockbalance` rows: 14
- keys withheld for this item (unresolved): 0

### Source stockbalance rows

- `{"batch_no": "STF-089", "expiry": "2024-05-31", "mrp": 350.0, "rate": 237.29, "net_pur_rate": 233.34, "total_purchase_qty_loose": 190.0, "pack_size": 10.0, "total_sales_qty_loose": 190.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "STF-007", "expiry": "2024-09-30", "mrp": 350.0, "rate": 237.29, "net_pur_rate": 233.34, "total_purchase_qty_loose": 120.0, "pack_size": 10.0, "total_sales_qty_loose": 120.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "STF-026", "expiry": "2024-11-30", "mrp": 350.0, "rate": 237.29, "net_pur_rate": 260.56, "total_purchase_qty_loose": 351.0, "pack_size": 10.0, "total_sales_qty_loose": 351.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "STF-2414", "expiry": "2025-10-31", "mrp": 385.0, "rate": 261.02, "net_pur_rate": 256.67, "total_purchase_qty_loose": 120.0, "pack_size": 10.0, "total_sales_qty_loose": 120.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "UTF-2414", "expiry": "2025-10-31", "mrp": 385.0, "rate": 261.02, "net_pur_rate": 444.04, "total_purchase_qty_loose": 140.0, "pack_size": 10.0, "total_sales_qty_loose": 139.0, "net_loose_units": 1.0, "net_packs": 0.1}`
- `{"batch_no": "JFT-2414", "expiry": "2025-10-31", "mrp": 385.0, "rate": 261.02, "net_pur_rate": 256.67, "total_purchase_qty_loose": 60.0, "pack_size": 10.0, "total_sales_qty_loose": 60.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "JFT-2437", "expiry": "2025-12-31", "mrp": 385.0, "rate": 261.02, "net_pur_rate": 256.67, "total_purchase_qty_loose": 60.0, "pack_size": 10.0, "total_sales_qty_loose": 60.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "JFT-2475", "expiry": "2026-06-30", "mrp": 385.0, "rate": 261.0, "net_pur_rate": 213.02, "total_purchase_qty_loose": 65.0, "pack_size": 10.0, "total_sales_qty_loose": 63.0, "net_loose_units": 2.0, "net_packs": 0.2}`
- `{"batch_no": "JFT-2505", "expiry": "2026-09-30", "mrp": 425.0, "rate": 288.14, "net_pur_rate": 283.34, "total_purchase_qty_loose": 60.0, "pack_size": 10.0, "total_sales_qty_loose": 60.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "JFT-2498", "expiry": "2026-06-30", "mrp": 343.0, "rate": 261.01, "net_pur_rate": 228.38, "total_purchase_qty_loose": 60.0, "pack_size": 10.0, "total_sales_qty_loose": 60.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "JTF-2505", "expiry": "2026-09-30", "mrp": 378.17, "rate": 288.14, "net_pur_rate": 252.12, "total_purchase_qty_loose": 60.0, "pack_size": 10.0, "total_sales_qty_loose": 60.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "JTF-2547", "expiry": "2027-01-31", "mrp": 378.0, "rate": 288.14, "net_pur_rate": 252.12, "total_purchase_qty_loose": 60.0, "pack_size": 10.0, "total_sales_qty_loose": 57.0, "net_loose_units": 3.0, "net_packs": 0.3}`
- `{"batch_no": "JFT-2573", "expiry": "2027-04-30", "mrp": 378.16, "rate": 288.14, "net_pur_rate": 252.12, "total_purchase_qty_loose": 60.0, "pack_size": 10.0, "total_sales_qty_loose": 60.0, "net_loose_units": 0.0, "net_packs": 0.0}`
- `{"batch_no": "JTF-2573", "expiry": "2027-04-30", "mrp": 378.18, "rate": 288.12, "net_pur_rate": 252.1, "total_purchase_qty_loose": 780.0, "pack_size": 10.0, "total_sales_qty_loose": 549.0, "net_loose_units": 231.0, "net_packs": 23.1}`

### Current state (before migration)

- These target rows are the zero-quantity history-linkage rows.
  They are shown for contrast only — **they are not the basis of
  the projection below.**

- current `stock_batches` rows: 14
- of those, `stock_qty > 0`: 0
- offered by Counter Sale right now: 0

### Projected state after migration (from `plan_rows`)

- projected batches: 14
- projected with `stock_qty > 0`: 4
- projected `stock_qty > 0` but expired (stocked, unsellable): 2
- **projected offered by Counter Sale (stock > 0 and unexpired): 2**

| batch | expiry | pack | mrp | net loose | projected stock | sellable |
| --- | --- | ---: | ---: | ---: | ---: | :---: |
| `STF-089` | 2024-05-31 | 10 | 350.0 | 0.0 | 0.0000 | no |
| `STF-007` | 2024-09-30 | 10 | 350.0 | 0.0 | 0.0000 | no |
| `STF-026` | 2024-11-30 | 10 | 350.0 | 0.0 | 0.0000 | no |
| `STF-2414` | 2025-10-31 | 10 | 385.0 | 0.0 | 0.0000 | no |
| `UTF-2414` | 2025-10-31 | 10 | 385.0 | 1.0 | 0.1000 | no |
| `JFT-2414` | 2025-10-31 | 10 | 385.0 | 0.0 | 0.0000 | no |
| `JFT-2437` | 2025-12-31 | 10 | 385.0 | 0.0 | 0.0000 | no |
| `JFT-2475` | 2026-06-30 | 10 | 385.0 | 2.0 | 0.2000 | no |
| `JFT-2505` | 2026-09-30 | 10 | 425.0 | 0.0 | 0.0000 | no |
| `JFT-2498` | 2026-06-30 | 10 | 343.0 | 0.0 | 0.0000 | no |
| `JTF-2505` | 2026-09-30 | 10 | 378.17 | 0.0 | 0.0000 | no |
| `JTF-2547` | 2027-01-31 | 10 | 378.0 | 3.0 | 0.3000 | yes |
| `JFT-2573` | 2027-04-30 | 10 | 378.16 | 0.0 | 0.0000 | no |
| `JTF-2573` | 2027-04-30 | 10 | 378.18 | 231.0 | 23.1000 | yes |
