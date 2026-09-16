# Accounting Decisions — Phase 2A

**Date:** 2026-09-15
**Status:** DECISION DOCUMENT ONLY — no code, schema, posting, calculation, or UI changes
**Depends on:** `docs/accounting_posting_specification.md` (§17 decisions 1–9), `docs/accounting_integration_audit.md`, `docs/accounting_integration_phase1.md`

---

## 0. Purpose

This document takes the nine unresolved accounting decisions from **§17 "Implementation Prerequisites" (items 1–9)** of `docs/accounting_posting_specification.md` and makes each one explicit: facts, options, recommendation, effects, missing information, and implementation consequence.

The nine decisions are reproduced **with their original terminology from the specification**:

1. Purchase posting entry shape: treatment of `bill_discount` (Discount Received account vs net-against-Purchase), `other_amount` (which account, confirmed sign), `round_off` account.
2. Sales posting entry shape: Discount Allowed account vs net-against-Sales for bill discount and Σ line `discount_amount`.
3. Credit/Debit note posting amount: `total_amount` vs `ledger_amount` — define semantics.
4. GST posture for Phase 2: (a) no GST ledgers (gross posting), or (b) input-GST-only with explicit acceptance that output tax is absent. (Sales-side tax capture is a prerequisite for full GST.)
5. Inventory posture: periodic (recommended, no inventory posting) vs perpetual (blocked — missing data per §6).
6. Reversal strategy: mirrored reversal rows (recommended) vs delete-rows.
7. Walk-in sale (`customer_id IS NULL`) policy: fully-paid only, or default cash-customer ledger.
8. Cheque/UPI policy: separate accounts vs mapped to Bank; whether uncleared cheques post as realized money in Phase 2.
9. Free-quantity costing: keep current behavior (free qty costed in `amount`) — confirm as accepted policy.

**Rules used in this document:**
- Where the specification supports a recommendation, it is stated as such.
- Where the source documentation does not support a definitive answer, the decision is marked **UNRESOLVED — USER DECISION REQUIRED**. Provisional leans are shown for planning only and are NOT decisions.
- All journal-entry examples are **PROPOSED — NOT IMPLEMENTED**. The application currently posts nothing to `ledger_transactions`.

---

## 1. Decision 1 — Purchase Posting Entry Shape

*Original wording:* "Purchase posting entry shape: treatment of `bill_discount` (Discount Received account vs net-against-Purchase), `other_amount` (which account, confirmed sign), `round_off` account."

### 1.1 Current implementation facts
- `purchase_invoices` stores: `invoice_net_amount`, `bill_discount`, `total_amount`, `gst_amount`, `debit_note_amount`, `other_amount`, `paid_amount`, `round_off`, `net_amount`.
- Verified formula (`screens/purchase_invoice.py`):
  `net_amount = total_amount + gst_amount − bill_discount − debit_note_amount + other_amount + round_off`
  where `total_amount = Σ line.amount`, `line.amount = (pay_qty + free_qty) × rate` (line `discount` captured but NOT applied), `gst_amount = Σ line.gst_amount`.
- `invoice_net_amount` is a manually entered informational field, used in no calculation.
- `purchase_type` ∈ {Credit, Cash, Credit Card}; `paid_amount` is manually entered with no instrument detail.
- No ledger posting exists.

### 1.2 What the software currently stores
One header row per invoice with the nine amount fields above; line rows with rate/discount/gst/amount; no link from any field to a ledger account; no expense-category field for `other_amount`.

### 1.3 Options
- **Option A — Gross posting with separate accounts:** Debit Purchase `total_amount`, Debit GST Input `gst_amount`, Debit Discount Received `bill_discount`, `other_amount` to an Other Expense/Income account (sign to be confirmed), Round-Off account for `round_off`; Credit Supplier ledger (`net_amount − paid_amount`) + Cash/Bank (`paid_amount`). Requires the user to confirm classifications; the specification's §1A example showed this variant currently **does not balance** without a confirmed `bill_discount`/`other_amount` treatment.
- **Option B — Net posting (absorb into Purchase):** Debit Purchase `net_amount` (= `total_amount + gst_amount − bill_discount − debit_note_amount + other_amount + round_off`); Credit Supplier ledger (`net_amount − paid_amount`) + Cash/Bank `paid_amount`. Always balances with stored figures; needs only Purchase, Cash/Bank, and supplier ledgers.
- **Option C — Hybrid:** Round-Off and Discount as separate accounts, `other_amount`/`debit_note_amount` absorbed or separate per user choice.

### 1.4 Recommended option
**UNRESOLVED — USER DECISION REQUIRED.**
Provisional lean (planning only): **Option B (net posting)** for Phase 2 — it is guaranteed to balance with the exact figures the software already stores and requires no interpretation of `other_amount`'s meaning. Option A produces better classification but is blocked by three sub-decisions (bill_discount account, other_amount account/sign, round_off account) none of which the current data can settle.

### 1.5 Why it fits the current application
`other_amount` has no category field and an ambiguous sign (+ in the formula); `bill_discount` has no linked discount policy; `round_off` is a pure balancing figure. Option B posts only numbers that are already computed and stored, so the engine cannot create an unbalanced or misclassified entry from data it doesn't have.

### 1.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | None |
| Purchase | **Defines the purchase entry** (debits Purchase at `net_amount` or split per Option A) |
| Customer Return | None |
| Supplier Return | None (a linked `debit_note_amount` treatment is a separate open item, §6.5) |
| Supplier Payment | None directly; payment credits the same supplier ledger the purchase debited/credited, so consistency depends on this decision |
| Customer Receipt | None |
| Journal Entry | None (users may manually post classification corrections) |

### 1.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | Supplier ledger receives `net_amount − paid_amount` credit either way; Cash/Bank receives `paid_amount` |
| Trial Balance | Balanced under both options; Option B shows fewer accounts |
| Profit & Loss | **Differs:** Option B puts discounts/other/round-off inside Purchase expense; Option A separates them into Discount Received / Other Expense / Round-Off |
| Balance Sheet | No difference in party/cash balances; classification difference sits in P&L only |

### 1.8 Information currently missing
- Which account `other_amount` belongs to, and its confirmed sign/meaning (freight? charges? income?).
- Whether `bill_discount` should be income (Discount Received) or a purchase-cost reduction.
- A Round-Off account (does not exist).
- Whether `paid_amount` can exceed `net_amount` (no validation seen; would break the entry shape).

### 1.9 Exact implementation consequence
- Option B: engine needs role map entries for **Purchase**, **Cash**, **Bank** only; posting = 1 debit line + up to 2 credit lines from stored header values.
- Option A: additionally requires **Discount Received**, **Other Expense/Income**, **Round-Off**, and (per Decision 4) **GST Input** accounts to exist and be configured before any purchase posts; engine must also validate `0 ≤ paid_amount ≤ net_amount`.

---

## 2. Decision 2 — Sales Posting Entry Shape

*Original wording:* "Sales posting entry shape: Discount Allowed account vs net-against-Sales for bill discount and Σ line `discount_amount`."

### 2.1 Current implementation facts
- `sales_invoices` stores: `discount` (bill discount), `paid_amount`, `total_amount`, `round_off`, `net_amount`; `sale_type` ∈ {Cash, Credit, Credit Card}.
- Verified formula (`screens/counter_sale.py`): `line.amount = mrp × sale_qty − discount_amount`; `total_amount = Σ line.amount`; `net_amount = total_amount − discount + round_off`.
- Line discount is **applied** inside `line.amount` (unlike purchases).
- Sales have **no GST fields** (see §5 of this document).
- `SalesDAO` has no update method — insert and delete only.
- No ledger posting exists.

### 2.2 What the software currently stores
Header bill-level `discount`, per-line `discount_amount`, `paid_amount`, computed `total_amount`/`round_off`/`net_amount`. Σ line `discount_amount` is derivable from line rows.

### 2.3 Options
- **Option A — Gross with Discount Allowed:** Debit Cash/Bank `paid_amount` + Customer ledger (`net_amount − paid_amount`) + Discount Allowed (`discount`, and optionally Σ line `discount_amount` shown gross); Credit Sales `total_amount + round_off`.
- **Option B — Net against Sales:** Debit Cash/Bank `paid_amount` + Customer ledger (`net_amount − paid_amount`); Credit Sales `net_amount`. Discounts never appear as separate lines.

### 2.4 Recommended option
**UNRESOLVED — USER DECISION REQUIRED.**
Provisional lean: **Option B (net-against-Sales)** — symmetric with the purchase lean, guaranteed balanced with stored figures, and avoids inventing a Discount Allowed account. Note: line `discount_amount` is already embedded in every line's `amount`, so Option B is fully consistent with stored data; Option A would additionally require deciding whether line discounts are also broken out (double-counting risk if both bill and line discounts are grossed up).

### 2.5 Why it fits the current application
`net_amount` is the single figure the application already treats as the sale value everywhere (customer balance formula uses `sales.net_amount`). Posting `net_amount` to Sales matches the existing balance system exactly during transition.

### 2.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | **Defines the sale entry** |
| Purchase | None |
| Customer Return | Return posts against Sales Return; if sales are net, returns stay net too (consistency requirement) |
| Supplier Return | None |
| Supplier Payment | None |
| Customer Receipt | None directly; receipts settle the customer-ledger debit created here |
| Journal Entry | None (manual corrections possible) |

### 2.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | Customer ledger debited `net_amount − paid_amount`; Cash/Bank debited `paid_amount` — identical under both options |
| Trial Balance | Balanced under both |
| Profit & Loss | **Differs:** Option A shows lower Sales + Discount Allowed expense; Option B shows net Sales only. Totals differ by the discount amount in gross profit composition |
| Balance Sheet | No difference |

### 2.8 Information currently missing
- A Discount Allowed account (does not exist).
- Whether the business wants discounts visible as an expense line in P&L.
- Whether `paid_amount` may exceed `net_amount` (no validation seen).

### 2.9 Exact implementation consequence
- Option B: role map needs **Sales**, **Cash**, **Bank**; posting = up to 2 debit lines + 1 credit line from stored header values.
- Option A: additionally requires **Discount Allowed** account and an explicit rule for line vs bill discount breakout.

---

## 3. Decision 3 — Credit/Debit Note Posting Amount

*Original wording:* "Credit/Debit note posting amount: `total_amount` vs `ledger_amount` — define semantics."

### 3.1 Current implementation facts
- `credit_notes` and `debit_notes` each store `total_amount` and `ledger_amount` on the header.
- Line rows store `return_qty`, `rate`, `mrp`, `less_amount`, `amount`, `price_factor`; the line `amount` is computed by the UI at entry time and stored as-is (the exact `less_amount`/`price_factor` formula is not re-derivable from the DAO).
- The existing balance formulas use **`total_amount`**: `get_customer_balance()` subtracts `Σ credit_notes.total_amount`; `get_supplier_balance()` subtracts `Σ debit_notes.total_amount`. **`ledger_amount` is stored but used by nothing** (audit: "exists but is not linked to any ledger posting").
- No ledger posting exists.

### 3.2 What the software currently stores
Two header amounts per note whose intended difference is undocumented; line detail sufficient to reproduce `total_amount` (Σ line `amount`) but not to explain `ledger_amount`.

### 3.3 Options
- **Option A — Post `total_amount`:** matches Σ line amounts and matches both existing balance calculations.
- **Option B — Post `ledger_amount`:** would require defining what it means (e.g., "amount to adjust in the party ledger after netting") — no code or documentation defines this.
- **Option C — Post both in different places** (e.g., stock/value at `total_amount`, party at `ledger_amount`): unsupported by any existing semantics.

### 3.4 Recommended option
**UNRESOLVED — USER DECISION REQUIRED.**
Provisional lean: **Option A (`total_amount`)** — it is the only one of the two with verified meaning (Σ line amounts) and verified use (both legacy balance formulas). If the business intends `ledger_amount` to mean something specific (e.g., cash refunded vs credit adjusted), the user must define it before Option B/C become possible.

### 3.5 Why it fits the current application
Posting `total_amount` keeps the future ledger balance identical to the legacy `get_customer_balance()`/`get_supplier_balance()` results during dual-run, making reconciliation trivial. Posting `ledger_amount` would immediately diverge from every existing balance display.

### 3.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | None (but a credit note reverses a sale's effect on the customer ledger) |
| Purchase | None (a debit note reverses a purchase's effect on the supplier ledger) |
| Customer Return | **Defines the note's posting amount** (Credit customer ledger by chosen amount) |
| Supplier Return | **Defines the note's posting amount** (Debit supplier ledger by chosen amount) |
| Supplier Payment | Supplier balance that payments settle will be computed from the chosen amount |
| Customer Receipt | Customer balance that receipts settle will be computed from the chosen amount |
| Journal Entry | None |

### 3.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | Party ledger return adjustment equals the chosen amount |
| Trial Balance | Balanced either way (single debit + single credit per note) |
| Profit & Loss | Sales Return / Purchase Return contra values differ if the two amounts differ |
| Balance Sheet | Party (debtor/creditor) balances differ by `total_amount − ledger_amount` per note if Option B is chosen |

### 3.8 Information currently missing
- The business definition of `ledger_amount` (origin/purpose unknown from code and docs).
- Whether `less_amount` is already inside line `amount` (UI-computed) — affects only re-derivation, not the posting amount itself.

### 3.9 Exact implementation consequence
- Option A: engine reads `total_amount` only; `ledger_amount` remains a stored, unused field (documented as such).
- Any option: a mismatch rule is needed — if `total_amount != ledger_amount` on a note, engine should either post per decision or refuse with a warning (recommended: refuse).

---

## 4. Decision 4 — GST Posture for Phase 2

*Original wording:* "GST posture for Phase 2: (a) no GST ledgers (gross posting), or (b) input-GST-only with explicit acceptance that output tax is absent. (Sales-side tax capture is a prerequisite for full GST.)"

### 4.1 Current implementation facts
- **Purchases only** carry GST: line `gst_percent`, `gst_amount`; header `gst_amount` = Σ lines; computed as `amount × gst_percent / 100` (added on top).
- **Sales have no GST fields at all** — `sales_invoices`/`sales_invoice_items` contain no tax columns.
- **Credit notes and debit notes have no GST adjustment fields.**
- No GST accounts, no tax configuration, no CGST/SGST/IGST split, no tax report exist.

### 4.2 What the software currently stores
Input tax amounts per purchase line/header. Nothing about output tax. Nothing about tax on returns.

### 4.3 Options
- **Option (a) — No GST ledgers (gross posting):** purchases post at `net_amount` (or `total_amount`) with GST embedded; no tax account touched.
- **Option (b) — Input-GST-only:** Debit GST Input `gst_amount` at purchase; accept that output tax is absent from sales postings, so the trial balance shows an input-tax asset with no matching liability.
- Full GST (input + output): **not available** — sales-side tax data does not exist (see §5).

### 4.4 Recommended option
**Option (a) — no GST ledgers (gross posting) for Phase 2.** The specification (§7) already recommends: "do not post GST ledgers until sales-side tax capture exists; otherwise the trial balance will show input tax with no output tax — an incorrect financial picture."

### 4.5 Why it fits the current application
The application cannot compute output tax from stored data; posting input tax alone would state a receivable/refund the business may not be entitled to. Gross posting requires no new accounts and no invented amounts.

### 4.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | None — no tax data to post |
| Purchase | GST stays embedded in the Purchase-side amount (Option a) or split to GST Input (Option b) |
| Customer Return | None — no tax fields (documented asymmetry) |
| Supplier Return | None — no tax reversal fields; if Option (b) were chosen, returns could not reverse their input tax |
| Supplier Payment | None |
| Customer Receipt | None |
| Journal Entry | Users may post manual tax adjustments; engine adds nothing |

### 4.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | Option (a): no tax ledgers involved. Option (b): GST Input ledger accumulates balance |
| Trial Balance | Option (a): balanced, no tax accounts. Option (b): balanced but shows input-tax asset with **no output-tax liability — misstated** |
| Profit & Loss | Option (a): purchases gross (tax inside expense). Option (b): purchases net of input tax |
| Balance Sheet | Option (b) overstates assets/understates liabilities for tax purposes |

### 4.8 Information currently missing
- Sales-side tax capture (fields, tax-inclusive vs tax-exclusive pricing).
- Tax on returns (no fields on credit/debit notes).
- CGST/SGST vs IGST split (only a single `gst_percent` exists).
- The business's actual GST registration/charging practice.

### 4.9 Exact implementation consequence
- Option (a): **no GST accounts, no GST role-map entries, no GST posting code** in Phase 2. Purchase posts gross. A documented note must accompany statements: "tax not separately accounted".
- Full GST later requires: sales/return tax fields (schema change), GST Output/Input accounts, split configuration — all out of Phase-2 scope.

---

## 5. Decision 5 — Inventory Posture

*Original wording:* "Inventory posture: periodic (recommended, no inventory posting) vs perpetual (blocked — missing data per §6)."

### 5.1 Current implementation facts
- `stock_batches` holds per-batch `purchase_rate`, `net_rate`, `mrp`, `stock_qty`; quantities move with every purchase/sale/return.
- **Sales lines store no cost** — only `mrp`, `sale_qty`, `discount_amount`, `amount`.
- No COGS calculation, no stock valuation report, no opening stock value, no Inventory account exist.
- Specification §6 states explicitly: "The current system does not contain enough information for reliable perpetual inventory accounting."

### 5.2 What the software currently stores
Quantities and current batch rates — enough for stock *quantity* management, not for historical *cost* accounting.

### 5.3 Options
- **Periodic inventory:** purchases post to Purchase expense; no Inventory/COGS posting at sale time; stock value computed/entered at period end (e.g., via manual journal entry).
- **Perpetual inventory:** Debit Inventory on purchase, Credit Inventory + Debit COGS on sale. **Blocked** — sale lines lack cost, batch rates mutate on every purchase, no opening stock value.

### 5.4 Recommended option
**Periodic inventory** (as recommended by the specification §6: "Recommended Phase-2 stance… Post purchases to a Purchase account (expense), do NOT post inventory/COGS at sale time").

### 5.5 Why it fits the current application
Perpetual would require inventing a COGS value per sale that the software does not record. Periodic uses only stored figures and keeps the ledger truthful.

### 5.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | Posts revenue + party/cash only; **no COGS line** (documented limitation) |
| Purchase | Posts to Purchase account (expense), not Inventory |
| Customer Return | Posts Sales Return only; stock qty restored, no inventory value line |
| Supplier Return | Posts Purchase Return only; stock qty reduced, no inventory value line |
| Supplier Payment | None |
| Customer Receipt | None |
| Journal Entry | Becomes the mechanism for period-end closing-stock/COGS adjustments (manual) |

### 5.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | No Inventory ledger activity (unless manual journals) |
| Trial Balance | Balanced; no Inventory account balance |
| Profit & Loss | Gross profit = Sales − Purchases (periodic approximation), **not** Sales − COGS; overstated margin in periods of stock buildup |
| Balance Sheet | **No stock asset appears automatically** — closing stock must be introduced via manual journal (missing information; see §7 of this document) |

### 5.8 Information currently missing
- Cost of goods per sale line (not stored).
- Opening stock valuation (does not exist).
- Stable historical batch cost (rates mutate per purchase).
- Free-quantity costing policy (Decision 9).

### 5.9 Exact implementation consequence
- No Inventory/COGS accounts or role-map entries in Phase 2.
- Sale posting code contains no cost logic — ever — until sale lines capture cost (future schema change).
- Period-end stock value enters the books only through manual Journal Entries (existing journal feature already supports this).

---

## 6. Decision 6 — Reversal Strategy

*Original wording:* "Reversal strategy: mirrored reversal rows (recommended) vs delete-rows."

### 6.1 Current implementation facts
- `ledger_transactions` columns: `ledger_id`, `transaction_date`, `transaction_time`, `voucher_type`, `voucher_no`, `reference_type`, `reference_id`, `description`, `debit`, `credit`. **No reversal flag, no "reverses" link column.**
- `reference_type`/`reference_id` exist but are written by nothing today (except manual `LedgerDAO.add_transaction()` calls with caller values).
- Source DAOs already do reverse-and-reapply for **stock** on update (e.g., `update_invoice` reverses old stock, applies new) — the same pattern extends to ledger rows.
- Journal entries are currently updated by **delete-and-reinsert of items** (`update_entry` deletes all items, re-inserts).

### 6.2 What the software currently stores
No posted rows yet; the schema supports identity tagging but not reversal tagging.

### 6.3 Options
- **Mirrored reversal rows:** reversal = new rows with debit/credit swapped, same `reference_type`/`reference_id`, distinguishable via `voucher_type` suffix (e.g., `PV-0007-REV`) or description convention. Audit trail preserved.
- **Delete rows:** reversal = `DELETE FROM ledger_transactions WHERE reference_type=? AND reference_id=?`. Simple; no audit trail; dangerous once reports have been taken.

### 6.4 Recommended option
**Mirrored reversal rows** (as recommended by the specification §1A/§10: "Recommended: mirrored reversal rows (preserves audit trail)").

### 6.5 Why it fits the current application
The application already prefers reversal patterns for stock (never deletes history silently in updates); ledger data feeds future Trial Balance/P&L where audit trails matter; and delete-rows would make "was this ever posted?" unanswerable after correction.

### 6.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | Delete/edit → mirrored reversal instead of row removal |
| Purchase | Same; edit = reverse old posting + post new, both mirrored-row based |
| Customer Return | Same |
| Supplier Return | Same |
| Supplier Payment | Same |
| Customer Receipt | Same |
| Journal Entry | Exception candidate: journal items are the voucher of record, so delete-and-reinsert of **derived** projection rows is safe; reversal rows optional here |

### 6.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | Reversal rows appear as visible offsetting transactions (date-ordered running balance stays correct) |
| Trial Balance | Net effect zero after reversal; both original and reversal rows count (correct) |
| Profit & Loss | Period containing the original but not the reversal still shows the original amounts (correct historical behavior) |
| Balance Sheet | Same period-sensitive correctness as P&L |

### 6.8 Information currently missing
- A reversal marker: which convention (`voucher_type` suffix vs description vs future schema column) — a small design choice inside the recommended option.
- Period-lock concept (specification risk #12): reversals of period-closed vouchers are currently unguarded.

### 6.9 Exact implementation consequence
- Reversal = insert mirrored rows within the caller's transaction; locate via `reference_type`/`reference_id`.
- Convention must be fixed before coding (e.g., `voucher_type` stored as source type but `description` prefixed `REVERSAL:` **or** `voucher_no` suffixed `-REV`) — one choice, applied uniformly.
- No schema change required for the basic strategy.

---

## 7. Decision 7 — Walk-In Sale (`customer_id IS NULL`) Policy

*Original wording:* "Walk-in sale (`customer_id IS NULL`) policy: fully-paid only, or default cash-customer ledger."

### 7.1 Current implementation facts
- `sales_invoices.customer_id` is **nullable** (`INTEGER REFERENCES customers(id) ON DELETE SET NULL`); `SalesDAO.insert_invoice()` accepts `customer_id=None`.
- Counter-sale UI allows cash sales without a customer.
- `paid_amount` for such sales is **not validated** against `net_amount` — a walk-in sale could currently be saved with `paid_amount < net_amount` (an untracked credit to nobody).
- Legacy `get_customer_balance()` is per-customer; null-customer sales are invisible to it.
- Phase 1 gives every *created* customer a ledger, but a NULL customer has none.

### 7.2 What the software currently stores
Sales rows with no party reference; `paid_amount` of any value; no ledger target.

### 7.3 Options
- **Option A — Fully-paid only:** engine refuses to post (or the screen refuses to save) a walk-in sale unless `paid_amount == net_amount`; the entire net posts to Cash/Bank.
- **Option B — Default cash-customer ledger:** a designated ledger (e.g., "Walk-in Customer") receives the credit portion of underpaid walk-in sales.

### 7.4 Recommended option
**UNRESOLVED — USER DECISION REQUIRED.**
Provisional lean: **Option A (fully-paid only)** — it requires no fake party ledger and matches the ordinary meaning of a counter cash sale. But note the current software does NOT enforce full payment, so Option A also implies a validation change in the sale screen or a refusal rule in the engine.

### 7.5 Why it fits the current application
Option B would invent a party that has no customer record, no Phase-1 mapping, and would appear in debtor reports as a real customer. Option A keeps the ledger free of synthetic parties; the engine simply refuses ambiguous data.

### 7.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | **Directly defines** whether NULL-customer sales post to Cash only (A) or to a default ledger (B), and whether underpaid walk-ins are rejected |
| Purchase | None (supplier_id is NOT NULL on purchases — not applicable) |
| Customer Return | Not applicable (credit_notes.customer_id is NOT NULL) |
| Supplier Return | None |
| Supplier Payment | None |
| Customer Receipt | Not applicable (receipts require a real customer) |
| Journal Entry | None |

### 7.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | Option A: Cash ledger only. Option B: an extra "Walk-in" ledger with a running balance |
| Trial Balance | Balanced either way; Option B adds one more ledger |
| Profit & Loss | None (Sales value identical) |
| Balance Sheet | Option B: walk-in credit portion sits inside debtors (potentially misleading ageing); Option A: none |

### 7.8 Information currently missing
- Whether underpaid walk-in sales occur in practice (data inspection needed).
- The business's intent for `sale_type='Credit'` sales without a customer.

### 7.9 Exact implementation consequence
- Option A: engine rule — `customer_id IS NULL AND paid_amount != net_amount` → refuse posting with explicit error; sale screen validation recommended (UI change deferred).
- Option B: requires creating and role-mapping a default ledger + engine falls back to it for the credit portion.

---

## 8. Decision 8 — Cheque/UPI Policy

*Original wording:* "Cheque/UPI policy: separate accounts vs mapped to Bank; whether uncleared cheques post as realized money in Phase 2."

### 8.1 Current implementation facts
- `supplier_payments.payment_mode` and `customer_receipts.receipt_mode` each hold one of **Cash, Bank, Cheque, UPI** (verified in both screens' combo boxes).
- `reference_no` holds the Cheque/UPI reference text — free text, no clearing status, no due/clearing date.
- No Cash, Bank, Cheque, or UPI ledger exists; no mode→account mapping exists.
- Purchase/sale types use different labels ({Credit, Cash, Credit Card}) with no instrument detail for partial payments on credit-type invoices.
- No clearing/confirmation workflow exists anywhere (specification risk #9).

### 8.2 What the software currently stores
Mode label + free-text reference + amount. Nothing about cheque status, bank account identity, or settlement date.

### 8.3 Options
- **Option A — Single Bank account:** Bank, Cheque, UPI all post to one Bank ledger; cheques count as realized money immediately.
- **Option B — Separate accounts:** Cheque-in-Hand (and optionally UPI) as its own ledger(s), cleared to Bank via manual journal later.
- **Option C — Multiple bank accounts:** map each mode (or each bank) to user-configured ledgers — supported by nothing in the data (no bank identity field).

### 8.4 Recommended option
**UNRESOLVED — USER DECISION REQUIRED.**
Provisional lean: **Option A (single Bank account)** for Phase 2 — simplest, matches available data (no clearing status exists to drive Option B), and the risk (bounced cheques overstating bank balance) is explicitly accepted and documented. Option B is more correct but requires a clearing workflow the application does not have.

### 8.5 Why it fits the current application
There is no field to mark a cheque cleared, so Option B's separate account could never be reconciled to Bank automatically; it would rely entirely on manual journals. Option A uses the one fact that exists: the mode label.

### 8.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | Paid portion posts per `sale_type` mapping (Cash→Cash; Credit Card→Bank per this decision's spirit) — instrument for credit-type partial payments remains unknown (specification §3 gap) |
| Purchase | Same for `purchase_type` paid portion |
| Customer Return | None |
| Supplier Return | None |
| Supplier Payment | **Defines** the credit side: Cash→Cash ledger; Bank/Cheque/UPI→Bank (A) or separate ledgers (B) |
| Customer Receipt | **Defines** the debit side identically |
| Journal Entry | Under Option B, cheque clearance becomes a manual journal (Debit Bank / Credit Cheque-in-Hand) |

### 8.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | Option A: one Bank ledger with all non-cash money. Option B: Cheque-in-Hand ledger visible until cleared |
| Trial Balance | Balanced either way |
| Profit & Loss | None |
| Balance Sheet | Option A: bank balance may include uncleared/bounced cheques (**risk accepted**). Option B: pending cheques shown as a distinct asset |

### 8.8 Information currently missing
- Cheque clearing status/dates (no fields).
- Bank account identity for multi-bank businesses (no fields).
- How "Credit Card" sale/purchase tender should map (card settlement account).

### 8.9 Exact implementation consequence
- Option A: role map needs **Cash** + **Bank** only; modes Bank/Cheque/UPI all resolve to Bank.
- Option B: additional **Cheque-in-Hand** (and optionally **UPI**) role + documented manual clearance procedure.

---

## 9. Decision 9 — Free-Quantity Costing

*Original wording:* "Free-quantity costing: keep current behavior (free qty costed in `amount`) — confirm as accepted policy."

### 9.1 Current implementation facts
- Purchase line: `amount = (pay_qty + free_qty) × rate` — **free quantity is costed** (verified `screens/purchase_invoice.py`: `qty_total = pay_qty + free_qty; amount = round(qty_total * rate)`).
- Free qty also enters stock (`stock_batches.stock_qty += pay_qty + free_qty`).
- `purchase_rate = (amount + gst) / qty_total` — per-unit cost diluted across free units.
- Line `discount` is captured but **not applied** to `amount`.
- Header `total_amount = Σ line.amount` — free-qty cost flows into every total and into `net_amount`.

### 9.2 What the software currently stores
Free quantities and their cost effect, merged inseparably into `amount`, `total_amount`, `net_amount`. There is no way to split free-qty value out of a stored invoice without recomputing lines.

### 9.3 Options
- **Option A — Keep current behavior:** free qty costed inside the purchase amount (what the software computes today).
- **Option B — Exclude free qty from cost:** `amount = pay_qty × rate` only (a change to existing calculations — explicitly forbidden to implement now; would alter stored figures and contradict the specification's "do not change existing calculations").

### 9.4 Recommended option
**Option A — keep current behavior (free qty costed in `amount`)**, as the specification §17.9 proposes, **but it requires explicit user confirmation as accepted accounting policy** because it embeds an assumption (free goods carry the same unit cost as paid goods) that only the business can validate.

### 9.5 Why it fits the current application
Option A requires zero changes: every stored figure already reflects it, and the posting engine simply uses `net_amount`/`total_amount` as stored. Option B would change existing transaction behavior — out of scope by the task's own constraints.

### 9.6 Effect on transactions

| Transaction | Effect |
|---|---|
| Sales | None |
| Purchase | Purchase-side amount (and thus the entry under any Option from Decision 1) includes free-qty cost |
| Customer Return | None |
| Supplier Return | Return lines carry `return_qty`/`amount` as entered; no free-qty concept |
| Supplier Payment | Supplier balance includes free-qty cost (payments settle it) |
| Customer Receipt | None |
| Journal Entry | Manual corrections possible |

### 9.7 Effect on statements

| Report | Effect |
|---|---|
| Account Ledger | Supplier ledger balance includes free-qty cost |
| Trial Balance | Balanced |
| Profit & Loss | Purchase expense includes free-qty cost (higher expense, lower margin, in the purchase period) |
| Balance Sheet | Under periodic inventory, none beyond the expense effect |

### 9.8 Information currently missing
- Business confirmation that free goods should carry cost (vs zero-cost schemes common in pharma trade schemes).
- No free-qty value is separately stored, so the policy cannot be reversed later for historical invoices.

### 9.9 Exact implementation consequence
- None for the engine — it posts stored amounts unchanged.
- The confirmation is recorded here so the policy is deliberate, not accidental.

---

## 10. Proposed Entry Shapes (All Examples)

> **PROPOSED — NOT IMPLEMENTED.** The application currently writes nothing to `ledger_transactions`. These shapes show what the future engine would produce **after** the decisions above are confirmed. Amounts in examples are illustrative only where the specification used examples.

### A. Purchase Invoice (assuming Decision 1 = Option B, Decision 4 = (a), Decision 9 = keep)

**PROPOSED — NOT IMPLEMENTED**

| Ledger | Debit | Credit |
|---|---|---|
| Purchase Account | `net_amount` | |
| Supplier Ledger | | `net_amount − paid_amount` |
| Cash/Bank | | `paid_amount` |

*(If Decision 1 = Option A, the debit splits across Purchase `total_amount`, GST Input `gst_amount`, Discount Received `bill_discount`, Other Expense/Income `other_amount`, Round-Off — blocked pending that decision.)*

### B. Counter Sale (assuming Decision 2 = Option B, Decision 7 = A)

**PROPOSED — NOT IMPLEMENTED**

| Ledger | Debit | Credit |
|---|---|---|
| Cash/Bank (per `sale_type`) | `paid_amount` | |
| Customer Ledger | `net_amount − paid_amount` | |
| Sales Account | | `net_amount` |

Walk-in (`customer_id IS NULL`): Cash/Bank debited `net_amount` only, and posting refused if `paid_amount != net_amount` (Decision 7, Option A).

### C. Customer Credit Note (assuming Decision 3 = `total_amount`)

**PROPOSED — NOT IMPLEMENTED**

| Ledger | Debit | Credit |
|---|---|---|
| Sales Return Account | `total_amount` | |
| Customer Ledger | | `total_amount` |

### D. Supplier Debit Note (assuming Decision 3 = `total_amount`)

**PROPOSED — NOT IMPLEMENTED**

| Ledger | Debit | Credit |
|---|---|---|
| Supplier Ledger | `total_amount` | |
| Purchase Return Account | | `total_amount` |

### E. Supplier Payment (assuming Decision 8 = Option A)

**PROPOSED — NOT IMPLEMENTED**

| Ledger | Debit | Credit |
|---|---|---|
| Supplier Ledger | `amount` | |
| Cash (mode=Cash) or Bank (mode=Bank/Cheque/UPI) | | `amount` |

### F. Customer Receipt (assuming Decision 8 = Option A)

**PROPOSED — NOT IMPLEMENTED**

| Ledger | Debit | Credit |
|---|---|---|
| Cash (mode=Cash) or Bank (mode=Bank/Cheque/UPI) | `amount` | |
| Customer Ledger | | `amount` |

### G. Journal Entry

**PROPOSED — NOT IMPLEMENTED**

One `ledger_transactions` row per `journal_entry_item` (`voucher_type='JV'`, `reference_type='journal_entry'`, `reference_id=<entry id>`, line debit/credit as entered). Already balanced by the existing `JournalDAO` validation (total debit = total credit, tolerance 0.001).

---

## 11. Required Account Roles

Only roles supported by the specification. "Required" = needed for the provisional entry shapes above.

| Role | Required? | Why | Transaction(s) using it | Configuration needed |
|---|---|---|---|---|
| **Cash** | **Yes** | Paid portions of sales/purchases; Cash-mode payments/receipts | Purchase, Sale, Supplier Payment, Customer Receipt | Role → ledger_id mapping; account must be created |
| **Bank** | **Yes** (if any non-cash mode used) | Bank/Cheque/UPI tender (Decision 8 lean: one account) | Purchase (Credit Card), Sale (Credit Card), Payment, Receipt | Role → ledger_id; account must be created |
| **Cheque** | Conditional (Decision 8) | Only if separate Cheque-in-Hand chosen | Payment, Receipt | Decision 8 outcome |
| **UPI** | Conditional (Decision 8) | Only if separate UPI account chosen | Payment, Receipt | Decision 8 outcome |
| **Customer (per-customer ledgers)** | **Yes** — exists | Credit portions of sales; credit notes; receipts | Sale, Credit Note, Customer Receipt | Already auto-created (Phase 1); must verify no NULL `ledger_id` |
| **Supplier (per-supplier ledgers)** | **Yes** — exists | Credit portions of purchases; debit notes; payments | Purchase, Debit Note, Supplier Payment | Already auto-created (Phase 1); same verification |
| **Sales** | **Yes** | Revenue credit on sales | Sale | Role → ledger_id; create account |
| **Purchase** | **Yes** | Expense debit on purchases | Purchase | Role → ledger_id; create account |
| **Sales Return** | **Yes** | Contra-revenue on customer returns | Credit Note | Role → ledger_id; create account |
| **Purchase Return** | **Yes** | Contra-expense on supplier returns | Debit Note | Role → ledger_id; create account |
| **Inventory / COGS** | **No** (Decision 5 = periodic) | No cost data at sale time; no inventory posting | None in Phase 2 | None; period-end stock enters via manual journal |
| **GST Input** | **No** (Decision 4 = (a)) | No output tax exists; input-only posting would misstate | None in Phase 2 | Blocked until sales tax capture |
| **GST Output** | **No — blocked** | Sales/returns contain no tax fields | None | Requires schema + data that don't exist |
| **Discount Allowed** | Conditional (Decision 2) | Only if gross posting chosen | Sale | Decision 2 outcome |
| **Discount Received** | Conditional (Decision 1) | Only if gross posting chosen | Purchase | Decision 1 outcome |
| **Round-Off** | Conditional (Decision 1) | Only if split posting chosen | Purchase (and Sale if gross) | Decision 1 outcome |
| **Other Expense / Other Income** | Conditional (Decision 1) | Target for `other_amount` if split | Purchase | Decision 1 outcome + sign confirmation |

---

## 12. Walk-In Customer (`customer_id IS NULL`) — Explicit Statement

- **Current fact:** the schema and DAO allow sales with no customer; `paid_amount` is not validated against `net_amount` for such sales; no ledger exists for a NULL customer; legacy balance math never sees these rows.
- **Options (from the specification):** fully-paid only, or default cash-customer ledger.
- **Status: UNRESOLVED — USER DECISION REQUIRED** (provisional lean: fully-paid only, with engine refusal for underpaid walk-ins; see Decision 7).
- **Consequence of doing nothing:** the engine cannot post walk-in sales with `paid_amount < net_amount` at all — there is no defensible ledger target. This is a blocking decision for sales posting.

---

## 13. GST — Explicit Statement of Current Limitation

- Sales and returns **contain no GST fields**. The application stores input tax on purchases only.
- **No GST amounts may be invented for sales or returns.** Output tax liability cannot be computed from existing data.
- Until sales-side tax capture exists, the only defensible Phase-2 postures are Decision 4's option (a) (gross, recommended) or (b) (input-only, explicitly accepting a misstated trial balance).
- Returns cannot reverse input tax even under option (b) — debit notes carry no tax split.
- Full GST requires future schema changes (sales/return tax fields, CGST/SGST/IGST split) that are outside Phase 2 and outside this document's scope.

---

## 14. Discounts / Other Amounts — Facts Only

From the specification and verified code — **no new accounting rules created here**:

| Field | Location | Verified current behavior | Accounting treatment status |
|---|---|---|---|
| Bill discount (purchase) | `purchase_invoices.bill_discount` | Subtracted in `net_amount` | **UNRESOLVED** — Decision 1 |
| Bill discount (sale) | `sales_invoices.discount` | Subtracted in `net_amount` | **UNRESOLVED** — Decision 2 |
| Line discount (purchase) | `purchase_invoice_items.discount` | Captured but **NOT applied** — `amount = (pay_qty+free_qty) × rate` regardless | No treatment needed for posting (use stored `amount`); field itself unreliable — documented |
| Line discount (sale) | `sales_invoice_items.discount_amount` | Applied: `amount = mrp × qty − discount_amount` | Embedded in amounts; separate posting only if Decision 2 = gross |
| Less amount | `credit_note_items.less_amount`, `debit_note_items.less_amount` | Stored per line; effect already inside UI-computed line `amount`; standalone formula not re-derivable from DAO | Line `amount` is authoritative; standalone `less_amount` posting **not defined** — no rule invented |
| Other amount | `purchase_invoices.other_amount` | Added (+) in `net_amount`; meaning/sign ambiguous; no category field | **UNRESOLVED** — Decision 1 |
| Debit note amount | `purchase_invoices.debit_note_amount` | Manually entered header deduction on the purchase invoice; subtracted in `net_amount`; **not linked to any `debit_notes` record** | **UNRESOLVED** — sub-item of Decision 1 (absorbed into net under Option B; would need a Purchase Return-side account under Option A). Double-counting risk exists if the same return is also entered as a debit note |

---

## 15. Inventory / COGS — Explicit MISSING INFORMATION

Per specification §6 and Decision 5:

> **The current system does not contain enough information for reliable inventory accounting.**

1. Sales lines do not record the cost of the sold goods — COGS cannot be derived historically.
2. `stock_batches.purchase_rate`/`net_rate` change whenever the same batch is repurchased — current rates are not historical cost.
3. No opening stock valuation exists.
4. Free-quantity cost policy was undefined until Decision 9 (provisional: keep current behavior).

**Meaning for future accounting:**
- No Inventory or COGS account will be posted in Phase 2 (periodic posture).
- The Balance Sheet will show **no stock asset** automatically; closing stock must be entered via manual Journal Entry at period end.
- Profit & Loss gross profit is Sales − Purchases (periodic), which misstates margin within a period where stock levels change — an accepted, documented limitation until sale lines capture cost.

**No COGS value is invented anywhere in this document.**

---

## 16. FINAL DECISIONS REQUIRED FROM USER

| # | Decision | Current status | Recommended choice | User confirmation required? |
|---|---|---|---|---|
| 1 | Purchase posting entry shape (`bill_discount` / `other_amount` / `round_off`) | UNRESOLVED — USER DECISION REQUIRED | Provisional: net-posting (Option B); split posting only after sub-decisions confirmed | **Yes** |
| 2 | Sales posting entry shape (Discount Allowed vs net-against-Sales) | UNRESOLVED — USER DECISION REQUIRED | Provisional: net-against-Sales (Option B) | **Yes** |
| 3 | Credit/Debit note posting amount (`total_amount` vs `ledger_amount`) | UNRESOLVED — USER DECISION REQUIRED | Provisional: `total_amount` (matches existing balance math) | **Yes** |
| 4 | GST posture for Phase 2 | Open — recommendation exists | **(a) No GST ledgers (gross posting)** — per specification §7 | **Yes** (acceptance of "tax not separately accounted") |
| 5 | Inventory posture | Open — recommendation exists | **Periodic** (per specification §6) | **Yes** (acceptance of no stock asset/COGS in ledger) |
| 6 | Reversal strategy | Open — recommendation exists | **Mirrored reversal rows** (per specification §10) | **Yes** (confirm; also pick reversal marker convention) |
| 7 | Walk-in sale (`customer_id IS NULL`) policy | UNRESOLVED — USER DECISION REQUIRED | Provisional: fully-paid only (Option A) | **Yes** |
| 8 | Cheque/UPI policy (separate vs Bank; uncleared cheques) | UNRESOLVED — USER DECISION REQUIRED | Provisional: single Bank account, cheques post as realized (risk accepted) | **Yes** |
| 9 | Free-quantity costing (keep current behavior) | Open — confirmation requested by specification §17.9 | **Keep current behavior** (free qty costed in `amount`) | **Yes** (explicit policy confirmation) |

---

## 17. BLOCKING ITEMS BEFORE POSTING ENGINE

Decisions and configuration that must be settled **before automatic posting can safely be implemented**:

**Blocking decisions (from §16):**
1. Decision 1 — purchase entry shape (blocks purchase posting entirely).
2. Decision 2 — sales entry shape (blocks sales posting).
3. Decision 3 — note posting amount (blocks credit/debit note posting).
4. Decision 7 — walk-in sale policy (blocks sales posting; a NULL-customer underpaid sale has no ledger target).
5. Decision 8 — mode/account mapping (blocks payment and receipt posting; also the paid-portion target for sales/purchases).
6. Decisions 4, 5, 6, 9 — recommended choices exist but require explicit user acceptance before they become the engine's rules.

**Blocking configuration (from specification §17 items 10–17; UI deferred):**
7. Account role map mechanism (role → `ledger_id`) with mandatory-role validation.
8. Mode maps: `payment_mode`, `receipt_mode`, `sale_type`, `purchase_type` → account roles.
9. Actual ledgers created: Cash, Bank, Sales, Purchase, Sales Return, Purchase Return (+ conditional accounts per decisions 1/2/8).
10. Run/verify `migrate_ledger_mapping` so every customer and supplier has a non-NULL `ledger_id` (engine must refuse unlinked parties).
11. Opening balances entered for Cash/Bank and all role accounts; party opening balances verified (migrated in Phase 1).
12. Posting on/off switches per transaction type (safe rollout).
13. Reversal marker convention fixed (Decision 6 implementation detail).

**Explicitly NOT blocking (accepted limitations, documented above):** no GST ledgers (Decision 4a), no inventory/COGS posting (Decision 5), `less_amount` standalone treatment (embedded in line `amount`), purchase line `discount` field (not applied — posting uses stored `amount`).

---

## Appendix: Source Documents

| Document | Role |
|---|---|
| `docs/accounting_posting_specification.md` | §17 decisions 1–9, §1A–1G entry examples, §6 stock, §7 GST, §8 discounts, §10 idempotency/reversal |
| `docs/accounting_integration_audit.md` | Current-behavior facts, `ledger_amount` "not linked to any ledger posting", balance systems |
| `docs/accounting_integration_phase1.md` | Party → ledger mapping, migration, deletion protection |
