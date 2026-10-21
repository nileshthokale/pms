"""Crystal Reports page builders for the Detailed Ledger reports.

The three ledger screens (Supplier, Customer and Itemwise) display their live
data in a table.  This module converts the same report dictionaries into A4
landscape ReportPage objects, so the records can be previewed and printed with
the standard Crystal Reports layout used by the other report screens.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from core.doc_formatter import format_document_number
from ui.crystal_report_viewer import (
    PAGE_HEIGHT_LANDSCAPE,
    PAGE_WIDTH_LANDSCAPE,
    BlockKind,
    CrystalReportViewer,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    fmt_date_dash,
    get_default_store_identity,
    print_or_export_report_pages,
)

# Matches the available body area of the other landscape report pages.
_MAX_LANDSCAPE_BODY_HEIGHT = 635.0


def _paginate_landscape(
    header: ReportHeaderData,
    blocks: List[ReportBlock],
    table_header_block: ReportBlock,
) -> List[ReportPage]:
    """Split ledger blocks across A4 landscape pages, repeating the header row."""
    if not blocks:
        return [
            ReportPage(
                page_num=1,
                total_pages=1,
                header=header,
                blocks=[],
                orientation="landscape",
                page_width=PAGE_WIDTH_LANDSCAPE,
                page_height=PAGE_HEIGHT_LANDSCAPE,
            )
        ]

    pages: List[ReportPage] = []
    current_blocks: List[ReportBlock] = []
    current_h = 0.0

    for block in blocks:
        if current_blocks and current_h + block.height > _MAX_LANDSCAPE_BODY_HEIGHT:
            pages.append(
                ReportPage(
                    page_num=len(pages) + 1,
                    total_pages=0,
                    header=header,
                    blocks=current_blocks,
                    orientation="landscape",
                    page_width=PAGE_WIDTH_LANDSCAPE,
                    page_height=PAGE_HEIGHT_LANDSCAPE,
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
                orientation="landscape",
                page_width=PAGE_WIDTH_LANDSCAPE,
                page_height=PAGE_HEIGHT_LANDSCAPE,
            )
        )

    total = len(pages)
    for page in pages:
        page.total_pages = total
    return pages


def _report_header(
    title: str, line_2: str, line_3: str
) -> ReportHeaderData:
    store_name, store_address = get_default_store_identity()
    return ReportHeaderData(
        store_name=store_name,
        store_address=store_address,
        header_line_1=title,
        header_line_2=line_2,
        header_line_3=line_3,
    )


def _warning_block(warning: Any) -> Optional[ReportBlock]:
    text = str(warning or "").strip()
    if not text:
        return None
    return ReportBlock(
        kind=BlockKind.GROUP_HEADER,
        height=16.0,
        data={"text": f"Note: {text}"},
    )


def build_party_ledger_pages(
    report: Dict[str, Any], ledger_type: str
) -> List[ReportPage]:
    """Build Supplier/Customer Ledger pages from a ledger report dictionary."""
    is_customer = ledger_type.strip().lower().startswith("customer")
    party_key = "customer" if is_customer else "supplier"
    name_key = "customer_name" if is_customer else "supplier_name"
    party = report.get(party_key) or {}

    party_name = str(party.get(name_key) or "")
    city = str(party.get("city") or "")
    contact = str(party.get("contact_no") or "")

    from_date = str(report.get("from_date") or "")
    to_date = str(report.get("to_date") or "")
    opening = float(report.get("opening_balance") or 0.0)
    opening_type = str(report.get("opening_balance_type") or "")
    total_debit = float(report.get("total_debit") or 0.0)
    total_credit = float(report.get("total_credit") or 0.0)
    closing = float(report.get("closing_balance") or 0.0)
    closing_type = str(report.get("closing_balance_type") or "")
    rows = report.get("rows") or []

    parts = [f"Party: {party_name}"] if party_name else ["Party: -"]
    if city:
        parts.append(f"({city})")
    if contact:
        parts.append(f"Ph: {contact}")

    header = _report_header(
        title=f"{'CUSTOMER' if is_customer else 'SUPPLIER'} LEDGER",
        line_2="  ".join(parts),
        line_3=(
            f"From: {fmt_date_dash(from_date)} To: {fmt_date_dash(to_date)}  |  "
            f"Opening: {opening:,.2f} {opening_type}  |  "
            f"Closing: {closing:,.2f} {closing_type}"
        ),
    )

    cols = [
        "Date",
        "Particulars",
        "Voucher Type",
        "Voucher No",
        "Debit (Dr)",
        "Credit (Cr)",
        "Balance",
    ]
    # Sums to CONTENT_WIDTH_LANDSCAPE (1053.0).
    widths = [85.0, 430.0, 95.0, 90.0, 110.0, 110.0, 133.0]
    aligns = ["center", "left", "left", "left", "right", "right", "right"]

    table_header_block = ReportBlock(
        kind=BlockKind.TABLE_HEADER,
        height=24.0,
        data={"columns": cols, "widths": widths, "aligns": aligns},
    )

    blocks: List[ReportBlock] = []
    warning_block = _warning_block(report.get("warning"))
    if warning_block is not None:
        blocks.append(warning_block)
    blocks.append(table_header_block)

    blocks.append(
        ReportBlock(
            kind=BlockKind.DATA_ROW,
            height=18.0,
            data={
                "cells": [
                    fmt_date_dash(from_date),
                    "*** OPENING BALANCE ***",
                    "-",
                    "-",
                    "",
                    "",
                    f"{opening:,.2f} {opening_type}".strip(),
                ],
                "widths": widths,
                "aligns": aligns,
            },
        )
    )

    for txn in rows:
        debit = float(txn.get("debit") or 0.0)
        credit = float(txn.get("credit") or 0.0)
        balance = float(txn.get("running_balance") or 0.0)
        balance_type = str(txn.get("running_balance_type") or "")
        blocks.append(
            ReportBlock(
                kind=BlockKind.DATA_ROW,
                height=18.0,
                data={
                    "cells": [
                        fmt_date_dash(txn.get("transaction_date")),
                        str(txn.get("particulars") or ""),
                        str(txn.get("voucher_type") or ""),
                        format_document_number(txn.get("voucher_no")),
                        f"{debit:,.2f}" if debit else "",
                        f"{credit:,.2f}" if credit else "",
                        f"{balance:,.2f} {balance_type}".strip(),
                    ],
                    "widths": widths,
                    "aligns": aligns,
                },
            )
        )

    prefix_w = sum(widths[:4])
    blocks.append(
        ReportBlock(
            kind=BlockKind.GRAND_TOTAL,
            height=22.0,
            data={
                "custom_cells": [
                    {
                        "width": prefix_w,
                        "text": "TOTALS & CLOSING BALANCE :",
                        "align": "right",
                        "is_bold": True,
                    },
                    {
                        "width": widths[4],
                        "text": f"{total_debit:,.2f}",
                        "align": "right",
                        "is_bold": True,
                    },
                    {
                        "width": widths[5],
                        "text": f"{total_credit:,.2f}",
                        "align": "right",
                        "is_bold": True,
                    },
                    {
                        "width": widths[6],
                        "text": f"{closing:,.2f} {closing_type}".strip(),
                        "align": "right",
                        "is_bold": True,
                    },
                ]
            },
        )
    )

    return _paginate_landscape(header, blocks, table_header_block)


def build_itemwise_ledger_pages(report: Dict[str, Any]) -> List[ReportPage]:
    """Build Itemwise Ledger pages from an item ledger report dictionary."""
    item = report.get("item") or {}
    item_name = str(item.get("item_name") or "")
    company_name = str(item.get("company_name") or "")
    unit_name = str(item.get("unit_name") or "Units")
    pack_size = str(item.get("pack_size") or "")

    from_date = str(report.get("from_date") or "")
    to_date = str(report.get("to_date") or "")
    opening = float(report.get("opening_stock") or 0.0)
    total_inward = float(report.get("total_inward") or 0.0)
    total_outward = float(report.get("total_outward") or 0.0)
    closing = float(report.get("closing_stock") or 0.0)
    on_hand = float(report.get("current_batch_stock") or 0.0)
    rows = report.get("rows") or []

    parts = [f"Item: {item_name}"] if item_name else ["Item: -"]
    if company_name:
        parts.append(f"[{company_name}]")
    if pack_size:
        parts.append(f"Pack: {pack_size}")

    header = _report_header(
        title="ITEMWISE LEDGER",
        line_2="  ".join(parts),
        line_3=(
            f"From: {fmt_date_dash(from_date)} To: {fmt_date_dash(to_date)}  |  "
            f"Opening: {opening:g}  |  Closing: {closing:g} {unit_name}  |  "
            f"On Hand: {on_hand:g}"
        ),
    )

    cols = [
        "Date",
        "Particulars",
        "Voucher No",
        "Voucher Type",
        "Batch No",
        "Expiry",
        "Inward Qty",
        "Outward Qty",
        "Closing Stock",
    ]
    # Sums to CONTENT_WIDTH_LANDSCAPE (1053.0).
    widths = [75.0, 390.0, 85.0, 90.0, 85.0, 65.0, 80.0, 90.0, 93.0]
    aligns = [
        "center",
        "left",
        "left",
        "left",
        "left",
        "center",
        "right",
        "right",
        "right",
    ]

    table_header_block = ReportBlock(
        kind=BlockKind.TABLE_HEADER,
        height=24.0,
        data={"columns": cols, "widths": widths, "aligns": aligns},
    )

    blocks: List[ReportBlock] = []
    warning_block = _warning_block(report.get("warning"))
    if warning_block is not None:
        blocks.append(warning_block)
    blocks.append(table_header_block)

    blocks.append(
        ReportBlock(
            kind=BlockKind.DATA_ROW,
            height=18.0,
            data={
                "cells": [
                    fmt_date_dash(from_date),
                    "*** OPENING STOCK ***",
                    "-",
                    "-",
                    "-",
                    "-",
                    "",
                    "",
                    f"{opening:g}",
                ],
                "widths": widths,
                "aligns": aligns,
            },
        )
    )

    for txn in rows:
        inward = float(txn.get("inward_qty") or 0.0)
        outward = float(txn.get("outward_qty") or 0.0)
        stock = float(txn.get("closing_stock") or 0.0)
        blocks.append(
            ReportBlock(
                kind=BlockKind.DATA_ROW,
                height=18.0,
                data={
                    "cells": [
                        fmt_date_dash(txn.get("date")),
                        str(txn.get("particulars") or ""),
                        format_document_number(txn.get("voucher_no")),
                        str(txn.get("voucher_type") or ""),
                        str(txn.get("batch_no") or ""),
                        str(txn.get("expiry") or ""),
                        f"{inward:g}" if inward else "",
                        f"{outward:g}" if outward else "",
                        f"{stock:g}",
                    ],
                    "widths": widths,
                    "aligns": aligns,
                },
            )
        )

    prefix_w = sum(widths[:6])
    blocks.append(
        ReportBlock(
            kind=BlockKind.GRAND_TOTAL,
            height=22.0,
            data={
                "custom_cells": [
                    {
                        "width": prefix_w,
                        "text": "TOTALS & CLOSING STOCK :",
                        "align": "right",
                        "is_bold": True,
                    },
                    {
                        "width": widths[6],
                        "text": f"{total_inward:g}",
                        "align": "right",
                        "is_bold": True,
                    },
                    {
                        "width": widths[7],
                        "text": f"{total_outward:g}",
                        "align": "right",
                        "is_bold": True,
                    },
                    {
                        "width": widths[8],
                        "text": f"{closing:g}",
                        "align": "right",
                        "is_bold": True,
                    },
                ]
            },
        )
    )

    return _paginate_landscape(header, blocks, table_header_block)


class LedgerReportPreviewDialog(QDialog):
    """Crystal Reports preview for a Detailed Ledger report."""

    def __init__(
        self,
        title: str,
        pages: List[ReportPage],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._pages = list(pages)
        self._export_name = f"{title.lower().replace(' ', '_')}.pdf"

        self.setWindowTitle(f"{title} - Crystal Report")
        self.resize(1180, 820)
        self.setMinimumSize(900, 600)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.viewer = CrystalReportViewer(self)
        self.viewer.print_requested.connect(self._on_print)
        self.viewer.export_requested.connect(self._on_export)
        layout.addWidget(self.viewer)
        self.viewer.set_pages(self._pages)

    def _on_print(self):
        if self._pages:
            print_or_export_report_pages(self._pages, parent=self)

    def _on_export(self):
        if not self._pages:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Report",
            self._export_name,
            "PDF Files (*.pdf)",
        )
        if not path:
            return
        if not path.casefold().endswith(".pdf"):
            path += ".pdf"
        if print_or_export_report_pages(
            self._pages, parent=self, output_pdf_path=path
        ):
            QMessageBox.information(
                self, "Export", f"Report saved as PDF:\n{path}"
            )


def open_ledger_report_preview(
    parent: QWidget, title: str, pages: List[ReportPage]
) -> LedgerReportPreviewDialog:
    """Show a non-modal Crystal preview, replacing an older ledger preview."""
    previous = getattr(parent, "_ledger_preview", None)
    if previous is not None:
        try:
            previous.close()
        except RuntimeError:
            pass

    dialog = LedgerReportPreviewDialog(title, pages, parent)
    parent._ledger_preview = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
