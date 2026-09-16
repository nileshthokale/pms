# Accounting Integration Audit

**Date:** 2026-09-14
**Purpose:** Full audit of current accounting foundation before implementing automatic ledger posting.
**Status:** Read-only audit — no code changes made.

---

## Files Inspected

| File | Role |
|------|------|
| `database/connection.py` | Schema definitions (all tables) |
| `database/ledger_dao.py` | Account ledger CRUD + balance calculation |
| `database/journal_dao.py` | Journal entry CRUD (manual only) |
| `database/purchase_dao.py` | Purchase invoice CRUD + stock |
| `database/sales_dao.py` | Counter sale CRUD + stock |
| `database/credit_note_dao.py` | Customer/supplier credit note CRUD + stock |
| `database/debit_note_dao.py` | Supplier debit note CRUD + stock |
| `database/supplier_payment_dao.py` | Supplier payment CRUD + balance |
| `database/customer_receipt_dao.py` | Customer receipt CRUD + balance |
| `database/customer_dao.py` | Customer master CRUD |
| `database/supplier_dao.py` | Supplier master CRUD |
| `screens/account_ledger.py` | Account ledger UI (list + detail) |
| `screens/journal_entry.py` | Journal entry UI (manual) |
| `screens/counter_sale.py` | Counter sale UI |
| `screens/purchase_invoice.py` | Purchase invoice UI |
| `screens/customer_receipt.py` | Customer receipt UI + balance display |
| `screens/supplier_payment.py` | Supplier payment UI + balance display |
| `screens/credit_note.py` | Credit note UI |
| `screens/debit_note.py` | Debit note UI |
| `screens/customer_master.py` | Customer master UI |
| `screens/supplier_master.py` | Supplier master UI |

---

## Transaction Audit

### A. Purchase Invoice

| Attribute | Current Implementation |
|-----------|----------------------|
| **Transaction name** | Purchase Invoice |
| **Header table** | `purchase_invoices` |
| **Detail table** | `purchase_invoice_items` |
| **Voucher prefix** | `PV-` (auto-increment) |
| **Financial fields** | `invoice_net_amount`, `bill_discount`, `total_amount`, `gst_amount`, `debit_note_amount`, `other_amount`, `paid_amount`, `round_off`, `net_amount` |
| **Party relationship** | `supplier_id` → `suppliers(id)` |
| **Stock effect** | Increases `stock_batches.stock_qty` on insert; reverses on delete/update |
| **Ledger posting** | **NONE** — no write to `ledger_transactions` |
| **Customer/supplier balance** | **NONE** — not used in `SupplierPaymentDAO.get_supplier_balance()` |
| **Voucher no generation** | `PurchaseDAO.generate_next_voucher_no()` — independent sequence |

**Proposed accounting treatment:**
- Debit: Purchase Account (or Stock Account)
- Credit: Supplier Ledger (or Cash/Bank if `paid_amount > 0`)
- Partial payment entry: Credit Supplier for `net_amount`, Debit Cash for `paid_amount`

**Missing information for automatic posting:**
- No mapping of `supplier_id` → `account_ledgers.id` (no foreign key from suppliers to ledgers)
- No mapping of `purchase_type` → specific ledger accounts (Cash vs Credit)
- No mapping of GST to tax ledgers
- `paid_amount` vs `net_amount` split not modeled for journal entries

---

### B. Counter Sale

| Attribute | Current Implementation |
|-----------|----------------------|
| **Transaction name** | Counter Sale |
| **Header table** | `sales_invoices` |
| **Detail table** | `sales_invoice_items` |
| **Voucher prefix** | `CS-` (auto-increment) |
| **Financial fields** | `discount`, `paid_amount`, `total_amount`, `round_off`, `net_amount` |
| **Party relationship** | `customer_id` → `customers(id)`, `doctor_id` → `doctors(id)` |
| **Stock effect** | Decreases `stock_batches.stock_qty` on insert; restores on delete |
| **Ledger posting** | **NONE** — no write to `ledger_transactions` |
| **Customer/supplier balance** | **NONE** — not used in `CustomerReceiptDAO.get_customer_balance()` |
| **Voucher no generation** | `SalesDAO.generate_next_bill_no()` — independent sequence |

**Proposed accounting treatment:**
- Debit: Cash/Bank (for `paid_amount`)
- Debit: Customer Ledger (for `net_amount - paid_amount`, i.e., credit portion)
- Credit: Sales Account (for `net_amount`)

**Missing information for automatic posting:**
- No mapping of `customer_id` → `account_ledgers.id`
- No mapping of `sale_type` → specific ledger accounts (Cash vs Credit vs Credit Card)
- No separate account for discount allowed
- `paid_amount` field not captured in `sales_invoices` table (only `paid_amount` in table, no separate cash ledger reference)

---

### C. Customer Credit Note

| Attribute | Current Implementation |
|-----------|----------------------|
| **Transaction name** | Customer Credit Note |
| **Header table** | `credit_notes` |
| **Detail table** | `credit_note_items` |
| **Voucher prefix** | `CN-` (auto-increment) |
| **Financial fields** | `total_amount`, `ledger_amount` |
| **Party relationship** | `customer_id` → `customers(id)` |
| **Stock effect** | Increases `stock_batches.stock_qty` (restores returned goods) |
| **Ledger posting** | **NONE** |
| **Customer balance** | Used in `CustomerReceiptDAO.get_customer_balance()` as deduction |
| **Voucher no generation** | `CreditNoteDAO.generate_next_voucher_no()` — independent sequence |

**Proposed accounting treatment:**
- Debit: Sales Return Account
- Credit: Customer Ledger

**Missing information for automatic posting:**
- No mapping of `customer_id` → `account_ledgers.id`
- No Sales Return ledger account exists by default
- `ledger_amount` field exists but is not linked to any ledger posting

---

### D. Supplier Debit Note

| Attribute | Current Implementation |
|-----------|----------------------|
| **Transaction name** | Supplier Debit Note |
| **Header table** | `debit_notes` |
| **Detail table** | `debit_note_items` |
| **Voucher prefix** | `DN-` (auto-increment) |
| **Financial fields** | `total_amount`, `ledger_amount` |
| **Party relationship** | `supplier_id` → `suppliers(id)` |
| **Stock effect** | Decreases `stock_batches.stock_qty` (goods returned to supplier) |
| **Ledger posting** | **NONE** |
| **Supplier balance** | Used in `SupplierPaymentDAO.get_supplier_balance()` as deduction |
| **Voucher no generation** | `DebitNoteDAO.generate_next_voucher_no()` — independent sequence |

**Proposed accounting treatment:**
- Debit: Supplier Ledger
- Credit: Purchase Return Account

**Missing information for automatic posting:**
- No mapping of `supplier_id` → `account_ledgers.id`
- No Purchase Return ledger account exists by default
- `ledger_amount` field exists but is not linked to any ledger posting

---

### E. Supplier Payment

| Attribute | Current Implementation |
|-----------|----------------------|
| **Transaction name** | Supplier Payment |
| **Header table** | `supplier_payments` |
| **Detail table** | None (single-table) |
| **Voucher prefix** | `SP-` (auto-increment) |
| **Financial fields** | `amount` |
| **Party relationship** | `supplier_id` → `suppliers(id)` |
| **Stock effect** | None |
| **Ledger posting** | **NONE** |
| **Supplier balance** | Used in `SupplierPaymentDAO.get_supplier_balance()` as deduction |
| **Voucher no generation** | `SupplierPaymentDAO.generate_next_voucher_no()` — independent sequence |

**Proposed accounting treatment:**
- Debit: Supplier Ledger
- Credit: Cash/Bank (based on `payment_mode`)

**Missing information for automatic posting:**
- No mapping of `supplier_id` → `account_ledgers.id`
- No mapping of `payment_mode` → specific Cash/Bank ledger accounts
- No line-item detail (what invoices are being paid)

---

### F. Customer Receipt

| Attribute | Current Implementation |
|-----------|----------------------|
| **Transaction name** | Customer Receipt |
| **Header table** | `customer_receipts` |
| **Detail table** | None (single-table) |
| **Voucher prefix** | `CR-` (auto-increment) |
| **Financial fields** | `amount` |
| **Party relationship** | `customer_id` → `customers(id)` |
| **Stock effect** | None |
| **Ledger posting** | **NONE** |
| **Customer balance** | Used in `CustomerReceiptDAO.get_customer_balance()` as deduction |
| **Voucher no generation** | `CustomerReceiptDAO.generate_next_voucher_no()` — independent sequence |

**Proposed accounting treatment:**
- Debit: Cash/Bank (based on `receipt_mode`)
- Credit: Customer Ledger

**Missing information for automatic posting:**
- No mapping of `customer_id` → `account_ledgers.id`
- No mapping of `receipt_mode` → specific Cash/Bank ledger accounts
- No line-item detail (what invoices are being paid)

---

### G. Journal Entry

| Attribute | Current Implementation |
|-----------|----------------------|
| **Transaction name** | Journal Entry |
| **Header table** | `journal_entries` |
| **Detail table** | `journal_entry_items` |
| **Voucher prefix** | `JV-` (auto-increment) |
| **Financial fields** | Per-line `debit` and `credit` |
| **Party relationship** | `ledger_id` → `account_ledgers(id)` |
| **Stock effect** | None |
| **Ledger posting** | **Standalone only** — writes to `journal_entry_items` but does NOT write to `ledger_transactions` |
| **Voucher no generation** | `JournalDAO.generate_next_voucher_no()` — independent sequence |

**Current behavior:**
- Manual journal entries can be created via UI
- Entries are stored in `journal_entries` + `journal_entry_items`
- Balanced entries enforced (total debit = total credit)
- **No integration with `ledger_transactions`** — journal entries are isolated

---

## Balance Calculation Analysis

### Three Independent Balance Systems

| Balance System | Location | Formula | Opening Balance Source |
|---------------|----------|---------|----------------------|
| **Customer Balance** | `CustomerReceiptDAO.get_customer_balance()` | `SUM(sales.net_amount) - SUM(credit_notes.total_amount) - SUM(receipts.amount)` | **IGNORED** — `customers.opening_balance` is not used |
| **Supplier Balance** | `SupplierPaymentDAO.get_supplier_balance()` | `SUM(purchases.net_amount) - SUM(debit_notes.total_amount) - SUM(payments.amount)` | **IGNORED** — `suppliers.opening_balance` is not used |
| **Ledger Balance** | `LedgerDAO.get_balance()` | `opening_balance + SUM(transactions.debit) - SUM(transactions.credit)` | **USED** — `account_ledgers.opening_balance` is used |

### Inconsistencies Found

1. **Dead opening_balance fields:**
   - `customers.opening_balance` — stored but never used in balance calculation
   - `suppliers.opening_balance` — stored but never used in balance calculation
   - These fields are displayed in master screens but have no effect on outstanding balance

2. **Conflicting balance sources:**
   - Customer balance is calculated from transaction tables (sales, credit notes, receipts)
   - Supplier balance is calculated from transaction tables (purchases, debit notes, payments)
   - Account Ledger balance is calculated from `account_ledgers.opening_balance` + `ledger_transactions`
   - These three systems are completely independent and will produce different numbers

3. **Purchase invoice screen shows wrong balance:**
   - `screens/purchase_invoice.py:508` displays `suppliers.opening_balance` as "supplier balance"
   - This is NOT the outstanding balance — it's just the static opening balance field
   - The real outstanding balance is in `SupplierPaymentDAO.get_supplier_balance()`

4. **No link between party tables and ledgers:**
   - `customers` table has no `ledger_id` foreign key
   - `suppliers` table has no `ledger_id` foreign key
   - No way to map a customer/supplier to their account ledger

---

## Summary Table

| Transaction | Current Behavior | Stock Effect | Current Ledger Posting | Proposed Debit | Proposed Credit | Missing Information |
|-------------|-----------------|--------------|----------------------|---------------|----------------|-------------------|
| Purchase Invoice | CRUD + stock increase | Increases stock | NONE | Purchase Account / Stock | Supplier Ledger / Cash | supplier→ledger mapping, tax ledger mapping |
| Counter Sale | CRUD + stock decrease | Decreases stock | NONE | Cash / Customer Ledger | Sales Account | customer→ledger mapping, sale_type→ledger mapping |
| Customer Credit Note | CRUD + stock restore | Restores stock | NONE | Sales Return | Customer Ledger | customer→ledger mapping, Sales Return account |
| Supplier Debit Note | CRUD + stock decrease | Decreases stock | NONE | Supplier Ledger | Purchase Return | supplier→ledger mapping, Purchase Return account |
| Supplier Payment | CRUD only | None | NONE | Supplier Ledger | Cash/Bank | supplier→ledger mapping, payment_mode→ledger mapping |
| Customer Receipt | CRUD only | None | NONE | Cash/Bank | Customer Ledger | customer→ledger mapping, receipt_mode→ledger mapping |
| Journal Entry | Manual CRUD | None | Standalone (no ledger_transactions write) | N/A (manual) | N/A (manual) | Integration with `ledger_transactions` |

---

## Critical Findings

### 1. No Automatic Ledger Posting Exists
No transaction module writes to `ledger_transactions`. The Account Ledger screen shows an empty transaction list unless entries are manually added.

### 2. No Party-to-Ledger Mapping
There is no foreign key or mapping table connecting `customers`/`suppliers` to `account_ledgers`. This must be created before automatic posting can work.

### 3. Duplicate Balance Calculations Will Conflict
If automatic posting is implemented, the existing `get_customer_balance()` and `get_supplier_balance()` methods will produce different numbers than the ledger balance for the same party. These must be reconciled or replaced.

### 4. Journal Entry Is Isolated
Journal entries are stored in `journal_entries`/`journal_entry_items` but never flow into `ledger_transactions`. The Account Ledger detail view will not show journal entries.

### 5. Voucher Numbering Is Fragmented
Each module has its own independent voucher sequence (PV-, CS-, CN-, DN-, SP-, CR-, JV-). This is acceptable but means there is no unified voucher register.

---

## Recommendations for Next Phase (DO NOT IMPLEMENT YET)

1. **Add `ledger_id` to `customers` and `suppliers` tables** — link each party to their account ledger
2. **Create default ledger accounts** — Cash, Bank, Sales, Purchase, GST, Sales Return, Purchase Return
3. **Implement posting hooks** in each DAO's insert/update/delete methods
4. **Replace `get_customer_balance()` and `get_supplier_balance()`** with ledger-based balance queries
5. **Integrate journal entries into `ledger_transactions`** so the Account Ledger shows all activity
6. **Handle `opening_balance` migration** — convert `customers.opening_balance` and `suppliers.opening_balance` into opening ledger transactions

---

## Test Suite Status

All existing tests were run after this audit (no code changes were made):

- `test_account_ledger.py`: All pass
- `test_customer_receipt.py`: All pass
- `test_supplier_payment.py`: All pass
- `test_credit_note.py`: All pass
- `test_debit_note.py`: All pass
- `test_journal_entry.py`: All pass

**Total: 164 tests passing (135 existing + 29 journal entry)**
