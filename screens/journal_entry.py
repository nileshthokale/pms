from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.ledger_dao import LedgerDAO
from database.journal_dao import JournalDAO
from database import financial_year

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

_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 5px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QDateEdit:focus {{ border: 1px solid {_ACCENT}; }}"
    f"QDateEdit::drop-down {{ border: none; width: 24px; }}"
    f"QDateEdit::down-arrow {{ image: none; border: none; }}"
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

_BTN_GREEN_SM = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 6px 14px;"
    f"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
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


def _make_date() -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setStyleSheet(_DATE_STYLE)
    return d


# ======================================================================
# Journal Entry Dialog
# ======================================================================

class _JournalEntryDialog(QDialog):
    """Modal dialog for creating / editing a journal entry."""

    def __init__(self, parent: QWidget | None = None, *, entry: dict | None = None,
                 items: list[dict] | None = None):
        super().__init__(parent)
        self._entry = entry
        self._saved = False
        self._ledgers = LedgerDAO.get_all_ledgers()

        self.setWindowTitle("Edit Journal Entry" if entry else "New Journal Entry")
        self.setMinimumWidth(850)
        self.setMinimumHeight(520)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {_DARK_BG}; }}"
            f"QLabel {{ {_LABEL_STYLE} }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self._build_header(root)
        self._build_lines_table(root)
        self._build_totals(root)

        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        save_btn = QPushButton("Save Entry")
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        root.addLayout(btn_bar)

        self._set_voucher_no()
        self._set_current_datetime()
        self._add_blank_line()
        self._add_blank_line()

        if entry and items:
            self._populate(entry, items)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self, root_layout: QVBoxLayout):
        grp = QGroupBox("Journal Entry Header")
        grp.setStyleSheet(_GROUP_BOX)
        grid = QGridLayout(grp)
        grid.setSpacing(8)
        grid.setContentsMargins(12, 20, 12, 10)

        row = 0
        grid.addWidget(self._lbl("Voucher No"), row, 0)
        self.voucher_no_edit = _make_edit()
        self.voucher_no_edit.setReadOnly(True)
        grid.addWidget(self.voucher_no_edit, row, 1)

        grid.addWidget(self._lbl("Date *"), row, 2)
        self.entry_date = _make_date()
        self.entry_date.setMaximumWidth(140)
        grid.addWidget(self.entry_date, row, 3)

        row = 1
        grid.addWidget(self._lbl("Time"), row, 0)
        self.entry_time_edit = _make_edit()
        self.entry_time_edit.setMaximumWidth(80)
        grid.addWidget(self.entry_time_edit, row, 1)

        grid.addWidget(self._lbl("Narration"), row, 2)
        self.narration_edit = _make_edit()
        grid.addWidget(self.narration_edit, row, 3)

        root_layout.addWidget(grp)

    def _build_lines_table(self, root_layout: QVBoxLayout):
        grp = QGroupBox("Journal Lines")
        grp.setStyleSheet(_GROUP_BOX)
        layout = QVBoxLayout(grp)
        layout.setContentsMargins(12, 20, 12, 10)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add Line")
        add_btn.setStyleSheet(_BTN_GREEN_SM)
        add_btn.clicked.connect(self._add_blank_line)
        btn_row.addWidget(add_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._lines_table = QTableWidget()
        self._lines_table.setColumnCount(5)
        self._lines_table.setHorizontalHeaderLabels([
            "Sr No.", "Ledger *", "Description", "Debit", "Credit"
        ])
        self._lines_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._lines_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._lines_table.verticalHeader().setVisible(False)
        self._lines_table.setShowGrid(True)
        self._lines_table.setAlternatingRowColors(False)

        hv = self._lines_table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)
        hv.setSectionResizeMode(2, QHeaderView.Stretch)
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 12px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._lines_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        layout.addWidget(self._lines_table, 1)

        root_layout.addWidget(grp, 1)

    def _build_totals(self, root_layout: QVBoxLayout):
        totals = QWidget()
        totals.setFixedHeight(36)
        tl = QHBoxLayout(totals)
        tl.setContentsMargins(12, 0, 12, 0)
        tl.setSpacing(20)

        tl.addWidget(self._lbl("Total Debit:"))
        self._total_debit_lbl = QLabel("0.00")
        self._total_debit_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        tl.addWidget(self._total_debit_lbl)

        tl.addWidget(self._lbl("Total Credit:"))
        self._total_credit_lbl = QLabel("0.00")
        self._total_credit_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        tl.addWidget(self._total_credit_lbl)

        tl.addWidget(self._lbl("Difference:"))
        self._difference_lbl = QLabel("0.00")
        self._difference_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        tl.addWidget(self._difference_lbl)

        tl.addStretch()
        root_layout.addWidget(totals)

    def _update_totals(self):
        total_debit = 0.0
        total_credit = 0.0
        for row in range(self._lines_table.rowCount()):
            debit_item = self._lines_table.item(row, 3)
            credit_item = self._lines_table.item(row, 4)
            if debit_item and debit_item.text().strip():
                total_debit += _safe_float(debit_item.text())
            if credit_item and credit_item.text().strip():
                total_credit += _safe_float(credit_item.text())

        self._total_debit_lbl.setText(f"{total_debit:,.2f}")
        self._total_credit_lbl.setText(f"{total_credit:,.2f}")

        diff = abs(total_debit - total_credit)
        self._difference_lbl.setText(f"{diff:,.2f}")

        if diff < 0.001 and total_debit > 0:
            self._difference_lbl.setStyleSheet(
                f"color: {_ACCENT}; font-size: 13px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )
        else:
            self._difference_lbl.setStyleSheet(
                f"color: {_ERROR}; font-size: 13px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )

    def _add_blank_line(self):
        row = self._lines_table.rowCount()
        self._lines_table.insertRow(row)

        sr = QTableWidgetItem(str(row + 1))
        sr.setFlags(sr.flags() & ~Qt.ItemIsEditable)
        sr.setTextAlignment(Qt.AlignCenter)
        self._lines_table.setItem(row, 0, sr)

        combo = _make_combo()
        combo.addItem("-- Select Ledger --", None)
        for lg in self._ledgers:
            combo.addItem(lg["ledger_name"], lg["id"])
        combo.currentIndexChanged.connect(lambda: self._update_totals())
        self._lines_table.setCellWidget(row, 1, combo)

        desc = QTableWidgetItem("")
        self._lines_table.setItem(row, 2, desc)

        debit_edit = _make_edit("0.00", 100)
        debit_edit.setAlignment(Qt.AlignRight)
        self._lines_table.setCellWidget(row, 3, debit_edit)

        credit_edit = _make_edit("0.00", 100)
        credit_edit.setAlignment(Qt.AlignRight)
        self._lines_table.setCellWidget(row, 4, credit_edit)

        del_btn = QPushButton("X")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet(_BTN_DANGER)
        del_btn.clicked.connect(lambda checked, r=row: self._delete_line(r))
        self._lines_table.setCellWidget(row, 2, del_btn) if False else None

    def _delete_line(self, row: int):
        if self._lines_table.rowCount() <= 2:
            QMessageBox.warning(self, "Validation", "At least 2 journal lines are required.")
            return
        self._lines_table.removeRow(row)
        self._renumber_rows()
        self._update_totals()

    def _renumber_rows(self):
        for row in range(self._lines_table.rowCount()):
            sr = QTableWidgetItem(str(row + 1))
            sr.setFlags(sr.flags() & ~Qt.ItemIsEditable)
            sr.setTextAlignment(Qt.AlignCenter)
            self._lines_table.setItem(row, 0, sr)

    def _set_voucher_no(self):
        if not self._entry:
            conn = None
            try:
                from database.connection import get_connection
                conn = get_connection()
                self.voucher_no_edit.setText(
                    JournalDAO.generate_next_voucher_no(conn)
                )
            finally:
                if conn:
                    conn.close()

    def _set_current_datetime(self):
        from PySide6.QtCore import QDate
        now = datetime.now()
        self.entry_date.setDate(QDate(now.year, now.month, now.day))
        self.entry_time_edit.setText(now.strftime("%H:%M"))

    def _populate(self, entry: dict, items: list[dict]):
        self.voucher_no_edit.setText(entry.get("voucher_no", ""))

        from PySide6.QtCore import QDate
        ed = entry.get("entry_date", "")
        if ed:
            try:
                parts = ed.split("-")
                self.entry_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.entry_time_edit.setText(entry.get("entry_time", ""))
        self.narration_edit.setText(entry.get("narration", ""))

        self._lines_table.setRowCount(0)
        for it in items:
            row = self._lines_table.rowCount()
            self._lines_table.insertRow(row)

            sr = QTableWidgetItem(str(row + 1))
            sr.setFlags(sr.flags() & ~Qt.ItemIsEditable)
            sr.setTextAlignment(Qt.AlignCenter)
            self._lines_table.setItem(row, 0, sr)

            combo = _make_combo()
            combo.addItem("-- Select Ledger --", None)
            for lg in self._ledgers:
                combo.addItem(lg["ledger_name"], lg["id"])
            lid = it.get("ledger_id")
            if lid:
                idx = combo.findData(lid)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(lambda: self._update_totals())
            self._lines_table.setCellWidget(row, 1, combo)

            desc = QTableWidgetItem(it.get("description", ""))
            self._lines_table.setItem(row, 2, desc)

            debit_edit = _make_edit("0.00", 100)
            debit_edit.setAlignment(Qt.AlignRight)
            d = it.get("debit", 0.0)
            if d:
                debit_edit.setText(f"{d:.2f}")
            self._lines_table.setCellWidget(row, 3, debit_edit)

            credit_edit = _make_edit("0.00", 100)
            credit_edit.setAlignment(Qt.AlignRight)
            c = it.get("credit", 0.0)
            if c:
                credit_edit.setText(f"{c:.2f}")
            self._lines_table.setCellWidget(row, 4, credit_edit)

        self._update_totals()

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _collect_items(self) -> list[dict]:
        items = []
        for row in range(self._lines_table.rowCount()):
            combo = self._lines_table.cellWidget(row, 1)
            if not combo:
                continue
            ledger_id = combo.currentData()
            desc_item = self._lines_table.item(row, 2)
            description = desc_item.text() if desc_item else ""
            debit_edit = self._lines_table.cellWidget(row, 3)
            credit_edit = self._lines_table.cellWidget(row, 4)
            debit = _safe_float(debit_edit.text()) if debit_edit else 0.0
            credit = _safe_float(credit_edit.text()) if credit_edit else 0.0
            items.append({
                "ledger_id": ledger_id,
                "description": description,
                "debit": debit,
                "credit": credit,
            })
        return items

    def _on_save(self):
        try:
            financial_year.validate_transaction_date(self.entry_date.date().toString("yyyy-MM-dd"))
        except financial_year.FinancialYearError as exc:
            QMessageBox.warning(self, "Financial Year", str(exc)); return
        items = self._collect_items()

        entry = {
            "entry_date": self.entry_date.date().toString("yyyy-MM-dd"),
            "entry_time": self.entry_time_edit.text().strip(),
            "narration": self.narration_edit.text().strip(),
        }

        try:
            if self._entry:
                JournalDAO.update_entry(self._entry["id"], entry, items)
            else:
                JournalDAO.insert_entry(entry, items)
            self._saved = True
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Validation", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save journal entry:\n{e}")

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Journal Entry PAGE
# ======================================================================

class JournalEntryPage(QWidget):
    """Journal Entry screen with history list and entry dialog."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._history_page = self._build_history_page()
        self._stack.addWidget(self._history_page)

        self._placeholder = QWidget()
        ph_layout = QVBoxLayout(self._placeholder)
        ph_layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel("Journal entry opens via dialog.")
        lbl.setStyleSheet(f"color: {_TEXT}; font-size: 16px; font-family: 'Segoe UI';")
        lbl.setAlignment(Qt.AlignCenter)
        ph_layout.addWidget(lbl)
        self._stack.addWidget(self._placeholder)

        self._refresh_history()

    # ------------------------------------------------------------------
    # History page
    # ------------------------------------------------------------------

    def _build_history_page(self) -> QWidget:
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

        title = QLabel("Journal Entry - History")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        new_btn = QPushButton("New Entry")
        new_btn.setFixedWidth(130)
        new_btn.setStyleSheet(_BTN_SAVE)
        new_btn.clicked.connect(self._on_new)
        hl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(90)
        edit_btn.setStyleSheet(_BTN_SECONDARY)
        edit_btn.clicked.connect(self._on_edit)
        hl.addWidget(edit_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedWidth(90)
        del_btn.setStyleSheet(_BTN_DANGER)
        del_btn.clicked.connect(self._on_delete)
        hl.addWidget(del_btn)

        layout.addWidget(header)

        # Filter bar
        filter_bar = QWidget()
        filter_bar.setFixedHeight(48)
        filter_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.setSpacing(8)

        fl.addWidget(self._flbl("From"))
        self._filter_from = _make_date()
        self._filter_from.setMaximumWidth(120)
        fl.addWidget(self._filter_from)

        fl.addWidget(self._flbl("To"))
        self._filter_to = _make_date()
        self._filter_to.setMaximumWidth(120)
        fl.addWidget(self._filter_to)

        fl.addWidget(self._flbl("Voucher No"))
        self._filter_voucher = _make_edit("JV-0001")
        self._filter_voucher.setMaximumWidth(120)
        fl.addWidget(self._filter_voucher)

        filter_btn = QPushButton("Filter")
        filter_btn.setFixedWidth(70)
        filter_btn.setStyleSheet(_BTN_GREEN_SM)
        filter_btn.clicked.connect(self._refresh_history)
        fl.addWidget(filter_btn)

        fl.addStretch()
        layout.addWidget(filter_bar)

        # History table
        self._hist_table = QTableWidget()
        self._hist_table.setColumnCount(6)
        self._hist_table.setHorizontalHeaderLabels([
            "Voucher No", "Date", "Time", "Narration",
            "Total Debit", "Total Credit"
        ])
        self._hist_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._hist_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hist_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setShowGrid(True)
        self._hist_table.setAlternatingRowColors(False)
        self._hist_table.setSortingEnabled(True)

        hv = self._hist_table.horizontalHeader()
        hv.setStretchLastSection(True)
        for col in range(6):
            if col == 3:
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
        self._hist_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        layout.addWidget(self._hist_table, 1)

        return page

    def _flbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_DIM)
        return lbl

    def _refresh_history(self):
        from_date = self._filter_from.date().toString("yyyy-MM-dd")
        to_date = self._filter_to.date().toString("yyyy-MM-dd")
        voucher = self._filter_voucher.text().strip()

        entries = JournalDAO.get_all_filtered(
            date_from=from_date, date_to=to_date, voucher_no=voucher,
        )

        self._hist_table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            self._hist_table.setItem(i, 0, QTableWidgetItem(e.get("voucher_no", "")))
            self._hist_table.setItem(i, 1, QTableWidgetItem(e.get("entry_date", "")))
            self._hist_table.setItem(i, 2, QTableWidgetItem(e.get("entry_time", "")))
            self._hist_table.setItem(i, 3, QTableWidgetItem(e.get("narration", "")))

            d_item = QTableWidgetItem(f"{e.get('total_debit', 0.0):.2f}")
            d_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._hist_table.setItem(i, 4, d_item)

            c_item = QTableWidgetItem(f"{e.get('total_credit', 0.0):.2f}")
            c_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._hist_table.setItem(i, 5, c_item)

            self._hist_table.item(i, 0).setData(Qt.UserRole, e["id"])

    def _selected_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._hist_table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _on_new(self):
        self._open_dialog()

    def _on_edit(self):
        eid = self._selected_id()
        if not eid:
            QMessageBox.information(self, "Edit Entry", "Please select a journal entry to edit.")
            return
        entry = JournalDAO.get_by_id(eid)
        if not entry:
            QMessageBox.warning(self, "Edit Entry", "Could not load journal entry.")
            return
        items = JournalDAO.get_items(eid)
        self._open_dialog(entry=entry, items=items)

    def _on_delete(self):
        eid = self._selected_id()
        if not eid:
            QMessageBox.information(self, "Delete Entry", "Please select a journal entry to delete.")
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            "Are you sure you want to delete this journal entry?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                JournalDAO.delete_entry(eid)
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete entry:\n{e}")

    def _open_dialog(self, entry: dict | None = None, items: list[dict] | None = None):
        dlg = _JournalEntryDialog(self, entry=entry, items=items)
        dlg.exec()
        if dlg.was_saved:
            self._refresh_history()
