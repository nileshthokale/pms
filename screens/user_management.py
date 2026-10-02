from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from database import auth
from ui import components as ui

_ID_ROLE = 32
_ACTIVE_ROLE = 33

ACTIVATE_TEXT = "Activate Selected"
DEACTIVATE_TEXT = "Deactivate Selected"

_COLUMNS = ["Username", "Role", "Active", "Created", "Last Login"]
_ROLE_COLUMN = 1
_ACTIVE_COLUMN = 2


class _CreateUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create User")
        form = QFormLayout(self)
        self.username = QLineEdit()
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit(); self.confirm.setEchoMode(QLineEdit.Password)
        self.role = QComboBox(); self.role.addItems(list(auth.USER_ROLES))
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        form.addRow("Confirm", self.confirm)
        form.addRow("Role", self.role)
        buttons = QHBoxLayout()
        create = ui.ActionButton("Create", "primary")
        create.clicked.connect(self.accept)
        cancel = ui.ActionButton("Cancel", "secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(create); buttons.addWidget(cancel); form.addRow(buttons)


class UserManagementPage(QWidget):
    """ADMIN-only account administration with the two supported roles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._create = ui.ActionButton("Create User", "primary")
        self._create.clicked.connect(self._create_user)
        self._refresh_button = ui.ActionButton("Refresh", "secondary")
        self._refresh_button.clicked.connect(self._refresh)
        self._toggle_active = ui.ActionButton(ACTIVATE_TEXT, "success")
        self._toggle_active.clicked.connect(self._toggle_active_user)
        self._role = ui.style_combo(QComboBox()); self._role.addItems(list(auth.USER_ROLES))
        self._change_role = ui.ActionButton("Change Role", "secondary")
        self._change_role.clicked.connect(self._change_selected_role)
        actions = ui.FilterBar()
        actions.add_widget(self._create)
        actions.add_widget(self._refresh_button)
        actions.add_widget(self._toggle_active)
        actions.add_field("Role", self._role)
        actions.add_widget(self._change_role)
        actions.add_stretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(ui.PageHeader("Master / User Management"))
        layout.addWidget(actions)
        ui.style_data_table(self._table, stretch_columns=(0, 4), resize_to_contents=(1, 2, 3))
        layout.addWidget(self._table, 1)
        self._table.selectionModel().selectionChanged.connect(self._sync_action_button)
        self._refresh()

    def _guard(self) -> bool:
        try:
            auth.session.require(auth.PERM_USER_MANAGEMENT)
            return True
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc))
            return False

    def _refresh(self):
        if not self._guard():
            return
        selected_id = self._selected_id()
        rows = auth.list_users()
        self._table.clearSelection()
        self._table.setRowCount(len(rows))
        restored = 0
        for index, row in enumerate(rows):
            self._table.setItem(index, 0, QTableWidgetItem(row["username"]))
            self._table.setItem(index, 1, QTableWidgetItem(row["role"]))
            self._table.setItem(index, 2, QTableWidgetItem("Yes" if row["is_active"] else "No"))
            self._table.setItem(index, 3, QTableWidgetItem(row.get("created_at") or ""))
            self._table.setItem(index, 4, QTableWidgetItem(row.get("last_login_at") or ""))
            self._table.item(index, 0).setData(_ID_ROLE, row["id"])
            self._table.item(index, 0).setData(_ACTIVE_ROLE, int(row["is_active"]))
            if selected_id is not None and row["id"] == selected_id:
                restored = index
        if restored:
            self._table.selectRow(restored)
        self._sync_action_button()

    def _selected_row(self):
        rows = self._table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _selected_id(self):
        row = self._selected_row()
        if row is None:
            return None
        item = self._table.item(row, 0)
        return item.data(_ID_ROLE) if item is not None else None

    def _selected_is_active(self):
        row = self._selected_row()
        if row is None:
            return None
        item = self._table.item(row, 0)
        return bool(item.data(_ACTIVE_ROLE)) if item is not None else None

    def _sync_action_button(self, *_args):
        is_active = self._selected_is_active()
        if is_active is None:
            self._toggle_active.setText(ACTIVATE_TEXT)
            self._toggle_active.setEnabled(False)
            return
        self._toggle_active.setText(DEACTIVATE_TEXT if is_active else ACTIVATE_TEXT)
        self._toggle_active.setEnabled(True)

    def _create_user(self):
        if not self._guard(): return
        dialog = _CreateUserDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        if dialog.password.text() != dialog.confirm.text():
            QMessageBox.warning(self, "Create user", "Passwords do not match."); return
        try:
            auth.create_user(auth.session.user, dialog.username.text(), dialog.password.text(), dialog.role.currentText())
            self._refresh()
        except auth.AuthenticationError as exc:
            QMessageBox.warning(self, "Create user", str(exc))

    def _toggle_active_user(self):
        if not self._guard(): return
        user_id = self._selected_id()
        if user_id is None: return
        currently_active = bool(self._selected_is_active())
        target = not currently_active
        try:
            auth.set_user_active(auth.session.user, user_id, target)
            self._refresh()
        except auth.AuthenticationError as exc:
            QMessageBox.warning(self, "Activate user" if target else "Deactivate user", str(exc))

    def _change_selected_role(self):
        if not self._guard(): return
        user_id = self._selected_id()
        if user_id is None: return
        try:
            auth.change_role(auth.session.user, user_id, self._role.currentText()); self._refresh()
        except auth.AuthenticationError as exc:
            QMessageBox.warning(self, "Change role", str(exc))