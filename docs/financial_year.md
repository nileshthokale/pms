# Financial Year Management — Phase 5J

**Date:** 2026-09-16  
**Menu:** Master → Financial Year  
**Files:** `database/financial_year.py`, `screens/financial_year.py`, `test_financial_year.py`

## 1. Purpose

Provide a centralized financial-year list and active-year selection for the new SQLite pharmacy application without rewriting historical transactions or changing accounting calculations.

## 2. Financial Year Structure

Each year has an id, name, start date, end date, active flag, and creation timestamp. Dates use `YYYY-MM-DD`. Years cannot overlap and only one year may be active.

## 3. Default Financial Year

On an existing database with no financial-year rows, startup idempotently creates and activates `2026-2027`, from `2026-04-01` through `2027-03-31`. The database is migrated in place; it is not recreated.

## 4. Creating a Financial Year

ADMIN users can create a year from Master → Financial Year. The name and dates are reviewed and explicitly confirmed. New years are inactive unless created through the service with explicit activation.

## 5. Switching Financial Year

ADMIN users select an existing inactive year and confirm Set Active. Switching only changes the active flags. Existing transactions, stock, ledgers, and postings remain unchanged.

## 6. Active Financial Year

The navigation bar displays the active year from the centralized service. Staff can view the active year and the list but cannot create or switch years.

## 7. Transaction Date Rules

New Purchase, Sales/Counter Sale, Credit Note, Debit Note, Customer Receipt, Supplier Payment, and Journal Entry saves validate their transaction date against the active year. Dates before or after the active range are rejected with a clear message. Existing historical rows are not changed.

## 8. Report Behavior

Sales, Purchase, Party Wise, GST, P&L, Trial Balance, and Balance Sheet controls default to the active-year range or end date where their existing UI supports dates. Manual filters remain available and are not forcibly overwritten after the user changes them.

## 9. Permissions

The existing two-role authentication system provides `financial_year_management` to ADMIN only. PHARMACIST/STAFF can view the active year but cannot create or switch one. No new role was introduced.

## 10. Accounting Safety

Financial-year selection does not invoke PostingEngine, create ledger transactions, create opening balances, carry P&L into equity, or alter Trial Balance/P&L/Balance Sheet formulas. It only validates new dates and supplies safe report defaults.

## 11. Historical Data

Historical records remain in their original tables with their original dates and values. Creating or switching a financial year never migrates, deletes, rewrites, or reposts historical data.

## 12. Backup and Restore

`financial_years` is part of normal schema initialization and is included in backup validation. Existing SQLite backup/restore behavior remains unchanged; snapshots preserve financial years and the active flag along with transactions.

## 13. Import Compatibility

Master-data import does not require a financial-year field. Company, Unit, Drug, Supplier, Customer, Doctor, and Item imports continue to use their existing mappings and validation.

## 14. Migration

The new table is created with `CREATE TABLE IF NOT EXISTS` and a partial unique active index. Existing databases retain all prior records. Default-year creation occurs only when no year exists.

## 15. Validation and Testing

Validation rejects malformed dates, empty names, reversed ranges, duplicate names, overlaps, and invalid IDs. `test_financial_year.py` contains 75 isolated tests covering schema, creation, defaults, active switching, date boundaries, permissions, persistence, preservation, and safety.

## 16. Limitations and Future Enhancements

This phase does not implement automatic year-end closing, opening-balance transfer, P&L-to-equity transfer, financial-year-aware SQL changes inside report DAOs, cloud sync, licensing, or macOS packaging. Future work may add explicit FY filter controls to more reports and a richer year audit history.
