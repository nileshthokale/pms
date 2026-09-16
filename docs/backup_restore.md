# Database Backup & Restore — Phase 5F

**Date:** 2026-09-16
**Menu:** Master → Backup & Restore
**Files:** `database/backup_restore.py`, `screens/backup_restore.py`, `test_backup_restore.py`

---

## 1. Purpose

Give the pharmacy a safe, user-friendly way to back up and restore the **new application's SQLite database**. Backups protect against hardware failure, accidental deletion, corruption, and mistakes; restore brings the application back to a known-good state. The feature is deliberately conservative: it never overwrites anything silently, and every destructive step is preceded by validation and an automatic safety copy.

## 2. Database Scope

**Only the new application's SQLite database** — the file returned by `database.connection.get_db_path()` (production: `data/pharmacy.db`).

**The old Pharma-WINNER/MySQL database is never accessed, modified, reset, migrated, or connected to by this module or its tests.** No MySQL client, connector, or legacy code path exists in this feature.

## 3. Backup Format

A backup is a complete SQLite database file (`.db`) containing:

- the full schema (all 24 application tables),
- all data in every table,
- indexes and unique constraints,
- foreign-key definitions,
- (triggers would be included too; the application defines none).

The file is created with SQLite's **online backup API** (`sqlite3.Connection.backup`), which produces a consistent snapshot even while the database is in use — never a blind file copy.

## 4. Backup Creation

1. User clicks **Create Backup** (or calls `create_backup(destination)`).
2. `QFileDialog` asks for the destination; the default is `pharmacy_backup_YYYYMMDD_HHMMSS.db` in the database folder.
3. If a **folder** is given (or any path without a `.db` suffix), a timestamped filename is generated automatically.
4. The snapshot is written via the SQLite backup API, then **validated** before success is reported.
5. The UI shows the exact path, file size, and SHA-256 checksum.

Failure handling: if anything fails, the source database is untouched and no partial "backup" is reported as successful.

## 5. Validation

`validate_backup(path)` checks, **read-only** (SQLite `mode=ro` URI — the file can never be written during validation):

| Check | Result on failure |
|---|---|
| File exists / non-empty | `File not found.` / `File is empty.` |
| Opens as SQLite | `Not a valid SQLite database (...)` |
| `PRAGMA integrity_check` | `Integrity check failed: ...` |
| All 24 expected tables present | `Not a pharmacy database — missing tables: ...` |

Returns `{valid, reason, path, size_bytes, sha256, integrity, tables, missing_tables}`. Validation is idempotent and does not change the file (mtime and checksum stay identical).

## 6. Restore Workflow

1. User clicks **Restore Backup** and selects a `.db` file.
2. The file is **validated first** — an invalid file is refused and the current database is untouched.
3. A **strong confirmation dialog** explains that restoring replaces all current application data, shows the source path/size/checksum, and defaults to **No**.
4. Only after explicit Yes: an **automatic safety backup** of the current database is created (see §7).
5. The current database content is replaced by the backup content via the SQLite backup API.
6. The restored database is **verified** (validity + table presence).
7. On success the UI reports the safety-backup path and notes that a restart is recommended if the screen shows outdated data.

The selected backup file is never deleted or modified by restore.

## 7. Automatic Safety Backup

Every restore creates `pharmacy_pre_restore_YYYYMMDD_HHMMSS.db` next to the current database **before** replacing anything. If the restore fails at any point, the original database is recovered from this file automatically. The safety backup is a full valid backup and can also be restored manually later.

## 8. Failure Recovery

| Failure point | Behavior |
|---|---|
| Backup creation fails | Source untouched; error reported |
| Validation fails | Restore refused; nothing changed |
| Safety backup creation fails | Restore aborted **before** any change |
| Copy fails mid-restore | Original recovered automatically from the safety backup; error explains both outcomes |
| Restored data fails verification | Original recovered automatically from the safety backup |

The application is never intentionally left pointing at a partially restored database.

## 9. SHA-256 Verification

Every created backup returns its SHA-256 checksum. The UI displays it, and `verify_checksum(path, expected)` lets a user confirm that a backup file still matches (useful after copying backups to another drive or cloud storage). Checksums change whenever file bytes change (verified by tests).

## 10. SQLite Integrity

Validation runs `PRAGMA integrity_check` on the backup. Only `ok` is accepted. Combined with the online backup API (which never copies a torn page), a valid backup is internally consistent and safe to restore.

## 11. User Confirmation

Restore always requires an explicit confirmation dialog (default answer: No) that states plainly that current data will be replaced and lists the source details. There is no silent or one-click restore path.

## 12. Limitations

- Backups are full snapshots (no incremental/differential backups).
- No automatic/scheduled backups — the user triggers backups.
- No built-in cloud/network copy; users may copy the `.db` files themselves (checksums help verify them).
- No backup rotation/retention policy (the UI does not delete old backups).
- Restore is for this application's SQLite database only; it does not migrate from or to the legacy MySQL system.
- The application may need a restart after restore for any already-open screen to show fresh data.

## 13. Security Considerations

- Backup files contain the complete business data — treat them like the live database (access-controlled storage).
- Checksums detect accidental corruption, not tampering/malicious modification.
- Restore will happily load any valid pharmacy backup file; users should restore only files they trust.
- No credentials, cloud tokens, or network services are involved — everything is local files.

## 14. Data Preservation

The test suite verifies that a backup preserves (and restore recovers) data across all modules: masters, purchases (including GST fields), sales, stock batches, customers/suppliers, ledgers + ledger transactions, journals + items, receipts, and payments — including schema, indexes, UNIQUE constraints, and foreign-key definitions. Nothing is re-validated against business rules during backup/restore; the database content is preserved exactly.

## 15. Testing

`test_backup_restore.py` — **46 tests** (43 service-level + 3 PySide6 GUI tests):

- creation: empty/populated databases, all tables, schema/columns, indexes, UNIQUE constraints, foreign keys, purchases, sales, stock, customers/suppliers, ledgers, journals, GST fields
- validation: valid file, non-SQLite file, nonexistent, empty, corrupted, missing-tables database, read-only guarantee
- checksums: consistency, change detection, verification helper
- restore: success, replacement of changed data, full-module preservation, pre-restore safety backup, refusal of invalid/missing files, simulated failure recovery (original preserved, no data loss), source file unchanged, repeated backups/restores, read/write isolation, persistence after reopen
- info: database info, timestamped folder naming, last-backup record, real `data/pharmacy.db` untouched
- UI (skip without PySide6; run in the development environment): page opens, shows database info, has all action buttons

Isolation: every test uses a throwaway database via `PHARMACY_DB` and per-test temporary backup folders. `data/pharmacy.db` is never modified (asserted by test 41). No test touches MySQL.

## 16. Future Enhancements

- Scheduled/automatic backups with retention policy
- Optional backup integrity reminder (re-validate last backup on startup)
- Encrypted backups (SQLCipher-style or container encryption)
- Cloud/network destination integration
- Restore preview showing backup metadata (created date, table counts) inside the confirmation dialog
- Compressed backup archives for long-term storage
