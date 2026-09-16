# Accounting Posting Specification — Phase 2

**Date:** 2026-09-15
**Status:** DESIGN DOCUMENT ONLY — no code, schema, or behavior changes
**Depends on:** `docs/accounting_integration_audit.md` (audit), `docs/accounting_integration_phase1.md` (party → ledger mapping)

---

## 0. Purpose and Scope

This document defines the exact accounting-posting design that a future **centralized Accounting Posting Engine** will implement. The engine must be capable of, for every supported transaction:

1. **Post** — create ledger entries in `ledger_transactions`
2. **Reverse** — create offsetting entries (or delete, per rules below)
3. **Re-post after edit** — reverse the old posting, apply the new posting
4. **Delete/reverse safely** — never leave orphaned or unbalanced ledger rows

**Nothing in this document is implemented.** Every section below separates:

- **CURRENT IMPLEMENTATION** — verified behavior in the codebase today
- **PROPOSED ACCOUNTING TREATMENT** — design for the future engine only

No application code, database schema, or transaction behavior is modified by this document.

---

## 1. Transaction Specifications

---

### A. Purchase Invoice

**CURRENT IMPLEMENTATION**

| Attribute | Current State |
|---|---|
| 1. Tables | `purchase_invoices` (header), `purchase_invoice_items` (lines), `stock_batches` (stock) |
| 2. Amount fields | Header: `invoice_net_amount`, `bill_discount`, `total_amount`, `gst_amount`, `debit_note_amount`, `other_amount`, `paid_amount`, `round_off`, `net_amount`. Line: `rate`, `mrp`, `discount`, `gst_percent`, `gst_amount`, `amount`, `purchase_rate`, `net_rate`, `pp`, `pay_qty`, `free_qty` |
| 3. Party | `supplier_id` → `suppliers(id)`; linked ledger via `suppliers.ledger_id` (Phase 1) |
| 4. Stock effect | Increases `stock_batches.stock_qty` by `pay_qty + free_qty` on insert; reversed on update/delete (`PurchaseDAO`) |
| Ledger posting | **NONE** — no write to `ledger_transactions` |

**Verified amount derivation (from `screens/purchase_invoice.py`):**

```
line.amount    = (pay_qty + free_qty) × rate          # free qty IS costed; line discount captured but NOT applied
line.gst_amount = round(line.amount × gst_percent / 100)
total_amount   = Σ line.amount                        # taxable value
gst_amount     = Σ line.gst_amount
net_amount     = total_amount + gst_amount − bill_discount − debit_note_amount + other_amount + round_off
```

Note: `invoice_net_amount` is a manually entered informational field (supplier's own invoice total); it is not used in any calculation. `purchase_type` ∈ {Credit, Cash, Credit Card}.

**PROPOSED ACCOUNTING TREATMENT**

| # | Item | Proposal |
|---|---|---|
| 5 | Debit | Purchase Account for `total_amount` (taxable value); GST Input Account for `gst_amount` |
| 6 | Credit | Supplier Ledger for `net_amount − paid_amount` (credit portion); Cash/Bank for `paid_amount` (per `purchase_type` mapping) |
| 7 | Amount determined by | `total_amount` (Σ line amounts), `gst_amount`, `paid_amount`, `net_amount`; sign adjustments for `bill_discount` (Debit: Discount Received or reduce Purchase), `other_amount` (Debit: Other Expense or Credit: Other Income — **decision required**), `round_off` (Round-Off account) |

**8. Example journal entry** (Credit purchase, total 1000.00, GST 50.00, bill discount 20.00, paid 500.00, round_off 0.00 → net = 1030.00):

| Ledger | Debit | Credit |
|---|---|---|
| Purchase Account | 1000.00 | |
| GST Input Account | 50.00 | |
| Discount Received (or Purchase reduced) | 20.00 | |
| Supplier Ledger ("Supplier - X") | | 530.00 |
| Cash Account | | 500.00 |
| **Total** | **1070.00** | **1030.00** |

⚠️ The example above does **not** balance — this is exactly the open question: how `bill_discount` and `other_amount` enter the entry must be decided (see §9 Discounts and §17 Accounting Risks). A consistent variant that always balances is: Debit Purchase `total_amount + gst_amount`; Credit Supplier `net_amount − paid_amount` + Cash `paid_amount`, with `bill_discount`/`other_amount`/`round_off` absorbed into the Purchase-side amount. **Final rule to be decided before implementation.**

**9. Reverse behavior** — insert mirrored rows (swap debit/credit) linked to the same `reference_type`/`reference_id`, OR delete the original rows if no closing balance/reporting period dependency exists. Recommended: mirrored reversal rows (preserves audit trail).

**10. Edit behavior** — `update_invoice()` replaces items and header in one transaction. The engine must: reverse the posting of the pre-edit invoice → post the new amounts, inside the same DB transaction as the edit.

**11. Delete behavior** — `delete_invoice()` reverses stock and removes rows. The engine must reverse (or delete) the associated ledger posting in the same transaction.

**12. Missing configuration/account information**
- No Purchase Account exists/linked
- No GST Input account
- No Discount Received account
- No Other Expense/Other Income accounts
- No Round-Off account
- No `purchase_type` → Cash/Bank ledger mapping (Cash vs Credit Card vs Credit)
- Free-quantity costing policy undefined (free units currently increase the posted cost because `amount` includes `free_qty × rate`)

---

### B. Counter Sale

**CURRENT IMPLEMENTATION**

| Attribute | Current State |
|---|---|
| 1. Tables | `sales_invoices` (header), `sales_invoice_items` (lines), `stock_batches` (stock) |
| 2. Amount fields | Header: `discount` (bill discount), `paid_amount`, `total_amount`, `round_off`, `net_amount`. Line: `mrp`, `sale_qty`, `discount_amount`, `amount` |
| 3. Party | `customer_id` → `customers(id)` (nullable — cash walk-in may have none); linked ledger via `customers.ledger_id` |
| 4. Stock effect | Decreases `stock_batches.stock_qty` on insert; restored on delete (`SalesDAO`) |
| Ledger posting | **NONE** |

**Verified amount derivation (from `screens/counter_sale.py`):**

```
line.amount  = mrp × sale_qty − discount_amount       # line discount
total_amount = Σ line.amount
net_amount   = total_amount − discount(bill) + round_off
```

**There are NO GST/tax fields on sales** — `sales_invoices` and `sales_invoice_items` contain no tax columns. `sale_type` ∈ {Cash, Credit, Credit Card}.

**PROPOSED ACCOUNTING TREATMENT**

| # | Item | Proposal |
|---|---|---|
| 5 | Debit | Cash/Bank (per `sale_type` mapping) for `paid_amount`; Customer Ledger for `net_amount − paid_amount` (credit portion) |
| 6 | Credit | Sales Account for `net_amount` (with bill `discount` either debited to Discount Allowed or netted against Sales — **decision required**) |
| 7 | Amount determined by | `paid_amount`, `net_amount`, `total_amount`, `discount`, `round_off` |

**8. Example journal entry** (Credit sale, net 1180.00, paid 680.00):

| Ledger | Debit | Credit |
|---|---|---|
| Cash Account | 680.00 | |
| Customer Ledger ("Customer - Y") | 500.00 | |
| Sales Account | | 1180.00 |
| **Total** | **1180.00** | **1180.00** |

With a separate Discount Allowed account (decision variant):

| Ledger | Debit | Credit |
|---|---|---|
| Cash | 680.00 | |
| Customer Ledger | 500.00 | |
| Discount Allowed | 20.00 | |
| Sales Account (gross) | | 1200.00 |

**9. Reverse behavior** — mirrored reversal rows (recommended), same reference identity.

**10. Edit behavior** — sales currently have **no update path in `SalesDAO`** (only insert/delete). If edit is added later, it must follow reverse-old → post-new. The engine design supports it regardless.

**11. Delete behavior** — reverse/delete the posting in the same transaction as `delete_invoice()` (which restores stock).

**12. Missing configuration/account information**
- No Sales Account
- No Discount Allowed account
- No `sale_type` → Cash/Bank account mapping (Cash vs Credit Card)
- Cash walk-in sales with `customer_id = NULL` have no party ledger — posting target for the credit portion must be defined (default customer ledger or Cash-only sales assumed fully paid)
- No GST output tax on sales (see §8)

---

### C. Customer Credit Note

**CURRENT IMPLEMENTATION**

| Attribute | Current State |
|---|---|
| 1. Tables | `credit_notes` (header), `credit_note_items` (lines) |
| 2. Amount fields | Header: `total_amount`, `ledger_amount`. Line: `rate`, `mrp`, `return_qty`, `less_amount`, `amount`, `price_factor` |
| 3. Party | `customer_id` → `customers(id)` (NOT NULL); ledger via `customers.ledger_id` |
| 4. Stock effect | Increases `stock_batches.stock_qty` by `return_qty` (goods returned to stock) |
| Ledger posting | **NONE**. Included in `CustomerReceiptDAO.get_customer_balance()` as a deduction |

**PROPOSED ACCOUNTING TREATMENT**

| # | Item | Proposal |
|---|---|---|
| 5 | Debit | Sales Return Account |
| 6 | Credit | Customer Ledger ("Customer - {name}") |
| 7 | Amount determined by | `total_amount` (Σ line `amount`). `ledger_amount` exists but its meaning vs `total_amount` is ambiguous — **decision required** which one posts (see §17) |

**8. Example journal entry** (return, total 150.00):

| Ledger | Debit | Credit |
|---|---|---|
| Sales Return Account | 150.00 | |
| Customer Ledger | | 150.00 |

**9. Reverse behavior** — mirrored rows (Debit Customer / Credit Sales Return).
**10. Edit behavior** — `update_credit_note()` replaces items/header; engine must reverse old posting then post new, atomically with the edit.
**11. Delete behavior** — reverse/delete posting in the same transaction as `delete_credit_note()`.

**12. Missing configuration/account information**
- No Sales Return account
- `ledger_amount` vs `total_amount` semantics undefined
- `less_amount` (line-level deduction) treatment undefined (see §9)
- No GST adjustment fields on returns while purchases carry GST — asymmetric (see §8)

---

### D. Supplier Debit Note

**CURRENT IMPLEMENTATION**

| Attribute | Current State |
|---|---|
| 1. Tables | `debit_notes` (header), `debit_note_items` (lines) |
| 2. Amount fields | Header: `total_amount`, `ledger_amount`. Line: `rate`, `mrp`, `return_qty`, `less_amount`, `amount`, `price_factor` |
| 3. Party | `supplier_id` → `suppliers(id)` (NOT NULL); ledger via `suppliers.ledger_id` |
| 4. Stock effect | Decreases `stock_batches.stock_qty` by `return_qty` (goods returned to supplier) |
| Ledger posting | **NONE**. Included in `SupplierPaymentDAO.get_supplier_balance()` as a deduction |

**PROPOSED ACCOUNTING TREATMENT**

| # | Item | Proposal |
|---|---|---|
| 5 | Debit | Supplier Ledger ("Supplier - {name}") |
| 6 | Credit | Purchase Return Account |
| 7 | Amount determined by | `total_amount` (Σ line `amount`); same `ledger_amount` ambiguity as credit notes |

**8. Example journal entry** (return to supplier, total 200.00):

| Ledger | Debit | Credit |
|---|---|---|
| Supplier Ledger | 200.00 | |
| Purchase Return Account | | 200.00 |

**9. Reverse behavior** — mirrored rows (Debit Purchase Return / Credit Supplier).
**10. Edit behavior** — reverse old + post new, atomically with `update_debit_note()`.
**11. Delete behavior** — reverse/delete posting atomically with `delete_debit_note()`.

**12. Missing configuration/account information**
- No Purchase Return account
- `ledger_amount` semantics undefined
- No GST reversal fields (input tax credit adjustment) — see §8

---

### E. Supplier Payment

**CURRENT IMPLEMENTATION**

| Attribute | Current State |
|---|---|
| 1. Tables | `supplier_payments` (single table, no detail) |
| 2. Amount fields | `amount` (single value), `payment_mode` ∈ {Cash, Bank, Cheque, UPI}, `reference_no` |
| 3. Party | `supplier_id` → `suppliers(id)` (NOT NULL); ledger via `suppliers.ledger_id` |
| 4. Stock effect | None |
| Ledger posting | **NONE**. Deducted in `get_supplier_balance()` |

**PROPOSED ACCOUNTING TREATMENT**

| # | Item | Proposal |
|---|---|---|
| 5 | Debit | Supplier Ledger |
| 6 | Credit | Cash/Bank/Cheque/UPI account per `payment_mode` mapping (see §6) |
| 7 | Amount determined by | `amount` |

**8. Example journal entry** (payment 400.00 by Cheque):

| Ledger | Debit | Credit |
|---|---|---|
| Supplier Ledger | 400.00 | |
| Cheque/Bank Account | | 400.00 |

**9. Reverse behavior** — mirrored rows.
**10. Edit behavior** — reverse old + post new atomically with `update_payment()` (mode/amount/date may change).
**11. Delete behavior** — reverse/delete posting atomically with `delete_payment()`.

**12. Missing configuration/account information**
- No payment_mode → ledger account mapping (Cash / Bank / Cheque / UPI accounts do not exist)
- No invoice-level allocation (payment is on-account, not against specific invoices) — acceptable for ledger posting but limits ageing/statement reporting

---

### F. Customer Receipt

**CURRENT IMPLEMENTATION**

| Attribute | Current State |
|---|---|
| 1. Tables | `customer_receipts` (single table, no detail) |
| 2. Amount fields | `amount` (single value), `receipt_mode` ∈ {Cash, Bank, Cheque, UPI}, `reference_no` |
| 3. Party | `customer_id` → `customers(id)` (NOT NULL); ledger via `customers.ledger_id` |
| 4. Stock effect | None |
| Ledger posting | **NONE**. Deducted in `get_customer_balance()` |

**PROPOSED ACCOUNTING TREATMENT**

| # | Item | Proposal |
|---|---|---|
| 5 | Debit | Cash/Bank/Cheque/UPI account per `receipt_mode` mapping |
| 6 | Credit | Customer Ledger |
| 7 | Amount determined by | `amount` |

**8. Example journal entry** (receipt 300.00 via UPI):

| Ledger | Debit | Credit |
|---|---|---|
| UPI/Bank Account | 300.00 | |
| Customer Ledger | | 300.00 |

**9. Reverse behavior** — mirrored rows.
**10. Edit behavior** — reverse old + post new atomically with `update_receipt()`.
**11. Delete behavior** — reverse/delete posting atomically with `delete_receipt()`.

**12. Missing configuration/account information**
- No receipt_mode → ledger account mapping
- No invoice-level allocation (on-account receipt)

---

### G. Journal Entry

**CURRENT IMPLEMENTATION**

| Attribute | Current State |
|---|---|
| 1. Tables | `journal_entries` (header), `journal_entry_items` (lines with `ledger_id`, `debit`, `credit`) |
| 2. Amount fields | Per-line `debit` / `credit`; balanced enforced (`total_debit == total_credit`, tolerance 0.001) |
| 3. Party | Lines reference `ledger_id` → `account_ledgers(id)` directly |
| 4. Stock effect | None |
| Ledger posting | **ISOLATED** — stored only in `journal_entries`/`journal_entry_items`; never written to `ledger_transactions`. Account Ledger detail screen will not show journal entries |

**PROPOSED ACCOUNTING TREATMENT**

Journal Entry is already a balanced, ledger-referenced voucher. The engine should treat it as a first-class posting source:

- On insert: write one `ledger_transactions` row per `journal_entry_item` (`voucher_type='JV'`, `voucher_no`, `reference_type='journal_entry'`, `reference_id=entry_id`, same date, line description, line debit/credit).
- Current storage (`journal_entry_items`) becomes the **source voucher**; `ledger_transactions` becomes the **posted representation**. Both exist; posting rows are derived and reversible.
- On update: delete/replace derived rows for `reference_type='journal_entry' AND reference_id=entry_id`, then re-insert from new items.
- On delete: delete derived rows.

**8. Example** — manual JV: Debit Rent 1000 / Credit Cash 1000 produces two `ledger_transactions` rows.

**9–11. Reverse/Edit/Delete** — as above (replace-derived-rows strategy; journals are the one source type where delete-and-repost of derived rows is safe because the full line detail remains in `journal_entry_items`).

**12. Missing configuration**
- None for journals themselves; all lines already carry explicit `ledger_id`. Only the posting hook is missing.

---

## 2. Required Ledger Accounts

`account_ledgers.account_group` is a free-text field. Currently guaranteed account groups in code: `Sundry Debtors` (auto-created per customer) and `Sundry Creditors` (auto-created per supplier). **No other accounts are created by the application.**

| Account | Category | Exists today? | Needs creating/config? | System role needed? |
|---|---|---|---|---|
| Cash | Cash | **No** | Yes — must be created and designated | **Yes** — posting target for all cash-mode receipts/payments and cash sales/purchases |
| Bank | Bank | **No** | Yes | **Yes** — target for Bank/UPI modes (or separate UPI account) |
| Cheque | Bank/Cash-equivalent | **No** | Yes — decide: separate Cheque-in-Hand account or map to Bank | **Yes** if separate |
| Customer ledgers | Sundry Debtors | **Yes** — auto-created per customer (Phase 1) | No — but every customer must have `ledger_id` non-null (legacy rows may be NULL if migration not run) | Yes — party ledger, auto-managed |
| Supplier ledgers | Sundry Creditors | **Yes** — auto-created per supplier (Phase 1) | Same as above | Yes — party ledger, auto-managed |
| Sales | Income | **No** | Yes | **Yes** — posting target for counter sales |
| Purchase | Expense/COGS | **No** | Yes | **Yes** — posting target for purchases |
| Sales Return | Income (contra) | **No** | Yes | **Yes** |
| Purchase Return | Expense (contra) | **No** | Yes | **Yes** |
| Inventory / Stock | Asset | **No** | Only if perpetual inventory is chosen (see §7) | Only under that decision |
| GST Input (Purchase tax) | Asset (current) | **No** | Yes if purchase GST is posted | **Yes** |
| GST Output (Sales tax) | Liability | **No** | **Blocked** — sales carry no tax data (see §8) | Future |
| Discount Allowed | Expense | **No** | Yes (decision: separate account vs netting) | **Yes** if separate |
| Discount Received | Income | **No** | Yes (same decision) | **Yes** if separate |
| Round-Off | Expense/Income | **No** | Yes | **Yes** |
| Other Expense / Other Income | Exp/Inc | **No** | Yes — target for purchase `other_amount` | **Yes** |

**System-role mechanism (proposed, not implemented):** a configuration mapping (e.g., `account_role → ledger_id`, stored in a settings table or config file) designating which ledger fills each role. The engine resolves roles → concrete `account_ledgers.id` at posting time. No such mechanism exists today.

---

## 3. Cash / Bank / Cheque / UPI Determination

**CURRENT IMPLEMENTATION**

- `supplier_payments.payment_mode` and `customer_receipts.receipt_mode` store one of: `Cash`, `Bank`, `Cheque`, `UPI` (combo boxes in `screens/supplier_payment.py:230` and `screens/customer_receipt.py:230`). `reference_no` holds Cheque/UPI reference text.
- Counter sale `sale_type` ∈ {Cash, Credit, Credit Card}; purchase `purchase_type` ∈ {Credit, Cash, Credit Card}. These are **labels only** — nothing maps them to any ledger.

**PROPOSED DETERMINATION (future engine)**

| Transaction | Field | Mapping required |
|---|---|---|
| Supplier Payment | `payment_mode` | Cash→Cash A/c, Bank→Bank A/c, Cheque→Cheque/Bank A/c, UPI→UPI/Bank A/c |
| Customer Receipt | `receipt_mode` | Same as above |
| Counter Sale (paid portion) | `sale_type` + `paid_amount` | Cash→Cash A/c; Credit Card→Bank/card A/c; Credit→paid portion still needs a mode (currently **unknown** — see below) |
| Purchase Invoice (paid portion) | `purchase_type` + `paid_amount` | Cash→Cash A/c; Credit Card→Bank/card A/c |

**MISSING PAYMENT-ACCOUNT CONFIGURATION (documented, not implemented):**
1. No Cash account, Bank account, Cheque account, or UPI account exists.
2. No mode → account mapping mechanism exists.
3. `sale_type`/`purchase_type` "Credit" does not record **how** any `paid_amount` was paid (cash vs card) — a credit-type invoice with partial payment has no instrument information. **Unresolved.**
4. Cheque clearing/confirmation workflow does not exist (a cheque receipt is indistinguishable from realized money once posted).

---

## 4. Customer Transactions & Party Ledger

**CURRENT IMPLEMENTATION**

- Every customer created via `CustomerDAO.insert()` gets a linked ledger "Customer - {name}" (group `Sundry Debtors`); `customers.ledger_id` may be NULL for pre-Phase-1 rows if `migrate_ledger_mapping.run_migration()` was never run.
- Customer outstanding balance today = `CustomerReceiptDAO.get_customer_balance()`: `Σ sales.net_amount − Σ credit_notes.total_amount − Σ receipts.amount` (opening_balance **ignored**). This is completely independent of ledger balances.

**PROPOSED ACCOUNTING TREATMENT**

- **Counter Sale**: credit portion (`net_amount − paid_amount`) posts to the customer's mapped ledger as a Debit (customer owes us). Cash sales with `customer_id = NULL` have no ledger — requires a default-cash-customer decision or mandatory paid-in-full treatment.
- **Credit Note**: posts as a Credit to the customer ledger (reduces what they owe).
- **Customer Receipt**: posts as a Credit... reversed — posts as a **Debit to Cash/Bank** and **Credit to the customer ledger** (settles receivable).
- Net effect after full posting: `LedgerDAO.get_balance(customer_ledger).closing_balance` (Debit) should equal the current `get_customer_balance()` **plus** migrated opening balance. The two systems will disagree until (a) opening balances are posted and (b) the legacy method is retired (Phase 3 decision).

---

## 5. Supplier Transactions & Party Ledger

**CURRENT IMPLEMENTATION**

- Every supplier gets "Supplier - {name}" (group `Sundry Creditors`); `suppliers.ledger_id` may be NULL pre-migration.
- Supplier outstanding balance = `SupplierPaymentDAO.get_supplier_balance()`: `Σ purchases.net_amount − Σ debit_notes.total_amount − Σ payments.amount` (opening_balance ignored). Independent of ledger balances.

**PROPOSED ACCOUNTING TREATMENT**

- **Purchase Invoice**: credit portion (`net_amount − paid_amount`) posts as a **Credit** to the supplier ledger (we owe them).
- **Debit Note**: posts as a **Debit** to the supplier ledger (reduces what we owe).
- **Supplier Payment**: Debit supplier ledger, Credit Cash/Bank.
- Same reconciliation issue as customers: ledger balance vs legacy formula will differ until opening balances are migrated and the legacy method retired.

---

## 6. Stock Accounting

**CURRENT IMPLEMENTATION — what information exists**

- `stock_batches` holds per-batch `purchase_rate`, `net_rate`, `mrp`, `stock_qty`. Quantities change with every purchase/sale/credit note/debit note.
- Purchase lines carry cost data: `rate`, `amount` (includes free qty), `purchase_rate`, `net_rate`, `pp`.
- Sales lines carry only `mrp`, `sale_qty`, `discount_amount`, `amount` — **no cost of the sold goods is stored on the sale line**.
- No stock valuation report, no COGS calculation, no stock account, no opening stock value exists anywhere.

**PROPOSED TREATMENT / FINDING**

Two standard options exist — (a) **periodic inventory**: no posting at sale time; stock value computed at period end; (b) **perpetual inventory**: Debit Inventory on purchase (instead of Purchase expense), Credit Inventory + Debit COGS on sale.

**MISSING INFORMATION — explicit statement:**

> **The current system does not contain enough information for reliable perpetual inventory accounting.**
>
> 1. Sales lines do not record the cost (purchase_rate) of the batch at time of sale — COGS cannot be derived historically.
> 2. There is no opening stock valuation.
> 3. `stock_batches.net_rate`/`purchase_rate` change on every purchase of the same batch, so current batch rates are not a reliable historical cost.
> 4. Free quantity is included in purchase line `amount` but adds zero cash cost in some supplier arrangements — policy undefined.

**Recommended Phase-2 stance (decision required): periodic inventory.** Post purchases to a Purchase account (expense), do NOT post inventory/COGS at sale time. Stock value reporting stays outside the ledger until the missing information is captured (e.g., snapshotting batch cost on each sale line in a later phase).

---

## 7. GST / Tax

**CURRENT IMPLEMENTATION**

- **Purchases only**: line-level `gst_percent`, `gst_amount`; header `gst_amount` = Σ lines. GST is added on top of line amount: `gst_amount = amount × gst_percent / 100`.
- **Sales: NO GST fields at all** — `sales_invoices`/`sales_invoice_items` have no tax columns. Selling prices are presumably tax-inclusive or tax-ignored; the system does not record it.
- **Credit/debit notes: no GST adjustment fields.**
- No tax configuration, no GSTIN-linked tax ledger, no input/output tax accounts, no tax report exists.

**PROPOSED MAPPING (purchases only, decision required)**

- Debit **GST Input Account** for header `gst_amount` at purchase posting; credit it (or a GST Input reversal) when a supplier debit note reverses tax — **but debit notes carry no tax split today**, so exact reversal of GST on returns is **not possible** (see risk §17).

**MISSING GST CONFIGURATION — explicit statement:**

> 1. No GST Input account exists.
> 2. **No GST Output account can be used because sales record no tax** — output tax liability cannot be computed from existing data. If the business charges GST on sales, that data is simply absent.
> 3. Tax-inclusive vs tax-exclusive pricing on sales is undocumented.
> 4. Debit/credit notes have no tax component, so tax on returns cannot be reversed accurately.
> 5. No intra-state (CGST/SGST) vs inter-state (IGST) split is recorded — only a single `gst_percent`.

**Recommendation: do not post GST ledgers until sales-side tax capture exists; otherwise the trial balance will show input tax with no output tax — an incorrect financial picture.** A safe interim: post purchases gross to Purchase account without tax split, flagged as an explicit accounting decision.

---

## 8. Discounts and Deductions — Current Information Inventory

| Field | Where | Current semantics (verified) | Enough info for accounting? |
|---|---|---|---|
| **Line discount** (purchase) | `purchase_invoice_items.discount` | Captured per line but **NOT applied** — line `amount = (pay_qty+free_qty) × rate` regardless of discount (`screens/purchase_invoice.py:633`) | **No** — field is dead in the amount math; posting `amount` as-is is consistent, but the discount value itself is unreliable |
| **Line discount** (sale) | `sales_invoice_items.discount_amount` | Applied: `amount = mrp × qty − discount_amount` | **Yes** — already embedded in line amount; separate Discount Allowed posting would require re-deriving Σ discount_amount (possible) |
| **Bill discount** (purchase) | `purchase_invoices.bill_discount` | Subtracted in `net_amount` formula | **Yes** — value available; needs Discount Received account or Purchase-netting decision |
| **Bill discount** (sale) | `sales_invoices.discount` | Subtracted in `net_amount` | **Yes** — same decision needed (Discount Allowed vs Sales-netting) |
| **Less amount** | `credit_note_items.less_amount`, `debit_note_items.less_amount` | Stored per line; effect on line `amount` is computed by the UI at entry time and embedded in `amount` — but the exact formula is **not verifiable from the DAO** (UI passes final `amount`) | **Partially** — line `amount` is authoritative; standalone `less_amount` treatment for a separate ledger line is **not defined** |
| **Other amount** | `purchase_invoices.other_amount` | Added in `net_amount` formula (+) | **Partially** — value available, but **sign/meaning is ambiguous** (an addition — is it freight/expense charged by supplier?) and no expense-category field exists |
| **Round off** | `purchase_invoices.round_off`, `sales_invoices.round_off` | Balancing figure to round `net_amount` | **Yes** — needs Round-Off account |

**No new accounting rules are created here** — these are open decisions to finalize before implementation.

---

## 9. Journal Entry ↔ ledger_transactions Integration

**CURRENT:** `journal_entries`/`journal_entry_items` store balanced manual vouchers. They are **never** reflected in `ledger_transactions`; `LedgerDAO.get_balance()` and the Account Ledger detail screen ignore them entirely.

**PROPOSED:** journal entry becomes a posting source (Section 1G): each line item is projected into `ledger_transactions` with `reference_type='journal_entry'`, `reference_id=<entry id>`. The journal tables remain the editable voucher of record; `ledger_transactions` rows are derived data that are replaced on update and removed on delete. This preserves current storage exactly and adds only the projection.

---

## 10. Idempotency

**CURRENT:** `ledger_transactions` already has `reference_type` (TEXT) and `reference_id` (INTEGER) columns — currently written by nothing except direct `LedgerDAO.add_transaction()` calls with caller-supplied values. **No UNIQUE constraint** exists on the pair.

**PROPOSED TRANSACTION IDENTITY**

```
source_type  → reference_type   ('purchase_invoice' | 'sales_invoice' | 'credit_note'
                                 | 'debit_note' | 'supplier_payment'
                                 | 'customer_receipt' | 'journal_entry')
source_id    → reference_id     (the source table's id)
```

**Rules for the future engine (design only):**
1. Before posting, query `ledger_transactions WHERE reference_type = ? AND reference_id = ?`. If active (non-reversed) rows exist → **refuse duplicate posting**.
2. Every posting writes `reference_type` + `reference_id` on **every row** it creates. No exceptions.
3. A reversal also carries the same identity plus a marker distinguishing it (either a `voucher_type` suffix like `PURCHASE-REVERSAL`, a paired reversal flag, or a `reverses_posting` grouping id — **schema decision for implementation phase**).
4. Locate-for-reversal = same query as (1). Reverse = insert mirrored rows with same identity.
5. Recommended hardening (future schema change, not now): `UNIQUE(reference_type, reference_id, voucher_type)` or a posting-run table to make the guard database-enforced rather than query-enforced.

Because the columns already exist, **no schema change is required** for the basic engine — only disciplined use and (optionally, later) a uniqueness constraint.

---

## 11. Atomicity

**CURRENT:** every source DAO (`purchase_dao`, `sales_dao`, `credit_note_dao`, `debit_note_dao`, `supplier_payment_dao`, `customer_receipt_dao`, `journal_dao`) already wraps its write operations in `BEGIN … COMMIT / ROLLBACK` on a single connection. Stock adjustments are atomic with the voucher. Ledger posting does not exist yet.

**REQUIRED FUTURE BEHAVIOR**

| Operation | Requirement |
|---|---|
| Insert (post) | Source voucher rows + all `ledger_transactions` rows committed in **one DB transaction**. SUCCESS = source saved + posting saved. FAILURE = both roll back. |
| Update (re-post) | In one transaction: write updated source → reverse old posting rows → insert new posting rows. Any failure rolls back everything (source edit included). |
| Delete | In one transaction: reverse (or delete) posting rows → delete source rows. Failure rolls back both. |
| Reverse API | In one transaction: insert mirrored rows for the identity. Never partially reverses a multi-row posting. |

**Implementation note (design):** the engine must accept an **open connection/cursor** from the calling DAO rather than opening its own, so posting joins the caller's transaction. All current DAOs open/close their own connection per call, so wiring point is inside each DAO's existing transaction block. Multi-line postings must be verified balanced (Σdebit = Σcredit) before commit.

---

## 12. Posting Engine API (Proposed — DO NOT IMPLEMENT)

```python
class PostingEngine:
    """Future centralized accounting posting engine — DESIGN ONLY."""

    def post_purchase(self, invoice_id: int, conn=None) -> PostingResult: ...
    def post_sale(self, invoice_id: int, conn=None) -> PostingResult: ...
    def post_credit_note(self, note_id: int, conn=None) -> PostingResult: ...
    def post_debit_note(self, note_id: int, conn=None) -> PostingResult: ...
    def post_supplier_payment(self, payment_id: int, conn=None) -> PostingResult: ...
    def post_customer_receipt(self, receipt_id: int, conn=None) -> PostingResult: ...
    def post_journal_entry(self, entry_id: int, conn=None) -> PostingResult: ...

    def reverse(self, source_type: str, source_id: int, conn=None) -> PostingResult: ...

    def repost(self, source_type: str, source_id: int, conn=None) -> PostingResult:
        """reverse() + post_<type>() in one transaction — used after edit."""

    def get_posting(self, source_type: str, source_id: int) -> PostingView | None: ...
    def is_posted(self, source_type: str, source_id: int) -> bool: ...
```

- `conn=None` means the engine opens its own transaction; a passed `conn` joins the caller's transaction (atomicity, §11).
- `PostingResult` carries: posted row ids, voucher_no, per-ledger lines, and success/failure reason.
- Every `post_*` must: resolve config roles (§13) → build balanced lines → check idempotency (§10) → insert rows with identity.
- Per-transaction behaviors (reverse/edit/delete) follow §1A–1G.

---

## 13. Configuration Requirements (Before Automatic Posting Can Operate)

Nothing below exists yet; all must be configurable (UI deferred):

1. **Account role map** — role → `account_ledgers.id`:
   - Cash account *(mandatory)*
   - Bank account *(mandatory if Bank/UPI modes used)*
   - Cheque account or explicit Cheque→Bank mapping
   - UPI account or explicit UPI→Bank mapping
   - Sales account *(mandatory)*
   - Purchase account *(mandatory)*
   - Sales Return account
   - Purchase Return account
   - GST Input account (only if GST posting is enabled — blocked by §7 gaps)
   - Discount Allowed account (or "net against Sales" policy flag)
   - Discount Received account (or "net against Purchase" policy flag)
   - Round-Off account
   - Other Expense / Other Income accounts for `other_amount`
   - Inventory/COGS accounts (only if perpetual inventory chosen — blocked by §6 gaps)
2. **Mode maps**: `payment_mode`/`receipt_mode` value → role; `sale_type`/`purchase_type` value → role (incl. how "Credit"-type partial payments are allocated — unresolved).
3. **Policies**: reversal strategy (mirror rows vs delete); `bill_discount`/`other_amount` posting treatment; `total_amount` vs `ledger_amount` on notes; walk-in (`customer_id IS NULL`) sale handling; free-qty costing policy.
4. **Posting on/off switch** per transaction type (safe rollout).
5. **Opening balances**: decision on migrating `customers.opening_balance`/`suppliers.opening_balance` (already copied into ledgers by Phase 1 migration) and opening balances for Cash/Bank/Sales/Purchase accounts before the first posting period.
6. **Legacy balance cutover**: when screens switch from `get_customer_balance()`/`get_supplier_balance()` to `LedgerDAO.get_balance()`.

---

## 14. Trial Balance Readiness

The proposed structure (all postings → `ledger_transactions`, identity-tagged, balanced per voucher) **will support**:

- **Trial Balance**: Σ debit vs Σ credit per ledger over `ledger_transactions` + opening balances — directly computable. Balanced-by-construction if every engine posting is validated balanced.
- **Profit & Loss**: requires classifying ledgers into Income vs Expense. **Current gap:** `account_group` is free text with no chart-of-accounts classification list — groups like "Sales", "Purchase Account", "Discount" don't exist. A group→statement-section classification (or fixed group vocabulary) is **missing information**.
- **Balance Sheet**: requires Asset/Liability classification (Cash, Bank, Sundry Debtors, Sundry Creditors) and **closing stock value** — stock valuation is not in the ledger (see §6), so a complete Balance Sheet needs either a periodic stock valuation input or a manual closing-stock journal. **Missing information documented.**

Other gaps affecting all three statements: opening balances for non-party accounts (none exist), and the sales-side GST absence (§7) which would misstate tax liability if input tax were posted.

---

## 15. Accounting Risks

Implementing automatic posting **now**, without resolving the following, would produce incorrect financial statements:

1. **Purchase `bill_discount`/`other_amount` treatment undefined** — an unbalanced or misclassified entry is possible (see §1A example imbalance).
2. **Sales have no tax data** — posting GST input without output tax overstates assets/understates liability.
3. **`ledger_amount` vs `total_amount` ambiguity** on credit/debit notes — posting the wrong one misstates both party balance and returns.
4. **Free quantity included in purchase line amount** — cost of goods inflated or deflated depending on supplier arrangement; policy undefined.
5. **Purchase line `discount` captured but not applied** — any future logic that "re-derives" amounts using discount would contradict the stored `amount`.
6. **"Credit"-type invoices with partial `paid_amount` have no instrument** — cash vs bank for the paid portion is a guess.
7. **No stock valuation / COGS data** — perpetual inventory posting would be fiction; Balance Sheet incomplete under periodic too (needs closing stock input).
8. **`other_amount` sign ambiguity** — added positively in the net formula; meaning (expense charged? income?) unknown.
9. **Cheque/UPI receipts posted as realized money** — no clearing concept; bank balance may be overstated for bounced cheques.
10. **Three conflicting balance systems during transition** — legacy formula, ledger balance, and master `opening_balance` fields; screens showing different numbers for the same party until cutover.
11. **Walk-in sales (`customer_id IS NULL`)** — no ledger target for any credit portion; must be forced fully-paid or mapped to a default cash customer.
12. **Reversal of edited/deleted period-closed vouchers** — no period-lock concept; users can edit/delete posted-history transactions with no guard (reporting-period locking is a missing feature).
13. **No UNIQUE constraint on (reference_type, reference_id)** — idempotency is only query-enforced; a bug or concurrent write could duplicate postings.

---

## 16. Future Test Plan

To be implemented **with** the engine (no tests added now):

| # | Area | Tests |
|---|---|---|
| 1 | First posting | Each `post_*` creates expected rows; Σdebit = Σcredit; correct `reference_type`/`reference_id`; party ledger balance moves correctly |
| 2 | Duplicate prevention | Second `post_*` for same source refused; no rows added; `is_posted()` true after first post |
| 3 | Reversal | `reverse()` mirrors all rows; net effect on every ledger = zero; identity preserved on reversal rows |
| 4 | Edit | Modify source → `repost()` → old rows reversed, new rows match new amounts; ledger reflects only the new state |
| 5 | Delete | Delete source → posting reversed/removed; no orphan `ledger_transactions` rows (query by reference) |
| 6 | Multi-line journal | N-line JV projects exactly N rows; balanced; update replaces all rows; delete removes all rows |
| 7 | Transaction rollback | Simulated failure mid-posting (e.g., missing config role) → source insert also rolled back (atomicity §11); failure mid-repost leaves pre-edit state intact |
| 8 | Payment modes | Each mode (Cash/Bank/Cheque/UPI) posts to configured account; unmapped mode → posting refused, not misposted |
| 9 | Customer mapping | Sale/CN/Receipt post to the customer's linked ledger; NULL `ledger_id` (unmigrated party) → refused with clear error |
| 10 | Supplier mapping | Purchase/DN/Payment post to supplier's linked ledger; same NULL guard |
| 11 | Opening balances | Ledger balance = opening + posted transactions; party ledger balance reconciles to legacy formula ± migrated opening balance |
| 12 | GST | Purchase GST posts to GST Input when enabled; disabled flag posts gross without tax split; sales post without tax fields (documented limitation) |
| 13 | Discounts | Bill discount (both sides) posts per chosen policy; line discount on sales re-derived correctly; purchase line discount ignored per current math |
| 14 | Stock accounting | Purchases post to Purchase account (periodic); no inventory/COGS posting occurs; stock quantities unchanged by posting logic |
| 15 | Cross-checks | Full flow per party: purchase→DN→payment nets supplier ledger to expected balance; sale→CN→receipt nets customer ledger to expected balance |

---

## 17. Implementation Prerequisites (Final Section — Decisions Required Before Coding)

**Accounting decisions:**
1. Purchase posting entry shape: treatment of `bill_discount` (Discount Received account vs net-against-Purchase), `other_amount` (which account, confirmed sign), `round_off` account.
2. Sales posting entry shape: Discount Allowed account vs net-against-Sales for bill discount and Σ line `discount_amount`.
3. Credit/Debit note posting amount: `total_amount` vs `ledger_amount` — define semantics.
4. GST posture for Phase 2: (a) no GST ledgers (gross posting), or (b) input-GST-only with explicit acceptance that output tax is absent. (Sales-side tax capture is a prerequisite for full GST.)
5. Inventory posture: periodic (recommended, no inventory posting) vs perpetual (blocked — missing data per §6).
6. Reversal strategy: mirrored reversal rows (recommended) vs delete-rows.
7. Walk-in sale (`customer_id IS NULL`) policy: fully-paid only, or default cash-customer ledger.
8. Cheque/UPI policy: separate accounts vs mapped to Bank; whether uncleared cheques post as realized money in Phase 2.
9. Free-quantity costing: keep current behavior (free qty costed in `amount`) — confirm as accepted policy.

**Configuration build-out (schema/UI deferred):**
10. Account role map mechanism (role → ledger_id) with mandatory roles validated at startup/posting.
11. Mode maps: `payment_mode`, `receipt_mode`, `sale_type`, `purchase_type` → account roles.
12. Create the actual ledgers: Cash, Bank, (Cheque), (UPI), Sales, Purchase, Sales Return, Purchase Return, Discount Allowed/Received (if separate), Round-Off, Other Expense/Income.
13. Account-group vocabulary with statement classification (P&L vs Balance Sheet sections) for reporting.
14. Posting on/off switches per transaction type.

**Data prerequisites:**
15. Run/verify `migrate_ledger_mapping` so every customer and supplier has non-NULL `ledger_id`; add a guard that refuses posting for unlinked parties.
16. Enter opening balances for Cash/Bank/all role accounts (party opening balances already migrated in Phase 1 — verify).
17. Decide legacy balance cutover plan (when screens switch to ledger balances) — dual-run reconciliation expected.

**Engine contract:**
18. Confirm the API shape (§12) and the shared-connection transaction pattern (§11).
19. Confirm identity values (`reference_type` strings) and reversal marker design (§10).
20. Reporting-period lock concept (at minimum, a warning) for editing/deleting posted history.

---

## Appendix: Files Inspected for This Specification

| File | Purpose |
|---|---|
| `docs/accounting_integration_audit.md` | Prior audit (current behavior reference) |
| `docs/accounting_integration_phase1.md` | Phase 1 party→ledger mapping |
| `database/ledger_dao.py` | Ledger CRUD, `ledger_transactions`, balance calc |
| `database/journal_dao.py` | Journal entry CRUD (balanced, isolated) |
| `database/purchase_dao.py` | Purchase CRUD + stock |
| `database/sales_dao.py` | Sales CRUD + stock |
| `database/credit_note_dao.py` | Credit note CRUD + stock |
| `database/debit_note_dao.py` | Debit note CRUD + stock |
| `database/supplier_payment_dao.py` | Payment CRUD + legacy balance |
| `database/customer_receipt_dao.py` | Receipt CRUD + legacy balance |
| `database/customer_dao.py` | Customer master + ledger linking |
| `database/supplier_dao.py` | Supplier master + ledger linking |
| `database/connection.py` | Full schema incl. `ledger_transactions.reference_type/reference_id` |
| `screens/purchase_invoice.py` (amount math only) | Verified purchase amount derivation |
| `screens/counter_sale.py` (amount math only) | Verified sale amount derivation |
| `screens/supplier_payment.py`, `screens/customer_receipt.py` (mode lists only) | Verified payment mode values |
