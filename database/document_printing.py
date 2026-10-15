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
            if _row.get("kind") == "grand":
                _h_line(_top, 0.8)
                _h_line(_top - _h, 0.8)
            else:
                _h_line(_top - _h, 0.5)
        # Verticals run only through grid rows (header/detail/totals), so the
        # full-width bill header bands stay free of crossing lines.
        GRID_KINDS = {"header", "detail", "billtotal", "grand"}
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
                base = bottom + 5.0
                span_w = sum(COL_WIDTHS[:4]) - 6.0
                label = _companywise_fit("Grand Total", span_w, GRAND_FONT, True)
                lw = _companywise_text_width_pt(label, GRAND_FONT, True)
                lx = COL_X[0] + sum(COL_WIDTHS[:4]) - 3.0 - lw
                commands.append(
                    f"BT /F2 {GRAND_FONT:.2f} Tf 1 0 0 1 {lx:.2f} {base:.2f} Tm ({_escape(label)}) Tj ET"
                )
                for col, key in ((4, "qty_str"), (5, "disc_str"), (6, "amt_str")):
                    txt = _fitted(col, row.get(key, ""), GRAND_FONT, True)
                    if not txt:
                        continue
                    commands.append(
                        f"BT /F2 {GRAND_FONT:.2f} Tf 1 0 0 1 {_cell_x(col, txt, GRAND_FONT, True, 'right'):.2f} {base:.2f} Tm ({_escape(txt)}) Tj ET"
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




def generate_purchase_report_pdf(
    rows: list[dict], summary: dict, financial_year: str, filter_summary: str,
    output_path: str | os.PathLike[str] | None = None,
) -> str:
    """Write the current, already-filtered Purchase Report as landscape PDF."""
    path = _output_path(output_path, "purchase_report", financial_year.replace(" ", "_"))
    headings = [
        "Voucher", "V Date", "Invoice", "I Date", "Supplier", "Item", "Company",
        "Pack", "Batch", "Expiry", "Pay", "Free", "Rate", "MRP", "Disc",
        "GST%", "GST Amt", "Amount", "Purc Rt", "Net Rt",
    ]
    widths = [9, 10, 9, 10, 12, 14, 11, 7, 9, 7, 6, 6, 8, 8, 7, 6, 9, 9, 8, 8]

    def clip(value: Any, width: int) -> str:
        value = _text(value).replace("\n", " ")
        return value[:width - 1] + "…" if len(value) > width else value

    def report_row(row: dict) -> str:
        values = [
            row.get("voucher_no"), row.get("voucher_date"), row.get("invoice_no"),
            row.get("invoice_date"), row.get("supplier_name"), row.get("item_name"),
            row.get("company_name"), row.get("pack_size"), row.get("batch_no"),
            row.get("expiry"), row.get("pay_qty"), row.get("free_qty"),
            _money(row.get("rate")), _money(row.get("mrp")), _money(row.get("discount")),
            row.get("gst_percent"), _money(row.get("gst_amount")), _money(row.get("amount")),
            _money(row.get("purchase_rate")), _money(row.get("net_rate")),
        ]
        return " ".join(clip(value, width).ljust(width) for value, width in zip(values, widths))

    header = " ".join(name.ljust(width) for name, width in zip(headings, widths))
    page_capacity = 37
    chunks = [rows[index:index + page_capacity] for index in range(0, len(rows), page_capacity)] or [[]]
    pages: list[list[str]] = []
    for page_index, chunk in enumerate(chunks):
        lines = ["Purchase Report", f"Financial Year: {financial_year}", f"Filters: {filter_summary}", "", header, "-" * len(header)]
        lines.extend(report_row(row) for row in chunk)
        if page_index == len(chunks) - 1:
            lines.extend([
                "",
                "Totals: " + " | ".join([
                    f"Bills: {summary.get('total_bills', 0)}",
                    f"Pay Qty: {summary.get('total_pay_qty', 0):g}",
                    f"Free Qty: {summary.get('total_free_qty', 0):g}",
                    f"Gross: {summary.get('total_gross', 0):,.2f}",
                    f"GST: {summary.get('total_gst', 0):,.2f}",
                    f"Discount: {summary.get('total_discount', 0):,.2f}",
                    f"Net: {summary.get('total_net', 0):,.2f}",
                ]),
                "Printed from stored application data. No transaction data was changed.",
            ])
        pages.append(lines)
    try:
        path.write_bytes(_landscape_pdf_bytes(pages, "Purchase Report"))
    except OSError as exc:
        raise DocumentPrintError(f"Could not create PDF at {path}: {exc}") from exc
    return str(path)


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
