from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.company_dao import CompanyDAO

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


class _CompanyDialog(QDialog):
    """Modal dialog for adding or editing a company."""

    def __init__(self, parent: QWidget | None = None, *, company: dict | None = None):
        super().__init__(parent)
        self._company = company
        self._saved = False

        self.setWindowTitle("Edit Company" if company else "Add New Company")
        self.setMinimumWidth(420)
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
        )

        form = QFormLayout(self)
        form.setSpacing(14)
        form.setContentsMargins(24, 24, 24, 24)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Enter company name")
        form.addRow("Company Name *:", self._name_edit)

        self._short_edit = QLineEdit()
        self._short_edit.setPlaceholderText("Enter short name")
        form.addRow("Short Name:", self._short_edit)

        if company:
            self._name_edit.setText(company["company_name"])
            self._short_edit.setText(company["short_name"])

        btn_layout = QHBoxLayout()
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

        form.addRow("", btn_layout)

    def _on_save(self):
        name = self._name_edit.text().strip()
        short = self._short_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Validation", "Company Name is required.")
            return

        exclude_id = self._company["id"] if self._company else None
        if CompanyDAO.name_exists(name, exclude_id):
            QMessageBox.warning(
                self, "Validation", "A company with this name already exists."
            )
            return

        if self._company:
            CompanyDAO.update(self._company["id"], name, short)
        else:
            CompanyDAO.insert(name, short)

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


class CompanyMasterPage(QWidget):
    """Company Master screen with a table list, New and Edit buttons."""

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

        title = QLabel("Company Master")
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
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["ID", "Company Name", "Short Name"])
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
        companies = CompanyDAO.get_all()
        self._table.setRowCount(len(companies))
        for row, co in enumerate(companies):
            self._table.setItem(row, 0, QTableWidgetItem(str(co["id"])))
            self._table.setItem(row, 1, QTableWidgetItem(co["company_name"]))
            self._table.setItem(row, 2, QTableWidgetItem(co["short_name"]))

    def _selected_company(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return {
            "id": int(self._table.item(row, 0).text()),
            "company_name": self._table.item(row, 1).text(),
            "short_name": self._table.item(row, 2).text(),
        }

    def _on_new(self):
        dlg = _CompanyDialog(self)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_edit(self):
        company = self._selected_company()
        if not company:
            QMessageBox.information(
                self, "Edit Company", "Please select a company to edit."
            )
            return
        dlg = _CompanyDialog(self, company=company)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()
