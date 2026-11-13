from __future__ import annotations

import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import auth
from ui import components as ui
from ui.input_rules import set_uppercase
from ui.theme import palette
from licensing.qt import get_active_controller, get_license_info

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


class _ActivateLicenseDialog(QDialog):
    """Modal dialog allowing Administrator to enter or renew a License ID."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Activate or Renew License")
        self.setMinimumWidth(480)
        p = palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        heading = QLabel("Enter License ID / Activation Key")
        heading.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {p['text']};")
        layout.addWidget(heading)

        desc = QLabel(
            "Paste the License ID issued from Super Admin to renew your subscription\n"
            "or expand device capacity for this pharmacy installation."
        )
        desc.setStyleSheet(f"font-size: 12px; color: {p['text_dim']};")
        layout.addWidget(desc)

        self.key_field = QLineEdit()
        self.key_field.setPlaceholderText("e.g. 2994c8a1-d281-4ffc-a9df-f63523c86726")
        self.key_field.setStyleSheet(
            f"padding: 8px; font-family: Consolas, monospace; font-size: 13px; "
            f"border: 1px solid {p['border']}; border-radius: 4px; background: {p['bg']};"
        )
        set_uppercase(self.key_field, False)
        layout.addWidget(self.key_field)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = ui.ActionButton("Cancel", "secondary")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        activate = ui.ActionButton("Activate & Verify", "primary")
        activate.clicked.connect(self.accept)
        btn_row.addWidget(activate)
        layout.addLayout(btn_row)


class LicenseValidityPanel(QWidget):
    """ADMIN dashboard panel displaying software license validity, remaining days, and renewal tools."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LicenseValidityPanel")
        self._init_ui()
        self.refresh_details()

        ctrl = get_active_controller()
        if ctrl is not None and hasattr(ctrl, "validation_updated"):
            try:
                ctrl.validation_updated.connect(lambda _dec: self.refresh_details())
            except Exception:
                pass

    def _init_ui(self):
        p = palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        # Header Strip with Title and Status Pill
        header = ui.PageHeader("Software License & Subscription Validity")
        self._badge = QLabel("Checking validity...")
        self._badge.setStyleSheet(
            "padding: 3px 10px; border-radius: 10px; font-size: 11px; font-weight: bold;"
        )
        header.add_action(self._badge)
        layout.addWidget(header)

        # Card container
        self._container = QFrame()
        self._container.setObjectName("LicenseContainer")
        self._container.setStyleSheet(
            f"#LicenseContainer {{"
            f"  background-color: {p['surface_alt']};"
            f"  border: 1px solid {p['border']};"
            f"  border-radius: 4px;"
            f"}}"
        )
        cont_layout = QVBoxLayout(self._container)
        cont_layout.setContentsMargins(14, 12, 14, 12)
        cont_layout.setSpacing(10)

        # Hero Banner Card
        self._card = QFrame()
        self._card.setObjectName("LicenseHeroCard")
        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(3)

        self._days_label = QLabel("0 Days Remaining")
        self._days_label.setStyleSheet("font-size: 22px; font-weight: 800;")
        left_col.addWidget(self._days_label)

        self._expires_label = QLabel("Valid until: ...")
        self._expires_label.setStyleSheet(f"font-size: 12px; color: {p['text_dim']};")
        left_col.addWidget(self._expires_label)
        card_layout.addLayout(left_col, 2)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(4)
        right_col.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._status_text = QLabel("Status: AUTHORIZED")
        self._status_text.setStyleSheet("font-size: 12px; font-weight: 600;")
        right_col.addWidget(self._status_text)

        self._conn_text = QLabel("Network: Online")
        self._conn_text.setStyleSheet(f"font-size: 11px; color: {p['text_dim']};")
        right_col.addWidget(self._conn_text)
        card_layout.addLayout(right_col, 1)

        cont_layout.addWidget(self._card)

        # Details Grid
        grid = QGridLayout()
        grid.setContentsMargins(4, 2, 4, 2)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        # Row 0: License ID
        lbl_lic = QLabel("License ID:")
        lbl_lic.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {p['text']};")
        grid.addWidget(lbl_lic, 0, 0)

        lic_box = QHBoxLayout()
        lic_box.setSpacing(6)
        self._license_id = QLabel("—")
        self._license_id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._license_id.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        lic_box.addWidget(self._license_id)

        self._copy_lic_btn = QPushButton("📋 Copy")
        self._copy_lic_btn.setFixedSize(60, 24)
        self._copy_lic_btn.setStyleSheet("font-size: 11px; padding: 2px;")
        self._copy_lic_btn.clicked.connect(self._copy_license_id)
        lic_box.addWidget(self._copy_lic_btn)
        lic_box.addStretch()
        grid.addLayout(lic_box, 0, 1)

        # Row 0: Device ID
        lbl_dev = QLabel("Registered Device ID:")
        lbl_dev.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {p['text']};")
        grid.addWidget(lbl_dev, 0, 2)

        dev_box = QHBoxLayout()
        dev_box.setSpacing(6)
        self._device_id = QLabel("—")
        self._device_id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._device_id.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        dev_box.addWidget(self._device_id)

        self._copy_dev_btn = QPushButton("📋 Copy")
        self._copy_dev_btn.setFixedSize(60, 24)
        self._copy_dev_btn.setStyleSheet("font-size: 11px; padding: 2px;")
        self._copy_dev_btn.clicked.connect(self._copy_device_id)
        dev_box.addWidget(self._copy_dev_btn)
        dev_box.addStretch()
        grid.addLayout(dev_box, 0, 3)

        # Row 1: Customer Account
        lbl_cust = QLabel("Customer Account:")
        lbl_cust.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {p['text']};")
        grid.addWidget(lbl_cust, 1, 0)
        self._cust_id = QLabel("—")
        self._cust_id.setStyleSheet("font-size: 12px;")
        grid.addWidget(self._cust_id, 1, 1)

        # Row 1: Offline Grace
        lbl_off = QLabel("Offline Grace Lease:")
        lbl_off.setStyleSheet(f"font-weight: 600; font-size: 12px; color: {p['text']};")
        grid.addWidget(lbl_off, 1, 2)
        self._offline_lease = QLabel("48 Hours Allowance")
        self._offline_lease.setStyleSheet("font-size: 12px;")
        grid.addWidget(self._offline_lease, 1, 3)

        cont_layout.addLayout(grid)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.setSpacing(10)

        self._refresh_btn = ui.ActionButton("Check / Verify Validity", "secondary")
        self._refresh_btn.clicked.connect(self._on_check_validity)
        btn_row.addWidget(self._refresh_btn)

        self._activate_btn = ui.ActionButton("Activate / Renew License", "primary")
        self._activate_btn.clicked.connect(self._on_activate_dialog)
        btn_row.addWidget(self._activate_btn)

        self._sync_status = QLabel("")
        self._sync_status.setStyleSheet(f"font-size: 11px; color: {p['text_dim']};")
        btn_row.addWidget(self._sync_status)

        btn_row.addStretch()
        cont_layout.addLayout(btn_row)

        layout.addWidget(self._container)

    def _copy_license_id(self):
        text = self._license_id.text().strip()
        if text and text != "—":
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
            self._copy_lic_btn.setText("✓ Copied")
            QTimer.singleShot(2000, lambda: self._copy_lic_btn.setText("📋 Copy"))

    def _copy_device_id(self):
        text = self._device_id.text().strip()
        if text and text != "—":
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
            self._copy_dev_btn.setText("✓ Copied")
            QTimer.singleShot(2000, lambda: self._copy_dev_btn.setText("📋 Copy"))

    def _on_check_validity(self):
        self._refresh_btn.setEnabled(False)
        self._sync_status.setText("Checking validity with licensing server…")
        ctrl = get_active_controller()
        if ctrl is not None:
            ctrl.validate()
            QTimer.singleShot(1500, self._finish_manual_check)
        else:
            try:
                from licensing.client import desktop_client
                c = desktop_client()
                c.validate()
            except Exception:
                pass
            self.refresh_details()
            self._refresh_btn.setEnabled(True)

    def _finish_manual_check(self):
        self.refresh_details()
        self._refresh_btn.setEnabled(True)

    def _on_activate_dialog(self):
        dialog = _ActivateLicenseDialog(self)
        if dialog.exec() == QDialog.Accepted:
            key = dialog.key_field.text().strip()
            if key:
                self._sync_status.setText("Activating license…")
                ctrl = get_active_controller()
                if ctrl is not None:
                    ctrl.validate(activation_key=key)
                else:
                    try:
                        from licensing.client import desktop_client
                        c = desktop_client()
                        c.validate(activation_key=key)
                    except Exception:
                        pass
                QTimer.singleShot(1000, self.refresh_details)

    def refresh_details(self):
        info = get_license_info()
        p = palette()

        days = info.get("days_remaining", 0)
        status = info.get("status", "UNKNOWN")
        level = info.get("alert_level", "danger")

        self._days_label.setText(info.get("days_label", f"{days} Days Remaining"))
        self._expires_label.setText(f"Valid until: {info.get('expires_at_formatted', 'Unknown')}")

        if level == "success":
            card_bg = "#f0fdf4" if p["bg"] == "#ffffff" else "#0f291e"
            card_border = "#86efac" if p["bg"] == "#ffffff" else "#1b4d3e"
            accent_color = "#15803d" if p["bg"] == "#ffffff" else "#4ade80"
            badge_text = f"🟢 ACTIVE · {days} DAYS"
        elif level == "warning":
            card_bg = "#fffbeb" if p["bg"] == "#ffffff" else "#2a2216"
            card_border = "#fde68a" if p["bg"] == "#ffffff" else "#4a3b20"
            accent_color = "#b45309" if p["bg"] == "#ffffff" else "#fbbf24"
            badge_text = f"⚠️ EXPIRING SOON · {days} DAYS"
        else:
            card_bg = "#fef2f2" if p["bg"] == "#ffffff" else "#2e1212"
            card_border = "#fca5a5" if p["bg"] == "#ffffff" else "#5c2424"
            accent_color = "#b91c1c" if p["bg"] == "#ffffff" else "#f87171"
            badge_text = "❌ EXPIRED / INACTIVE"

        self._card.setStyleSheet(
            f"#LicenseHeroCard {{"
            f"  background-color: {card_bg};"
            f"  border: 1px solid {card_border};"
            f"  border-radius: 4px;"
            f"}}"
        )
        self._days_label.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {accent_color};")
        self._badge.setText(badge_text)
        self._badge.setStyleSheet(
            f"background-color: {card_bg}; color: {accent_color}; border: 1px solid {card_border}; "
            f"padding: 3px 10px; border-radius: 10px; font-size: 11px; font-weight: bold;"
        )

        self._status_text.setText(f"Status: {status}")
        conn = info.get("connectivity", "NOT_CHECKED").replace("_", " ").title()
        self._conn_text.setText(f"Network: {conn}")

        self._license_id.setText(str(info.get("license_id") or "—"))
        self._device_id.setText(str(info.get("device_id") or "—"))
        self._cust_id.setText(str(info.get("customer_id") or "—"))
        self._offline_lease.setText(info.get("offline_until_formatted") or "48 Hours Allowance")

        import datetime
        now_str = datetime.datetime.now().strftime("%d-%b-%Y %I:%M %p")
        self._sync_status.setText(f"Last updated: {now_str}")


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

        # Lower half: License Validity & Remaining Days
        self._license_panel = LicenseValidityPanel(self)
        layout.addWidget(self._license_panel, 1)

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
        if hasattr(self, "_license_panel"):
            self._license_panel.refresh_details()

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
