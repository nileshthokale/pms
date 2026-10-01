# Purchase Invoice Delete — Phase 6B-2

**Date:** 2026-09-16  
**Menu:** Purchase → Purchase History  
**Files:** `database/purchase_dao.py`, `screens/purchase_invoice.py`, `test_purchase_delete.py`

## 1. Purpose

Provide a safe delete workflow for stored purchase invoices. Deletion removes the source purchase and reverses the stock and accounting effects created by that purchase.

## 2. Permissions

Deletion requires the existing centralized `delete_transactions` permission. ADMIN can delete. PHARMACIST/STAFF is rejected by the underlying DAO when an authenticated actor/session is supplied, independently of button visibility.

## 3. Confirmation

Purchase History now provides a Delete action. The user must select an invoice, review voucher, supplier, and net amount, then explicitly confirm that stock, accounting/ledger effects, and the source transaction will be reversed.

## 4. Stock Reversal

The stored purchase lines are authoritative. For each line, the exact quantity `pay_qty + free_qty` is subtracted from the matching `item_id + batch_no` stock batch. Current Item Master values are not consulted.

## 5. Accounting Reversal

The existing `PostingEngine.reverse(SOURCE_PURCHASE_INVOICE, invoice_id, cur=cur)` mechanism is used. Historical ledger rows remain; mirrored reversal rows offset the active posting net. No new posting direction or accounting rule was introduced.

## 6. Transaction Deletion

Purchase invoice items are deleted first, then the purchase invoice is deleted. Foreign-key cascade behavior remains available, and no unrelated stock batches or transactions are deleted.

## 7. Atomicity

Stock reversal, posting reversal, item deletion, and invoice deletion execute in one SQLite transaction. Any exception rolls back the entire operation, preserving the purchase, stock, and ledger state.

## 8. Rollback

Missing batches, insufficient stock, posting failures, and source failures abort the operation. The purchase source remains available after rollback and no partial stock/accounting reversal is committed.

## 9. Idempotency

A second delete of the same invoice returns a clear not-found/already-deleted error. It does not create additional reversal rows or change stock again.

## 10. Edit/Delete Lifecycle

The stored post-edit lines are used during deletion. Create → edit → delete and repeated edit → delete lifecycles are covered by dedicated tests.

## 11. Audit Behavior

The existing mirrored ledger reversal architecture preserves historical accounting rows. No separate delete-audit table was introduced in this phase.

## 12. Limitations

Zero-stock batches are preserved rather than globally removed because sales/return history may still reference them. A trusted internal DAO call without an explicit actor remains compatible with existing non-UI tests; authenticated UI/service calls are permission-checked.

## 13. Testing

`test_purchase_delete.py` contains 45 isolated tests covering source deletion, pay/free quantities, multiple batches, accounting reversal, supplier balance, rollback, permissions, repeat delete, edit/delete, foreign keys, integrity checks, and unrelated data preservation.

## 14. Security Considerations

The UI checks the centralized permission before showing the destructive confirmation. The DAO also checks an explicit actor or authenticated session. No username-specific checks or legacy database access are used.

## 15. Historical Preservation

Purchase source rows are removed by design, but historical ledger posting rows are preserved with mirrored reversal rows. Other purchases, sales, masters, and unrelated ledger entries are not modified.
