# Phase 4 — Loose-Unit Stock Correction (STAGING ONLY, live untouched)

Verified convention: `stock_batches.stock_qty` = loose tablets; purchase
`pay_qty`/`free_qty` = packs; `sale_qty`/`return_qty` = loose; MRP and
`purchase_rate` = per pack; `amount = qty × MRP / pack_size`.

## 1. Phase 1 audit — every stock_qty read/write

- `purchase_dao` insert/update-new: `stock += pay + free` — FIXED to
  `× pack_factor(pack_size)` (4 sites incl. both reversals, which use each
  line's own stored `pack_size`). Reversal keeps its `MAX(...,0)` clamp;
  delete keeps exact-reversal accounting.
- `sales_dao` insert/update/delete: `∓ sale_qty` — already loose,
  unchanged. REMOVED `DELETE FROM stock_batches WHERE stock_qty <= 0`
  (it would wipe history linkage, zero batches and legitimate negatives).
- `credit_note_dao` (`±return_qty`), `debit_note_dao` (`∓return_qty`) —
  already loose, unchanged. `draft_stock` pure same-unit math, unchanged.
- `stock_dao.get_summary`, `expiry_report_dao._summarize` valuation —
  FIXED to `Σ qty × rate / pack_size` (rate is per pack).
- Counter Sale: `get_stock_batches_for_item` (`qty>0` + unexpired, FEFO),
  `:.0f` labels, `sale_qty > available` check, expired-posting guard —
  unchanged and now exact (values are integral loose units). Pricing
  `qty×MRP/pack` unchanged. `get_total_stock` SUM is loose, unchanged.
- `import_service` writes no stock. Historical transaction values frozen.

## 2. UC-CART proof (item 1808, legacy 865, pack 10)

Source `pay/free/loose` proves packs vs tablets (e.g. 10+2→120).

| Batch | Src net loose | Before (packs) | After (tablets) | Display was → now |
|---|---|---|---|---|
| VHT14811 (MRP 435) | 1 | 0.1 | 1.0 | Avail 0 → 1 |
| VHT14811. (dot, MRP 387) | 19 | 1.9 | 19.0 | 2 → 19 |
| VH16956 (MRP 387) | 101 | 10.1 | 101.0 | 10 → 101 |
| VH18512 (MRP 387) | 20 | 2.0 | 20.0 | 2 → 20 |

Distinct identities/histories re-verified (44/2, 51/4, 10/2 purchase/sales
lines; FKs 44/51/10 split). MRP differences are source-correct.

## 3. Staging reconstruction (`staging/stock_loose_stage.db`)

- Fresh backup-API clone of live; pre-image `stock_final_verify.db`
  compared: **zero** post-migration transactions (ID maxima and
  quantity checksums identical), so `corrected = legacy net_loose`
  with no deltas to merge and no double-counting.
- One transaction, idempotent SETs: 7,793 keys set, 0 inserted
  (2 history-only zero batches untouched), negatives kept
  (−138.0 etc., never clamped), no `/PackSize`, no adjustment re-add.
- Provenance `legacy_batch_resolution`: 36 rows (17 collision + 19
  trailing-whitespace), recoverable without JSON; audit
  `legacy_stock_correction` (7,793 set, 14 negatives).
- Rerun is byte-identical (updated 7,793 / inserted 0 / 36 rows again).

## 4. Verification on staging

- integrity ok, FK 0, duplicate (item,batch) 0; stored-vs-legacy exact
  for all 7,793 keys; 0 non-integer quantities remain.
- Totals: 7,795 batches, pos 1,967 / zero 5,814 / neg 14;
  expired-with-stock 1,549; Counter-Sale sellable **418**.
- BIO D3 PLUS sellable: 1/1/15/70 tablets (pack 15); UC-ROSE: 3/231.
- Zero/negative/expired remain unsellable by construction.

## 5. Tests

- New `test_loose_stock_units` (9): packs 1/5/10/15, UC-CART tablets,
  purchase×pack, tablet pricing, negative/idempotence, valuation, guards,
  live-refusal — pass.
- Suites: `counter_sale_units` 51, phase3/purchase/sales/credit/debit/
  posting/expiry 213, loose+resolution+audit 60 — pass.
- FY-history/switch suites show the same 20 failures before and after
  this change (pre-existing UI feature gap, unrelated).

## 6. Rollback (live NOT touched; for approval-gated future use only)

- Live `data/pharmacy.db` was never opened for writing in this task.
- Rollback of a future live correction: timestamped pre-apply backup
  restore (clone-only pattern), or deterministic reversal from
  `legacy_batch_resolution` + `legacy_stock_correction`
  (`stock_qty = net_loose / pack_size` recompute per batch) — to be
  rehearsed on staging first. Post-apply backup
  `post_stock_apply_20261011_182303.db` already on file.

STOP: awaiting approval before any live change.
