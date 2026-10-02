"""Hold Bill page — manage draft sales held for later completion.

A held bill is a temporary sales draft.  It does NOT affect stock,
accounting, customer balances, or completed sales until the sale is
explicitly completed via the normal Save Sale flow after resume.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

from database.hold_bill_dao import (
    get_all,
    get_hold_items,
    get_by_id,
    update_status,
    delete_hold,
    STATUS_ACTIVE,
    STATUS_RESUMED,
    STATUS_DISCARDED,
)
from database import auth

from ui.theme import palette
_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]
_ERROR = "#c0392b"
_WARNING = "#b26a00"

_LABEL_STYLE = f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI'; background: transparent;"
_LABEL_DIM = f"color: {_TEXT_DIM}; font-size: 11px; font-family: 'Segoe UI'; background: transparent;"

_BTN_SAVE = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_BTN_SECONDARY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #7d93a8; }}"
)

_BTN_DANGER = (
    f"QPushButton {{ background-color: {_ERROR}; color: white;"
    f"  border: none; border-radius: 3px; padding: 4px 8px;"
    f"  font-weight: bold; font-size: 11px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #d32f2f; }}"
)

_BTN_ORANGE = (
    f"QPushButton {{ background-color: {_WARNING}; color: white;"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #8f5500; }}"
)


class HoldBillPage(QWidget):
    """Hold Bill management page — list, resume, discard held drafts."""

    _TABLE_COLS = 9
    _COL_MAP = {
        0: "hold_number",
        1: "created_at",
        2: "customer_name",
        3: "patient_name",
        4: "counter_no",
        5: "item_count",
        6: "total_amount_preview",
        7: "created_by",
        8: "status",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Hold Bills — Draft Sales")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(100)
        refresh_btn.setStyleSheet(_BTN_SECONDARY)
        refresh_btn.clicked.connect(self._refresh)
        hl.addWidget(refresh_btn)

        resume_btn = QPushButton("Resume")
        resume_btn.setFixedWidth(100)
        resume_btn.setStyleSheet(_BTN_SAVE)
        resume_btn.clicked.connect(self._on_resume)
        hl.addWidget(resume_btn)

        discard_btn = QPushButton("Discard")
        discard_btn.setFixedWidth(100)
        discard_btn.setStyleSheet(_BTN_DANGER)
        discard_btn.clicked.connect(self._on_discard)
        hl.addWidget(discard_btn)

        root.addWidget(header)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(self._TABLE_COLS)
        self._table.setHorizontalHeaderLabels([
            "Hold No", "Date/Time", "Customer", "Patient", "Counter",
            "Items", "Amount", "Created By", "Status",
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(True)
        for i in range(self._TABLE_COLS):
            if i == 0:
                hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            elif i in (2, 3):
                hv.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 9pt;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 11px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        root.addWidget(self._table, 1)

        self._hold_ids: list[int] = []
        self._refresh()

    def _refresh(self):
        holds = get_all()
        self._hold_ids = []
        self._table.setRowCount(len(holds))
        for i, h in enumerate(holds):
            self._hold_ids.append(h["id"])

            self._table.setItem(i, 0, QTableWidgetItem(h.get("hold_number", "")))
            self._table.setItem(i, 1, QTableWidgetItem(h.get("created_at", "")))
            self._table.setItem(i, 2, QTableWidgetItem(h.get("customer_name", "") or ""))
            self._table.setItem(i, 3, QTableWidgetItem(h.get("patient_name", "") or ""))
            self._table.setItem(i, 4, QTableWidgetItem(h.get("counter_no", "") or ""))

            items = get_hold_items(h["id"])
            qty_item = QTableWidgetItem(str(len(items)))
            qty_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 5, qty_item)

            amt_item = QTableWidgetItem(f"{h.get('total_amount_preview', 0.0):.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 6, amt_item)

            self._table.setItem(i, 7, QTableWidgetItem(h.get("created_by", "") or ""))
            self._table.setItem(i, 8, QTableWidgetItem(h.get("status", "")))

    def _selected_hold_id(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if 0 <= row < len(self._hold_ids):
            return self._hold_ids[row]
        return None

    def _on_resume(self):
        try:
            auth.session.require(auth.PERM_COUNTER_SALE)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc))
            return

        hold_id = self._selected_hold_id()
        if not hold_id:
            QMessageBox.information(self, "Resume Hold", "Please select a held bill to resume.")
            return

        hold = get_by_id(hold_id)
        if not hold:
            QMessageBox.warning(self, "Resume Hold", "Held bill not found.")
            return

        if hold["status"] != STATUS_ACTIVE:
            QMessageBox.information(
                self, "Resume Hold",
                f"This held bill is already {hold['status']}."
            )
            return

        items = get_hold_items(hold_id)
        if not items:
            QMessageBox.warning(self, "Resume Hold", "This held bill has no items.")
            return

        hold_data = {"hold": hold, "items": items}

        update_status(hold_id, STATUS_RESUMED,
                      auth.session.user["username"] if auth.session.user else "")

        from screens.counter_sale import CounterSalePage
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, CounterSalePage):
                parent.open_sale_dialog_with_hold(hold_data)
                break
            parent = parent.parent()
        else:
            QMessageBox.information(
                self, "Resume Hold",
                f"Resume data prepared for {hold['hold_number']}.\n"
                f"Items: {len(items)}  |  "
                f"Amount: {hold.get('total_amount_preview', 0.0):.2f}\n\n"
                "Please open New Bill and load the items manually."
            )

        self._refresh()

    def _on_discard(self):
        try:
            auth.session.require(auth.PERM_COUNTER_SALE)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc))
            return

        hold_id = self._selected_hold_id()
        if not hold_id:
            QMessageBox.information(self, "Discard Hold", "Please select a held bill to discard.")
            return

        hold = get_by_id(hold_id)
        if not hold:
            QMessageBox.warning(self, "Discard Hold", "Held bill not found.")
            return

        if hold["status"] != STATUS_ACTIVE:
            QMessageBox.information(
                self, "Discard Hold",
                f"This held bill is already {hold['status']}."
            )
            return

        reply = QMessageBox.question(
            self, "Confirm Discard",
            f"Discard held bill {hold['hold_number']}?\n\n"
            "This action cannot be undone. No stock or accounting will be affected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                delete_hold(hold_id)
                self._refresh()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to discard held bill:\n{e}")
