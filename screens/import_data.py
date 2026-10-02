from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from database import import_service
from database import auth
from ui import components as ui


class ImportDataPage(QWidget):
    """Guided master-data import page; preview and validation never write rows."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        colors = ui.palette()
        self.setStyleSheet(f"background-color: {colors['bg']}; color: {colors['text']};")
        self._data = None
        self._preview = None
        self._mapping = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(ui.PageHeader("Master / Import Data"))

        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 12, 10)
        root.addLayout(body)

        form = QFormLayout()
        self._master = QComboBox()
        self._master.addItems([name.title() for name in import_service.MASTER_TYPES])
        self._master.currentTextChanged.connect(self._reset_mapping)
        form.addRow("1. Master Type", self._master)

        file_row = QHBoxLayout()
        self._file = QLabel("No file selected")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        inspect = QPushButton("Refresh / Inspect")
        inspect.clicked.connect(self._inspect)
        file_row.addWidget(self._file, 1); file_row.addWidget(browse); file_row.addWidget(inspect)
        form.addRow("2. CSV / XLSX File", file_row)

        self._sheet = QComboBox()
        self._sheet.setEnabled(False)
        self._sheet.currentTextChanged.connect(self._inspect)
        form.addRow("3. Excel Sheet", self._sheet)
        body.addLayout(form)

        mapping_row = QHBoxLayout()
        self._mapping_table = QTableWidget(0, 3)
        self._mapping_table.setHorizontalHeaderLabels(["Source column", "Target field", "Status"])
        ui.style_data_table(self._mapping_table, stretch_columns=(0, 1))
        mapping_row.addWidget(self._mapping_table, 1)
        map_buttons = QVBoxLayout()
        auto_map = ui.ActionButton("Auto Map", "secondary")
        auto_map.clicked.connect(self._auto_map)
        map_buttons.addWidget(auto_map)
        mapping_row.addLayout(map_buttons)
        body.addLayout(mapping_row, 1)

        self._summary = QLabel("Select a file to begin.")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(ui.label_style(size=9))
        body.addWidget(self._summary)
        self._preview_table = QTableWidget(0, 0)
        ui.style_data_table(self._preview_table)
        body.addWidget(self._preview_table, 1)

        actions = ui.FilterBar()
        validate = ui.ActionButton("Validate", "primary")
        validate.clicked.connect(self._validate)
        template = ui.ActionButton("Generate Template", "secondary")
        template.clicked.connect(self._template)
        history = ui.ActionButton("Recent History", "secondary")
        history.clicked.connect(self._history)
        self._duplicate_mode = ui.style_combo(QComboBox())
        self._duplicate_mode.addItems(["Skip duplicate", "Update existing", "Cancel import"])
        import_button = ui.ActionButton("Import", "success")
        import_button.clicked.connect(self._import)
        actions.add_widget(validate); actions.add_widget(template); actions.add_widget(history); actions.add_field("Duplicates", self._duplicate_mode)
        actions.add_stretch(); actions.add_widget(import_button)
        body.addWidget(actions)

    def _master_type(self):
        return self._master.currentText().casefold()

    def _reset_mapping(self):
        self._data = None; self._preview = None; self._mapping_table.setRowCount(0)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select import file", "", "CSV / Excel (*.csv *.xlsx)")
        if path:
            self._file.setText(path)
            self._sheet.clear(); self._inspect()

    def _inspect(self):
        path = self._file.text()
        if not Path(path).is_file():
            return
        try:
            selected_sheet = self._sheet.currentText() or None
            data = import_service.inspect_file(path, selected_sheet)
            if "sheets" in data:
                self._sheet.blockSignals(True); self._sheet.clear(); self._sheet.addItems(data["sheets"]); self._sheet.setEnabled(True); self._sheet.blockSignals(False)
                if data["sheets"]:
                    data = import_service.inspect_file(path, data["sheets"][0])
            self._data = data
            self._mapping = import_service.detect_columns(data["headers"], self._master_type())
            self._show_mapping(); self._summary.setText(f"Detected {len(data['headers'])} columns and {len(data['rows'])} data rows.")
        except Exception as exc:
            QMessageBox.warning(self, "Inspect failed", str(exc))

    def _show_mapping(self):
        self._mapping_table.setRowCount(0)
        master = self._master_type()
        fields = list(import_service.FIELD_DEFINITIONS[master])
        for source in (self._data or {}).get("headers", []):
            target = self._mapping.get(source, "(unmapped)")
            row = self._mapping_table.rowCount(); self._mapping_table.insertRow(row)
            self._mapping_table.setItem(row, 0, QTableWidgetItem(source))
            combo = QComboBox(); combo.addItem("(unmapped)")
            combo.addItems(fields); combo.setCurrentText(target)
            combo.currentTextChanged.connect(self._refresh_mapping_status)
            self._mapping_table.setCellWidget(row, 1, combo)
            self._mapping_table.setItem(row, 2, QTableWidgetItem("Mapped" if target != "(unmapped)" else "Unmapped"))

        mapped_targets = set(self._mapping.values())
        for field, definition in import_service.FIELD_DEFINITIONS[master].items():
            if definition.get("required") and field not in mapped_targets:
                row = self._mapping_table.rowCount(); self._mapping_table.insertRow(row)
                self._mapping_table.setItem(row, 0, QTableWidgetItem("(no source column)"))
                self._mapping_table.setItem(row, 1, QTableWidgetItem(field))
                self._mapping_table.setItem(row, 2, QTableWidgetItem("Required target missing"))

    def _refresh_mapping_status(self):
        for row in range(self._mapping_table.rowCount()):
            combo = self._mapping_table.cellWidget(row, 1)
            if combo is None:
                continue
            status = "Mapped" if combo.currentText() != "(unmapped)" else "Unmapped"
            self._mapping_table.setItem(row, 2, QTableWidgetItem(status))

    def _auto_map(self):
        if self._data:
            self._mapping = import_service.detect_columns(self._data["headers"], self._master_type()); self._show_mapping()

    def _current_mapping(self):
        mapping = {}
        for row in range(self._mapping_table.rowCount()):
            source = self._mapping_table.item(row, 0).text()
            combo = self._mapping_table.cellWidget(row, 1)
            if combo is None:
                continue
            target = combo.currentText()
            if target != "(unmapped)": mapping[source] = target
        return mapping

    def _validate(self):
        if not self._data:
            QMessageBox.information(self, "Import", "Select and inspect a file first."); return
        self._mapping = self._current_mapping()
        self._preview = import_service.preview_import(self._master_type(), self._data, self._mapping)
        self._preview["filename"] = self._file.text()
        self._summary.setText(f"Total: {self._preview['total_rows']} | Valid: {self._preview['valid_rows']} | Invalid: {self._preview['invalid_rows']} | Duplicates: {len(self._preview['duplicate_rows'])} | Unmapped: {len(self._preview['unmapped_columns'])}")
        issues = self._preview["issues"]
        self._preview_table.setColumnCount(5); self._preview_table.setHorizontalHeaderLabels(["Row", "Field", "Value", "Message", "Severity"]); self._preview_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            for column, key in enumerate(("row", "field", "value", "message", "severity")):
                self._preview_table.setItem(row, column, QTableWidgetItem(str(issue[key])))

    def _import(self):
        try:
            auth.session.require(auth.PERM_IMPORT_DATA)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        if not self._preview:
            self._validate()
        if not self._preview or self._preview.get("invalid_rows"):
            return
        if QMessageBox.question(self, "Confirm import", "Import the validated master data now?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        mode = ("skip", "update", "cancel")[self._duplicate_mode.currentIndex()]
        try:
            result = import_service.import_rows(self._master_type(), self._preview, duplicate_mode=mode, confirm=True)
            QMessageBox.information(self, "Import complete", import_service.generate_import_report(result))
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))

    def _template(self):
        fmt = "xlsx" if import_service.openpyxl is not None else "csv"
        suffix = ".xlsx" if fmt == "xlsx" else ".csv"
        path, _ = QFileDialog.getSaveFileName(self, "Save template", f"{self._master_type()}_template{suffix}", f"{fmt.upper()} (*{suffix})")
        if path:
            try:
                Path(path).write_bytes(import_service.get_import_template(self._master_type(), fmt))
            except Exception as exc:
                QMessageBox.warning(self, "Template failed", str(exc))
    
    def _history(self):
        history = import_service.get_import_history()
        if not history:
            QMessageBox.information(self, "Import history", "No imports have been recorded.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Recent Import History")
        dialog.resize(980, 420)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(history), 8)
        table.setHorizontalHeaderLabels([
            "Date/Time", "Master Type", "Source Filename", "Total Rows",
            "Inserted", "Updated", "Skipped", "Failed",
        ])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setWordWrap(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for row_index, record in enumerate(history):
            values = (
                record["timestamp"], record["master_type"].title(), record["filename"],
                record["total_rows"], record["inserted"], record["updated"],
                record["skipped"], record["failed"],
            )
            for column, value in enumerate(values):
                table.setItem(row_index, column, QTableWidgetItem(str(value)))
        layout.addWidget(table)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignRight)
        dialog.exec()
