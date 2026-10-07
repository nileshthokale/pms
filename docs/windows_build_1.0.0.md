# Windows Build 1.0.0 — First EXE Testing Release

Packaging-only release. No accounting rules, business logic, UI behaviour,
database data, or application features were changed to produce this build,
except the minimum required to make packaging safe:

- `database/connection.py`: a frozen (packaged) EXE uses the per-user
  `pharmacy.db` at `%LOCALAPPDATA%\PharmacyManagementSystem\` instead of the
  source-tree `data/pharmacy.db`. Development runs and the test suite
  (`PHARMACY_DB`) are unaffected.
- `ui/theme.py`: a frozen EXE stores `theme.json` next to that per-user
  database instead of beside the EXE/source tree.
- `version.py` (new) + window/brand titles: visible `v1.0.0` identifier.
  Nothing else in the UI was redesigned.

## 1. Prerequisites (development machine)

- Windows 10/11, 64-bit.
- Python 3.13.x (this release was built with 3.13.14).
- The project virtualenv with dependencies installed:

```text
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install PyInstaller
```

Versions used for 1.0.0: Python 3.13.14, PyInstaller 6.22.3, PySide6 6.11.2,
openpyxl 3.1.5.

## 2. Pre-build verification (mandatory)

From the project root, with the virtualenv active:

```text
.venv\Scripts\python.exe run_tests.py
```

Expected for 1.0.0: **2,757 tests, OK — 0 failures, 0 errors, 0 skips**
(about 9 minutes on the reference machine). Do not build if the suite is
not green, and never disable/skip tests to make it green.

## 3. Build command

From the project root:

```text
.venv\Scripts\python.exe -m PyInstaller build\windows\pharmacy_management.spec --noconfirm
```

- Spec file: `build/windows/pharmacy_management.spec` (the single source of
  truth for the build; `--onedir`, never `--onefile` for this release).
- Entry point: `main.py`.
- Mode: windowed (`console=False`); no application icon exists in the repo
  yet, so the default executable icon is used.

## 4. Output location

```text
dist\
    PharmacyManagement\
        PharmacyManagement.exe   <- the exact file to test / distribute
        _internal\               <- Qt 6 DLLs, plugins, collected packages
```

Release folder size for 1.0.0: ~113 MB, 169 files.
What is deliberately NOT inside: no `*.db`, no `theme.json`, no
`last_backup.json`, no `.venv`, no `tests`/`test_*`, no `.git`, no source
database, no screenshots, no caches.

## 5. Runtime database location (tester machine)

First launch creates everything automatically:

```text
%LOCALAPPDATA%\PharmacyManagementSystem\
    pharmacy.db    <- live database (schema + default FY 2026-2027 created)
    theme.json     <- day/night preference
    <backups>      <- safety/user backups created next to the database
```

Because the database lives per-user outside the install folder, the EXE
works when installed under `Program Files` and two Windows users never
share (or clash over) one database file.

## 6. How the test database is initialised

No database is shipped. On first launch the app creates an empty schema
and the login screen shows **first-run ADMIN setup**: the tester creates
their own ADMIN username/password. There are no pre-seeded users and no
production passwords anywhere in the release. After that:

1. Sign in with the new ADMIN account.
2. Open Master → Account Roles once so system ledgers (CASH/BANK/PURCHASE,
   …) are initialised — required before purchase/sales post.
3. Add a Company, Unit, Supplier, Customer, Item, then Purchase → Sale.

No fake accounting/business data is bundled; the tester enters real
trial data themselves.

## 7. How to give the EXE to a tester

1. Zip the whole `dist\PharmacyManagement` folder (the EXE alone will not
   run — it needs its `_internal` folder next to it).
2. The tester unzips to any folder (e.g. Desktop) and double-clicks
   `PharmacyManagement.exe`. No Python installation needed.
3. Tester creates their ADMIN account on first launch (see §6).

## 8. How to collect bug reports

Ask the tester for ALL of the following:

1. The window title (shows the version, e.g. `… v1.0.0`).
2. What they clicked / typed, step by step, and what they expected.
3. The exact error message text (screenshot if it is a popup).
4. Their database info from Master → Backup & Restore (location, size,
   tables) — and, if willing, a **backup file** created with Create Backup
   (it contains their test data; handle it as business data).
5. Any `pharmacy_pre_restore_*.db` safety backups if the issue involves
   restore.

## 9. Future versions — replacing/updating the EXE

1. Re-run the full suite (§2), rebuild with the same command (§3).
2. Bump `version.py` (`APP_VERSION`) so the window title shows the new
   version.
3. To update a tester: replace ONLY the `PharmacyManagement` application
   folder contents (EXE + `_internal`).

> **WARNING — never delete, replace, or "refresh" the tester's database.**
> `%LOCALAPPDATA%\PharmacyManagementSystem\pharmacy.db` (and its backups)
> are the tester's data. Updates must never touch that folder. Schema
> changes must go through migration-safe `init_database()` additions, and
> must be verified against a copy of real data — never by resetting the
> tester's file.

## 10. Verification performed for 1.0.0

- Full suite: Ran 2,757 tests — OK (0 failures, 0 errors, 0 skips).
- Static: Qt platform plugins (`qwindows.dll`, `qoffscreen.dll`),
  `Qt6PrintSupport`/`QtPrintSupport.pyd`, `sqlite3.dll` present; no
  `*.db`/`theme.json`/`last_backup.json`/`*.sql` inside `dist`.
- Live EXE (`dist\PharmacyManagement\PharmacyManagement.exe`) launched
  offscreen with an isolated `%LOCALAPPDATA%`: process reached the login
  screen (no missing DLL/module/plugin) and created a 28-table,
  integrity-ok `pharmacy.db` with active FY 2026-2027 in the per-user
  folder.
- Clean-room functional smoke (40 checks, isolated throwaway DB): login,
  roles, inactive-user rejection, master CRUD, purchase → stock +10,
  sale → stock −2, record read-back, all major modules constructed,
  sales/purchase/GST/stock reports, A6 PDF (media box 297.64 × 419.53 pt
  = 105 × 148 mm portrait), live printer detection
  (`Canon LBP2900`, `Microsoft Print to PDF`, `OneNote (Desktop)` —
  dynamically listed, nothing hard-coded), backup, restore into a TEST
  destination, persistence after reopen.
- Production `data/pharmacy.db` byte-identical before and after
  (SHA-256 `96a30744…f51d`, 42,618,880 bytes).
- Physical printing was NOT claimed: paper printing needs a real printer
  on the tester's machine; only PDF generation + printer detection were
  verified here.
