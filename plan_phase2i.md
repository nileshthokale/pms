# Phase 2I: End-to-End Audit Test — Implementation Plan

## Objective
Create 10-scenario audit test (`test_accounting_end_to_end.py`) and documentation (`docs/accounting_posting_e2e_audit.md`) that verify all 6 accounting source types coexist correctly, posting accurate ledger entries across their full lifecycle.

---

## Files to Create

| File | Purpose |
|---|---|
| `test_accounting_end_to_end.py` | 10 audit test classes covering all 6 source types |
| `docs/accounting_posting_e2e_audit.md` | Audit documentation explaining scenarios and results |

---

## 10 Audit Test Classes

### 1. `TestScenario1_CustomerReceiptPosting`
- Insert customer receipt (cash mode)
- Verify: Debit CASH, Credit Customer Ledger
- Check row count = 2, amounts match, reference_type = CUSTOMER_RECEIPT

### 2. `TestScenario2_SupplierPaymentPosting`
- Insert supplier payment (cash mode)
- Verify: Debit Supplier Ledger, Credit CASH
- Check row count = 2, amounts match, reference_type = SUPPLIER_PAYMENT

### 3. `TestScenario3_CounterSalePosting`
- Insert counter sale (walk-in, cash)
- Verify: Debit CASH, Credit SALES for net_amount
- Check row count = 2

### 4. `TestScenario4_PurchaseInvoicePosting`
- Insert purchase invoice (credit)
- Verify: Debit PURCHASE, Credit Supplier Ledger
- Check row count = 2

### 5. `TestScenario5_CreditNotePosting`
- Insert credit note
- Verify: Debit SALES_RETURN, Credit Customer Ledger
- Check row count = 2

### 6. `TestScenario6_DebitNotePosting`
- Insert debit note
- Verify: Debit Supplier Ledger, Credit PURCHASE_RETURN
- Check row count = 2

### 7. `TestScenario7_EditAndRepostLifecycle`
- For each source type: insert → verify → edit → verify old reversed + new posted
- Check net matches new values

### 8. `TestScenario8_DeleteLifecycle`
- For each source type: insert → verify → delete → verify reversed
- is_posted() returns False

### 9. `TestScenario9_CrossModuleIndependence`
- Create all 6 source types independently
- Verify each posts correctly without affecting others
- Check global balance invariant: SUM(all debits) == SUM(all credits)

### 10. `TestScenario10_PersistenceAndBalanceConsistency`
- Fresh connection reads committed posting rows
- LedgerDAO.get_transactions() shows correct entries
- LedgerDAO.get_balance() matches expected values

---

## Test Infrastructure

- **DB path**: `_test_e2e_audit.db` (unique per module)
- **Table wipe list**: Full list including journal tables
- **setUp**: Delete DB, reinit, create all master records, ensure system ledgers
- **Helper methods**: `_nets(source_type, source_id)`, `_assert_posting_rows()`, `_assert_no_stray_ledgers()`

---

## Documentation Content

### `docs/accounting_posting_e2e_audit.md`
- Overview of 6 source types and their entry shapes
- Description of each audit scenario
- Expected results for each scenario
- How to run the tests: `python run_tests.py`
- Pass/fail summary table

---

## Verification

1. Run `python run_tests.py` — all new tests should pass
2. Verify no pre-existing tests broken (500 tests, 0 failures baseline)
3. Document results in audit markdown

---

## Execution Order

1. Create `test_accounting_end_to_end.py` with all 10 test classes
2. Run tests to verify they pass
3. Create `docs/accounting_posting_e2e_audit.md`
4. Run full suite to confirm no regressions
5. Report final results