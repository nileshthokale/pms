from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.ledger_dao import LedgerDAO
from database.account_group_dao import AccountGroupDAO

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
_DEBIT_COLOR = "#2e7d32"
_CREDIT_COLOR = "#c0392b"

_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 6px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 24px; }}"
    f"QComboBox::down-arrow {{ image: none; border: none; }}"
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; selection-background-color: {_ACCENT};"
    f"  font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
)

_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 5px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

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
    f"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #d32f2f; }}"
)

_LABEL_STYLE = f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI'; background: transparent;"
_LABEL_DIM = f"color: {_TEXT}; font-size: 12px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;"
_HEADER_LABEL = f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI'; background: transparent; font-weight: bold;"

_GROUP_BOX = (
    f"QGroupBox {{"
    f"  color: {_TEXT}; font-weight: bold; font-size: 12px;"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  margin-top: 10px; padding-top: 14px;"
    f"}}"
    f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
)


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        return float(text.strip()) if text.strip() else default
    except ValueError:
        return default


def _safe_int(text: str, default: int = 0) -> int:
    try:
        return int(float(text.strip())) if text.strip() else default
    except ValueError:
        return default


def _make_edit(placeholder: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_EDIT_STYLE)
    from PySide6.QtGui import QFont
    e.setFont(QFont("Segoe UI", 12))
    if width:
        e.setMaximumWidth(width)
    return e


def _make_combo() -> QComboBox:
    c = QComboBox()
    c.setStyleSheet(_COMBO_STYLE)
    return c


# ======================================================================
# Ledger Entry Dialog
# ======================================================================

class _LedgerEntryDialog(QDialog):
    """Modal dialog for creating / editing a ledger."""

    def __init__(self, parent: QWidget | None = None, *, ledger: dict | None = None):
        super().__init__(parent)
        self._ledger = ledger
        self._saved = False

        self.setWindowTitle("Edit Ledger" if ledger else "Add New Ledger")
        self.setMinimumWidth(520)
        self.setMinimumHeight(500)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {_DARK_BG}; }}"
            f"QLabel {{ color: {_TEXT}; font-family: 'Segoe UI'; font-size: 13px; }}"
            f"QLineEdit {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 8px; font-size: 13px;"
            f"}}"
            f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
            f"QScrollArea {{ border: none; background: transparent; }}"
        )

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        form = QFormLayout(container)
        form.setSpacing(12)
        form.setContentsMargins(24, 24, 24, 24)

        self._ledger_name_edit = QLineEdit()
        self._ledger_name_edit.setPlaceholderText("Enter ledger name")
        form.addRow("Ledger Name *:", self._ledger_name_edit)

        self._account_group_edit = QLineEdit()
        self._account_group_edit.setPlaceholderText("e.g. Sundry Creditors, Sundry Debtors")
        form.addRow("Under Group:", self._account_group_edit)

        # Structured account group selector (Phase 4A)
        self._structured_group_combo = _make_combo()
        self._structured_group_combo.addItem("(None)", None)
        for ag in AccountGroupDAO.get_all():
            label = ag["group_name"]
            if ag.get("statement_type"):
                label += f"  [{ag['statement_type']}]"
            self._structured_group_combo.addItem(label, ag["id"])
        self._structured_group_combo.setMaximumWidth(300)
        form.addRow("Account Group:", self._structured_group_combo)

        self._opening_balance_edit = QLineEdit()
        self._opening_balance_edit.setPlaceholderText("0.00")
        form.addRow("Opening Balance:", self._opening_balance_edit)

        self._opening_balance_type_combo = _make_combo()
        self._opening_balance_type_combo.addItems(["Debit", "Credit"])
        self._opening_balance_type_combo.setMaximumWidth(140)
        form.addRow("Balance Type:", self._opening_balance_type_combo)

        self._discount_edit = QLineEdit()
        self._discount_edit.setPlaceholderText("0.0")
        form.addRow("Discount (%):", self._discount_edit)

        self._credit_limit_edit = QLineEdit()
        self._credit_limit_edit.setPlaceholderText("0.00")
        form.addRow("Credit Limit:", self._credit_limit_edit)

        self._credit_period_edit = QLineEdit()
        self._credit_period_edit.setPlaceholderText("0")
        form.addRow("Credit Period (Days):", self._credit_period_edit)

        self._address_edit = QLineEdit()
        self._address_edit.setPlaceholderText("Enter address")
        form.addRow("Address:", self._address_edit)

        self._city_edit = QLineEdit()
        self._city_edit.setPlaceholderText("Enter city")
        form.addRow("City:", self._city_edit)

        self._state_edit = QLineEdit()
        self._state_edit.setPlaceholderText("Enter state")
        form.addRow("State:", self._state_edit)

        self._contact_person_edit = QLineEdit()
        self._contact_person_edit.setPlaceholderText("Enter contact person")
        form.addRow("Contact Person:", self._contact_person_edit)

        self._contact_no_edit = QLineEdit()
        self._contact_no_edit.setPlaceholderText("Enter contact number")
        form.addRow("Contact No:", self._contact_no_edit)

        self._tax_no_edit = QLineEdit()
        self._tax_no_edit.setPlaceholderText("Enter GST/Tax number")
        form.addRow("Tax No:", self._tax_no_edit)

        if ledger:
            self._ledger_name_edit.setText(ledger.get("ledger_name", ""))
            self._account_group_edit.setText(ledger.get("account_group", ""))
            # Set structured group combo
            group_id = ledger.get("account_group_id")
            if group_id is not None:
                idx = self._structured_group_combo.findData(group_id)
                if idx >= 0:
                    self._structured_group_combo.setCurrentIndex(idx)
            self._opening_balance_edit.setText(str(ledger.get("opening_balance", 0.0)))
            idx = self._opening_balance_type_combo.findText(ledger.get("opening_balance_type", "Debit"))
            if idx >= 0:
                self._opening_balance_type_combo.setCurrentIndex(idx)
            self._discount_edit.setText(str(ledger.get("discount", 0.0)))
            self._credit_limit_edit.setText(str(ledger.get("credit_limit", 0.0)))
            self._credit_period_edit.setText(str(ledger.get("credit_period", 0)))
            self._address_edit.setText(ledger.get("address", ""))
            self._city_edit.setText(ledger.get("city", ""))
            self._state_edit.setText(ledger.get("state", ""))
            self._contact_person_edit.setText(ledger.get("contact_person", ""))
            self._contact_no_edit.setText(ledger.get("contact_no", ""))
            self._tax_no_edit.setText(ledger.get("tax_no", ""))

        scroll.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(24, 12, 24, 24)
        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(90)
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        main_layout.addLayout(btn_layout)

    def _on_save(self):
        name = self._ledger_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Ledger Name is required.")
            return

        exclude_id = self._ledger["id"] if self._ledger else None
        if LedgerDAO.ledger_name_exists(name, exclude_id):
            QMessageBox.warning(
                self, "Validation", "A ledger with this name already exists."
            )
            return

        kwargs = {
            "ledger_name": name,
            "account_group": self._account_group_edit.text().strip(),
            "opening_balance": _safe_float(self._opening_balance_edit.text()),
            "opening_balance_type": self._opening_balance_type_combo.currentText(),
            "discount": _safe_float(self._discount_edit.text()),
            "credit_limit": _safe_float(self._credit_limit_edit.text()),
            "credit_period": _safe_int(self._credit_period_edit.text()),
            "address": self._address_edit.text().strip(),
            "city": self._city_edit.text().strip(),
            "state": self._state_edit.text().strip(),
            "contact_person": self._contact_person_edit.text().strip(),
            "contact_no": self._contact_no_edit.text().strip(),
            "tax_no": self._tax_no_edit.text().strip(),
            "account_group_id": self._structured_group_combo.currentData(),
        }

        if self._ledger:
            LedgerDAO.update_ledger(self._ledger["id"], **kwargs)
        else:
            LedgerDAO.insert_ledger(**kwargs)

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Account Ledger PAGE
# ======================================================================

class AccountLedgerPage(QWidget):
    """Account Ledger page with list and detail views."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._list_page = self._build_list_page()
        self._stack.addWidget(self._list_page)

        self._detail_page = self._build_detail_page()
        self._stack.addWidget(self._detail_page)

        self._refresh_list()

    # ------------------------------------------------------------------
    # List page
    # ------------------------------------------------------------------

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Account Ledger")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        new_btn = QPushButton("New")
        new_btn.setFixedWidth(90)
        new_btn.setStyleSheet(_BTN_SAVE)
        new_btn.clicked.connect(self._on_new)
        hl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(90)
        edit_btn.setStyleSheet(_BTN_SECONDARY)
        edit_btn.clicked.connect(self._on_edit)
        hl.addWidget(edit_btn)

        layout.addWidget(header)

        # Search bar
        search_bar = QWidget()
        search_bar.setFixedHeight(48)
        search_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        sl = QHBoxLayout(search_bar)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(8)

        sl.addWidget(QLabel("Search:"))
        self._search_edit = _make_edit("Ledger name...")
        self._search_edit.setMaximumWidth(300)
        self._search_edit.returnPressed.connect(self._on_search)
        sl.addWidget(self._search_edit)

        search_btn = QPushButton("Search")
        search_btn.setFixedWidth(70)
        search_btn.setStyleSheet(_BTN_SAVE)
        search_btn.clicked.connect(self._on_search)
        sl.addWidget(search_btn)

        all_btn = QPushButton("All")
        all_btn.setFixedWidth(50)
        all_btn.setStyleSheet(_BTN_SECONDARY)
        all_btn.clicked.connect(self._on_show_all)
        sl.addWidget(all_btn)

        sl.addStretch()
        layout.addWidget(search_bar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            "ID", "Ledger Name", "Account Group", "Opening Balance"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_double_click)

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
        layout.addWidget(self._table, 1)

        return page

    # ------------------------------------------------------------------
    # Detail page
    # ------------------------------------------------------------------

    def _build_detail_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        back_btn = QPushButton("< Back")
        back_btn.setFixedWidth(80)
        back_btn.setStyleSheet(_BTN_SECONDARY)
        back_btn.clicked.connect(self._on_back)
        hl.addWidget(back_btn)

        self._detail_title = QLabel("Ledger Detail")
        self._detail_title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(self._detail_title)
        hl.addStretch()

        layout.addWidget(header)

        # Balance summary
        summary_widget = QWidget()
        summary_widget.setFixedHeight(80)
        summary_widget.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        sg = QHBoxLayout(summary_widget)
        sg.setContentsMargins(16, 8, 16, 8)
        sg.setSpacing(24)

        sg.addWidget(self._bal_label("Account Group"))
        self._detail_group = self._bal_value("")
        sg.addWidget(self._detail_group)

        sg.addWidget(self._bal_label("Opening Balance"))
        self._detail_opening = self._bal_value("")
        sg.addWidget(self._detail_opening)

        sg.addWidget(self._bal_label("Total Debit"))
        self._detail_total_debit = self._bal_value("")
        sg.addWidget(self._detail_total_debit)

        sg.addWidget(self._bal_label("Total Credit"))
        self._detail_total_credit = self._bal_value("")
        sg.addWidget(self._detail_total_credit)

        sg.addWidget(self._bal_label("Closing Balance"))
        self._detail_closing = self._bal_value("")
        sg.addWidget(self._detail_closing)

        sg.addStretch()
        layout.addWidget(summary_widget)

        # Transaction table
        self._txn_table = QTableWidget()
        self._txn_table.setColumnCount(8)
        self._txn_table.setHorizontalHeaderLabels([
            "Date", "Time", "Voucher Type", "Voucher No",
            "Description", "Debit", "Credit", "Balance"
        ])
        self._txn_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._txn_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._txn_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._txn_table.verticalHeader().setVisible(False)
        self._txn_table.setShowGrid(True)
        self._txn_table.setAlternatingRowColors(False)

        hv = self._txn_table.horizontalHeader()
        hv.setStretchLastSection(True)
        for col in range(8):
            if col == 4:
                hv.setSectionResizeMode(col, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 12px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._txn_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        layout.addWidget(self._txn_table, 1)

        return page

    @staticmethod
    def _bal_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    @staticmethod
    def _bal_value(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 14px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        return lbl

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _refresh_list(self, ledgers: list[dict] | None = None):
        if ledgers is None:
            ledgers = LedgerDAO.get_all_ledgers()

        # Build id → group_name map for structured groups
        all_groups = AccountGroupDAO.get_all()
        gid_to_name = {g["id"]: g["group_name"] for g in all_groups}

        self._table.setRowCount(len(ledgers))
        for i, lg in enumerate(ledgers):
            self._table.setItem(i, 0, QTableWidgetItem(str(lg["id"])))
            self._table.setItem(i, 1, QTableWidgetItem(lg["ledger_name"]))

            # Prefer structured group name, fall back to legacy text
            group_id = lg.get("account_group_id")
            if group_id and group_id in gid_to_name:
                group_text = gid_to_name[group_id]
            else:
                group_text = lg.get("account_group", "")
            self._table.setItem(i, 2, QTableWidgetItem(group_text))

            ob = lg.get("opening_balance", 0.0)
            ob_type = lg.get("opening_balance_type", "Debit")
            ob_text = f"{ob:,.2f} ({ob_type})" if ob else ""
            self._table.setItem(i, 3, QTableWidgetItem(ob_text))

            self._table.item(i, 0).setData(Qt.UserRole, lg["id"])

    def _selected_id(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _on_search(self):
        text = self._search_edit.text().strip()
        if text:
            ledgers = LedgerDAO.search_ledgers(text)
        else:
            ledgers = LedgerDAO.get_all_ledgers()
        self._refresh_list(ledgers)

    def _on_show_all(self):
        self._search_edit.clear()
        self._refresh_list()

    def _on_new(self):
        dlg = _LedgerEntryDialog(self)
        dlg.exec()
        if dlg.was_saved:
            self._refresh_list()

    def _on_edit(self):
        lid = self._selected_id()
        if not lid:
            QMessageBox.information(self, "Edit Ledger", "Please select a ledger to edit.")
            return
        ledger = LedgerDAO.get_ledger_by_id(lid)
        if not ledger:
            QMessageBox.warning(self, "Edit Ledger", "Could not load ledger data.")
            return
        dlg = _LedgerEntryDialog(self, ledger=ledger)
        dlg.exec()
        if dlg.was_saved:
            self._refresh_list()

    def _on_double_click(self):
        lid = self._selected_id()
        if not lid:
            return
        self._show_detail(lid)

    def _show_detail(self, ledger_id: int):
        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        if not ledger:
            return

        self._detail_title.setText(ledger["ledger_name"])

        # Prefer structured group name for display
        group_id = ledger.get("account_group_id")
        if group_id:
            ag = AccountGroupDAO.get_by_id(group_id)
            if ag:
                self._detail_group.setText(ag["group_name"])
            else:
                self._detail_group.setText(ledger.get("account_group", "") or "-")
        else:
            self._detail_group.setText(ledger.get("account_group", "") or "-")

        ob = ledger.get("opening_balance", 0.0)
        ob_type = ledger.get("opening_balance_type", "Debit")
        self._detail_opening.setText(f"{ob:,.2f} ({ob_type})" if ob else "0.00")

        balance = LedgerDAO.get_balance(ledger_id)
        self._detail_total_debit.setText(f"{balance['total_debit']:,.2f}")
        self._detail_total_credit.setText(f"{balance['total_credit']:,.2f}")
        closing = balance["closing_balance"]
        closing_type = balance["closing_balance_type"]
        self._detail_closing.setText(f"{closing:,.2f} ({closing_type})")

        txns = LedgerDAO.get_transactions(ledger_id)
        running = 0.0
        self._txn_table.setRowCount(len(txns))
        for i, t in enumerate(txns):
            self._txn_table.setItem(i, 0, QTableWidgetItem(t.get("transaction_date", "")))
            self._txn_table.setItem(i, 1, QTableWidgetItem(t.get("transaction_time", "")))
            self._txn_table.setItem(i, 2, QTableWidgetItem(t.get("voucher_type", "")))
            self._txn_table.setItem(i, 3, QTableWidgetItem(t.get("voucher_no", "")))
            self._txn_table.setItem(i, 4, QTableWidgetItem(t.get("description", "")))

            debit = t.get("debit", 0.0)
            credit = t.get("credit", 0.0)
            running = running + debit - credit

            d_item = QTableWidgetItem(f"{debit:,.2f}" if debit else "")
            d_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._txn_table.setItem(i, 5, d_item)

            c_item = QTableWidgetItem(f"{credit:,.2f}" if credit else "")
            c_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._txn_table.setItem(i, 6, c_item)

            bal_item = QTableWidgetItem(f"{running:,.2f}")
            bal_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if running >= 0:
                bal_item.setForeground(Qt.green)
            else:
                bal_item.setForeground(Qt.red)
            self._txn_table.setItem(i, 7, bal_item)

        self._stack.setCurrentIndex(1)

    def _on_back(self):
        self._stack.setCurrentIndex(0)
