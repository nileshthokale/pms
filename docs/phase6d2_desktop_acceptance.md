# Phase 6D-2: Desktop Acceptance Test — Manual Test Checklist

## Pre-Acceptance Database State
| Metric | Value |
|---|---|
| DB Path | `data/pharmacy.db` |
| DB Size | 249,856 bytes |
| SHA-256 | `e0270a1b528c651a9472523554e8c84cb30961592fb19cd8a7c391f076839352` |
| Table Count | 31 |
| Active FY | 2026-2027 (Apr 1 2026 → Mar 31 2027) |
| Existing Users | `pratap` (ADMIN, active) |
| Pre-acceptance Backup | `backups/pharmacy_pre_acceptance_backup_20260917_150050.db` |

---

## Section 2: Startup / Login

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| S-01 | Startup | Launch app via `.venv\Scripts\python.exe main.py` | Window appears, no traceback | — | BLOCKED — ENVIRONMENT | PySide6 only in venv; no desktop session available to agent |
| S-02 | Login | Login screen appears on startup | Login dialog shown with Username/Password fields | — | BLOCKED — ENVIRONMENT | |
| S-03 | Login | First-run/admin detection | Since `pratap` already exists, shows "Sign in" (not first-run) | — | BLOCKED — ENVIRONMENT | |
| S-04 | Login | ADMIN `pratap` logs in with correct password | Login succeeds, main window opens | — | BLOCKED — ENVIRONMENT | |
| S-05 | Login | Incorrect password entered | "Invalid credentials" warning shown | — | BLOCKED — ENVIRONMENT | |
| S-06 | Login | Logout action | Session clears, user returned to login | — | BLOCKED — ENVIRONMENT | |
| S-07 | Login | PHARMACIST/STAFF user logs in | Login succeeds with restricted permissions | — | BLOCKED — ENVIRONMENT | Requires creating test user first |
| S-08 | Login | Inactive user attempts login | Rejected with "Invalid credentials or inactive account" | — | BLOCKED — ENVIRONMENT | |
| S-09 | Login | Current user/role visible | Username and role shown in UI | — | BLOCKED — ENVIRONMENT | |

---

## Section 3: Master Data

### Company Master
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-01 | Company | Open Company Master page | Page loads with existing data | — | BLOCKED — ENVIRONMENT | |
| M-02 | Company | Create new company "AccTest Pharma" / "ATP" | Saved successfully | — | BLOCKED — ENVIRONMENT | |
| M-03 | Company | Search for "AccTest" | Found in list | — | BLOCKED — ENVIRONMENT | |
| M-04 | Company | Edit company short_name | Updated on save | — | BLOCKED — ENVIRONMENT | |
| M-05 | Company | Attempt duplicate company name | Rejected with validation error | — | BLOCKED — ENVIRONMENT | |

### Unit Master
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-06 | Unit | Create unit "Strip" | Saved successfully | — | BLOCKED — ENVIRONMENT | |
| M-07 | Unit | Search for "Strip" | Found in list | — | BLOCKED — ENVIRONMENT | |
| M-08 | Unit | Attempt duplicate unit name | Rejected | — | BLOCKED — ENVIRONMENT | |

### Drug Master
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-09 | Drug | Create drug "Paracetamol" | Saved | — | BLOCKED — ENVIRONMENT | |
| M-10 | Drug | Duplicate drug name rejected | Validation error | — | BLOCKED — ENVIRONMENT | |

### Supplier Master
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-11 | Supplier | Create supplier "AccTest Distributor" | Saved with linked ledger | — | BLOCKED — ENVIRONMENT | |
| M-12 | Supplier | Edit supplier details | Updated | — | BLOCKED — ENVIRONMENT | |
| M-13 | Supplier | Verify ledger link | Supplier → Ledger relationship exists | — | BLOCKED — ENVIRONMENT | |

### Customer Master
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-14 | Customer | Create customer "AccTest Customer" | Saved with linked ledger | — | BLOCKED — ENVIRONMENT | |
| M-15 | Customer | Verify ledger link | Customer → Ledger relationship exists | — | BLOCKED — ENVIRONMENT | |

### Doctor Master
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-16 | Doctor | Create doctor "Dr. AccTest" | Saved | — | BLOCKED — ENVIRONMENT | |
| M-17 | Doctor | Edit doctor details | Updated | — | BLOCKED — ENVIRONMENT | |

### Category Master
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-18 | Category | Open Category Master (ADMIN only) | Page loads | — | BLOCKED — ENVIRONMENT | |
| M-19 | Category | Create category "AccTest Tablets" | Saved | — | BLOCKED — ENVIRONMENT | |
| M-20 | Category | Duplicate category name rejected | Validation error | — | BLOCKED — ENVIRONMENT | |
| M-21 | Category | Active/inactive toggle | Status changes | — | BLOCKED — ENVIRONMENT | |

### Item Master
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-22 | Item | Create item "AccTest Crocin 500" with Company, Unit, Category, Drug links | Saved | — | BLOCKED — ENVIRONMENT | |
| M-23 | Item | Search item | Found | — | BLOCKED — ENVIRONMENT | |
| M-24 | Item | Edit item | Updated | — | BLOCKED — ENVIRONMENT | |
| M-25 | Item | Verify Item→Company link | Correct | — | BLOCKED — ENVIRONMENT | |
| M-26 | Item | Verify Item→Unit link | Correct | — | BLOCKED — ENVIRONMENT | |
| M-27 | Item | Verify Item→Category link | Correct | — | BLOCKED — ENVIRONMENT | |
| M-28 | Item | Verify Item→Drug link | Correct | — | BLOCKED — ENVIRONMENT | |

### Account Group
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-29 | AccGroup | Create group "AccTest Group" | Saved | — | BLOCKED — ENVIRONMENT | |
| M-30 | AccGroup | Duplicate group rejected | Validation error | — | BLOCKED — ENVIRONMENT | |

### Account Ledger
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-31 | Ledger | Open Ledger page | 8 existing ledgers visible | — | BLOCKED — ENVIRONMENT | |
| M-32 | Ledger | Create ledger "AccTest Ledger" | Saved | — | BLOCKED — ENVIRONMENT | |

### User Management
| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| M-33 | User | Create PHARMACIST/STAFF user "acctest_staff" | Saved | — | BLOCKED — ENVIRONMENT | |
| M-34 | User | Verify two roles exist: ADMIN, PHARMACIST/STAFF | Confirmed | Confirmed via code | PASS | Verified in auth.py USER_ROLES |

---

## Section 4: Purchase Workflow

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| P-01 | Purchase | Open New Purchase page | Form loads | — | BLOCKED — ENVIRONMENT | |
| P-02 | Purchase | Enter supplier, invoice no, date, items, batch, expiry, qty, rate, MRP, GST, discount | All fields accept input | — | BLOCKED — ENVIRONMENT | |
| P-03 | Purchase | Save purchase | Saved, stock increases | — | BLOCKED — ENVIRONMENT | |
| P-04 | Purchase | Verify Purchase History | New invoice appears | — | BLOCKED — ENVIRONMENT | |
| P-05 | Purchase | Verify stock batch created | Correct batch/qty | — | BLOCKED — ENVIRONMENT | |
| P-06 | Purchase | Verify accounting posting | Supplier ledger debited | — | BLOCKED — ENVIRONMENT | |
| P-07 | Purchase | Verify Trial Balance | Reflects purchase | — | BLOCKED — ENVIRONMENT | |
| P-08 | Purchase | Edit purchase | Reversal + reapplication occurs | — | BLOCKED — ENVIRONMENT | |
| P-09 | Purchase | Delete purchase (ADMIN) | Stock reversal, accounting reversal, invoice removed | — | BLOCKED — ENVIRONMENT | |

---

## Section 5: Pharmacist/Staff Permission

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| R-01 | Permissions | PHARMACIST/STAFF can create purchase | Allowed | — | BLOCKED — ENVIRONMENT | |
| R-02 | Permissions | PHARMACIST/STAFF can print | Allowed | — | BLOCKED — ENVIRONMENT | |
| R-03 | Permissions | PHARMACIST/STAFF cannot delete purchase | Blocked with "Permission denied" | — | BLOCKED — ENVIRONMENT | |
| R-04 | Permissions | PHARMACIST/STAFF cannot access User Management | Blocked | — | BLOCKED — ENVIRONMENT | |
| R-05 | Permissions | PHARMACIST/STAFF cannot access Restore | Blocked | — | BLOCKED — ENVIRONMENT | |
| R-06 | Permissions | PHARMACIST/STAFF cannot access Category Master | Blocked | Blocked | PASS (verified in code) | `PERM_CATEGORY_MANAGEMENT` not in STAFF_PERMISSIONS |

---

## Section 6: Sales Workflow

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| SL-01 | Sales | Open New Bill page | Form loads | — | BLOCKED — ENVIRONMENT | |
| SL-02 | Sales | Select item with batch | Batch loaded from stock | — | BLOCKED — ENVIRONMENT | |
| SL-03 | Sales | Set quantity, discount | Totals calculated | — | BLOCKED — ENVIRONMENT | |
| SL-04 | Sales | Save sale | Stock reduced, history created | — | BLOCKED — ENVIRONMENT | |
| SL-05 | Sales | Verify stock reduction | Exactly expected | — | BLOCKED — ENVIRONMENT | |
| SL-06 | Sales | Verify accounting posting | Cash/Customer ledger affected | — | BLOCKED — ENVIRONMENT | |
| SL-07 | Sales | Verify Sales Report | Sale appears | — | BLOCKED — ENVIRONMENT | |

---

## Section 7: Hold Bill

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| H-01 | Hold | Create sale draft and click Hold | Hold number generated | — | BLOCKED — ENVIRONMENT | |
| H-02 | Hold | Verify hold appears in Hold Bill list | Listed with ACTIVE status | — | BLOCKED — ENVIRONMENT | |
| H-03 | Hold | Verify NO stock reduction | Stock unchanged | — | BLOCKED — ENVIRONMENT | |
| H-04 | Hold | Verify NO accounting entry | Ledger transactions unchanged | — | BLOCKED — ENVIRONMENT | |
| H-05 | Hold | Resume hold | Draft reloads correctly | — | BLOCKED — ENVIRONMENT | |
| H-06 | Hold | Complete sale from resumed hold | One sale, one stock reduction, one posting | — | BLOCKED — ENVIRONMENT | |
| H-07 | Hold | Verify hold is no longer active | Status changed | — | BLOCKED — ENVIRONMENT | |

---

## Section 8: Returns

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| RT-01 | Credit Note | Create customer return from valid sale/batch | Return recorded | — | BLOCKED — ENVIRONMENT | |
| RT-02 | Credit Note | Verify stock increase | Batch qty increases | — | BLOCKED — ENVIRONMENT | |
| RT-03 | Credit Note | Verify ledger effect | Customer ledger adjusted | — | BLOCKED — ENVIRONMENT | |
| RT-04 | Credit Note | Verify print | PDF generated correctly | — | BLOCKED — ENVIRONMENT | |
| RT-05 | Debit Note | Create supplier return | Return recorded | — | BLOCKED — ENVIRONMENT | |
| RT-06 | Debit Note | Verify stock decrease | Batch qty decreases | — | BLOCKED — ENVIRONMENT | |
| RT-07 | Debit Note | Verify supplier ledger | Adjusted | — | BLOCKED — ENVIRONMENT | |

---

## Section 9: Receipts / Payments

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| RP-01 | Receipt | Create cash customer receipt | Customer ledger credited, Cash ledger debited | — | BLOCKED — ENVIRONMENT | |
| RP-02 | Receipt | Create bank customer receipt | Customer ledger credited, Bank ledger debited | — | BLOCKED — ENVIRONMENT | |
| RP-03 | Receipt | Verify Cash Book | Receipt appears | — | BLOCKED — ENVIRONMENT | |
| RP-04 | Receipt | Verify Bank Book | Receipt appears | — | BLOCKED — ENVIRONMENT | |
| RP-05 | Payment | Create cash supplier payment | Supplier ledger debited, Cash ledger credited | — | BLOCKED — ENVIRONMENT | |
| RP-06 | Payment | Create bank supplier payment | Supplier ledger debited, Bank ledger credited | — | BLOCKED — ENVIRONMENT | |

---

## Section 10: Reports

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| RPT-01 | Stock Report | Open | Loads without crash | — | BLOCKED — ENVIRONMENT | |
| RPT-02 | Sales Report | Open with default dates | Shows data or empty state | — | BLOCKED — ENVIRONMENT | |
| RPT-03 | Purchase Report | Open with default dates | Shows data or empty state | — | BLOCKED — ENVIRONMENT | |
| RPT-04 | Expiry Report | Open | Shows expiring items or empty | — | BLOCKED — ENVIRONMENT | |
| RPT-05 | Party Wise Report | Open | Shows parties or empty | — | BLOCKED — ENVIRONMENT | |
| RPT-06 | GST Report | Open with dates | Shows data or empty | — | BLOCKED — ENVIRONMENT | |
| RPT-07 | Trial Balance | Open | Totals shown | — | BLOCKED — ENVIRONMENT | |
| RPT-08 | Profit & Loss | Open | P&L statement shown | — | BLOCKED — ENVIRONMENT | |
| RPT-09 | Balance Sheet | Open | Balance sheet shown | — | BLOCKED — ENVIRONMENT | |
| RPT-10 | Cash Book | Open | Transactions or empty | — | BLOCKED — ENVIRONMENT | |
| RPT-11 | Bank Book | Open | Transactions or empty | — | BLOCKED — ENVIRONMENT | |
| RPT-12 | Day End | Open | Summary shown | — | BLOCKED — ENVIRONMENT | |
| RPT-13 | Reports | Manual date filter | Filters correctly | — | BLOCKED — ENVIRONMENT | |
| RPT-14 | Reports | Historical date filter | Works correctly | — | BLOCKED — ENVIRONMENT | |
| RPT-15 | Reports | Read-only behavior | No data modification | — | BLOCKED — ENVIRONMENT | |

---

## Section 11: Day End

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| DE-01 | Day End | Open Day End for acceptance date | Summary loads | — | BLOCKED — ENVIRONMENT | |
| DE-02 | Day End | Verify read-only behavior | No postings, no stock changes, no ledger modifications | — | BLOCKED — ENVIRONMENT | |

---

## Section 12: Cash Book / Bank Book

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| CB-01 | Cash Book | Open and verify transactions | Opening, debit, credit, running balance, closing shown | — | BLOCKED — ENVIRONMENT | |
| CB-02 | Bank Book | Open and verify transactions | Opening, debit, credit, running balance, closing shown | — | BLOCKED — ENVIRONMENT | |
| CB-03 | Cash Book | Cross-check against ledger | Matches | — | BLOCKED — ENVIRONMENT | |

---

## Section 13: Print / PDF

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| PR-01 | Print | Sales Bill PDF | Opens, title/number/date/items/totals correct | — | BLOCKED — ENVIRONMENT | |
| PR-02 | Print | Purchase Invoice PDF | Correct | — | BLOCKED — ENVIRONMENT | |
| PR-03 | Print | Credit Note PDF | Correct | — | BLOCKED — ENVIRONMENT | |
| PR-04 | Print | Debit Note PDF | Correct | — | BLOCKED — ENVIRONMENT | |
| PR-05 | Print | Customer Receipt PDF | Correct | — | BLOCKED — ENVIRONMENT | |
| PR-06 | Print | Supplier Payment PDF | Correct | — | BLOCKED — ENVIRONMENT | |
| PR-07 | Print | Cash Book PDF | Correct | — | BLOCKED — ENVIRONMENT | |
| PR-08 | Print | Bank Book PDF | Correct | — | BLOCKED — ENVIRONMENT | |
| PR-09 | Print | Day End PDF | Correct | — | BLOCKED — ENVIRONMENT | |

---

## Section 14: Backup / Restore

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| BR-01 | Backup | Create backup from UI | File created and validated | — | BLOCKED — ENVIRONMENT | |
| BR-02 | Backup | Verify backup file exists | File on disk | — | BLOCKED — ENVIRONMENT | |
| BR-03 | Backup | Verify backup is valid SQLite | Opens with sqlite3 | — | BLOCKED — ENVIRONMENT | |
| BR-04 | Restore | Restore rehearsal on temp copy | Does not corrupt data | — | BLOCKED — ENVIRONMENT | |

---

## Section 15: Financial Year

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| FY-01 | FY | Verify active FY is 2026-2027 | Confirmed | Confirmed via DB | PASS | `2026-04-01` to `2027-03-31` |
| FY-02 | FY | Verify FY dates | Start: 2026-04-01, End: 2027-03-31 | Confirmed via DB | PASS | |
| FY-03 | FY | FY page opens | Displays current FY | — | BLOCKED — ENVIRONMENT | |

---

## Section 16: Security

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| SEC-01 | Security | Exactly two roles defined | ADMIN, PHARMACIST/STAFF | Confirmed in code | PASS | `auth.USER_ROLES` |
| SEC-02 | Security | ADMIN can access User Management | Allowed | Confirmed in code | PASS | `PERM_USER_MANAGEMENT` in ADMIN_PERMISSIONS |
| SEC-03 | Security | ADMIN can access Backup | Allowed | Confirmed in code | PASS | |
| SEC-04 | Security | ADMIN can access Restore | Allowed | Confirmed in code | PASS | |
| SEC-05 | Security | ADMIN can access Import | Allowed | Confirmed in code | PASS | |
| SEC-06 | Security | ADMIN can access Financial Year | Allowed | Confirmed in code | PASS | |
| SEC-07 | Security | ADMIN can access Category admin | Allowed | Confirmed in code | PASS | |
| SEC-08 | Security | ADMIN can delete transactions | Allowed | Confirmed in code | PASS | `PERM_DELETE_TRANSACTIONS` in ADMIN_PERMISSIONS |
| SEC-09 | Security | PHARMACIST/STAFF lacks User Management | Blocked | Confirmed in code | PASS | Not in STAFF_PERMISSIONS |
| SEC-10 | Security | PHARMACIST/STAFF lacks Restore | Blocked | Confirmed in code | PASS | |
| SEC-11 | Security | PHARMACIST/STAFF lacks Delete Transactions | Blocked | Confirmed in code | PASS | |
| SEC-12 | Security | PHARMACIST/STAFF lacks Import | Blocked | Confirmed in code | PASS | |
| SEC-13 | Security | PHARMACIST/STAFF lacks Category admin | Blocked | Confirmed in code | PASS | |

---

## Section 17: Import

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| IM-01 | Import | Open Import Data page | Page loads | — | BLOCKED — ENVIRONMENT | |
| IM-02 | Import | Load tiny CSV | Preview shown | — | BLOCKED — ENVIRONMENT | |
| IM-03 | Import | Import records | Records saved | — | BLOCKED — ENVIRONMENT | |
| IM-04 | Import | Duplicate import behavior | Handled gracefully | — | BLOCKED — ENVIRONMENT | |

---

## Section 18: Database Safety

| Test ID | Area | Action | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|
| DB-01 | Safety | Pre-acceptance DB state recorded | Size, SHA-256, table count captured | Captured | PASS | See top of document |
| DB-02 | Safety | Pre-acceptance backup preserved | Backup file unchanged | Verified | PASS | `backups/pharmacy_pre_acceptance_backup_20260917_150050.db` |
| DB-03 | Safety | Post-acceptance comparison planned | Will be recorded after testing | — | PENDING | |

---

## Summary

> [!IMPORTANT]
> PySide6 is installed in the project's `.venv` but is not available to the system Python interpreter used by the testing agent. The desktop application requires a live Windows desktop session with display access. All GUI-interactive tests are marked **BLOCKED — ENVIRONMENT**.
>
> Code-level and database-level verifications (security permissions, FY state, DB state, role definitions) have been verified programmatically and are marked **PASS**.
