from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from database import auth
from ui import components as ui
from ui.input_rules import set_uppercase

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
        # An account name is an authentication identifier, stored and audited
        # exactly as typed — not business data (see ui/input_rules.py).
        set_uppercase(self.username, False)
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


class ChangePasswordDialog(QDialog):
    """Dialog to change a user's password with credential verification."""

    def __init__(self, user_id: int, username: str, parent=None):
        super().__init__(parent)
        self.user_id = user_id
        self.username_text = username
        self.setWindowTitle("Change Password")
        self.setMinimumWidth(380)

        current_actor = auth.session.user or {}
        self.is_self = current_actor.get("id") == self.user_id

        form = QFormLayout(self)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        self.username_field = QLineEdit(self.username_text)
        self.username_field.setReadOnly(True)
        set_uppercase(self.username_field, False)
        form.addRow("Username", self.username_field)

        self.current_password = QLineEdit()
        self.current_password.setEchoMode(QLineEdit.Password)
        set_uppercase(self.current_password, False)
        current_label = "Current Password" if self.is_self else "Admin Password"
        self.current_password.setPlaceholderText(
            "Enter your current password" if self.is_self else "Enter your administrator password"
        )
        form.addRow(current_label, self.current_password)

        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.new_password.setPlaceholderText("Minimum 8 characters")
        set_uppercase(self.new_password, False)
        form.addRow("New Password", self.new_password)

        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.Password)
        self.confirm_password.setPlaceholderText("Re-type new password")
        set_uppercase(self.confirm_password, False)
        form.addRow("Confirm Password", self.confirm_password)

        self.show_passwords_cb = QCheckBox("Show Passwords")
        self.show_passwords_cb.toggled.connect(self._toggle_show_passwords)
        form.addRow("", self.show_passwords_cb)

        buttons = QHBoxLayout()
        self.save_btn = ui.ActionButton("Save Password", "primary")
        self.save_btn.clicked.connect(self._on_save)
        self.cancel_btn = ui.ActionButton("Cancel", "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.cancel_btn)
        form.addRow(buttons)

    def _toggle_show_passwords(self, checked: bool):
        mode = QLineEdit.Normal if checked else QLineEdit.Password
        self.current_password.setEchoMode(mode)
        self.new_password.setEchoMode(mode)
        self.confirm_password.setEchoMode(mode)

    def _on_save(self):
        curr_pwd = self.current_password.text()
        new_pwd = self.new_password.text()
        confirm_pwd = self.confirm_password.text()

        if not curr_pwd:
            err_msg = "Please enter your current password." if self.is_self else "Please enter your administrator password."
            QMessageBox.warning(self, "Change Password", err_msg)
            return

        if not new_pwd:
            QMessageBox.warning(self, "Change Password", "Please enter a new password.")
            return

        if new_pwd != confirm_pwd:
            QMessageBox.warning(self, "Change Password", "New password and confirmation do not match.")
            return

        if len(new_pwd) < 8:
            QMessageBox.warning(self, "Change Password", "Password must contain at least 8 characters.")
            return

        if not new_pwd.strip():
            QMessageBox.warning(self, "Change Password", "Password cannot consist solely of whitespace.")
            return

        if self.is_self and new_pwd == curr_pwd:
            QMessageBox.warning(self, "Change Password", "New password must be different from current password.")
            return

        try:
            auth.change_password(
                actor=auth.session.user,
                user_id=self.user_id,
                current_password=curr_pwd,
                new_password=new_pwd,
            )
            QMessageBox.information(self, "Change Password", "Password changed successfully.")
            self.accept()
        except (auth.AuthenticationError, auth.PermissionDenied) as exc:
            QMessageBox.warning(self, "Change Password", str(exc))


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
        self._change_password = ui.ActionButton("Change Password", "secondary")
        self._change_password.clicked.connect(self._change_password_clicked)
        self._change_password.setEnabled(False)
        self._role = ui.style_combo(QComboBox()); self._role.addItems(list(auth.USER_ROLES))
        self._change_role = ui.ActionButton("Change Role", "secondary")
        self._change_role.clicked.connect(self._change_selected_role)
        actions = ui.FilterBar()
        actions.add_widget(self._create)
        actions.add_widget(self._refresh_button)
        actions.add_widget(self._toggle_active)
        actions.add_widget(self._change_password)
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

    def _selected_username(self):
        row = self._selected_row()
        if row is None:
            return None
        item = self._table.item(row, 0)
        return item.text() if item is not None else None

    def _sync_action_button(self, *_args):
        is_active = self._selected_is_active()
        user_id = self._selected_id()
        has_sel = user_id is not None
        if is_active is None:
            self._toggle_active.setText(ACTIVATE_TEXT)
            self._toggle_active.setEnabled(False)
        else:
            self._toggle_active.setText(DEACTIVATE_TEXT if is_active else ACTIVATE_TEXT)
            self._toggle_active.setEnabled(True)
        self._change_password.setEnabled(has_sel)

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

    def _change_password_clicked(self):
        if not self._guard():
            return
        user_id = self._selected_id()
        username = self._selected_username()
        if user_id is None or not username:
            return
        dialog = ChangePasswordDialog(user_id=user_id, username=username, parent=self)
        dialog.exec()
