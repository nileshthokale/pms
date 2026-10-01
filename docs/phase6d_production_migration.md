# Phase 6D-1: Controlled Production Database Migration & Backup Verification

## Overview
This document summarizes the Phase 6D-1 procedure for preparing the NEW SQLite production database safely for real-world acceptance testing. The procedure validates the built-in startup schema migration and ensures all existing production data is preserved.

## Current Production DB State (Pre-Migration)
- **Path**: `data/pharmacy.db`
- **Size**: 229,376 bytes
- **SHA-256**: `36fa37cc02a47999a78d2ea1b0897595ffa61f20ca118356f01c321b38d74524`
- **Table Count**: 28
- **Status**: The active financial year (`2026-2027`) exists. Basic master data exists (e.g., one item, one user). Transactions and accounting data are zero.
- **Missing Tables**: `categories`, `hold_bills`, `hold_bill_items`.

## Backup Procedure
Before any migration, a full backup was created using the application's built-in `create_backup` service (via the SQLite online backup API).
- **Backup File**: `backups/pharmacy_pre_acceptance_backup_20260917_150050.db`
- **Backup SHA-256**: `cbd394b53de1fedf9a46186758e68cf510cbdd9433d4afc5e13a442afc2209f9`
- **Backup Status**: Explicit validation (`validate_backup()`) passed. `integrity_check` is `ok`.

## Migration Rehearsal on a Copy
A rehearsal migration was performed by copying the production database to a temporary location and setting `PHARMACY_DB` to point to the copy. The application's standard initializations (`init_database()`, `auth.ensure_auth_schema()`, `ensure_default_financial_year()`, `ensure_hold_tables()`) were triggered.
- **Result**: Success. The expected schema tables were created.
- **Foreign Key Check**: `0` violations.
- **Integrity Check**: `ok`.

## Schema Additions
The migration added the following 3 tables safely to the database:
1. `categories`
2. `hold_bills`
3. `hold_bill_items`

## Preservation Verification
- All existing 28 tables remain intact.
- Row counts for all pre-existing tables remain identical.
- Foreign keys remain valid, confirming no orphan records were created by the schema changes.

## Idempotence
The migration rehearsal was explicitly triggered a second time against the already-migrated database. 
- **Result**: No duplicate tables, no data corruption, row counts did not change. This guarantees that repeated startup migrations are idempotent and structurally safe.

## Real Migration
The real production migration was executed directly against `data/pharmacy.db`.
- **Pre-Migration Hash**: `36fa37cc02a47999a78d2ea1b0897595ffa61f20ca118356f01c321b38d74524`
- **Post-Migration Hash**: `e0270a1b528c651a9472523554e8c84cb30961592fb19cd8a7c391f076839352`
*(A hash change is expected due to new tables being added. The data remains preserved).*
- **Post-Migration Size**: 249,856 bytes
- **Post-Migration Table Count**: 31 (inclusive of `categories`, `hold_bills`, `hold_bill_items`).

## Backup Restore Rehearsal
A new temporary database was created by restoring the pre-acceptance backup.
- **Validation**: Passed.
- **Data Verifications**: The active financial year and master items were confirmed to exist inside the restored copy.
- **Integrity**: `ok`.

## Integrity Checks
Both the pre-migration backup and the post-migration production databases pass `PRAGMA integrity_check` and `PRAGMA foreign_key_check` unconditionally.

## Rollback / Recovery Approach
Should the new schema introduce unexpected bugs during acceptance testing, the `pharmacy_pre_acceptance_backup_20260917_150050.db` backup is confirmed readable, valid, and fully restorable. No business transactions were created during this check, so a rollback involves no data loss.

## Limitations
- This migration only applies to the newly designed SQLite backend. It does not pull historical data from the old Pharma-WINNER/MySQL system.

## Acceptance Prerequisites
- 0 business transactions were introduced.
- Production data preservation was structurally tested.
- Backups are validated and functional.
- The test suite (`test_production_migration.py`) contains 30 dedicated safety tests.
- Database is fully ready for business operations and user acceptance testing.
