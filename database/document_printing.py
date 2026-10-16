"""Read-only PDF document generation for stored pharmacy transactions.

The renderer uses only the application's SQLite DAOs and a small standard-library
PDF writer. It never inserts, updates, deletes, posts, or recalculates a
transaction. PySide6 printer integration is optional and intentionally isolated
from PDF generation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from database import pharmacy_a6_receipt as a6
from database.credit_note_dao import CreditNoteDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.debit_note_dao import DebitNoteDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.supplier_payment_dao import SupplierPaymentDAO


class DocumentPrintError(ValueError):
    """Raised when a stored document cannot be loaded or written."""



def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _money(value: Any) -> str:
    try:
        return f"{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return _text(value)


def _purchase_display_bill_no(value: Any) -> str:
    """Display-only Bill/Voucher number without the financial-year prefix.

    Purchase vouchers are stored with a financial-year prefix such as
    ``2026-2027-Credit-250`` (or, in simplified form, ``2026-2027-123``).
    This helper strips only the leading ``YYYY-YYYY-`` prefix and returns
    the remainder (``Credit-250`` / ``123``) for the Purchase Report
    printout.  Values without that prefix (``PV-0001``, ``INV-001``,
    plain numbers) are returned unchanged.  Stored data is never altered.
    """
    import re

    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    match = re.match(r"^\d{4}-\d{4}-(.+)$", text)
    if match:
        remainder = match.group(1).strip()
        if remainder:
            return remainder
    return text


def _escape(value: Any) -> str:
    return _text(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _require(record: dict | None, label: str) -> dict:
    if not record:
        raise DocumentPrintError(f"{label} was not found or has been deleted.")
    return record


def _output_path(output_path: str | os.PathLike[str] | None, title: str, identifier: str) -> Path:
    if output_path is None:
        output_path = Path.cwd() / f"{title.lower().replace(' ', '_')}_{identifier}.pdf"
    path = Path(output_path)
    if path.suffix.casefold() != ".pdf":
        path = path.with_suffix(".pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _sales_data(invoice_id: int) -> tuple[dict, list[dict]]:
    return _require(SalesDAO.get_by_id(invoice_id), "Sales bill"), SalesDAO.get_invoice_items(invoice_id)


def _purchase_data(invoice_id: int) -> tuple[dict, list[dict]]:
    return _require(PurchaseDAO.get_by_id(invoice_id), "Purchase invoice"), PurchaseDAO.get_invoice_items(invoice_id)


def _credit_data(note_id: int) -> tuple[dict, list[dict]]:
    return _require(CreditNoteDAO.get_by_id(note_id), "Credit note"), CreditNoteDAO.get_invoice_items(note_id)


def _debit_data(note_id: int) -> tuple[dict, list[dict]]:
    return _require(DebitNoteDAO.get_by_id(note_id), "Debit note"), DebitNoteDAO.get_items(note_id)


def _receipt_data(receipt_id: int) -> tuple[dict, list[dict]]:
    return _require(CustomerReceiptDAO.get_by_id(receipt_id), "Customer receipt"), []


def _payment_data(payment_id: int) -> tuple[dict, list[dict]]:
    return _require(SupplierPaymentDAO.get_by_id(payment_id), "Supplier payment"), []


def _header(title: str, record: dict) -> list[str]:
    identifier = record.get("bill_no") or record.get("voucher_no") or ""
    date = record.get("sale_date") or record.get("voucher_date") or record.get("receipt_date") or record.get("payment_date") or ""
    time = record.get("sale_time") or record.get("voucher_time") or record.get("receipt_time") or record.get("payment_time") or ""
    lines = [title, f"Document No: {identifier}", f"Date: {date}    Time: {time}"]
    party = record.get("customer_name") or record.get("supplier_name")
    if party is not None:
        lines.append(f"Party: {party}")
    return lines


def _document_lines(title: str, record: dict, items: list[dict]) -> list[str]:
    lines = _header(title, record)
    if title in {"Sales Bill", "Counter Sale Bill"}:
        lines.extend([
            f"Sale Type: {_text(record.get('sale_type'))}",
            f"Patient: {_text(record.get('patient_name'))}",
            f"Doctor: {_text(record.get('doctor_name'))}",
            "",
            "Item | Pack | Location | Batch | Expiry | MRP | Qty | Discount | Amount",
        ])
        for item in items:
            lines.append(" | ".join([
                _text(item.get("item_name")), _text(item.get("pack_size")), _text(item.get("location")),
                _text(item.get("batch_no")), _text(item.get("expiry")), _money(item.get("mrp")),
                _text(item.get("sale_qty")), _money(item.get("discount_amount")), _money(item.get("amount")),
            ]))
        lines.extend([
            "", f"Total Items: {len(items)}", f"Total Amount: {_money(record.get('total_amount'))}",
            f"Bill Discount: {_money(record.get('discount'))}", f"Round Off: {_money(record.get('round_off'))}",
            f"Paid Amount: {_money(record.get('paid_amount'))}", f"Net Amount: {_money(record.get('net_amount'))}",
        ])
    elif title == "Purchase Invoice":
        lines.extend([
            f"Invoice No: {_text(record.get('invoice_no'))}", f"Invoice Date: {_text(record.get('invoice_date'))}",
            f"Purchase Type: {_text(record.get('purchase_type'))}", "",
            "Item | Pack | Pay Qty | Free Qty | Batch | Expiry | Rate | MRP | Discount | GST% | GST Amt | Amount",
        ])
        for item in items:
            lines.append(" | ".join([
                _text(item.get("item_name")), _text(item.get("pack_size")), _text(item.get("pay_qty")),
                _text(item.get("free_qty")), _text(item.get("batch_no")), _text(item.get("expiry")),
                _money(item.get("rate")), _money(item.get("mrp")), _money(item.get("discount")),
                _money(item.get("gst_percent")), _money(item.get("gst_amount")), _money(item.get("amount")),
            ]))
        lines.extend([
            "", f"Total Items: {len(items)}", f"Taxable/Line Amount: {_money(record.get('total_amount'))}",
            f"GST Amount: {_money(record.get('gst_amount'))}", f"Bill Discount: {_money(record.get('bill_discount'))}",
            f"Debit Note Amount: {_money(record.get('debit_note_amount'))}", f"Other Amount: {_money(record.get('other_amount'))}",
            f"Paid Amount: {_money(record.get('paid_amount'))}", f"Round Off: {_money(record.get('round_off'))}",
            f"Net Amount: {_money(record.get('net_amount'))}",
        ])
    elif title in {"Credit Note", "Debit Note"}:
        lines.extend([
            f"Note Date: {_text(record.get('cn_date') or record.get('dn_date'))}",
            f"Note Type: {_text(record.get('cn_type') or record.get('dn_type'))}", "",
            "Item | Pack | Batch | Expiry | Rate | MRP | Return Qty | Less Amount | Amount | Reason",
        ])
        for item in items:
            lines.append(" | ".join([
                _text(item.get("item_name")), _text(item.get("pack_size")), _text(item.get("batch_no")),
                _text(item.get("expiry")), _money(item.get("rate")), _money(item.get("mrp")),
                _text(item.get("return_qty")), _money(item.get("less_amount")), _money(item.get("amount")),
                _text(item.get("return_reason")),
            ]))
        lines.extend(["", f"Total Amount: {_money(record.get('total_amount'))}", f"Ledger Amount: {_money(record.get('ledger_amount'))}"])
    elif title == "Customer Receipt":
        lines.extend([
            f"Payment Mode: {_text(record.get('receipt_mode'))}", f"Amount: {_money(record.get('amount'))}",
            f"Reference No: {_text(record.get('reference_no'))}",
        ])
    elif title == "Supplier Payment":
        lines.extend([
            f"Payment Mode: {_text(record.get('payment_mode'))}", f"Amount: {_money(record.get('amount'))}",
            f"Reference No: {_text(record.get('reference_no'))}",
        ])
    elif title == "Cash Book":
        lines.extend(["", "Date | Reference | Particulars | Debit | Credit | Balance"])
        for item in items:
            lines.append(_text(item.get("item_name")))
    elif title == "Bank Book":
        lines.extend(["", "Date | Reference | Particulars | Debit | Credit | Balance"])
        for item in items:
            lines.append(_text(item.get("item_name")))
    elif title == "Day End":
        lines.append("")
        for item in items:
            lines.append(_text(item.get("item_name")))
    if record.get("remarks"):
        lines.append(f"Remarks: {record['remarks']}")
    lines.append("Printed from stored application data. No transaction data was changed.")
    return lines


def _pdf_bytes(lines: list[str], title: str) -> bytes:
    page_capacity = 48
    pages = [lines[i:i + page_capacity] for i in range(0, max(len(lines), 1), page_capacity)]
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for page_index, page_lines in enumerate(pages, 1):
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        content_commands = ["BT", "/F1 10 Tf", "50 800 Td", f"({_escape(title)}) Tj", "0 -18 Td"]
        for line in page_lines:
            content_commands.append(f"({_escape(line[:180])}) Tj")
            content_commands.append("0 -14 Td")
        content_commands.extend([f"(Page {page_index} of {len(pages)}) Tj", "ET"])
        stream = "\n".join(content_commands).encode("latin-1", "replace")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output)); output.extend(f"{number} 0 obj\n".encode()); output.extend(obj); output.extend(b"\nendobj\n")
    xref = len(output); output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def generate_document(title: str, record: dict, items: list[dict], output_path: str | os.PathLike[str] | None = None) -> str:
    path = _output_path(output_path, title, record.get("bill_no") or record.get("voucher_no") or str(record.get("id")))
    try:
        path.write_bytes(_pdf_bytes(_document_lines(title, record, items), title))
    except OSError as exc:
        raise DocumentPrintError(f"Could not create PDF at {path}: {exc}") from exc
    return str(path)


def _companywise_text_width_pt(text: Any, size_pt: float, bold: bool = False) -> float:
    """Width of ``text`` in PDF points for the companywise table."""
    try:
        mm = a6.text_width_mm(str(text), float(size_pt), bold=bool(bold))
        return float(mm) * float(a6.PT_PER_MM)
    except Exception:
        return len(str(text)) * float(size_pt) * 0.55


def _companywise_fit(text: Any, max_pt: float, size_pt: float, bold: bool = False) -> str:
    """Truncate ``text`` with '...' so it never overflows its column."""
    s = _text(text).replace("\n", " ").strip()
    if not s:
        return ""
    if _companywise_text_width_pt(s, size_pt, bold) <= max_pt:
        return s
    ell = "..."
    if _companywise_text_width_pt(ell, size_pt, bold) > max_pt:
        return ""
    for cut in range(len(s) - 1, 0, -1):
        cand = s[:cut].rstrip() + ell
        if _companywise_text_width_pt(cand, size_pt, bold) <= max_pt:
            return cand
    return ""


def _companywise_fmt_mrp(value: Any) -> str:
    try:
        return f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return _text(value)


def _companywise_fmt_qty(value: Any) -> str:
    try:
        return f"{round(float(value or 0), 2):g}"
    except (TypeError, ValueError):
        return _text(value)


def _companywise_fmt_amt(value: Any) -> str:
    try:
        return f"{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return _text(value)


def _companywise_company_name(filter_summary: Any, rows: list[dict]) -> str:
    """Company label for the header without changing any filter logic."""
    import re

    if filter_summary:
        match = re.search(r"Company\s*:\s*([^|]+)", str(filter_summary))
        if match:
            name = match.group(1).strip()
            if name and name.lower() not in {"", "all", "all companies", "all items", "none"}:
                return name
    names = sorted({str(r.get("company_name") or "").strip() for r in rows if str(r.get("company_name") or "").strip()})
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        joined = ", ".join(names)
        return joined[:80] + ("..." if len(joined) > 80 else "")
    return "All Companies"


def _companywise_period(rows: list[dict]) -> tuple[str | None, str | None]:
    """Date range from the already-filtered rows (no re-query, no recalc)."""
    dates = sorted({str(r.get("sale_date") or "").strip() for r in rows if str(r.get("sale_date") or "").strip()})

    def _fmt(iso: str) -> str:
        parts = iso.split("-")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return iso

    if not dates:
        return None, None
    return _fmt(dates[0]), _fmt(dates[-1])


def _billwise_bills(rows: list[dict]) -> list[dict]:
    """Group already-filtered rows by bill (display-only, no recalculation).

    Each bill keeps its own stored lines in their original order; nothing is
    combined across bills.  Bill totals are plain sums of the bill's stored
    line values, so the printed rows always reconcile with the data.
    """

    def _fnum(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    bills: dict[Any, dict] = {}
    for r in rows:
        inv = r.get("invoice_id")
        if inv is not None:
            key: Any = ("id", inv)
        else:
            key = ("bill", str(r.get("bill_no") or "").strip())
        bill = bills.get(key)
        if bill is None:
            bill = {
                "bill_no": str(r.get("bill_no") or "").strip(),
                "sale_date": str(r.get("sale_date") or "").strip(),
                "customer_name": str(r.get("customer_name") or "").strip(),
                "patient_name": str(r.get("patient_name") or "").strip(),
                "lines": [], "qty": 0.0, "discount": 0.0, "amount": 0.0,
            }
            bills[key] = bill
        line = {
            "item_name": str(r.get("item_name") or "").strip() or "(Unknown Item)",
            "batch_no": str(r.get("batch_no") or "").strip(),
            "mrp": _fnum(r.get("mrp")),
            "qty": _fnum(r.get("sale_qty")),
            "discount": _fnum(r.get("discount_amount")),
            "amount": _fnum(r.get("amount")),
        }
        bill["lines"].append(line)
        bill["qty"] += line["qty"]
        bill["discount"] += line["discount"]
        bill["amount"] += line["amount"]
    ordered = sorted(
        bills.values(),
        key=lambda b: (str(b["sale_date"]), str(b["bill_no"])),
    )
    for b in ordered:
        b["qty"] = round(b["qty"], 2)
        b["discount"] = round(b["discount"], 2)
        b["amount"] = round(b["amount"], 2)
    return ordered


def _billwise_pdf_bytes(
    pages: list[list[dict]],
    store_name: str,
    store_address: str,
    period_from: str | None,
    period_to: str | None,
    financial_year: str,
    company_name: str,
) -> bytes:
    """Minimal portrait-A4 writer for the Daily Sales Report table."""
    PAGE_W, PAGE_H = 595.0, 842.0
    ML, MT, MB = 36.0, 36.0, 36.0
    CONTENT_X0 = ML
    CONTENT_W = PAGE_W - ML - 36.0
    COL_WIDTHS = [30.0, 175.0, 80.0, 60.0, 45.0, 60.0, 73.0]
    COL_X: list[float] = []
    _x = CONTENT_X0
    for _w in COL_WIDTHS:
        COL_X.append(_x)
        _x += _w
    COL_RIGHT = CONTENT_X0 + CONTENT_W
    HEADS = ["SrNo", "Item Name", "Batch No", "MRP", "Qty", "Discount", "Amount"]
    HEADER_H, BILLHEAD_H, DETAIL_H, BILLTOTAL_H, GRAND_H, EMPTY_H = 17.0, 14.0, 13.5, 13.5, 15.0, 16.0
    HEADER_FONT, BODY_FONT, GRAND_FONT, BILLHEAD_FONT = 8.0, 7.5, 8.0, 7.5

    def _centered_x(text: str, size: float, bold: bool) -> float:
        w = _companywise_text_width_pt(text, size, bold)
        return CONTENT_X0 + max(0.0, (CONTENT_W - w) / 2.0)

    def _cell_x(col: int, text: str, size: float, bold: bool, align: str) -> float:
        max_w = COL_WIDTHS[col] - 6.0
        fitted = _companywise_fit(text, max_w, size, bold)
        w = _companywise_text_width_pt(fitted, size, bold)
        if align == "right":
            return COL_X[col] + COL_WIDTHS[col] - 3.0 - w
        if align == "center":
            return COL_X[col] + max(3.0, (COL_WIDTHS[col] - w) / 2.0)
        return COL_X[col] + 3.0

    def _fitted(col: int, text: str, size: float, bold: bool) -> str:
        return _companywise_fit(text, COL_WIDTHS[col] - 6.0, size, bold)

    def _fmt_date(iso: str) -> str:
        parts = str(iso).split("-")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return str(iso)

    def _bill_head_text(bill_no: str, sale_date: str, patient: str) -> str:
        parts: list[str] = []
        if bill_no:
            parts.append(f"Bill No: {bill_no}")
        if sale_date:
            parts.append(f"Date: {_fmt_date(sale_date)}")
        if patient:
            parts.append(f"Patient: {patient}")
        return "     ".join(parts) if parts else "Bill"

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    page_ids: list[int] = []
    total_pages = max(len(pages), 1)
    for page_index, page_rows in enumerate(pages, 1):
        is_first = page_index == 1
        commands: list[str] = []
        y_top = PAGE_H - MT
        if is_first:
            y = y_top
            if store_name:
                txt = _companywise_fit(store_name, CONTENT_W, 13.5, True)
                commands.append(
                    f"BT /F2 13.50 Tf 1 0 0 1 {_centered_x(txt, 13.5, True):.2f} {y - 11.50:.2f} Tm ({_escape(txt)}) Tj ET"
                )
                y -= 17.0
            if store_address:
                txt = _companywise_fit(store_address, CONTENT_W, 8.5, False)
                commands.append(
                    f"BT /F1 8.50 Tf 1 0 0 1 {_centered_x(txt, 8.5, False):.2f} {y - 7.50:.2f} Tm ({_escape(txt)}) Tj ET"
                )
                y -= 11.0
            title = "DAILY SALES REPORT"
            commands.append(
                f"BT /F2 11.00 Tf 1 0 0 1 {_centered_x(title, 11.0, True):.2f} {y - 10.00:.2f} Tm ({_escape(title)}) Tj ET"
            )
            y -= 15.0
            if period_from and period_to:
                period_txt = f"From : {period_from}    To : {period_to}"
            elif period_from:
                period_txt = f"Date : {period_from}"
            else:
                period_txt = f"Financial Year : {_text(financial_year)}"
            period_txt = _companywise_fit(period_txt, CONTENT_W, 8.5, False)
            commands.append(
                f"BT /F1 8.50 Tf 1 0 0 1 {_centered_x(period_txt, 8.5, False):.2f} {y - 7.50:.2f} Tm ({_escape(period_txt)}) Tj ET"
            )
            y -= 11.0
            company_txt = _companywise_fit(f"Company : {company_name}", CONTENT_W, 8.5, True)
            commands.append(
                f"BT /F2 8.50 Tf 1 0 0 1 {_centered_x(company_txt, 8.5, True):.2f} {y - 7.50:.2f} Tm ({_escape(company_txt)}) Tj ET"
            )
            y -= 11.0
            y -= 7.0
            table_top = y
        else:
            table_top = y_top
        # ── table geometry for this page ──
        heights = {"billhead": BILLHEAD_H, "detail": DETAIL_H, "billtotal": BILLTOTAL_H, "grand": GRAND_H, "empty": EMPTY_H}
        row_tops: list[tuple[dict, float, float]] = []
        cursor = table_top - HEADER_H
        row_tops.append(({"kind": "header"}, table_top, HEADER_H))
        for row in page_rows:
            h = heights.get(str(row.get("kind")), DETAIL_H)
            top = cursor
            row_tops.append((row, top, h))
            cursor -= h
        table_bottom = cursor

        def _h_line(y: float, w: float = 0.5) -> None:
            commands.append(f"{w:.2f} w {CONTENT_X0:.2f} {y:.2f} m {COL_RIGHT:.2f} {y:.2f} l S")

        def _v_line(x: float, y0: float, y1: float, w: float = 0.5) -> None:
            commands.append(f"{w:.2f} w {x:.2f} {y1:.2f} m {x:.2f} {y0:.2f} l S")

        _h_line(table_top, 0.7)
        _h_line(table_top - HEADER_H, 0.7)
        for _row, _top, _h in row_tops[1:]:
            if str(_row.get("kind")) != "grand":
                _h_line(_top - _h, 0.5)
        # Verticals run only through the table grid, so the full-width bill
        # header bands and the grand-total footer box stay clean rectangles.
        GRID_KINDS = {"header", "detail", "billtotal"}
        run_top: float | None = None
        run_bottom: float | None = None

        def _close_run() -> None:
            nonlocal run_top, run_bottom
            if run_top is not None and run_bottom is not None:
                for _cx in COL_X[1:] + [COL_RIGHT]:
                    _v_line(_cx, run_top, run_bottom, 0.5)
                _v_line(CONTENT_X0, run_top, run_bottom, 0.7)
            run_top = None
            run_bottom = None

        for _row, _top, _h in row_tops:
            if str(_row.get("kind")) in GRID_KINDS:
                if run_top is None:
                    run_top = _top
                run_bottom = _top - _h
            else:
                _close_run()
        _close_run()
        # ── column headings ──
        head_base = table_top - HEADER_H + 6.0
        for col, head in enumerate(HEADS):
            align = "left" if col == 1 else ("right" if col >= 3 else "center")
            txt = _fitted(col, head, HEADER_FONT, True)
            commands.append(
                f"BT /F2 {HEADER_FONT:.2f} Tf 1 0 0 1 {_cell_x(col, txt, HEADER_FONT, True, align):.2f} {head_base:.2f} Tm ({_escape(txt)}) Tj ET"
            )
        # ── body rows ──
        for row, top, h in row_tops[1:]:
            kind = str(row.get("kind"))
            bottom = top - h
            if kind == "billhead":
                txt = _companywise_fit(
                    _bill_head_text(str(row.get("bill_no") or ""), str(row.get("sale_date") or ""), str(row.get("patient") or "")),
                    CONTENT_W - 6.0, BILLHEAD_FONT, True,
                )
                if txt:
                    commands.append(
                        f"BT /F2 {BILLHEAD_FONT:.2f} Tf 1 0 0 1 {CONTENT_X0 + 3.0:.2f} {bottom + 4.5:.2f} Tm ({_escape(txt)}) Tj ET"
                    )
            elif kind == "detail":
                cells: list[str] = row.get("cells", [""] * 7)
                aligns = ["center", "left", "center", "right", "right", "right", "right"]
                base = bottom + 4.0
                for col in range(7):
                    txt = _fitted(col, cells[col] if col < len(cells) else "", BODY_FONT, False)
                    if not txt:
                        continue
                    commands.append(
                        f"BT /F1 {BODY_FONT:.2f} Tf 1 0 0 1 {_cell_x(col, txt, BODY_FONT, False, aligns[col]):.2f} {base:.2f} Tm ({_escape(txt)}) Tj ET"
                    )
            elif kind == "billtotal":
                base = bottom + 4.0
                span_w = sum(COL_WIDTHS[:4]) - 6.0
                label = _companywise_fit("Bill Total", span_w, BODY_FONT, True)
                lw = _companywise_text_width_pt(label, BODY_FONT, True)
                lx = COL_X[0] + sum(COL_WIDTHS[:4]) - 3.0 - lw
                commands.append(
                    f"BT /F2 {BODY_FONT:.2f} Tf 1 0 0 1 {lx:.2f} {base:.2f} Tm ({_escape(label)}) Tj ET"
                )
                for col, key in ((4, "qty_str"), (5, "disc_str"), (6, "amt_str")):
                    txt = _fitted(col, row.get(key, ""), BODY_FONT, True)
                    if not txt:
                        continue
                    commands.append(
                        f"BT /F2 {BODY_FONT:.2f} Tf 1 0 0 1 {_cell_x(col, txt, BODY_FONT, True, 'right'):.2f} {base:.2f} Tm ({_escape(txt)}) Tj ET"
                    )
            elif kind == "grand":
                commands.append(
                    f"0.80 w {CONTENT_X0:.2f} {bottom:.2f} {CONTENT_W:.2f} {h:.2f} re S"
                )
                total_txt = _companywise_fit(
                    f"Grand Total: {row.get('amt_str', '')}", CONTENT_W - 8.0, GRAND_FONT, True)
                total_w = _companywise_text_width_pt(total_txt, GRAND_FONT, True)
                commands.append(
                    f"BT /F2 {GRAND_FONT:.2f} Tf 1 0 0 1 {COL_RIGHT - 4.0 - total_w:.2f} {bottom + 5.0:.2f} Tm ({_escape(total_txt)}) Tj ET"
                )
            elif kind == "empty":
                msg = _companywise_fit(row.get("message", "No sales found."), CONTENT_W - 12.0, 8.0, False)
                base = bottom + 5.0
                commands.append(
                    f"BT /F1 8.00 Tf 1 0 0 1 {_centered_x(msg, 8.0, False):.2f} {base:.2f} Tm ({_escape(msg)}) Tj ET"
                )
        stamp = f"Page {page_index} of {total_pages}"
        commands.append(
            f"BT /F1 7.00 Tf 1 0 0 1 {_centered_x(stamp, 7.0, False):.2f} {(MB - 12.0):.2f} Tm ({_escape(stamp)}) Tj ET"
        )
        stream = "\n".join(commands).encode("latin-1", "replace")
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def generate_daily_sales_report_pdf(
    rows: list[dict], summary: dict, financial_year: str, filter_summary: str,
    output_path: str | os.PathLike[str] | None = None,
) -> str:
    """Create a read-only, portrait Daily Sales Report PDF.

    This deliberately receives already-filtered report rows rather than
    querying the database.  Every bill prints as its own section with its
    stored item lines and its own bill total, followed by a bordered grand
    total summed from the displayed stored values.
    """
    path = _output_path(output_path, "sales_report", str(financial_year).replace(" ", "_"))
    try:
        profile = a6.store_profile()
    except Exception:
        profile = {}
    store_name = str(profile.get("name") or "").strip()
    store_address = str(profile.get("address") or "").strip()
    company_name = _companywise_company_name(filter_summary, rows)
    period_from, period_to = _companywise_period(rows)
    bills = _billwise_bills(rows)
    # ── build drawable rows (bill header + lines + bill total) ──
    bill_groups: list[list[dict]] = []
    serial = 0
    for bill in bills:
        group: list[dict] = [{
            "kind": "billhead", "bill_no": bill["bill_no"],
            "sale_date": bill["sale_date"],
            "patient": bill["patient_name"] or "WALKIN",
        }]
        for line in bill["lines"]:
            serial += 1
            group.append({"kind": "detail", "cells": [
                str(serial),
                str(line["item_name"]),
                str(line["batch_no"]),
                _companywise_fmt_mrp(line["mrp"]),
                _companywise_fmt_qty(line["qty"]),
                _companywise_fmt_amt(line["discount"]),
                _companywise_fmt_amt(line["amount"]),
            ]})
        group.append({
            "kind": "billtotal",
            "qty_str": _companywise_fmt_qty(bill["qty"]),
            "disc_str": _companywise_fmt_amt(bill["discount"]),
            "amt_str": _companywise_fmt_amt(bill["amount"]),
        })
        bill_groups.append(group)
    grand_qty = round(sum(b["qty"] for b in bills), 2) if bills else 0.0
    grand_disc = round(sum(b["discount"] for b in bills), 2) if bills else 0.0
    grand_amt = round(sum(b["amount"] for b in bills), 2) if bills else 0.0
    grand_row = {
        "kind": "grand",
        "qty_str": _companywise_fmt_qty(grand_qty),
        "disc_str": _companywise_fmt_amt(grand_disc),
        "amt_str": _companywise_fmt_amt(grand_amt),
    }
    # ── paginate (keep each bill together when possible) ──
    BILLHEAD_H, DETAIL_H, BILLTOTAL_H, GRAND_H, EMPTY_H = 14.0, 13.5, 13.5, 15.0, 16.0
    FIRST_CAP = 667.0
    OTHER_CAP = 739.0

    def _row_h(row: dict) -> float:
        kind = str(row.get("kind"))
        if kind == "billhead":
            return BILLHEAD_H
        if kind == "billtotal":
            return BILLTOTAL_H
        if kind == "grand":
            return GRAND_H
        if kind == "empty":
            return EMPTY_H
        return DETAIL_H

    pages: list[list[dict]] = []
    if not bill_groups:
        empty = [{"kind": "empty", "message": "No records found."}]
        if EMPTY_H + GRAND_H <= FIRST_CAP:
            pages = [empty + [grand_row]]
        else:
            pages = [empty, [grand_row]]
    else:
        current: list[dict] = []
        remaining = FIRST_CAP
        for group in bill_groups:
            grp_h = sum(_row_h(r) for r in group)
            if grp_h <= remaining:
                current.extend(group)
                remaining -= grp_h
                continue
            if current:
                pages.append(current)
                current = []
                remaining = OTHER_CAP
            if grp_h <= remaining:
                current.extend(group)
                remaining -= grp_h
            else:
                for r in group:
                    rh = _row_h(r)
                    if rh > remaining:
                        if current:
                            pages.append(current)
                        current = []
                        remaining = OTHER_CAP
                    current.append(r)
                    remaining -= rh
        if GRAND_H > remaining:
            if current:
                pages.append(current)
            current = []
            remaining = OTHER_CAP
        current.append(grand_row)
        pages.append(current)
    try:
        path.write_bytes(_billwise_pdf_bytes(
            pages, store_name, store_address, period_from, period_to,
            str(financial_year), company_name,
        ))
    except OSError as exc:
        raise DocumentPrintError(f"Could not create PDF at {path}: {exc}") from exc
    return str(path)




def _purchase_is_company_only(filter_summary: Any, company_name: Any) -> bool:
    """True when only a Company Name was entered (other filters empty).

    Detected from the top filter info: ``Company:`` present while none of
    Supplier/Item/Invoice/Voucher/Batch are present.  Print routing only;
    filtering itself stays in the DAO/screen.
    """
    text = str(filter_summary or "")
    if str(company_name or "").strip():
        has_company = True
    else:
        has_company = "Company:" in text
    if not has_company:
        return False
    for key in ("Supplier:", "Item:", "Invoice:", "Voucher:", "Batch:"):
        if key in text:
            return False
    return True


def _purchase_company_name(
    filter_summary: Any, rows: list[dict], company_name: Any = "",
) -> str:
    """Selected company display name for the companywise header (no query)."""
    import re

    if str(company_name or "").strip():
        return str(company_name).strip()
    match = re.search(r"Company\s*:\s*([^|]+)", str(filter_summary or ""))
    if match:
        name = match.group(1).strip()
        if name:
            return name
    names = sorted({
        str(r.get("company_name") or "").strip()
        for r in rows if str(r.get("company_name") or "").strip()
    })
    if len(names) == 1:
        return names[0]
    return ""


def _purchase_vh_type(row: dict) -> str:
    """Voucher type for the companywise VhType column (display only)."""
    import re

    stored = str(row.get("purchase_type") or "").strip()
    if stored:
        return stored
    voucher = str(row.get("voucher_no") or "").strip()
    match = re.match(r"^\d{4}-\d{4}-([A-Za-z ]+)-.+?$", voucher)
    if match:
        return match.group(1).strip()
    return ""


def _purchase_vh_no(row: dict) -> str:
    """Voucher number for the companywise VhNo column (display only).

    For stored ``YYYY-YYYY-Type-Seq`` vouchers (e.g.
    ``2026-2027-Credit-250``) shows only the sequential part (``250``),
    since the type already has its own VhType column.  Other values fall
    back to the FY-prefix-stripped form, never touching stored data.
    """
    import re

    voucher = str(row.get("voucher_no") or "").strip()
    match = re.match(r"^\d{4}-\d{4}-(.+)$", voucher)
    if match:
        remainder = match.group(1).strip()
        if "-" in remainder:
            seq = remainder.rsplit("-", 1)[-1].strip()
            if seq:
                return seq
        if remainder:
            return remainder
    return _purchase_display_bill_no(voucher)


def _purchase_fmt_vhdate(iso: Any) -> str:
    """Voucher date as DD/MM/YYYY for the companywise print (display only)."""
    text = str(iso or "").strip()
    parts = text.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return text


def _purchase_fmt_header_date(iso: Any) -> str:
    """Header From/To date as DD-MM-YYYY (display only)."""
    text = str(iso or "").strip()
    parts = text.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return text


def generate_purchase_report_pdf(
    rows: list[dict], summary: dict, financial_year: str, filter_summary: str,
    output_path: str | os.PathLike[str] | None = None,
    from_date: str = "", to_date: str = "", company_name: str = "",
) -> str:
    """Write the current, already-filtered Purchase Report as landscape PDF.

    Print presentation only: clean Helvetica type, bold title/headings,
    padded grid cells with consistent alignment, and a display-only Bill
    Number without the ``YYYY-YYYY`` financial-year prefix.  Stored
    voucher/invoice numbers are never modified.

    Print-only columns: Voucher Date, Discount, GST%, GST Amount,
    Purchase Rate and Net Rate are excluded from the printed PDF only.
    The on-screen report, DAO rows, filters, summary math and stored data
    are unchanged.  When a Company is entered in the top filter info, the
    Company column is also hidden from the print (it is already known
    from the header), print-only.

    When only a Company Name is entered (other optional filters empty),
    the print becomes a Companywise Itemwise Purchase report grouped by
    item with item Totals and a Grand Total, matching the reference
    layout.  Any additional filter falls back to the existing flat print.
    """
    path = _output_path(output_path, "purchase_report", financial_year.replace(" ", "_"))
    # Companywise Itemwise print when only a Company Name was entered.
    if _purchase_is_company_only(filter_summary, company_name):
        try:
            path.write_bytes(_companywise_itemwise_pdf_bytes(
                list(rows or []), str(financial_year), str(filter_summary or ""),
                str(from_date or ""), str(to_date or ""),
                _purchase_company_name(filter_summary, list(rows or []), company_name),
            ))
        except OSError as exc:
            raise DocumentPrintError(f"Could not create PDF at {path}: {exc}") from exc
        return str(path)
    # If a Company value was entered at the top (filter info), we already
    # know the company, so hide the Company column from the print only.
    _filter_text = str(filter_summary or "")
    _hide_company = "Company:" in _filter_text
    if _hide_company:
        headings = [
            "Voucher", "Invoice", "I Date", "Supplier", "Item",
            "Pack", "Batch", "Expiry", "Pay", "Free", "Rate", "MRP", "Amount",
        ]
    else:
        headings = [
            "Voucher", "Invoice", "I Date", "Supplier", "Item", "Company",
            "Pack", "Batch", "Expiry", "Pay", "Free", "Rate", "MRP", "Amount",
        ]

    def _qty(value: Any) -> str:
        try:
            return f"{round(float(value or 0), 2):g}"
        except (TypeError, ValueError):
            return _text(value).replace("\n", " ").strip()

    def _amt(value: Any) -> str:
        try:
            return f"{float(value or 0):,.2f}"
        except (TypeError, ValueError):
            return _text(value).replace("\n", " ").strip()

    def _plain(value: Any) -> str:
        return _text(value).replace("\n", " ").strip()

    detail_rows: list[list[str]] = []
    for row in rows:
        full = [
            _purchase_display_bill_no(row.get("voucher_no")),
            _purchase_display_bill_no(row.get("invoice_no")),
            _plain(row.get("invoice_date")),
            _plain(row.get("supplier_name")),
            _plain(row.get("item_name")),
            _plain(row.get("company_name")),
            _plain(row.get("pack_size")),
            _plain(row.get("batch_no")),
            _plain(row.get("expiry")),
            _qty(row.get("pay_qty")),
            _qty(row.get("free_qty")),
            _amt(row.get("rate")),
            _amt(row.get("mrp")),
            _amt(row.get("amount")),
        ]
        if _hide_company:
            # Drop the Company cell (index 5), print-only.
            del full[5]
        detail_rows.append(full)

    totals_line = "Totals: " + " | ".join([
        f"Bills: {summary.get('total_bills', 0)}",
        f"Pay Qty: {_qty(summary.get('total_pay_qty', 0))}",
        f"Free Qty: {_qty(summary.get('total_free_qty', 0))}",
        f"Gross: {_amt(summary.get('total_gross', 0))}",
        f"GST: {_amt(summary.get('total_gst', 0))}",
        f"Discount: {_amt(summary.get('total_discount', 0))}",
        f"Net: {_amt(summary.get('total_net', 0))}",
    ])
    note_line = "Printed from stored application data. No transaction data was changed."
    try:
        path.write_bytes(_purchase_report_pdf_bytes(
            detail_rows, headings, str(financial_year), str(filter_summary),
            totals_line, note_line,
        ))
    except OSError as exc:
        raise DocumentPrintError(f"Could not create PDF at {path}: {exc}") from exc
    return str(path)


def _companywise_itemwise_pdf_bytes(
    rows: list[dict], financial_year: str, filter_summary: str,
    from_date: str, to_date: str, company_name: str,
) -> bytes:
    """Companywise Itemwise Purchase print (Reports → Purchase Report only).

    Groups the already-filtered purchase rows by item name (first-appearance
    order), with per-item Totals and a final Grand Total summed from stored
    line values only.  No query, no recalculation, no stored-data change.
    """
    try:
        profile = a6.store_profile()
    except Exception:
        profile = {}
    store_name = str((profile or {}).get("name") or "").strip() or "SHREE SAMARTH MEDICAL AND GEN STORE"
    store_address = str((profile or {}).get("address") or "").strip() or "GHORPADE HOSPITAL, RAHURI"

    def _fnum(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def _qty_str(value: Any) -> str:
        try:
            return f"{round(float(value or 0), 2):g}"
        except (TypeError, ValueError):
            return _text(value).replace("\n", " ").strip()

    def _amt2(value: Any) -> str:
        try:
            return f"{float(value or 0):.2f}"
        except (TypeError, ValueError):
            return _text(value).replace("\n", " ").strip()

    # ── date range for the header (existing values, display only) ──
    eff_from = str(from_date or "").strip()
    eff_to = str(to_date or "").strip()
    if not eff_from or not eff_to:
        dates = sorted({
            str(r.get("voucher_date") or "").strip()
            for r in rows if str(r.get("voucher_date") or "").strip()
        })
        if dates:
            eff_from = eff_from or dates[0]
            eff_to = eff_to or dates[-1]
    from_txt = _purchase_fmt_header_date(eff_from) if eff_from else ""
    to_txt = _purchase_fmt_header_date(eff_to) if eff_to else ""
    if from_txt and to_txt:
        period_txt = f"Companywise Itemwise Purchase For {from_txt} To {to_txt}"
    else:
        period_txt = "Companywise Itemwise Purchase"

    # ── group by item (first-appearance order, no re-sort) ──
    groups: list[tuple[str, list[dict]]] = []
    index_by_item: dict[str, int] = {}
    for r in rows:
        name = str(r.get("item_name") or "").strip() or "(Unknown Item)"
        if name not in index_by_item:
            index_by_item[name] = len(groups)
            groups.append((name, []))
        groups[index_by_item[name]][1].append(r)

    HEADS = [
        "VhType", "VhNo", "VhDate", "BatchNo", "PackSize",
        "ExpiryDate", "Rate", "Pay Qty", "Free", "Amount",
    ]
    # ── build drawable blocks ──
    # kinds: itemhead / colhead / detail / itemtotal / grand / empty
    blocks: list[dict] = []
    grand_pay = 0.0
    grand_free = 0.0
    grand_amt = 0.0
    for item_name, lines in groups:
        blocks.append({"kind": "itemhead", "item": item_name})
        blocks.append({"kind": "colhead"})
        tot_pay = 0.0
        tot_free = 0.0
        tot_amt = 0.0
        for r in lines:
            pay = _fnum(r.get("pay_qty"))
            free = _fnum(r.get("free_qty"))
            amt = _fnum(r.get("amount"))
            tot_pay += pay
            tot_free += free
            tot_amt += amt
            blocks.append({"kind": "detail", "cells": [
                _text(_purchase_vh_type(r)).replace("\n", " ").strip(),
                _text(_purchase_vh_no(r)).replace("\n", " ").strip(),
                _purchase_fmt_vhdate(r.get("voucher_date")),
                _text(r.get("batch_no")).replace("\n", " ").strip(),
                _text(r.get("pack_size")).replace("\n", " ").strip(),
                _text(r.get("expiry")).replace("\n", " ").strip(),
                _amt2(r.get("rate")),
                _qty_str(pay),
                _qty_str(free),
                _amt2(amt),
            ]})
        tot_pay = round(tot_pay, 2)
        tot_free = round(tot_free, 2)
        tot_amt = round(tot_amt, 2)
        grand_pay += tot_pay
        grand_free += tot_free
        grand_amt += tot_amt
        blocks.append({
            "kind": "itemtotal",
            "pay_str": _qty_str(tot_pay),
            "free_str": _qty_str(tot_free),
            "amt_str": _amt2(tot_amt),
        })
    grand_pay = round(grand_pay, 2)
    grand_free = round(grand_free, 2)
    grand_amt = round(grand_amt, 2)
    if groups:
        blocks.append({
            "kind": "grand",
            "pay_str": _qty_str(grand_pay),
            "free_str": _qty_str(grand_free),
            "amt_str": _amt2(grand_amt),
        })
    else:
        blocks.append({"kind": "empty", "message": "No records found."})

    PAGE_W, PAGE_H = 842.0, 595.0
    ML, MT, MB, MR = 28.0, 28.0, 28.0, 28.0
    CONTENT_X0 = ML
    CONTENT_W = PAGE_W - ML - MR
    CONTENT_X1 = CONTENT_X0 + CONTENT_W
    COL_WIDTHS = [72.0, 66.0, 88.0, 96.0, 72.0, 92.0, 78.0, 72.0, 62.0, 88.0]
    COL_X: list[float] = []
    _xx = CONTENT_X0
    for _ww in COL_WIDTHS:
        COL_X.append(_xx)
        _xx += _ww
    ALIGNS = [
        "center", "center", "center", "center", "center", "center",
        "right", "right", "right", "right",
    ]
    STORE_PT, SUB_PT = 11.0, 8.0
    TITLE_PT, COMP_PT = 9.5, 9.0
    ITEM_PT, HEAD_PT, BODY_PT = 8.5, 7.5, 7.5
    TOTAL_PT, GRAND_PT = 7.5, 8.0
    STORE_H, SUB_H, TITLE_H, COMP_H, GAP_H = 15.0, 11.0, 13.0, 12.0, 8.0
    ITEM_H, HEAD_H, DETAIL_H, ITEMTOTAL_H, GRAND_H, EMPTY_H = 14.0, 15.0, 13.0, 13.5, 16.0, 16.0

    def _centered_x(text: str, size: float, bold: bool) -> float:
        w = _companywise_text_width_pt(text, size, bold)
        return CONTENT_X0 + max(0.0, (CONTENT_W - w) / 2.0)

    def _cell_x(col: int, text: str, size: float, bold: bool, align: str) -> float:
        max_w = COL_WIDTHS[col] - 6.0
        fitted = _companywise_fit(text, max_w, size, bold)
        w = _companywise_text_width_pt(fitted, size, bold)
        if align == "right":
            return COL_X[col] + COL_WIDTHS[col] - 3.0 - w
        if align == "center":
            return COL_X[col] + max(3.0, (COL_WIDTHS[col] - w) / 2.0)
        return COL_X[col] + 3.0

    def _fitted(col: int, text: str, size: float, bold: bool) -> str:
        return _companywise_fit(text, COL_WIDTHS[col] - 6.0, size, bold)

    def _row_h(block: dict) -> float:
        kind = str(block.get("kind"))
        if kind == "itemhead":
            return ITEM_H
        if kind == "colhead":
            return HEAD_H
        if kind == "itemtotal":
            return ITEMTOTAL_H
        if kind == "grand":
            return GRAND_H
        if kind == "empty":
            return EMPTY_H
        return DETAIL_H

    CONTENT_H = PAGE_H - MT - MB
    FIRST_HEAD = STORE_H + SUB_H + TITLE_H + COMP_H + GAP_H
    FIRST_CAP = CONTENT_H - FIRST_HEAD
    OTHER_CAP = CONTENT_H

    # ── paginate by item groups (keep each item together when possible) ──
    pages: list[list[dict]] = []
    if not groups:
        pages = [[{"kind": "empty", "message": "No records found."}]]
    else:
        # One block group per item: [itemhead, colhead, detail*, itemtotal].
        item_groups: list[tuple[str, list[dict]]] = []
        cur: list[dict] = []
        cur_name = ""
        for b in blocks:
            if b.get("kind") == "grand":
                if cur:
                    item_groups.append((cur_name, cur))
                    cur = []
                    cur_name = ""
                item_groups.append(("", [b]))
                continue
            if b.get("kind") == "itemhead":
                if cur:
                    item_groups.append((cur_name, cur))
                cur = [b]
                cur_name = str(b.get("item") or "")
                continue
            cur.append(b)
        if cur:
            item_groups.append((cur_name, cur))

        def _repeat_head(name: str) -> list[dict]:
            return [
                {"kind": "itemhead", "item": name},
                {"kind": "colhead"},
            ]

        current: list[dict] = []
        remaining = FIRST_CAP
        first_page = True

        def _flush() -> None:
            nonlocal current, remaining, first_page
            if current:
                pages.append(current)
            current = []
            first_page = False
            remaining = OTHER_CAP

        for gname, grp in item_groups:
            if gname == "" and len(grp) == 1 and grp[0].get("kind") == "grand":
                # Grand Total always closes the last page when it fits.
                if current and _row_h(grp[0]) > remaining:
                    _flush()
                if not current:
                    remaining = FIRST_CAP if (first_page and not pages) else OTHER_CAP
                current.extend(grp)
                remaining -= _row_h(grp[0])
                continue
            gh = sum(_row_h(b) for b in grp)
            if not current:
                remaining = FIRST_CAP if (first_page and not pages) else OTHER_CAP
            if gh <= remaining:
                current.extend(grp)
                remaining -= gh
                continue
            if current:
                _flush()
            if gh <= remaining:
                current.extend(grp)
                remaining -= gh
                continue
            # Split a large single item across pages.
            head = [b for b in grp if b.get("kind") in ("itemhead", "colhead")]
            body = [b for b in grp if b.get("kind") not in ("itemhead", "colhead")]
            current.extend(head)
            remaining -= sum(_row_h(b) for b in head)
            for b in body:
                rh = _row_h(b)
                if rh > remaining:
                    _flush()
                    rep = _repeat_head(gname)
                    current.extend(rep)
                    remaining -= sum(_row_h(x) for x in rep)
                current.append(b)
                remaining -= rh
        if current:
            pages.append(current)

    total_pages = max(len(pages), 1)
    period_fit = _companywise_fit(period_txt, CONTENT_W / 2 - 6.0, TITLE_PT, True)
    company_txt_raw = f"Company : {company_name}" if company_name else "Company : "
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    page_ids: list[int] = []
    for page_index, page_blocks in enumerate(pages, 1):
        is_first = page_index == 1
        commands: list[str] = []
        y_top = PAGE_H - MT
        if is_first:
            y = y_top
            left_store = _companywise_fit(store_name, CONTENT_W / 2 - 6.0, STORE_PT, True)
            commands.append(
                f"BT /F2 {STORE_PT:.2f} Tf 1 0 0 1 {CONTENT_X0 + 3.0:.2f} {y - 11.00:.2f} Tm ({_escape(left_store)}) Tj ET"
            )
            right_title = period_fit
            rtw = _companywise_text_width_pt(right_title, TITLE_PT, True)
            commands.append(
                f"BT /F2 {TITLE_PT:.2f} Tf 1 0 0 1 {CONTENT_X1 - 3.0 - rtw:.2f} {y - 10.50:.2f} Tm ({_escape(right_title)}) Tj ET"
            )
            y -= STORE_H
            left_addr = _companywise_fit(store_address, CONTENT_W / 2 - 6.0, SUB_PT, False)
            commands.append(
                f"BT /F1 {SUB_PT:.2f} Tf 1 0 0 1 {CONTENT_X0 + 3.0:.2f} {y - 7.50:.2f} Tm ({_escape(left_addr)}) Tj ET"
            )
            comp_txt = _companywise_fit(company_txt_raw, CONTENT_W / 2 - 6.0, COMP_PT, True)
            ctw = _companywise_text_width_pt(comp_txt, COMP_PT, True)
            commands.append(
                f"BT /F2 {COMP_PT:.2f} Tf 1 0 0 1 {CONTENT_X1 - 3.0 - ctw:.2f} {y - 8.00:.2f} Tm ({_escape(comp_txt)}) Tj ET"
            )
            # Header occupies FIRST_HEAD points; the table starts below it.
            table_top = y_top - FIRST_HEAD
        else:
            table_top = y_top

        # ── draw blocks for this page ──
        cursor = table_top
        # Pre-draw pass: compute tops.
        tops: list[tuple[dict, float, float]] = []
        for b in page_blocks:
            h = _row_h(b)
            tops.append((b, cursor, h))
            cursor -= h
        # Horizontal + vertical grid per table segment.
        # Segments are runs of colhead/detail/itemtotal bounded by itemhead/grand/empty.
        def _h_line(yy: float, w: float = 0.5) -> None:
            commands.append(f"{w:.2f} w {CONTENT_X0:.2f} {yy:.2f} m {CONTENT_X1:.2f} {yy:.2f} l S")

        def _v_line(xx: float, y0: float, y1: float, w: float = 0.5) -> None:
            commands.append(f"{w:.2f} w {xx:.2f} {y1:.2f} m {xx:.2f} {y0:.2f} l S")

        seg_top: float | None = None
        seg_bottom: float | None = None

        def _close_seg() -> None:
            nonlocal seg_top, seg_bottom
            if seg_top is not None and seg_bottom is not None:
                for _cx in COL_X[1:] + [CONTENT_X1]:
                    _v_line(_cx, seg_top, seg_bottom, 0.4)
                _v_line(CONTENT_X0, seg_top, seg_bottom, 0.7)
            seg_top = None
            seg_bottom = None

        for b, top, h in tops:
            kind = str(b.get("kind"))
            if kind in ("colhead", "detail", "itemtotal"):
                if seg_top is None:
                    seg_top = top
                seg_bottom = top - h
                _h_line(top, 0.7 if kind == "colhead" else 0.4)
                if kind == "itemtotal":
                    _h_line(top - h, 0.7)
                    _close_seg()
                elif kind == "colhead":
                    pass
                else:
                    _h_line(top - h, 0.4)
            else:
                _close_seg()
                if kind == "grand":
                    _h_line(top, 0.8)
                    _h_line(top - h, 0.8)
                elif kind == "empty":
                    _h_line(top, 0.7)
                    _h_line(top - h, 0.7)
        _close_seg()

        for b, top, h in tops:
            kind = str(b.get("kind"))
            bottom = top - h
            if kind == "itemhead":
                txt = _companywise_fit(str(b.get("item") or ""), CONTENT_W - 6.0, ITEM_PT, True)
                if txt:
                    commands.append(
                        f"BT /F2 {ITEM_PT:.2f} Tf 1 0 0 1 {CONTENT_X0 + 3.0:.2f} {bottom + 4.5:.2f} Tm ({_escape(txt)}) Tj ET"
                    )
            elif kind == "colhead":
                base = bottom + 5.0
                for col, head in enumerate(HEADS):
                    align = ALIGNS[col]
                    txt = _companywise_fit(head, COL_WIDTHS[col] - 6.0, HEAD_PT, True)
                    # Compute x.
                    max_w = COL_WIDTHS[col] - 6.0
                    fitted = _companywise_fit(txt, max_w, HEAD_PT, True)
                    w = _companywise_text_width_pt(fitted, HEAD_PT, True)
                    if align == "right":
                        xx = COL_X[col] + COL_WIDTHS[col] - 3.0 - w
                    elif align == "center":
                        xx = COL_X[col] + max(3.0, (COL_WIDTHS[col] - w) / 2.0)
                    else:
                        xx = COL_X[col] + 3.0
                    commands.append(
                        f"BT /F2 {HEAD_PT:.2f} Tf 1 0 0 1 {xx:.2f} {base:.2f} Tm ({_escape(fitted)}) Tj ET"
                    )
            elif kind == "detail":
                cells: list[str] = b.get("cells", [""] * 10)
                base = bottom + 4.0
                for col in range(10):
                    raw = cells[col] if col < len(cells) else ""
                    if raw == "":
                        continue
                    align = ALIGNS[col]
                    txt = _companywise_fit(raw, COL_WIDTHS[col] - 6.0, BODY_PT, False)
                    if not txt:
                        continue
                    w = _companywise_text_width_pt(txt, BODY_PT, False)
                    if align == "right":
                        xx = COL_X[col] + COL_WIDTHS[col] - 3.0 - w
                    elif align == "center":
                        xx = COL_X[col] + max(3.0, (COL_WIDTHS[col] - w) / 2.0)
                    else:
                        xx = COL_X[col] + 3.0
                    commands.append(
                        f"BT /F1 {BODY_PT:.2f} Tf 1 0 0 1 {xx:.2f} {base:.2f} Tm ({_escape(txt)}) Tj ET"
                    )
            elif kind == "itemtotal":
                base = bottom + 4.0
                label = _companywise_fit("Total :", sum(COL_WIDTHS[:7]) - 6.0, TOTAL_PT, True)
                lw = _companywise_text_width_pt(label, TOTAL_PT, True)
                lx = COL_X[0] + sum(COL_WIDTHS[:7]) - 3.0 - lw
                commands.append(
                    f"BT /F2 {TOTAL_PT:.2f} Tf 1 0 0 1 {lx:.2f} {base:.2f} Tm ({_escape(label)}) Tj ET"
                )
                for col, key in ((7, "pay_str"), (8, "free_str"), (9, "amt_str")):
                    txt = _companywise_fit(b.get(key, ""), COL_WIDTHS[col] - 6.0, TOTAL_PT, True)
                    if not txt:
                        continue
                    w = _companywise_text_width_pt(txt, TOTAL_PT, True)
                    xx = COL_X[col] + COL_WIDTHS[col] - 3.0 - w
                    commands.append(
                        f"BT /F2 {TOTAL_PT:.2f} Tf 1 0 0 1 {xx:.2f} {base:.2f} Tm ({_escape(txt)}) Tj ET"
                    )
            elif kind == "grand":
                commands.append(
                    f"0.80 w {CONTENT_X0:.2f} {bottom:.2f} {CONTENT_W:.2f} {h:.2f} re S"
                )
                base = bottom + 5.5
                label = _companywise_fit("Grand Total :", sum(COL_WIDTHS[:7]) - 6.0, GRAND_PT, True)
                lw = _companywise_text_width_pt(label, GRAND_PT, True)
                lx = COL_X[0] + sum(COL_WIDTHS[:7]) - 3.0 - lw
                commands.append(
                    f"BT /F2 {GRAND_PT:.2f} Tf 1 0 0 1 {lx:.2f} {base:.2f} Tm ({_escape(label)}) Tj ET"
                )
                for col, key in ((7, "pay_str"), (8, "free_str"), (9, "amt_str")):
                    txt = _companywise_fit(b.get(key, ""), COL_WIDTHS[col] - 6.0, GRAND_PT, True)
                    if not txt:
                        continue
                    w = _companywise_text_width_pt(txt, GRAND_PT, True)
                    xx = COL_X[col] + COL_WIDTHS[col] - 3.0 - w
                    commands.append(
                        f"BT /F2 {GRAND_PT:.2f} Tf 1 0 0 1 {xx:.2f} {base:.2f} Tm ({_escape(txt)}) Tj ET"
                    )
            elif kind == "empty":
                msg = _companywise_fit(b.get("message", "No records found."), CONTENT_W - 12.0, BODY_PT, False)
                w = _companywise_text_width_pt(msg, BODY_PT, False)
                xx = CONTENT_X0 + max(0.0, (CONTENT_W - w) / 2.0)
                commands.append(
                    f"BT /F1 {BODY_PT:.2f} Tf 1 0 0 1 {xx:.2f} {bottom + 5.0:.2f} Tm ({_escape(msg)}) Tj ET"
                )
        stamp = f"Page {page_index} of {total_pages}"
        sw = _companywise_text_width_pt(stamp, 7.0, False)
        commands.append(
            f"BT /F1 7.00 Tf 1 0 0 1 {CONTENT_X0 + max(0.0, (CONTENT_W - sw) / 2.0):.2f} {(MB - 12.0):.2f} Tm ({_escape(stamp)}) Tj ET"
        )
        stream = "\n".join(commands).encode("latin-1", "replace")
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def _purchase_report_pdf_bytes(
    detail_rows: list[list[str]], headings: list[str],
    financial_year: str, filter_summary: str,
    totals_line: str, note_line: str,
) -> bytes:
    """Professional landscape-A4 writer for the Purchase Report table only.

    Print-only column set; Helvetica/Helvetica-Bold, bold headings,
    padded grid cells, right-aligned numerics, fitted text so nothing
    touches borders or overlaps.  Totals and notes are preserved on the
    final page.
    """
    PAGE_W, PAGE_H = 842.0, 595.0
    ML, MT, MB, MR = 28.0, 28.0, 28.0, 28.0
    CONTENT_X0 = ML
    CONTENT_W = PAGE_W - ML - MR
    CONTENT_X1 = CONTENT_X0 + CONTENT_W
    # Column widths (points) sum to CONTENT_W (786).  Wider for Item /
    # Supplier / Company, narrow for qty columns, with breathing room so
    # values never touch adjacent borders.  When the Company column is
    # hidden (company already known from the top filter), its width is
    # redistributed to the remaining columns.
    if "Company" not in headings:
        COL_WIDTHS = [
            64.0, 60.0, 64.0, 90.0, 120.0, 42.0, 56.0, 44.0,
            34.0, 34.0, 56.0, 56.0, 66.0,
        ]
    else:
        COL_WIDTHS = [
            62.0, 58.0, 62.0, 78.0, 104.0, 76.0, 38.0, 52.0, 40.0,
            32.0, 32.0, 48.0, 48.0, 56.0,
        ]
    COL_X: list[float] = []
    _x = CONTENT_X0
    for _w in COL_WIDTHS:
        COL_X.append(_x)
        _x += _w
    if "Company" not in headings:
        ALIGNS = [
            "left", "left", "center", "left", "left",
            "center", "center", "center",
            "right", "right", "right", "right", "right",
        ]
    else:
        ALIGNS = [
            "left", "left", "center", "left", "left", "left",
            "center", "center", "center",
            "right", "right", "right", "right", "right",
        ]
    TITLE_PT, FY_PT, FILTER_PT = 13.0, 8.5, 7.5
    HEADER_PT, BODY_PT = 7.0, 7.0
    TOTALS_PT, NOTE_PT = 7.5, 7.0
    TITLE_H, FY_H, FILTER_H, TITLE_GAP = 17.0, 11.0, 10.0, 8.0
    HEADER_H, DETAIL_H = 15.0, 12.5
    TOTALS_H, NOTE_H, BLOCK_GAP = 16.0, 11.0, 6.0

    def _centered_x(text: str, size: float, bold: bool) -> float:
        w = _companywise_text_width_pt(text, size, bold)
        return CONTENT_X0 + max(0.0, (CONTENT_W - w) / 2.0)

    def _cell_x(col: int, text: str, size: float, bold: bool, align: str) -> float:
        max_w = COL_WIDTHS[col] - 6.0
        fitted = _companywise_fit(text, max_w, size, bold)
        w = _companywise_text_width_pt(fitted, size, bold)
        if align == "right":
            return COL_X[col] + COL_WIDTHS[col] - 3.0 - w
        if align == "center":
            return COL_X[col] + max(3.0, (COL_WIDTHS[col] - w) / 2.0)
        return COL_X[col] + 3.0

    def _fitted(col: int, text: str, size: float, bold: bool) -> str:
        return _companywise_fit(text, COL_WIDTHS[col] - 6.0, size, bold)

    # ── paginate detail rows (heights, not fixed counts) ──
    CONTENT_H = PAGE_H - MT - MB
    FIRST_HEAD_BLOCK = TITLE_H + FY_H + FILTER_H + TITLE_GAP
    FIRST_CAP = CONTENT_H - FIRST_HEAD_BLOCK - HEADER_H
    OTHER_CAP = CONTENT_H - HEADER_H
    RESERVE_LAST = TOTALS_H + BLOCK_GAP + NOTE_H + BLOCK_GAP

    pages_rows: list[list[list[str]]] = []
    if not detail_rows:
        pages_rows = [[]]
    else:
        current: list[list[str]] = []
        remaining = FIRST_CAP
        is_first_page = True
        for crow in detail_rows:
            if not current:
                remaining = FIRST_CAP if is_first_page else OTHER_CAP
            if current and DETAIL_H > remaining:
                pages_rows.append(current)
                current = []
                is_first_page = False
                remaining = OTHER_CAP
            current.append(crow)
            remaining -= DETAIL_H
        if current:
            pages_rows.append(current)
        # Ensure the totals block fits on the last page.
        last_used = len(pages_rows[-1]) * DETAIL_H if pages_rows else 0
        last_cap = FIRST_CAP if len(pages_rows) == 1 else OTHER_CAP
        if last_used + RESERVE_LAST > last_cap:
            # Totals move to their own closing page with no detail rows.
            pages_rows.append([])

    total_pages = max(len(pages_rows), 1)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    page_ids: list[int] = []
    for page_index, page_detail in enumerate(pages_rows, 1):
        is_first = page_index == 1
        is_last = page_index == total_pages
        commands: list[str] = []
        y_top = PAGE_H - MT
        if is_first:
            y = y_top
            title = _companywise_fit("Purchase Report", CONTENT_W, TITLE_PT, True)
            commands.append(
                f"BT /F2 {TITLE_PT:.2f} Tf 1 0 0 1 {_centered_x(title, TITLE_PT, True):.2f} {y - 12.00:.2f} Tm ({_escape(title)}) Tj ET"
            )
            y -= TITLE_H
            fy_txt = _companywise_fit(f"Financial Year: {financial_year}", CONTENT_W, FY_PT, False)
            commands.append(
                f"BT /F1 {FY_PT:.2f} Tf 1 0 0 1 {_centered_x(fy_txt, FY_PT, False):.2f} {y - 7.50:.2f} Tm ({_escape(fy_txt)}) Tj ET"
            )
            y -= FY_H
            filt_raw = f"Filters: {filter_summary}"
            filt_txt = _companywise_fit(filt_raw, CONTENT_W, FILTER_PT, False)
            commands.append(
                f"BT /F1 {FILTER_PT:.2f} Tf 1 0 0 1 {_centered_x(filt_txt, FILTER_PT, False):.2f} {y - 6.50:.2f} Tm ({_escape(filt_txt)}) Tj ET"
            )
            y -= FILTER_H
            y -= TITLE_GAP
            table_top = y
        else:
            table_top = y_top

        # ── table frame for this page ──
        n_detail = len(page_detail)
        has_totals = is_last
        table_h = HEADER_H + n_detail * DETAIL_H
        if has_totals:
            table_h += BLOCK_GAP + TOTALS_H
            if note_line:
                table_h += BLOCK_GAP + NOTE_H
        table_bottom = table_top - table_h

        def _h_line(yy: float, w: float = 0.5) -> None:
            commands.append(f"{w:.2f} w {CONTENT_X0:.2f} {yy:.2f} m {CONTENT_X1:.2f} {yy:.2f} l S")

        def _v_line(xx: float, y0: float, y1: float, w: float = 0.5) -> None:
            commands.append(f"{w:.2f} w {xx:.2f} {y1:.2f} m {xx:.2f} {y0:.2f} l S")

        # Horizontal rules: top, below header, after each detail row, around totals.
        _h_line(table_top, 0.7)
        _h_line(table_top - HEADER_H, 0.7)
        cursor = table_top - HEADER_H
        for _ in page_detail:
            cursor -= DETAIL_H
            _h_line(cursor, 0.4)
        # Verticals through header + detail grid.
        grid_bottom = cursor
        for _cx in COL_X[1:] + [CONTENT_X1]:
            _v_line(_cx, table_top, grid_bottom, 0.4)
        _v_line(CONTENT_X0, table_top, grid_bottom, 0.7)

        # ── column headings (bold, clearly distinct) ──
        head_base = table_top - HEADER_H + 5.5
        for col, head in enumerate(headings):
            align = ALIGNS[col] if col < len(ALIGNS) else "left"
            # Headings stay centered for date/batch groups? Keep alignment
            # consistent with body for clean columns, except text heads left.
            txt = _fitted(col, head, HEADER_PT, True)
            commands.append(
                f"BT /F2 {HEADER_PT:.2f} Tf 1 0 0 1 {_cell_x(col, txt, HEADER_PT, True, align):.2f} {head_base:.2f} Tm ({_escape(txt)}) Tj ET"
            )
        # ── body rows ──
        for r_idx, cells in enumerate(page_detail):
            row_top = table_top - HEADER_H - r_idx * DETAIL_H
            row_bottom = row_top - DETAIL_H
            base = row_bottom + 4.0
            for col in range(len(headings)):
                raw = cells[col] if col < len(cells) else ""
                if raw == "":
                    continue
                align = ALIGNS[col] if col < len(ALIGNS) else "left"
                bold = False
                txt = _fitted(col, raw, BODY_PT, bold)
                if not txt:
                    continue
                commands.append(
                    f"BT /F1 {BODY_PT:.2f} Tf 1 0 0 1 {_cell_x(col, txt, BODY_PT, bold, align):.2f} {base:.2f} Tm ({_escape(txt)}) Tj ET"
                )
        if not page_detail:
            # Empty-state row keeps the grid shape and preserves pagination.
            empty_h = DETAIL_H
            msg = _companywise_fit("No records found.", CONTENT_W - 12.0, BODY_PT, False)
            commands.append(
                f"BT /F1 {BODY_PT:.2f} Tf 1 0 0 1 {_centered_x(msg, BODY_PT, False):.2f} {cursor - empty_h + 4.0:.2f} Tm ({_escape(msg)}) Tj ET"
            )
        # ── totals box + disclaimer (last page only, info preserved) ──
        if has_totals:
            t_top = cursor - BLOCK_GAP
            t_bottom = t_top - TOTALS_H
            commands.append(
                f"0.80 w {CONTENT_X0:.2f} {t_bottom:.2f} {CONTENT_W:.2f} {TOTALS_H:.2f} re S"
            )
            tot_txt = _companywise_fit(totals_line, CONTENT_W - 8.0, TOTALS_PT, True)
            tot_w = _companywise_text_width_pt(tot_txt, TOTALS_PT, True)
            # Totals are data: left-aligned with padding so long lines never
            # touch the box edges; short lines still start at a fixed inset.
            tot_x = CONTENT_X0 + 4.0
            if tot_w > CONTENT_W - 8.0:
                tot_x = CONTENT_X0 + 4.0
            commands.append(
                f"BT /F2 {TOTALS_PT:.2f} Tf 1 0 0 1 {tot_x:.2f} {t_bottom + 5.5:.2f} Tm ({_escape(tot_txt)}) Tj ET"
            )
            cursor = t_bottom
            if note_line:
                cursor -= BLOCK_GAP
                n_bottom = cursor - NOTE_H
                note_txt = _companywise_fit(note_line, CONTENT_W - 8.0, NOTE_PT, False)
                commands.append(
                    f"BT /F1 {NOTE_PT:.2f} Tf 1 0 0 1 {_centered_x(note_txt, NOTE_PT, False):.2f} {n_bottom + 3.5:.2f} Tm ({_escape(note_txt)}) Tj ET"
                )
                cursor = n_bottom
        stamp = f"Page {page_index} of {total_pages}"
        commands.append(
            f"BT /F1 7.00 Tf 1 0 0 1 {_centered_x(stamp, 7.0, False):.2f} {(MB - 12.0):.2f} Tm ({_escape(stamp)}) Tj ET"
        )
        stream = "\n".join(commands).encode("latin-1", "replace")
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def _landscape_pdf_bytes(pages: list[list[str]], title: str) -> bytes:
    """Minimal landscape A4 writer used for report tables (842 × 595 points)."""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
    page_ids = []
    for page_index, lines in enumerate(pages, 1):
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        commands = ["BT", "/F1 8 Tf", "28 567 Td"]
        for line in lines:
            commands.append(f"({_escape(line[:155])}) Tj")
            commands.append("0 -12 Td")
        commands.extend(["0 -12 Td", f"(Page {page_index} of {len(pages)}) Tj", "ET"])
        stream = "\n".join(commands).encode("latin-1", "replace")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output)); output.extend(f"{number} 0 obj\n".encode()); output.extend(obj); output.extend(b"\nendobj\n")
    xref = len(output); output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def generate_pharmacy_a6_bill(invoice_id: int, output_path: str | os.PathLike[str] | None = None, title: str = "Sales Bill") -> str:
    """Write a sales/counter-sale receipt on true A6 paper (105 x 148 mm).

    Shares one layout engine with ``print_pharmacy_a6_bill`` so the exported PDF
    and the printed bill are the same page. Sales Bill and Counter Sale both use
    it, so no printing code is duplicated between them.
    """
    if output_path is None:
        output_path = Path.cwd() / f"pharmacy_a6_bill_{title.lower().replace(' ', '_')}_{invoice_id}.pdf"
    try:
        return a6.generate_pharmacy_a6_bill(invoice_id, output_path, title)
    except a6.ReceiptPrintError as exc:
        raise DocumentPrintError(str(exc)) from exc


def print_pharmacy_a6_bill(invoice_id: int, parent=None, title: str = "Sales Bill", show_dialog: bool = True) -> bool:
    """Print a sales/counter-sale receipt on A6 via the normal Windows print dialog."""
    try:
        return a6.print_pharmacy_a6_bill(invoice_id, parent, title, show_dialog=show_dialog)
    except a6.ReceiptPrintError as exc:
        raise DocumentPrintError(str(exc)) from exc


def preview_pharmacy_a6_bill(invoice_id: int, title: str = "Sales Bill") -> str:
    """Plain-text A6 layout preview for a stored sale."""
    return a6.preview_pharmacy_a6_bill(invoice_id, title)


def a6_profile():
    """The reusable ``PHARMACY_A6`` print profile."""
    return a6.PHARMACY_A6


def available_printers() -> list[str]:
    """Windows printers discovered through Qt, in their installed order."""
    return a6.available_printers()


def default_printer_name() -> str:
    """The Windows default printer; nothing is hard-coded."""
    return a6.default_printer_name()


def supported_page_size_mm(printer_name: str) -> list[tuple[float, float]]:
    """Paper sizes (width_mm, height_mm) reported by ``printer_name``."""
    return a6.supported_page_size_mm(printer_name)


def generate_sales_bill(invoice_id: int, output_path: str | os.PathLike[str] | None = None) -> str:
    return generate_pharmacy_a6_bill(invoice_id, output_path, "Sales Bill")


def generate_counter_sale_bill(invoice_id: int, output_path: str | os.PathLike[str] | None = None) -> str:
    return generate_pharmacy_a6_bill(invoice_id, output_path, "Counter Sale Bill")


def generate_purchase_invoice(invoice_id: int, output_path: str | os.PathLike[str] | None = None) -> str:
    record, items = _purchase_data(invoice_id); return generate_document("Purchase Invoice", record, items, output_path)


def generate_credit_note(note_id: int, output_path: str | os.PathLike[str] | None = None) -> str:
    record, items = _credit_data(note_id); return generate_document("Credit Note", record, items, output_path)


def generate_debit_note(note_id: int, output_path: str | os.PathLike[str] | None = None) -> str:
    record, items = _debit_data(note_id); return generate_document("Debit Note", record, items, output_path)


def generate_customer_receipt(receipt_id: int, output_path: str | os.PathLike[str] | None = None) -> str:
    record, items = _receipt_data(receipt_id); return generate_document("Customer Receipt", record, items, output_path)


def generate_supplier_payment(payment_id: int, output_path: str | os.PathLike[str] | None = None) -> str:
    record, items = _payment_data(payment_id); return generate_document("Supplier Payment", record, items, output_path)


def preview_document(title: str, record: dict, items: list[dict]) -> str:
    """Return plain text preview data for environments without Qt printing."""
    if title in {"Sales Bill", "Counter Sale Bill"}:
        blocks = a6.build_layout(dict(record, document_title=title), items)
        return a6.pages_to_preview_text(a6.paginate(blocks))
    return "\n".join(_document_lines(title, record, items))


def print_pdf(path: str | os.PathLike[str], parent=None) -> bool:
    """Open an optional Qt print dialog; PDF export remains available headlessly."""
    if not os.path.exists(path):
        raise DocumentPrintError(f"PDF file not found: {path}")
    try:
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
    except ImportError:
        raise DocumentPrintError("Printer support requires PySide6; use Save PDF instead.")
    printer = QPrinter(QPrinter.HighResolution)
    dialog = QPrintDialog(printer, parent)
    if dialog.exec() != QPrintDialog.Accepted:
        return False
    return True


__all__ = [
    "DocumentPrintError", "generate_document", "generate_daily_sales_report_pdf", "generate_purchase_report_pdf", "generate_sales_bill", "generate_counter_sale_bill",
    "generate_purchase_invoice", "generate_credit_note", "generate_debit_note",
    "generate_customer_receipt", "generate_supplier_payment", "preview_document", "print_pdf",
    "generate_pharmacy_a6_bill", "print_pharmacy_a6_bill", "preview_pharmacy_a6_bill", "a6_profile",
    "available_printers", "default_printer_name", "supported_page_size_mm",
]
