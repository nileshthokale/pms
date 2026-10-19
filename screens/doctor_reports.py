"""Doctor's Reports Screens — Crystal Reports Style & Pharma-WINNER Reference.

Implements both Doctor's Reports matching Pharma-WINNER:
1. DoctorwiseItemSalePage ("Doctorwise Item Sale")
2. DoctorwiseItemSaleDetailsPage ("Doctorwise Item Sale Details")

Features:
- Standard blue title bar with report title and close "✕" button
- Crystal Reports viewer with toolbar (Export PDF/CSV, Print, Page navigation, Zoom, Find, Copy)
- Centered white A4 page (Portrait at 96 DPI) with drop shadow on grey canvas
- Resizable split layouts:
  * Doctorwise Item Sale: Group Tree / Doctor outline + Report Viewer + Filter Panel
  * Doctorwise Item Sale Details: Item Selection Tree/List + Report Viewer + Filter Panel
- Searchable doctor dropdowns and Item Master autocomplete
- Full financial calculations matching established costing rules
- Full Day Mode and Night Mode theme compatibility
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QDate, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.doctor_reports_dao import DoctorReportsDAO
from database import financial_year
from ui import theme
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
    fmt_date_dash,
    fmt_qty,
    get_default_store_identity,
    print_or_export_report_pages,
)

MAX_PAGE_BODY_HEIGHT = 980.0


def paginate_doctor_report_blocks(
    header: ReportHeaderData,
    blocks: List[ReportBlock],
    default_table_header: Optional[ReportBlock] = None,
) -> List[ReportPage]:
    """Split report blocks across A4 pages, repeating group and table headers across page breaks."""
    if not blocks:
        return [
            ReportPage(
                page_num=1,
                total_pages=1,
                header=header,
                blocks=[],
                orientation="portrait",
                page_width=PAGE_WIDTH,
                page_height=PAGE_HEIGHT,
            )
        ]

    pages: List[ReportPage] = []
    current_blocks: List[ReportBlock] = []
    current_h = 0.0

    active_group_header: Optional[ReportBlock] = None
    active_table_header: Optional[ReportBlock] = default_table_header

    for block in blocks:
        if block.kind == BlockKind.GROUP_HEADER:
            active_group_header = block
        elif block.kind == BlockKind.TABLE_HEADER:
            active_table_header = block

        # For group headers, ensure space for group header + table header + at least 1 data row (~66px)
        needed_h = 66.0 if block.kind == BlockKind.GROUP_HEADER else block.height

        if current_blocks and (current_h + needed_h > MAX_PAGE_BODY_HEIGHT):
            # Close out current page
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

            # If breaking inside an item table, repeat headers at top of continuation page
            if block.kind not in (BlockKind.GROUP_HEADER, BlockKind.TABLE_HEADER, BlockKind.EMPTY):
                if active_group_header:
                    current_blocks.append(active_group_header)
                    current_h += active_group_header.height
                if active_table_header:
                    current_blocks.append(active_table_header)
                    current_h += active_table_header.height

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

    total = len(pages)
    for p in pages:
        p.total_pages = total

    return pages


class _BaseDoctorReportPage(QWidget):
    """Base class for Doctor's Reports with shared title bar, theme management, and export."""

    close_requested = Signal()

    def __init__(
        self,
        window_title: str,
        panel_title: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.window_title_text = window_title
        self.panel_title_text = panel_title
        self._pages: List[ReportPage] = []
        self._history_financial_year: Optional[Dict[str, Any]] = None
        self._doctors: List[Dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 1. Top Blue Title Bar ─────────────────────────────────────
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(32)
        tb_layout = QHBoxLayout(self.title_bar)
        tb_layout.setContentsMargins(10, 0, 4, 0)

        self.lbl_title = QLabel(self.window_title_text)
        tb_layout.addWidget(self.lbl_title)
        tb_layout.addStretch()

        self.btn_close = QPushButton("✕")
        self.btn_close.setToolTip("Close Report")
        self.btn_close.clicked.connect(self.close_requested.emit)
        tb_layout.addWidget(self.btn_close)
        root.addWidget(self.title_bar)

        # ── 2. Splitter ───────────────────────────────────────────────
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(2)
        root.addWidget(self.main_splitter, 1)

        # Viewer
        self.viewer = CrystalReportViewer()
        self.viewer.print_requested.connect(self.print_report)
        self.viewer.export_requested.connect(self.export_report)

        # Filter panel
        self.filter_panel = QFrame()
        self.fp_layout = QVBoxLayout(self.filter_panel)
        self.fp_layout.setContentsMargins(14, 14, 14, 14)
        self.fp_layout.setSpacing(10)

        self.lbl_panel_title = QLabel(self.panel_title_text)
        self.lbl_panel_title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 6px;")
        self.lbl_panel_title.setWordWrap(True)
        self.fp_layout.addWidget(self.lbl_panel_title)

        # Subclasses construct their UI and add widgets to main_splitter
        self._init_filter_controls()

        theme.theme_manager.on_changed(lambda mode: self.refresh_theme())
        self.refresh_theme()

    def _init_filter_controls(self):
        """Override in subclasses to build layout."""
        pass

    def _init_default_dates(self):
        active_fy = (
            financial_year.get_active_financial_year()
            or financial_year.ensure_default_financial_year()
        )
        if active_fy and active_fy.get("start_date"):
            parts = [int(p) for p in active_fy["start_date"].split("-")]
            self.from_date_edit.setDate(QDate(parts[0], parts[1], parts[2]))
        else:
            cur_year = QDate.currentDate().year()
            if QDate.currentDate().month() < 4:
                cur_year -= 1
            self.from_date_edit.setDate(QDate(cur_year, 4, 1))

        self.to_date_edit.setDate(QDate.currentDate())

    def set_history_financial_year(self, year: Optional[Dict[str, Any]]):
        """Scope date range to selected financial year for viewing."""
        self._history_financial_year = dict(year) if year else None
        if self._history_financial_year:
            s_date = self._history_financial_year.get("start_date")
            e_date = self._history_financial_year.get("end_date")
            if s_date:
                p = [int(x) for x in s_date.split("-")]
                self.from_date_edit.setDate(QDate(p[0], p[1], p[2]))
            if e_date:
                p = [int(x) for x in e_date.split("-")]
                self.to_date_edit.setDate(QDate(p[0], p[1], p[2]))
        else:
            self._init_default_dates()
        if self._pages:
            self.generate_report()

    def _load_doctors(self):
        self._doctors = DoctorReportsDAO.get_doctors_list()
        self.doctor_combo.clear()
        self.doctor_combo.addItem("-- Select Doctor --", None)
        for doc in self._doctors:
            name = doc["doctor_name"]
            spec = doc.get("specialty")
            label = f"{name} ({spec})" if spec else name
            self.doctor_combo.addItem(label, doc["id"])

    def get_selected_doctor_id(self) -> Optional[int]:
        text = self.doctor_combo.currentText().strip()
        if not text or text.lower().startswith("-- select"):
            return None

        curr_idx = self.doctor_combo.currentIndex()
        if 0 <= curr_idx < self.doctor_combo.count():
            item_text = self.doctor_combo.itemText(curr_idx).strip()
            if item_text.lower() == text.lower():
                data = self.doctor_combo.itemData(curr_idx)
                if data is not None:
                    return data

        for i in range(self.doctor_combo.count()):
            if self.doctor_combo.itemText(i).strip().lower() == text.lower():
                data = self.doctor_combo.itemData(i)
                if data is not None:
                    return data

        # Substring search
        matches = [
            self.doctor_combo.itemData(i)
            for i in range(self.doctor_combo.count())
            if text.lower() in self.doctor_combo.itemText(i).strip().lower()
            and not self.doctor_combo.itemText(i).strip().lower().startswith("-- select")
            and self.doctor_combo.itemData(i) is not None
        ]
        if len(matches) == 1:
            return matches[0]

        return None

    def get_selected_doctor_name(self) -> str:
        doc_id = self.get_selected_doctor_id()
        if doc_id is None:
            return ""
        for doc in self._doctors:
            if doc["id"] == doc_id:
                return doc["doctor_name"]
        return self.doctor_combo.currentText().strip()

    def print_report(self):
        if not self._pages:
            self._show_msg("Print", "No report to print. Please generate the report first.")
            return
        print_or_export_report_pages(self._pages, parent=self)

    def export_report(self):
        if not self._pages:
            self._show_msg("Export PDF", "No report to export. Please generate the report first.")
            return
        default_name = f"{self.window_title_text.replace(' ', '_').lower()}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {self.window_title_text}",
            default_name,
            "PDF Files (*.pdf);;CSV Files (*.csv)",
        )
        if not file_path:
            return
        if file_path.casefold().endswith(".pdf"):
            success = print_or_export_report_pages(self._pages, output_pdf_path=file_path, parent=self)
            if success:
                self._show_msg("Export PDF", f"Report successfully exported to:\n{file_path}")
        else:
            self._export_csv(file_path)

    def _export_csv(self, file_path: str):
        lines: List[str] = []
        for p in self._pages:
            for b in p.blocks:
                if b.kind == BlockKind.TABLE_HEADER:
                    lines.append(",".join(f'"{c}"' for c in b.data.get("columns", [])))
                elif b.kind == BlockKind.DATA_ROW:
                    lines.append(",".join(f'"{c}"' for c in b.data.get("cells", [])))
                elif b.kind in (BlockKind.ITEM_SUBTOTAL, BlockKind.GRAND_TOTAL):
                    if "custom_cells" in b.data:
                        lines.append(",".join(f'"{c.get("text", "")}"' for c in b.data["custom_cells"]))
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._show_msg("Export CSV", f"Report saved as CSV:\n{file_path}")
        except Exception as exc:
            self._show_msg("Export Error", f"Failed to save CSV: {exc}")

    def _show_msg(self, title: str, text: str):
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QMessageBox.information(self, title, text)

    def _show_validation_error(self, message: str):
        self.lbl_msg.setText(message)
        self.lbl_msg.setVisible(True)
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QMessageBox.warning(self, "Validation Error", message)

    def refresh_theme(self):
        p = theme.theme_manager.palette()
        is_dark = theme.theme_manager.is_dark()

        self.title_bar.setStyleSheet(
            f"QFrame {{ background-color: {'#1A365D' if is_dark else '#1B5299'}; border-bottom: 1px solid {p['border']}; }}"
            f"QLabel {{ color: #FFFFFF; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; }}"
            f"QPushButton {{ background: transparent; color: #FFFFFF; font-size: 14px; font-weight: bold; border: none; width: 28px; height: 28px; }}"
            f"QPushButton:hover {{ background-color: #E81123; }}"
        )

        panel_bg = p["surface"] if is_dark else "#E8EFF7"
        panel_border = p["border"] if is_dark else "#B0C4DE"
        label_color = p["accent"] if is_dark else "#003366"

        self.filter_panel.setStyleSheet(
            f"QFrame {{ background-color: {panel_bg}; border-left: 1px solid {panel_border}; }}"
            f"QLabel {{ color: {p['text']}; font-size: 12px; font-weight: bold; background: transparent; }}"
            f"QDateEdit {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 2px; padding: 4px 6px; font-size: 12px; }}"
            f"QComboBox {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 2px; padding: 4px 6px; font-size: 12px; }}"
            f"QPushButton {{ background-color: {p['accent']}; color: white; border: none; border-radius: 3px; padding: 7px 12px; font-size: 13px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
            f"QPushButton:disabled {{ background-color: {'#404040' if is_dark else '#A0B8D0'}; color: {'#707070' if is_dark else '#E0E8F0'}; }}"
        )
        self.lbl_panel_title.setStyleSheet(f"color: {label_color}; font-size: 14px; font-weight: bold; margin-bottom: 6px;")

        self.main_splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {p['border']}; }}")

        workspace_bg = QColor("#303030") if is_dark else QColor("#808080")
        self.viewer.canvas.set_workspace_bg(workspace_bg)
        self.viewer.scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color: {'#303030' if is_dark else '#808080'}; border: none; }}"
        )


# ══════════════════════════════════════════════════════════════════════
# 1. Doctorwise Item Sale Page (Report 1)
# ══════════════════════════════════════════════════════════════════════

class DoctorwiseItemSalePage(_BaseDoctorReportPage):
    """Doctorwise Item Sale report screen matching Pharma-WINNER reference."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            window_title="Doctorwise Item Sale Report",
            panel_title="Doctorwise Item Sales",
            parent=parent,
        )

    def _init_filter_controls(self):
        # 1. Left outline tree pane (Crystal Reports Group Tree style)
        self.tree_pane = QFrame()
        self.tree_pane.setMinimumWidth(160)
        self.tree_pane.setMaximumWidth(280)
        tp_layout = QVBoxLayout(self.tree_pane)
        tp_layout.setContentsMargins(4, 4, 4, 4)
        tp_layout.setSpacing(4)

        lbl_tree = QLabel("Doctors Outline")
        lbl_tree.setStyleSheet("font-size: 11px; font-weight: bold;")
        tp_layout.addWidget(lbl_tree)

        self.doctor_tree = QTreeWidget()
        self.doctor_tree.setHeaderHidden(True)
        self.doctor_tree.itemClicked.connect(self._on_tree_item_clicked)
        tp_layout.addWidget(self.doctor_tree, 1)

        self.main_splitter.addWidget(self.tree_pane)
        self.main_splitter.addWidget(self.viewer)

        # 2. Right filter panel
        self.lbl_from = QLabel("From Date:")
        self.fp_layout.addWidget(self.lbl_from)
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.from_date_edit)

        self.lbl_to = QLabel("To")
        self.fp_layout.addWidget(self.lbl_to)
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.to_date_edit)

        self._init_default_dates()

        self.lbl_doctor = QLabel("Doctor:")
        self.fp_layout.addWidget(self.lbl_doctor)

        self.doctor_combo = QComboBox()
        self.doctor_combo.setEditable(True)
        self.doctor_combo.setInsertPolicy(QComboBox.NoInsert)
        if self.doctor_combo.completer():
            self.doctor_combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
            self.doctor_combo.completer().setFilterMode(Qt.MatchContains)
        self.doctor_combo.currentIndexChanged.connect(self._sync_tree_selection)
        self.fp_layout.addWidget(self.doctor_combo)

        self.lbl_msg = QLabel("")
        self.lbl_msg.setStyleSheet("color: #C00000; font-size: 11px; font-weight: bold; background: transparent;")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setVisible(False)
        self.fp_layout.addWidget(self.lbl_msg)

        self.fp_layout.addSpacing(6)

        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.clicked.connect(self.generate_report)
        self.fp_layout.addWidget(self.btn_show_report)

        self.btn_panel_print = QPushButton("Print")
        self.btn_panel_print.setEnabled(False)
        self.btn_panel_print.clicked.connect(self.print_report)
        self.fp_layout.addWidget(self.btn_panel_print)

        self.btn_panel_export = QPushButton("Export PDF")
        self.btn_panel_export.setEnabled(False)
        self.btn_panel_export.clicked.connect(self.export_report)
        self.fp_layout.addWidget(self.btn_panel_export)

        self.fp_layout.addStretch()
        self.main_splitter.addWidget(self.filter_panel)

        # Set splitter proportions: Left Tree 15%, Viewer 65%, Filter 20%
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 4)
        self.main_splitter.setStretchFactor(2, 1)

        self._load_doctors()
        self._populate_doctor_tree()

    def _populate_doctor_tree(self):
        self.doctor_tree.clear()
        for doc in self._doctors:
            item = QTreeWidgetItem(self.doctor_tree)
            item.setText(0, doc["doctor_name"])
            item.setData(0, Qt.UserRole, doc["id"])
            item.setToolTip(0, f"{doc['doctor_name']} - {doc.get('specialty', '')}")

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int):
        doc_id = item.data(0, Qt.UserRole)
        if doc_id is not None:
            idx = self.doctor_combo.findData(doc_id)
            if idx >= 0:
                self.doctor_combo.setCurrentIndex(idx)
                self.generate_report()

    def _sync_tree_selection(self, index: int):
        doc_id = self.doctor_combo.itemData(index)
        if doc_id is not None:
            for i in range(self.doctor_tree.topLevelItemCount()):
                item = self.doctor_tree.topLevelItem(i)
                if item.data(0, Qt.UserRole) == doc_id:
                    self.doctor_tree.setCurrentItem(item)
                    break

    def generate_report(self):
        from_qdate = self.from_date_edit.date()
        to_qdate = self.to_date_edit.date()

        if from_qdate > to_qdate:
            self._pages = []
            self.viewer.clear_report()
            self.btn_panel_print.setEnabled(False)
            self.btn_panel_export.setEnabled(False)
            self._show_validation_error("From Date must be earlier than or equal to To Date.")
            return

        doctor_id = self.get_selected_doctor_id()
        if doctor_id is None:
            self._pages = []
            self.viewer.clear_report()
            self.btn_panel_print.setEnabled(False)
            self.btn_panel_export.setEnabled(False)
            self._show_validation_error("Please select a Doctor.")
            return

        self.lbl_msg.setText("")
        self.lbl_msg.setVisible(False)

        from_iso = from_qdate.toString("yyyy-MM-dd")
        to_iso = to_qdate.toString("yyyy-MM-dd")
        doctor_name = self.get_selected_doctor_name()

        data = DoctorReportsDAO.get_doctorwise_item_sale(from_iso, to_iso, doctor_id)
        rows = data["rows"]
        summary = data["summary"]

        store_name, store_address = get_default_store_identity()
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1=f"Doctorwise Item Sale from {fmt_date_dash(from_iso)} To {fmt_date_dash(to_iso)}",
            header_line_2=f"Doctor Name: {doctor_name}",
        )

        columns = ["SrNo", "Item Name", "Unit", "SalesQty", "Sales", "Purchase", "NetProfit"]
        widths = [40.0, 244.0, 70.0, 70.0, 100.0, 100.0, 100.0]
        aligns = ["center", "left", "center", "right", "right", "right", "right"]

        table_header_block = ReportBlock(
            BlockKind.TABLE_HEADER,
            22.0,
            {"columns": columns, "widths": widths, "aligns": aligns},
        )

        blocks: List[ReportBlock] = [table_header_block]

        if not rows:
            blocks.append(
                ReportBlock(
                    BlockKind.EMPTY,
                    80.0,
                    {"message": "No transactions found for the selected doctor and date range."},
                )
            )
        else:
            for idx, r in enumerate(rows):
                cells = [
                    str(idx + 1),
                    str(r["item_name"]),
                    str(r["unit_name"]),
                    fmt_qty(r["sales_qty"]),
                    fmt_amt(r["sales"]),
                    fmt_amt(r["purchase"]),
                    fmt_amt(r["net_profit"]),
                ]
                blocks.append(
                    ReportBlock(
                        BlockKind.DATA_ROW,
                        20.0,
                        {"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            # Totals row matching screenshot 1
            custom_cells = [
                {"width": 354.0, "text": "Total :", "align": "right"},
                {"width": 70.0, "text": fmt_qty(summary["total_qty"]), "align": "right"},
                {"width": 100.0, "text": fmt_amt(summary["total_sales"]), "align": "right"},
                {"width": 100.0, "text": fmt_amt(summary["total_purchase"]), "align": "right"},
                {"width": 100.0, "text": fmt_amt(summary["total_net_profit"]), "align": "right"},
            ]
            blocks.append(
                ReportBlock(
                    BlockKind.GRAND_TOTAL,
                    24.0,
                    {"custom_cells": custom_cells},
                )
            )

        self._pages = paginate_doctor_report_blocks(header, blocks, table_header_block)
        self.viewer.set_pages(self._pages)
        has_data = bool(rows)
        self.btn_panel_print.setEnabled(has_data)
        self.btn_panel_export.setEnabled(has_data)

    def refresh_theme(self):
        super().refresh_theme()
        p = theme.theme_manager.palette()
        is_dark = theme.theme_manager.is_dark()
        if hasattr(self, "tree_pane"):
            panel_bg = p["surface"] if is_dark else "#F4F7FB"
            panel_border = p["border"] if is_dark else "#B0C4DE"
            self.tree_pane.setStyleSheet(
                f"QFrame {{ background-color: {panel_bg}; border-right: 1px solid {panel_border}; }}"
                f"QLabel {{ color: {p['text']}; font-weight: bold; background: transparent; }}"
                f"QTreeWidget {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; }}"
                f"QTreeWidget::item:selected {{ background-color: {p['selected']}; color: {p['selected_text']}; }}"
            )


# ══════════════════════════════════════════════════════════════════════
# 2. Doctorwise Item Sale Details Page (Report 2)
# ══════════════════════════════════════════════════════════════════════

class DoctorwiseItemSaleDetailsPage(_BaseDoctorReportPage):
    """Doctorwise Item Sale Details report screen with left item selection tree."""

    def __init__(self, parent: Optional[QWidget] = None):
        self._all_items_master: List[Dict[str, Any]] = []
        self._selected_item_id: Optional[int] = None
        super().__init__(
            window_title="Doctorwise Item Sale Details Report",
            panel_title="Doctorwise Item Sales Details",
            parent=parent,
        )

    def _init_filter_controls(self):
        # 1. Left Item Selection Pane
        self.item_tree_pane = QFrame()
        self.item_tree_pane.setMinimumWidth(180)
        self.item_tree_pane.setMaximumWidth(320)
        itp_layout = QVBoxLayout(self.item_tree_pane)
        itp_layout.setContentsMargins(6, 6, 6, 6)
        itp_layout.setSpacing(6)

        lbl_item_tree = QLabel("Item Selection")
        lbl_item_tree.setStyleSheet("font-size: 12px; font-weight: bold;")
        itp_layout.addWidget(lbl_item_tree)

        self.item_search = QLineEdit()
        self.item_search.setPlaceholderText("🔍 Search item...")
        self.item_search.textChanged.connect(self._filter_item_tree)
        itp_layout.addWidget(self.item_search)

        self.item_tree = QTreeWidget()
        self.item_tree.setHeaderHidden(True)
        self.item_tree.itemClicked.connect(self._on_item_tree_clicked)
        itp_layout.addWidget(self.item_tree, 1)

        self.main_splitter.addWidget(self.item_tree_pane)
        self.main_splitter.addWidget(self.viewer)

        # 2. Right filter panel
        self.lbl_from = QLabel("From Date:")
        self.fp_layout.addWidget(self.lbl_from)
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.from_date_edit)

        self.lbl_to = QLabel("To")
        self.fp_layout.addWidget(self.lbl_to)
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        self.fp_layout.addWidget(self.to_date_edit)

        self._init_default_dates()

        self.lbl_doctor = QLabel("Doctor:")
        self.fp_layout.addWidget(self.lbl_doctor)

        self.doctor_combo = QComboBox()
        self.doctor_combo.setEditable(True)
        self.doctor_combo.setInsertPolicy(QComboBox.NoInsert)
        if self.doctor_combo.completer():
            self.doctor_combo.completer().setCaseSensitivity(Qt.CaseInsensitive)
            self.doctor_combo.completer().setFilterMode(Qt.MatchContains)
        self.doctor_combo.currentIndexChanged.connect(self._on_doctor_changed)
        self.fp_layout.addWidget(self.doctor_combo)

        self.lbl_msg = QLabel("")
        self.lbl_msg.setStyleSheet("color: #C00000; font-size: 11px; font-weight: bold; background: transparent;")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setVisible(False)
        self.fp_layout.addWidget(self.lbl_msg)

        self.fp_layout.addSpacing(6)

        self.btn_show_report = QPushButton("Show Report")
        self.btn_show_report.clicked.connect(self.generate_report)
        self.fp_layout.addWidget(self.btn_show_report)

        self.btn_panel_print = QPushButton("Print")
        self.btn_panel_print.setEnabled(False)
        self.btn_panel_print.clicked.connect(self.print_report)
        self.fp_layout.addWidget(self.btn_panel_print)

        self.btn_panel_export = QPushButton("Export PDF")
        self.btn_panel_export.setEnabled(False)
        self.btn_panel_export.clicked.connect(self.export_report)
        self.fp_layout.addWidget(self.btn_panel_export)

        self.fp_layout.addStretch()
        self.main_splitter.addWidget(self.filter_panel)

        # Proportions: Left Tree 20%, Viewer 60%, Filter 20%
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 4)
        self.main_splitter.setStretchFactor(2, 1)

        self._load_doctors()
        self._load_master_items()

    def _load_master_items(self):
        self._all_items_master = DoctorReportsDAO.get_all_master_items()
        self._populate_item_tree(self._all_items_master)

    def _populate_item_tree(self, items: List[Dict[str, Any]]):
        self.item_tree.clear()
        # All items root entry
        all_item = QTreeWidgetItem(self.item_tree)
        all_item.setText(0, "★ (All Items)")
        all_item.setData(0, Qt.UserRole, None)
        all_item.setFont(0, QFont("Segoe UI", 9, QFont.Bold))

        for it in items:
            node = QTreeWidgetItem(self.item_tree)
            node.setText(0, it["item_name"])
            node.setData(0, Qt.UserRole, it["id"])
            if it.get("unit_name"):
                node.setToolTip(0, f"{it['item_name']} [{it['unit_name']}]")

        if self._selected_item_id is None:
            self.item_tree.setCurrentItem(all_item)

    def _filter_item_tree(self, search_text: str):
        query = search_text.strip().lower()
        for i in range(self.item_tree.topLevelItemCount()):
            item = self.item_tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) is None:
                item.setHidden(False)
                continue
            text = item.text(0).lower()
            item.setHidden(query not in text if query else False)

    def _on_doctor_changed(self, index: int):
        doctor_id = self.doctor_combo.itemData(index)
        if doctor_id is not None:
            from_iso = self.from_date_edit.date().toString("yyyy-MM-dd")
            to_iso = self.to_date_edit.date().toString("yyyy-MM-dd")
            sold_items = DoctorReportsDAO.get_items_for_doctor(from_iso, to_iso, doctor_id)
            if sold_items:
                self._populate_item_tree(sold_items)
            else:
                self._populate_item_tree(self._all_items_master)

    def _on_item_tree_clicked(self, item: QTreeWidgetItem, column: int):
        item_id = item.data(0, Qt.UserRole)
        self._selected_item_id = item_id
        if self.get_selected_doctor_id() is not None:
            self.generate_report()

    def generate_report(self):
        from_qdate = self.from_date_edit.date()
        to_qdate = self.to_date_edit.date()

        if from_qdate > to_qdate:
            self._pages = []
            self.viewer.clear_report()
            self.btn_panel_print.setEnabled(False)
            self.btn_panel_export.setEnabled(False)
            self._show_validation_error("From Date must be earlier than or equal to To Date.")
            return

        doctor_id = self.get_selected_doctor_id()
        if doctor_id is None:
            self._pages = []
            self.viewer.clear_report()
            self.btn_panel_print.setEnabled(False)
            self.btn_panel_export.setEnabled(False)
            self._show_validation_error("Please select a Doctor.")
            return

        self.lbl_msg.setText("")
        self.lbl_msg.setVisible(False)

        from_iso = from_qdate.toString("yyyy-MM-dd")
        to_iso = to_qdate.toString("yyyy-MM-dd")
        doctor_name = self.get_selected_doctor_name()

        # Query details, filtered by selected_item_id if not None
        data = DoctorReportsDAO.get_doctorwise_item_sale_details(
            from_date=from_iso,
            to_date=to_iso,
            doctor_id=doctor_id,
            item_id=self._selected_item_id,
        )
        groups = data["groups"]
        summary = data["summary"]

        # Also refresh sold items in the item tree if tree was showing master items
        if self._selected_item_id is None:
            sold_items = DoctorReportsDAO.get_items_for_doctor(from_iso, to_iso, doctor_id)
            if sold_items:
                current_selected = self.item_tree.currentItem()
                cur_data = current_selected.data(0, Qt.UserRole) if current_selected else None
                self._populate_item_tree(sold_items)
                if cur_data is not None:
                    for i in range(self.item_tree.topLevelItemCount()):
                        ti = self.item_tree.topLevelItem(i)
                        if ti.data(0, Qt.UserRole) == cur_data:
                            self.item_tree.setCurrentItem(ti)
                            break

        store_name, store_address = get_default_store_identity()
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1=f"Doctorwise Item Sale Details from {fmt_date_dash(from_iso)} To {fmt_date_dash(to_iso)}",
            header_line_2=f"Doctor Name: {doctor_name}",
        )

        columns = ["SrNo", "VhType", "BillNo", "PatientName", "Address", "MRP", "SalesQty", "TotSalesAmt"]
        widths = [36.0, 50.0, 50.0, 178.0, 130.0, 80.0, 80.0, 120.0]
        aligns = ["center", "center", "center", "left", "left", "right", "right", "right"]

        blocks: List[ReportBlock] = []

        if not groups:
            table_hdr = ReportBlock(
                BlockKind.TABLE_HEADER,
                22.0,
                {"columns": columns, "widths": widths, "aligns": aligns},
            )
            blocks.append(table_hdr)
            blocks.append(
                ReportBlock(
                    BlockKind.EMPTY,
                    80.0,
                    {"message": "No transactions found for the selected doctor, date range, and item."},
                )
            )
        else:
            for g in groups:
                # Group Header: Item Name in bold
                blocks.append(
                    ReportBlock(
                        BlockKind.GROUP_HEADER,
                        24.0,
                        {"text": f"{g['item_name']}"},
                    )
                )

                # Table Header for this item
                table_hdr = ReportBlock(
                    BlockKind.TABLE_HEADER,
                    22.0,
                    {"columns": columns, "widths": widths, "aligns": aligns},
                )
                blocks.append(table_hdr)

                # Data rows for this item
                for sr_no, line in enumerate(g["lines"], start=1):
                    cells = [
                        str(sr_no),
                        str(line["voucher_type"]),
                        str(line["bill_no_display"]),
                        str(line["patient_name"]),
                        str(line["address"]),
                        fmt_amt(line["mrp"]),
                        fmt_qty(line["sale_qty"]),
                        fmt_amt(line["amount"]),
                    ]
                    blocks.append(
                        ReportBlock(
                            BlockKind.DATA_ROW,
                            20.0,
                            {"cells": cells, "widths": widths, "aligns": aligns},
                        )
                    )

                # Item Subtotal row matching screenshot 2
                subtotal_cells = [
                    {"width": 524.0, "text": "Total :", "align": "right"},
                    {"width": 80.0, "text": fmt_qty(g["subtotal_qty"]), "align": "right"},
                    {"width": 120.0, "text": fmt_amt(g["subtotal_amount"]), "align": "right"},
                ]
                blocks.append(
                    ReportBlock(
                        BlockKind.ITEM_SUBTOTAL,
                        22.0,
                        {"custom_cells": subtotal_cells},
                    )
                )

            # Grand Total row if multiple items
            if len(groups) > 1:
                grand_cells = [
                    {"width": 524.0, "text": "Grand Total :", "align": "right"},
                    {"width": 80.0, "text": fmt_qty(summary["grand_total_qty"]), "align": "right"},
                    {"width": 120.0, "text": fmt_amt(summary["grand_total_amount"]), "align": "right"},
                ]
                blocks.append(
                    ReportBlock(
                        BlockKind.GRAND_TOTAL,
                        24.0,
                        {"custom_cells": grand_cells},
                    )
                )

        default_table_hdr = ReportBlock(
            BlockKind.TABLE_HEADER,
            22.0,
            {"columns": columns, "widths": widths, "aligns": aligns},
        )
        self._pages = paginate_doctor_report_blocks(header, blocks, default_table_hdr)
        self.viewer.set_pages(self._pages)
        has_data = bool(groups)
        self.btn_panel_print.setEnabled(has_data)
        self.btn_panel_export.setEnabled(has_data)

    def refresh_theme(self):
        super().refresh_theme()
        p = theme.theme_manager.palette()
        is_dark = theme.theme_manager.is_dark()
        if hasattr(self, "item_tree_pane"):
            panel_bg = p["surface"] if is_dark else "#F4F7FB"
            panel_border = p["border"] if is_dark else "#B0C4DE"
            self.item_tree_pane.setStyleSheet(
                f"QFrame {{ background-color: {panel_bg}; border-right: 1px solid {panel_border}; }}"
                f"QLabel {{ color: {p['text']}; font-weight: bold; background: transparent; }}"
                f"QLineEdit {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 2px; padding: 4px; font-size: 12px; }}"
                f"QTreeWidget {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; }}"
                f"QTreeWidget::item:selected {{ background-color: {p['selected']}; color: {p['selected_text']}; }}"
            )
