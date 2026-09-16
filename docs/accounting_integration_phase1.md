# Accounting Integration Phase 1

**Date:** 2026-09-15
**Status:** COMPLETE
**Test results:** 42 Phase 1 tests passed, 208 total tests passed, 0 actual failures

---

## 1. Objective

Phase 1 establishes Customer/Supplier → Account Ledger mapping. Every customer and supplier is now linked to an Account Ledger, preparing Account Ledger as the future single source of accounting truth.

This phase does NOT implement automatic ledger posting. It creates the prerequisite mapping so that Phase 2 can post transactions directly to each party's linked ledger.

The audit that preceded this work is documented in `docs/accounting_integration_audit.md`.

---

## 2. Completed Work

### 2.1 Customer Ledger Mapping

**File:** `database/customer_dao.py`

Each customer now has a nullable `ledger_id` foreign key referencing `account_ledgers(id)`.

**Automatic ledger creation:**
- `CustomerDAO.insert()` creates an Account Ledger immediately after creating the customer record.
- Ledger name pattern: `"Customer - {customer_name}"`
- Account group: `Sundry Debtors`
- The customer's `credit_limit`, `credit_period`, address, city, state, contact_person, and contact_no are copied to the ledger.
- Opening balance: positive values are stored as `Debit`, negative as `Credit`, with the absolute amount stored.

**Idempotency:**
- If a ledger with the same name already exists (e.g., from a previous run or migration), the existing ledger is reused rather than creating a duplicate.
- This is enforced by checking `account_ledgers.ledger_name` before inserting.

**Update synchronization:**
- `CustomerDAO.update()` syncs the linked ledger's name and details when the customer record is edited.
- If no ledger exists yet (edge case for pre-Phase 1 records that somehow bypassed migration), one is created during update.
- No second ledger is ever created for the same customer.

**Deletion protection:**
- `CustomerDAO.delete()` checks whether the linked ledger has any transactions in `ledger_transactions`.
- If transactions exist, deletion is blocked and `False` is returned.
- If the ledger has no transactions (or no ledger is linked), the customer is deleted normally and `True` is returned.

**Ledger helpers:**
- `CustomerDAO.get_ledger_id(customer_id)` — returns the `ledger_id` for a customer, or `None`.
- `CustomerDAO.get_customer_by_ledger(ledger_id)` — reverse lookup, returns customer record for a given ledger.

### 2.2 Supplier Ledger Mapping

**File:** `database/supplier_dao.py`

Identical pattern to Customer DAO:

- `SupplierDAO.insert()` creates an Account Ledger immediately after creating the supplier record.
- Ledger name pattern: `"Supplier - {supplier_name}"`
- Account group: `Sundry Creditors`
- Opening balance: positive values are stored as `Credit`, negative as `Debit` (suppliers are creditors).
- Idempotent — reuses existing ledger if name collision occurs.

**Update synchronization:**
- `SupplierDAO.update()` syncs the linked ledger name and details.
- Also syncs `tax_no` from `sales_tax_no` to the ledger.

**Deletion protection:**
- `SupplierDAO.delete()` checks `ledger_transactions` before allowing deletion.
- Blocked if ledger has transactions.

**Ledger helpers:**
- `SupplierDAO.get_ledger_id(supplier_id)` — returns `ledger_id` or `None`.
- `SupplierDAO.get_supplier_by_ledger(ledger_id)` — reverse lookup.

### 2.3 Database Changes

**File:** `database/connection.py`

Two nullable foreign key columns were added to existing tables using safe `ALTER TABLE` statements:

```sql
ALTER TABLE customers ADD COLUMN ledger_id INTEGER
    REFERENCES account_ledgers(id) ON DELETE SET NULL

ALTER TABLE suppliers ADD COLUMN ledger_id INTEGER
    REFERENCES account_ledgers(id) ON DELETE SET NULL
```

These `ALTER TABLE` statements run during `init_database()` and are idempotent — SQLite's `ALTER TABLE ADD COLUMN` is a no-op if the column already exists. The columns are nullable so existing rows are unaffected.

No `UNIQUE` constraint was added on `ledger_id` — one-to-one enforcement is handled at the DAO level (each insert/update ensures only one ledger per party).

### 2.4 Migration

**File:** `database/migrate_ledger_mapping.py`

`run_migration()` handles existing customers and suppliers that were created before Phase 1.

**Behavior:**
1. Ensures `ledger_id` columns exist on `customers` and `suppliers` (idempotent).
2. For each customer without a `ledger_id`: creates an Account Ledger with name `"Customer - {name}"`, copies address/contact details from the customer record, migrates `opening_balance` into the ledger's `opening_balance` and `opening_balance_type`, and writes `ledger_id` back to the customer.
3. For each supplier without a `ledger_id`: same process, using `"Supplier - {name}"` and group `Sundry Creditors`.
4. If a ledger with the same name already exists, it is reused rather than duplicated.

**Idempotency:**
- Only processes customers/suppliers where `ledger_id IS NULL`.
- Running twice produces no duplicates.

**Transactional safety:**
- Entire migration runs inside a single transaction.
- Rolls back completely on any failure.

**Opening balance migration:**
- Positive customer opening balance → `Debit` type, absolute value.
- Positive supplier opening balance → `Credit` type, absolute value.
- The original `customers.opening_balance` and `suppliers.opening_balance` values are preserved (not zeroed out).

**Data preservation:**
- Existing customer and supplier records are never deleted or overwritten.
- Existing ledgers are never deleted or overwritten.
- Only `ledger_id` is written back to link existing records.

### 2.5 UI Changes

**Customer Master** (`screens/customer_master.py`):
- Table now displays a "Ledger" column showing the linked ledger name.
- Customer dialog shows a read-only Ledger indicator (label with ledger name) when editing an existing customer that has a linked ledger.

**Supplier Master** (`screens/supplier_master.py`):
- Same additions: "Ledger" column in the table and read-only Ledger indicator in the dialog.

---

## 3. Accounting Source of Truth

Account Ledger is intended to become the future authoritative source for all accounting balances.

**Current implementation (Phase 1):**
- Account Ledger exists and can be maintained manually via the Account Ledger screen.
- Customer and supplier records now have linked ledgers.
- No automatic posting occurs — ledger_transactions is not written to by any transaction module.

**Future intent (Phase 2+):**
- All transactions (purchases, sales, credit notes, debit notes, receipts, payments) will post directly to `ledger_transactions` via the linked party ledger.
- `LedgerDAO.get_balance()` will become the single source of truth for party balances.
- The legacy balance calculation methods will be replaced.

Phase 1 creates the mapping infrastructure. It does not redirect any balance calculations to use the ledger.

---

## 4. Legacy Balance Calculations

The following methods remain temporarily available and have NOT been removed:

- **`CustomerReceiptDAO.get_customer_balance()`** — calculates customer outstanding balance from `sales_invoices`, `credit_notes`, and `customer_receipts`.
- **`SupplierPaymentDAO.get_supplier_balance()`** — calculates supplier outstanding balance from `purchase_invoices`, `debit_notes`, and `supplier_payments`.

These methods are still used by the Customer Receipt and Supplier Payment screens. They are independent of `LedgerDAO.get_balance()` and will produce different numbers for the same party.

**Do not assume automatic ledger posting exists.** These legacy calculations will be replaced in Phase 2 when transactions begin posting to `ledger_transactions`.

---

## 5. What Is NOT Implemented Yet

Phase 1 does NOT implement any of the following:

- Automatic Sales ledger posting (counter sales do not write to `ledger_transactions`)
- Automatic Purchase ledger posting (purchases do not write to `ledger_transactions`)
- Credit Note ledger posting (credit notes do not write to `ledger_transactions`)
- Debit Note ledger posting (debit notes do not write to `ledger_transactions`)
- Supplier Payment ledger posting (payments do not write to `ledger_transactions`)
- Customer Receipt ledger posting (receipts do not write to `ledger_transactions`)
- Journal Entry → `ledger_transactions` posting (journal entries remain isolated in `journal_entries`/`journal_entry_items`)
- Centralized automatic posting or reversal engine
- Trial Balance report
- Profit & Loss report
- Balance Sheet report
- Payment allocation model (linking receipts/payments to specific invoices)
- Replacement of legacy balance methods with ledger-based queries

---

## 6. Future Architecture

The intended future flow (Phase 2+, NOT current behavior):

```
Transaction (Purchase / Sale / Credit Note / Debit Note / Receipt / Payment)
    │
    ▼
Accounting Posting Engine
    │
    ▼
ledger_transactions (debit/credit entries per party ledger)
    │
    ▼
Account Ledger (running balance per ledger)
    │
    ▼
Trial Balance
    │
    ▼
Profit & Loss / Balance Sheet
```

This architecture is NOT yet implemented. Phase 1 only establishes the `customers.ledger_id` and `suppliers.ledger_id` mapping that the posting engine will use.

---

## 7. Data Safety

- **Transactional:** All migration and DAO operations use explicit transactions (`BEGIN`/`COMMIT`/`ROLLBACK`). Failure at any point rolls back all changes.
- **Existing records preserved:** No existing customers, suppliers, or ledgers are deleted or overwritten by Phase 1 changes.
- **Linked ledgers protected:** `CustomerDAO.delete()` and `SupplierDAO.delete()` refuse to delete a party whose ledger has transactions, preventing orphaned accounting records.
- **Idempotent schema changes:** `ALTER TABLE ADD COLUMN` is safe to run on databases that already have the column.
- **Idempotent migration:** `run_migration()` only processes records where `ledger_id IS NULL`. Running it multiple times produces no duplicates.

---

## 8. Testing

**Phase 1 ledger-mapping tests:** 42 tests in `test_ledger_mapping.py` — all pass.

**Total test suite:** 208 tests across 7 test files — all pass.

| Test file | Tests | Status |
|-----------|-------|--------|
| `test_ledger_mapping.py` | 42 | All pass |
| `test_account_ledger.py` | 25 | All pass |
| `test_customer_receipt.py` | 26 | All pass |
| `test_supplier_payment.py` | 28 | All pass |
| `test_credit_note.py` | 26 | All pass |
| `test_debit_note.py` | 26 | All pass |
| `test_journal_entry.py` | 35 | All pass |
| **Total** | **208** | **All pass** |

**0 actual test failures.**

Note: unittest discovery reported 2 import errors for `screens/` and `ui/` packages. These are not test failures — they occurred because unittest attempted to import these packages as test modules, and PySide6 was not available in the test environment. No application tests are affected.

---

## 9. Files Changed

| File | Change |
|------|--------|
| `database/connection.py` | Added `ledger_id` columns to `customers` and `suppliers` via safe `ALTER TABLE` |
| `database/customer_dao.py` | Rewritten: auto-creates ledger on insert, syncs on update, blocks delete if ledger has transactions, added `get_ledger_id()` and `get_customer_by_ledger()` |
| `database/supplier_dao.py` | Rewritten: same ledger support as customer_dao |
| `database/migrate_ledger_mapping.py` | New: idempotent migration script with `run_migration()` |
| `screens/customer_master.py` | Added "Ledger" column in table, read-only Ledger indicator in dialog |
| `screens/supplier_master.py` | Added "Ledger" column in table, read-only Ledger indicator in dialog |
| `test_ledger_mapping.py` | New: 42 tests covering migration, CRUD, deletion safety, cross-module, and legacy balance |
| `test_account_ledger.py` | Updated expected ledger count (3 → 5) to account for auto-created ledgers in setUp |
| `test_journal_entry.py` | Updated expected ledger count (4 → 6) to account for auto-created ledgers in setUp |
| `docs/accounting_integration_audit.md` | Existing audit document (unchanged, referenced by this document) |
| `docs/accounting_integration_phase1.md` | This document |

---

## 10. Phase 1 Completion Status

**Phase 1: COMPLETE**

- 42 Phase 1 ledger-mapping tests: passed
- 208 total tests (existing + new): passed
- 0 actual test failures
- Customer/Supplier → Account Ledger mapping: implemented
- Migration for existing records: implemented
- UI ledger indicators: implemented
- Automatic ledger posting: NOT implemented (Phase 2)
