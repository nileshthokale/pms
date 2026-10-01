# Hold Bill / Resume Bill — Phase 6B-6

## Purpose

The Hold Bill feature provides a safe temporary draft-sale system that allows
cashiers to pause a sale mid-entry and resume it later, without affecting stock,
accounting, or financial records.

> **A held bill is a temporary sales draft and does not affect stock, accounting,
> customer balances, or completed sales until the sale is explicitly completed.**

## Draft Concept

A held bill is a **DRAFT** only. It captures the items a user intends to sell
but does **NOT**:

- Reduce stock
- Create sales invoice accounting postings
- Change customer balance
- Affect Trial Balance
- Affect P&L
- Affect Balance Sheet
- Appear in completed sales history

Only completing/finalizing the sale through the normal Sales flow creates the
Sales transaction.

## Storage Design

### Tables

**`hold_bills`** — header record

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| hold_number | TEXT UNIQUE | HOLD-NNNN format |
| created_at | TEXT | Creation timestamp |
| updated_at | TEXT | Last modification |
| customer_id | INTEGER FK | Nullable |
| patient_name | TEXT | Nullable |
| doctor_id | INTEGER FK | Nullable |
| counter_no | TEXT | Nullable |
| remarks | TEXT | Nullable |
| status | TEXT | ACTIVE / RESUMED / DISCARDED |
| total_amount_preview | REAL | Sum of item amounts |
| created_by | TEXT | Username |
| updated_by | TEXT | Username |

**`hold_bill_items`** — line items

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| hold_bill_id | INTEGER FK | CASCADE delete |
| item_id | INTEGER FK | References items |
| item_name_snapshot | TEXT | Name at hold time |
| batch_no | TEXT | Batch identifier |
| pack_size | TEXT | Pack size at hold time |
| location | TEXT | Location at hold time |
| expiry | TEXT | Expiry at hold time |
| mrp | REAL | MRP at hold time |
| sale_qty | REAL | Quantity |
| discount_amount | REAL | Discount |
| amount | REAL | Line total |
| ordering | INTEGER | Display order |

## Hold Workflow

1. User enters items in the Counter Sale dialog
2. User clicks **Hold Bill** (orange button)
3. System validates that at least one item exists
4. System saves the draft to `hold_bills` + `hold_bill_items`
5. System generates a unique HOLD-NNNN number
6. System shows confirmation with hold number and amount
7. Dialog closes, current sale is cleared

**No stock is reduced. No accounting is posted.**

## Resume Workflow

1. User navigates to **Sales → Hold Bill**
2. User sees list of all active held bills
3. User selects a held bill and clicks **Resume**
4. System marks the hold as RESUMED
5. System opens the Counter Sale dialog pre-populated with the held items
6. **Stock is revalidated** at resume time:
   - Batch no longer exists → warning, item excluded
   - Batch expired → warning, item excluded
   - Insufficient stock → warning, item included (user must fix before save)
7. User reviews/corrects items as needed
8. User clicks **Save Sale** to complete the sale

**The normal SalesDAO.insert_invoice flow is used. Stock reduction and
accounting posting happen exactly once, at completion time.**

## Discard Workflow

1. User selects a held bill on the Hold Bill page
2. User clicks **Discard**
3. System shows confirmation dialog
4. On confirmation, system deletes the hold records
5. **No stock, accounting, or ledger effects occur**

## Snapshot Behavior

At hold time, the following are captured as a snapshot:
- Item ID, name, batch number, pack size, location
- Expiry, MRP, quantity, discount, amount

At resume time:
- **Current stock data** is used (batch lookup by item_id + batch_no)
- **Current pricing** follows the existing sale workflow
- Stale or invalid data triggers **visible warnings** to the user

The user is never silently given incorrect data. If a batch is no longer valid,
the user is notified and must correct before completing the sale.

## Stock Revalidation

| Condition | Behavior |
|-----------|----------|
| Batch exists, in stock | Item loaded normally |
| Batch exists, insufficient stock | Warning shown, item loaded (user must reduce qty) |
| Batch expired | Warning shown, item excluded |
| Batch not found | Warning shown, item excluded |
| Item deleted from master | Warning shown, item excluded |

## Completion

The completion lifecycle:

```
Create Hold → Resume → Complete Sale
```

Verifiable invariants:
- Exactly ONE completed sales transaction (sales_invoices row)
- Exactly ONE stock reduction (stock_batches update)
- Exactly ONE accounting posting set (ledger_transactions rows)
- Hold is no longer active (status = RESUMED)

## Accounting Behavior

| Action | Accounting Effect |
|--------|-------------------|
| Hold | None |
| Resume | None (just status change) |
| Discard | None |
| Complete Sale | Normal SalesDAO.insert_invoice posting |

## Permissions

| Role | Hold | View | Resume | Discard |
|------|------|------|--------|---------|
| ADMIN | Yes | Yes | Yes | Yes |
| PHARMACIST/STAFF | Yes | Yes | Yes | Yes |

Both roles have full operational hold/resume/discard capability via the
existing `PERM_COUNTER_SALE` permission.

## Financial Year

- Hold creation uses the current application date
- The hold itself is **temporary** and does not become a financial transaction
- No financial-year accounting records are created merely by holding a bill
- The date is validated only at sale completion time

## Crash / Restart Behavior

| Scenario | Behavior |
|----------|----------|
| App closes after Hold | Held bill persists in SQLite, available after restart |
| App closes after Resume but before Save | Hold remains RESUMED; user can create new sale manually |
| App closes during Complete | Transaction rolls back via SQLite WAL; no partial sale |

The hold data is stored in the same SQLite database as all other data, with
WAL journaling providing crash safety.

## Data Persistence

- Hold data persists across application restarts
- Hold data survives database connection close/reopen
- The `hold_bills` and `hold_bill_items` tables are created via
  `ensure_hold_tables()` which uses `CREATE TABLE IF NOT EXISTS`

## Testing

`test_hold_bill.py` contains 65 dedicated tests covering:

- Creation (7 tests)
- Storage (4 tests)
- No side effects (6 tests)
- Resume (9 tests)
- Completion lifecycle (7 tests)
- Delete/discard (6 tests)
- Multiple holds (4 tests)
- Persistence (2 tests)
- Authorization (4 tests)
- Financial year (3 tests)
- Read-only side effects (4 tests)
- Regression (9 tests)

All tests use temporary SQLite databases and never touch `data/pharmacy.db`.

## Limitations

- No automatic bill completion on resume
- No cloud synchronization of hold data
- Counter number is stored but not linked to a counter master
- Hold numbers are sequential across all users

## Future Enhancements

- Hold timeout/expiry with automatic discard
- Hold priority/urgency levels
- Hold transfer between counters
- Hold statistics/analytics
- Hold list filtering and search
- Print held bill preview before resume

## Files

| File | Purpose |
|------|---------|
| `database/hold_bill_dao.py` | Hold Bill DAO — tables, CRUD, status management |
| `screens/hold_bill.py` | Hold Bill page — list, resume, discard UI |
| `screens/counter_sale.py` | Modified — Hold Bill button, resume data loading |
| `database/sales_dao.py` | Modified — added `get_batch_by_item_and_batch_no` |
| `database/__init__.py` | Unchanged (hold_bill_dao imported directly) |
| `screens/__init__.py` | Modified — exports HoldBillPage |
| `ui/main_window.py` | Modified — wires HoldBillPage |
| `ui/menu_data.py` | Unchanged (already had "Hold Bill" entry) |
| `test_hold_bill.py` | 65 dedicated tests |
| `docs/hold_bill.md` | This documentation |
