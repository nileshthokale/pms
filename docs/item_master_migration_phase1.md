# Item Master Migration — Phase 1 Report

## 1. Source file
- `PharmaWinner202610051955.sql` — 35,462,774 bytes, MySQL 5.7.11 dump of `medicalretailer`, 52 tables.
- Opened READ-ONLY (offline parser, never executed against a server). Unmodified (mtime 2026-10-07 11:19:48).

## 2. Source database type
- Old Pharma-WINNER, MySQL 5.7. Phase 1 uses only: `itemmst`, `companymst`, `unitmst`, `pathymst`, `drugmst`, `itemdrugs`.

## 3. Source table mappings (OLD FIELD → NEW FIELD, verbatim unless noted)
- `companymst.ID` → `companies.id` (explicit, preserved); `CompanyName` → `company_name`; `ShortName` → `short_name`.
- `unitmst.ID` → `units.id` (preserved); `ItemUnit` → `unit_name`.
- `drugmst.ID` → `drugs.id` (preserved); `DrugName` → `drug_name`.
- `pathymst` → no table; `PathyID` resolved to `items.pathy` text (all 942 items → `ALLOPATHIC MEDICINES`).
- `itemmst.ID` → `items.id` (preserved); `ItemName` → `item_name` (byte-verbatim, trailing spaces kept);
  `UnitID` → `unit_id`; `CompanyID` → `company_id`; `category_id` = NULL (never invented);
  `PackSize` smallint → `pack_size` TEXT; `DiscountPer` → `discount`; `ReorderStockLevel` → int;
  `Rate` → `rate`; `MRP` → `mrp`; `TaxID` → `tax_structure` (str verbatim);
  `Location` → `location`; `SheduledID` → `scheduled` (str verbatim); `DPCO` → `dpco`.
- `itemmst.SellLoose`, `itemmst.BillCompulsory` → UNSUPPORTED (no target column; all Y / all N).
- `itemdrugs.ItemID` → `item_ingredients.item_id`; `DrugID` → `drug_id`; `Power` verbatim.
  `itemdrugs.ID` has no target (`item_ingredients.id` is newly generated).

## 4. Target DB path
- ONLY `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\data\pharmacy.db`
  (unfrozen dev DB per `database/connection.py`; `sys.frozen` false, `PHARMACY_DB` unset).
- Production EXE DB (`%LOCALAPPDATA%\PharmacyManagementSystem\`), source SQL, `dist/`, EXE untouched.
- Post-migration SHA-256: `2da61746f06004f5b2f96ab767527365370308cf00bbf4198b2e680e39af0dde`.

## 5. Backups + SHA-256
- `migration_backups/pre_item_master_migration_20261007_131800.db` — 249,856 bytes,
  `2db65e9b4f0fc752aff75f9292a176bf0ea4137b6c9d6a674b8c6f403a8cfa59`, integrity ok.
  Restored before apply (removed 2 stray `auth_audit_log` rows from a direct-unittest run).
- `migration_backups/pre_item_master_apply_20261007_135646.db` — 249,856 bytes, same SHA, integrity ok.
- Apply-time backup by tool: `data/backups/pharmacy_backup_20261007_135659.db` (262,144 bytes).
- No backup deleted.

## 6. Dry-run counts
- Source: companymst 1222, unitmst 16, pathymst 6, drugmst 147, itemmst 942, itemdrugs 402.
- Expected targets: companies 219, units 14, drugs 137, items 942, item_ingredients 402.
- Missing refs: 0. Orphans: 0. Final dry run: internally consistent TRUE, blockers 0.
- Reports: `migration_backups/phase1_dry_run.md`, `migration_backups/phase1_dry_run.json`.

## 7. Imported counts
- companies 219, units 14, drugs 137, items 942, item_ingredients 402 (tool-reported and independently re-queried).

## 8. Skipped counts
- 1003 unreferenced companies, 2 unreferenced units (ID 7 SCRUB, 14 DROP), 10 unreferenced drugs.
- 0 item rows skipped. UI-check scratch rows (`UIVERIFY-SCRATCH`) created and removed; final items = 942.

## 9. Unsupported fields
- `SellLoose`, `BillCompulsory`, `itemdrugs.ID`, `items.category_id` (see §3).

## 10. Tax mapping results
- No tax master table exists in the dump. All 10 TaxIDs (1,2,4,6,7,11,12,13,14,15) = UNKNOWN,
  preserved verbatim in `items.tax_structure`, never converted. TaxID 12 numerically overlaps GST 12%
  — flagged AMBIGUOUS-NUMERIC-OVERLAP, still preserved as `'12'`. No GST amount is invented for legacy codes.

## 11. ID preservation result
- All company/unit/drug/item IDs preserved explicitly (e.g. item 6 = BIO D3 PLUS).
- All 942 source items cross-checked by ID against the dump: 0 mismatches.
- `sqlite_sequence` cursors kept above preserved IDs.

## 12. Item-Drug mapping result
- 402/402 `itemdrugs` rows imported (398 distinct items incl. one 5-drug item 488; 137 distinct drugs).
- 0 orphan ingredients. `Power` verbatim (137 distinct values).

## 13. Duplicate-name/unit handling (approved schema decision)
- Old key `UNIQUE(UnitID, ItemName)` → new `UNIQUE(item_name, unit_id)` (`database/connection.py`,
  with rebuild migration `_migrate_items_name_unit_unique` for existing DBs).
- POWERGESIC: ID 51 + TABLET(12) and ID 920 + GEL(15) — both kept.
- CALTONVIT: ID 681 + unit 12 and ID 869 + POWDER(5) — both kept.
- VITOMIN-Z: IDs 290 (`VITOMIN-Z`) / 303 (`VITOMIN-Z `) — trailing space preserved, untouched.
- Same name + same unit still rejected (DB constraint + dialog + `ItemDAO.name_exists(name, unit_id, ...)`).
- CSV import identity is now (name, unit). Counter-sale/item combos unchanged (ID-keyed).

## 14. Orphan/reference checks
- 0 orphan unit/company references; 0 duplicate (item_name, unit_id); 0 orphan ingredients.

## 15. Transaction tables confirmed empty
- purchase_invoices/items, stock_batches, sales_invoices/items, customer_receipts, supplier_payments,
  credit/debit notes + items, journal_entries/items, ledger_transactions: all 0.
- Party tables (customers, suppliers, doctors): all 0. No stock or accounting created.

## 16. SQLite integrity result
- `integrity_check` = ok; `foreign_key_check` = 0 violations (tool + independent checks, pre- and post-UI-check).

## 17. Test results
- New `test_item_name_unit_unique.py`: 12/12 pass (A–E incl. Qt dialog tests).
- Official `run_tests.py` before apply: 2812 tests, 6 failures — all proven pre-existing on the clean
  tree (test_04 layout width, test_30 offscreen rowHeight, test_71 isolated-DB assertion,
  test_05/06/07 offscreen font metrics). Clean-tree full baseline: 2800 tests, same 6 + env printer flake.
- Official `run_tests.py` after apply + UI check: 2812 tests, 5 failures — the same pre-existing set
  minus flaky test_71 (passed with migrated data staged). No test disabled. **Zero new failures.**

## 18. Application UI verification (local dev DB, Master → Item)
- Grid shows 942 items. Search POWERGESIC → IDs 51/TABLET and 920/GEL (+ substring match 52 POWERGESIC M R).
- Search CALTONVIT → IDs 681/TABLET and 869/POWDER with correct units.
- Edit + reopen item 51 with identical values: row byte-identical after save.
- Same name + same unit rejected in dialog; same name + other unit accepted. Scratch rows removed.

## 19. Exact files changed (this phase only)
- `database/connection.py` — composite `UNIQUE(item_name, unit_id)` + `_migrate_items_name_unit_unique()`.
- `database/item_dao.py` — unit-aware `name_exists(name, unit_id, exclude_id)`.
- `database/import_service.py` — item identity (name, unit) via `_find_existing_item()`.
- `screens/item_master.py` — per-unit duplicate validation.
- `docs/legacy_data_migration.md` — uniqueness rule note.
- `test_item_name_unit_unique.py` — new, 12 focused tests.
- `tools/migrate_item_master_from_pharma_winner.py` — new, dry-run/apply tool (ID-preserving, atomic).
- `migration_backups/` — backups + dry-run reports (untracked, retained).
- This file.

## PHASE 1 STATUS = PASS
- Final counts: companies 219, units 14, drugs 137, items 942, item_ingredients 402.
- SOURCE → MAPPING → IMPORT → VALIDATION → UI CHECK: all pass.
