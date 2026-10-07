from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.customer_dao import CustomerDAO

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


class _CustomerDialog(QDialog):
    """Modal dialog for adding or editing a customer."""

    def __init__(self, parent: QWidget | None = None, *, customer: dict | None = None):
        super().__init__(parent)
        self._customer = customer
        self._saved = False

        self.setWindowTitle("Edit Customer" if customer else "Add New Customer")
        self.setMinimumWidth(520)
        self.setMinimumHeight(450)
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

        self._customer_name_edit = QLineEdit()
        self._customer_name_edit.setPlaceholderText("Enter customer name")
        form.addRow("Customer Name *:", self._customer_name_edit)

        self._opening_balance_edit = QLineEdit()
        self._opening_balance_edit.setPlaceholderText("0.00")
        form.addRow("Opening Balance:", self._opening_balance_edit)

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

        # Read-only ledger indicator
        self._ledger_label = QLabel("")
        self._ledger_label.setStyleSheet(
            f"color: {_ACCENT}; font-weight: bold; font-size: 13px;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        form.addRow("Ledger:", self._ledger_label)

        if customer:
            self._customer_name_edit.setText(customer.get("customer_name", ""))
            self._opening_balance_edit.setText(str(customer.get("opening_balance", 0.0)))
            self._discount_edit.setText(str(customer.get("discount", 0.0)))
            self._credit_limit_edit.setText(str(customer.get("credit_limit", 0.0)))
            self._credit_period_edit.setText(str(customer.get("credit_period", 0)))
            self._address_edit.setText(customer.get("address", ""))
            self._city_edit.setText(customer.get("city", ""))
            self._state_edit.setText(customer.get("state", ""))
            self._contact_person_edit.setText(customer.get("contact_person", ""))
            self._contact_no_edit.setText(customer.get("contact_no", ""))
            ledger_name = customer.get("ledger_name", "")
            if ledger_name:
                self._ledger_label.setText(ledger_name)
            else:
                self._ledger_label.setText("(auto-created on save)")
        else:
            self._ledger_label.setText("(auto-created on save)")

        scroll.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(24, 12, 24, 24)
        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(90)
        save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_ACCENT}; color: white;"
            f"  border: none; border-radius: 2px; padding: 4px 8px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
        )
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
            f"  border: none; border-radius: 2px; padding: 8px; }}"
            f"QPushButton:hover {{ background-color: #7d93a8; }}"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        main_layout.addLayout(btn_layout)

    def _safe_float(self, text: str, default: float = 0.0) -> float:
        try:
            return float(text.strip()) if text.strip() else default
        except ValueError:
            return default

    def _safe_int(self, text: str, default: int = 0) -> int:
        try:
            return int(float(text.strip())) if text.strip() else default
        except ValueError:
            return default

    def _on_save(self):
        name = self._customer_name_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Validation", "Customer Name is required.")
            return

        exclude_id = self._customer["id"] if self._customer else None
        if CustomerDAO.name_exists(name, exclude_id):
            QMessageBox.warning(
                self, "Validation", "A customer with this name already exists."
            )
            return

        kwargs = {
            "customer_name": name,
            "city": self._city_edit.text().strip(),
            "contact_person": self._contact_person_edit.text().strip(),
            "contact_no": self._contact_no_edit.text().strip(),
            "address": self._address_edit.text().strip(),
            "state": self._state_edit.text().strip(),
            "discount": self._safe_float(self._discount_edit.text()),
            "credit_limit": self._safe_float(self._credit_limit_edit.text()),
            "credit_period": self._safe_int(self._credit_period_edit.text()),
            "opening_balance": self._safe_float(self._opening_balance_edit.text()),
        }

        if self._customer:
            CustomerDAO.update(self._customer["id"], **kwargs)
        else:
            CustomerDAO.insert(**kwargs)

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


class CustomerMasterPage(QWidget):
    """Customer Master screen with search bar, table list, New and Edit buttons."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Header bar --
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Customer Master")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        header_layout.addWidget(title)
        header_layout.addStretch()

        new_btn = QPushButton("New")
        new_btn.setFixedWidth(90)
        new_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_ACCENT}; color: white;"
            f"  border: none; border-radius: 2px; padding: 8px 16px;"
            f"  font-weight: bold; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
        )
        new_btn.clicked.connect(self._on_new)
        header_layout.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(90)
        edit_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
            f"  border: none; border-radius: 2px; padding: 8px 16px;"
            f"  font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: #7d93a8; }}"
        )
        edit_btn.clicked.connect(self._on_edit)
        header_layout.addWidget(edit_btn)

        root.addWidget(header)

        # -- Search bar --
        search_bar = QWidget()
        search_bar.setFixedHeight(48)
        search_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        search_layout = QHBoxLayout(search_bar)
        search_layout.setContentsMargins(16, 0, 16, 0)

        search_label = QLabel("Customer Name:")
        search_label.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        search_layout.addWidget(search_label)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Enter customer name to search")
        self._search_edit.setFixedWidth(300)
        self._search_edit.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 6px 10px; font-size: 13px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
            f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
        )
        self._search_edit.returnPressed.connect(self._on_search)
        search_layout.addWidget(self._search_edit)

        search_btn = QPushButton("Search")
        search_btn.setFixedWidth(90)
        search_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_ACCENT}; color: white;"
            f"  border: none; border-radius: 2px; padding: 6px 16px;"
            f"  font-weight: bold; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
        )
        search_btn.clicked.connect(self._on_search)
        search_layout.addWidget(search_btn)

        search_layout.addStretch()

        root.addWidget(search_bar)

        # -- Table --
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "CustomerName", "City", "ContactPerson", "ContactNo", "Ledger"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)

        header_view = self._table.horizontalHeader()
        header_view.setStretchLastSection(True)
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 8px; font-weight: bold; font-size: 12px;"
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
            f"QTableWidget::item {{ padding: 2px 6px; }}"
        )

        root.addWidget(self._table, 1)
        self._refresh()

    def _refresh(self, customers: list[dict] | None = None):
        if customers is None:
            customers = CustomerDAO.get_all()
        self._table.setRowCount(len(customers))
        for row, c in enumerate(customers):
            self._table.setItem(row, 0, QTableWidgetItem(c["customer_name"]))
            self._table.setItem(row, 1, QTableWidgetItem(c.get("city", "")))
            self._table.setItem(row, 2, QTableWidgetItem(c.get("contact_person", "")))
            self._table.setItem(row, 3, QTableWidgetItem(c.get("contact_no", "")))
            self._table.setItem(row, 4, QTableWidgetItem(c.get("ledger_name", "")))

    def _selected_customer(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return {
            "customer_name": self._table.item(row, 0).text(),
        }

    def _on_new(self):
        dlg = _CustomerDialog(self)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_edit(self):
        customer = self._selected_customer()
        if not customer:
            QMessageBox.information(
                self, "Edit Customer", "Please select a customer to edit."
            )
            return
        # Find the full customer record by name
        all_customers = CustomerDAO.get_all()
        full_customer = None
        for c in all_customers:
            if c["customer_name"] == customer["customer_name"]:
                full_customer = c
                break
        if not full_customer:
            QMessageBox.warning(
                self, "Edit Customer", "Could not load customer data."
            )
            return
        dlg = _CustomerDialog(self, customer=full_customer)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_search(self):
        search_text = self._search_edit.text().strip()
        if not search_text:
            self._refresh()
        else:
            customers = CustomerDAO.search(search_text)
            self._refresh(customers)
