# Phase 6D-2: Desktop Acceptance Test — Results & Bugs

## Summary of Results

| Metric | Count |
|---|---|
| Total Test Cases | 67 |
| Passed (Programmatic) | 8 |
| Failed | 0 |
| Blocked (Environment) | 59 |
| Not Tested | 0 |

---

## Detailed Blocked Constraints
Because the Acceptance Test requires a real Windows desktop environment to manually run the PySide6 UI, perform data entry, generate PDFs, and test printing, these operations cannot be executed headlessly by the testing agent. 

**Blocked Categories:**
- Functional UI failures (BLOCKED)
- UI failures (BLOCKED)
- Printing failures (BLOCKED)

**Programmatic Passes:**
- Permission policies (Tested via Python assertions / code review)
- Database schema safety (Tested in previous phases)
- Financial Year baseline setup

---

## Environment and Setup

- **Pre-acceptance Backup Path:** `backups/pharmacy_pre_acceptance_backup_20260917_150050.db`
- **Pre-acceptance DB Hash:** `e0270a1b528c651a9472523554e8c84cb30961592fb19cd8a7c391f076839352`
- **Acceptance Dataset Used:** N/A (Blocked)
- **DB Restored After Testing:** N/A (No tests executed that mutated the DB, DB remains in pristine pre-acceptance state).

---

## Bug Record

*(No bugs recorded during this automated check. Await manual QA execution on a live desktop.)*

| ID | Feature | Steps to reproduce | Expected | Actual | Severity | Screenshot/file evidence | Recommended fix |
|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — |

