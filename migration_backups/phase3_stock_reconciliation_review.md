# Stock Reconciliation Review — Read-Only (NO migration applied)

Verified against `PharmaWinner202610051955.sql` (35,462,774 bytes, unmodified)
and dev `data/pharmacy.db` (read-only). Target table confirmed:
`stock_batches(..., stock_qty REAL)` — 0 rows. **`pharma_inventory` does not
exist**; no such assumption is used anywhere below.

## 1. Verified facts (trigger + arithmetic evidence)

- **Units**: source triggers maintain `stockbalance` in LOOSE (individual-unit)
  quantities — `TotalPurchaseQty += TotalLooseQty` (invoice/challan),
  `+= AdjustedQty` (stockadjusted), `+= TotQty` (credit notes);
  `TotalSalesQty += SalesQty` (sales), `+= TotQty` (debit notes).
  Target `stock_qty` is packs (posting engine adds `pay_qty + free_qty`).
  Conversion: `stock_qty = (TotalPurchaseQty − TotalSalesQty) / PackSize`.
- **Pay/Free are packs**: all 11,891 purchase lines satisfy
  `TotalLooseQty = (PayPackQty + FreePackQty) × PackSize = RcvdPackQty × PackSize`,
  so loose→packs conversion is exact, not lossy.
- **Adjustments already included**: `stockadjusted_AINS` adds `AdjustedQty`
  into `TotalPurchaseQty` (same for challan-linked invoice lines, which the
  invoice trigger skips because the challan trigger already counted them).
  Adding adjustments again would double-count. The earlier dry run's
  "adjustments counted once" reconciliation variant is SUPERSEDED.
- **Pack sizes valid**: zero NULL/zero `PackSize` in 7,793 balance rows;
  100% agreement between balance rows and their purchase lines.
- **NULL quantities**: none — `TotalPurchaseQty`/`TotalSalesQty`/`PackSize`
  are all non-NULL. The NULL-sales rule is documented but has zero members.
- **Challan-linked invoice lines** (109) are correctly excluded from any
  re-addition (already counted via challan triggers).

## 2. Buckets (ItemID + BatchNo matched, 7,793 keys)

| Bucket | Count | Treatment |
| --- | ---: | --- |
| Matched (computable net) | 7,793 | `stock_qty = (P − S) / PackSize` |
| Positive | 1,967 | importable as-is |
| Zero | 5,812 | importable (depleted batches) |
| Negative (exceptions, preserved) | 14 | importable only under an owner rule; never clamp — worst: (600,'ST16-2195') −13.8 packs |
| Invalid pack size | 0 | — |
| NULL quantities | 0 | — |
| Missing from balance (purchase 2, sales 2, adj 10; CN/DN/challan 0) | 14 keys | zero-qty history batches only |

## 3. The 21 sales-total discrepancies (all `sb.TotalSalesQty` > detail sum)

17 mismatches (e.g. (718,'JMT-18210'): 2,515 vs 555; (680,'LTA-13267'): 3,423 vs
2,523) + 4 batches with NO sales-detail rows at all
((33,'E600204')=100, (235,'ALY1507013')=80, (814,'ASMT22001')=360, (835,'HTJ0097')=100).
Direction is uniform: balance exceeds verifiable detail — consistent with
deleted/edited sales rows or direct balance edits bypassing triggers. Net
math uses the balance totals (per §3 rule); the 21 are listed as exceptions,
not corrections.

## 4. Reconciling totals

- Σ TotalPurchaseQty = 1,782,848 loose; Σ TotalSalesQty = 1,723,404 loose.
- Net = 59,444 loose → **9,587.46 packs** across 7,793 batches
  (1,967 positive / 5,812 zero / 14 negative preserved).

## 5. Assumptions (explicit, minimal)

- Per-batch PackSize (last-write-wins in source) applies to the whole net.
- History-only keys get zero-qty batches for linkage, per prior approved pattern.
- Sales detail is evidence only; it cannot rebuild balances (deleted rows).

## 6. Out of scope (unchanged)

Year-wise sales/purchase history import and display is a SEPARATE requirement:
nothing here fixes it, and this reconciliation must not be cited as history
coverage. No data was written; source, dev, production, EXE and dist untouched.
