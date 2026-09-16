# Sales Report — Phase 5A

**Date:** 2026-09-16
**Menu:** Reports → Sales Report
**Files:** `database/sales_report_dao.py`, `screens/sales_report.py`, `test_sales_report.py`

---

## 1. Purpose

Read-only operational report of all sales bills. It answers "what did we sell, to whom, when, and for how much" from the **sales source documents** — it is not an accounting report.

> **Relationship to accounting reports:** The Sales Report reads `sales_invoices` / `sales_invoice_items` (the transactions themselves). The Trial Balance, Profit & Loss and Balance Sheet read `ledger_transactions` (the postings the PostingEngine produced from those transactions). The two families can legitimately differ in timing/amount treatment (e.g. credit notes are separate documents; NET posting embeds discounts) and are reconciled through the ledger, not through this report.

## 2. Source Tables

Read-only; nothing is written, and no duplicate sales records are created.

| Table | Used for |
|---|---|
| `sales_invoices` | bill no, sale date, customer, patient, doctor, bill discount, net amount |
| `sales_invoice_items` | item, batch, expiry, MRP, quantity, line discount, line amount |
| `items` | item name, company link |
| `companies` | company name (filter + display) |
| `customers` | customer name (filter + display) |
| `doctors` | doctor name (filter + display) |
| `stock_batches` | batch/expiry are taken from the stored line values; the batch table is used only to resolve filter options |

## 3. Filters

All filters are optional; an empty filter matches everything.

| Filter | Behavior |
|---|---|
| From Date | inclusive lower bound on `sale_date` |
| To Date | inclusive upper bound on `sale_date` |
| Customer | exact customer id |
| Item | exact item id |
| Company | exact company id (via the item's company) |
| Bill No. | partial match (`LIKE %value%`) |
| Patient | partial match on `patient_name` |
| Doctor | exact doctor id |

In the UI, the two date bounds are optional (checkbox + date field, unchecked = no bound by default), so the initial view shows all sales; **Clear** resets every filter to empty.

## 4. Date Behavior

`sale_date` is stored as ISO `YYYY-MM-DD` TEXT; filtering uses string comparison with **inclusive** bounds:

```
from_date <= sale_date <= to_date
```

Both bounds are optional. Documented assumption: ISO text dates compare correctly as strings.

## 5. Columns

Bill No · Sale Date · Customer · Patient · Doctor · Item Name · Batch No · Expiry · MRP · Qty · Discount · Amount

All values come straight from the stored rows (no recalculation).

## 6. Totals

Computed from a single detail query; **bill-level amounts are counted once per invoice** even when the invoice has multiple lines:

| Total | Formula (stored values) |
|---|---|
| Total Bills | count of distinct invoices in the filtered rows |
| Total Items | number of sale lines |
| Total Quantity | Σ `sale_qty` |
| Total Gross Amount | Σ line (`amount` + line `discount_amount`) |
| Total Discount | Σ line `discount_amount` + Σ invoice `discount` (once per bill) |
| Total Net Amount | Σ invoice `net_amount` (once per bill) |

Note: because `net_amount = total_amount − bill discount + round_off`, the stored `round_off` can make `Gross − Discount` differ from `Net` by that stored rounding amount — this is the stored data, not a calculation error.

## 7. Performance

- One parameterized detail query (invoice × line join with LEFT JOINs for names); the summary is computed from the fetched rows — no N+1, no second aggregate round-trip for the report itself.
- Filter combos load from four small master lookups (`get_filter_options`).

## 8. Known Limitations

- **No GST/tax columns** — sales carry no tax fields (approved Decision 4a); any tax is embedded in MRP/amounts.
- **No cost/COGS columns** — periodic-inventory posture; the report is purely operational.
- **No returns** — credit notes are separate documents and do not appear here (they belong to a future returns report).
- Deleted bills disappear (their rows are deleted from the source); edited bills show the current stored state.
- Not an accounting statement — for financial figures use Trial Balance / P&L / Balance Sheet.

## 9. Running

```
python run_tests.py                       # full suite
python -m unittest test_sales_report -v   # this report's tests
```
