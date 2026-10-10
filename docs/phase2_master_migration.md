# Phase 2 Master Migration Report — Party/Reference Masters ONLY

## Scope
Suppliers, customers, doctors (+ their direct reference fields) from
`PharmaWinner202610051955.sql` (35,462,774 bytes, READ-ONLY, unmodified).
No transactions, no ledgers, no balances. Local dev DB only
(`data/pharmacy.db`); production/EXE/dist/source untouched; no EXE built.

## Pre-apply backup
- `migration_backups/pre_phase2_apply_20261009_131957.db` — 372,736 bytes,
  SHA-256 `a2012169d71a368de938dcf6ab32f795e730c45e73a43ada505`, integrity ok
  (post-GST Phase-1 state: 219/14/137/942/402, GST 218/313/23/2/7/379).
- Apply-time backup by tool: `data/backups/pharmacy_backup_20261009_132018.db`.

## Dry run (re-verified before apply; reports retained)
- `migration_backups/phase2_dry_run.md` + `.json` — internally consistent TRUE, blockers 0.
- Source: ledger 123 (debtors 29 incl. WALKIN id 7, creditors 85, 9 system/bank/sale rows
  excluded), sundaryinfo 113, doctormst 8.
- Expected/achieved: customers 29, suppliers 85, doctors 8.

## Mappings (verbatim, IDs preserved)
- Debtor ledgers → `customers` (id = ledger ID, incl. WALKIN 7 with defaults — no fabrication).
- Creditor ledgers → `suppliers` (id = ledger ID).
- `doctormst` → `doctors` (id preserved; SELF 3 = RAHURI/blank, SELF 6 = SELF/SELF).
- `sundaryinfo` → address/city/contact person/contact no verbatim; StateID 1 → MAHARASHTRA
  (85 info rows), 0/unknown → `''` (28 rows); supplier-only SalesTaxNo/VATorTIN/discount/
  credit limit/period verbatim; customer discount/credit fields verbatim.
- Unsupported / held back: `ledger.OpeningBal` (32 nonzero parties — forbidden),
  `AdminCreated`/groups, non-partyledgers, `ledger_id` stays NULL (direct-SQL inserts;
  DAO auto-ledger creation deliberately bypassed), customers have no tax columns.

## Schema decision (owner-approved)
- `UNIQUE(doctors.doctor_name)` dropped via `init_database` rebuild migration
  (`_migrate_doctors_name_not_unique`; IDs/FKs/sequence preserved, idempotent).
  All consumers key by `doctors(id)`; counter-sale/doctor combos select by ID;
  doctor dialog still blocks *new* UI-created dupes (unchanged conservative behavior).

## Validation (independent, 23/23)
- customers 29, suppliers 85, doctors 8; SELF 3+6 exact; WALKIN id 7 defaults.
- `ledger_id` NULL everywhere; `account_ledgers` 0; all opening balances 0.
- Phase 1 frozen: 219/14/137/942/402, GST 218/313/23/2/7/379, provenance 942/942,
  item 590 EMPTY/6. All transaction tables 0. integrity ok, FK 0.
- Post-apply SHA-256: `51a8346eadbf659d20a3b6801c3221a16ba909750dca18d6c091cd134a1e5cec`.

## UI verification (dev DB, offscreen)
- Supplier/Customer/Doctor grids: 85/29/8 rows. Doctor search SELF → IDs 3+6.
  Customer search WALKIN → 1 row. Counter-sale doctor combo lists both SELF
  entries and selects IDs 3 and 6 by key.
- Observation (not a blocker): the sale-panel combo shows both SELF rows with
  identical text (distinguished by order/ID); the master grid shows the
  distinguishing city/specialty columns. `SupplierDAO.update` auto-creates a
  linked ledger as a side effect — a UI-check probe created one such ledger and
  it was fully reverted (0 ledgers, NULL FKs, integrity re-verified). Migration
  path never touches those DAOs.

## Tests
- New `test_phase2_party_masters.py`: 5/5 (dry-run consistency, apply counts/IDs,
  no-ledgers/balances, transactions-empty/integrity). Tool freeze-check improved
  to relative pre/post comparison (safer + testable; same guarantee on dev data).
- Full `.venv run_tests.py`: **2879 tests, 5 failures** — the documented pre-existing
  offscreen set (test_04, test_30, test_05/06/07). Zero new, none disabled.

## Files changed
- `tools/migrate_party_masters_from_pharma_winner.py` (new tool),
  `test_phase2_party_masters.py` (new),
  `database/connection.py` (doctors uniqueness migration),
  `migration_backups/phase2_dry_run.*` (reports), this file.
