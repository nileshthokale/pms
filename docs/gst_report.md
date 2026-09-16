# GST Report — Phase 5E

**Date:** 2026-09-16
**Menu:** Reports → GST Report
**Files:** `database/gst_report_dao.py`, `screens/gst_report.py`

---

## 1. Purpose

The GST Report displays **Purchase GST** data stored in `purchase_invoices` + `purchase_invoice_items`. It shows the GST breakdown for each purchase line item and a GST Rate Summary grouped by tax percentage.

> **Important Limitation:** Sales GST data is NOT available — `sales_invoices` schema does not contain GST fields. Credit Note / Debit Note schemas also lack GST fields. This report shows **Purchase GST only**. No GST values are invented or recalculated.

## 2. Purchase GST Detail Table

For each purchase line, the report displays:

| Column | Source |
|--------|--------|
| Voucher No | `purchase_invoices.voucher_no` |
| Voucher Date | `purchase_invoices.voucher_date` |
| Invoice No | `purchase_invoices.invoice_no` |
| Invoice Date | `purchase_invoices.invoice_date` |
| Supplier Name | `suppliers.supplier_name` |
| Item Name | `items.item_name` |
| Company Name | `companies.company_name` |
| Batch No | `purchase_invoice_items.batch_no` |
| Pay Qty | `purchase_invoice_items.pay_qty` |
| Free Qty | `purchase_invoice_items.free_qty` |
| GST % | `purchase_invoice_items.gst_percent` |
| Taxable Amount | `purchase_invoice_items.amount` (stored) |
| GST Amount | `purchase_invoice_items.gst_amount` (stored) |
| Amount | `purchase_invoice_items.amount` (stored) |

## 3. GST Rate Summary Table

Grouped by `gst_percent` from `purchase_invoice_items`:

| Column | Source |
|--------|--------|
| GST % | `DISTINCT purchase_invoice_items.gst_percent` |
| Taxable Amount | `SUM(pii.amount)` |
| GST Amount | `SUM(pii.gst_amount)` |

GST % filter is populated from actual data — no hardcoded percentages.

## 4. Data Sources

The report reads from:

- `purchase_invoices` — header: voucher_no, voucher_date, invoice_no, invoice_date, supplier_id, bill_discount, gst_amount, net_amount
- `purchase_invoice_items` — line: item_id, batch_no, pay_qty, free_qty, gst_percent, gst_amount, amount
- `items` — item_name, company_id
- `companies` — company_name
- `suppliers` — supplier_name

Source documents are never modified. The report is purely read-only.

## 5. Stored GST Calculation

The report uses the stored values from PurchaseDAO — it does NOT recalculate:

```
line.amount     = (pay_qty + free_qty) × rate
line.gst_amount = round(line.amount × gst_percent / 100)
header.gst_amount = Σ line.gst_amount
header.net_amount = total_amount + gst_amount − bill_discount
                     − debit_note_amount + other_amount + round_off
```

Taxable Amount = `purchase_invoice_items.amount` (stored field, line-level `(pay_qty + free_qty) × rate`).

## 6. Date Logic

Date filtering uses `purchase_invoices.voucher_date` (same as the existing Purchase Report):

- **From Date:** `voucher_date >= from_date` (inclusive)
- **To Date:** `voucher_date <= to_date` (inclusive)
- `invoice_date` is displayed but NOT used for filtering — the application convention is to filter on `voucher_date`.

## 7. Filters

| Filter | Type | Behavior |
|--------|------|----------|
| From Date | Date (checkbox-enabled) | `voucher_date >= value` |
| To Date | Date (checkbox-enabled) | `voucher_date <= value` |
| Supplier | Combo (All / specific) | `supplier_id = value` |
| Company | Combo (All / specific) | `items.company_id = value` |
| Item | Combo (All / specific) | `item_id = value` |
| GST % | Combo (All / specific) | `gst_percent = value` |
| Invoice No | Text (partial match) | `invoice_no LIKE '%value%'` |
| Voucher No | Text (partial match) | `voucher_no LIKE '%value%'` |

All filters are optional. No filter = all data returned.

## 8. Summary Totals

| Total | Calculation |
|-------|-------------|
| Bills | Count of distinct `purchase_invoices.id` in result |
| Items | Count of line rows |
| Taxable | `SUM(purchase_invoice_items.amount)` |
| GST | `SUM(purchase_invoice_items.gst_amount)` |
| Discount | `SUM(purchase_invoices.bill_discount)` per invoice (once per invoice) |
| Net | `SUM(purchase_invoices.net_amount)` per invoice (once per invoice) |

## 9. Limitations

1. **Sales GST not available** — `sales_invoices` schema has no GST fields. Sales GST cannot be shown.
2. **Credit/Debit Note GST not available** — `credit_notes` / `debit_notes` schemas have no GST fields.
3. **No CGST/SGST/IGST breakup** — the schema stores a single `gst_percent` and `gst_amount` per line.
4. **No GST accounting postings** — the GST amount is stored at the purchase line level and flows into the Purchase ledger posting at the net level; there are no separate GST liability/input credit postings.
5. **No e-way bill or GSTR filing data** — this is an internal report, not a government filing format.

## 10. UI Layout

```
┌─────────────────────────────────────────────────────┐
│ GST Report                    Purchase GST only ... │
├─────────────────────────────────────────────────────┤
│ Sales GST not available ... │ Credit/Debit Note ... │
├─────────────────────────────────────────────────────┤
│ [From] [date] [To] [date]  Supplier [▼] Company [▼]│
│ Item [▼]  GST % [▼]  Invoice No [__] Voucher No [__]│
│                              [Search] [Clear]       │
├─────────────────────────────────────────────────────┤
│ Purchase GST                                       │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Voucher No │ Date │ Invoice │ Supplier │ ...    │ │
│ │ PV-0001    │ ...  │ INV-001 │ SupplierA│ 5% 480 │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ GST Rate Summary                                   │
│ ┌─────────────────────────────────────────────────┐ │
│ │ GST %   │ Taxable Amount │ GST Amount           │ │
│ │ 5%      │ 480.00         │ 24.00                │ │
│ │ 12%     │ 600.00         │ 72.00                │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ Bills: 1  Items: 2  Taxable: 1,080  GST: 96  Net:  │
└─────────────────────────────────────────────────────┘
```

## 11. DAO API

### `GSTReportDAO.get_purchase_gst_report(**filters) -> dict`

Returns `{"rows": [...], "summary": {...}}`.

Filters: `from_date`, `to_date`, `supplier_id`, `item_id`, `company_id`, `gst_percent`, `invoice_no`, `voucher_no`.

### `GSTReportDAO.get_gst_rate_summary(**filters) -> list[dict]`

Returns `[{"gst_percent": float, "taxable_amount": float, "gst_amount": float}, ...]` sorted by `gst_percent`.

### `GSTReportDAO.get_summary(**filters) -> dict`

Returns summary dict directly.

### `GSTReportDAO.get_filter_options() -> dict`

Returns `{"suppliers": [...], "items": [...], "companies": [...], "gst_percents": [...]}`.

## 12. Test Coverage

41 tests in `test_gst_report.py`:

| Range | Category |
|-------|----------|
| 1-4 | Basics: empty, single purchase, multiple, multiple items |
| 5-12 | Filters: dates, supplier, item, company, GST %, invoice, voucher |
| 13-19 | Totals & rate summary: single/multi invoice, empty, filtered, multiple suppliers/rates |
| 20-22 | Lifecycle: edited, deleted, persistence |
| 23-27 | Safety: read-only, no invented data, zero-rate, posting unchanged, stock unchanged |
| 28-41 | Regression: all modules, reports, masters still work |

## 13. Regression Safety

The GST Report:
- **Never writes** to any table
- **Never modifies** `accounting_posting.py`, `PostingEngine`, Trial Balance, P&L, or Balance Sheet
- **Never modifies** any source document
- Stock quantities are unaffected
- Accounting postings are unaffected

## 14. Wiring

- `screens/__init__.py` — imports `GSTReportPage`
- `ui/main_window.py` — maps `"Reports" → "GST Report"` to `GSTReportPage()`
- `ui/menu_data.py` — already contains `"GST Report"` in Reports menu

## 15. Architecture

```
database/gst_report_dao.py  ←── read-only queries
screens/gst_report.py       ←── PySide6 UI page
test_gst_report.py          ←── 41 unit tests
```

The DAO never writes. The screen never writes. Tests use their own temp database.

## 16. Related Phases

| Phase | Report | Status |
|-------|--------|--------|
| 5A | Sales Report | Completed |
| 5B | Purchase Report | Completed |
| 5C | Expiry Report | Completed |
| 5D | Party Wise Report | Completed |
| 5E | GST Report | **This phase** |
