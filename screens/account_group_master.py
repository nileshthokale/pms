"""Account Group Master screen — Phase 4A.

Provides list/create/edit/delete/search for the structured
account-group hierarchy used by future financial statements.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
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

from database.account_group_dao import AccountGroupDAO
from database.account_roles import (
    STMT_ASSET,
    STMT_LIABILITY,
    STMT_EQUITY,
    STMT_INCOME,
    STMT_EXPENSE,
    NORMAL_DEBIT,
    NORMAL_CREDIT,
)

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
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #d32f2f; }}"
)

_LABEL_STYLE = (
    f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI';"
    f" background: transparent;"
)

_STMT_TYPES = [STMT_ASSET, STMT_LIABILITY, STMT_EQUITY, STMT_INCOME, STMT_EXPENSE, ""]
_NORMAL_BALANCES = [NORMAL_DEBIT, NORMAL_CREDIT, ""]


def _make_edit(placeholder: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_EDIT_STYLE)
    e.setFont(QFont("Segoe UI", 12))
    if width:
        e.setMaximumWidth(width)
    return e


def _make_combo() -> QComboBox:
    c = QComboBox()
    c.setStyleSheet(_COMBO_STYLE)
    return c


# ======================================================================
# Account Group Entry Dialog
# ======================================================================

class _AccountGroupDialog(QDialog):
    """Modal dialog for creating / editing an account group."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        group: dict | None = None,
        all_groups: list[dict] | None = None,
    ):
        super().__init__(parent)
        self._group = group
        self._all_groups = all_groups or []
        self._saved = False

        self.setWindowTitle(
            "Edit Account Group" if group else "Add New Account Group"
        )
        self.setMinimumWidth(460)
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
        self._name_edit.setPlaceholderText("Enter group name")
        form.addRow("Group Name *:", self._name_edit)

        # Parent combo — exclude self when editing
        self._parent_combo = _make_combo()
        self._parent_combo.addItem("(None)", None)
        exclude_id = group["id"] if group else None
        for g in self._all_groups:
            if g["id"] != exclude_id:
                self._parent_combo.addItem(g["group_name"], g["id"])
        form.addRow("Parent Group:", self._parent_combo)

        # Statement type
        self._stmt_combo = _make_combo()
        self._stmt_combo.addItem("", "")
        for st in _STMT_TYPES[:-1]:  # skip trailing ""
            self._stmt_combo.addItem(st, st)
        form.addRow("Statement Type:", self._stmt_combo)

        # Normal balance
        self._normal_combo = _make_combo()
        self._normal_combo.addItem("", "")
        for nb in _NORMAL_BALANCES[:-1]:
            self._normal_combo.addItem(nb, nb)
        form.addRow("Normal Balance:", self._normal_combo)

        self._system_check = QCheckBox("System Group")
        self._system_check.setStyleSheet(_LABEL_STYLE)
        form.addRow("", self._system_check)

        if group:
            self._name_edit.setText(group.get("group_name", ""))
            pid = group.get("parent_group_id")
            if pid is not None:
                idx = self._parent_combo.findData(pid)
                if idx >= 0:
                    self._parent_combo.setCurrentIndex(idx)
            stmt = group.get("statement_type", "")
            if stmt:
                idx = self._stmt_combo.findData(stmt)
                if idx >= 0:
                    self._stmt_combo.setCurrentIndex(idx)
            nb = group.get("normal_balance", "")
            if nb:
                idx = self._normal_combo.findData(nb)
                if idx >= 0:
                    self._normal_combo.setCurrentIndex(idx)
            self._system_check.setChecked(bool(group.get("is_system", 0)))

        # Buttons
        btn_layout = QHBoxLayout()
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

        form.addRow("", btn_layout)

    def _on_save(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Group Name is required.")
            return

        parent_id = self._parent_combo.currentData()
        stmt_type = self._stmt_combo.currentText()
        normal_bal = self._normal_combo.currentText()
        is_sys = self._system_check.isChecked()

        try:
            if self._group:
                AccountGroupDAO.update(
                    self._group["id"],
                    group_name=name,
                    parent_group_id=parent_id,
                    statement_type=stmt_type,
                    normal_balance=normal_bal,
                    is_system=is_sys,
                )
            else:
                AccountGroupDAO.insert(
                    group_name=name,
                    parent_group_id=parent_id,
                    statement_type=stmt_type,
                    normal_balance=normal_bal,
                    is_system=is_sys,
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
            return

        self._saved = True
        self.accept()

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Account Group Master PAGE
# ======================================================================

class AccountGroupMasterPage(QWidget):
    """Account Group Master screen with list, New, Edit and Delete buttons."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Account Group Master")
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

        delete_btn = QPushButton("Delete")
        delete_btn.setFixedWidth(90)
        delete_btn.setStyleSheet(_BTN_DANGER)
        delete_btn.clicked.connect(self._on_delete)
        hl.addWidget(delete_btn)

        root.addWidget(header)

        # ── Search bar ────────────────────────────────────────────
        search_bar = QWidget()
        search_bar.setFixedHeight(48)
        search_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        sl = QHBoxLayout(search_bar)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(8)

        sl.addWidget(QLabel("Search:"))
        self._search_edit = _make_edit("Group name...")
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
        root.addWidget(search_bar)

        # ── Table ─────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "ID", "Group Name", "Parent", "Statement Type",
            "Normal Balance", "System",
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 9pt;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 11px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        root.addWidget(self._table, 1)

        self._refresh()

    # ── Helpers ───────────────────────────────────────────────────

    def _refresh(self, groups: list[dict] | None = None):
        if groups is None:
            groups = AccountGroupDAO.get_all()

        # Build id → name map for parent display
        id_to_name = {g["id"]: g["group_name"] for g in groups}

        self._table.setRowCount(len(groups))
        for i, g in enumerate(groups):
            self._table.setItem(i, 0, QTableWidgetItem(str(g["id"])))
            self._table.setItem(i, 1, QTableWidgetItem(g["group_name"]))

            pid = g.get("parent_group_id")
            parent_name = id_to_name.get(pid, "") if pid else ""
            self._table.setItem(i, 2, QTableWidgetItem(parent_name))
            self._table.setItem(i, 3, QTableWidgetItem(g.get("statement_type", "")))
            self._table.setItem(i, 4, QTableWidgetItem(g.get("normal_balance", "")))
            self._table.setItem(i, 5, QTableWidgetItem("Yes" if g.get("is_system") else ""))

            self._table.item(i, 0).setData(Qt.UserRole, g["id"])

    def _selected_id(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).data(Qt.UserRole)

    # ── Actions ───────────────────────────────────────────────────

    def _on_search(self):
        text = self._search_edit.text().strip()
        if text:
            all_groups = AccountGroupDAO.get_all()
            filtered = [g for g in all_groups if text.lower() in g["group_name"].lower()]
            self._refresh(filtered)
        else:
            self._refresh()

    def _on_show_all(self):
        self._search_edit.clear()
        self._refresh()

    def _on_new(self):
        all_groups = AccountGroupDAO.get_all()
        dlg = _AccountGroupDialog(self, all_groups=all_groups)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_edit(self):
        gid = self._selected_id()
        if not gid:
            QMessageBox.information(
                self, "Edit Account Group",
                "Please select a group to edit."
            )
            return
        group = AccountGroupDAO.get_by_id(gid)
        if not group:
            QMessageBox.warning(
                self, "Edit Account Group",
                "Could not load group data."
            )
            return
        all_groups = AccountGroupDAO.get_all()
        dlg = _AccountGroupDialog(self, group=group, all_groups=all_groups)
        dlg.exec()
        if dlg.was_saved:
            self._refresh()

    def _on_delete(self):
        gid = self._selected_id()
        if not gid:
            QMessageBox.information(
                self, "Delete Account Group",
                "Please select a group to delete."
            )
            return

        ok, reason = AccountGroupDAO.can_delete(gid)
        if not ok:
            QMessageBox.warning(self, "Delete Account Group", reason)
            return

        group = AccountGroupDAO.get_by_id(gid)
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete account group '{group['group_name']}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                AccountGroupDAO.delete(gid)
            except ValueError as exc:
                QMessageBox.warning(self, "Delete Failed", str(exc))
            self._refresh()
