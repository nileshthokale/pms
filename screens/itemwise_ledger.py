"""Itemwise Ledger report screen.

Displays chronological inventory transactions for a selected medicine / item:
- Date range filtering respecting the active / selected financial year
- Searchable medicine / item selector
- Opening stock before the first transaction (in loose units)
- Transaction-wise inward, outward, batch, expiry, voucher details, and running closing stock
- Closing stock after the last transaction (in loose units)
- Comparison against current on-hand batch stock
- Full day/night theme support
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from core.doc_formatter import format_document_number
from database import financial_year
from database.ledger_report_dao import LedgerReportDAO
from screens.ledger_widgets import (
    SearchableSelector,
    btn_primary_style,
    btn_secondary_style,
    make_date_edit,
    table_header_style,
    table_style,
)
from ui.fy_view import view_year_bounds
from ui.theme import palette, TYPE_PAGE_TITLE


class ItemwiseLedgerPage(QWidget):
    """Itemwise Ledger page (Reports -> Itemwise Ledger)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._history_financial_year: dict | None = None
        self._last_report: dict | None = None

        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 1. Header ───────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(54)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(16, 0, 16, 0)

        self._title_label = QLabel("Itemwise Ledger")
        self._title_label.setStyleSheet(
            f"color: {p['text']}; font-size: {TYPE_PAGE_TITLE}px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(self._title_label)

        self._header_hint = QLabel(
            "Medicine inventory ledger · Inward / Outward · Batches · Running stock"
        )
        self._header_hint.setStyleSheet(
            f"color: {p['text_dim']}; font-size: 13px; background: transparent;"
            f"font-family: 'Segoe UI'; margin-left: 14px;"
        )
        hl.addWidget(self._header_hint)
        hl.addStretch()

        root.addWidget(self._header)

        # ── 2. Filter Bar ───────────────────────────────────────────
        self._filter_bar = QWidget()
        fl = QHBoxLayout(self._filter_bar)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.setSpacing(10)

        self._lbl_item = QLabel("Medicine / Item:")
        self._lbl_item.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: 14px;")
        fl.addWidget(self._lbl_item)

        self._item_selector = SearchableSelector(placeholder="-- Select Item / Medicine --")
        self._item_selector.setMinimumWidth(280)
        self._item_selector.selection_changed.connect(self._on_item_changed)
        fl.addWidget(self._item_selector)

        self._lbl_from = QLabel("From Date:")
        self._lbl_from.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: 14px;")
        fl.addWidget(self._lbl_from)

        self._from_date = make_date_edit(self)
        self._from_date.setFixedWidth(125)
        fl.addWidget(self._from_date)

        self._lbl_to = QLabel("To Date:")
        self._lbl_to.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: 14px;")
        fl.addWidget(self._lbl_to)

        self._to_date = make_date_edit(self)
        self._to_date.setFixedWidth(125)
        fl.addWidget(self._to_date)

        self._btn_show = QPushButton("Show Report")
        self._btn_show.setStyleSheet(btn_primary_style(p))
        self._btn_show.clicked.connect(self._on_generate)
        fl.addWidget(self._btn_show)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setStyleSheet(btn_secondary_style(p))
        self._btn_refresh.clicked.connect(self._on_refresh)
        fl.addWidget(self._btn_refresh)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setStyleSheet(btn_secondary_style(p))
        self._btn_clear.clicked.connect(self._on_clear)
        fl.addWidget(self._btn_clear)

        fl.addStretch()
        root.addWidget(self._filter_bar)

        # ── 3. Summary Panel ────────────────────────────────────────
        self._summary_panel = QWidget()
        self._summary_panel.setFixedHeight(68)
        sl = QHBoxLayout(self._summary_panel)
        sl.setContentsMargins(16, 6, 16, 6)
        sl.setSpacing(20)

        # Details box
        self._info_item = QLabel("Item: -")
        self._info_item.setStyleSheet(f"color: {p['text']}; font-size: 14px; font-weight: bold;")
        sl.addWidget(self._info_item)

        # Opening stock
        self._lbl_card_os = QLabel("Opening Stock:")
        self._lbl_card_os.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_os = QLabel("0")
        self._val_card_os.setStyleSheet(f"color: {p['text']}; font-size: 15px; font-weight: bold;")
        os_box = QVBoxLayout()
        os_box.setSpacing(2)
        os_box.addWidget(self._lbl_card_os)
        os_box.addWidget(self._val_card_os)
        sl.addLayout(os_box)

        # Total Inward
        self._lbl_card_in = QLabel("Total Inward:")
        self._lbl_card_in.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_in = QLabel("0")
        self._val_card_in.setStyleSheet(f"color: {p['text']}; font-size: 15px; font-weight: bold;")
        in_box = QVBoxLayout()
        in_box.setSpacing(2)
        in_box.addWidget(self._lbl_card_in)
        in_box.addWidget(self._val_card_in)
        sl.addLayout(in_box)

        # Total Outward
        self._lbl_card_out = QLabel("Total Outward:")
        self._lbl_card_out.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_out = QLabel("0")
        self._val_card_out.setStyleSheet(f"color: {p['text']}; font-size: 15px; font-weight: bold;")
        out_box = QVBoxLayout()
        out_box.setSpacing(2)
        out_box.addWidget(self._lbl_card_out)
        out_box.addWidget(self._val_card_out)
        sl.addLayout(out_box)

        # Closing Stock
        self._lbl_card_cs = QLabel("Closing Stock:")
        self._lbl_card_cs.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_cs = QLabel("0")
        self._val_card_cs.setStyleSheet(f"color: {p['accent']}; font-size: 16px; font-weight: bold;")
        cs_box = QVBoxLayout()
        cs_box.setSpacing(2)
        cs_box.addWidget(self._lbl_card_cs)
        cs_box.addWidget(self._val_card_cs)
        sl.addLayout(cs_box)

        # Current on hand
        self._lbl_card_hand = QLabel("Batch Stock (On Hand):")
        self._lbl_card_hand.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_hand = QLabel("0")
        self._val_card_hand.setStyleSheet(f"color: {p.get('success', '#2e7d32')}; font-size: 15px; font-weight: bold;")
        hand_box = QVBoxLayout()
        hand_box.setSpacing(2)
        hand_box.addWidget(self._lbl_card_hand)
        hand_box.addWidget(self._val_card_hand)
        sl.addLayout(hand_box)

        sl.addStretch()

        # Warning / status indicator
        self._status_badge = QLabel("")
        self._status_badge.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px;")
        sl.addWidget(self._status_badge)

        root.addWidget(self._summary_panel)

        # ── 4. Transaction Table ────────────────────────────────────
        self._columns = [
            "Date", "Particulars", "Voucher No", "Voucher Type",
            "Batch No", "Expiry", "Inward Qty", "Outward Qty", "Closing Stock"
        ]
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Date
        hv.setSectionResizeMode(1, QHeaderView.Stretch)           # Particulars
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Voucher No
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Voucher Type
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Batch No
        hv.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Expiry
        hv.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Inward
        hv.setSectionResizeMode(7, QHeaderView.ResizeToContents)  # Outward
        hv.setSectionResizeMode(8, QHeaderView.ResizeToContents)  # Closing Stock

        root.addWidget(self._table, 1)

        self._apply_theme_styles(p)
        self._load_options()
        self._set_default_dates()

    # ── Option loading & Date initialization ─────────────────────────

    def _load_options(self):
        items = LedgerReportDAO.get_item_options()
        self._item_selector.set_options(
            items, id_key="id", name_key="item_name", subtitle_key="company_name"
        )

    def _set_default_dates(self):
        """Default range: FY start date to today's date, respecting viewing FY."""
        fy_from, fy_to = view_year_bounds(self._history_financial_year)
        today_iso = date.today().isoformat()
        if fy_from <= today_iso <= fy_to:
            default_to = today_iso
        elif today_iso > fy_to:
            default_to = fy_to
        else:
            default_to = fy_to

        self._from_date.blockSignals(True)
        self._to_date.blockSignals(True)
        self._from_date.setDate(QDate.fromString(fy_from, "yyyy-MM-dd"))
        self._to_date.setDate(QDate.fromString(default_to, "yyyy-MM-dd"))
        self._from_date.blockSignals(False)
        self._to_date.blockSignals(False)

    def set_history_financial_year(self, year: dict | None) -> None:
        """Called when user changes financial year view from the navigation bar."""
        self._history_financial_year = dict(year) if year else None
        self._set_default_dates()
        if self._item_selector.selected_id:
            self._on_generate()

    # ── Report Generation ────────────────────────────────────────────

    def _on_item_changed(self, item_id):
        if item_id:
            self._on_generate()

    def _on_refresh(self):
        self._load_options()
        if self._item_selector.selected_id:
            self._on_generate()

    def _on_clear(self):
        self._item_selector.clear_selection()
        self._set_default_dates()
        self._table.setRowCount(0)
        self._info_item.setText("Item: -")
        self._val_card_os.setText("0")
        self._val_card_in.setText("0")
        self._val_card_out.setText("0")
        self._val_card_cs.setText("0")
        self._val_card_hand.setText("0")
        self._status_badge.setText("")

    def _on_generate(self):
        item_id = self._item_selector.selected_id
        if not item_id:
            QMessageBox.information(
                self, "Itemwise Ledger", "Please select a medicine / item from the list."
            )
            return

        from_iso = self._from_date.date().toString("yyyy-MM-dd")
        to_iso = self._to_date.date().toString("yyyy-MM-dd")

        if from_iso > to_iso:
            QMessageBox.warning(
                self, "Date Error", "From Date cannot be later than To Date."
            )
            return

        try:
            report = LedgerReportDAO.get_item_ledger(
                item_id=item_id,
                from_date=from_iso,
                to_date=to_iso,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to generate report:\n{exc}")
            return

        self._last_report = report
        self._render(report)

    # ── Rendering ────────────────────────────────────────────────────

    def _render(self, report: dict):
        p = palette()
        item = report.get("item") or {}
        iname = item.get("item_name", "")
        cname = item.get("company_name", "")
        uname = item.get("unit_name", "Units") or "Units"
        psize = item.get("pack_size", "")

        info_parts = [f"Item: {iname}"]
        if cname:
            info_parts.append(f"[{cname}]")
        if psize:
            info_parts.append(f"Pack: {psize}")
        if uname:
            info_parts.append(f"Unit: {uname}")
        self._info_item.setText("  ".join(info_parts))

        os = report["opening_stock"]
        self._val_card_os.setText(f"{os:g} {uname}")

        tin = report["total_inward"]
        tout = report["total_outward"]
        self._val_card_in.setText(f"{tin:g}")
        self._val_card_out.setText(f"{tout:g}")

        cs = report["closing_stock"]
        self._val_card_cs.setText(f"{cs:g} {uname}")

        cbs = report["current_batch_stock"]
        self._val_card_hand.setText(f"{cbs:g} {uname}")

        txns = report["rows"]
        warning = report.get("warning")
        if warning:
            self._status_badge.setText(warning)
            self._status_badge.setStyleSheet(f"color: {p.get('danger', '#c0392b')}; font-size: 13px; font-weight: bold;")
        elif not txns:
            self._status_badge.setText("No stock movements found in selected period.")
            self._status_badge.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: normal;")
        else:
            self._status_badge.setText(f"{len(txns)} movement(s)")
            self._status_badge.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: normal;")

        total_rows = len(txns) + 2
        self._table.setRowCount(total_rows)

        # ── Row 0: Opening Stock ──
        self._set_cell(0, 0, report["from_date"], bold=True)
        self._set_cell(0, 1, "*** OPENING STOCK ***", bold=True)
        self._set_cell(0, 2, "-", align=Qt.AlignCenter)
        self._set_cell(0, 3, "-", align=Qt.AlignCenter)
        self._set_cell(0, 4, "-", align=Qt.AlignCenter)
        self._set_cell(0, 5, "-", align=Qt.AlignCenter)
        self._set_cell(0, 6, "-", align=Qt.AlignRight)
        self._set_cell(0, 7, "-", align=Qt.AlignRight)
        self._set_cell(0, 8, f"{os:g}", bold=True, align=Qt.AlignRight,
                       color=p.get("success", "#2e7d32") if os >= 0 else p.get("danger", "#c0392b"))

        # ── Rows 1..N: Movements ──
        for idx, t in enumerate(txns, start=1):
            self._set_cell(idx, 0, t["date"])
            self._set_cell(idx, 1, t["particulars"])

            vno = t["voucher_no"]
            disp_vno = format_document_number(vno)
            self._set_cell(idx, 2, disp_vno, tooltip=f"Voucher: {vno}")

            self._set_cell(idx, 3, t["voucher_type"])
            self._set_cell(idx, 4, t["batch_no"])
            self._set_cell(idx, 5, t["expiry"])

            in_q = t["inward_qty"]
            in_text = f"{in_q:g}" if in_q else ""
            self._set_cell(idx, 6, in_text, align=Qt.AlignRight)

            out_q = t["outward_qty"]
            out_text = f"{out_q:g}" if out_q else ""
            self._set_cell(idx, 7, out_text, align=Qt.AlignRight)

            stock = t["closing_stock"]
            color = p.get("success", "#2e7d32") if stock >= 0 else p.get("danger", "#c0392b")
            self._set_cell(idx, 8, f"{stock:g}", align=Qt.AlignRight, color=color)

        # ── Last Row: Totals & Closing Stock ──
        last_row = total_rows - 1
        self._set_cell(last_row, 0, report["to_date"], bold=True)
        self._set_cell(last_row, 1, "*** TOTALS & CLOSING STOCK ***", bold=True)
        self._set_cell(last_row, 2, "-", align=Qt.AlignCenter)
        self._set_cell(last_row, 3, "-", align=Qt.AlignCenter)
        self._set_cell(last_row, 4, "-", align=Qt.AlignCenter)
        self._set_cell(last_row, 5, "-", align=Qt.AlignCenter)
        self._set_cell(last_row, 6, f"{tin:g}", bold=True, align=Qt.AlignRight)
        self._set_cell(last_row, 7, f"{tout:g}", bold=True, align=Qt.AlignRight)
        self._set_cell(last_row, 8, f"{cs:g}", bold=True, align=Qt.AlignRight,
                       color=p.get("success", "#2e7d32") if cs >= 0 else p.get("danger", "#c0392b"))

    def _set_cell(
        self,
        row: int,
        col: int,
        text: str,
        bold: bool = False,
        align: int = Qt.AlignLeft | Qt.AlignVCenter,
        color: str | None = None,
        tooltip: str | None = None,
    ):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align)
        if bold:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        if color:
            from PySide6.QtGui import QColor
            item.setForeground(QColor(color))
        if tooltip:
            item.setToolTip(tooltip)
        self._table.setItem(row, col, item)

    # ── Theme Refresh ────────────────────────────────────────────────

    def _apply_theme_styles(self, p: dict):
        self.setStyleSheet(f"background-color: {p['bg']};")
        self._header.setStyleSheet(
            f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};"
        )
        self._filter_bar.setStyleSheet(
            f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};"
        )
        self._summary_panel.setStyleSheet(
            f"background-color: {p.get('surface_alt', p['surface'])}; border-bottom: 1px solid {p['border']};"
        )
        self._table.setStyleSheet(table_style(p))
        self._table.horizontalHeader().setStyleSheet(table_header_style(p))

        self._btn_show.setStyleSheet(btn_primary_style(p))
        self._btn_refresh.setStyleSheet(btn_secondary_style(p))
        self._btn_clear.setStyleSheet(btn_secondary_style(p))

        self._item_selector.refresh_theme(p)

    def refresh_theme(self, p: dict | None = None) -> None:
        p = p or palette()
        self._apply_theme_styles(p)
        if self._last_report:
            self._render(self._last_report)
