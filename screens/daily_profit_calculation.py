"""Daily Profit Calculation Screen.

Calculates actual medicine purchase cost per tablet/unit accounting for
free quantities and purchase discounts, then computes profit on quantities sold.

Adheres strictly to the formula:
- Net Purchase Cost = (Paid Quantity × Purchase Rate) − Purchase Discount
- Total Quantity Received = Paid Quantity + Free Quantity
- Actual Net Purchase Cost Per Tablet = Net Purchase Cost ÷ Total Quantity Received
- Profit Per Tablet = Actual Selling Rate − Actual Net Purchase Cost
- Total Profit = Total Net Sales − Total Purchase Cost of Sold Quantity
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.sales_reports_dao import SalesReportsDAO
from ui import components as ui
from screens.sales_reports import paginate_sales_blocks
from ui.crystal_report_viewer import (
    BlockKind,
    CONTENT_WIDTH_LANDSCAPE,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    fmt_date_dash,
    get_default_store_identity,
    print_or_export_report_pages,
)
from ui.theme import theme_manager


def palette() -> Dict[str, Any]:
    return theme_manager.palette()


class DailyProfitCostReportWidget(QWidget):
    """Wide tabular profit calculation view with actual purchase cost per tablet."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pages: List[ReportPage] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── 1. Filter Strip ──────────────────────────────────────────
        filter_box = QFrame()
        filter_box.setObjectName("FilterBox")
        fb_layout = QVBoxLayout(filter_box)
        fb_layout.setContentsMargins(8, 8, 8, 8)
        fb_layout.setSpacing(8)

        # Row 1: Filters (From, To, Medicine, Company)
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        row1.addWidget(QLabel("From Date:"))
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDate(QDate.currentDate())
        row1.addWidget(self.from_date_edit)

        row1.addWidget(QLabel("To Date:"))
        self.to_date_edit = QDateEdit()
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setCalendarPopup(True)
        self.to_date_edit.setDate(QDate.currentDate())
        row1.addWidget(self.to_date_edit)

        row1.addWidget(QLabel("Medicine:"))
        self.item_combo = QComboBox()
        self.item_combo.setMinimumWidth(180)
        self.item_combo.setEditable(True)
        self.item_combo.setInsertPolicy(QComboBox.NoInsert)
        ui.style_combo(self.item_combo)
        row1.addWidget(self.item_combo)

        row1.addWidget(QLabel("Company:"))
        self.company_combo = QComboBox()
        self.company_combo.setMinimumWidth(180)
        self.company_combo.setEditable(True)
        self.company_combo.setInsertPolicy(QComboBox.NoInsert)
        ui.style_combo(self.company_combo)
        row1.addWidget(self.company_combo)

        row1.addStretch()
        fb_layout.addLayout(row1)

        # Row 2: Action Buttons
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self.btn_search = QPushButton("Search")
        self.btn_search.clicked.connect(self.load_data)
        row2.addWidget(self.btn_search)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.clear_filters)
        row2.addWidget(self.btn_clear)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.load_data)
        row2.addWidget(self.btn_refresh)

        self.btn_export = QPushButton("Export CSV")
        self.btn_export.clicked.connect(self.export_csv)
        row2.addWidget(self.btn_export)

        self.btn_print = QPushButton("Print")
        self.btn_print.setEnabled(False)
        self.btn_print.clicked.connect(self.print_report)
        row2.addWidget(self.btn_print)

        row2.addStretch()
        fb_layout.addLayout(row2)

        root.addWidget(filter_box)

        # Populate combos
        self._populate_filter_lookups()

        # ── 2. Table Widget ──────────────────────────────────────────
        self.table = QTableWidget()
        headers = [
            "Sr. No.",
            "Medicine Name",
            "Company Name",
            "Batch Number",
            "Total Quantity Sold",
            "Actual Selling Rate",
            "Purchase Rate",
            "Free Quantity",
            "Purchase Discount",
            "Actual Net Purchase Cost Per Tablet",
            "Total Net Sales",
            "Total Purchase Cost of Sold Quantity",
            "Total Profit",
        ]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

        # ── 3. Summary Strip ─────────────────────────────────────────
        self.lbl_summary = QLabel("Ready")
        self.lbl_summary.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        root.addWidget(self.lbl_summary)

        self.refresh_theme()

    def _populate_filter_lookups(self):
        """Populate medicine and company combos from database masters."""
        # Items
        self.item_combo.clear()
        self.item_combo.addItem("-- All Medicines --", None)
        try:
            for it in SalesReportsDAO.get_filter_items():
                disp = f"{it['item_name']} ({it['company_code'] or it['company_name']})" if (it.get('company_code') or it.get('company_name')) else it['item_name']
                self.item_combo.addItem(disp, it["id"])
        except Exception:
            pass
        if self.item_combo.completer():
            self.item_combo.completer().setFilterMode(Qt.MatchContains)

        # Companies
        self.company_combo.clear()
        self.company_combo.addItem("-- All Companies --", None)
        try:
            for c in SalesReportsDAO.get_filter_companies():
                self.company_combo.addItem(c["company_name"], c["id"])
        except Exception:
            pass
        if self.company_combo.completer():
            self.company_combo.completer().setFilterMode(Qt.MatchContains)

    def clear_filters(self):
        """Reset date range and combo filters to default."""
        self.from_date_edit.setDate(QDate.currentDate())
        self.to_date_edit.setDate(QDate.currentDate())
        self.item_combo.setCurrentIndex(0)
        self.company_combo.setCurrentIndex(0)
        self.table.setRowCount(0)
        self._pages = []
        self.btn_print.setEnabled(False)
        self.lbl_summary.setText("Filters cleared. Ready.")

    def load_data(self):
        """Query actual purchase cost and sales profit for selected criteria."""
        from_iso = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_iso = self.to_date_edit.date().toString("yyyy-MM-dd")
        if from_iso > to_iso:
            QMessageBox.warning(self, "Invalid Range", "From Date cannot be later than To Date.")
            return

        item_id = self.item_combo.currentData()
        company_id = self.company_combo.currentData()

        data = SalesReportsDAO.get_daily_profit_cost_calculation(
            from_iso, to_iso, item_id=item_id, company_id=company_id
        )
        rows = data.get("rows", [])
        totals = data.get("summary", {})

        row_count = len(rows) + (1 if rows else 0)
        self.table.setRowCount(row_count)

        for i, r in enumerate(rows):
            # 1. Sr. No.
            sr_item = QTableWidgetItem(str(r["sr_no"]))
            sr_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, sr_item)

            # 2. Medicine Name
            med_item = QTableWidgetItem(str(r["item_name"]))
            med_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(i, 1, med_item)

            # 3. Company Name
            comp_item = QTableWidgetItem(str(r["company_name"]))
            comp_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(i, 2, comp_item)

            # 4. Batch Number
            batch_item = QTableWidgetItem(str(r["batch_no"]))
            batch_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 3, batch_item)

            # 5. Total Quantity Sold
            qty_item = QTableWidgetItem(f"{float(r['total_sold_qty']):,.2f}")
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 4, qty_item)

            # 6. Actual Selling Rate
            sr_rate = QTableWidgetItem(f"{float(r['actual_selling_rate']):,.2f}")
            sr_rate.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 5, sr_rate)

            # 7. Purchase Rate
            pr_rate = QTableWidgetItem(f"{float(r['purchase_rate']):,.2f}")
            pr_rate.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 6, pr_rate)

            # 8. Free Quantity
            free_item = QTableWidgetItem(f"{float(r['free_qty']):,.2f}")
            free_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 7, free_item)

            # 9. Purchase Discount
            disc_item = QTableWidgetItem(f"{float(r['purchase_discount']):,.2f}%")
            disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 8, disc_item)

            # 10. Actual Net Purchase Cost Per Tablet
            cost_item = QTableWidgetItem(f"{float(r['actual_cost_per_tablet']):,.2f}")
            cost_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 9, cost_item)

            # 11. Total Net Sales
            sales_item = QTableWidgetItem(f"{float(r['total_net_sales']):,.2f}")
            sales_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 10, sales_item)

            # 12. Total Purchase Cost of Sold Quantity
            cost_tot_item = QTableWidgetItem(f"{float(r['total_purchase_cost']):,.2f}")
            cost_tot_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 11, cost_tot_item)

            # 13. Total Profit
            prof_item = QTableWidgetItem(f"{float(r['total_profit']):,.2f}")
            prof_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 12, prof_item)

        # Bottom Totals row
        if rows:
            tot_row_idx = len(rows)
            t_label = QTableWidgetItem("Total :")
            t_label.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table.setItem(tot_row_idx, 0, t_label)

            # Empty for cols 1-3
            for c in range(1, 4):
                self.table.setItem(tot_row_idx, c, QTableWidgetItem(""))

            # Total Quantity Sold (Col 4)
            tot_qty = QTableWidgetItem(f"{float(totals.get('total_sold_qty', 0.0)):,.2f}")
            tot_qty.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tot_qty.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table.setItem(tot_row_idx, 4, tot_qty)

            # Empty for cols 5-9
            for c in range(5, 10):
                self.table.setItem(tot_row_idx, c, QTableWidgetItem(""))

            # Total Net Sales (Col 10)
            tot_sales = QTableWidgetItem(f"{float(totals.get('total_net_sales', 0.0)):,.2f}")
            tot_sales.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tot_sales.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table.setItem(tot_row_idx, 10, tot_sales)

            # Total Purchase Cost of Sold Quantity (Col 11)
            tot_cost = QTableWidgetItem(f"{float(totals.get('total_purchase_cost', 0.0)):,.2f}")
            tot_cost.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tot_cost.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table.setItem(tot_row_idx, 11, tot_cost)

            # Total Profit (Col 12)
            tot_prof = QTableWidgetItem(f"{float(totals.get('total_profit', 0.0)):,.2f}")
            tot_prof.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tot_prof.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table.setItem(tot_row_idx, 12, tot_prof)

        self.table.resizeColumnsToContents()
        self._pages = self._build_report_pages(rows, totals, from_iso, to_iso)
        self.btn_print.setEnabled(bool(rows))
        self.lbl_summary.setText(
            f"Records: {len(rows)}  |  "
            f"Total Quantity Sold: {totals.get('total_sold_qty', 0.0):,.2f}  |  "
            f"Total Net Sales: ₹{totals.get('total_net_sales', 0.0):,.2f}  |  "
            f"Total Purchase Cost: ₹{totals.get('total_purchase_cost', 0.0):,.2f}  |  "
            f"Total Profit: ₹{totals.get('total_profit', 0.0):,.2f}"
        )

    def print_report(self):
        if not self._pages:
            return
        print_or_export_report_pages(self._pages, parent=self)

    def _build_report_pages(
        self, rows: List[dict], totals: dict, from_iso: str, to_iso: str
    ) -> List[ReportPage]:
        """Build A4 landscape printable report pages matching on-screen data."""
        store_name, store_address = get_default_store_identity()
        header = ReportHeaderData(
            store_name=store_name,
            store_address=store_address,
            header_line_1="DAILY PROFIT CALCULATION",
            header_line_2=f"From: {fmt_date_dash(from_iso)} To: {fmt_date_dash(to_iso)}",
            header_line_3=(
                f"Total Net Sales: ₹{float(totals.get('total_net_sales', 0.0) or 0.0):,.2f}  |  "
                f"Total Purchase Cost: ₹{float(totals.get('total_purchase_cost', 0.0) or 0.0):,.2f}  |  "
                f"Total Profit: ₹{float(totals.get('total_profit', 0.0) or 0.0):,.2f}"
            ),
        )

        cols = [
            "Sr",
            "Medicine Name",
            "Company Name",
            "Batch",
            "Qty Sold",
            "Selling Rate",
            "Pur. Rate",
            "Free Qty",
            "Pur. Disc",
            "Cost/Tab",
            "Net Sales",
            "Pur. Cost",
            "Profit",
        ]
        # Sums to CONTENT_WIDTH_LANDSCAPE (1053.0)
        widths = [36.0, 160.0, 135.0, 72.0, 60.0, 70.0, 65.0, 55.0, 55.0, 75.0, 85.0, 85.0, 100.0]
        aligns = [
            "center", "left", "left", "center",
            "right", "right", "right", "right",
            "right", "right", "right", "right", "right"
        ]

        table_header_block = ReportBlock(
            kind=BlockKind.TABLE_HEADER,
            height=24.0,
            data={"columns": cols, "widths": widths, "aligns": aligns},
        )
        blocks: List[ReportBlock] = [table_header_block]

        if not rows:
            blocks.append(
                ReportBlock(
                    kind=BlockKind.EMPTY,
                    height=32.0,
                    data={"message": "No sales records found for the selected period and criteria."},
                )
            )
        else:
            for r in rows:
                cells = [
                    str(r.get("sr_no", "")),
                    str(r.get("item_name", "")),
                    str(r.get("company_name", "")),
                    str(r.get("batch_no", "")),
                    f"{float(r.get('total_sold_qty') or 0.0):,.2f}",
                    f"{float(r.get('actual_selling_rate') or 0.0):,.2f}",
                    f"{float(r.get('purchase_rate') or 0.0):,.2f}",
                    f"{float(r.get('free_qty') or 0.0):,.2f}",
                    f"{float(r.get('purchase_discount') or 0.0):,.2f}%",
                    f"{float(r.get('actual_cost_per_tablet') or 0.0):,.2f}",
                    f"{float(r.get('total_net_sales') or 0.0):,.2f}",
                    f"{float(r.get('total_purchase_cost') or 0.0):,.2f}",
                    f"{float(r.get('total_profit') or 0.0):,.2f}",
                ]
                blocks.append(
                    ReportBlock(
                        kind=BlockKind.DATA_ROW,
                        height=18.0,
                        data={"cells": cells, "widths": widths, "aligns": aligns},
                    )
                )

            # Total row
            custom_cells = [
                {"width": widths[0], "text": "Total :", "align": "right", "is_bold": True},
                {"width": widths[1], "text": "", "align": "left", "is_bold": False},
                {"width": widths[2], "text": "", "align": "left", "is_bold": False},
                {"width": widths[3], "text": "", "align": "center", "is_bold": False},
                {"width": widths[4], "text": f"{float(totals.get('total_sold_qty', 0.0)):,.2f}", "align": "right", "is_bold": True},
                {"width": widths[5], "text": "", "align": "right", "is_bold": False},
                {"width": widths[6], "text": "", "align": "right", "is_bold": False},
                {"width": widths[7], "text": "", "align": "right", "is_bold": False},
                {"width": widths[8], "text": "", "align": "right", "is_bold": False},
                {"width": widths[9], "text": "", "align": "right", "is_bold": False},
                {"width": widths[10], "text": f"{float(totals.get('total_net_sales', 0.0)):,.2f}", "align": "right", "is_bold": True},
                {"width": widths[11], "text": f"{float(totals.get('total_purchase_cost', 0.0)):,.2f}", "align": "right", "is_bold": True},
                {"width": widths[12], "text": f"{float(totals.get('total_profit', 0.0)):,.2f}", "align": "right", "is_bold": True},
            ]
            blocks.append(
                ReportBlock(
                    kind=BlockKind.GRAND_TOTAL,
                    height=22.0,
                    data={"custom_cells": custom_cells},
                )
            )

        return paginate_sales_blocks(
            header, blocks, table_header_block, orientation="landscape"
        )

    def export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "Export CSV", "No data to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Daily Profit Calculation", "daily_profit_calculation.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        lines = []
        headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
        lines.append(",".join(f'"{h}"' for h in headers))

        for r in range(self.table.rowCount()):
            row_vals = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                row_vals.append(f'"{item.text() if item else ""}"')
            lines.append(",".join(row_vals))

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            QMessageBox.information(self, "Export", f"File saved:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Failed to export CSV: {exc}")

    def refresh_theme(self):
        p = palette()
        is_dark = p.get("mode") == "dark" or p.get("bg", "").lower() in ("#1e1e1e", "#121212", "#222222")
        self.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']}; font-family: 'Segoe UI';")
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {p['surface']}; color: {p['text']}; gridline-color: {p['border']}; border: 1px solid {p['border']}; }}"
            f"QHeaderView::section {{ background-color: {'#2A2A2A' if is_dark else '#E8EEF5'}; color: {p['text']}; font-weight: bold; border: 1px solid {p['border']}; padding: 4px; }}"
        )
        self.btn_search.setStyleSheet(
            f"QPushButton {{ background-color: #1B5299; color: white; border: none; border-radius: 3px; padding: 6px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #2669B8; }}"
        )
        self.btn_clear.setStyleSheet(
            f"QPushButton {{ background-color: {p['border']}; color: {p['text']}; border: none; border-radius: 3px; padding: 6px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['text_dim']}; color: white; }}"
        )
        self.btn_refresh.setStyleSheet(
            f"QPushButton {{ background-color: {p['border']}; color: {p['text']}; border: none; border-radius: 3px; padding: 6px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['text_dim']}; color: white; }}"
        )
        self.btn_export.setStyleSheet(
            f"QPushButton {{ background-color: {p['border']}; color: {p['text']}; border: none; border-radius: 3px; padding: 6px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['text_dim']}; color: white; }}"
        )
        self.btn_print.setStyleSheet(
            f"QPushButton {{ background-color: #1B5299; color: white; border: none; border-radius: 3px; padding: 6px 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #2669B8; }}"
            f"QPushButton:disabled {{ background-color: {'#404040' if is_dark else '#A0B8D0'}; color: {'#707070' if is_dark else '#E0E8F0'}; }}"
        )


class DailyProfitCalculationReportPage(QWidget):
    """Daily Profit Calculation Report Page embedded in MainWindow stack."""

    close_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.window_title_text = "Daily Profit Calculation"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        title_bar = QFrame()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet(
            "QFrame { background-color: #1B5299; border-bottom: 1px solid #0E356A; }"
            "QLabel { color: #FFFFFF; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; }"
            "QPushButton { background: transparent; color: #FFFFFF; font-size: 14px; font-weight: bold; border: none; width: 28px; height: 28px; }"
            "QPushButton:hover { background-color: #E81123; }"
        )
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(10, 0, 4, 0)
        lbl_title = QLabel("Daily Profit Calculation")
        tb_layout.addWidget(lbl_title)
        tb_layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setToolTip("Close")
        btn_close.clicked.connect(self.close_requested.emit)
        tb_layout.addWidget(btn_close)
        root.addWidget(title_bar)

        self.widget = DailyProfitCostReportWidget(self)
        root.addWidget(self.widget, 1)

    def set_history_financial_year(self, year: Optional[Dict]):
        if year:
            s_date = year.get("start_date")
            e_date = year.get("end_date")
            if s_date:
                self.widget.from_date_edit.setDate(QDate.fromString(s_date, "yyyy-MM-dd"))
            if e_date:
                self.widget.to_date_edit.setDate(QDate.fromString(e_date, "yyyy-MM-dd"))

    def refresh_theme(self):
        self.widget.refresh_theme()


class DailyProfitCostCalculationDialog(QDialog):
    """Separate wide dialog for Daily Profit Calculation."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Daily Profit Calculation")
        self.resize(1300, 680)
        self.setMinimumSize(1000, 500)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.widget = DailyProfitCostReportWidget(self)
        root.addWidget(self.widget)
        self.widget.load_data()
