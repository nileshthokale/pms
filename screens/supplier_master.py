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

from database.supplier_dao import SupplierDAO

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


class _SupplierDialog(QDialog):
    """Modal dialog for adding or editing a supplier."""

    def __init__(self, parent: QWidget | None = None, *, supplier: dict | None = None):
        super().__init__(parent)
        self._supplier = supplier
        self._saved = False

        self.setWindowTitle("Edit Supplier" if supplier else "Add New Supplier")
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

        self._supplier_name_edit = QLineEdit()
        self._supplier_name_edit.setPlaceholderText("Enter supplier name")
        form.addRow("Supplier Name *:", self._supplier_name_edit)

        self._under_group_edit = QLineEdit()
        self._under_group_edit.setPlaceholderText("e.g. Sundry Creditors")
        form.addRow("Under Group:", self._under_group_edit)

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

        self._vat_tin_edit = QLineEdit()
        self._vat_tin_edit.setPlaceholderText("Enter VAT/TIN")
        form.addRow("VAT/TIN:", self._vat_tin_edit)

        self._sales_tax_no_edit = QLineEdit()
        self._sales_tax_no_edit.setPlaceholderText("Enter sales tax number")
        form.addRow("Sales Tax No:", self._sales_tax_no_edit)

        # Read-only ledger indicator
        self._ledger_label = QLabel("")
        self._ledger_label.setStyleSheet(
            f"color: {_ACCENT}; font-weight: bold; font-size: 13px;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        form.addRow("Ledger:", self._ledger_label)

        if supplier:
            self._supplier_name_edit.setText(supplier.get("supplier_name", ""))
            self._under_group_edit.setText(supplier.get("under_group", ""))
            self._opening_balance_edit.setText(str(supplier.get("opening_balance", 0.0)))
            self._discount_edit.setText(str(supplier.get("discount", 0.0)))
            self._credit_limit_edit.setText(str(supplier.get("credit_limit", 0.0)))
            self._credit_period_edit.setText(str(supplier.get("credit_period", 0)))
            self._address_edit.setText(supplier.get("address", ""))
            self._city_edit.setText(supplier.get("city", ""))
            self._state_edit.setText(supplier.get("state", ""))
            self._contact_person_edit.setText(supplier.get("contact_person", ""))
            self._contact_no_edit.setText(supplier.get("contact_no", ""))
            self._vat_tin_edit.setText(supplier.get("vat_tin", ""))
            self._sales_tax_no_edit.setText(supplier.get("sales_tax_no", ""))
            ledger_name = supplier.get("ledger_name", "")
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
        name = self._supplier_name_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Validation", "Supplier Name is required.")
            return

        exclude_id = self._supplier["id"] if self._supplier else None
        if SupplierDAO.name_exists(name, exclude_id):
            QMessageBox.warning(
                self, "Validation", "A supplier with this name already exists."
            )
            return

        kwargs = {
            "supplier_name": name,
            "sales_tax_no": self._sales_tax_no_edit.text().strip(),
            "vat_or_tin": "",
            "city": self._city_edit.text().strip(),
            "contact_person": self._contact_person_edit.text().strip(),
            "contact_no": self._contact_no_edit.text().strip(),
            "address": self._address_edit.text().strip(),
            "state": self._state_edit.text().strip(),
            "discount": self._safe_float(self._discount_edit.text()),
            "credit_limit": self._safe_float(self._credit_limit_edit.text()),
            "credit_period": self._safe_int(self._credit_period_edit.text()),
            "vat_tin": self._vat_tin_edit.text().strip(),
            "opening_balance": self._safe_float(self._opening_balance_edit.text()),
        }

        if self._supplier:
            SupplierDAO.update(self._supplier["id"], **kwargs)
        else:
            SupplierDAO.insert(**kwargs)

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


class SupplierMasterPage(QWidget):
    """Supplier Master screen with a table list, New and Edit buttons."""

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

        title = QLabel("Supplier Master")
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

        # -- Table --
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "ID", "Supplier Name", "Sales Tax No", "VAT/TIN", "City", "Contact Person", "Contact No", "Ledger"
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
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents)
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

    def _refresh(self):
        suppliers = SupplierDAO.get_all()
        self._table.setRowCount(len(suppliers))
        for row, s in enumerate(suppliers):
            self._table.setItem(row, 0, QTableWidgetItem(str(s["id"])))
            self._table.setItem(row, 1, QTableWidgetItem(s["supplier_name"]))
            self._table.setItem(row, 2, QTableWidgetItem(s.get("sales_tax_no", "")))
            self._table.setItem(row, 3, QTableWidgetItem(s.get("vat_tin", "")))
            self._table.setItem(row, 4, QTableWidgetItem(s.get("city", "")))
            self._table.setItem(row, 5, QTableWidgetItem(s.get("contact_person", "")))
            self._table.setItem(row, 6, QTableWidgetItem(s.get("contact_no", "")))
            self._table.setItem(row, 7, QTableWidgetItem(s.get("ledger_name", "")))

    def _selected_supplier(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return {
            "id": int(self._table.item(row, 0).text()),
            "supplier_name": self._table.item(row, 1).text(),
        }

    def _on_new(self):
        dlg = _SupplierDialog(self)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_edit(self):
        supplier = self._selected_supplier()
        if not supplier:
            QMessageBox.information(
                self, "Edit Supplier", "Please select a supplier to edit."
            )
            return
        full_supplier = SupplierDAO.get_by_id(supplier["id"])
        dlg = _SupplierDialog(self, supplier=full_supplier)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()
