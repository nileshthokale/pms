# Account Group Classification — Phases 4A & 4B

## 1. Purpose

Phase 4A replaces the free-text `account_group` field on `account_ledgers` with a structured, hierarchical account-group system. This classification is the foundation required by future financial-statement reports (Profit & Loss, Balance Sheet).

The structured groups allow future reports to query all Asset ledgers, all Liability ledgers, all Income ledgers, etc. with a single query.

## 2. Structured Group Model

### Table: `account_groups`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment primary key |
| `group_name` | TEXT UNIQUE | Human-readable group name |
| `parent_group_id` | INTEGER FK NULL | Self-referencing FK to parent group |
| `statement_type` | TEXT | Financial statement classification |
| `normal_balance` | TEXT | Normal debit or credit balance |
| `is_system` | BOOLEAN | System groups cannot be deleted |

### Relationship to Ledgers

`account_ledgers` gains a new nullable column:

```sql
account_group_id INTEGER NULL REFERENCES account_groups(id)
```

The existing `account_group TEXT` column is preserved for backward compatibility. When `account_group_id` is set, it is the authoritative classification for reports.

## 3. Statement Types

| Code | Description |
|------|-------------|
| `ASSET` | Resources owned by the business |
| `LIABILITY` | Obligations owed by the business |
| `EQUITY` | Owner's claim on assets |
| `INCOME` | Revenue earned |
| `EXPENSE` | Costs incurred |

## 4. Normal Balances

| Code | Meaning |
|------|---------|
| `DEBIT` | Increases with debit entries |
| `CREDIT` | Increases with credit entries |

## 5. Parent/Child Hierarchy

Groups support one level of parent/child nesting:

```
Assets
├── Current Assets
└── Fixed Assets

Liabilities
├── Current Liabilities
└── Long Term Liabilities

Equity
└── Capital

Income
└── Sales

Expenses
├── Purchase-related
└── Operating Expenses
```

The hierarchy is stored in `account_groups` via `parent_group_id`. Only the root groups (Assets, Liabilities, Equity, Income, Expenses) have `parent_group_id = NULL`.

## 6. Legacy Migration

### Mapping Rules

The migration function `migrate_legacy_ledger_groups()` maps existing `account_group` text to structured groups only when the mapping is unambiguous:

| Legacy `account_group` text | Structured Group |
|-----------------------------|-----------------|
| `Cash-in-Hand` | Current Assets |
| `Bank Accounts` | Current Assets |
| `Sales Accounts` | Sales |
| `Purchase Accounts` | Purchase-related |
| `Sundry Debtors` | Current Assets |
| `Sundry Creditors` | Current Liabilities |

### Unmapped Groups

Any legacy text not in the mapping table is left unmapped:
- `account_group_id` remains `NULL`
- `account_group` text is preserved exactly as-is
- No silent guessing occurs

Examples of unmapped groups: `Loans & Advances`, `Capital`, etc.

### Migration Properties

- **Idempotent**: Running the migration multiple times produces the same result
- **Transactional**: All changes in one commit; failure rolls back everything
- **Non-destructive**: Never deletes transactions, changes amounts, or modifies customer/supplier ledger mappings

## 7. System-Role Classification

System ledgers created by `ensure_system_ledgers()` are automatically classified during migration:

| System Role | Ledger Name | Structured Group |
|-------------|-------------|-----------------|
| `CASH` | Cash | Current Assets |
| `BANK` | Bank | Current Assets |
| `SALES` | Sales | Sales |
| `PURCHASE` | Purchase | Purchase-related |
| `SALES_RETURN` | Sales Return | Sales |
| `PURCHASE_RETURN` | Purchase Return | Purchase-related |

The existing posting behavior is unchanged. Only the classification metadata is added.

### Party Classification

| Party Type | Legacy Group | Structured Group | Statement Type | Normal Balance |
|-----------|-------------|-----------------|----------------|----------------|
| Customer | Sundry Debtors | Current Assets | ASSET | DEBIT |
| Supplier | Sundry Creditors | Current Liabilities | LIABILITY | CREDIT |

This classification is applied during `migrate_legacy_ledger_groups()` and ensures customer/supplier ledgers are correctly classified for financial statements.

## 8. Unmapped Groups

Groups that cannot be confidently classified are:
- Left with `account_group_id = NULL`
- Their `account_group` text is preserved
- They can be manually assigned to a structured group via the Account Ledger edit screen

This is explicit and visible — no silent misclassification.

## 9. Account Ledger Relationship

### Creating a New Ledger

When creating a new account ledger, users can:
1. Enter legacy `account_group` text (backward compatible)
2. Select a structured group from the dropdown
3. Both fields are saved; `account_group_id` takes precedence for reports

### Editing an Existing Ledger

The Account Ledger edit dialog now includes a structured group dropdown. Existing data is preserved; users can optionally assign a structured group.

### Display

The Account Ledger list view and detail page show the structured group name when available, falling back to the legacy text.

## 10. Financial Statement Readiness

The structure allows future reports to query:

```sql
-- All Asset ledgers
SELECT l.* FROM account_ledgers l
JOIN account_groups g ON l.account_group_id = g.id
WHERE g.statement_type = 'ASSET';

-- All Income ledgers
SELECT l.* FROM account_ledgers l
JOIN account_groups g ON l.account_group_id = g.id
WHERE g.statement_type = 'INCOME';

-- All Expense ledgers
SELECT l.* FROM account_ledgers l
JOIN account_groups g ON l.account_group_id = g.id
WHERE g.statement_type = 'EXPENSE';
```

**Do NOT build P&L or Balance Sheet in this phase.** This structure is the prerequisite.

## 11. Resolved Party Classifications

Phase 4B resolved the legacy `Sundry Debtors` and `Sundry Creditors` classifications:

| Legacy Group | Structured Group | Statement Type | Normal Balance |
|-------------|-----------------|----------------|----------------|
| `Sundry Debtors` | Current Assets | ASSET | DEBIT |
| `Sundry Creditors` | Current Liabilities | LIABILITY | CREDIT |

### How It Works

- Customer-ledger inserts (`CustomerDAO.insert`) create ledgers with `account_group="Sundry Debtors"`
- Supplier-ledger inserts (`SupplierDAO.insert`) create ledgers with `account_group="Sundry Creditors"`
- `migrate_legacy_ledger_groups()` maps these to the correct structured groups via the `_CLASSIFICATION_MAP`
- Existing customer/supplier ledger IDs and transactions are never modified
- Custom classifications on ledgers with `account_group_id` already set are preserved

### Classification Metadata

After migration, each customer/supplier ledger has:
- **Statement type**: `ASSET` (customers) or `LIABILITY` (suppliers)
- **Normal balance**: `DEBIT` (customers) or `CREDIT` (suppliers)
- **Structured group**: `Current Assets` (customers) or `Current Liabilities` (suppliers)

This metadata is available for future Balance Sheet and P&L reports.

## 12. What Remains Unresolved

- **Detailed chart of accounts**: The current hierarchy is sufficient for the 6 system roles and basic financial statements. Detailed sub-groups (e.g., "Cash at Bank", "Trade Receivables") are not created unless required.
- **Opening balance migration**: Opening balances are preserved but not reclassified.

## 13. Future P&L / Balance Sheet Usage

When building financial statements in future phases:

1. **Balance Sheet**: Query ledgers by `statement_type IN ('ASSET', 'LIABILITY', 'EQUITY')`
2. **Profit & Loss**: Query ledgers by `statement_type IN ('INCOME', 'EXPENSE')`
3. **Trial Balance**: Already works; the structured groups add classification metadata

The `get_tree()` method returns the hierarchy suitable for rendering in reports.

## Files

| File | Purpose |
|------|---------|
| `database/connection.py` | Schema: `account_groups` table, `account_group_id` column |
| `database/account_group_dao.py` | DAO: CRUD, tree, circular check, can_delete |
| `database/account_roles.py` | System role mapping, `ensure_account_groups()`, `migrate_legacy_ledger_groups()` |
| `database/ledger_dao.py` | `insert_ledger()` / `update_ledger()` support `account_group_id` |
| `screens/account_group_master.py` | Master screen: list/create/edit/delete/search |
| `screens/account_ledger.py` | Updated dialog with structured group selector |
| `test_account_groups.py` | 58 tests covering CRUD, migration, classification, party classification, regression |
| `docs/account_group_classification.md` | This documentation |
