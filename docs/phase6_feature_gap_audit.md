# Phase 6A — Complete Feature Gap & Workflow Audit

**Date:** 2026-09-16  
**Scope:** Read-only audit of the new SQLite Pharmacy Management System  
**Legacy system:** Not accessed. No Pharma-WINNER/MySQL connection or migration was used.

## 1. Executive Summary

The application has a substantial working core: seven pharmacy masters, purchase/sales/returns, receipts/payments, journal entry, ledger/reporting, backup/restore, master import, PDF output, two-role authentication, and financial-year configuration.

The largest gaps are workflow completeness rather than missing core database services:

- Five visible menu entries currently open `PlaceholderPage` screens.
- Several original master screens support create/edit but not delete, and search/relationship behavior is inconsistent.
- Purchase history has edit and print but no visible delete action.
- Journal Entry has edit/delete but no print/PDF action.
- Permission enforcement is centralized for major admin features and transaction edit/delete handlers, but menu coverage is incomplete and several operational actions are not individually guarded.
- The current production database has no application users and no transaction/posting rows, so production workflow behavior is not demonstrated by live data.
- GUI tests are skipped because PySide6 is unavailable in the test environment.

**Audit totals:**  
- Implemented: 24 feature/workflow areas  
- Partially implemented: 17  
- Missing: 7  
- Implemented but different from original: 5  
- Implemented but needs additional testing: 11  
- Not applicable: 3

These categories overlap where a feature is both partial and under-tested.

## 2. Complete Menu Audit

| Feature | Current status | Relevant source files | Original workflow | Current workflow | Gap | Severity | Recommended next action |
|---|---|---|---|---|---|---|---|
| Sales > New Bill | IMPLEMENTED | `screens/counter_sale.py`, `database/sales_dao.py` | Create a sales bill | Counter Sale page/dialog | Named as Counter Sale rather than separate Sales Bill | MEDIUM | Decide whether a separate Sales Bill workflow is required |
| Sales > Hold Bill | MISSING | `ui/menu_data.py`, `ui/main_window.py` | Hold and resume an unfinished bill | Placeholder | No hold storage or resume flow | HIGH | Add hold-bill persistence and resume workflow |
| Sales > Return Bill | IMPLEMENTED | `screens/credit_note.py` | Customer return / credit note | Credit Note page | Naming differs | LOW | Preserve alias and document mapping |
| Sales > Sales History | IMPLEMENTED | `screens/counter_sale.py` | Search, edit, delete, print sales | Flattened item-level history | One invoice may appear on multiple rows; no dedicated bill detail view | MEDIUM | Add invoice-level selection/detail view |
| Sales > Day End | MISSING | `ui/main_window.py` | Day-end close/report workflow | Placeholder | No day-end process | HIGH | Define day-end requirements before implementation |
| Purchase > New Purchase | IMPLEMENTED | `screens/purchase_invoice.py` | Create purchase invoice | Purchase page/dialog | Uses existing stored math | LOW | Add workflow-level GUI coverage |
| Purchase > Purchase Return | IMPLEMENTED | `screens/debit_note.py` | Supplier return / debit note | Debit Note page | Naming differs | LOW | Preserve alias and document mapping |
| Purchase > Purchase History | IMPLEMENTED | `screens/purchase_invoice.py` | History, edit, delete, print | History with edit and print | No visible delete action | HIGH | Add protected delete workflow or document intentional policy |
| Purchase > Supplier Payment | IMPLEMENTED | `screens/supplier_payment.py` | Create/history/edit/delete/print payment | Existing page | Strongly aligned | LOW | Add GUI coverage when PySide6 is available |
| Account > Customer Receipt | IMPLEMENTED | `screens/customer_receipt.py` | Receipt and ledger effect | Existing page | Strongly aligned | LOW | Add GUI coverage |
| Account > Cash Book | MISSING | `ui/main_window.py` | Cash book | Placeholder | No cash-book screen/report | HIGH | Implement or explicitly remove from menu after requirements decision |
| Account > Bank Book | MISSING | `ui/main_window.py` | Bank book | Placeholder | No bank-book screen/report | HIGH | Implement or explicitly remove from menu |
| Account > Ledger | IMPLEMENTED | `screens/account_ledger.py`, `database/ledger_dao.py` | Ledger inquiry | Existing ledger page | Needs FY/default-filter audit | MEDIUM | Add active-FY default and workflow tests |
| Account > Journal Entry | IMPLEMENTED | `screens/journal_entry.py`, `database/journal_dao.py` | Create/edit/delete journal | Existing page | No print/PDF action; no explicit journal date test in legacy suites | MEDIUM | Add journal print and date/permission tests |
| Account > Account Roles | IMPLEMENTED | `screens/account_roles.py`, `database/account_roles.py` | Accounting role configuration | Ledger system-role initializer | This is accounting-role setup, not user-role management | LOW | Clarify label in documentation |
| Account > Trial Balance | IMPLEMENTED | `screens/trial_balance.py`, `database/trial_balance_dao.py` | Trial balance | Existing page | FY is a UI default, not a DAO-level active-FY filter | MEDIUM | Add explicit FY semantics and tests |
| Account > Profit & Loss | IMPLEMENTED | `screens/profit_loss.py`, `database/profit_loss_dao.py` | P&L | Existing page | Same active-FY default limitation | MEDIUM | Add explicit FY semantics and tests |
| Account > Balance Sheet | IMPLEMENTED | `screens/balance_sheet.py`, `database/balance_sheet_dao.py` | Balance sheet | Existing page | As-of date defaults to FY end; no FY-specific DAO contract | MEDIUM | Add explicit FY semantics and tests |
| Reports > Stock Report | IMPLEMENTED | `screens/stock_master.py`, `database/stock_dao.py` | Stock report | Existing stock page | Naming differs from Stock Master | LOW | Align labels |
| Reports > Sales/Purchase/Expiry/Party Wise/GST | IMPLEMENTED | Corresponding screens/DAOs | Reports with filters/totals | Existing report screens | Date defaults vary and are not uniformly FY-driven | MEDIUM | Standardize active-FY defaults and manual override tests |
| Master > Account Group | MISSING FROM MENU | `screens/account_group_master.py`, `ui/menu_data.py` | Master menu contains Account Group | Screen exists but is unreachable from current menu | Functionality is inaccessible through navigation | HIGH | Add menu wiring after requirements confirmation |
| Master > Account Ledger | IMPLEMENTED UNDER ACCOUNT | `screens/account_ledger.py` | Original master/account ledger | Reachable under Account > Ledger | Location differs from original master list | LOW | Document navigation mapping |
| Master > User | MISSING FROM MENU | `screens/user_management.py`, `ui/menu_data.py` | User management | `User Master` opens placeholder; `UserManagementPage` is not wired to that label | Working page exists but is inaccessible | CRITICAL | Wire `User Master` to UserManagementPage and preserve ADMIN guard |
| Master > Category Master | MISSING | `ui/main_window.py` | Category master | Placeholder | No category schema/DAO/page | MEDIUM | Confirm whether category is still required |
| Master > Backup & Restore | IMPLEMENTED | `screens/backup_restore.py`, `database/backup_restore.py` | Backup/restore | Existing page and service | ADMIN guard exists on create/restore handlers; validate-only action policy should be clarified | LOW | Add GUI permission tests |
| Master > Import Data | IMPLEMENTED | `screens/import_data.py`, `database/import_service.py` | Master import | Existing page/service | STAFF is denied by current policy; acceptable but should be documented | LOW | Document ADMIN-only decision |
| Master > Financial Year | IMPLEMENTED | `screens/financial_year.py`, `database/financial_year.py` | FY management | Existing page/service | FY changes do not automatically refresh already-instantiated report pages | MEDIUM | Refresh affected screens after switch |

## 3. Master Audit

| Feature | Status | Evidence and gap |
|---|---|---|
| Company, Unit, Drug, Doctor | PARTIALLY IMPLEMENTED | Create/edit/duplicate validation exist. Delete actions are not exposed. Search behavior is not uniform. |
| Supplier and Customer | PARTIALLY IMPLEMENTED | Create/edit and linked account-ledger creation exist. Delete is not exposed in the current screens; ledger synchronization is handled in DAOs. |
| Item | PARTIALLY IMPLEMENTED | Company and Unit FKs exist; ingredients use `item_ingredients`; Drug relationship is supported through ingredients. Item delete is not exposed and ingredient editing needs workflow-level coverage. |
| Account Group | IMPLEMENTED BUT INACCESSIBLE | `account_group_master.py` exists with CRUD, but the current menu does not expose it. |
| Account Ledger | IMPLEMENTED BUT DIFFERENT | Available under Account rather than Master; system-role protection exists. |
| Import | IMPLEMENTED | CSV/XLSX, mapping, validation, duplicates, templates, audit history. Master imports are FY-independent as required. |
| Permissions | PARTIAL | Admin/staff auth exists, but most master page CRUD handlers do not visibly enforce a centralized permission at each action boundary. |
| UI usability | PARTIAL | Master pages share a consistent dark UI, but delete/search/refresh affordances are inconsistent. |

Relationship observations:

- `items.company_id` and `items.unit_id` are nullable FKs with `ON DELETE SET NULL`.
- `item_ingredients.item_id` and `drug_id` are cascading FKs.
- Supplier/customer `ledger_id` links are nullable and set null on ledger deletion.
- No orphan rows were observed in the production database because transaction tables are empty; broader orphan detection should be run against populated production data.

## 4. Sales Audit

**Workflow:** Create -> Save -> Stock -> Ledger -> History -> Edit -> Delete -> Print

- Create/save: IMPLEMENTED. Sales data is stored in `sales_invoices` and `sales_invoice_items`.
- Stock deduction: IMPLEMENTED in `SalesDAO.insert_invoice` and update/delete lifecycle paths.
- Ledger posting: IMPLEMENTED through `SOURCE_COUNTER_SALE` / sales posting paths.
- History: IMPLEMENTED, but flattened one row per item rather than one row per bill.
- Edit: IMPLEMENTED and protected by ADMIN edit permission.
- Delete: IMPLEMENTED and protected by ADMIN delete permission.
- Print: IMPLEMENTED through `document_printing.py` and `Print / PDF`.
- FY validation: IMPLEMENTED at new dialog save boundary.
- Main gap: no separate “Sales Bill” page distinct from Counter Sale; no GUI tests because PySide6 is unavailable.

**Status:** IMPLEMENTED BUT DIFFERENT / NEEDS TESTING. **Severity:** MEDIUM.

## 5. Purchase Audit

**Workflow:** Create -> Save -> Stock -> Ledger -> History -> Edit -> Delete -> Print

- Create/save, stock update, posting, history, edit, and print are implemented.
- Purchase history does not expose a delete action even though the DAO has lifecycle capabilities elsewhere.
- Purchase GST values are stored/displayed; no new values are invented by printing.
- FY validation is applied at save.

**Status:** PARTIALLY IMPLEMENTED. **Severity:** HIGH because delete behavior is incomplete relative to the requested workflow.

## 6. Returns Audit

### Credit Note

Create, stock effect, ledger posting, history, edit, delete, print, stored reason/quantity, and FY date validation are implemented. The service uses existing stored fields and does not invent GST.

**Status:** IMPLEMENTED, GUI testing gap MEDIUM.

### Debit Note

Create, stock effect, ledger posting, history, edit, delete, print, stored reason/quantity, and FY date validation are implemented.

**Status:** IMPLEMENTED, GUI testing gap MEDIUM.

## 7. Accounting Audit

The posting engine and tests cover these source types:

- `CUSTOMER_RECEIPT`
- `SUPPLIER_PAYMENT`
- `COUNTER_SALE`
- `PURCHASE_INVOICE`
- `CREDIT_NOTE`
- `DEBIT_NOTE`
- `JOURNAL_ENTRY`

Existing tests strongly cover debit/credit direction, reversals, edits, deletes, idempotency, persistence, ledger visibility, Trial Balance, P&L, and Balance Sheet regression paths. No posting logic was changed in this audit.

**Observed gap:** accounting reports are date-driven and FY controls are currently UI defaults rather than a unified FY parameter in every DAO. This can show historical data if users manually choose other dates, which is consistent with current manual-filter behavior but should be documented explicitly.

**Status:** IMPLEMENTED / NEEDS FY CONTRACT TESTING. **Severity:** MEDIUM.

## 8. Report Audit

| Report | Status | Findings |
|---|---|---|
| Stock | IMPLEMENTED | Read-only stock view; no PDF action visible. |
| Sales | IMPLEMENTED BUT DIFFERENT | Manual filters exist; active FY is used as default range after Phase 5J. |
| Purchase | IMPLEMENTED BUT DIFFERENT | Manual filters exist; no report print action observed. |
| Expiry | IMPLEMENTED | Read-only operational report; FY is not naturally required. |
| Party Wise | IMPLEMENTED BUT DIFFERENT | Manual filters and active-FY defaults; needs populated-data verification. |
| GST | IMPLEMENTED BUT DIFFERENT | Uses stored purchase GST/report fields; no fabricated sales GST. |
| Trial Balance | IMPLEMENTED BUT DIFFERENT | As-of date defaults to FY end; DAO remains ledger/date based. |
| P&L | IMPLEMENTED BUT DIFFERENT | Date range defaults to active FY; manual override remains. |
| Balance Sheet | IMPLEMENTED BUT DIFFERENT | As-of date defaults to active FY end. |

Common gaps:

- No consistent Print/PDF action across reports.
- Empty-state and manual override behavior are not covered uniformly by GUI tests.
- PySide6-dependent tests are skipped in the current environment.
- Active FY selection does not automatically refresh already-open report widgets.

## 9. Security Audit

Exactly two application roles are defined in `database/auth.py`: `ADMIN` and `PHARMACIST/STAFF`. No `MANAGER` or `VIEWER` role was found in the application implementation inspected for authentication.

- User management: ADMIN-only service and page.
- Backup: ADMIN-only handler/menu permission.
- Restore: ADMIN-only handler/menu permission.
- Import: ADMIN-only policy.
- Transaction edit/delete: ADMIN-only guards exist in major transaction handlers.
- Reports: available to staff.
- Printing: available to staff.
- Financial year management: ADMIN-only.
- Last active ADMIN protection: implemented and tested.

**Gaps:** User Management is not wired to the `User Master` menu label; account/master CRUD enforcement is not uniformly centralized at every screen handler; no production users currently exist in the development database.

**Status:** PARTIALLY IMPLEMENTED. **Severity:** CRITICAL for inaccessible user management, HIGH for inconsistent handler-level enforcement.

## 10. Financial Year Audit

The service/table/UI/default/overlap/active uniqueness/date-validation behavior is implemented and has 75 dedicated tests. The active production year is `2026-2027` (`2026-04-01` through `2027-03-31`).

**Gaps:** Switching FY does not rebuild or refresh all open screens automatically. Report DAOs do not receive an explicit FY identifier; the UI supplies default date ranges. Existing transaction rows are not tagged with an FY, which is safe for migration but leaves FY association date-derived.

**Status:** IMPLEMENTED BUT DIFFERENT. **Severity:** MEDIUM.

## 11. Backup/Restore Audit

Backup/restore uses SQLite online backup and validation. The `financial_years` table is included in `EXPECTED_TABLES`, so the service validates its presence in backups. Existing transaction and accounting tables are included.

**Gaps:** `app_users` and `auth_audit_log` are not listed in `EXPECTED_TABLES`, despite being part of the new application schema. Backups still copy them physically, but validation does not require them. This may be intentional backward compatibility, but it should be made explicit.

**Status:** IMPLEMENTED WITH A SCHEMA-VALIDATION GAP. **Severity:** MEDIUM.

## 12. Import Audit

CSV/XLSX master import, mapping, preview, validation, duplicate handling, atomic import, templates, audit history, and read-only preview are implemented and covered by 69 dedicated tests. Import does not require FY columns and remains compatible with all seven masters.

**Gap:** Admin-only import policy is enforced, but the user-facing documentation should make that operational decision prominent. Multi-file dependency orchestration remains user-controlled.

**Status:** IMPLEMENTED. **Severity:** LOW/MEDIUM.

## 13. Printing Audit

PDF generation exists for Sales Bill, Counter Sale Bill, Purchase Invoice, Credit Note, Debit Note, Customer Receipt, and Supplier Payment. Transaction history screens expose `Print / PDF` actions. Printing is read-only and uses stored values.

**Gaps:** Journal Entry and reports do not expose print actions. PDF rendering is a small standard-library writer rather than a full typography/layout library; PySide6 printer preview is unavailable in the current environment. No printer GUI validation was run.

**Status:** PARTIALLY IMPLEMENTED. **Severity:** MEDIUM.

## 14. Database Audit

Production database path: `data/pharmacy.db`  
Observed size: 229,376 bytes  
Observed tables: 27  
Active FY: `2026-2027`  
Application users: 0 rows  
Transaction rows: 0 for purchases, sales, notes, receipts, payments, journals, and ledger transactions.

Table inventory:

| Table | Purpose | Key relationships |
|---|---|---|
| companies | Company master | Referenced by items |
| units | Unit master | Referenced by items |
| drugs | Drug master | Referenced by item_ingredients |
| suppliers | Supplier master | Optional ledger link; transaction references |
| customers | Customer master | Optional ledger link; transaction references |
| doctors | Doctor master | Sales invoice reference |
| items | Item master | Company/unit references |
| item_ingredients | Item-drug relationship | Cascades from item/drug |
| account_groups | Structured account hierarchy | Self-parent relationship |
| account_ledgers | Ledger master/system roles | Account group and party links |
| ledger_transactions | Posted ledger rows | Ledger FK |
| purchase_invoices / purchase_invoice_items | Purchases | Supplier/item FKs; cascade item rows |
| sales_invoices / sales_invoice_items | Sales | Customer/doctor/item/stock FKs |
| stock_batches | Stock by item/batch | Item FK |
| credit_notes / credit_note_items | Customer returns | Customer/item/stock FKs |
| debit_notes / debit_note_items | Supplier returns | Supplier/item/stock FKs |
| customer_receipts | Customer receipts | Customer FK |
| supplier_payments | Supplier payments | Supplier FK |
| journal_entries / journal_entry_items | Manual journals | Ledger and journal FKs |
| financial_years | FY configuration | No transaction FK; date-derived association |
| app_users | Authentication users | No business-data FK |
| auth_audit_log | Auth audit events | No business-data FK |

The schema has no duplicate feature tables observed. Foreign keys are enabled by `connection.py`. Orphan detection was limited by the empty production transaction state; populated-data orphan checks should be part of deployment validation.

## 15. Test Coverage Audit

Current full suite: **1,327 tests**, with **22 PySide6 environment skips**.

Strong coverage:

- Posting direction, reversal, edit/delete, idempotency, persistence.
- Trial Balance, P&L, Balance Sheet calculations and regression paths.
- Backup/restore integrity and rollback.
- Import parsing, validation, duplicates, rollback, templates.
- PDF generation and read-only safety.
- Authentication roles, hashing, admin safety, audit, and permissions.
- Financial-year service and date boundaries.

Weak or missing coverage:

- GUI screens generally cannot run because PySide6 is unavailable.
- Placeholder menu workflows have no functional tests.
- Master delete/search consistency is not comprehensively tested.
- Purchase delete workflow is not covered because the current page does not expose it.
- Journal/PDF/report printing GUI coverage is missing.
- Active-FY switch refresh behavior across open screens is not tested.
- Production-like populated database audit is not represented by the empty development DB.

## 16. UI/UX Audit

Observed issues:

- `PlaceholderPage` is used for Hold Bill, Day End, Cash Book, Bank Book, Category Master, and User Master.
- `Account Group` screen exists but is absent from `MENUS`.
- `UserManagementPage` exists but `User Master` is not wired to it.
- Navigation labels mix legacy names (`New Bill`, `Return Bill`) with implementation names (`Counter Sale`, `Credit Note`).
- Refresh controls exist on many pages but active FY switching does not refresh all open page instances.
- Print/PDF actions are present on transaction histories but absent from Journal Entry and reports.
- The dark application theme is consistent for existing pages, while generated documents use light paper output as intended.

## 17. Missing Features

1. Hold Bill workflow.
2. Day End workflow.
3. Cash Book screen.
4. Bank Book screen.
5. Category Master.
6. Account Group menu access.
7. User Master menu access to the existing user-management screen.

## 18. Partially Implemented Features

1. Purchase lifecycle: no visible delete action.
2. Sales history: item-flattened rather than invoice-level.
3. Master CRUD: delete/search behavior inconsistent.
4. Account Ledger/financial reports: FY is a UI date default, not a unified DAO FY contract.
5. Financial-year switching: active state changes but all open screens do not refresh.
6. Printing: transaction documents only; no journal/report printing.
7. Permissions: central policy exists, but enforcement is not uniform across all master/account handlers.
8. Backup validation: auth tables are copied but not required in `EXPECTED_TABLES`.

## 19. Recommended Implementation Order

1. Wire `User Master` to `UserManagementPage` and add production first-run/login verification.
2. Resolve or remove placeholder entries: Hold Bill, Day End, Cash Book, Bank Book, Category Master.
3. Add Account Group to the menu and document Account Ledger navigation.
4. Decide and implement the purchase-delete policy.
5. Standardize master CRUD/search/duplicate/permission behavior.
6. Define active-FY refresh semantics for open screens and add explicit report/FY tests.
7. Add Journal Entry and report print/PDF workflows if required by the original operation.
8. Add populated-database orphan/integrity audit tooling and GUI tests in a PySide6-enabled CI environment.

## 20. Production-Readiness Observations

- Core accounting and transaction services have strong regression coverage, but the live development database contains no transaction data and no users, so operational readiness is not proven by current production state.
- The application currently exposes several navigation entries that are visibly placeholders; this is the most important user-facing completeness issue.
- Database migrations are additive and foreign keys are enabled. The current audit did not modify the database.
- Backup/restore compatibility is good for financial years and transactions, but authentication-table validation should be explicitly reviewed.
- No old Pharma-WINNER/MySQL database was accessed.
- No application functionality was changed in Phase 6A. Only this report and its machine-readable summary were created.
