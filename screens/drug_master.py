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

from database.drug_dao import DrugDAO

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


class _DrugDialog(QDialog):
    """Modal dialog for adding or editing a drug."""

    def __init__(self, parent: QWidget | None = None, *, drug: dict | None = None):
        super().__init__(parent)
        self._drug = drug
        self._saved = False

        self.setWindowTitle("Edit Drug" if drug else "New Drug")
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
        self._name_edit.setPlaceholderText("Enter drug name")
        form.addRow("Drug Name *:", self._name_edit)

        if drug:
            self._name_edit.setText(drug["drug_name"])

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

        if not name:
            QMessageBox.warning(self, "Validation", "Drug Name is required.")
            return

        exclude_id = self._drug["id"] if self._drug else None
        if DrugDAO.name_exists(name, exclude_id):
            QMessageBox.warning(
                self, "Validation", "A drug with this name already exists."
            )
            return

        if self._drug:
            DrugDAO.update(self._drug["id"], name)
        else:
            DrugDAO.insert(name)

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


class DrugMasterPage(QWidget):
    """Drug Master screen with a table list, New and Edit buttons."""

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

        title = QLabel("Drug Master")
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
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["ID", "Drug Name"])
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
        header_view.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 8px; font-weight: bold; font-size: 9pt;"
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
        drugs = DrugDAO.get_all()
        self._table.setRowCount(len(drugs))
        for row, d in enumerate(drugs):
            self._table.setItem(row, 0, QTableWidgetItem(str(d["id"])))
            self._table.setItem(row, 1, QTableWidgetItem(d["drug_name"]))

    def _selected_drug(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return {
            "id": int(self._table.item(row, 0).text()),
            "drug_name": self._table.item(row, 1).text(),
        }

    def _on_new(self):
        dlg = _DrugDialog(self)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_edit(self):
        drug = self._selected_drug()
        if not drug:
            QMessageBox.information(
                self, "Edit Drug", "Please select a drug to edit."
            )
            return
        dlg = _DrugDialog(self, drug=drug)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()
