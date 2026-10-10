# Final Desktop Acceptance Test

**Date:** 2026-10-05
**Tester:** Kilo CLI agent, driving the real application on the Windows desktop session
**Project:** Pharmacy Management System (`C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System`)
**Application under test:** `main.py`, PySide6 6.11.2, Qt platform `windows` (real rendering, not offscreen)

---

## 0. Verdict

# NOT READY — 5 exact blockers

1. **A6 output is not 105 × 148 mm.** Both the saved PDF and the physical print job emit a content-shrunk page (105 × 50.75 mm for a small bill, 105 × 91.7 mm for a multi-item bill) instead of a full A6 sheet. Fails the stated "105 × 148 mm Portrait" criterion.
2. **Physical printing on `Canon LBP2900` was not verified — no such printer exists on this machine.** No print job was created and no paper was observed. Not claimed as passing.
3. **Visual/appearance acceptance of the GUI was not performed.** This agent cannot view images, so screenshots were captured but never inspected. Only geometry-level layout checks were verified.
4. **The Sales Bill counter/bill number is truncated on screen.** The `CNo` field is fixed at 34 px but the rendered text needs 109 px (`2026-2027-Cash-0015`).
5. **Balance Sheet does not balance on the migrated data** — `Status: UNBALANCED (by 6,751,112.25)` with a blank *Total Equity*.

A sixth item is recorded as a FAIL against the literal checklist wording but is **not** an application defect: Bank Book shows no rows in the default financial year (see §12).

---

## 1. Environment actually available

The previous acceptance attempt (`docs/phase6d2_desktop_acceptance.md`) marked everything `BLOCKED — ENVIRONMENT`, noting *"no desktop session available to agent"*. That is no longer true:

| Capability | Status |
|---|---|
| Windows desktop session | Present — `console`, user `nilesh`, session 1, Active |
| Qt rendering | Real — `QApplication.platformName() == "windows"`; widgets render and `grab()` returns true pixels |
| Real key events | Real — `QTest.keyClick` / `keyClicks` delivered through the Qt event system |
| Installed printers | `Microsoft Print to PDF` (default), `OneNote (Desktop)` |
| `Canon LBP2900` | **NOT INSTALLED** — `Get-Printer`, `Win32_Printer` and `QPrinterInfo.availablePrinterNames()` all agree |
| Image inspection by this agent | **NOT AVAILABLE** — the model cannot read images, so captured screenshots were never viewed |

### Limitations that bound this report

- **No image input.** Screenshots exist (21 files, `docs/acceptance_screenshots/`) but were never visually inspected. Every layout verdict below comes from **geometry arithmetic** (widget rects, `QFontMetrics.horizontalAdvance`, parent-containment), not from looking at pixels.
- **No hardware printer.** Physical print is impossible here and is reported as `BLOCKED`, never as `PASS`.
- **No production credentials.** The clone contains `pratap` (ADMIN) and `pratap1` (PHARMACIST/STAFF) with PBKDF2-SHA256/240 000-iteration hashes. Passwords cannot be reversed, and none were supplied during this run. Successful login was therefore proven with acceptance accounts provisioned **on the clone only** (see §2).

---

## 2. Temporary clone — the only database written

| Item | Value |
|---|---|
| Production DB (never written) | `data/pharmacy.db` |
| **Temporary clone (all writes here)** | **`data/pharmacy_temp.db`** |
| Clone creation method | SQLite backup API (`sqlite3.Connection.backup`) — a consistent snapshot including any WAL frames |
| `PHARMACY_DB` | `data/pharmacy_temp.db` |
| Extra guard | `PHARMACY_TEST_PROTECTED_DB` = production, `PHARMACY_TEST_SAFE_DB` = clone, so `get_db_path()` silently rewrites any accidental reference to production back onto the clone |
| Harness pre-flight | Every step asserted the resolved DB is **not** production before running |

### Clone verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| `PRAGMA integrity_check` | `ok` | `ok` | **PASS** |
| `PRAGMA foreign_key_check` | 0 violations | 0 | **PASS** |
| Table count | equal | 33 = 33 | **PASS** |
| Major row counts preserved | all equal | 26/26 tables identical | **PASS** |

Preserved row counts (identical in production and clone):

`items 939` · `stock_batches 1962` · `sales_invoices 71811` · `sales_invoice_items 44245` · `purchase_invoices 5681` · `purchase_invoice_items 11829` · `account_ledgers 123` · `ledger_transactions 156748` · `customers 29` · `suppliers 85` · `companies 1218` · `units 16` · `doctors 7` · `financial_years 12` · `item_ingredients 403` · `drugs 147` · `categories 0` · `app_users 2` · `auth_audit_log 100`

> The clone's own SHA-256 differs from production's. That is expected and benign: the backup API rewrites page layout and freelist. Logical content is identical, as the row-count and integrity checks show.

---

## 3. Summary table

| # | Area | PASS | FAIL | BLOCKED |
|---|---|---|---|---|
| 2 | Login | 15 | 0 | 0 |
| 3 | User Master | 9 | 0 | 0 |
| 4 | Item Master | 9 | 0 | 0 |
| 5 | Counter Sale | 24 | 0 | 0 |
| 6 | Save Validation | 21 | 0 | 0 |
| 7 | Hold Bill | 9 | 0 | 0 |
| 8 | Purchase | 17 | 0 | 0 |
| 9 | Sales Bill UI | 8 | 2 | 1 |
| 10 | A6 Print | 13 | 7 | 2 |
| 11 | Backup / Restore | 12 | 0 | 0 |
| 12 | Reports | 24 | 2 | 0 |
| 13 | Production safety | 13 | 0 | 0 |
| | **TOTAL** | **165** | **11** | **3** |

Automated baseline re-confirmed during this run: `python run_tests.py` → **Ran 2757 tests … OK** (0 failures, 0 errors, 0 skips).

---

## 4. Login — PASS (15/15)

Driven through the real `database.auth` module and the real `AuthSession`.

| Test | Result | Evidence |
|---|---|---|
| Unknown username rejected | **PASS** | `authenticate()` returned `None` |
| Production ADMIN `pratap` present and active in clone | **PASS** | role `ADMIN`, `is_active=1` |
| Password hash is PBKDF2, not plaintext | **PASS** | `pbkdf2_sha256`, 240 000 iterations |
| Wrong password for a real account rejected | **PASS** | `authenticate()` → `None`, session cleared |
| ADMIN login succeeds through real session | **PASS** | role `ADMIN` |
| Logout clears the session | **PASS** | `session.user is None` |
| PHARMACIST/STAFF login succeeds | **PASS** | role string is exactly `"PHARMACIST/STAFF"` |
| Session never exposes the password hash | **PASS** | keys = `id, is_active, role, username` |
| **Inactive user refused even with the correct password** | **PASS** | login returned `False`, session cleared |
| Successful + failed logins written to audit log | **PASS** | `('login',1)` and `('login',0)` both present |
| STAFF denied all 12 admin-only permissions | **PASS** | wrongly granted = `[]` |
| STAFF retains operational permissions | **PASS** | `view_masters, purchase, sales, counter_sale, reports, print_pdf` all held |
| ADMIN holds every admin-only permission | **PASS** | nothing missing |
| Exactly two roles exist | **PASS** | `('ADMIN', 'PHARMACIST/STAFF')` |

**Admin-only permissions verified as STAFF-denied:** `user_management`, `role_administration`, `security_audit`, `password_reset_others`, `deactivate_users`, `financial_year_management`, `category_management`, `backup`, `restore`, `import_data`, `edit_transactions`, `delete_transactions`.

### Caveat on scope

`create_first_admin()` refuses to run once any user exists, and the clone already carries the two production accounts. The bootstrap ADMIN was therefore inserted **directly into the clone** using the real `auth.hash_password()` helper, and every login after that went through the genuine `authenticate()` / `AuthSession.login()` path. This proves the authentication machinery, roles, session handling, inactive rejection, permission matrix and audit logging — but it does **not** prove that the specific production passwords for `pratap` / `pratap1` are known to the operator. That remains unverified.

---

## 5. User Master — PASS (9/9)

Driven through the real `screens.user_management.UserManagementPage` widget, clicking the real button.

Starting state: acceptance STAFF deactivated via the real `auth.set_user_active`.

| Test | Result |
|---|---|
| Inactive STAFF appears with `Active = No` | **PASS** |
| Button reads `Activate Selected` for an inactive user | **PASS** |
| **`Activate Selected` → `Active = Yes`** | **PASS** (`is_active=1`, cell shows `Yes`) |
| Button switches to `Deactivate Selected` | **PASS** |
| **Login succeeds after activation** | **PASS** (role `PHARMACIST/STAFF`) |
| **`Deactivate Selected` → `Active = No`** | **PASS** (`is_active=0`) |
| **Login rejected after deactivation** | **PASS** (`login()` → `False`) |
| STAFF refused access to User Master | **PASS** (`_guard()` → `False`, "Permission denied" shown) |

Screenshot: `docs/acceptance_screenshots/s3_user_master_activated.png` (captured, not visually inspected)

---

## 6. Item Master — PASS (9/9)

Real `ItemMasterPage` → New → real `_ItemDialog`, clone, 939 historical items snapshotted before and after.

Tax Structure dropdown contains **exactly** the five required entries, in order:

```
GST @ 5% (CGST-2.5% & SGST-2.5%)      -> internal value "5"
GST @ 12% (CGST-6% & SGST-6%)        -> internal value "12"
GST @ 18% (CGST-9% & SGST-9%)        -> internal value "18"
GST @ 28% (CGST-14% & SGST-14%)      -> internal value "28"
ZERO GST                             -> internal value "0"
```

| Test | Result |
|---|---|
| Exactly the 5 required entries, in order | **PASS** |
| No extra or missing entries (`count == 5`) | **PASS** |
| Internal values are the bare GST rates | **PASS** — `['5','12','18','28','0']` |
| Default selection is ZERO GST (no implicit tax liability) | **PASS** |
| Module constant matches the rendered dropdown | **PASS** |
| Legacy display helpers present (`display_for`, `legacy_display`) | **PASS** |
| **Historical imported items NOT modified** | **PASS** — 939 items compared, 0 changed |

Screenshot: `docs/acceptance_screenshots/s4_item_master_new_tax_structure.png`

---

## 7. Counter Sale — PASS (24/24)

Real `CounterSalePage` at 1600 × 900. Real migrated item **`MECOLTRIP`** (item_id 11060), real batch **`LGT-260517`** (batch_id 13937, stock 348, MRP 122, expiry 2028-03-31).

### Keyboard workflow, exactly as specified

Keystrokes were delivered as real Qt key events through the real event filter chain (`_KeyboardCombo.eventFilter` → completer popup → `completionAccepted`), not by calling handler methods.

| Step | Result |
|---|---|
| Item: typed search + **Arrow Down** opens the completer popup | **PASS** |
| Item: **Enter** accepts the highlighted row (`MECOLTRIP`, id 11060) | **PASS** |
| Focus auto-advances Item → Batch | **PASS** |
| Batch: **Arrow Down** opens the batch popup | **PASS** |
| Batch: **Enter** selects a real batch (`LGT-260148`, id 13777) | **PASS** |
| Keyboard-selected batch is sellable (not expired) | **PASS** |
| Focus auto-advances Batch → Qty | **PASS** |
| **Qty** → **Tab** moves focus to Discount | **PASS** |
| Discount → **Enter** adds the item | **PASS** |
| **Item appears in the bill** | **PASS** — 1 `_item_rows` entry, 1 table row |
| Row matches the keyboard-entered qty and discount | **PASS** — qty 3, discount 5 |

### Draft stock availability

| Test | Result | Numbers |
|---|---|---|
| Target batch selectable in the real dropdown | **PASS** | |
| Avail equals stored stock with an empty bill | **PASS** | `348` |
| **Draft availability decreased immediately** | **PASS** | `345` after qty 3 |
| **Stored stock NOT yet reduced (draft only)** | **PASS** | DB still `348` |
| **Same item+batch MERGES into one line** | **PASS** | 1 line, qty `3+2 = 5` |
| **Availability decreased again after the merge** | **PASS** | `343` |
| **Delete draft row removed the line** | **PASS** | 0 rows |
| **Availability returned to stored stock after delete** | **PASS** | back to `348` |
| Stored stock untouched at end of section | **PASS** | `348` |

### Bonus guard observed

Adding an **expired** batch (expiry 2018-06-30) was refused with `warning:Expired Batch` and created no row. **PASS.**

> An early harness run reported a false failure here: the bare `Arrow Down` landed on a batch expired 2024-06-30 and the app correctly refused to sell it. That is correct behaviour, not a defect; the keyboard test was re-pointed at a valid batch.

Screenshots: `s5_counter_sale_initial.png`, `s5_counter_sale_draft_qty5.png`, `s5_counter_sale_after_delete.png`

---

## 8. Save Validation — PASS (21/21)

| Test | Result | Evidence |
|---|---|---|
| Bill has one item line before Save | **PASS** | |
| Required Customer cleared (placeholder selected) | **PASS** | `currentData() is None` |
| **Save BLOCKED with clear validation** | **PASS** | `warning:Validation` → *"Customer is required."* |
| **NO database transaction written by the blocked Save** | **PASS** | `sales_invoices`, `sales_invoice_items`, `stock_batches`, `ledger_transactions`, `journal_entries`, `journal_entry_items` — diff `{}` |
| Bill still pending, nothing committed | **PASS** | |
| Customer supplied from the real customer master | **PASS** | `WALKIN` |
| Save succeeded | **PASS** | invoice id `73588`, bill `2026-2027-Cash-0013` |
| **Exactly ONE sales invoice created** | **PASS** | 1 new row |
| **Exactly ONE sales item set created** | **PASS** | 1 `sales_invoice_items` row |
| **Stock reduced by the sold quantity** | **PASS** | `338 → 336` (delta 2) |
| **Accounting posting written** | **PASS** | 2 rows, `voucher_type='Counter Sale'` |
| Posting is balanced (Dr == Cr per type) | **PASS** | `14.40 / 14.40` |
| Exactly one posting voucher group per sale | **PASS** | |
| Ledger totals changed after the sale | **PASS** | |

> Note: `_on_save()` on the page's panel normally only *opens the modal review dialog*. The harness set `panel._in_review_popup = True` to reach the commit path. Assertions were made against database state (ID-diffed new rows), not against the panel's `was_saved` flag, because the page resets the panel on save — which clears that flag and mints a new bill number. An earlier harness version made this mistake and produced false failures.

Screenshot: `s6_saved_sale.png`

---

## 9. Hold Bill — PASS (9/9)

| Test | Result | Evidence |
|---|---|---|
| Form reset for a new bill after Save | **PASS** | |
| **Hold BILL saved a held draft** | **PASS** | `information:Bill Held`; `hold_bills` +1, `hold_bill_items` +1 |
| **NO stock change on Hold** | **PASS** | `336 → 336` |
| **NO ledger change on Hold** | **PASS** | debit/credit totals identical |
| **NO completed sale created by Hold** | **PASS** | all snapshot tables unchanged |
| **Resume RELOADS the held bill data into the form** | **PASS** | 1 row, qty 3, patient `ACCEPTANCE PATIENT` |
| **Completed resumed bill saved — exactly ONE sale** | **PASS** | 1 invoice, 1 item set, no double save |
| Completed resumed bill reduced stock | **PASS** | `336 → 333` |
| No duplicate bill numbers; resumed bill number differs | **PASS** | `…0013` vs `…0014` |

Screenshot: `s7_held_bill.png`

---

## 10. Purchase — PASS (17/17)

Real `_InvoiceDialog`, real item `ARACHITOL-3L`, real supplier `KARWA AGENCIES`.

| Test | Result | Evidence |
|---|---|---|
| Voucher number auto-generated | **PASS** | `2026-2027-Credit-0219` |
| Save blocked when Supplier missing, nothing written | **PASS** | `warning:Validation`, 0 new invoices |
| Purchase item line added from the entry row | **PASS** | |
| **Purchase saved to the clone** | **PASS** | `purchase_invoices` id `12002` |
| **Stock increased by pay qty + free qty** | **PASS** | `1 → 13` (pay 10 + free 2 = 12) |
| **Accounting posting written** | **PASS** | 2 rows |
| **Posting balanced** | **PASS** | Dr 537.60 / Cr 537.60 |
| **History updated** | **PASS** | `purchase_invoices` total 5682 |
| Saved purchase reloads with header + item lines | **PASS** | |
| **Edit** repopulates the dialog | **PASS** | |
| **Edit updates in place, no duplicate invoice** | **PASS** | pay_qty 10 → 20, 1 row for the id |
| **Edit re-posts stock consistently** | **PASS** | `13 → 23` (+10 for the +10 units) |
| **Delete removes the invoice** | **PASS** | |
| **Delete reverses the stock increase** | **PASS** | `23 → 1`, reversing all 22 units of the *edited* purchase |
| **Delete reverses the accounting posting** | **PASS** | mirrored reversal rows appended, originals retained |

Screenshot: `s8_purchase_saved.png`

---

## 11. Sales Bill UI — FAIL (8 PASS / 2 FAIL / 1 BLOCKED)

Real `PharmacyMainWindow` → `Sales → New Bill`.

### Verified (geometry-level)

| Test | Result | Evidence |
|---|---|---|
| No widget escapes its parent's bounds | **PASS** | 0 issues in a recursive audit |
| Customer / Patient / Doctor controls all present | **PASS** | |
| Customer / Patient / Doctor do not overlap | **PASS** | 0 overlaps |
| Visible spacing between them | **PASS** | Customer→Patient 47 px, Patient→Doctor 46 px |
| Item entry row fields fit inside the entry bar | **PASS** | bar 1364 × 34, 0 fields escaped |
| Entry bar has a cashier-usable height | **PASS** | 34 px |
| Footer Save and Close controls present | **PASS** | `Save Sale`, `Cancel` present |
| Header layout and item entry render | **PASS** | |

### FAIL

| Test | Result | Evidence |
|---|---|---|
| No label text materially overflows its widget | **FAIL** | 1 overflow |
| **Bill/counter number fully readable in its field** | **FAIL** | `cno_label` is `setFixedWidth(34)`, but the rendered counter number `2026-2027-Cash-0015` needs **109 px**. The text is truncated on screen. |

Screenshot: `s9_sales_bill_page.png`

### BLOCKED

| Test | Result | Reason |
|---|---|---|
| Visual appearance of the rendered Sales Bill | **BLOCKED** | Screenshots were captured, but this agent cannot view images. Human-eye assessment of readability, crowding and visual overlap was **not performed**. |

---

## 12. A6 Print — FAIL (13 PASS / 7 FAIL / 2 BLOCKED)

### PASS

| Test | Result |
|---|---|
| Declared A6 profile is 105 × 148 mm | **PASS** |
| Declared orientation is Portrait | **PASS** |
| Content box fits inside the page (97 × 138 mm) | **PASS** |
| A6 PDF generated for the acceptance sale | **PASS** (2 517 bytes) |
| A6 PDF generated for a multi-item bill | **PASS** (7 246 bytes) |
| Qt print page layout is hard-coded Portrait | **PASS** |
| Qt page size resolves to A6 105 × 148 mm | **PASS** |
| Page validation passes (no overflow past page edges) | **PASS** |
| No overlapping text runs on page 1 | **PASS** |

### FAIL — the A6 page size requirement is not met

| Test | Result | Actual |
|---|---|---|
| PDF MediaBox is 105 × 148 mm (acceptance sale) | **FAIL** | **105.0 × 50.75 mm** |
| PDF page is Portrait (acceptance sale) | **FAIL** | 105 wide × 50.75 tall → landscape-shaped |
| PDF MediaBox is 105 × 148 mm (multi-item bill) | **FAIL** | **105.0 × 91.7 mm** |
| PDF page is Portrait (multi-item bill) | **FAIL** | 105 wide × 91.7 tall |
| Print-path page size is full A6 105 × 148 mm (acceptance sale) | **FAIL** | print job would use **105.0 × 50.75 mm** |
| Print-path page size is full A6 105 × 148 mm (multi-item) | **FAIL** | print job would use **105.0 × 91.7 mm** |
| `Canon LBP2900` is installed and available to Qt | **FAIL** | available = `['OneNote (Desktop)', 'Microsoft Print to PDF']` |

**Root cause.** `database/pharmacy_a6_receipt.py` declares `PHARMACY_A6` as 105 × 148 mm correctly, but every output path then passes the pages through `content_profile()`, which **shrinks the page height to fit the actual content**, floored at `MIN_RECEIPT_HEIGHT_MM = 45` and capped at 148:

```
wanted = used_height_mm(pages, profile)
height = max(45.0, min(wanted, profile.height_mm))     # pharmacy_a6_receipt.py:880-881
```

This is applied inside `build_sale_pages`, again in `generate_pharmacy_a6_bill`, and again in `print_pharmacy_a6_bill` **before** the `QPageLayout` is built. Consequences:

- The saved PDF's `/MediaBox` is **not** A6. It is a variable-height receipt strip.
- The **physical print job uses the same shrunk height**, so printing would not produce a full A6 sheet either.
- Width is always exactly 105 mm, so it is not a full-size A4-or-worse failure — but it is not the 105 × 148 mm the acceptance criterion requires, and short pages are wider than they are tall (landscape-shaped), which is the opposite of the required Portrait.

Whether this is intended behaviour or a defect is a product decision — the docstring presents content-sized pages as deliberate. **Against the acceptance criterion as written, it is a FAIL.** No code was changed.

### BLOCKED — physical printing

| Test | Result | Reason |
|---|---|---|
| Printer A6 page-size support probe | **BLOCKED** | The only printers are `OneNote (Desktop)` and `Microsoft Print to PDF`; neither is the target device. |
| **Physical print on `Canon LBP2900`** | **BLOCKED** | **`Canon LBP2900` is not installed on this machine.** No print job was created and no paper output was observed. **Physical printing is NOT claimed as passing.** |

Generated PDFs are retained at `…/pharmacy_accept/a6/acceptance_sale.pdf` and `…/multi_item.pdf` for inspection.

---

## 13. Backup / Restore — PASS (12/12)

Driven through `database.backup_restore` and the real `BackupRestorePage`, with `PHARMACY_DB` pointing at the clone.

| Test | Result | Evidence |
|---|---|---|
| Backup & Restore page opened (ADMIN session) | **PASS** | page shows the clone path |
| **Backup created via the application code path** | **PASS** | 42 618 880 bytes, 32 tables, SHA-256 recorded |
| Backup file exists and is non-empty | **PASS** | |
| **Backup validates** (integrity + 27 expected tables) | **PASS** | `valid=True`, `integrity='ok'`, 0 missing tables |
| Recorded SHA-256 matches the file on disk | **PASS** | |
| **Restore rehearsal completed against the CLONE** | **PASS** | `restored=True`, safety snapshot auto-created |
| **Restored clone `integrity_check` ok, 0 FK violations** | **PASS** | |
| Restored clone row counts match the backup source | **PASS** | all 5 tracked tables equal |
| **Production NOT touched by the restore** | **PASS** | production SHA-256 identical before/after |
| Restore rewrote the database the app points at | **PASS** | `data/pharmacy_temp.db` |
| Validate rejects a non-database file with a clear reason | **PASS** | `Not a valid SQLite database (file is not a database).` |

> `restore_backup()` has **no target-path parameter** — it always restores into `get_db_path()`. The rehearsal was therefore safe only because the process-level `PHARMACY_DB` guard pointed at the clone. Any restore run without that guard would overwrite production. This is worth an explicit confirmation prompt in the UI.

Screenshot: `s11_backup_restore.png`

---

## 14. Reports — FAIL (24 PASS / 2 FAIL)

All 11 required reports were opened through the **real** `PharmacyMainWindow._on_menu_action` dispatcher, exactly as the menu does.

| Report | Menu path | Rows rendered | Result |
|---|---|---|---|
| Sales | Reports → Sales Report | 44 251 | **PASS** |
| Purchase | Reports → Purchase Report | 11 829 | **PASS** |
| Stock | Reports → Stock Report | 1 962 | **PASS** |
| GST | Reports → GST Report | 11 829 | **PASS** |
| Party Wise | Reports → Party Wise Report | 3 | **PASS** |
| Trial Balance | Account → Trial Balance | 123 | **PASS** |
| P&L | Account → Profit & Loss | 9 | **PASS** |
| Balance Sheet | Account → Balance Sheet | 102 (3 section tables) | page opens — **see FAIL below** |
| Cash Book | Account → Cash Book | 2 070 | **PASS** |
| Bank Book | Account → Bank Book | 0 | **FAIL** — see below |
| Day End | Sales → Day End | 51 | **PASS** |

Total migrated data rows rendered across the report set: **72 229**. Every page reached the "displayed" state with the navigation status label updated (e.g. `Reports / Sales Report`). No report raised an error dialog.

Screenshots: `s12_*.png` (11 files, captured not inspected)

### FAIL 1 — Bank Book shows no rows in the default period

The page opens correctly and reports `Opening Balance: -958,740.00` with the message *"No bank transactions found for the selected period."*

**This is not an application defect.** The clone's only `BANK`-role ledger is `SBI AC NO 33822385323` (id 69274) and its **144** transactions are all dated **2015-04-15 → 2025-03-31**, entirely outside the active financial year **2026-04-01 → 2027-03-31** that the page defaults to. The report is answering correctly; there is simply no migrated bank data in the current FY.

Recorded as **FAIL** against the literal criterion *"pages open and migrated data is visible"*, because migrated bank data is **not** visible without widening the date range.

### FAIL 2 — Balance Sheet does not balance

The page opens and renders 102 rows across ASSETS / LIABILITIES / EQUITY sections, but reports:

```
Status: UNBALANCED (by 6,751,112.25)
Total Assets:      14,341,727.47
Total Liabilities:  7,590,615.22
Total Equity:      (blank)
Difference:         6,751,112.25
```

This is a genuine finding requiring owner attention: the migrated opening balances do not reconcile, and the equity line is empty. It is a data/migration condition rather than a page-open failure, but a balance sheet that reports itself unbalanced is not releasable as-is.

---

## 15. Production safety — PASS (13/13)

| Check | Before | After | Result |
|---|---|---|---|
| **Production SHA-256** | `538e8f017ec5253a2b59b8cf6b418904a8d5a78bd01a2caa56e71309a2eae73a` | `538e8f017ec5253a2b59b8cf6b418904a8d5a78bd01a2caa56e71309a2eae73a` | **PASS — IDENTICAL** |
| Production file size | 42 618 880 | 42 618 880 | **PASS** |
| 26 business + auth table row counts | — | — | **PASS** (0 differences) |
| `app_users` row count | 2 | 2 | **PASS** |
| `app_users` content | `pratap`/ADMIN/active, `pratap1`/STAFF/active | identical, same `created_at`, `updated_at`, `last_login_at` | **PASS** |
| **`auth_audit_log` row count** | **100** | **100** | **PASS — no new login entry** |
| `auth_audit_log` max id | 100 | 100 | **PASS** |
| `integrity_check` | ok | ok | **PASS** |
| `foreign_key_check` | 0 | 0 | **PASS** |

**The previous attempt's blocker #1 is resolved and disproved for this run.** The stray successful `pratap` login at audit row 100 (`2026-10-05T11:27:24.727198+00:00`) that the earlier documentation flagged is still present and unchanged — it belongs to the earlier session, not this one. No authentication metadata was modified during this acceptance.

### Disclosure — empty WAL sidecars appeared and were removed

Opening the WAL-mode production database **read-only** to take the clone caused SQLite to create two scratch sidecars next to it: `data/pharmacy.db-wal` (**0 bytes**) and `data/pharmacy.db-shm` (32 768 bytes).

- The `-wal` was **zero-length**, so **no data was ever written** — there were no pending frames.
- `data/pharmacy.db` itself has `LastWriteTime = 2026-10-05 16:57:24`, **before** this acceptance began, and its SHA-256 is byte-identical before and after.
- Both empty sidecars were deleted afterwards to leave the directory as found; this is safe precisely because the WAL contained nothing.

This is the only filesystem side effect of the acceptance outside the clone.

---

## 16. Evidence index

| Artifact | Location |
|---|---|
| Harness scripts | `C:\Users\Nilesh\AppData\Local\Temp\pharmacy_accept\` |
| Per-section machine-readable results | `…\pharmacy_accept\result_*.json` |
| Production before/after snapshot | `…\pharmacy_accept\step1_clone.json`, `production_final.json` |
| Screenshots (21, **captured but not visually inspected**) | `docs/acceptance_screenshots/` |
| Generated A6 PDFs | `…\pharmacy_accept\a6\acceptance_sale.pdf`, `multi_item.pdf` |
| Acceptance backup | `…\pharmacy_accept\backups\acceptance_backup.db` |

Screenshots exist but were **never viewed** by this agent. They are supplied as evidence for a human reviewer, not as proof of visual quality.

---

## 17. Release recommendation

# NOT READY — 5 exact blockers

1. **A6 output is not 105 × 148 mm.** `database/pharmacy_a6_receipt.py` applies `content_profile()` to every output path, shrinking page height to content (105 × 50.75 mm small bill, 105 × 91.7 mm multi-item). This affects the saved PDF *and* the physical print job. Decide whether full A6 is required and, if so, stop shrinking the height for the print path.
2. **Physical `Canon LBP2900` printing is unverified.** No such printer is installed on this machine; no job was created and no paper was observed. Install the driver and re-run §12 on real hardware.
3. **Visual GUI acceptance was never performed.** This agent cannot view images. A human must review the 21 screenshots in `docs/acceptance_screenshots/` for readability, crowding and overlap.
4. **Sales Bill counter number is truncated.** `cno_label` is fixed at 34 px but needs 109 px for `2026-2027-Cash-0015`.
5. **Balance Sheet is unbalanced by 6,751,112.25 with blank Total Equity.** Requires owner review of migrated opening balances.

### Not blockers

- **Bank Book shows 0 rows** in the default FY. Correct behaviour — all 144 bank transactions predate the active year. Noted for awareness only.
- **Production data is intact.** Hash identical, `auth_audit_log` still at 100 rows, all 26 table counts unchanged, integrity ok, 0 FK violations. The prior attempt's authentication-metadata concern did not recur.

### Strongly verified

Login and role enforcement (15/15) · User Master activate/deactivate with login verification (9/9) · Item Master tax structures exact (9/9) · Counter sale keyboard workflow and draft stock arithmetic (24/24) · Save validation with proven zero-write rejection (21/21) · Hold / resume / single completion (9/9) · Purchase create-edit-delete with balanced, reversed postings (17/17) · Backup, validate, and clone-only restore (12/12) · All 11 reports open on migrated data · Production safety (13/13) · 2 757 automated tests still green.

**No features were added and no application code was modified.**
