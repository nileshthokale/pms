# Phase 6G - A6 Pharmacy Bill Printing

Sales Bill and Counter Sale bills print on **A6 / custom receipt paper
(105 x 148 mm, portrait)**, matching the old Pharma-WINNER pharmacy bill format
and the `BillA6 [Custom]` Canon LBP2900 profile.

## 1. A6 dimensions

| Property | Value |
| --- | --- |
| Width | 105 mm (297.64 pt) |
| Height | 148 mm (419.53 pt) |
| Orientation | Portrait |
| Scale | 100 % |
| Margins | left/right 4 mm, top/bottom 5 mm |
| Printable content area | 97 x 138 mm |

A4 (210 x 297 mm), Letter (215.9 x 279.4 mm) and Legal are **not** used for the
pharmacy receipt. Every other document in the application keeps its existing A4
layout; only the sales/counter-sale receipt moved to A6.

### Why the PDF uses 297.64 pt and not 297 pt

`QPageSize.size(QPageSize.Point)` rounds a page size to whole points and reports
297 x 420 pt, which is 104.77 x 148.17 mm - not A6. The profile therefore
computes points arithmetically (`mm x 72 / 25.4`) for the PDF media box and the
painter scaling, while the printer still receives an exact-match
`QPageSize(QSizeF(105, 148), Millimeter, ..., ExactMatch)`. Both describe the
same physical sheet.

## 2. Canon LBP2900 example

The old configuration was a Windows custom form named `BillA6 [Custom]` at
approximately 104.9 x 148.1 mm, portrait, "Match Page Size" scaling.

To reproduce it in Windows:

1. Control Panel -> Devices and Printers -> right-click the printer ->
   Printing Preferences -> Paper / Quality -> Custom.
2. Name the form `BillA6 [Custom]`.
3. Set Width `104.9 mm`, Height `148.1 mm`, Portrait, Units millimetres.
4. Set scaling to **Match Page Size** (not "Fit to Page").
5. Save as the default form for that printer.

The application does not need this form. It sends an exact 105 x 148 mm page
layout, and renders the receipt letterboxed into whatever printable rectangle the
driver reports, so the bill is neither clipped nor scaled up to A4 even if the
driver substitutes a different paper.

## 3. Windows printer handling

* Printers come from the standard Windows list via `QPrinterInfo`; no printer
  name is hard-coded anywhere in the codebase.
* The default printer is the Windows default. The user can switch printers in
  the normal `QPrintDialog`, which also provides copies and page range.
* `print_pharmacy_a6_bill()` applies the A6 `QPageLayout` before showing the
  dialog, so the dialog previews A6 rather than A4.
* Discovery helpers: `available_printers()`, `default_printer_name()`,
  `supported_page_size_mm(name)` - exported by both
  `database.pharmacy_a6_receipt` and the `database.document_printing` façade.

## 4. PDF page size

The exported PDF is written by the standard-library writer in
`database/document_printing.py` with a real A6 media box:

```
/MediaBox [0 0 297.64 419.53]
```

This is a genuine A6 PDF, not an A4 page with a small receipt drawn on it.
Tests parse the media box straight from the PDF bytes and convert back to
millimetres, asserting 105.0 x 148.0 mm with a 0.1 mm tolerance.

## 5. Bill layout

Header (only what is configured - see section 8):

```
Sales Bill
Bill No: CS-0001                              Date: 2026-09-16  Time: 10:30
--------------------------------------------------
Patient: Patient One   Customer: Customer One   Doctor: Dr Stored
QTY   UNIT      DESCRIPTION          COMP.   BATCH    EXP. DT        AMT
--------------------------------------------------
1     10x10     Paracetamol 500mg      CO      B-001    12/27        48.00
      Tablets Extended Releas...
--------------------------------------------------
Total Items                              7
Total Amount                          50.00
Bill Discount                          2.00
Round Off                              0.00
Paid Amount                           48.00
Net Amt                              48.00
--------------------------------------------------
E & O.E.
Printed from stored application data.
```

Column widths (millimetres, summing to the 97 mm content width):

| Column | Width | Notes |
| --- | --- | --- |
| QTY | 8.0 | right aligned |
| UNIT | 9.0 | ellipsized |
| DESCRIPTION | 27.0 | wraps to a second line, then ellipsized |
| COMP. | 12.0 | ellipsized |
| BATCH | 12.0 | ellipsized |
| EXP. DT | 12.0 | ellipsized |
| AMT | 17.0 | right aligned |

Text measurement uses the Helvetica advance-width table, so wrapping and
clipping are computed from real glyph widths rather than character counts. The
wrapped second line uses 5.7 pt; the body is 6.2 pt, which stays readable on a
105 mm receipt. Nothing is ever clipped mid-glyph: the layout is verified to keep
every run inside the margins.

### Totals

Only stored values are printed: `total_amount`, `discount`, `round_off`,
`paid_amount`, `net_amount` and the item count, read from `sales_invoices`.

**No sales GST is printed.** `sales_invoices` and `sales_invoice_items` have no
GST, CGST, SGST, IGST or tax-amount column, so there is nothing reliable to
print and nothing is invented. GST exists only on the purchase side
(`purchase_invoices.gst_amount`, `purchase_invoice_items.gst_percent/gst_amount`).
A per-line rate is also absent from sales items, so no "Rate" column exists.

## 6. Multi-page behaviour

| Items | A6 pages |
| --- | --- |
| 1 | 1 |
| 7 | 1 |
| 15 | 1 |
| 25 | 1 |
| 30 | 2 |
| 40 | 2 |

Text is never shrunk to fit; bills grow onto extra A6 sheets instead. On each
extra page the column heading row repeats, the document header (bill number,
date, patient) appears only on page one, and totals plus footer are held back to
the final page. Pagination reserves room for totals and footer only when the
last page needs it, so short bills are not pushed onto an extra sheet.

## 7. Printer setup and usage

* Counter Sale / Sales Bill sidebar: **Print** opens the Windows print dialog on
  A6; **Print / PDF** saves an A6 PDF. Both share one engine.
* A `Paper: A6 (105 x 148 mm)` label sits under the buttons.
* Programmatic use:

```python
from database.document_printing import (
    generate_pharmacy_a6_bill, print_pharmacy_a6_bill, a6_profile)

generate_pharmacy_a6_bill(invoice_id, r"C:\temp\bill.pdf", "Counter Sale Bill")
print_pharmacy_a6_bill(invoice_id, parent, "Counter Sale Bill")
```

## 8. Business information

**There is no pharmacy/store profile in this schema.** There is no settings or
config table, and the `companies` table is the drug-manufacturer master, not the
store. Consequently the receipt prints **no store name, address, GSTIN or
pharmacist name** - the old bill's "SHREE SAMARTH MEDICAL AND GEN STORE /
GHORPADE HOSPITAL, RAHURI" header is not reproduced, because inventing it would
put unverified business identity on a legal document.

`store_profile()` in `database/pharmacy_a6_receipt.py` is the single extension
point. Return a mapping with `name`, `address`, `gstin` and `pharmacist` keys and
the A6 layout renders them with no other change:

```python
def store_profile() -> dict[str, str]:
    return {"name": "...", "address": "...", "gstin": "...", "pharmacist": "..."}
```

`E & O.E.` is printed unconditionally as standard receipt boilerplate, not as
stored business data.

## 9. Files

| File | Role |
| --- | --- |
| `database/pharmacy_a6_receipt.py` | A6 profile, column model, layout, pagination, PDF and QPainter backends, printer helpers |
| `database/document_printing.py` | `generate_pharmacy_a6_bill`, `print_pharmacy_a6_bill`, `preview_pharmacy_a6_bill`, `a6_profile`; Sales Bill and Counter Sale route here |
| `screens/counter_sale.py` | **Print** and **Print / PDF** buttons plus the paper label |
| `test_a6_pharmacy_printing.py` | 102 tests |
| `docs/a6_pharmacy_printing.md` | This document |

## 10. Testing

```
python -m unittest test_a6_pharmacy_printing
```

102 tests covering page geometry, column widths, text measurement and wrapping,
PDF media boxes, header/party/item/total/footer content, absence of invented
GST and business identity, long item names, pagination at 1/7/15/25/30/40 items,
letterboxing into smaller device rectangles, and the read-only guarantee. All
tests use disposable temporary databases under the system temp directory;
`data/pharmacy.db` is never opened.

Print-side coverage renders the same layout through a real `QPrinter` and a real
`QPdfWriter`, both at A6, and asserts a page per receipt page.

## 11. Limitations

* **No physical printer test has been performed.** The Canon LBP2900 is not
  installed on the development machine; the only available printers are
  `OneNote (Desktop)` and `Microsoft Print to PDF`. The print path is verified
  against a real Qt print device but no paper has been fed through a printer.
  Physical verification is still required.
* Printers that reject a custom 105 x 148 mm form will print on their nearest
  supported paper. The receipt is still scaled and centred into the printable
  area, so nothing is clipped, but the sheet will not be A6.
* The PDF writer embeds the standard-14 Helvetica/Helvetica-Bold faces and
  encodes text as WinAnsi. Non-latin item names are replaced rather than
  rendered.
* No `QPrintPreviewWidget` preview dialog is wired up; the on-screen preview is
  plain text via `preview_pharmacy_a6_bill()`.
* Only Sales Bill and Counter Sale use A6. Purchase Invoice, Credit Note, Debit
  Note, Customer Receipt, Supplier Payment, Cash Book, Bank Book and Day End are
  unchanged on A4.

## 12. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Bill prints on A4 | The driver ignored the custom form. Add the `BillA6 [Custom]` form (section 2) and set scaling to *Match Page Size*. |
| Text is cut off at the right edge | The driver's printable width is smaller than the paper. The receipt scales down automatically; check the printer's non-printable margins. |
| Bill is too small on the sheet | Expected when the driver reports a larger page: the receipt is centred and scaled uniformly rather than stretched. |
| Nothing prints | Confirm the printer is set as the Windows default and is online. |
| Extra blank page | The driver adds a trailing page for a partly used sheet. On a real printer this is normal. |