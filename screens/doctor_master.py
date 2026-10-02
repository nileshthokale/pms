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

from database.doctor_dao import DoctorDAO

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


class _DoctorDialog(QDialog):
    """Modal dialog for adding or editing a doctor."""

    def __init__(self, parent: QWidget | None = None, *, doctor: dict | None = None):
        super().__init__(parent)
        self._doctor = doctor
        self._saved = False

        self.setWindowTitle("Edit Doctor" if doctor else "Add New Doctor")
        self.setMinimumWidth(520)
        self.setMinimumHeight(350)
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

        self._doctor_name_edit = QLineEdit()
        self._doctor_name_edit.setPlaceholderText("Enter doctor name")
        form.addRow("Doctor Name *:", self._doctor_name_edit)

        self._city_edit = QLineEdit()
        self._city_edit.setPlaceholderText("Enter city")
        form.addRow("City:", self._city_edit)

        self._specialty_edit = QLineEdit()
        self._specialty_edit.setPlaceholderText("Enter specialty")
        form.addRow("Specialty:", self._specialty_edit)

        self._phone_no_edit = QLineEdit()
        self._phone_no_edit.setPlaceholderText("Enter phone number")
        form.addRow("Phone No.:", self._phone_no_edit)

        if doctor:
            self._doctor_name_edit.setText(doctor.get("doctor_name", ""))
            self._city_edit.setText(doctor.get("city", ""))
            self._specialty_edit.setText(doctor.get("specialty", ""))
            self._phone_no_edit.setText(doctor.get("phone_no", ""))

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

    def _on_save(self):
        name = self._doctor_name_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Validation", "Doctor Name is required.")
            return

        exclude_id = self._doctor["id"] if self._doctor else None
        if DoctorDAO.name_exists(name, exclude_id):
            QMessageBox.warning(
                self, "Validation", "A doctor with this name already exists."
            )
            return

        kwargs = {
            "doctor_name": name,
            "city": self._city_edit.text().strip(),
            "specialty": self._specialty_edit.text().strip(),
            "phone_no": self._phone_no_edit.text().strip(),
        }

        if self._doctor:
            DoctorDAO.update(self._doctor["id"], **kwargs)
        else:
            DoctorDAO.insert(**kwargs)

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


class DoctorMasterPage(QWidget):
    """Doctor Master screen with search bar, table list, New and Edit buttons."""

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

        title = QLabel("Doctor Master")
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

        search_label = QLabel("Doctor Name:")
        search_label.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        search_layout.addWidget(search_label)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Enter doctor name to search")
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
            "ID", "Doctor Name", "City", "Specialty", "Phone No."
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

    def _refresh(self, doctors: list[dict] | None = None):
        if doctors is None:
            doctors = DoctorDAO.get_all()
        self._table.setRowCount(len(doctors))
        for row, d in enumerate(doctors):
            self._table.setItem(row, 0, QTableWidgetItem(str(d["id"])))
            self._table.setItem(row, 1, QTableWidgetItem(d["doctor_name"]))
            self._table.setItem(row, 2, QTableWidgetItem(d.get("city", "")))
            self._table.setItem(row, 3, QTableWidgetItem(d.get("specialty", "")))
            self._table.setItem(row, 4, QTableWidgetItem(d.get("phone_no", "")))

    def _selected_doctor(self) -> dict | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return {
            "id": int(self._table.item(row, 0).text()),
            "doctor_name": self._table.item(row, 1).text(),
        }

    def _on_new(self):
        dlg = _DoctorDialog(self)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_edit(self):
        doctor = self._selected_doctor()
        if not doctor:
            QMessageBox.information(
                self, "Edit Doctor", "Please select a doctor to edit."
            )
            return
        full_doctor = DoctorDAO.get_by_id(doctor["id"])
        if not full_doctor:
            QMessageBox.warning(
                self, "Edit Doctor", "Could not load doctor data."
            )
            return
        dlg = _DoctorDialog(self, doctor=full_doctor)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_search(self):
        search_text = self._search_edit.text().strip()
        if not search_text:
            self._refresh()
        else:
            doctors = DoctorDAO.search(search_text)
            self._refresh(doctors)
