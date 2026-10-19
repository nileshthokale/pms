"""Purchase Report Screens.

Implements the 6 Crystal-Reports-style Purchase Report forms:
1. CompanywiseItemwisePurchasePage
2. CompanywiseSupplierwisePurchasePage
3. SupplierwiseItemwiseInvoicePurchasePage
4. SupplierwiseItemwiseChallanPurchasePage
5. ItemwisePurchasePage
6. ItemwiseBatchwisePurchasePage

Each page includes:
- Blue title bar with close "X" at top right
- Report Viewer (~80% width) with Crystal Reports toolbar, "Main Report" tab, grey canvas, A4 page, drop shadow, status bar
- Filter Panel (~20% width) with light-blue background, bold blue title, From/To dates, searchable dropdown, "Show Report", and "Print" button
- Read-only queries via PurchaseReportsDAO
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.doc_formatter import format_document_number
from database.purchase_reports_dao import PurchaseReportsDAO
from ui.crystal_report_viewer import (
    BasePurchaseReportWindow,
    BlockKind,
    CONTENT_WIDTH,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    draw_report_page,
    fmt_amt,
    fmt_date_dash,
    fmt_date_slash,
    fmt_free,
    fmt_qty,
    get_default_store_identity,
)


MAX_PAGE_BODY_HEIGHT = 980.0


def paginate_blocks(
    header: ReportHeaderData,
    blocks: List[ReportBlock],
    table_header_block: Optional[ReportBlock] = None,
) -> List[ReportPage]:
    """Split blocks into A4 portrait pages, repeating table headers across page breaks."""
    if not blocks:
        empty_page = ReportPage(page_num=1, total_pages=1, header=header, blocks=[])
        return [empty_page]

    pages: List[ReportPage] = []
    current_blocks: List[ReportBlock] = []
    current_h = 0.0

    for block in blocks:
        # Check if block fits on the current page
        # If it's a group header, ensure space for group header + table header + at least 1 row (~66px)
        needed_h = 66.0 if block.kind == BlockKind.GROUP_HEADER else block.height
        if current_blocks and (current_h + needed_h > MAX_PAGE_BODY_HEIGHT):
            # Finish current page
            pages.append(
                ReportPage(
                    page_num=len(pages) + 1,
                    total_pages=0,  # will update after loop
                    header=header,
                    blocks=current_blocks,
                )
            )
            current_blocks = []
            current_h = 0.0

            # If table was split across pages, repeat table header at top of new page
            if table_header_block and block.kind not in (BlockKind.GROUP_HEADER, BlockKind.TABLE_HEADER):
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
            )
        )

    # Update total_pages
    total = len(pages)
    for p in pages:
        p.total_pages = total

    return pages


# ── REPORT 1: Companywise Itemwise Purchase ───────────────────────────

class CompanywiseItemwisePurchasePage(BasePurchaseReportWindow):
    """Report 1: Companywise Itemwise Purchase."""

    def __init__(self, parent=None):
        super().__init__(
            report_title="Companywise Itemwise Purchase",
            panel_title="Companywise Itemwise Purchase",
            dropdown_label="Company",
            parent=parent,
        )
        self.load_dropdown_data()

    def load_dropdown_data(self):
        companies = PurchaseReportsDAO.get_filter_companies()
        self.dropdown.clear()
        self.dropdown.addItem("-- Select Company --", None)
        for c in companies:
            self.dropdown.addItem(c["company_name"], c["id"])

    def generate_report_pages(
        self, from_date: str, to_date: str, selected_id: int
    ) -> List[ReportPage]:
        store_name, store_addr = get_default_store_identity()
        idx = self.dropdown.findData(selected_id)
        company_name = self.dropdown.itemText(idx).strip() if idx >= 0 else self.dropdown.currentText().strip()

        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_addr,
            header_line_1=f"Companywise Itemwise Purchase for {fmt_date_dash(from_date)} To {fmt_date_dash(to_date)}",
            header_line_2=f"Company : {company_name}",
        )

        rows = PurchaseReportsDAO.get_companywise_itemwise_purchase(
            from_date, to_date, selected_id
        )

        cols = ["VhType", "VhNo", "VhDate", "BatchNo", "PackSize", "ExpiryDate", "Rate", "Pay Qty", "Free", "Amount"]
        widths = [60.0, 55.0, 70.0, 85.0, 55.0, 75.0, 65.0, 65.0, 55.0, 139.0]
        aligns = ["left", "left", "left", "left", "left", "left", "right", "right", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        if not rows:
            blocks = [
                table_header_block,
                ReportBlock(kind=BlockKind.EMPTY, height=30.0, data={"message": "No purchases found for this company in the selected date range."}),
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=24.0,
                    data={"widths": widths, "label": "Grand Total :", "pay_str": "0", "free_str": "0", "amt_str": "0.00"},
                ),
            ]
            return paginate_blocks(header, blocks, table_header_block)

        # Group by item
        groups: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            i_id = r["item_id"]
            if i_id not in groups:
                groups[i_id] = {
                    "item_name": r["item_name"],
                    "form": r["form"],
                    "rows": [],
                }
            groups[i_id]["rows"].append(r)

        blocks: List[ReportBlock] = []
        grand_pay = 0.0
        grand_free = 0.0
        grand_amt = 0.0

        for item_data in groups.values():
            item_name = item_data["item_name"]
            form = item_data["form"]
            group_title = f"{item_name}   {form}".strip()

            blocks.append(
                ReportBlock(
                    kind=BlockKind.GROUP_HEADER,
                    height=22.0,
                    data={"text": group_title},
                )
            )
            blocks.append(table_header_block)

            item_pay = 0.0
            item_free = 0.0
            item_amt = 0.0

            for r in item_data["rows"]:
                pay = float(r.get("pay_qty") or 0.0)
                free = float(r.get("free_qty") or 0.0)
                amt = float(r.get("amount") or 0.0)

                item_pay += pay
                item_free += free
                item_amt += amt

                vh_no = format_document_number(r.get("voucher_no"))
                cells = [
                    str(r.get("purchase_type") or ""),
                    vh_no,
                    fmt_date_slash(r.get("voucher_date")),
                    str(r.get("batch_no") or ""),
                    str(r.get("pack_size") or ""),
                    fmt_date_dash(r.get("expiry")),
                    fmt_amt(r.get("rate")),
                    fmt_qty(pay),
                    fmt_free(free),
                    fmt_amt(amt),
                ]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=20.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            grand_pay += item_pay
            grand_free += item_free
            grand_amt += item_amt

            blocks.append(
                ReportBlock(
                    kind=BlockKind.ITEM_SUBTOTAL,
                    height=22.0,
                    data={
                        "widths": widths,
                        "pay_str": fmt_qty(item_pay),
                        "free_str": fmt_qty(item_free),
                        "amt_str": fmt_amt(item_amt),
                    },
                )
            )

        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "widths": widths,
                    "label": "Grand Total :",
                    "pay_str": fmt_qty(grand_pay),
                    "free_str": fmt_qty(grand_free),
                    "amt_str": fmt_amt(grand_amt),
                },
            )
        )

        return paginate_blocks(header, blocks, table_header_block)


# ── REPORT 2: Companywise Supplierwise Purchase ───────────────────────

class CompanywiseSupplierwisePurchasePage(BasePurchaseReportWindow):
    """Report 2: Companywise Supplierwise Purchase."""

    def __init__(self, parent=None):
        super().__init__(
            report_title="Companywise Supplierwise Purchase",
            panel_title="Companywise Supplierwise Purchase",
            dropdown_label="Company",
            parent=parent,
        )
        self.load_dropdown_data()

    def load_dropdown_data(self):
        companies = PurchaseReportsDAO.get_filter_companies()
        self.dropdown.clear()
        self.dropdown.addItem("-- Select Company --", None)
        for c in companies:
            self.dropdown.addItem(c["company_name"], c["id"])

    def generate_report_pages(
        self, from_date: str, to_date: str, selected_id: int
    ) -> List[ReportPage]:
        store_name, store_addr = get_default_store_identity()
        idx = self.dropdown.findData(selected_id)
        company_name = self.dropdown.itemText(idx).strip() if idx >= 0 else self.dropdown.currentText().strip()

        # Kept exact wording & spelling from original specification: "Suppler"
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_addr,
            header_line_1=f"Companywise Suppler Purchase for {fmt_date_dash(from_date)} To {fmt_date_dash(to_date)}",
            header_line_2=f"Company Name: {company_name}",
        )

        rows = PurchaseReportsDAO.get_companywise_supplierwise_purchase(
            from_date, to_date, selected_id
        )

        cols = ["Sr No", "Supplier", "Address", "Amount"]
        widths = [60.0, 240.0, 284.0, 140.0]
        aligns = ["right", "left", "left", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        if not rows:
            blocks = [
                table_header_block,
                ReportBlock(kind=BlockKind.EMPTY, height=30.0, data={"message": "No purchases found for this company in the selected date range."}),
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=24.0,
                    data={"widths": widths, "label": "Total :", "amt_str": "0.00"},
                ),
            ]
            return paginate_blocks(header, blocks, table_header_block)

        blocks: List[ReportBlock] = [table_header_block]
        total_amt = 0.0

        for idx, r in enumerate(rows, start=1):
            amt = float(r.get("amount") or 0.0)
            total_amt += amt
            addr = str(r.get("address") or "").strip()
            city = str(r.get("city") or "").strip()
            if addr and city and city.lower() not in addr.lower():
                full_addr = f"{addr}, {city}"
            else:
                full_addr = addr or city
            cells = [
                str(idx),
                str(r.get("supplier_name") or ""),
                full_addr,
                fmt_amt(amt),
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.DATA_ROW,
                    height=20.0,
                    data={"cells": cells, "widths": widths, "aligns": aligns},
                )
            )

        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={"widths": widths, "label": "Total :", "amt_str": fmt_amt(total_amt)},
            )
        )

        return paginate_blocks(header, blocks, table_header_block)


# ── REPORT 3: Supplierwise Itemwise Purchase (Invoice) ────────────────

class SupplierwiseItemwiseInvoicePurchasePage(BasePurchaseReportWindow):
    """Report 3: Supplierwise Itemwise Purchase (Invoice)."""

    def __init__(self, parent=None):
        super().__init__(
            report_title="Supplierwise Itemwise Purchase (Invoice)",
            panel_title="Supplierwise Itemwise Purchase Report",
            dropdown_label="Supplier",
            parent=parent,
        )
        self.load_dropdown_data()

    def load_dropdown_data(self):
        suppliers = PurchaseReportsDAO.get_filter_suppliers()
        self.dropdown.clear()
        self.dropdown.addItem("-- Select Supplier --", None)
        for s in suppliers:
            self.dropdown.addItem(s["supplier_name"], s["id"])

    def generate_report_pages(
        self, from_date: str, to_date: str, selected_id: int
    ) -> List[ReportPage]:
        store_name, store_addr = get_default_store_identity()
        idx = self.dropdown.findData(selected_id)
        supplier_name = self.dropdown.itemText(idx).strip() if idx >= 0 else self.dropdown.currentText().strip()

        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_addr,
            header_line_1=f"Supplierwise Itemwise Purchase for {fmt_date_dash(from_date)} To {fmt_date_dash(to_date)}",
            header_line_2=f"Supplier: {supplier_name}",
        )

        rows = PurchaseReportsDAO.get_supplierwise_itemwise_purchase(
            from_date, to_date, selected_id, is_challan=False
        )

        cols = ["VhType", "InvoiceNo", "InvoiceDate", "BatchNo", "PackSize", "ExpiryDate", "Rate", "Pay Qty", "Free", "Amount"]
        widths = [60.0, 65.0, 70.0, 85.0, 55.0, 75.0, 65.0, 65.0, 55.0, 129.0]
        aligns = ["left", "left", "left", "left", "left", "left", "right", "right", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        if not rows:
            blocks = [
                table_header_block,
                ReportBlock(kind=BlockKind.EMPTY, height=30.0, data={"message": "No invoice purchases found for this supplier in the selected date range."}),
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=24.0,
                    data={"widths": widths, "label": "Grand Total :", "pay_str": "0", "free_str": "0", "amt_str": "0.00"},
                ),
            ]
            return paginate_blocks(header, blocks, table_header_block)

        groups: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            i_id = r["item_id"]
            if i_id not in groups:
                groups[i_id] = {
                    "item_name": r["item_name"],
                    "company_code": r["company_code"],
                    "rows": [],
                }
            groups[i_id]["rows"].append(r)

        blocks: List[ReportBlock] = []
        grand_pay = 0.0
        grand_free = 0.0
        grand_amt = 0.0

        for item_data in groups.values():
            item_name = item_data["item_name"]
            code = item_data["company_code"]
            group_title = f"{item_name} ({code})" if code else item_name

            blocks.append(
                ReportBlock(
                    kind=BlockKind.GROUP_HEADER,
                    height=22.0,
                    data={"text": group_title},
                )
            )
            blocks.append(table_header_block)

            item_pay = 0.0
            item_free = 0.0
            item_amt = 0.0

            for r in item_data["rows"]:
                pay = float(r.get("pay_qty") or 0.0)
                free = float(r.get("free_qty") or 0.0)
                amt = float(r.get("amount") or 0.0)

                item_pay += pay
                item_free += free
                item_amt += amt

                inv_no = format_document_number(r.get("invoice_no"))
                cells = [
                    str(r.get("purchase_type") or ""),
                    inv_no,
                    fmt_date_slash(r.get("invoice_date")),
                    str(r.get("batch_no") or ""),
                    str(r.get("pack_size") or ""),
                    fmt_date_dash(r.get("expiry")),
                    fmt_amt(r.get("rate")),
                    fmt_qty(pay),
                    fmt_free(free),
                    fmt_amt(amt),
                ]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=20.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            grand_pay += item_pay
            grand_free += item_free
            grand_amt += item_amt

            blocks.append(
                ReportBlock(
                    kind=BlockKind.ITEM_SUBTOTAL,
                    height=22.0,
                    data={
                        "widths": widths,
                        "pay_str": fmt_qty(item_pay),
                        "free_str": fmt_qty(item_free),
                        "amt_str": fmt_amt(item_amt),
                    },
                )
            )

        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "widths": widths,
                    "label": "Grand Total :",
                    "pay_str": fmt_qty(grand_pay),
                    "free_str": fmt_qty(grand_free),
                    "amt_str": fmt_amt(grand_amt),
                },
            )
        )

        return paginate_blocks(header, blocks, table_header_block)


# ── REPORT 4: Supplierwise Itemwise Purchase (Challan) ────────────────

class SupplierwiseItemwiseChallanPurchasePage(BasePurchaseReportWindow):
    """Report 4: Supplierwise Itemwise Purchase (Challan)."""

    def __init__(self, parent=None):
        super().__init__(
            report_title="Supplierwise Itemwise Purchase (Challan)",
            panel_title="Supplierwise Itemwise Purchase Report (Challan)",
            dropdown_label="Supplier",
            parent=parent,
        )
        self.load_dropdown_data()

    def load_dropdown_data(self):
        suppliers = PurchaseReportsDAO.get_filter_suppliers()
        self.dropdown.clear()
        self.dropdown.addItem("-- Select Supplier --", None)
        for s in suppliers:
            self.dropdown.addItem(s["supplier_name"], s["id"])

    def generate_report_pages(
        self, from_date: str, to_date: str, selected_id: int
    ) -> List[ReportPage]:
        store_name, store_addr = get_default_store_identity()
        idx = self.dropdown.findData(selected_id)
        supplier_name = self.dropdown.itemText(idx).strip() if idx >= 0 else self.dropdown.currentText().strip()

        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_addr,
            header_line_1=f"Supplierwise Itemwise Purchase (Challan) for {fmt_date_dash(from_date)} To {fmt_date_dash(to_date)}",
            header_line_2=f"Supplier: {supplier_name}",
        )

        rows = PurchaseReportsDAO.get_supplierwise_itemwise_purchase(
            from_date, to_date, selected_id, is_challan=True
        )

        cols = ["VhType", "ChallanNo", "ChallanDate", "BatchNo", "PackSize", "ExpiryDate", "Rate", "Pay Qty", "Free", "Amount"]
        widths = [60.0, 65.0, 70.0, 85.0, 55.0, 75.0, 65.0, 65.0, 55.0, 129.0]
        aligns = ["left", "left", "left", "left", "left", "left", "right", "right", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        if not rows:
            blocks = [
                table_header_block,
                ReportBlock(kind=BlockKind.EMPTY, height=30.0, data={"message": "No challan purchases found for this supplier in the selected date range."}),
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=24.0,
                    data={"widths": widths, "label": "Grand Total :", "pay_str": "0", "free_str": "0", "amt_str": "0.00"},
                ),
            ]
            return paginate_blocks(header, blocks, table_header_block)

        groups: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            i_id = r["item_id"]
            if i_id not in groups:
                groups[i_id] = {
                    "item_name": r["item_name"],
                    "company_code": r["company_code"],
                    "rows": [],
                }
            groups[i_id]["rows"].append(r)

        blocks: List[ReportBlock] = []
        grand_pay = 0.0
        grand_free = 0.0
        grand_amt = 0.0

        for item_data in groups.values():
            item_name = item_data["item_name"]
            code = item_data["company_code"]
            group_title = f"{item_name} ({code})" if code else item_name

            blocks.append(
                ReportBlock(
                    kind=BlockKind.GROUP_HEADER,
                    height=22.0,
                    data={"text": group_title},
                )
            )
            blocks.append(table_header_block)

            item_pay = 0.0
            item_free = 0.0
            item_amt = 0.0

            for r in item_data["rows"]:
                pay = float(r.get("pay_qty") or 0.0)
                free = float(r.get("free_qty") or 0.0)
                amt = float(r.get("amount") or 0.0)

                item_pay += pay
                item_free += free
                item_amt += amt

                challan_no = format_document_number(r.get("invoice_no"))
                cells = [
                    str(r.get("purchase_type") or ""),
                    challan_no,
                    fmt_date_slash(r.get("invoice_date")),
                    str(r.get("batch_no") or ""),
                    str(r.get("pack_size") or ""),
                    fmt_date_dash(r.get("expiry")),
                    fmt_amt(r.get("rate")),
                    fmt_qty(pay),
                    fmt_free(free),
                    fmt_amt(amt),
                ]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=20.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            grand_pay += item_pay
            grand_free += item_free
            grand_amt += item_amt

            blocks.append(
                ReportBlock(
                    kind=BlockKind.ITEM_SUBTOTAL,
                    height=22.0,
                    data={
                        "widths": widths,
                        "pay_str": fmt_qty(item_pay),
                        "free_str": fmt_qty(item_free),
                        "amt_str": fmt_amt(item_amt),
                    },
                )
            )

        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "widths": widths,
                    "label": "Grand Total :",
                    "pay_str": fmt_qty(grand_pay),
                    "free_str": fmt_qty(grand_free),
                    "amt_str": fmt_amt(grand_amt),
                },
            )
        )

        return paginate_blocks(header, blocks, table_header_block)


# ── REPORT 5: Itemwise Purchase ───────────────────────────────────────

class ItemwisePurchasePage(BasePurchaseReportWindow):
    """Report 5: Itemwise Purchase."""

    def __init__(self, parent=None):
        super().__init__(
            report_title="Itemwise Purchase",
            panel_title="Itemwise Purchase Report",
            dropdown_label="Item",
            parent=parent,
        )
        self.load_dropdown_data()

    def load_dropdown_data(self):
        items = PurchaseReportsDAO.get_filter_items()
        self.dropdown.clear()
        self.dropdown.addItem("-- Select Item --", None)
        for it in items:
            label = it["item_name"]
            code = it["company_code"]
            form = it["form"]
            extra = []
            if form:
                extra.append(form)
            if code:
                extra.append(code)
            if extra:
                label = f"{label} ({' - '.join(extra)})"
            self.dropdown.addItem(label, it["id"])

    def generate_report_pages(
        self, from_date: str, to_date: str, selected_id: int
    ) -> List[ReportPage]:
        store_name, store_addr = get_default_store_identity()

        # Find item metadata for Header Line 2: "<ITEM NAME> - <FORM> (<COMPANY CODE>)"
        items = PurchaseReportsDAO.get_filter_items()
        target_item = next((it for it in items if it["id"] == selected_id), None)
        if target_item:
            i_name = target_item["item_name"]
            i_form = str(target_item.get("form") or "").strip()
            i_code = str(target_item.get("company_code") or "").strip()
            if i_form and i_code:
                line_2 = f"{i_name} - {i_form} ({i_code})"
            elif i_form:
                line_2 = f"{i_name} - {i_form}"
            elif i_code:
                line_2 = f"{i_name} ({i_code})"
            else:
                line_2 = i_name
        else:
            line_2 = self.dropdown.currentText().strip()

        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_addr,
            header_line_1=f"Itemwise Purchase for {fmt_date_dash(from_date)} To {fmt_date_dash(to_date)}",
            header_line_2=line_2,
        )

        rows = PurchaseReportsDAO.get_itemwise_purchase(from_date, to_date, selected_id)

        cols = ["InvoiceNo", "VhType", "VhNo", "VhDate", "Supplier", "BatchNo", "Rate", "Pay Qty", "Free", "Amount"]
        widths = [65.0, 55.0, 55.0, 70.0, 130.0, 85.0, 60.0, 60.0, 50.0, 94.0]
        aligns = ["left", "left", "left", "left", "left", "left", "right", "right", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        if not rows:
            blocks = [
                table_header_block,
                ReportBlock(kind=BlockKind.EMPTY, height=30.0, data={"message": "No purchases found for this item in the selected date range."}),
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=24.0,
                    data={"widths": widths, "label": "Total :", "pay_str": "0", "free_str": "0", "amt_str": "0.00"},
                ),
            ]
            return paginate_blocks(header, blocks, table_header_block)

        blocks: List[ReportBlock] = [table_header_block]
        total_pay = 0.0
        total_free = 0.0
        total_amt = 0.0

        for r in rows:
            pay = float(r.get("pay_qty") or 0.0)
            free = float(r.get("free_qty") or 0.0)
            amt = float(r.get("amount") or 0.0)

            total_pay += pay
            total_free += free
            total_amt += amt

            inv_no = format_document_number(r.get("invoice_no"))
            vh_no = format_document_number(r.get("voucher_no"))

            cells = [
                inv_no,
                str(r.get("purchase_type") or ""),
                vh_no,
                fmt_date_slash(r.get("voucher_date")),
                str(r.get("supplier_name") or ""),
                str(r.get("batch_no") or ""),
                fmt_amt(r.get("rate")),
                fmt_qty(pay),
                fmt_free(free),
                fmt_amt(amt),
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.DATA_ROW,
                    height=20.0,
                    data={"cells": cells, "widths": widths, "aligns": aligns},
                )
            )

        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "widths": widths,
                    "label": "Total :",
                    "pay_str": fmt_qty(total_pay),
                    "free_str": fmt_qty(total_free),
                    "amt_str": fmt_amt(total_amt),
                },
            )
        )

        return paginate_blocks(header, blocks, table_header_block)


# ── REPORT 6: Itemwise Batchwise Purchase ─────────────────────────────

class ItemwiseBatchwisePurchasePage(BasePurchaseReportWindow):
    """Report 6: Itemwise Batchwise Purchase."""

    def __init__(self, parent=None):
        super().__init__(
            report_title="Itemwise Batchwise Purchase",
            panel_title="Itemwise Batchwise Purchase Report",
            dropdown_label="Item",
            parent=parent,
        )
        self.load_dropdown_data()

    def load_dropdown_data(self):
        items = PurchaseReportsDAO.get_filter_items()
        self.dropdown.clear()
        self.dropdown.addItem("-- Select Item --", None)
        for it in items:
            label = it["item_name"]
            code = it["company_code"]
            form = it["form"]
            extra = []
            if form:
                extra.append(form)
            if code:
                extra.append(code)
            if extra:
                label = f"{label} ({' - '.join(extra)})"
            self.dropdown.addItem(label, it["id"])

    def generate_report_pages(
        self, from_date: str, to_date: str, selected_id: int
    ) -> List[ReportPage]:
        store_name, store_addr = get_default_store_identity()

        items = PurchaseReportsDAO.get_filter_items()
        target_item = next((it for it in items if it["id"] == selected_id), None)
        if target_item:
            i_name = target_item["item_name"]
            i_form = str(target_item.get("form") or "").strip()
            i_code = str(target_item.get("company_code") or "").strip()
            if i_form and i_code:
                line_2 = f"{i_name} - {i_form} ({i_code})"
            elif i_form:
                line_2 = f"{i_name} - {i_form}"
            elif i_code:
                line_2 = f"{i_name} ({i_code})"
            else:
                line_2 = i_name
        else:
            line_2 = self.dropdown.currentText().strip()

        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_addr,
            header_line_1=f"Itemwise Purchase for {fmt_date_dash(from_date)} To {fmt_date_dash(to_date)}",
            header_line_2=line_2,
        )

        rows = PurchaseReportsDAO.get_itemwise_batchwise_purchase(
            from_date, to_date, selected_id
        )

        cols = ["InvoiceNo", "VhType", "VhNo", "VhDate", "Supplier", "BatchNo", "Rate", "Pay Qty", "Free", "Amount"]
        widths = [65.0, 55.0, 55.0, 70.0, 130.0, 85.0, 60.0, 60.0, 50.0, 94.0]
        aligns = ["left", "left", "left", "left", "left", "left", "right", "right", "right", "right"]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )

        if not rows:
            blocks = [
                table_header_block,
                ReportBlock(kind=BlockKind.EMPTY, height=30.0, data={"message": "No batchwise purchases found for this item in the selected date range."}),
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=24.0,
                    data={"widths": widths, "label": "Grand Total :", "pay_str": "0", "free_str": "0", "amt_str": "0.00"},
                ),
            ]
            return paginate_blocks(header, blocks, table_header_block)

        # Group rows by batch_no (case-insensitive)
        batch_groups: Dict[str, Tuple[str, List[Dict[str, Any]]]] = {}
        for r in rows:
            b_no = str(r.get("batch_no") or "").strip()
            key = b_no.casefold()
            if key not in batch_groups:
                batch_groups[key] = (b_no, [])
            batch_groups[key][1].append(r)

        blocks: List[ReportBlock] = [table_header_block]
        grand_pay = 0.0
        grand_free = 0.0
        grand_amt = 0.0

        for key, (b_no, b_rows) in batch_groups.items():
            batch_pay = 0.0
            batch_free = 0.0
            batch_amt = 0.0

            for idx, r in enumerate(b_rows):
                pay = float(r.get("pay_qty") or 0.0)
                free = float(r.get("free_qty") or 0.0)
                amt = float(r.get("amount") or 0.0)

                batch_pay += pay
                batch_free += free
                batch_amt += amt

                inv_no = format_document_number(r.get("invoice_no"))
                vh_no = format_document_number(r.get("voucher_no"))

                # BatchNo and Rate printed ONLY on the FIRST row of each batch; following rows leave blank
                disp_batch = b_no if idx == 0 else ""
                disp_rate = fmt_amt(r.get("rate")) if idx == 0 else ""

                cells = [
                    inv_no,
                    str(r.get("purchase_type") or ""),
                    vh_no,
                    fmt_date_slash(r.get("voucher_date")),
                    str(r.get("supplier_name") or ""),
                    disp_batch,
                    disp_rate,
                    fmt_qty(pay),
                    fmt_free(free),
                    fmt_amt(amt),
                ]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=20.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            grand_pay += batch_pay
            grand_free += batch_free
            grand_amt += batch_amt

            # After each batch show right-aligned label "<BATCHNO>   Total :" with small bordered box
            blocks.append(
                ReportBlock(
                    kind=BlockKind.BATCH_SUBTOTAL,
                    height=22.0,
                    data={
                        "widths": widths,
                        "batch_no": b_no,
                        "pay_str": fmt_qty(batch_pay),
                        "free_str": fmt_qty(batch_free),
                        "amt_str": fmt_amt(batch_amt),
                    },
                )
            )

        # End with bordered bold "Grand Total :" row with sum of all batches
        blocks.append(
            ReportBlock(
                kind=BlockKind.GRAND_TOTAL,
                height=24.0,
                data={
                    "widths": widths,
                    "label": "Grand Total :",
                    "pay_str": fmt_qty(grand_pay),
                    "free_str": fmt_qty(grand_free),
                    "amt_str": fmt_amt(grand_amt),
                },
            )
        )

        return paginate_blocks(header, blocks, table_header_block)
