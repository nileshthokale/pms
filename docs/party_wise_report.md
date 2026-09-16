# Party Wise Report — Phase 5D

**Date:** 2026-09-16
**Menu:** Reports → Party Wise Report
**Files:** `database/party_wise_report_dao.py`, `screens/party_wise_report.py`

---

## 1. Purpose

The Party Wise Report provides transaction summaries for Customers and Suppliers, showing operational totals from source transaction tables and outstanding balances from the mapped Account Ledger. It is a read-only report with no balance-calculation system of its own.

> **Important:** Operational totals (sales, purchases, credit notes, debit notes, receipts, payments) come from source transaction tables. Outstanding balances come from the mapped Account Ledger. Legacy balance methods (`get_customer_balance()`, `get_supplier_balance()`) are NOT used as the authoritative report balance.

## 2. Customer Report

For each customer, the report displays:

| Column | Source |
|--------|--------|
| Customer Name | `customers.customer_name` |
| City | `customers.city` |
| Contact No | `customers.contact_no` |
| Total Sales | `SUM(sales_invoices.net_amount)` within period |
| Credit Notes | `SUM(credit_notes.total_amount)` within period |
| Receipts | `SUM(customer_receipts.amount)` within period |
| Outstanding | Account Ledger closing balance (current) |

## 3. Supplier Report

For each supplier, the report displays:

| Column | Source |
|--------|--------|
| Supplier Name | `suppliers.supplier_name` |
| City | `suppliers.city` |
| Contact No | `suppliers.contact_no` |
| Total Purchases | `SUM(purchase_invoices.net_amount)` within period |
| Debit Notes | `SUM(debit_notes.total_amount)` within period |
| Payments | `SUM(supplier_payments.amount)` within period |
| Outstanding | Account Ledger closing balance (current) |

## 4. Data Sources

The report reads from the following tables:

**Customer report:**
- `customers` — party master (name, city, contact)
- `sales_invoices` — sales totals (net_amount)
- `credit_notes` — return totals (total_amount)
- `customer_receipts` — receipt totals (amount)
- `account_ledgers` + `ledger_transactions` — outstanding balance

**Supplier report:**
- `suppliers` — party master
- `purchase_invoices` — purchase totals (net_amount)
- `debit_notes` — return totals (total_amount)
- `supplier_payments` — payment totals (amount)
- `account_ledgers` + `ledger_transactions` — outstanding balance

Source documents are never modified. The report is purely read-only.

## 5. Date Logic

**Date filtering behavior:**
- **No date filter:** all parties are returned (even those with zero transactions).
- **Date filter applied:** only parties with at least one matching transaction in the period are returned.
- **From Date and To Date are inclusive.**

**Outstanding balance:**
The outstanding balance is always the **current** Account Ledger balance, regardless of the report period. This is documented Option B behavior. The report does NOT compute a period-end balance.

**Date convention:**
- `sales_invoices.sale_date` — YYYY-MM-DD text, string comparison for filtering.
- `credit_notes.voucher_date` — same format.
- `customer_receipts.receipt_date` — same format.
- `purchase_invoices.voucher_date` — same format.
- `debit_notes.voucher_date` — same format.
- `supplier_payments.payment_date` — same format.

## 6. Balance Source

**Authoritative source:** `LedgerDAO.get_balance(ledger_id)` for each party's linked Account Ledger.

The report does NOT maintain a second independent outstanding calculation. It reads from the same Account Ledger used by Trial Balance, P&L, and Balance Sheet.

Legacy balance methods (`CustomerReceiptDAO.get_customer_balance()`, `SupplierPaymentDAO.get_supplier_balance()`) are NOT used. The report explicitly ignores them.

**Accounting consistency:** Party report balances must agree with Account Ledger for the same point in time.

## 7. Customer Totals

| Total | Formula | Source Table |
|-------|---------|-------------|
| Total Sales | `SUM(net_amount)` WHERE `sale_date` in period | `sales_invoices` |
| Credit Notes | `SUM(total_amount)` WHERE `voucher_date` in period | `credit_notes` |
| Receipts | `SUM(amount)` WHERE `receipt_date` in period | `customer_receipts` |

## 8. Supplier Totals

| Total | Formula | Source Table |
|-------|---------|-------------|
| Total Purchases | `SUM(net_amount)` WHERE `voucher_date` in period | `purchase_invoices` |
| Debit Notes | `SUM(total_amount)` WHERE `voucher_date` in period | `debit_notes` |
| Payments | `SUM(amount)` WHERE `payment_date` in period | `supplier_payments` |

## 9. Outstanding Balance Treatment

- Outstanding balance comes from `LedgerDAO.get_balance(ledger_id)`.
- This is the **current** balance, not the period-end balance.
- A customer's outstanding is shown as a signed amount: positive = debit balance (we are owed), negative = credit balance.
- A supplier's outstanding is shown as a signed amount: positive = credit balance (we owe), negative = debit balance.
- The report does NOT hide the sign. Amount is displayed with its natural sign.

## 10. Ledger Relationship

Each customer has a linked Account Ledger (`customers.ledger_id` → `account_ledgers.id`).
Each supplier has a linked Account Ledger (`suppliers.ledger_id` → `account_ledgers.id`).

The ledger is created automatically by `CustomerDAO.insert()` / `SupplierDAO.insert()` with group `Sundry Debtors` / `Sundry Creditors`.

If a party has no linked ledger (`ledger_id IS NULL`), the outstanding balance is reported as 0.

## 11. Detail View

The `get_party_detail(party_type, party_id)` method returns:

```python
{
    "party_info": { ... },           # party master fields
    "ledger_info": { ... },          # account_ledgers row
    "opening_balance": float,        # ledger opening balance
    "opening_balance_type": str,     # "Debit" or "Credit"
    "closing_balance": float,        # current balance
    "closing_balance_type": str,     # "Debit" or "Credit"
    "transactions": [ ... ],         # ledger_transactions for this party
}
```

Transactions are ordered by `transaction_date, transaction_time, id`.

## 12. Filters

**Party Type:** Customer / Supplier / All

**From Date / To Date:** Date range for filtering operational totals. When both are set, only parties with transactions in that period appear.

**Party Name:** Partial, case-insensitive search. Uses `LIKE '%pattern%'`.

## 13. Summary

**Customer view summary:**
- Total Customers
- Total Sales
- Total Returns (Credit Notes)
- Total Receipts
- Total Outstanding

**Supplier view summary:**
- Total Suppliers
- Total Purchases
- Total Returns (Debit Notes)
- Total Payments
- Total Outstanding

**All view:** Shows Customer summary and Supplier summary separately (not combined into a single total, since customer and supplier outstanding amounts are in opposite directions).

## 14. Deleted / Edit Behavior

- **Deleted transactions:** Excluded from source totals. When a receipt is deleted, `total_receipts` decreases.
- **Edited transactions:** Current values reflected. When a receipt amount is edited, `total_receipts` updates.
- **Reversal rows:** Net to zero in the active-net concept. Both original and reversal rows are present in the ledger, but their net effect cancels out.

## 15. Read-Only Behavior

The report is strictly read-only:
- No data can be edited from this screen.
- The DAO methods return data only, never modify records.
- No write operations exist in the DAO.

## 16. Limitations

1. **Outstanding balance is current, not period-end.** The report does not compute what the balance was at the end of the filtered period. This is documented Option B behavior.
2. **No ageing analysis.** The report shows current outstanding only, not aging buckets.
3. **No detailed transaction drill-down in the UI.** The detail view is available via `get_party_detail()` but the UI table is summary-only.
4. **No GST separation.** Transaction amounts are gross.
5. **Party type "All" shows only the first type's summary in the UI.** The summary bar reflects the currently displayed table (customers or suppliers).

## Running

```
python run_tests.py                              # full suite (936 tests)
python -m unittest test_party_wise_report -v     # Party Wise Report tests only (46 tests)
```

The 2 UI tests (47–48) require PySide6 and skip with an explicit dependency reason in environments without it.
