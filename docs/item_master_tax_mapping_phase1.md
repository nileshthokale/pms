# Item Master Tax Mapping — Phase 1 Final Report

Owner decision implemented: **flag all, convert none**.

## Problem description
Phase 1 stored old `itemmst.TaxID` values verbatim in `items.tax_structure`
(`6`, `11`, `12`, …), and the UI displayed them as bare numbers — with `12`
additionally at risk of being read as GST 12% by numeric coincidence.

## Source evidence
- `taxmst` has NO `CREATE TABLE` / `INSERT` in `PharmaWinner202610051955.sql`.
  Its only trace is the final `dvitemlist` view definition, proving the join
  `taxmst.ID = itemmst.TaxID` and its columns (`TaxStructure`, `Percentage`,
  `TaxOn`). Names/percentages are unrecoverable. (`sheduledmst` is missing identically.)
- `dvitemlist` in the dump is a `SELECT 1 AS …` placeholder — no mapping recoverable.
- Historical `TaxPer` (purchase-side only: 11,891 `invoiceitemdetail` + 142
  `challanitemdetail` rows; sales/stock carry no tax columns; entry-invoice has 0 rows):
  values 0, 5, **5.5, 6, 12.5, 13.5**, 12, 18, 28 — a VAT-era mix plus GST-era
  rates across 2015–2026. Supporting evidence only, never an overwrite rule.

## All legacy TaxIDs (942 items)
| TaxID | Items | Historical TaxPer | Status |
| --- | ---: | --- | --- |
| 1 | 5 | 0 ×5 | AMBIGUOUS |
| 2 | 43 | 0 ×25 | AMBIGUOUS |
| 4 | 1 | 12.5 ×1 | UNKNOWN |
| 6 | 305 | 5/5.5/6 split, no 12/18/28 | AMBIGUOUS |
| 7 | 18 | bimodal 12.5/13.5 vs 5-family | AMBIGUOUS |
| 11 | 220 | 12 at 63% plurality, 37% other | AMBIGUOUS |
| 12 | 323 | 12 at 62% plurality, 35% at 5/5.5/6 | AMBIGUOUS |
| 13 | 24 | 18 at 83% + VAT residue | AMBIGUOUS |
| 14 | 2 | 12.5/13.5/28 split | AMBIGUOUS |
| 15 | 1 | single 0 row | UNKNOWN |

## Proposed / verified / unknown / ambiguous mapping
- Proposed GST conversions: **none**. Verified: **0**. Unknown: 4, 15. Ambiguous: the rest.
- Numeric look-alikes (`12`→12%) were explicitly NOT mapped.

## Final owner decision implemented
- Stored codes stay verbatim (full traceability, zero data migration).
- `database/tax_structures.py` holds the single `LEGACY_TAX_ID_MAPPING`
  (OLD → NEW=None → REASON, all non-VERIFIED) plus `resolve_tax_display()`.
- Every user-facing label shows `Legacy Tax Code N — Mapping Required`
  (grid via `display_for`, dialog via `legacy_display`); known legacy IDs take
  precedence over numeric GST coincidence, so `12` never displays as GST.
- A future VERIFIED entry maps to its GST full name with no other code change.
- Five dropdown options byte-exact and unchanged; no VAT option added; save
  paths round-trip codes unchanged; purchase prefill still reads numeric rates
  through `rate_percent()` (user-overridable per-line default, covered by
  existing compatibility tests — not an item-master truth claim).
- Known limitation (documented): a newly created GST-12% item shares the stored
  value `12` with legacy TaxID 12 and therefore also displays the flag; its
  value, validation and save path are unaffected.

## Validation
- Stored data byte-identical before/after (same 10 codes/counts; integrity ok, FK 0).
- Transaction/party tables untouched (still Phase-1 empty).
- New `test_item_tax_flag_display.py`: 10/10 pass (no GST names for codes, exact flag
  format, five options, no VAT, ambiguous flagged, VERIFIED mechanism, mapping
  coverage, traceability incl. same-name/different-unit, dialog + grid flags).
- Updated `test_07`, `test_40`, `test_53` to the flagged contract.
- Official `run_tests.py`: 2822 tests, 5 failures — all proven pre-existing on the
  clean tree (offscreen layout/font metrics). Zero new failures, none disabled.

## Backups / safety
- `migration_backups/pre_tax_display_correction_20261007_143207.db` (360,448 bytes,
  SHA-256 `756cbafef9cce944568a07fac39192651ccf303f2ec2331cc2db0ae5af70f915`, integrity ok).
- Code-only change; no data migration ran. Production/EXE/source/dist untouched.

## Files changed
- `database/tax_structures.py`, `screens/item_master.py` (dialog selection + docstrings),
  `test_item_tax_structure.py` (3 expectations), `test_item_tax_flag_display.py` (new),
  `docs/item_tax_structure.md`, `migration_backups/phase1_tax_mapping_dryrun.md` (dry run),
  this file.

## Provenance correction (follow-up, implemented and validated)
- New nullable `items.legacy_tax_id` (`INTEGER DEFAULT NULL`; `init_database` ALTER + fresh
  CREATE; rebuild path carries the column when present): NULL = new GST value,
  non-NULL = old Pharma-WINNER TaxID preserved for audit.
- All 942 migrated items backfilled (`legacy_tax_id` == stored code, 0 mismatches);
  distribution matches source TaxIDs exactly (1:5, 2:43, 4:1, 6:305, 7:18, 11:220,
  12:323, 13:24, 14:2, 15:1). No conversion, no other field touched.
- `ItemDAO` returns `legacy_tax_id` in get/search; `insert` defaults NULL (new items);
  `update` preserves provenance unless an explicit value (incl. NULL on deliberate
  GST conversion) is passed. Phase-1 import tool writes provenance and validates it.
- Display is provenance-first: non-NULL → flag for that code; NULL → genuine GST label.
  Verified live: OLD TaxID 12 → `Legacy Tax Code 12 — Mapping Required`;
  NEW GST 12 → `GST @ 12% (CGST-6% & SGST-6%)` — never collide.
- Dialog: legacy rows get the flagged entry; NULL rows select the GST option; unrelated
  edits preserve provenance; explicit tax change clears it. No VAT option anywhere.
- Tests: `test_item_tax_provenance.py` (A–J: 11 tests) + flag suite pass; full
  `run_tests.py` 2833 tests with only the 5 proven pre-existing offscreen failures.
- Validation: 942 items, provenance 942/942, integrity ok, FK 0, all transaction tables empty.
- Provenance backup: `migration_backups/pre_tax_provenance_20261007_145107.db` (360,448 bytes,
  SHA-256 `15afe9fbf51e46a90b7ed3a6f3cd1dd93e543feda12c209d99c9d7e3edea1b90`, integrity ok).

## GST-only apply (owner-approved, applied 2026-10-09, local dev DB only)
- Review gate passed: dry-run JSON holds 942 per-item decisions with exact totals
  (5:218, 12:313, 18:23, 28:2, 0:7, EMPTY:379); every non-empty decision backed by
  GST-era (VhDate >= 2017-07-01) evidence; no VAT-rate conversion.
- Pre-apply backup: `migration_backups/pre_gst_apply_20261009_124845.db` (372,736 bytes,
  SHA-256 `a347847e0c9b63aea17f630a022df54a0ac133532ce7ef765bf22c4df4369cf7`, integrity ok).
- Applier: `tools/apply_gst_only_tax_mapping.py` — updates ONLY `items.tax_structure`
  from the reviewed JSON in one transaction (rollback on any failure).
- Post-apply SHA-256: `880991f6e57e9561409a0ba2772db1aa40948854084031cf0c5dad7f37206681`.
- Final distribution: GST 5% = 218, GST 12% = 313, GST 18% = 23, GST 28% = 2,
  ZERO GST = 7, EMPTY = 379 (total 942; per-item match to review 942/942).
- Item 590 remains EMPTY with `legacy_tax_id` = 6. All IDs, names, provenance, masters
  (219/14/137/402), and empty transaction tables verified; integrity ok, FK 0.
- Display now: GST values (mapped or new) → full GST names; EMPTY → blank; unmapped
  legacy codes (none remain in migrated data) → flag. Dialog selects the GST option
  for mapped items and preserves value+provenance on untouched saves.
- UI verified on dev data: 942 grid rows, only GST/ZERO/blank labels, POWERGESIC /
  CALTONVIT / BIO D3 PLUS spot-checked, edit/reopen preserves (probe edits reverted).
- Tests: focused tax suites 102/102; full `run_tests.py` 2874 tests with only the 5
  documented pre-existing offscreen failures — zero new, none disabled.
- Remaining limitation: a newly saved GST-12% item shares stored value `12`; it is
  distinguished solely by NULL provenance (see provenance section above).
