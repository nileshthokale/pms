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
    "DocumentPrintError", "generate_document", "generate_sales_bill", "generate_counter_sale_bill",
    "generate_purchase_invoice", "generate_credit_note", "generate_debit_note",
    "generate_customer_receipt", "generate_supplier_payment", "preview_document", "print_pdf",
    "generate_pharmacy_a6_bill", "print_pharmacy_a6_bill", "preview_pharmacy_a6_bill", "a6_profile",
    "available_printers", "default_printer_name", "supported_page_size_mm",
]
