from __future__ import annotations

from PySide6.QtGui import QColor
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

from database.account_roles import ensure_system_ledgers, get_role_status

from ui.theme import palette
_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]
_OK_COLOR = QColor("#2e7d32")
_MISSING_COLOR = QColor("#c0392b")

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

_NOTE_STYLE = (
    f"color: {_TEXT_DIM}; font-size: 11px; font-family: 'Segoe UI';"
    f" background: transparent;"
)


class AccountRolesPage(QWidget):
    """Account Roles configuration page (read-only status + initialize).

    Shows every required system role and whether it is configured. The only
    write action is "Initialize Missing Accounts", which runs the idempotent
    ensure routine. Role assignment/removal and ledger deletion are
    intentionally NOT available in this first version.
    """

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

        title = QLabel("Account Roles")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        init_btn = QPushButton("Initialize Missing Accounts")
        init_btn.setStyleSheet(_BTN_SAVE)
        init_btn.clicked.connect(self._on_initialize)
        hl.addWidget(init_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(90)
        refresh_btn.setStyleSheet(_BTN_SECONDARY)
        refresh_btn.clicked.connect(self._on_refresh)
        hl.addWidget(refresh_btn)

        root.addWidget(header)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            "Role", "Ledger Name", "Ledger ID", "Status"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 12px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        root.addWidget(self._table, 1)

        # Footer note
        note = QLabel(
            "System roles are used by the accounting posting engine. "
            "Role assignment and deletion are managed here only — system "
            "ledgers cannot be deleted."
        )
        note.setStyleSheet(_NOTE_STYLE)
        note.setContentsMargins(16, 8, 16, 8)
        root.addWidget(note)

        self._refresh()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _refresh(self):
        rows = get_role_status()
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(r["role"]))
            self._table.setItem(i, 1, QTableWidgetItem(r["ledger_name"]))
            self._table.setItem(
                i, 2,
                QTableWidgetItem(str(r["ledger_id"]) if r["ledger_id"] else "")
            )

            status_item = QTableWidgetItem(r["status"])
            if r["status"] == "Configured":
                status_item.setForeground(_OK_COLOR)
            else:
                status_item.setForeground(_MISSING_COLOR)
            self._table.setItem(i, 3, status_item)

            self._table.item(i, 0).setToolTip(r["description"])

    def _on_refresh(self):
        self._refresh()

    def _on_initialize(self):
        result = ensure_system_ledgers()
        msg = (
            f"Created: {len(result['created'])}   "
            f"Reused: {len(result['reused'])}   "
            f"Already configured: {len(result['already_configured'])}"
        )
        if result["created"]:
            msg += "\n\nNew: " + ", ".join(result["created"])
        QMessageBox.information(self, "Initialize Missing Accounts", msg)
        self._refresh()
