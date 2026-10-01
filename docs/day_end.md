# Day End Report — Phase 6B-5

**Date:** 2026-09-16
**Menu:** Sales → Day End
**Files:** `database/day_end_dao.py`, `screens/day_end.py`, `test_day_end.py`

---

> **This implementation provides a daily operational summary. It does not perform irreversible end-of-day closing or create accounting closing entries.**

## 1. Purpose

Give the pharmacy a single read-only screen that summarizes a selected business date: sales, purchases, returns, receipts, payments, cash and bank movement, and stock impact — with a printable "Day End" PDF. It is an operational view of what happened on the date, assembled from the same stored data the individual reports use.

## 2. Read-Only Design

Day End **never writes anything**:

- no closing journal entries, no ledger postings,
- no date locking, no closing markers,
- no stock changes, no ledger balance changes,
- no artificial cash difference,
- no year-end closing logic.

The DAO imports neither `accounting_posting` nor any posting engine (asserted by tests), and repeated generation returns identical results with byte-identical table contents (verified by full-table snapshots).

## 3. Business Date

- Default: **today** if today falls inside the active financial year.
- If today is outside the active FY: the **active FY end date** is used (safe default, documented).
- ADMIN and PHARMACIST/STAFF may view **any historical date**; viewing never modifies data.
- The date is validated strictly (`YYYY-MM-DD`); invalid values raise `DayEndError` (shown as a warning in the UI).

## 4. Sales

From `sales_invoices` for the selected `sale_date`: bill count, total amount, counter-sales amount (`sale_type='Cash'`), stored bill discount, stored net amount. No GST is invented for sales (sales carry no tax fields — approved Decision 4a).

## 5. Purchases

From `purchase_invoices` for the selected `voucher_date`: invoice count, line/taxable amount (`total_amount`), stored `gst_amount`, bill discount, other amount, round off, and `net_amount` — exactly the stored purchase fields; nothing recalculated.

## 6. Returns

Separately: credit-note (customer return) count and amount; debit-note (supplier return) count and amount — stored `total_amount` values for the selected `voucher_date`.

## 7. Receipts and Payments

Customer receipts: count, cash-mode amount, bank-mode amount (Bank/Cheque/UPI — the application's approved mode mapping), total. Supplier payments: the same split by `payment_mode`. No separate balance calculations are created.

## 8. Cash and Bank

Reuses the authoritative ledger system behind the Cash Book and Bank Book (`CashBookDAO.get_cash_book` / `BankBookDAO.get_bank_book` for the single selected day):

- daily debit, credit, net movement,
- opening and closing balances using the **same formulas already validated in Cash Book / Bank Book** — no new balance math.

Agreement with Cash Book/Bank Book is asserted by tests.

## 9. Stock Impact

Daily quantity movement where the data supports it: purchase quantity added (`pay_qty + free_qty`), sales quantity removed, customer-return quantity added, supplier-return quantity removed. No valuation and no COGS — the periodic-inventory posture means no reliable daily stock valuation exists, so none is invented.

## 10. Reconciliation Limitations

The report shows the related daily totals (sales net, receipts total, cash movement, bank movement). A reliable cash-drawer "difference" **cannot** be calculated from the stored data (no opening/closing physical cash counts exist), so the difference field explicitly displays:

> **"Not available from current stored data."**

No unexplained difference formula is introduced.

## 11. Financial Year

`financial_years` (managed by the existing Financial Year service) determines the safe default date. Day End does not modify the FY service or its data; historical dates can be viewed regardless of the active FY range.

## 12. Permissions

Both application roles may **view** Day End: ADMIN and PHARMACIST/STAFF. No new role is added. Printing follows normal report permissions. Viewing is always read-only.

## 13. Printing

Uses the existing `database/document_printing` service with title **"Day End"**. The print record carries the business date, and every summary section/metric/value line is included. Long output flows into multiple pages (reportlab pagination), and printing is completely read-only. The PDF can be saved via the "Print / PDF" button.

## 14. Testing

`test_day_end.py` — **98 tests**:

| Area | Coverage |
|---|---|
| Empty | empty date, historical empty date, zero stock impact |
| Sales | count, amount, counter sales, discount, net, date isolation |
| Purchases | count, amount, GST, bill discount, other amount, round off, net, no invented fields |
| Returns | credit/debit counts and amounts, separation |
| Receipts/Payments | counts, cash/bank buckets, UPI/Cheque mapping, totals |
| Cash/Bank | debit, credit, net, opening, closing, agreement with Cash Book/Bank Book, missing-ledger safety |
| Stock | purchase added, sales removed, customer/supplier return movement, no valuation |
| Dates | selected date, invalid/empty/malformed rejection, ±1-day boundaries, historical view |
| Financial Year | default within active FY, today inside FY, outside-FY fallback to FY end, historical independent |
| Read-only | full-table row-count and content snapshots, no stock/ledger/posting changes, repeated generation, balance unchanged |
| Reconciliation | section present, related totals, explicit "Not available…" difference, absent from Overall |
| Print | PDF creation (%PDF), preview contains title/date/all sections, long-report generation, size scaling, no MySQL reference, no posting-engine import |
| Regression | Cash Book, Bank Book, Sales Report, Purchase Report, Trial Balance unchanged |
| UI (PySide6) | page opens, controls present, rows render, empty-state message, read-only note (5 tests skip without PySide6; run in the development environment) |

All tests use an isolated temporary SQLite database via `PHARMACY_DB`; `data/pharmacy.db` is never touched, and no legacy/MySQL system is referenced anywhere.

## 15. Limitations

- No cash-drawer reconciliation (difference reported as unavailable — see §10).
- Stock impact is quantity-only (no valuation/COGS).
- Sales GST is not reported (sales store no tax fields).
- The screen may need a refresh (or app restart) if other users modified data concurrently.
- Day End is a summary of source documents and ledger postings; it is not a statutory closing statement.

## 16. Future Enhancements

- Optional cash-count entry to enable a real drawer-difference reconciliation.
- Shift/user-wise Day End views (once user attribution is stored on transactions).
- Print a consolidated Day End pack (Day End + Cash Book + Bank Book).
- Scheduled automatic PDF generation at a configurable closing time.

## 17. Running

```
python run_tests.py                   # full suite
python -m unittest test_day_end -v    # this report's tests
```
