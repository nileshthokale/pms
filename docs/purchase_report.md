# Purchase Report — Phase 5B

**Date:** 2026-09-16
**Menu:** Reports → Purchase Report
**Files:** `database/purchase_report_dao.py`, `screens/purchase_report.py`, `test_purchase_report.py`

---

## 1. Purpose

Read-only operational report of all purchase vouchers. It answers "what did we buy, from whom, when, in which batches, and for how much" from the **purchase source documents**.

> **Relationship to accounting reports:** The Purchase Report reads `purchase_invoices` / `purchase_invoice_items` (the transactions themselves). The Trial Balance, Profit & Loss and Balance Sheet read `ledger_transactions` (the postings the PostingEngine produced from those purchases). The two families can legitimately differ (e.g. debit notes are separate documents; NET posting absorbs discounts) and are reconciled through the ledger, not through this report.

## 2. Source Tables

Read-only; nothing is written, and no purchase records are duplicated or modified.

| Table | Used for |
|---|---|
| `purchase_invoices` | voucher no/date, invoice no/date, supplier, bill discount, net amount |
| `purchase_invoice_items` | item, pack size, batch, expiry, quantities, rates, discount, GST, amount |
| `items` | item name, company link |
| `companies` | company name (filter + display) |
| `suppliers` | supplier name (filter + display) |

Batch/expiry are shown from the stored line values (`purchase_invoice_items.batch_no` / `expiry`).

## 3. Detail Fields

Voucher No · Voucher Date · Invoice No · Invoice Date · Supplier · Item Name · Company · Pack Size · Batch No · Expiry · Pay Qty · Free Qty · Rate · MRP · Discount · GST % · GST Amount · Amount · Purchase Rate · Net Rate

All values are stored source values — nothing is recalculated.

## 4. Filters

All optional; empty filter matches everything.

| Filter | Behavior |
|---|---|
| From Date | inclusive lower bound on `voucher_date` |
| To Date | inclusive upper bound on `voucher_date` |
| Supplier | exact supplier id |
| Item | exact item id |
| Company | exact company id (via the item's company) |
| Invoice No. | partial match (`LIKE %value%`) |
| Voucher No. | partial match (`LIKE %value%`) |
| Batch No. | partial match (`LIKE %value%`) |

UI: date bounds are checkbox-optional (unchecked = no bound) so the initial view shows all vouchers; **Clear** resets everything; **Refresh** reloads combos and re-runs.

## 5. Date Behavior

Filtering uses `voucher_date` — the purchase transaction date — exactly like the existing Purchase History (`PurchaseDAO.get_all_filtered`). Inclusive bounds:

```
from_date <= voucher_date <= to_date
```

`invoice_date` (the supplier's bill date) is displayed as stored but is **not** used for filtering; the existing application does not filter on it and no new semantics were invented. ISO `YYYY-MM-DD` text comparison is used.

## 6. Summary Calculations

Computed from a single detail query; bill-level amounts counted once per invoice:

| Total | Formula (stored values) |
|---|---|
| Total Purchase Bills | count of distinct invoices in the filtered rows |
| Total Pay Qty | Σ `pay_qty` |
| Total Free Qty | Σ `free_qty` |
| Total Quantity | Σ (`pay_qty` + `free_qty`) |
| Total Gross Amount | Σ line `amount` |
| Total GST | Σ line `gst_amount` |
| Total Discount | Σ line `discount` + Σ invoice `bill_discount` (once per bill) |
| Total Net Amount | Σ invoice `net_amount` (once per bill) |

## 7. Current Purchase Calculation Representation

As recorded by `PurchaseDAO` / the purchase screen (shown, never recalculated):

```
line.amount     = (pay_qty + free_qty) × rate     # free qty IS costed;
                                                  # line discount stored
                                                  # but NOT applied
line.gst_amount = round(line.amount × gst_percent / 100)
header.total_amount = Σ line.amount
header.gst_amount   = Σ line.gst_amount
header.net_amount   = total_amount + gst_amount − bill_discount
                      − debit_note_amount + other_amount + round_off
```

Consequences visible in the report, consistent with the stored data:
- **Free quantity is costed** inside `amount` (existing behavior, kept).
- **Line `discount` is informational only** — it is displayed and summed in Total Discount but is not subtracted from `amount` (existing behavior, kept).
- **Bill discount and round-off** live on the header and are reflected only through `net_amount`.
- Therefore Gross − Discount ≠ Net in general (net also includes GST, debit-note amount, other amount, round-off) — this is the existing stored semantics, not a report error.

## 8. Relationship to Accounting Reports

This is a **source-document report**. It does not:
- write or change ledger postings,
- read `ledger_transactions`,
- affect Trial Balance / P&L / Balance Sheet.

Financial statements use the ledger postings produced by the PostingEngine (PURCHASE debit / supplier credit / cash-bank credit per the approved NET-posting rules).

## 9. Lifecycle Behavior

The report reads current stored state:
- **Deleted** purchase vouchers do not appear (their rows are removed).
- **Edited** vouchers show the updated stored values (quantities, rates, amounts, batch).
- No deleted-transaction history is shown separately.

Verified by tests 21–22.

## 10. Known Limitations

- **No GST report classification** — GST percent/amount are displayed from stored line values only (no input-tax ledger linkage; approved Decision 4a).
- **No cost/valuation reporting** — periodic inventory; the report is operational, not a COGS source.
- **Debit notes (purchase returns) are not part of this report** — they are separate documents.
- Line `discount` is stored but not applied to amounts (existing calculation — kept unchanged per the task constraints).
- Not an accounting statement — for financial figures use Trial Balance / P&L / Balance Sheet.

## 11. Running

```
python run_tests.py                        # full suite
python -m unittest test_purchase_report -v # this report's tests
```
