# Printing & PDF Document Output — Phase 5H

**Date:** 2026-09-16  
**Menu surfaces:** Sales, Purchase, Credit Note, Debit Note, Customer Receipt, Supplier Payment histories  
**Files:** `database/document_printing.py`, transaction screen modules, `test_document_printing.py`

## 1. Purpose

Provide read-only PDF output for stored pharmacy transactions. Users select an existing history record, choose **Print / PDF**, and save a paper-friendly document without re-entering data.

## 2. Supported Documents

Sales Bill, Counter Sale Bill, Purchase Invoice, Credit Note, Debit Note, Customer Receipt, and Supplier Payment are supported.

## 3. Data Source

Documents are loaded through the existing transaction DAOs and their existing item readers. Stored voucher/bill numbers, dates, times, parties, lines, quantities, amounts, remarks, batch values, expiry values, and GST fields are authoritative.

## 4. PDF Generation

`database/document_printing.py` contains one reusable renderer and document-specific generator functions. It uses a small standard-library PDF writer because no PDF package was installed in the environment. Output is a valid PDF 1.4 file.

## 5. Print Preview

The history actions provide a Save PDF workflow. The service also exposes a plain-text preview helper. A full Qt print preview can be added when PySide6 is installed; headless environments still support PDF export.

## 6. Printer Support

`print_pdf` exposes an optional PySide6 print dialog and reports a useful error when PySide6 printer support is unavailable. PDF export does not require a printer.

## 7. A4 Layout

Generated documents use a 595 x 842 point A4 media box, readable Helvetica text, consistent margins, document headings, line tables, totals, and page numbering.

## 8. Receipt Layout

Receipts and supplier payments use the same A4 renderer with compact key/value content. A future enhancement may add a narrow thermal-receipt layout without changing stored data.

## 9. Business Information

The schema has no configurable pharmacy profile. The output therefore does not invent a pharmacy name, address, phone number, GST number, or other business detail. It uses document titles and stored party information only.

## 10. Document Numbering

Printing reads the stored bill or voucher number. It never generates, increments, or changes identifiers.

## 11. Totals

Totals and adjustments are displayed from stored header values. Purchase line GST percentage and GST amount are displayed where stored. No new sales, credit-note, or debit-note GST is invented.

## 12. GST Handling

Purchase documents show stored GST percentage and GST amount. The renderer does not recalculate GST or alter transaction math. Sales and note documents contain no fabricated GST values.

## 13. Error Handling

Missing or deleted transactions raise `DocumentPrintError`. Unavailable output paths and missing optional printer support produce user-facing errors. Empty optional fields remain blank rather than being fabricated.

## 14. Read-Only Behavior

Document generation uses DAO reads only. It does not insert, update, delete, adjust stock, create ledger rows, post accounting entries, or alter balances. Repeated generation produces files only.

## 15. Testing

`test_document_printing.py` contains 75 isolated tests covering all supported documents, stored values, output paths, valid PDF structure, titles and identifiers, pagination, missing records, repeated generation, printer limitations, and database read-only invariants. Tests use a temporary SQLite database and never use `data/pharmacy.db` or MySQL.

## 16. Limitations and Future Enhancements

No PDF dependency was installed, so the current renderer is intentionally small and text-oriented. PySide6 is unavailable in the current environment, so GUI printer-dialog tests are skipped. Future work may add richer typography, logo/profile settings, thermal layouts, native Qt print preview, printer copies/page setup, and PDF text extraction validation with an approved dependency.
