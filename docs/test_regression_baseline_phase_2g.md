# Test Regression Baseline — Phase 2G

**Date:** 2026-09-15
**Scope:** Full regression-suite diagnosis and cleanup after Credit Note posting (Phase 2G). No accounting behavior, posting rules, transaction calculations, or schema were changed.

---

## 1. Test Command Used

```
python run_tests.py
```

`run_tests.py` (new, test infrastructure only) loads every top-level `test_*.py` module explicitly. It does **not** recurse into application packages.

Why not `python -m unittest discover -s . -p "test_*.py"`: `discover` walks and imports every package. In an environment without PySide6, importing the `screens` and `ui` packages fails and discover reports 2 environmental loader "errors" (`screens`, `ui`) that are not test failures — polluting the result. The explicit runner avoids this in every environment and is the canonical command.

## 2. Environment

| Item | Value |
|---|---|
| OS | Windows (PowerShell 5.1) |
| Python | 3.13 |
| Project path | `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System` |
| PySide6 | **NOT installed in the test shell used for this baseline** (GUI-dependent tests skip with an explicit dependency reason). The real development environment has PySide6 installed (the application runs there). |
| Database | SQLite (WAL mode) |

## 3–7. Final Suite Result (two consecutive clean runs, identical)

| Metric | Count |
|---|---|
| **Total tests** | **459** |
| **Passed** | **456** |
| **Failed** | **0** |
| **Errors** | **0** |
| **Skipped** | **3** (GUI screen tests — PySide6 absent in this shell; skip reason: `PySide6 not available (No module named 'PySide6')`) |

Reproducibility: `Ran 459 tests ... OK (skipped=3)` on two consecutive full runs. The user's real application database `data/pharmacy.db` was SHA-256-verified **byte-identical before and after both full runs**.

Module-level spot checks: `test_credit_note_posting` — 36/36 pass (Credit Note posting: row creation, duplicate prevention, reversal, edit/repost, delete, customer ledger mapping, SALES_RETURN role, stock restoration — all green, implementation untouched).

## 8. Failure Classification (everything found during diagnosis)

| Test / Symptom | Classification | Root Cause | Correct Fix |
|---|---|---|---|
| `ERROR: screens`, `ERROR: ui` under `unittest discover` (2 loader errors) | **C — Environment/dependency** | `discover` imports every package; `screens`/`ui` import PySide6, absent in the test shell | Canonical `run_tests.py` runner loads only top-level test modules. Not an application defect. |
| `test_account_roles` tests 17–19 (GUI screen tests) skip | **C — Environment/dependency** | PySide6 not installed in the test shell | Already skip with an explicit dependency reason. Must be executed separately in the development environment (see §11). Not counted as passed. |
| `setUpClass` `PermissionError: [WinError 32]` in `test_credit_note_posting`, `test_purchase_posting`, `test_supplier_payment_posting` (3 errors — surfaced only after the DB-isolation fix) | **B — Broken test fixture** | `get_connection().execute(...)` in one test per module leaked an unclosed SQLite connection; on Windows the open handle blocked the next test class's `os.remove(cls._DB_PATH)` | Close the connection in `try/finally` in the 3 affected tests (fixture-only change; no assertions changed) |
| All DB tests silently sharing `data/pharmacy.db` (systemic, pre-existing) | **B — Broken test fixture** | Every test class set `os.environ["PHARMACY_DB"]` but `database/connection.py` never read it — the variable was dead. All per-test table wipes hit the **real application database** on every run. | `get_db_path()` added to `connection.py` (resolves per call). Tests now run against per-class throwaway `_test_*.db` files, exactly as they always claimed. Production never sets the variable → production path unchanged. |
| Historical contradictions in the Phase 2G report: `NameError: cnt`, `0 != 2`, `PostingError not raised` in `test_credit_note_posting` | **B/E — transient broken/outdated test file** | The file was captured mid-edit by a concurrent session (undefined variable, stale expectations); it was completed afterwards | Final file passes 36/36 as-is. No application defect; no fix needed beyond what the completing session already did. |

**No classification-A (real application regression) items were found. No accounting/posting/DAO behavior was changed.**

## 9. Changes Made (fixtures / test infrastructure only)

| File | Change |
|---|---|
| `database/connection.py` | Added `get_db_path()`: resolves the DB path per call, honoring `PHARMACY_DB` when set; `get_connection()` uses it (and creates its parent dir). `_DB_PATH` remains the production default. |
| `test_counter_sale_posting.py` | Top-level `_DB_PATH` import → `get_db_path()` for the persistence check |
| `test_accounting_posting.py`, `test_supplier_payment_posting.py`, `test_purchase_posting.py`, `test_credit_note_posting.py` | Local `from database.connection import _DB_PATH` → `get_db_path()` in the restart-persistence tests |
| `test_credit_note_posting.py`, `test_purchase_posting.py`, `test_supplier_payment_posting.py` | Fixed the connection leak: raw `get_connection().execute(...)` → open / query / `close()` in `try/finally` |
| `run_tests.py` (new) | Canonical test runner — loads top-level `test_*.py` only |

## 10. Why Each Change Is Safe

- **`get_db_path()`**: purely additive. Production code (`main.py`, screens, DAOs) never sets `PHARMACY_DB`, so `get_db_path()` always returns the original `data/pharmacy.db` — identical production behavior. The variable was already set by every test class; the change makes the existing, documented intent actually work instead of introducing a new mechanism. No UNIQUE constraints, schema, or data were touched.
- **`_DB_PATH` → `get_db_path()` in tests**: the affected checks open a fresh SQLite connection to read committed state. Using the call-time resolver points them at the same database the test class is actually using (previously they read the default DB — the checks were silently verifying the wrong file).
- **Connection-leak fix**: adds only `close()` in `try/finally`; the query and assertions are byte-identical. Prevents Windows file-lock failures between test classes.
- **`run_tests.py`**: test infrastructure; imports and runs the same test modules, just without walking application packages. No application code involved.

## 11. Remaining Environment Limitations

1. **PySide6 is not installed in the test shell** used for this baseline. The 3 GUI tests (`test_account_roles` tests 17–19) skip with an explicit dependency reason and are **not** counted as passed. They must be verified in the real development environment:
   ```
   python -m unittest test_account_roles -v
   ```
   With PySide6 present they execute for real (window construction, status table, refresh).
2. **OneDrive file locking**: the project lives inside a OneDrive-synced folder; transient `WinError 32` locks from the sync engine are possible in principle. The two consecutive clean runs show no current interference.
3. **Real DB content**: `data/pharmacy.db` currently contains only residue from the pre-fix era (test-named records: one "TestCustomer", one "TestSupplier", the 6 system-role ledgers; zero transactions). It was verified untouched during this baseline and is no longer written by tests. No business data existed to recover.

## 12. Verdict

> **FULL REGRESSION CLEAN**
>
> 459 tests — 456 passed, 0 failed, 0 errors, 3 skipped (GUI tests, dependency-skipped in this shell, to be executed in the PySide6 development environment). Reproduced on two consecutive runs with the real application database verified untouched. Credit Note posting: 36/36, implementation unchanged.
