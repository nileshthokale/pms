from __future__ import annotations

from PySide6.QtWidgets import QDateEdit, QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import QDate

from database import auth, financial_year
from ui import components as ui


class _NewFinancialYearDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("New Financial Year")
        form = QFormLayout(self)
        self.name = QLabel("Enter dates to name the year")
        self.start = QDateEdit(QDate(2027, 4, 1)); self.start.setCalendarPopup(True)
        self.end = QDateEdit(QDate(2028, 3, 31)); self.end.setCalendarPopup(True)
        form.addRow("Year", self.name); form.addRow("Start Date", self.start); form.addRow("End Date", self.end)
        buttons = QHBoxLayout()
        create = ui.ActionButton("Create", "primary"); create.clicked.connect(self.accept)
        cancel = ui.ActionButton("Cancel", "secondary"); cancel.clicked.connect(self.reject)
        buttons.addWidget(create); buttons.addWidget(cancel); form.addRow(buttons)

    def values(self):
        start = self.start.date().toString("yyyy-MM-dd"); end = self.end.date().toString("yyyy-MM-dd")
        return f"{start[:4]}-{end[:4]}", start, end


class FinancialYearPage(QWidget):
    """Financial-year viewer; creation and switching are ADMIN-only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._table = QTableWidget(0, 4); self._table.setHorizontalHeaderLabels(["Financial Year", "Start Date", "End Date", "Active"])
        self._new = ui.ActionButton("New Financial Year", "primary"); self._new.clicked.connect(self._create)
        self._activate = ui.ActionButton("Set Active", "secondary"); self._activate.clicked.connect(self._activate_selected)
        refresh = ui.ActionButton("Refresh", "secondary"); refresh.clicked.connect(self._refresh)
        actions = ui.FilterBar()
        actions.add_widget(self._new); actions.add_widget(self._activate); actions.add_widget(refresh); actions.add_stretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        layout.addWidget(ui.PageHeader("Master / Financial Year"))
        layout.addWidget(actions)
        ui.style_data_table(self._table, stretch_columns=(0,))
        layout.addWidget(self._table, 1)
        self._refresh()

    def _is_admin(self):
        if auth.session.has_permission(auth.PERM_FINANCIAL_YEAR_MANAGEMENT): return True
        QMessageBox.warning(self, "Permission denied", "Only ADMIN can change the active financial year."); return False

    def _refresh(self):
        rows = financial_year.get_financial_years(); self._table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, value in enumerate((row["name"], row["start_date"], row["end_date"], "Yes" if row["is_active"] else "No")):
                self._table.setItem(index, column, QTableWidgetItem(str(value)))
            self._table.item(index, 0).setData(32, row["id"])

    def _selected_id(self):
        rows = self._table.selectionModel().selectedRows(); return rows[0].data(32) if rows else None

    def _create(self):
        if not self._is_admin(): return
        dialog = _NewFinancialYearDialog(self)
        if dialog.exec() != QDialog.Accepted: return
        name, start, end = dialog.values()
        if QMessageBox.question(self, "Confirm", f"Create financial year {name}?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        try: financial_year.create_financial_year(name, start, end, actor=auth.session.user); self._refresh()
        except (financial_year.FinancialYearError, auth.AuthenticationError) as exc: QMessageBox.warning(self, "Financial Year", str(exc))

    def _activate_selected(self):
        if not self._is_admin(): return
        year_id = self._selected_id()
        if year_id is None: return
        if QMessageBox.question(self, "Confirm", "Switch the active financial year?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        try: financial_year.set_active_financial_year(year_id, actor=auth.session.user); self._refresh()
        except (financial_year.FinancialYearError, auth.AuthenticationError) as exc: QMessageBox.warning(self, "Financial Year", str(exc))
