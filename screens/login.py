from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

from database import auth
from ui import components as ui


class LoginDialog(QDialog):
    """Login and first-run ADMIN setup dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pharmacy Management System Login")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._first_run = auth.user_count() == 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        brand = QLabel("Pharmacy Management System")
        brand.setStyleSheet(ui.title_style(13))
        layout.addWidget(brand)
        title = QLabel("First-run ADMIN setup" if self._first_run else "Sign in")
        title.setStyleSheet(ui.label_style(bold=True, size=10))
        layout.addWidget(title)
        if self._first_run:
            layout.addWidget(ui.subtitle("Create the initial ADMIN account to continue."))

        form = QFormLayout()
        self._username = ui.style_edit(QLineEdit())
        self._password = ui.style_edit(QLineEdit())
        self._password.setEchoMode(QLineEdit.Password)
        form.addRow("Username", self._username)
        form.addRow("Password", self._password)
        layout.addLayout(form)
        if self._first_run:
            self._confirm = ui.style_edit(QLineEdit())
            self._confirm.setEchoMode(QLineEdit.Password)
            form.addRow("Confirm password", self._confirm)
        else:
            self._confirm = None

        button = ui.ActionButton("Create ADMIN" if self._first_run else "Login", "primary")
        button.clicked.connect(self._submit)
        layout.addWidget(button)
        self._username.setFocus()

    def _submit(self):
        username = self._username.text().strip()
        password = self._password.text()
        if self._first_run:
            if password != self._confirm.text():
                QMessageBox.warning(self, "Setup", "Passwords do not match.")
                return
            try:
                auth.create_first_admin(username, password)
            except auth.AuthenticationError as exc:
                QMessageBox.warning(self, "Setup", str(exc))
                return
            auth.session.login(username, password)
            self.accept()
            return
        if not auth.session.login(username, password):
            QMessageBox.warning(self, "Login", "Invalid credentials or inactive account.")
            self._password.clear()
            return
        self.accept()


def run_login(parent=None) -> bool:
    auth.ensure_auth_schema()
    dialog = LoginDialog(parent)
    return dialog.exec() == QDialog.Accepted
