# Master Data Import — Phase 5G

**Date:** 2026-09-16  
**Menu:** Master → Import Data  
**Files:** `database/import_service.py`, `screens/import_data.py`, `test_import_service.py`

## 1. Purpose

Import master data into the new application's SQLite database without importing historical transactions. Supported masters are Company, Unit, Drug, Supplier, Customer, Doctor, and Item.

## 2. Supported Formats

UTF-8 CSV, including UTF-8 BOM, quoted fields, headers, and blank rows, is supported. `.xlsx` workbooks are supported when the installed `openpyxl` package is available. `.xls` is intentionally rejected because no safe installed parser is assumed.

## 3. Supported Master Types

The service supports Company, Unit, Drug, Supplier, Customer, Doctor, and Item. Purchase invoices, sales invoices, accounting documents, stock history, and other transactions are outside this phase.

## 4. File Preparation

Use one header row and one record per row. Remove merged headers, totals, subtotals, and transaction documents. Required names must be populated. Numeric fields should contain plain numeric values; boolean fields accept true/false, yes/no, or 1/0.

## 5. Column Mapping

Column matching is case-insensitive and whitespace-normalized, with aliases for common labels such as `Company Name`, `Supplier Name`, `Phone No.`, and `VAT/TIN`. The UI displays the detected mapping and permits manual source-to-target selection.

## 6. Validation

Validation happens before writing. It reports row, field, value, message, and severity. It checks required fields, numbers, integers, booleans, empty/malformed rows, duplicate keys, and Item references to existing Company, Unit, and Drug records.

## 7. Duplicate Handling

The database's existing unique name columns are the business keys. The default action is Skip duplicate. Update existing and Cancel import are explicit alternatives. Duplicate records within the same file are also detected.

## 8. Dependency Order

Import in this order when relationships are present: Company, Unit and Drug, Supplier/Customer/Doctor, then Item. Missing Item references are validation errors; referenced records are never silently created.

## 9. Preview

Selecting and inspecting a file performs no database writes. Preview shows columns, sample rows, total rows, valid rows, invalid rows, duplicate rows, unmapped columns, missing required values, and warnings.

## 10. Transaction Behavior

A confirmed import validates the complete input first, then uses one SQLite transaction. Supplier and Customer imports create their linked application ledger records inside the same transaction. Audit history is written only after the data operation succeeds.

## 11. Rollback

Any critical write error rolls back the entire import operation. No partial master data or audit record is retained. Cancelled duplicate mode and validation failures do not open a write transaction.

## 12. Templates

The Generate Template action creates a blank CSV or XLSX template with the supported target fields. Templates contain headers only; no example data is inserted into the database. XLSX templates require `openpyxl`.

## 13. Audit History

Recent imports are stored locally in the SQLite `import_history` table with timestamp, master type, filename, total rows, inserted, updated, skipped, and failed counts. Source-file contents are never stored.

## 14. Limitations

Only `.csv` and `.xlsx` are supported. `.xls` is not parsed. Ingredients are represented as comma- or semicolon-separated existing Drug names without power values. There is no multi-file orchestration wizard yet; dependency order is user-controlled.

## 15. Security

The feature accesses only the SQLite path resolved by `database.connection.get_db_path()`. It does not connect to or modify Pharma-WINNER/MySQL data. Users should review previews and protect source files and database backups as business data.

## 16. Testing and Future Enhancements

`test_import_service.py` contains 62 isolated tests covering CSV, XLSX, inspection, mapping, validation, all seven masters, dependencies, duplicates, rollback, templates, audit history, and persistence. Future work may add richer multi-sheet workflows, `.xls` support when a trusted parser is available, ingredient power mapping, progress reporting for very large files, and an audit-history viewer.
