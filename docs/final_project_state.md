# Current Project State Audit

Audit date: 2026-10-05 (workspace inspection)

## Application architecture

`main.py` starts a PySide6 desktop app, applies the shared stylesheet, initializes the SQLite schema/authentication/financial year, then presents login and `PharmacyMainWindow`. `ui/` owns navigation, menu mapping, components and theme. Each feature is split between a screen in `screens/` and data/service logic in `database/` (DAOs, posting, auth, imports, printing, backup, FY and reports). Tests are top-level `test_*.py`, collected by `run_tests.py`.

Subsystem findings:

1. **Schema:** `database/connection.py` creates/extends SQLite tables and indexes idempotently at startup; the current real file already has 32 tables.
2. **Authentication:** `database/auth.py` stores salted PBKDF2 hashes, login audit events, active state and session data. Supported application roles are exactly `ADMIN` and `PHARMACIST/STAFF`.
3. **Permissions:** one central role-to-permission map gates page and service actions; Admin-only actions include user/FY management, import, restore and transaction edits/deletes.
4. **Financial years:** `financial_years` records named date ranges and one active year. Current active row is 2026-2027.
5. **Stock:** inventory is in `stock_batches.stock_qty`; current migrated sales examples and regression tests support individual-unit quantities. Draft Counter Sale reservations are calculated in memory and do not write stock.
6. **Sales:** invoice headers/items use `sales_invoices` and `sales_invoice_items`. Sale commit validates, reduces batch stock and posts accounting in a transactional DAO path; edits/deletes reverse prior effects.
7. **Purchases:** purchase invoices/items create or adjust batch balances and post through accounting services; purchase return is represented by debit notes.
8. **Accounting:** `PostingEngine` writes reference-linked `ledger_transactions`; system-role mappings identify cash, bank, sales, returns and purchase ledgers. Reversal rows preserve audit history.
9. **Reports:** report DAOs and read-oriented screens cover stock, transactions, expiry, parties, GST, statements/books and Day End. Operational/report-page PDF export is inconsistent or absent (see matrix).
10. **Printing:** transaction documents have PDF rendering; pharmacy sales receipt has a separate shared A6 (105 x 148 mm portrait) print/PDF profile. Physical printer output was not verified.
11. **Import/migration:** current Import Data supports mapped CSV/XLSX master import. Legacy Pharma-WINNER migration code exists separately; it was not invoked against the real file or any MySQL service.
12. **Backup/restore:** SQLite snapshot, validation, restore and recovery logic are in `database/backup_restore.py`; GUI operation was not manually verified.
13. **UI/theme:** PySide6 screens use shared `ui/` navigation/components and a light Fusion stylesheet. Automated layout checks exist; actual screen visual QA is outstanding.

## Real database snapshot (read only)

Path: `data/pharmacy.db`. Inspected with SQLite URI `mode=ro`; no writes, migrations, imports or transactions were performed.

- Initial audit size: 42,618,880 bytes; initial SHA-256: `9f585a04471a940cf4a0d8b890e792a73be79bb70dcad0ffbb67059eed5d149c`. Latest read-only check after the desktop attempt: same size, SHA-256 `538e8f017ec5253a2b59b8cf6b418904a8d5a78bd01a2caa56e71309a2eae73a`.
- Tables: 32; `PRAGMA integrity_check`: `ok`; foreign-key check: 0 violations.
- Items 939; batches 1,962; purchase invoices 5,681; purchase items 11,829; sales invoices 71,811; sales items 44,245; credit notes 1,345; credit note items 779; debit notes 13; debit note items 8.
- Customers 29; suppliers 85; companies 1,218; doctors 7; units 16; drugs 147; ledgers 123; ledger transactions 156,748; users 2.
- Financial years: 2015-2016 through 2026-2027 (12); active: 2026-2027 (2026-04-01 to 2027-03-31).
- Both stored users are active and use the exact roles `ADMIN` and `PHARMACIST/STAFF`; credentials were not read.
- Current tables include account_groups, account_ledgers, app_users, auth_audit_log, categories, companies, credit/debit note headers and items, customer_receipts, customers, doctors, drugs, financial_years, hold bill headers/items, item_ingredients, items, journal headers/items, ledger_transactions, legacy mapping/meta, purchase headers/items, sales headers/items, stock_batches, supplier_payments, suppliers, and units.

Real sale rows show individual-unit stock: sample rows pair pack size 10 with sale quantities like 2, 4, 10 and stored amount equal to quantity times unit price. `items.mrp/rate` are zero on sampled migrated master rows while batch MRP is populated; historical sale item MRP tracks batch price. No pricing or stock conversion rules were changed.

Read-only availability probes found migrated item `BRONTICORT 6`; positive, unexpired stock includes `CALTONIC` batch `LTA-489448A` (expiry `2026-12-31`, stock 1,074) and `PROTONIX DSR` batch `C-26056` (expiry `2028-06-30`, stock 944). Supplier/customer name queries returned migrated names; latest purchase/sales voucher queries returned populated invoices. Stock, sales, purchase and ledger aggregate queries returned numeric results. These are database probes, not live screen demonstrations.

## Feature matrix

Status reflects source inspection plus existing automated test coverage. Interactive desktop behavior is separately marked NOT VERIFIED where applicable.

| Feature | Status | Evidence / remaining work |
|---|---|---|
| Item master | PARTIAL | CRUD/search, linked masters, ingredients and five GST choices are tested; no safe retirement/delete path. Unknown imported tax values are retained. |
| Company, Supplier, Customer, Doctor, Drug, Unit, Category masters | PARTIAL | Screens and DAOs are present and tested. Master lifecycle/search/deactivation coverage is uneven; no global delete/retire workflow. Category supports active/inactive state. |
| User master | COMPLETE | Selection-aware Activate/Deactivate labels; admin-only management; auth tests cover activation and inactive login denial. Interactive role workflow NOT VERIFIED. |
| Account Group, Account Ledger | COMPLETE | DAO/screens and hierarchy/mapping tests. |
| Sales Bill | PARTIAL | Counter sale bill flow and popup layout tests exist; real database UI workflow NOT VERIFIED. |
| Counter Sale | COMPLETE | Keyboard, merge, draft reservation, validation, posting and rollback tests. Real migrated-data keyboard session NOT VERIFIED. |
| Hold Bill | COMPLETE | DAO/screen, draft/resume tests; no live desktop session performed. |
| Purchase Invoice | COMPLETE | Entry, stock and accounting posting tests; manual migrated-data workflow NOT VERIFIED. |
| Credit Note, Debit Note | COMPLETE | DAO/screens and stock/account posting tests. |
| Customer Receipt, Supplier Payment, Journal Entry | COMPLETE | Screens/DAOs and posting tests. |
| Batch stock, expiry, stock deduction, stock return | COMPLETE | Stock and expiry reports; sale/purchase/return stock tests. |
| Draft stock reservation | COMPLETE | In-memory availability logic and add/merge/delete release tests; no production DB writes. |
| PostingEngine and ledger mapping | COMPLETE | Posting/reversal and end-to-end accounting test modules. |
| Trial Balance, P&L, Balance Sheet | PARTIAL | DAOs, screens and consistency tests; report-page PDF export is absent and manual review NOT VERIFIED. |
| Cash Book, Bank Book, Day End | COMPLETE | Screens/DAOs, filters, totals and PDF tests. |
| System roles | COMPLETE | Two-role constants and role mapping tests; no third role. |
| Stock, Sales, Purchase, Expiry, Party Wise, GST reports | PARTIAL | Report screens/DAOs and tests support data/filter views; manual viewing NOT VERIFIED. Consistent PDF export was not found for these report pages. |
| Import | COMPLETE | Import service/UI and fixture tests; legacy importer is not invoked. |
| Backup/Restore | PARTIAL | Backup/restore service and tests; live desktop backup/restore NOT VERIFIED. |
| Financial Year | COMPLETE | 12 years and active FY read from DB; service/screens/tests. |
| Authentication | COMPLETE | Hash-based auth, audit trail, two roles and inactive-user denial tests. |
| Sales/Counter, Purchase, CN, DN, receipt, payment printing | PARTIAL | PDF generation code/tests; Windows print dialog and printer path NOT VERIFIED. |
| A6 pharmacy bill | COMPLETE (PDF geometry) | A6 105 x 148 mm layout/PDF geometry tests; actual Windows printer NOT VERIFIED. |
| UI/theme | UI POLISH | Shared light theme and counter sale layout/pop-up tests. Visual review on the target display NOT VERIFIED. |

## Known issue verification

A. User activation/login: implementation and test coverage present; exact two roles preserved.

B. Item GST: the new-item dropdown is exactly five choices in requested labels/order. Existing unsupported imported values get an extra legacy entry when editing to preserve their stored value; no imported rows were rewritten.

C-F. Counter Sale: source/test coverage verifies keyboard progression, available stock reduced by this unsaved bill, same item+batch merge, delete releasing availability, commit-time validation/rollback, and compact UI sizing/light popup. Physical keyboard and screenshots against the real data are NOT VERIFIED.

G. Sales Bill: source contains a voucher/date/time header and spaced three-column form; the Address-to-Doctor gap measures 19 px and Doctor-to-field 4 px in Qt geometry checks. Visual alignment on the actual desktop is NOT VERIFIED.

H. A6: PDF tests assert 105 x 148 mm portrait; code uses the system printer selection path. Physical print NOT VERIFIED.

## COMPLETE

- SQLite schema and imported record integrity checks pass.
- Authentication, FY, stock, sales/purchase, accounting and report subsystems have implementation and automated tests.
- The existing implementation covers the requested GST, user activation, counter-sale draft/keyboard/validation, sales popup and A6 behavior at source/test level.
- No changes were made to historical business rows or business calculations.

## PARTIAL

- Visual/interactive acceptance with the real migrated dataset and Windows printer remains unperformed.
- Test runner now makes a disposable snapshot even when the caller sets `PHARMACY_DB` to production, and `database.connection` redirects accidental production-path connections while runner guards are active. The current 2,757-test suite passed twice with 0 failures, errors, or skips.

## BROKEN

- No confirmed application feature defect found in the source and test coverage reviewed.

## MISSING

- No verified real desktop acceptance record for this audit. This report does not claim that UI or physical printing passed.

## UI POLISH

- Counter sale and sales bill visual work exists and has automated geometry/layout assertions; screen-level visual inspection remains outstanding.

## RELEASE BLOCKERS

- RELEASE BLOCKER: During the attempted desktop launch, the production database hash changed and its auth audit gained one successful `pratap` login row (99 to 100, timestamp `2026-10-05T11:27:24.727198+00:00`); the active Admin's `last_login_at` reflects that event. The shared interactive desktop prevents reliable attribution. Other required historical transaction/master counts remain at the values above; `integrity_check` is `ok`, and foreign-key violations are 0. No attempt was made to reverse the audit entry. Owner review is required before release.
- BLOCKED — ENVIRONMENT: the interactive desktop could not be safely driven to complete login, live-data workflows, and physical printer verification. Do not use this report as a manual acceptance sign-off.
- NOT VERIFIED: backup/restore through the running GUI and real printer selection.

The attempted desktop check created a temporary database clone and screen captures in the Windows Temp folder. An automatic policy review rejected the cleanup command; those scratch artifacts remain outside the workspace and were not used as the application's production database.

## Safety

No connection to Pharma-WINNER/MySQL was made. The legacy migration was not run against live data. The database snapshot/count/integrity audit used SQLite `mode=ro`; full test runs used disposable snapshots. During the attempted desktop launch, the production file later changed hash as described above. Read-only follow-up found one additional successful authentication audit row and updated Admin `last_login_at`; all listed historical business table counts are unchanged, integrity remains `ok`, and foreign-key violations remain 0. The desktop was shared with another active session, so the source of this authentication metadata change is NOT VERIFIED. No attempt was made to edit or reverse the audit entry. Treat it as a release blocker requiring owner review. No further app or database activity was performed.
