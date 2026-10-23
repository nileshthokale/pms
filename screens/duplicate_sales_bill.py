"""Duplicate Sales Bill feature (List Page, Popup Form, and Crystal Report Print).

Completely separate, print-only duplicate sales bills:
- Does NOT read from or write to stock, batch stock, ledger, customer balance,
  cash book, VAT/GST reports, sales reports, or any existing transaction table.
- Stores plain typed text and numbers in dup_sales_bill_head and dup_sales_bill_item.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QDate, QTime, Qt, Signal
import re
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QScrollArea,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from database.duplicate_sales_dao import DuplicateSalesDAO
from database import financial_year
from database import pharmacy_a6_receipt as a6
from ui.crystal_report_viewer import (
    BlockKind,
    CONTENT_WIDTH,
    CrystalReportViewer,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    fmt_amt,
    fmt_qty,
    get_default_store_identity,
    print_or_export_report_pages,
)
from ui.input_rules import attach_uppercase
from ui.theme import (
    FONT_FAMILY,
    TYPE_FORM_LABEL,
    TYPE_SECTION_HEADER,
    TYPE_VALUE,
    palette,
)


def _safe_float(val: Any) -> float:
    try:
        return float(str(val).strip().replace(",", ""))
    except Exception:
        return 0.0


# ══════════════════════════════════════════════════════════════════════
# 1. CRYSTAL REPORT GENERATOR FOR DUPLICATE SALES BILL
# ══════════════════════════════════════════════════════════════════════

_MAX_PORTRAIT_BODY_HEIGHT = 860.0


def build_duplicate_sales_bill_report_pages(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    show_duplicate_copy: bool = True,
) -> list[ReportPage]:
    """Generate A4 portrait Crystal Report pages for a Duplicate Sales Bill."""
    store_name, store_address = get_default_store_identity()

    header_line_1 = "DUPLICATE SALES BILL"
    header_line_2 = f"Voucher No: {head.get('voucher_no', '')}   |   Date: {head.get('vh_date', '')}   |   Time: {head.get('vh_time', '')}"
    cust = head.get("customer_name") or "WALKIN"
    pat = head.get("patient_name") or ""
    doc = head.get("doctor_name") or ""
    cust_str = f"Customer: {cust}" + (f"  (Patient: {pat})" if pat else "")
    if doc:
        cust_str += f"   |   Doctor: {doc}"
    header_line_3 = cust_str

    if show_duplicate_copy:
        header_line_1 = "DUPLICATE SALES BILL   [ DUPLICATE COPY ]"

    header = ReportHeaderData(
        store_name=store_name,
        store_address=store_address,
        header_line_1=header_line_1,
        header_line_2=header_line_2,
        header_line_3=header_line_3,
    )

    columns = [
        "Sr",
        "Item Name",
        "Pack",
        "Batch",
        "Expiry",
        "MRP",
        "Qty",
        "Disc %",
        "Amount",
    ]
    widths = [35.0, 210.0, 65.0, 75.0, 60.0, 65.0, 50.0, 50.0, 85.0]
    aligns = ["center", "left", "center", "left", "center", "right", "right", "right", "right"]

    blocks: list[ReportBlock] = []

    table_header_block = ReportBlock(
        kind=BlockKind.TABLE_HEADER,
        height=24.0,
        data={"columns": columns, "widths": widths, "aligns": aligns},
    )
    blocks.append(table_header_block)

    for idx, itm in enumerate(items, start=1):
        row_vals = [
            str(idx),
            str(itm.get("item_name") or ""),
            str(itm.get("pack_size") or ""),
            str(itm.get("batch_no") or ""),
            str(itm.get("expiry") or ""),
            fmt_amt(itm.get("mrp")),
            fmt_qty(itm.get("sales_qty")),
            fmt_amt(itm.get("disc")),
            fmt_amt(itm.get("amount")),
        ]
        blocks.append(
            ReportBlock(
                kind=BlockKind.DATA_ROW,
                height=20.0,
                data={"cells": row_vals, "widths": widths, "aligns": aligns},
            )
        )

    # Totals block
    tot_amt = _safe_float(head.get("total_amount"))
    less_disc = _safe_float(head.get("less_bill_discount"))
    less_cn = _safe_float(head.get("less_cn_amt"))
    add_dr = _safe_float(head.get("add_dr_amt"))
    rnd_off = _safe_float(head.get("round_off"))
    net_amt = _safe_float(head.get("net_amount"))
    sum_qty = sum(_safe_float(i.get("sales_qty")) for i in items)

    custom_cells = [
        (widths[0] + widths[1], f"TOTAL ITEMS: {len(items)}", "left"),
        (sum(widths[2:6]), f"Gross: {fmt_amt(tot_amt)}", "center"),
        (widths[6], fmt_qty(sum_qty), "right"),
        (widths[7], f"Disc: {fmt_amt(less_disc)}", "right"),
        (widths[8], fmt_amt(net_amt), "right"),
    ]
    blocks.append(
        ReportBlock(
            kind=BlockKind.GRAND_TOTAL,
            height=24.0,
            data={"custom_cells": custom_cells, "widths": widths},
        )
    )

    if rnd_off != 0.0 or less_cn != 0.0 or add_dr != 0.0 or head.get("remarks"):
        summary_lines = []
        if head.get("remarks"):
            summary_lines.append(f"Remarks: {head.get('remarks')}")
        if less_cn:
            summary_lines.append(f"Less CN: {fmt_amt(less_cn)}")
        if add_dr:
            summary_lines.append(f"Add Dr: {fmt_amt(add_dr)}")
        if rnd_off:
            summary_lines.append(f"Round Off: {fmt_amt(rnd_off)}")
        blocks.append(
            ReportBlock(
                kind=BlockKind.SUMMARY_BOX,
                height=22.0,
                data={"text": "   |   ".join(summary_lines), "width": sum(widths)},
            )
        )

    # Paginate blocks across portrait A4 pages
    pages: list[ReportPage] = []
    current_blocks: list[ReportBlock] = []
    current_h = 0.0

    for block in blocks:
        if current_blocks and current_h + block.height > _MAX_PORTRAIT_BODY_HEIGHT:
            pages.append(
                ReportPage(
                    page_num=len(pages) + 1,
                    total_pages=0,
                    header=header,
                    blocks=current_blocks,
                    orientation="portrait",
                    page_width=PAGE_WIDTH,
                    page_height=PAGE_HEIGHT,
                )
            )
            current_blocks = []
            current_h = 0.0
            if block.kind != BlockKind.TABLE_HEADER:
                current_blocks.append(table_header_block)
                current_h += table_header_block.height

        current_blocks.append(block)
        current_h += block.height

    if current_blocks:
        pages.append(
            ReportPage(
                page_num=len(pages) + 1,
                total_pages=0,
                header=header,
                blocks=current_blocks,
                orientation="portrait",
                page_width=PAGE_WIDTH,
                page_height=PAGE_HEIGHT,
            )
        )

    tot = len(pages)
    for p in pages:
        p.total_pages = tot

    return pages


def _format_expiry_display(val: str) -> str:
    val = str(val or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})", val)
    if m:
        return f"{m.group(2)}/{m.group(1)[2:]}"
    m2 = re.match(r"^(\d{1,2})/(\d{4})$", val)
    if m2:
        return f"{int(m2.group(1)):02d}/{m2.group(2)[2:]}"
    return val


def _build_a6_pages_for_duplicate_bill(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    show_duplicate_copy: bool = True,
) -> tuple[list[list[a6.Block]], a6.PaperProfile]:
    doc_title = "DUPLICATE SALES BILL"
    if show_duplicate_copy:
        doc_title = "DUPLICATE SALES BILL [DUPLICATE COPY]"

    raw_date = str(head.get("vh_date") or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw_date)
    display_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else raw_date

    record = {
        "document_title": doc_title,
        "customer_name": head.get("customer_name") or "WALKIN",
        "patient_name": head.get("patient_name") or "",
        "doctor_name": head.get("doctor_name") or "",
        "bill_no": str(head.get("voucher_no") or head.get("bill_no") or "1"),
        "sale_date": display_date,
        "net_amount": head.get("net_amount") or 0.0,
        "remarks": head.get("remarks") or ("DUPLICATE COPY" if show_duplicate_copy else ""),
    }

    prepared_items = []
    units = {}
    companies = {}
    for idx, itm in enumerate(items, start=1):
        prepared_items.append({
            "item_id": idx,
            "item_name": itm.get("item_name") or "",
            "batch_no": itm.get("batch_no") or "",
            "expiry": itm.get("expiry") or "",
            "sale_qty": itm.get("sales_qty") if itm.get("sales_qty") is not None else itm.get("sale_qty", 0.0),
            "mrp": itm.get("mrp") or 0.0,
            "amount": itm.get("amount") or 0.0,
        })
        if itm.get("pack_size"):
            units[idx] = str(itm["pack_size"])
        if itm.get("location"):
            companies[idx] = str(itm["location"])

    profile = a6.PHARMACY_A6
    blocks = a6.build_layout(record, prepared_items, companies=companies, units=units, profile=profile)
    pages = a6.paginate(blocks, profile)
    page_profile = a6.content_profile(pages, profile)
    return pages, page_profile


def print_duplicate_a6_bill(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    parent=None,
    title: str = "DUPLICATE SALES BILL",
    show_dialog: bool = True,
    show_duplicate_copy: bool = True,
) -> bool:
    """Print duplicate sales bill on A6 (105 x 148 mm) via standard Windows print dialog."""
    try:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        from PySide6.QtGui import QPainter
    except ImportError as exc:
        raise ValueError("Printer support requires PySide6.") from exc

    pages, page_profile = _build_a6_pages_for_duplicate_bill(head, items, show_duplicate_copy=show_duplicate_copy)

    printer = QPrinter(QPrinter.HighResolution)
    layout = a6.qt_page_layout(page_profile)
    if layout is not None:
        printer.setPageLayout(layout)

    doc_title = title + (" [DUPLICATE COPY]" if show_duplicate_copy else "")
    if show_dialog:
        dialog = QPrintDialog(printer, parent)
        dialog.setWindowTitle(f"Print {doc_title} - {page_profile.size_label}")
        if dialog.exec() != QPrintDialog.Accepted:
            return False

    painter = QPainter()
    try:
        if not painter.begin(printer):
            raise RuntimeError("Could not start print job on printer.")
        painter.setRenderHint(QPainter.Antialiasing, True)
        a6.draw_pages_on_painter(painter, pages, painter.viewport(), page_profile)
    finally:
        if painter.isActive():
            painter.end()
    return True


def generate_duplicate_a6_pdf(
    head: dict[str, Any],
    items: list[dict[str, Any]],
    output_path: str,
    title: str = "DUPLICATE SALES BILL",
    show_duplicate_copy: bool = True,
) -> str:
    pages, page_profile = _build_a6_pages_for_duplicate_bill(head, items, show_duplicate_copy=show_duplicate_copy)
    pdf_bytes = a6.pages_to_pdf_bytes(pages, page_profile)
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)
    return output_path


class DuplicateSalesBillA6PreviewDialog(QDialog):
    """A6 Receipt Preview and Print Dialog for Duplicate Sales Bills."""

    def __init__(
        self,
        head: dict[str, Any],
        items: list[dict[str, Any]],
        show_duplicate: bool = True,
        show_duplicate_copy: bool | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._head = dict(head)
        self._items = list(items)
        if show_duplicate_copy is not None:
            self._show_duplicate = bool(show_duplicate_copy)
        else:
            self._show_duplicate = bool(show_duplicate)

        v_no = self._head.get("voucher_no") or 1
        self.setWindowTitle(f"Duplicate Sales Bill #{v_no} - A6 Receipt (105 x 148 mm)")
        self.resize(560, 780)
        self.setModal(True)

        p = palette()
        self.setStyleSheet(f"QDialog {{ background-color: {p['bg']}; color: {p['text']}; }}")

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ── Toolbar ──────────────────────────────────────────────────
        tb = QHBoxLayout()
        title_lbl = QLabel("A6 Receipt Preview")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #00838f;")
        tb.addWidget(title_lbl)

        v_num = self._head.get("voucher_no") or 1
        net_amt = fmt_amt(self._head.get("net_amount"))
        info_lbl = QLabel(f"Voucher #{v_num}   |   Net: ₹{net_amt}")
        info_lbl.setStyleSheet("font-weight: bold; color: #555;")
        tb.addSpacing(12)
        tb.addWidget(info_lbl)

        tb.addStretch()

        self._print_btn = QPushButton("🖨 Print (A6)")
        self._print_btn.setFixedHeight(30)
        self._print_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 0 14px;")
        self._print_btn.clicked.connect(self._on_print)
        tb.addWidget(self._print_btn)

        self._pdf_btn = QPushButton("📥 Save PDF")
        self._pdf_btn.setFixedHeight(30)
        self._pdf_btn.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; padding: 0 12px;")
        self._pdf_btn.clicked.connect(self._on_save_pdf)
        self._save_pdf_btn = self._pdf_btn
        tb.addWidget(self._pdf_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.setFixedHeight(30)
        self._close_btn.setStyleSheet("font-weight: bold; padding: 0 12px;")
        self._close_btn.clicked.connect(self.reject)
        tb.addWidget(self._close_btn)

        root.addLayout(tb)

        # ── Scroll Area for A6 Pages ─────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setStyleSheet("QScrollArea { background-color: #607d8b; border: 1px solid #cfd8dc; }")
        self._scroll.setAlignment(Qt.AlignCenter)

        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(16, 16, 16, 16)
        c_layout.setSpacing(16)
        c_layout.setAlignment(Qt.AlignCenter)

        # Render A6 layout blocks & pages
        self._pages, self._page_profile = _build_a6_pages_for_duplicate_bill(
            self._head, self._items, show_duplicate_copy=self._show_duplicate
        )

        dpi = 150.0
        scale_factor = dpi / 72.0
        w_px = int(round(self._page_profile.width_pt * scale_factor))
        h_px = int(round(self._page_profile.height_pt * scale_factor))

        for page_blocks in self._pages:
            pixmap = QPixmap(w_px, h_px)
            pixmap.fill(QColor("#ffffff"))

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            a6.draw_pages_on_painter(painter, [page_blocks], QRectF(0, 0, w_px, h_px), self._page_profile)
            painter.end()

            page_lbl = QLabel()
            page_lbl.setPixmap(pixmap)
            page_lbl.setFixedSize(w_px, h_px)
            page_lbl.setStyleSheet(
                "QLabel { background: white; border: 1px solid #37474f; border-radius: 2px; }"
            )
            c_layout.addWidget(page_lbl)

        self._scroll.setWidget(container)
        root.addWidget(self._scroll, 1)

    def _on_print(self):
        try:
            success = print_duplicate_a6_bill(
                self._head,
                self._items,
                parent=self,
                title="DUPLICATE SALES BILL",
                show_dialog=True,
                show_duplicate_copy=self._show_duplicate,
            )
            if success:
                self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Print Error", f"Failed to print A6 receipt:\n{exc}")

    def _on_save_pdf(self):
        v_no = self._head.get("voucher_no") or 1
        default_name = f"duplicate_sales_bill_A6_{v_no}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save A6 Duplicate Bill PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        try:
            generate_duplicate_a6_pdf(
                self._head,
                self._items,
                path,
                title="DUPLICATE SALES BILL",
                show_duplicate_copy=self._show_duplicate,
            )
            QMessageBox.information(self, "PDF Saved", f"A6 receipt PDF saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Failed to save PDF:\n{exc}")


# ══════════════════════════════════════════════════════════════════════
# 2. POPUP ENTRY FORM ("Sales Bill" Modal Dialog)
# ══════════════════════════════════════════════════════════════════════

class DuplicateSalesBillDialog(QDialog):
    """Modal dialog for creating and editing separate Duplicate Sales Bills.

    Layout copies the existing Sales Bill form exactly:
    - Top: Voucher No, Time.
    - Left: Cnt No, Type (Cash/Credit), Date.
    - Middle: Customer (default WALKIN, free text), Patient, Address, Bill No.
    - Right: Doctor (free text), Discount, Paid Amount.
    - Item entry row: Item Name, Pack Size, Item Stock (disabled), Batch #,
      Expiry, MRP, Batch Stock (disabled), Sale Qty, Disc, Down arrow Add button.
    - Grid: ItemName | PackSize | Location | BatchNo | Expiry | MRP | SalesDate |
      SalesQty | DiscAmt | Amount | Del.
    - Footer: Total Items, Remarks, Net Receivable box with calculation rules.
    - Checkbox: "Show DUPLICATE label" (checked by default).
    - Buttons: Save and Close.
    """

    saved = Signal()

    def __init__(self, dup_id: int | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._dup_id = dup_id
        self._items: list[dict[str, Any]] = []
        self._current_item_batches: list[dict[str, Any]] = []

        self.setWindowTitle("Sales Bill")
        self.setModal(True)
        self.resize(1150, 680)

        p = palette()
        self.setStyleSheet(
            f"QDialog {{ background-color: {p['bg']}; color: {p['text']}; font-family: {FONT_FAMILY}; }}"
            f"QLabel {{ color: {p['text']}; font-family: {FONT_FAMILY}; }}"
            f"QLineEdit, QComboBox, QDateEdit, QTextEdit {{"
            f"  background-color: {p['surface']}; color: {p['text']};"
            f"  border: 1px solid {p['border']}; border-radius: 2px; padding: 3px 5px;"
            f"}}"
            f"QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus {{"
            f"  border: 1px solid {p['accent']};"
            f"}}"
        )

        self._build_ui()

        if self._dup_id:
            self._load_existing_bill(self._dup_id)
        else:
            self._init_new_bill()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # ── Title strip ──────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel("Sales Bill")
        title_lbl.setStyleSheet("color: #cc0000; font-size: 20px; font-weight: bold;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        title_row.addWidget(self._lbl("Voucher No"))
        self._voucher_edit = QLineEdit()
        self._voucher_edit.setReadOnly(True)
        self._voucher_edit.setFixedWidth(80)
        self._voucher_edit.setAlignment(Qt.AlignCenter)
        self._voucher_edit.setStyleSheet("font-weight: bold;")
        title_row.addWidget(self._voucher_edit)

        title_row.addSpacing(12)
        title_row.addWidget(self._lbl("Time"))
        self._time_edit = QLineEdit(QTime.currentTime().toString("hh:mm AP"))
        self._time_edit.setFixedWidth(85)
        self._time_edit.setAlignment(Qt.AlignCenter)
        title_row.addWidget(self._time_edit)

        root.addLayout(title_row)

        # ── Header Form Group (Three Columns) ────────────────────────
        header_frame = QFrame()
        header_frame.setFrameShape(QFrame.StyledPanel)
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(8, 8, 8, 8)
        h_layout.setSpacing(16)

        # Column 1: Left (Cnt No, Type, Date)
        c1 = QGridLayout()
        c1.setHorizontalSpacing(8)
        c1.setVerticalSpacing(6)
        c1.addWidget(self._lbl("Cnt No :"), 0, 0, Qt.AlignRight)
        self._cnt_no = QLineEdit("")
        self._cnt_no.setFixedWidth(100)
        c1.addWidget(self._cnt_no, 0, 1)

        c1.addWidget(self._lbl("Type :"), 1, 0, Qt.AlignRight)
        self._type_combo = QComboBox()
        self._type_combo.addItems(["Cash", "Credit"])
        self._type_combo.setFixedWidth(100)
        c1.addWidget(self._type_combo, 1, 1)

        c1.addWidget(self._lbl("Date :"), 2, 0, Qt.AlignRight)
        self._date_edit = QDateEdit(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("dd-MM-yyyy")
        self._date_edit.setFixedWidth(100)
        c1.addWidget(self._date_edit, 2, 1)
        h_layout.addLayout(c1)

        # Column 2: Middle (Customer, Patient, Address, Bill No)
        c2 = QGridLayout()
        c2.setHorizontalSpacing(8)
        c2.setVerticalSpacing(6)
        c2.addWidget(self._lbl("Customer :"), 0, 0, Qt.AlignRight)
        self._customer_edit = QLineEdit("WALKIN")
        attach_uppercase(self._customer_edit)
        c2.addWidget(self._customer_edit, 0, 1)
        c2.addWidget(QLabel("(Outstanding: 0)"), 0, 2)

        c2.addWidget(self._lbl("Patient :"), 1, 0, Qt.AlignRight)
        self._patient_edit = QLineEdit("")
        attach_uppercase(self._patient_edit)
        c2.addWidget(self._patient_edit, 1, 1)
        bno_box = QHBoxLayout()
        bno_box.setSpacing(4)
        bno_box.addWidget(self._lbl("(Bill No)"))
        self._bill_no_edit = QLineEdit("")
        self._bill_no_edit.setFixedWidth(80)
        bno_box.addWidget(self._bill_no_edit)
        c2.addLayout(bno_box, 1, 2)

        c2.addWidget(self._lbl("Address :"), 2, 0, Qt.AlignRight)
        self._address_edit = QLineEdit("")
        attach_uppercase(self._address_edit)
        c2.addWidget(self._address_edit, 2, 1, 1, 2)
        h_layout.addLayout(c2, 2)

        # Column 3: Right (Doctor, Discount, Paid Amount)
        c3 = QGridLayout()
        c3.setHorizontalSpacing(8)
        c3.setVerticalSpacing(6)
        c3.addWidget(self._lbl("Doctor :"), 0, 0, Qt.AlignRight)
        self._doctor_edit = QLineEdit("DR. K.N. GHORPADE")
        attach_uppercase(self._doctor_edit)
        c3.addWidget(self._doctor_edit, 0, 1)

        c3.addWidget(self._lbl("Discount :"), 1, 0, Qt.AlignRight)
        self._bill_disc_edit = QLineEdit("0.00")
        self._bill_disc_edit.setFixedWidth(90)
        self._bill_disc_edit.setAlignment(Qt.AlignRight)
        self._bill_disc_edit.textEdited.connect(self._recalc_net_totals)
        c3.addWidget(self._bill_disc_edit, 1, 1)

        c3.addWidget(self._lbl("Paid Amount :"), 2, 0, Qt.AlignRight)
        self._paid_edit = QLineEdit("0.00")
        self._paid_edit.setFixedWidth(90)
        self._paid_edit.setAlignment(Qt.AlignRight)
        c3.addWidget(self._paid_edit, 2, 1)
        h_layout.addLayout(c3, 1)

        root.addWidget(header_frame)

        # ── Item Entry Row ───────────────────────────────────────────
        entry_frame = QFrame()
        entry_frame.setFrameShape(QFrame.StyledPanel)
        el = QHBoxLayout(entry_frame)
        el.setContentsMargins(6, 6, 6, 6)
        el.setSpacing(6)

        # Item Name
        box_item = QVBoxLayout()
        box_item.setSpacing(2)
        box_item.addWidget(self._lbl("* Item Name"))
        self._entry_item = QLineEdit()
        self._entry_item.setPlaceholderText("Medicine / Item name")
        attach_uppercase(self._entry_item)
        # Setup item autocomplete suggestions
        suggestions = DuplicateSalesDAO.get_item_name_suggestions(limit=5000)
        self._item_completer = QCompleter(suggestions, self)
        self._item_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._item_completer.setFilterMode(Qt.MatchContains)
        self._entry_item.setCompleter(self._item_completer)
        self._item_completer.activated[str].connect(self._on_item_name_chosen)
        self._entry_item.editingFinished.connect(self._on_item_editing_finished)
        box_item.addWidget(self._entry_item)
        el.addLayout(box_item, 3)

        # Pack Size
        box_pack = QVBoxLayout()
        box_pack.setSpacing(2)
        box_pack.addWidget(self._lbl("Pack Size"))
        self._entry_pack = QLineEdit("10x10")
        self._entry_pack.setFixedWidth(65)
        box_pack.addWidget(self._entry_pack)
        el.addLayout(box_pack)

        # Item Stock (Disabled/Hidden in Duplicate bill)
        box_istk = QVBoxLayout()
        box_istk.setSpacing(2)
        box_istk.addWidget(self._lbl("Item Stock"))
        self._entry_item_stock = QLineEdit("--")
        self._entry_item_stock.setReadOnly(True)
        self._entry_item_stock.setEnabled(False)
        self._entry_item_stock.setFixedWidth(65)
        self._entry_item_stock.setAlignment(Qt.AlignCenter)
        box_istk.addWidget(self._entry_item_stock)
        el.addLayout(box_istk)

        # Batch #
        box_batch = QVBoxLayout()
        box_batch.setSpacing(2)
        box_batch.addWidget(self._lbl("Batch #"))
        self._entry_batch = QLineEdit("")
        self._entry_batch.setFixedWidth(80)
        attach_uppercase(self._entry_batch)
        box_batch.addWidget(self._entry_batch)
        el.addLayout(box_batch)

        # Expiry
        box_exp = QVBoxLayout()
        box_exp.setSpacing(2)
        box_exp.addWidget(self._lbl("Expiry"))
        self._entry_exp = QLineEdit("12/28")
        self._entry_exp.setFixedWidth(60)
        box_exp.addWidget(self._entry_exp)
        el.addLayout(box_exp)

        # MRP
        box_mrp = QVBoxLayout()
        box_mrp.setSpacing(2)
        box_mrp.addWidget(self._lbl("MRP"))
        self._entry_mrp = QLineEdit("0.00")
        self._entry_mrp.setFixedWidth(70)
        self._entry_mrp.setAlignment(Qt.AlignRight)
        box_mrp.addWidget(self._entry_mrp)
        el.addLayout(box_mrp)

        # Batch Stock (Disabled/Hidden in Duplicate bill)
        box_bstk = QVBoxLayout()
        box_bstk.setSpacing(2)
        box_bstk.addWidget(self._lbl("Batch Stock"))
        self._entry_batch_stock = QLineEdit("--")
        self._entry_batch_stock.setReadOnly(True)
        self._entry_batch_stock.setEnabled(False)
        self._entry_batch_stock.setFixedWidth(65)
        self._entry_batch_stock.setAlignment(Qt.AlignCenter)
        box_bstk.addWidget(self._entry_batch_stock)
        el.addLayout(box_bstk)

        # Sale Qty
        box_qty = QVBoxLayout()
        box_qty.setSpacing(2)
        box_qty.addWidget(self._lbl("Sale Qty"))
        self._entry_qty = QLineEdit("1")
        self._entry_qty.setFixedWidth(60)
        self._entry_qty.setAlignment(Qt.AlignRight)
        box_qty.addWidget(self._entry_qty)
        el.addLayout(box_qty)

        # Disc %
        box_disc = QVBoxLayout()
        box_disc.setSpacing(2)
        box_disc.addWidget(self._lbl("Disc"))
        self._entry_disc = QLineEdit("0.00")
        self._entry_disc.setFixedWidth(55)
        self._entry_disc.setAlignment(Qt.AlignRight)
        box_disc.addWidget(self._entry_disc)
        el.addLayout(box_disc)

        self._entry_batch.editingFinished.connect(self._on_batch_editing_finished)

        # Connect returnPressed for smooth keyboard progression
        self._entry_item.returnPressed.connect(self._on_item_return_pressed)
        self._entry_batch.returnPressed.connect(self._entry_qty.setFocus)
        self._entry_qty.returnPressed.connect(self._entry_mrp.setFocus)
        self._entry_mrp.returnPressed.connect(self._entry_disc.setFocus)
        self._entry_disc.returnPressed.connect(self._on_add_item)

        # Add Button (Down arrow)
        box_btn = QVBoxLayout()
        box_btn.setSpacing(2)
        box_btn.addWidget(QLabel(" "))
        self._add_btn = QPushButton("↓")
        self._add_btn.setFixedWidth(36)
        self._add_btn.setStyleSheet("font-size: 16px; font-weight: bold; background-color: #00bcd4; color: white;")
        self._add_btn.setToolTip("Add item row")
        self._add_btn.clicked.connect(self._on_add_item)
        box_btn.addWidget(self._add_btn)
        el.addLayout(box_btn)

        root.addWidget(entry_frame)

        # ── Item Grid Table ──────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "ItemName", "PackSize", "Location", "BatchNo", "Expiry",
            "MRP", "SalesDate", "SalesQty", "DiscAmt", "Amount", "Del."
        ])
        th = self._table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 10):
            th.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(10, QHeaderView.Fixed)
        self._table.setColumnWidth(10, 45)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self._table, 1)

        # ── Footer: Remarks & Net Receivable ─────────────────────────
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(14)

        # Left Column: Total Items & Remarks
        left_box = QVBoxLayout()
        left_box.setSpacing(6)
        ti_box = QHBoxLayout()
        ti_box.addWidget(self._lbl("Total Items :"))
        self._total_items_val = QLineEdit("0")
        self._total_items_val.setReadOnly(True)
        self._total_items_val.setFixedWidth(60)
        self._total_items_val.setAlignment(Qt.AlignCenter)
        ti_box.addWidget(self._total_items_val)
        ti_box.addStretch()
        left_box.addLayout(ti_box)

        left_box.addWidget(self._lbl("Remarks :"))
        self._remarks_edit = QTextEdit()
        self._remarks_edit.setFixedHeight(75)
        left_box.addWidget(self._remarks_edit)

        # Checkbox: Show DUPLICATE label
        self._show_duplicate_chk = QCheckBox("Show DUPLICATE label on print")
        self._show_duplicate_chk.setChecked(True)
        self._show_duplicate_chk.setStyleSheet("font-weight: bold; color: #00838f;")
        left_box.addWidget(self._show_duplicate_chk)

        footer_layout.addLayout(left_box, 1)

        # Right Column: Net Receivable GroupBox
        net_grp = QGroupBox("Net Receivable")
        net_grp.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #b0bec5; margin-top: 8px; padding-top: 8px; }")
        grid_net = QGridLayout(net_grp)
        grid_net.setHorizontalSpacing(10)
        grid_net.setVerticalSpacing(4)

        grid_net.addWidget(self._lbl("Total Amount :"), 0, 0, Qt.AlignRight)
        self._tot_amt_edit = QLineEdit("0.00")
        self._tot_amt_edit.setReadOnly(True)
        self._tot_amt_edit.setFixedWidth(100)
        self._tot_amt_edit.setAlignment(Qt.AlignRight)
        grid_net.addWidget(self._tot_amt_edit, 0, 1)

        grid_net.addWidget(self._lbl("Less Bill Discount :"), 1, 0, Qt.AlignRight)
        self._net_less_disc = QLineEdit("0.00")
        self._net_less_disc.setReadOnly(True)
        self._net_less_disc.setFixedWidth(100)
        self._net_less_disc.setAlignment(Qt.AlignRight)
        grid_net.addWidget(self._net_less_disc, 1, 1)

        grid_net.addWidget(self._lbl("Less CN Amt :"), 0, 2, Qt.AlignRight)
        self._less_cn_edit = QLineEdit("0.00")
        self._less_cn_edit.setFixedWidth(90)
        self._less_cn_edit.setAlignment(Qt.AlignRight)
        self._less_cn_edit.textEdited.connect(self._recalc_net_totals)
        grid_net.addWidget(self._less_cn_edit, 0, 3)

        self._cn_btn = QPushButton("Credit Note")
        self._cn_btn.setEnabled(False)  # Hidden/disabled as requested
        self._cn_btn.setVisible(False)
        grid_net.addWidget(self._cn_btn, 0, 4)

        grid_net.addWidget(self._lbl("Add Dr Amt :"), 1, 2, Qt.AlignRight)
        self._add_dr_edit = QLineEdit("0.00")
        self._add_dr_edit.setFixedWidth(90)
        self._add_dr_edit.setAlignment(Qt.AlignRight)
        self._add_dr_edit.textEdited.connect(self._recalc_net_totals)
        grid_net.addWidget(self._add_dr_edit, 1, 3)

        grid_net.addWidget(self._lbl("Round off :"), 2, 0, Qt.AlignRight)
        self._round_off_edit = QLineEdit("0.00")
        self._round_off_edit.setReadOnly(True)
        self._round_off_edit.setFixedWidth(100)
        self._round_off_edit.setAlignment(Qt.AlignRight)
        grid_net.addWidget(self._round_off_edit, 2, 1)

        grid_net.addWidget(self._lbl("Net Amount :"), 2, 2, Qt.AlignRight)
        self._net_amt_edit = QLineEdit("0.00")
        self._net_amt_edit.setReadOnly(True)
        self._net_amt_edit.setFixedWidth(90)
        self._net_amt_edit.setAlignment(Qt.AlignRight)
        self._net_amt_edit.setStyleSheet("font-weight: bold; font-size: 15px; color: #b71c1c;")
        grid_net.addWidget(self._net_amt_edit, 2, 3)

        footer_layout.addWidget(net_grp, 1)
        root.addLayout(footer_layout)

        # ── Buttons: Save, Print, Close ──────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedWidth(90)
        self._save_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; height: 28px;")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        self._print_btn = QPushButton("Print")
        self._print_btn.setFixedWidth(90)
        self._print_btn.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; height: 28px;")
        self._print_btn.clicked.connect(self._on_print)
        btn_row.addWidget(self._print_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.setFixedWidth(90)
        self._close_btn.setStyleSheet("font-weight: bold; height: 28px;")
        self._close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._close_btn)

        root.addLayout(btn_row)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        return lbl

    def _init_new_bill(self):
        v_next = DuplicateSalesDAO.get_next_voucher_no()
        self._voucher_edit.setText(str(v_next))
        self._date_edit.setDate(QDate.currentDate())
        self._time_edit.setText(QTime.currentTime().toString("hh:mm AP"))
        self._items = []
        self._current_item_batches = []
        self._refresh_table()

    def _on_item_name_chosen(self, text: str):
        self._entry_item.setText(text)
        self._autofill_item_and_batch(text)

    def _on_item_editing_finished(self):
        text = self._entry_item.text().strip()
        if text:
            self._autofill_item_and_batch(text)

    def _on_item_return_pressed(self):
        text = self._entry_item.text().strip()
        if text:
            self._autofill_item_and_batch(text)
        self._entry_qty.setFocus()
        self._entry_qty.selectAll()

    def _autofill_item_and_batch(self, item_name: str):
        batches = DuplicateSalesDAO.get_item_batch_suggestions(item_name)
        self._current_item_batches = batches
        if batches:
            top = batches[0]
            if top.get("batch_no"):
                self._entry_batch.setText(str(top["batch_no"]))
            if top.get("mrp") is not None and float(top["mrp"]) > 0:
                self._entry_mrp.setText(f"{float(top['mrp']):.2f}")
            if top.get("expiry"):
                self._entry_exp.setText(_format_expiry_display(str(top["expiry"])))
            if top.get("pack_size"):
                self._entry_pack.setText(str(top["pack_size"]))

            batch_list = [str(b["batch_no"]) for b in batches if b.get("batch_no")]
            if batch_list:
                b_completer = QCompleter(batch_list, self)
                b_completer.setCaseSensitivity(Qt.CaseInsensitive)
                self._entry_batch.setCompleter(b_completer)
                b_completer.activated[str].connect(self._on_batch_chosen)

    def _on_batch_chosen(self, batch_no: str):
        self._entry_batch.setText(batch_no)
        self._autofill_from_batch(batch_no)

    def _on_batch_editing_finished(self):
        batch_no = self._entry_batch.text().strip()
        if batch_no:
            self._autofill_from_batch(batch_no)

    def _autofill_from_batch(self, batch_no: str | None = None):
        if not batch_no:
            batch_no = self._entry_batch.text().strip()
        if not batch_no:
            return
        item_name = self._entry_item.text().strip()
        matched = None
        for b in getattr(self, "_current_item_batches", []):
            if str(b.get("batch_no", "")).strip().upper() == batch_no.strip().upper():
                matched = b
                break
        if not matched and item_name:
            matched = DuplicateSalesDAO.get_batch_details(item_name, batch_no)
        if matched:
            if matched.get("mrp") is not None and float(matched["mrp"]) > 0:
                self._entry_mrp.setText(f"{float(matched['mrp']):.2f}")
            if matched.get("expiry"):
                self._entry_exp.setText(_format_expiry_display(str(matched["expiry"])))
            if matched.get("pack_size"):
                self._entry_pack.setText(str(matched["pack_size"]))

    def _load_existing_bill(self, dup_id: int):
        head = DuplicateSalesDAO.get_bill_by_id(dup_id)
        if not head:
            QMessageBox.warning(self, "Error", f"Duplicate bill #{dup_id} not found.")
            self.reject()
            return

        self._voucher_edit.setText(str(head.get("voucher_no") or ""))
        if head.get("vh_date"):
            qd = QDate.fromString(head["vh_date"], "yyyy-MM-dd")
            if qd.isValid():
                self._date_edit.setDate(qd)
            else:
                qd2 = QDate.fromString(head["vh_date"], "dd-MM-yyyy")
                if qd2.isValid():
                    self._date_edit.setDate(qd2)
        self._time_edit.setText(head.get("vh_time") or "")
        self._cnt_no.setText(head.get("cnt_no") or "")
        self._type_combo.setCurrentText(head.get("bill_type") or "Cash")
        self._customer_edit.setText(head.get("customer_name") or "WALKIN")
        self._patient_edit.setText(head.get("patient_name") or "")
        self._bill_no_edit.setText(head.get("bill_no") or "")
        self._address_edit.setText(head.get("address") or "")
        self._doctor_edit.setText(head.get("doctor_name") or "")
        self._bill_disc_edit.setText(fmt_amt(head.get("discount")))
        self._paid_edit.setText(fmt_amt(head.get("paid_amount")))
        self._remarks_edit.setPlainText(head.get("remarks") or "")
        self._less_cn_edit.setText(fmt_amt(head.get("less_cn_amt")))
        self._add_dr_edit.setText(fmt_amt(head.get("add_dr_amt")))

        self._items = DuplicateSalesDAO.get_bill_items(dup_id)
        self._refresh_table()

    def _on_add_item(self):
        item_name = self._entry_item.text().strip()
        if not item_name:
            QMessageBox.warning(self, "Validation", "Item Name is required.")
            self._entry_item.setFocus()
            return

        qty = _safe_float(self._entry_qty.text())
        if qty <= 0:
            QMessageBox.warning(self, "Validation", "Sale Qty must be greater than zero.")
            self._entry_qty.setFocus()
            return

        mrp = _safe_float(self._entry_mrp.text())
        disc_pct = _safe_float(self._entry_disc.text())
        disc_amt = round(qty * mrp * (disc_pct / 100.0), 2) if disc_pct > 0 else 0.0
        line_amt = round((qty * mrp) - disc_amt, 2)

        sale_date = self._date_edit.date().toString("dd-MM-yyyy")

        row_dict = {
            "item_name": item_name,
            "pack_size": self._entry_pack.text().strip(),
            "location": "",
            "batch_no": self._entry_batch.text().strip(),
            "expiry": self._entry_exp.text().strip(),
            "mrp": mrp,
            "sales_date": sale_date,
            "sales_qty": qty,
            "disc": disc_pct,
            "disc_amt": disc_amt,
            "amount": line_amt,
        }
        self._items.append(row_dict)
        self._refresh_table()

        # Clear entry fields for next item
        self._entry_item.clear()
        self._entry_batch.clear()
        self._entry_pack.setText("10x10")
        self._entry_exp.setText("12/28")
        self._entry_mrp.setText("0.00")
        self._entry_qty.setText("1")
        self._entry_disc.setText("0.00")
        self._current_item_batches = []
        self._entry_item.setFocus()

    def _on_delete_row(self, row_idx: int):
        if 0 <= row_idx < len(self._items):
            self._items.pop(row_idx)
            self._refresh_table()

    def _refresh_table(self):
        self._table.setRowCount(len(self._items))
        for r, itm in enumerate(self._items):
            self._table.setItem(r, 0, QTableWidgetItem(str(itm.get("item_name") or "")))
            self._table.setItem(r, 1, QTableWidgetItem(str(itm.get("pack_size") or "")))
            self._table.setItem(r, 2, QTableWidgetItem(str(itm.get("location") or "")))
            self._table.setItem(r, 3, QTableWidgetItem(str(itm.get("batch_no") or "")))
            self._table.setItem(r, 4, QTableWidgetItem(str(itm.get("expiry") or "")))

            mrp_cell = QTableWidgetItem(fmt_amt(itm.get("mrp")))
            mrp_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r, 5, mrp_cell)

            self._table.setItem(r, 6, QTableWidgetItem(str(itm.get("sales_date") or "")))

            qty_cell = QTableWidgetItem(fmt_qty(itm.get("sales_qty")))
            qty_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r, 7, qty_cell)

            damt_cell = QTableWidgetItem(fmt_amt(itm.get("disc_amt")))
            damt_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r, 8, damt_cell)

            amt_cell = QTableWidgetItem(fmt_amt(itm.get("amount")))
            amt_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r, 9, amt_cell)

            del_btn = QPushButton("✕")
            del_btn.setFixedWidth(28)
            del_btn.setStyleSheet("color: red; font-weight: bold;")
            del_btn.clicked.connect(lambda chk=False, idx=r: self._on_delete_row(idx))
            self._table.setCellWidget(r, 10, del_btn)

        self._total_items_val.setText(str(len(self._items)))
        self._recalc_net_totals()

    def _recalc_net_totals(self):
        tot_amount = sum(_safe_float(i.get("amount")) for i in self._items)
        self._tot_amt_edit.setText(fmt_amt(tot_amount))

        bill_disc = _safe_float(self._bill_disc_edit.text())
        self._net_less_disc.setText(fmt_amt(bill_disc))

        less_cn = _safe_float(self._less_cn_edit.text())
        add_dr = _safe_float(self._add_dr_edit.text())

        raw_net = tot_amount - bill_disc - less_cn + add_dr
        round_net = round(raw_net)
        round_off = round_net - raw_net

        self._round_off_edit.setText(f"{round_off:+.2f}")
        self._net_amt_edit.setText(fmt_amt(round_net))

    def _gather_head_dict(self) -> dict[str, Any]:
        fy_obj = financial_year.get_active_financial_year()
        fy_name = fy_obj.get("name") if fy_obj else ""

        return {
            "voucher_no": int(_safe_float(self._voucher_edit.text()) or 1),
            "financial_year": fy_name,
            "vh_date": self._date_edit.date().toString("yyyy-MM-dd"),
            "vh_time": self._time_edit.text().strip(),
            "cnt_no": self._cnt_no.text().strip(),
            "bill_type": self._type_combo.currentText(),
            "customer_name": self._customer_edit.text().strip() or "WALKIN",
            "patient_name": self._patient_edit.text().strip(),
            "bill_no": self._bill_no_edit.text().strip(),
            "address": self._address_edit.text().strip(),
            "doctor_name": self._doctor_edit.text().strip(),
            "discount": _safe_float(self._bill_disc_edit.text()),
            "paid_amount": _safe_float(self._paid_edit.text()),
            "total_items": len(self._items),
            "remarks": self._remarks_edit.toPlainText().strip(),
            "total_amount": _safe_float(self._tot_amt_edit.text()),
            "less_bill_discount": _safe_float(self._net_less_disc.text()),
            "less_cn_amt": _safe_float(self._less_cn_edit.text()),
            "add_dr_amt": _safe_float(self._add_dr_edit.text()),
            "round_off": _safe_float(self._round_off_edit.text()),
            "net_amount": _safe_float(self._net_amt_edit.text()),
            "created_by": "admin",
        }

    def _on_save(self) -> bool:
        if not self._items:
            QMessageBox.warning(self, "Validation", "Cannot save a bill with no items.")
            return False

        head = self._gather_head_dict()

        try:
            if self._dup_id:
                DuplicateSalesDAO.update_bill(self._dup_id, head, self._items)
            else:
                self._dup_id = DuplicateSalesDAO.insert_bill(head, self._items)
                self._voucher_edit.setText(str(head["voucher_no"]))

            self.saved.emit()

            reply = QMessageBox.question(
                self,
                "Saved",
                f"Duplicate Sales Bill Voucher #{head['voucher_no']} saved successfully.\n"
                "(Print-only record: no stock or ledger was affected)\n\n"
                "Would you like to print now on A6?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self._on_print()

            self.accept()
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Failed to save Duplicate Sales Bill:\n{exc}")
            return False

    def _on_print(self):
        if not self._items:
            QMessageBox.warning(self, "Print", "Cannot print an empty bill.")
            return

        head = self._gather_head_dict()
        show_dup = self._show_duplicate_chk.isChecked()
        dlg = DuplicateSalesBillA6PreviewDialog(head, self._items, show_duplicate=show_dup, parent=self)
        dlg.exec()


# ══════════════════════════════════════════════════════════════════════
# 3. LIST PAGE ("Duplicate Sales Bill List")
# ══════════════════════════════════════════════════════════════════════

class DuplicateSalesBillListPage(QWidget):
    """Duplicate Sales Bill List screen matching the Debit Note List layout."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._build_ui()
        active_fy = financial_year.get_active_financial_year() or financial_year.ensure_default_financial_year()
        if active_fy and active_fy.get("start_date") and active_fy.get("end_date"):
            s_qd = QDate.fromString(active_fy["start_date"], "yyyy-MM-dd")
            e_qd = QDate.fromString(active_fy["end_date"], "yyyy-MM-dd")
            if s_qd.isValid() and e_qd.isValid():
                self._from_date.setDate(s_qd)
                self._to_date.setDate(e_qd)
        self._load_bills()

    def set_history_financial_year(self, year: dict | None) -> None:
        """Scope listing date filter to chosen financial year without altering active FY."""
        if not year:
            return
        start_iso = year.get("start_date") or ""
        end_iso = year.get("end_date") or ""
        if start_iso and end_iso:
            s_qd = QDate.fromString(start_iso, "yyyy-MM-dd")
            e_qd = QDate.fromString(end_iso, "yyyy-MM-dd")
            if s_qd.isValid():
                self._from_date.setDate(s_qd)
            if e_qd.isValid():
                self._to_date.setDate(e_qd)
            self._load_bills()

    def _build_ui(self):
        p = palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Cyan Header Band with Bold Red Title ─────────────────────
        header_band = QWidget()
        header_band.setFixedHeight(48)
        header_band.setStyleSheet("background-color: #00bcd4; border-bottom: 1px solid #0097a7;")
        hl = QHBoxLayout(header_band)
        hl.setContentsMargins(16, 0, 16, 0)

        title_lbl = QLabel("Duplicate Sales Bill List")
        title_lbl.setStyleSheet("color: #cc0000; font-size: 22px; font-weight: bold; background: transparent;")
        hl.addWidget(title_lbl)
        hl.addStretch()
        layout.addWidget(header_band)

        # ── Toolbar (New, Edit, Print) ───────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(46)
        toolbar.setStyleSheet(f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 0, 12, 0)
        tl.setSpacing(8)

        self._new_btn = QPushButton("New")
        self._new_btn.setFixedWidth(80)
        self._new_btn.setStyleSheet("background-color: #00bcd4; color: white; font-weight: bold; height: 26px;")
        self._new_btn.clicked.connect(self._on_new)
        tl.addWidget(self._new_btn)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setFixedWidth(80)
        self._edit_btn.setStyleSheet(f"background-color: {p['surface_alt']}; color: {p['text']}; font-weight: bold; height: 26px;")
        self._edit_btn.clicked.connect(self._on_edit)
        tl.addWidget(self._edit_btn)

        self._print_btn = QPushButton("Print")
        self._print_btn.setFixedWidth(80)
        self._print_btn.setStyleSheet(f"background-color: {p['surface_alt']}; color: {p['text']}; font-weight: bold; height: 26px;")
        self._print_btn.clicked.connect(self._on_print)
        tl.addWidget(self._print_btn)

        tl.addStretch()
        layout.addWidget(toolbar)

        # ── Filter Row ───────────────────────────────────────────────
        filter_bar = QWidget()
        filter_bar.setFixedHeight(44)
        filter_bar.setStyleSheet(f"background-color: {p['bg']}; border-bottom: 1px solid {p['border']};")
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(12, 0, 12, 0)
        fl.setSpacing(6)

        # From Date
        fl.addWidget(QLabel("From"))
        self._from_date = QDateEdit(QDate.currentDate().addMonths(-1))
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("dd/MM/yyyy")
        self._from_date.setFixedWidth(115)
        fl.addWidget(self._from_date)

        # Date Field Selector (VhDate)
        self._date_field_combo = QComboBox()
        self._date_field_combo.addItem("VhDate")
        self._date_field_combo.setFixedWidth(85)
        fl.addWidget(self._date_field_combo)

        # To Date
        fl.addWidget(QLabel("To"))
        self._to_date = QDateEdit(QDate.currentDate())
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("dd/MM/yyyy")
        self._to_date.setFixedWidth(115)
        fl.addWidget(self._to_date)

        # Go Button
        self._go_btn = QPushButton("Go")
        self._go_btn.setFixedWidth(50)
        self._go_btn.clicked.connect(self._load_bills)
        fl.addWidget(self._go_btn)

        fl.addStretch()

        # Search Box (Customer / Bill No / Voucher No)
        fl.addWidget(QLabel("Search"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("[Search Customer / Bill / Voucher]")
        self._search_edit.setFixedWidth(240)
        self._search_edit.returnPressed.connect(self._load_bills)
        fl.addWidget(self._search_edit)

        self._filter_btn = QPushButton("Filter")
        self._filter_btn.setFixedWidth(65)
        self._filter_btn.clicked.connect(self._load_bills)
        fl.addWidget(self._filter_btn)

        layout.addWidget(filter_bar)

        # ── Grid Table ───────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "VhType", "VhNo", "VhDate", "VhTime", "Customer", "Doctor", "Total Items", "Net Amount"
        ])
        th = self._table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(4, QHeaderView.Stretch)
        th.setSectionResizeMode(5, QHeaderView.Stretch)
        th.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        th.setSectionResizeMode(7, QHeaderView.ResizeToContents)

        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(True)
        self._table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self._table, 1)

    def _load_bills(self):
        from_str = self._from_date.date().toString("yyyy-MM-dd")
        to_str = self._to_date.date().toString("yyyy-MM-dd")
        search_txt = self._search_edit.text().strip()

        rows = DuplicateSalesDAO.search_bills(
            from_date=from_str,
            to_date=to_str,
            search_text=search_txt,
        )

        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            t_cell = QTableWidgetItem(row.get("bill_type") or "Cash")
            t_cell.setData(Qt.UserRole, row["id"])
            self._table.setItem(r, 0, t_cell)

            vno_cell = QTableWidgetItem(str(row.get("voucher_no") or ""))
            vno_cell.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._table.setItem(r, 1, vno_cell)

            dt_cell = QTableWidgetItem(row.get("vh_date") or "")
            dt_cell.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._table.setItem(r, 2, dt_cell)

            tm_cell = QTableWidgetItem(row.get("vh_time") or "")
            tm_cell.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._table.setItem(r, 3, tm_cell)

            cust_text = row.get("customer_name") or "WALKIN"
            if row.get("patient_name"):
                cust_text += f" ({row['patient_name']})"
            self._table.setItem(r, 4, QTableWidgetItem(cust_text))

            self._table.setItem(r, 5, QTableWidgetItem(row.get("doctor_name") or ""))

            ti_cell = QTableWidgetItem(str(row.get("total_items") or "0"))
            ti_cell.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._table.setItem(r, 6, ti_cell)

            net_cell = QTableWidgetItem(fmt_amt(row.get("net_amount")))
            net_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r, 7, net_cell)

    def _selected_dup_id(self) -> int | None:
        sel = self._table.selectedItems()
        if not sel:
            return None
        row = sel[0].row()
        item = self._table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_new(self):
        dlg = DuplicateSalesBillDialog(dup_id=None, parent=self)
        dlg.saved.connect(self._load_bills)
        dlg.exec()

    def _on_edit(self):
        dup_id = self._selected_dup_id()
        if not dup_id:
            QMessageBox.information(self, "Duplicate Sales Bill", "Please select a duplicate bill to edit.")
            return
        dlg = DuplicateSalesBillDialog(dup_id=dup_id, parent=self)
        dlg.saved.connect(self._load_bills)
        dlg.exec()

    def _on_print(self):
        dup_id = self._selected_dup_id()
        if not dup_id:
            QMessageBox.information(self, "Duplicate Sales Bill", "Please select a duplicate bill to print.")
            return

        head = DuplicateSalesDAO.get_bill_by_id(dup_id)
        if not head:
            QMessageBox.warning(self, "Error", "Bill record not found.")
            return

        items = DuplicateSalesDAO.get_bill_items(dup_id)
        dlg = DuplicateSalesBillA6PreviewDialog(head, items, show_duplicate=True, parent=self)
        dlg.exec()
