# Item Master GST Tax Structure

The Item Master **Tax Structure** control is a fixed dropdown offering exactly
five GST options. Display text is descriptive; every consumer reads the
internal value — the bare GST rate as a string — which is also what is stored.

## The five options

| Display | Internal value |
|---|---|
| `GST @ 5% (CGST-2.5% & SGST-2.5%)` | `5` |
| `GST @ 12% (CGST-6% & SGST-6%)` | `12` |
| `GST @ 18% (CGST-9% & SGST-9%)` | `18` |
| `GST @ 28% (CGST-14% & SGST-14%)` | `28` |
| `ZERO GST` | `0` |

The definitions live in `database/tax_structures.py` and are the single source
of truth for both the dropdown and the Purchase screen.

## Storage

`items.tax_structure` remains a plain `TEXT` column. **No schema change, no
lookup table, no CHECK constraint** — a new item's value is written as the bare
rate (`"5"`, `"0"`, …), never the display label.

## New items

The dropdown contains exactly the five options above and nothing else — no
`VAT @ 12.50%`, `NO-TAX` or other legacy label is offered. A new item defaults
to **ZERO GST**, so creating an item never silently implies a tax liability; no
non-zero rate is ever pre-selected.

A new item can only be saved with `0`, `5`, `12`, `18` or `28`. Arbitrary text
cannot reach the database through the normal UI.

## Existing imported items — never rewritten

Imported items do **not** hold labels like `VAT @ 12.50%`. They hold **legacy
numeric tax codes** copied verbatim from the old `itemmst.TaxID` column (see
`legacy_data_migration.md`). The imported values in the live database are:

```
'12' 326   '6' 305   '11' 213   '2' 43   '13' 24
'7' 18     '1' 5     '14' 2     '4' 1    '15' 1
```

When such an item is opened for editing:

- the stored value is kept as-is and shown as an extra, clearly marked entry
  (`Legacy Tax Code 11 — Mapping Required`) alongside the five GST options;
- saving an unrelated field change (MRP, reorder level, …) leaves the tax value
  **and its provenance byte-for-byte unchanged** — editing a legacy item is
  never blocked by tax;
- nothing is mass-updated. There is no migration, no backfill and no rewrite.

A user can still deliberately move a legacy item onto one of the five GST rates;
that is an explicit choice, saved only when the user saves the item. Because the
legacy code no longer describes the stored value, that deliberate conversion
clears `legacy_tax_id`.

### Provenance — `items.legacy_tax_id`

`items.legacy_tax_id` is a nullable `INTEGER` recording the old Pharma-WINNER
`TaxID` a value came from:

| Stored value | `legacy_tax_id` | Meaning |
|---|---|---|
| `0` `5` `12` `18` `28` | `NULL` | a genuine new-system GST selection |
| any | non-`NULL` | the legacy code preserved for audit |

A later owner-approved pass (`tools/apply_gst_only_tax_mapping.py`) rewrote
`tax_structure` to GST rates for the imported items using GST-era evidence,
leaving `legacy_tax_id` untouched. So the two fields can disagree, and the
**stored value decides what is displayed**:

- a genuine GST rate shows its full GST name — whether it is a new selection or
  an imported item the owner remapped;
- an unmapped legacy code shows `Legacy Tax Code N — Mapping Required`;
- EMPTY (a VAT-only imported item) shows blank.

`database/tax_structures.resolve_tax_display()` implements that rule for the
grid. Called without a provenance argument it defers to `display_for()`, which
is deliberately stricter: with no provenance information at all a **known**
legacy code wins over a numeric GST coincidence, so a bare `12` is flagged
rather than shown as GST.

### One unavoidable ambiguity

Legacy code `'12'` is numerically identical to GST 12%. A value of `'12'` whose
provenance is `NULL` is a genuine GST 12% selection and displays as
`GST @ 12% (CGST-6% & SGST-6%)`; the same value called through `display_for()`,
which has no provenance to consult, displays the mapping flag instead. The
stored value round-trips unchanged in every case, so **no data is rewritten** —
only the label is an interpretation. The original tax master was not present in
the imported dump, so the true historical rate for the legacy code is not
recoverable, and may not be assumed from the numeric coincidence.

## Purchase compatibility

`PurchaseInvoiceDialog` used to regex the first digit out of the tax string
(`if "GST" in tax: re.search(r"(\d+)", tax)`). It now calls
`tax_structures.rate_percent()`, which:

- returns the rate for the five supported GST values, pre-filling the per-line
  `GST%` box as before;
- returns `None` for a legacy code, so **no GST is invented** for an imported
  item — identical to the previous behaviour, because a bare code never
  contained the string `GST`.

`ZERO GST` pre-fills an explicit `0`.

The `GST%` box remains per-line and fully user-overridable: a value the user
has already typed is never overwritten. The GST arithmetic
(`amount × gst% / 100`) is untouched, and stored
`purchase_invoice_items.gst_percent` / `gst_amount` values are unaffected.

## What this feature does not touch

The GST Report reads `purchase_invoice_items.gst_percent` — the value recorded
on the transaction line — and never reads `items.tax_structure`, so historical
GST report records are unaffected. Sales have no GST fields at all. Stock,
accounting, the posting engine, Hold Bill, permissions, the financial year and
the legacy migration are all untouched.

## Tests

`test_item_tax_structure.py` — 36 focused tests covering the five options and
their exact text, internal values, the ZERO GST default, saving and editing at
every rate, rejection of unsupported values, legacy-code preservation, no mass
update, Purchase pre-fill and compatibility, and data-safety checks that the
real database is unmodified. All tests use disposable temporary databases;
`data/pharmacy.db` is never a test target.