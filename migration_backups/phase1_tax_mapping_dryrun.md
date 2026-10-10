# Item Master Tax Mapping — Phase 1 Dry-Run Report (NO DB CHANGES)

Source: `PharmaWinner202610051955.sql` (read-only). Target DB untouched.
Date: 2026-10-07. Status: **STOPPED AT OWNER REVIEW — 0 VERIFIED mappings.**

## A. Current tax codes (`items.tax_structure`, 942 items)
| Code | Items | Sample items |
| --- | ---: | --- |
| 1 | 5 | SOFT ROLL 6", FOLDING CHAIR, RABECAP 20, PREGABID D 50 |
| 2 | 43 | SACRO LUMBAR BELT, SCALPE VEIN 20/23, STERILE WATER 5ML |
| 4 | 1 | NORTRYPTOMER P SR 50 |
| 6 | 305 | ALPRAX 0.25 MG, AMLOVAS L, AVIL AMP, BRO ZEDEX 60ML |
| 7 | 18 | ALMITY, B-PROTIN CHOCOLATE/DF, LUPIFIT 110ML |
| 11 | 220 | ANKLE TRACTION BELT, BIO D3 PLUS, DALACIN C 300MG, DEXONA |
| 12 | 323 | ATIVAN 1MG, CLAVAM BID DRY, DEPO MEDROL 40/80 |
| 13 | 24 | TESS 15GM, HYDROGEN PEROXIDE 10, COERIP, ROSORTHO |
| 14 | 2 | COECORAL 250, ZEROSTIFF TOTAL |
| 15 | 1 | TOLEX-DMR |

## B. Source evidence
1. **taxmst is missing**: no CREATE/INSERT in the dump. It appears only in the final
   `dvitemlist` view definition (`taxmst.ID = itemmst.TaxID`, exposing `TaxStructure`,
   `Percentage`, `TaxOn`). Join direction confirmed; names/percentages unrecoverable.
   (`sheduledmst` is missing the same way.)
2. `dvitemlist` in the dump is a `SELECT 1 AS ...` placeholder — no mapping recoverable.
3. Historical `TaxPer` (purchase-side only; `salesitemdetail` and `stockbalance` carry no tax
   columns; `entryinvoicevhitem` has 0 rows):
   - `invoiceitemdetail.TaxPer`: 11,891 rows; `challanitemdetail.TaxPer`: 142 rows.
   - Values seen: 0, 5, 5.5, 6, 12, 12.5, 13.5, 18, 28 — a VAT-era mix (5.5/6/12.5/13.5
     are not GST rates) plus GST-era 5/12/18/28. Data spans 2015–2026, i.e. both regimes.

## C–H. Per-TaxID evidence table (proposed mapping: NONE assigned)
| TaxID | Items | Historical TaxPer (rows) | Candidate GST | Confidence | Status | Reason |
| --- | ---: | --- | --- | --- | --- | --- |
| 1 | 5 | 0 ×5 | ZERO GST? | low | AMBIGUOUS | 100% zero but only 5 txn rows; exempt use possible |
| 2 | 43 | 0 ×25 | ZERO GST? | low | AMBIGUOUS | 100% zero but thin (25 rows, 43 items) |
| 4 | 1 | 12.5 ×1 | none | — | UNKNOWN | single VAT-era row, no GST signal |
| 6 | 305 | 5 ×391, 5.5 ×111, 6 ×94 | none | — | AMBIGUOUS | VAT-era split, no 12/18/28 at all |
| 7 | 18 | 12.5 ×41, 13.5 ×22, 5 ×8, 6 ×7, 5.5 ×5 | none | — | AMBIGUOUS | bimodal VAT-era |
| 11 | 220 | 12 ×4526, 5 ×1620, 6 ×367, 5.5 ×197, 0 ×176, 18 ×220, 12.5 ×34, 13.5 ×10, 28 ×4 | none | — | AMBIGUOUS | 12 is 63% plurality, 37% other incl. VAT rates |
| 12 | 323 | 12 ×2412, 5 ×663, 6 ×438, 5.5 ×272, 0 ×50, 18 ×23, 13.5 ×4, 12.5 ×1 | none | — | AMBIGUOUS | same shape as 11; numeric == GST 12 proves nothing |
| 13 | 24 | 18 ×233, 12.5 ×23, 13.5 ×14, 0 ×5, 5 ×3, 12 ×3, 6 ×1 | GST 18? | medium | AMBIGUOUS | 83% at 18 but VAT residue; supporting evidence only |
| 14 | 2 | 12.5 ×10, 13.5 ×8, 28 ×5 | none | — | AMBIGUOUS | VAT-era split over 23 rows, 2 items |
| 15 | 1 | 0 ×1 | none | — | UNKNOWN | single row, no signal |

- VERIFIED: 0. AMBIGUOUS: 8 (1, 2, 6, 7, 11, 12, 13, 14). UNKNOWN: 2 (4, 15).
- No TaxID is mapped to GST in this report. Numeric look-alikes (12→12, 13→?, 11→?) are NOT mappings.

## Recommendation (owner decision required)
Keep legacy codes stored verbatim with full traceability and change ONLY the display layer to show
`Legacy Tax Code N — Mapping Required` instead of a bare number, introducing no VAT option and
converting no code to GST until the owner supplies an explicit per-code mapping. Any future
`LEGACY_TAX_ID_MAPPING` must live in one place (`database/tax_structures.py`) with OLD→NEW→REASON rows.
