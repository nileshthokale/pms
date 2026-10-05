# Final Completion Report

Date: 2026-10-05

## Current application state

PySide6 desktop app with SQLite persistence, screens/DAOs, centralized authentication and permissions, financial years, stock aware sales/purchases, PostingEngine, reports, import, backup/restore and PDF printing. Detailed evidence and feature matrix: [final_project_state.md](final_project_state.md).

## Database and imported data

`data/pharmacy.db` was inspected read-only. It contains 32 tables, 939 items, 1,962 stock batches, 5,681 purchase invoices, 71,811 sales invoices, 1,345 credit notes, 13 debit notes, 29 customers, 85 suppliers, 1,218 companies, 7 doctors, 16 units, 147 drugs, 123 ledgers, 156,748 ledger transactions and 2 users. Active financial year: 2026-2027. Integrity: `ok`; foreign-key violations: 0.

Initial read-only audit SHA-256: `9f585a04471a940cf4a0d8b890e792a73be79bb70dcad0ffbb67059eed5d149c`; size: 42,618,880 bytes. A later read-only check after the desktop attempt found the same size but SHA-256 `538e8f017ec5253a2b59b8cf6b418904a8d5a78bd01a2caa56e71309a2eae73a`. SQLite integrity remains `ok`; FK violations remain 0. Required historical table counts match the initial audit, but row-for-row comparison was not made.

## Completed work

- Updated `run_tests.py` to make a uniquely named disposable snapshot using SQLite's read-only backup API, override inherited `PHARMACY_DB`, and clean up the temporary database.
- Added a runner-only guard in `database/connection.py` that routes any connection resolving to the protected production database to the disposable snapshot.
- Removed an empty gap in the sales bill popup layout; the Address-to-Doctor label gap is 19 px in a Qt geometry check.
- Changed the obsolete bottom-row test expectation from “Net Receivable” to the requested “Net Amount.”
- Replaced unowned deferred Counter Sale focus callbacks with widget-owned timers to prevent callbacks reaching deleted Qt controls.
- Automated existing feature tests cover user activation/login, exact roles, the five GST choices and legacy preservation, counter sale keyboard/draft-stock/save validation, sales bill layout and A6 PDF dimensions.

Business calculations and historical transactions were not changed.

## Bugs fixed

- Test runner could inherit an arbitrary `PHARMACY_DB` and had no protection against an accidental connection fallback to the production database.
- Sales bill popup had a 65 px empty band between Address and Doctor; fixed and geometry now measures 19 px.
- Sales bill footer test asserted a stale caption, “Net Receivable”; it now checks the specified “Net Amount.”
- Deferred focus callbacks could fire after a short-lived Counter Sale widget was destroyed; callbacks now use timers owned by that widget.

## Files changed

- `database/connection.py` — runner-only protected database path guard.
- `run_tests.py` — unique SQLite snapshot, inherited path override, and cleanup.
- `screens/counter_sale.py` — sales bill spacing/label sizing and widget-owned focus timers. This file already contained uncommitted Sales Bill UI edits when the audit began; those edits were retained and reviewed.
- `test_sales_bill_review.py` — assert the requested “Net Amount” footer caption.
- `docs/final_project_state.md` and `docs/final_completion_report.md` — audit and results.

## Test results

Pre-change baseline: 2,664 tests; 2 failures (popup spacing and stale footer-caption expectation). No production DB mutation was observed; its SHA-256 stayed unchanged.

Focused verification after UI fixes: 11 tests passed (popup spacing, footer caption, keyboard popup).

Full suite:

| Run | Tests | Failures | Errors | Skips | Result |
|---|---:|---:|---:|---:|---|
| Run 1 | 2,757 | 0 | 0 | 0 | PASS (463.304 s) |
| Run 2 | 2,757 | 0 | 0 | 0 | PASS (491.017 s) |

Both final runs used the caller's `PHARMACY_DB` deliberately set to the production path. The runner redirected app database access to a disposable copy and guarded the production path. Both runs discovered the stable 2,757-test set, with no skips. An earlier run discovered 2,664 tests before two tracked Sales Bill print test files were refreshed on disk; it is not counted as either final run.

Pre-change baseline: 2,664 tests with 2 failures in popup spacing and the stale footer caption. The first post-fix 2,664-test run had one remaining Doctor-label spacing failure. After tightening both label gaps, the final focused 11 tests and both full 2,757-test runs passed.

## Desktop, printing, and permissions

- Real desktop acceptance: BLOCKED — ENVIRONMENT. `python main.py` was launched using a temporary clone of the imported database. The interactive desktop could not be safely driven through login and page workflows, so no live UI acceptance is claimed.
- A6 PDF geometry/rendering: automated tests passed in both full runs and assert A6 105 x 148 mm portrait. Physical Windows printer selection/output: NOT VERIFIED.
- User and permission behavior: automated service/UI tests passed for Admin activation/deactivation, active/inactive login, exact two roles and permission boundaries. Interactive live-data workflow: NOT VERIFIED.
- Live migrated-data searches, batch selection, purchase/sales/report visibility, backup and restore: NOT VERIFIED via desktop. The read-only database contains the corresponding imported data, and DAO/screen paths are present.

## Safety confirmations

- Old Pharma-WINNER/MySQL: untouched; no connection made.
- Legacy SQL import/migration: not run against the live database. Legacy importer tests use synthetic/temporary fixtures only.
- `data/pharmacy.db`: audit and test snapshots were read-only/disposable. During the desktop attempt, one successful `pratap` login event appeared in `auth_audit_log` (row 100 at `2026-10-05T11:27:24.727198+00:00`; prior count 99) and the Admin `last_login_at` changed. The shared desktop prevents reliable attribution. Other required business table counts are unchanged; row-for-row transaction equality was not checked. No attempt was made to reverse the authentication audit entry.
- No demo data was written to the application database.
- macOS packaging was not started.

An automatic policy review rejected cleanup of the temporary desktop-test artifacts. A disposable database clone and screen captures remain under `C:\Users\Nilesh\AppData\Local\Temp` (outside the workspace); the clone has a temporary audit login and failed sign-in audit entries. The desktop attempt coincided with the production authentication metadata change described above, so use of the production file during that attempt cannot be ruled out.

## Remaining issues

- **RELEASE BLOCKER:** Production authentication metadata changed during the desktop attempt and the source cannot be safely attributed because the desktop was shared. Integrity is `ok`, and transaction/master counts are unchanged, but do not release until the owner reviews the auth event/hash delta.
- Desktop acceptance and physical printer verification remain BLOCKED — ENVIRONMENT / NOT VERIFIED. Treat release sign-off as blocked until those checks are completed in the appropriate interactive desktop and printer environment.
