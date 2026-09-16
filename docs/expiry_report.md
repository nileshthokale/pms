# Expiry Report — Phase 5C

**Date:** 2026-09-16
**Menu:** Reports → Expiry Report
**Files:** `database/expiry_report_dao.py`, `screens/expiry_report.py`, `test_expiry_report.py`

---

## 1. Purpose

Read-only report of stock batches that are **expired** or **approaching expiry**, so the pharmacy can act (return, dispose, prioritize sale) before a batch is lost. It reads the current batch-wise stock and never modifies anything.

> **Stock value shown by this report is informational and is not a replacement for the accounting/inventory valuation system.** It exists to help prioritize expiry action, not to state financial value (the application follows a periodic-inventory posture with no Inventory/COGS ledger accounts).

## 2. Data Source

Current stock only — source invoices are **never** queried for availability:

| Table | Used for |
|---|---|
| `stock_batches` | batch no, expiry, MRP, purchase/net rate, **current stock (`stock_qty`)** |
| `items` | item name, company link, reorder level |
| `companies` | company name |
| `units` | unit name |

`stock_batches.stock_qty` is the report's current-availability figure (verified by test 25: changing it directly changes the report).

## 3. Expiry Formats Supported

| Format | Example | Status |
|---|---|---|
| `MM/YY` | `12/27` | **The application's format** — produced by purchase/sales screens and parsed by `StockDAO` |
| `MM/YYYY` | `12/2027` | Defensive support (not app-produced; pre-existing/hand-entered data cannot crash the report) |
| `YYYY-MM-DD` (ISO) | `2027-12-31` | Defensive support, exact date kept |

Normalization: month formats map to the **first day of the expiry month** — exactly the convention of `StockDAO._is_expired` (`datetime(2000+yy, mm, 1)`). This guarantees the report agrees with the Stock Master's Expired filter (verified by test 42).

## 4. Expired Definition

```
expired  ⇔  normalized expiry date < today
```

`today` defaults to the real current date at report time (never a hardcoded historical date). Tests inject a fixed `today` for determinism.

## 5. Expiring-Soon Definition

```
expiring_soon  ⇔  today <= normalized expiry date <= today + selected period
```

Already-expired batches are **never** classified as Expiring Soon (verified by test 8). Period options: 30 Days (default 90 is standard for this report — see §8), 60 Days, 90 Days, 6 Months (180 d), 12 Months (365 d).

## 6. Date Calculation

- Formats are parsed safely at read time; stored values are never rewritten.
- Comparison uses plain `date` arithmetic against `today`.
- A value that cannot be parsed is classified `invalid` and sorted last.

## 7. Zero-Stock Behavior

- **Default:** batches with `stock_qty <= 0` are excluded (they are not actionable for expiry).
- **Include Zero Stock** checkbox: shows them; they are then classified/summarized like any other batch.
- The summary always reflects the rows currently shown (documented in §10).

## 8. Filters

| Filter | Behavior | Default |
|---|---|---|
| Status | Expired / Expiring Soon / All | **Expiring Soon** |
| Within | 30 / 60 / 90 Days, 6 / 12 Months | **90 Days** |
| Item Name | partial match (`LIKE`) | empty (all) |
| Company | exact company id | All |
| Batch No. | partial match (`LIKE`) | empty (all) |
| Include Zero Stock | checkbox | **unchecked** |

Defaults are labeled in the page header: *"Defaults: Expiring Soon · Within 90 Days · Zero-stock batches excluded"*. **Clear** restores exactly these defaults.

## 9. Sorting

Default: **expiry ascending** (most urgent first), then item name (case-insensitive), then batch no. Unparseable/invalid expiry values sort **last**.

## 10. Summary

Computed over the currently filtered rows (so the summary matches what is on screen):

| Field | Meaning |
|---|---|
| Expired | count of expired batches in the view |
| Expiring Soon | count of expiring-soon batches in the view |
| Invalid | count of unparseable/empty expiry values in the view |
| Batches | total rows in the view |
| Total Qty | Σ `stock_qty` |
| Est. Stock Value | Σ (`stock_qty` × `purchase_rate`) — informational only |

## 11. Stock-Value Calculation

`stock_qty × purchase_rate`, i.e. the same formula the Stock screen uses (`StockDAO.get_summary`). It is the stored purchase cost of currently-held quantity. **It is not an accounting valuation** — no COGS/Inventory ledger posting exists (periodic inventory), and no FIFO/weighted-average method is applied.

## 12. Invalid / Unknown Expiry Handling

Empty, NULL, or malformed values (`"ABC"`, `"13/26"`, `"12/"`, …) never crash the report. They are:

- displayed with status **Invalid** (expiry shown as the stored text, or "Unknown" when blank),
- counted in the summary's **Invalid** field,
- excluded from the Expired and Expiring Soon classifications and counts.

## 13. Read-Only Behavior

The report performs SELECT queries only. It never changes stock quantity, deletes batches, edits expiry values, or touches purchase records (verified by tests 26–28: table counts and full row snapshots are byte-identical before/after report generation).

## 14. Relationship to Stock Master

- Same table, same expiry parsing convention (first-of-month for `MM/YY`) — the two screens agree on what is Expired.
- Stock Master is the general inventory view; this report is the expiry worklist with date-window filtering, urgency sorting, and expiry-focused summary.

## 15. Known Limitations

- **Informational stock value only** — not an accounting/inventory valuation (§11).
- The report shows batches as stored; it does not aggregate by item or dosage form.
- No reminder/alert workflow (report-only, on demand).
- Sorting/classification use the parsed date; deliberately ambiguous values (e.g. `13/26`) are treated as Invalid rather than guessed.
- Not part of Trial Balance / P&L / Balance Sheet — inventory value is outside the ledger (periodic inventory, approved Decision 5).

## 16. Running

```
python run_tests.py                    # full suite
python -m unittest test_expiry_report -v
```
