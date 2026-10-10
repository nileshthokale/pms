# Phase 1 Dry Run — Item Master ONLY

- Source: `C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System\PharmaWinner202610051955.sql` (35,462,774 bytes, READ-ONLY)

## Source counts

- companymst: 1222
- unitmst: 16
- pathymst: 6
- drugmst: 147
- itemmst: 942
- itemdrugs: 402

## Target expected (required-only)

- companies: 219
- units: 14
- drugs: 137
- items: 942
- item_ingredients: 402

## References
- required companies: 219
- required units: 14 (skip unreferenced unit IDs [7, 14])
- required drugs: 137 (skip 10 unreferenced)
- skip 1003 unreferenced companies
- pathy IDs referenced: [1]

## Missing references (must all be empty)
- {"companies": [], "units": [], "pathy": [], "itemdrugs_missing_item": [], "itemdrugs_missing_drug": []}

## Duplicate item names (composite UNIQUE(item_name, unit_id))
- exact name duplicates (informational only): {"POWERGESIC": [51, 920], "CALTONVIT": [681, 869]}
- normalized name duplicates (informational only): {"POWERGESIC": [51, 920], "VITOMIN-Z": [290, 303], "CALTONVIT": [681, 869]}
- composite (name, unit) conflicts (blockers): {}

## Tax mapping (no master table in dump — all UNKNOWN)
- TaxID=1 -> '1': UNKNOWN (no tax master table in source dump; preserved verbatim)
- TaxID=2 -> '2': UNKNOWN (no tax master table in source dump; preserved verbatim)
- TaxID=4 -> '4': UNKNOWN (no tax master table in source dump; preserved verbatim)
- TaxID=6 -> '6': UNKNOWN (no tax master table in source dump; preserved verbatim)
- TaxID=7 -> '7': UNKNOWN (no tax master table in source dump; preserved verbatim)
- TaxID=11 -> '11': UNKNOWN (no tax master table in source dump; preserved verbatim)
- TaxID=12 -> '12': AMBIGUOUS-NUMERIC-OVERLAP (numerically equals a GST rate but old meaning is UNKNOWN (no tax master in dump); preserved verbatim, never converted)
- TaxID=13 -> '13': UNKNOWN (no tax master table in source dump; preserved verbatim)
- TaxID=14 -> '14': UNKNOWN (no tax master table in source dump; preserved verbatim)
- TaxID=15 -> '15': UNKNOWN (no tax master table in source dump; preserved verbatim)

## Unsupported fields
- itemmst.SellLoose (no target column; all values {"Y": 942})
- itemmst.BillCompulsory (no target column; all values {"N": 942})
- itemdrugs.ID (no target; item_ingredients.id is newly generated)
- items.category_id (always NULL in Phase 1; never invented)

## Invalid values
- {"empty_item_names": [], "negative_mrp_item_ids": [608], "negative_rate_item_ids": [], "missing_item_id_198_gap": true}

## Blockers: none

- none — internally consistent

Internally consistent: True
