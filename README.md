# Pharmacy Management System

A Windows desktop application for pharmacy billing, inventory, purchasing, accounting, and reporting. The app is built with Python, PySide6/Qt, and SQLite. The current application version identifier is **1.0.0**; the release notes describe it as the first Windows executable testing release.

## Features

### Pharmacy operations

- **Medicine and master data:** Items, companies, units, categories, drug/ingredient records, suppliers, customers, doctors, and account groups.
- **Sales:** Counter sales, patient and doctor details, batch-aware stock selection, held bills, bill history, bill-number-wise patient history, duplicate bill tools, and customer returns through credit notes.
- **Purchasing:** Purchase invoices and history, supplier returns through debit notes, supplier payments, and stock adjustments.
- **Inventory:** Batch stock, stock views and reports, quantity adjustments, and expiry reporting.
- **Accounting:** Customer receipts, supplier payments, journal entries, account ledgers and roles, cash book, bank book, day-end reporting, trial balance, profit and loss, and balance sheet.
- **Financial years:** Create and switch named financial-year date ranges. New transactions are checked against the active year; reports can use date filters. Year-end closing and automatic balance carry-forward are not provided.
- **Reports:** Sales and purchase summaries, stock and expiry reports, party-wise and doctor-wise reports, ledger reports, GST reports, profit calculations, and H1/NRX sales and purchase schedules.
- **Data import:** Preview, map, validate, and import Company, Unit, Drug, Supplier, Customer, Doctor, and Item master records from CSV or XLSX files. `.xls` files are not supported.
- **Printing and PDF:** Transaction documents include sales bills, purchase invoices, credit/debit notes, customer receipts, and supplier payments. Pharmacy sales bills use an A6 portrait layout (105 × 148 mm).
- **Backup and restore:** Create and validate SQLite backups; restore validates the selected backup and creates a safety backup of the current database first.
- **Authentication:** First-run ADMIN setup, sign-in, user activation, login audit events, and two application roles: `ADMIN` and `PHARMACIST/STAFF`. Administrative actions such as user and financial-year management, imports, backup/restore, and transaction edits/deletes are restricted by permissions.
- **Appearance:** Shared PySide6 interface with light and night themes.

GST reporting uses values recorded in the application. Sales invoice records do not currently store item-level GST amounts, so sales bills do not invent or print those amounts.

## Recent performance update

- The dashboard registers all navigation routes up front, then constructs each page when it is first opened and reuses it for later visits.
- Opening Sales Report no longer generates a full report automatically. Report results are generated after a user action.
- Item Master table refresh batches row population and restores the current sorting and column sizing afterward.
- The measured implementation changes, clone-only regression checks, and before/after timings are recorded in [`docs/performance_audit.md`](docs/performance_audit.md).

## Technology and architecture

- **Language:** Python (the documented Windows release build uses Python 3.13.x)
- **Desktop UI:** PySide6 / Qt
- **Database:** SQLite, with write-ahead logging and foreign-key enforcement
- **Spreadsheet support:** openpyxl for XLSX import/template workflows
- **Structure:** `screens/` contains the application pages; `database/` contains SQLite access, business services, and reporting queries; `ui/` contains navigation, shared components, and theming.

## Run from source

Use Windows PowerShell from the repository root. Python 3.13.x is the version used for the documented Windows release build.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

On first launch, the application creates its database schema and prompts you to create the initial ADMIN account. There are no default usernames or passwords. Use a password of at least eight characters.

The pinned runtime dependencies are listed in [`requirements.txt`](requirements.txt): PySide6 and openpyxl.

## Data, backups, and configuration

- A source checkout stores its database at `data/pharmacy.db` and its theme preference at `data/theme.json`.
- A packaged Windows executable stores its database and theme preference under `%LOCALAPPDATA%\PharmacyManagementSystem\`, keeping business data outside the application install folder.
- SQLite WAL sidecar files may appear while the database is in use. Do not delete the database or its WAL files while the application is running.
- Use **Master → Backup & Restore** to create or restore backups. Treat backup files as sensitive business data.
- Development and test setups can select a database with the `PHARMACY_DB` or `PHARMACY_DB_PATH` environment variable. The application does not load `.env` files.

## Automated checks

Run the repository test suite with:

```powershell
python run_tests.py
```

The runner discovers the top-level `test_*.py` modules and runs the suite against a temporary SQLite snapshot, rather than writing test changes to the source database. Individual tests are also available as top-level `test_*.py` files.

## Windows executable build

The repository includes a PyInstaller spec at [`build/windows/pharmacy_management.spec`](build/windows/pharmacy_management.spec) and a release guide at [`docs/windows_build_1.0.0.md`](docs/windows_build_1.0.0.md). The guide documents prerequisites, the build command, output folder, first-run account setup, and the persistent per-user data location. Package the complete output folder, including its `_internal` directory; the executable is not a standalone file.

## Repository map

| Path | Contents |
| --- | --- |
| `main.py` | Application startup, database initialization, login, and main window |
| `screens/` | Sales, purchasing, masters, accounting, inventory, reports, and administration pages |
| `database/` | SQLite schema, DAOs, accounting posting, authentication, import, backup, printing, and reports |
| `ui/` | Main window, navigation, shared widgets, theme, and input behavior |
| `docs/` | Feature specifications, migration notes, audits, and Windows release documentation |
| `test_*.py` | Top-level unit and integration test modules |
| `tools/`, `scripts/` | Data migration, reconciliation, audit, and maintenance utilities |
| `build/windows/` | Windows PyInstaller build specification |

Useful feature guides include [`docs/financial_year.md`](docs/financial_year.md), [`docs/import_data.md`](docs/import_data.md), [`docs/backup_restore.md`](docs/backup_restore.md), [`docs/a6_pharmacy_printing.md`](docs/a6_pharmacy_printing.md), and [`docs/accounting_posting_specification.md`](docs/accounting_posting_specification.md).

## License

No license file is included in this repository, so redistribution terms are not specified here.
