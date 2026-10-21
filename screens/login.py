from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from database import auth
from ui import components as ui
from ui.input_rules import set_uppercase
from version import APP_TITLE

#login file


class LoginDialog(QDialog):
    """Login and first-run ADMIN setup dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        is_staging = os.environ.get("PHARMACY_STAGING_MODE") == "1"
        if is_staging:
            self.setWindowTitle("Pharmacy Management System Login [STAGING / AUDIT MODE]")
        else:
            self.setWindowTitle("Pharmacy Management System Login")
        self.setModal(True)
        self.setMinimumWidth(380)
        if parent is None:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._first_run = auth.user_count() == 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        brand = QLabel(APP_TITLE)
        brand.setStyleSheet(ui.title_style())
        layout.addWidget(brand)
        title = QLabel("First-run ADMIN setup" if self._first_run else "Sign in")
        title.setStyleSheet(ui.label_style(bold=True))
        layout.addWidget(title)
        if self._first_run:
            layout.addWidget(ui.subtitle("Create the initial ADMIN account to continue."))

        form = QFormLayout()
        self._username = ui.style_edit(QLineEdit())
        self._password = ui.style_edit(QLineEdit())
        self._password.setEchoMode(QLineEdit.Password)
        # Authentication identifiers and secrets are not business data: the
        # account name is stored and audited exactly as the operator typed
        # it, and the password must keep its case.  (An echo-mode password
        # field excludes itself; the username needs to say so explicitly.)
        set_uppercase(self._username, False)
        set_uppercase(self._password, False)
        form.addRow("Username", self._username)
        form.addRow("Password", self._password)
        layout.addLayout(form)
        if self._first_run:
            self._confirm = ui.style_edit(QLineEdit())
            self._confirm.setEchoMode(QLineEdit.Password)
            set_uppercase(self._confirm, False)
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


def _desktop_names() -> tuple[str, str | None, str | None]:
    """Return (window station, this thread's desktop, input desktop).

    Windows can attach a process to a private desktop object on ``WinSta0``
    (sandboxed/agent-hosted terminals do this).  Windows created there are
    real — ``IsWindowVisible()`` is true — but they are never displayed on
    the operator's screen.  Qt has no way to detect or correct that, so the
    launcher checks it before entering a modal loop.
    """
    if sys.platform != "win32":
        return "", None, None

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    name_size = 256
    needed = wintypes.DWORD()

    def _object_name(handle) -> str | None:
        if not handle:
            return None
        buffer = ctypes.create_unicode_buffer(name_size)
        user32.GetUserObjectInformationW(
            handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)
        )
        return buffer.value or None

    station_name = _object_name(user32.GetProcessWindowStation())
    desktop_handle = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    desktop_name = _object_name(desktop_handle)

    DESKTOP_READOBJECTS = 0x0001
    DESKTOP_SWITCHDESKTOP = 0x0100
    input_handle = user32.OpenInputDesktop(
        0, False, DESKTOP_READOBJECTS | DESKTOP_SWITCHDESKTOP
    )
    input_name = _object_name(input_handle)
    if input_handle:
        user32.CloseDesktop(input_handle)

    return station_name or "", desktop_name, input_name


def _login_diag(message: str) -> None:
    """Flushed startup diagnostics for the login window (staging runs only)."""
    if os.environ.get("PHARMACY_STAGING_MODE") == "1":
        print(f"[LOGIN] {message}", file=sys.stderr, flush=True)


def run_login(parent=None) -> bool:
    auth.ensure_auth_schema()

    app = QApplication.instance()
    platform_name = QGuiApplication.platformName()
    station_name, desktop_name, input_name = _desktop_names()
    _login_diag(
        f"Qt platform={platform_name!r} window_station={station_name!r} "
        f"desktop={desktop_name!r} input_desktop={input_name!r} application={app!r}"
    )
    for screen in QGuiApplication.screens():
        _login_diag(
            f"screen {screen.name()!r} geometry={screen.geometry().getRect()} "
            f"available={screen.availableGeometry().getRect()} "
            f"devicePixelRatio={screen.devicePixelRatio()}"
        )

    # A non-display platform can create widgets but can never put one on the
    # desktop.  Failing loudly is strictly better than a modal loop waiting
    # forever behind an invisible window.
    if platform_name in ("offscreen", "minimal"):
        raise RuntimeError(
            f"Qt is running on the {platform_name!r} platform plugin, which cannot "
            "display a window. Unset QT_QPA_PLATFORM and launch again."
        )

    # A private desktop is just as invisible to the operator: the window is
    # created, reports itself visible/exposed, and still never reaches the
    # screen.  Staging and test-release launches fail loudly with the exact
    # remedy; a normal launch keeps its previous behaviour (the window still
    # cannot appear, but this diagnostic must not change production startup).
    if input_name and desktop_name and desktop_name != input_name:
        private_desktop_message = (
            "This process is attached to the private Windows desktop "
            f"{desktop_name!r} (window station {station_name!r}), but the "
            f"interactive desktop is {input_name!r}.\n"
            "Windows creates the login window on the private desktop, so it "
            "can never appear on screen - Qt's isVisible()/isActiveWindow() "
            "still report True.\n"
            "This happens when the launcher is started from a sandboxed or "
            "agent-hosted terminal. Run '.\\run_staging.ps1 run' from a normal "
            "PowerShell window (Start -> Windows PowerShell) instead."
        )
        if (
            os.environ.get("PHARMACY_STAGING_MODE") == "1"
            or os.environ.get("PHARMACY_TEST_RELEASE") == "1"
        ):
            raise RuntimeError(private_desktop_message)
        print(
            f"[WARNING] {private_desktop_message}",
            file=sys.stderr,
            flush=True,
        )

    dialog = LoginDialog(parent)
    _login_diag(
        f"LoginDialog created; windowFlags=0x{int(dialog.windowFlags()):x} "
        f"modal={dialog.isModal()} "
        f"sizeHint={dialog.sizeHint().width()}x{dialog.sizeHint().height()}"
    )

    # Size the dialog for its content and place it on the screen the operator
    # is actually looking at (the one under the mouse) instead of relying on
    # the platform's default placement.
    dialog.adjustSize()
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        frame = dialog.frameGeometry()
        frame.moveCenter(available.center())
        dialog.move(frame.topLeft())
    _login_diag(
        f"Active screen={(screen.name() if screen else None)!r} "
        f"geometry={dialog.geometry().getRect()} "
        f"frame={dialog.frameGeometry().getRect()}"
    )

    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    if app is not None:
        app.processEvents()
    _login_diag(
        f"After show/raise/activate: visible={dialog.isVisible()} "
        f"minimized={dialog.isMinimized()} active={dialog.isActiveWindow()} "
        f"geometry={dialog.geometry().getRect()} winId={int(dialog.winId())}"
    )

    def _verify_and_reassert() -> None:
        # Runs on the GUI thread once the event loop is pumping, so this
        # reports the state Qt/Windows actually settled on - not merely the
        # fact that show() was called.
        if not dialog.isVisible():
            _login_diag("dialog reported hidden inside the event loop - re-showing")
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        _login_diag(
            f"Delayed check: visible={dialog.isVisible()} "
            f"minimized={dialog.isMinimized()} active={dialog.isActiveWindow()} "
            f"geometry={dialog.geometry().getRect()}"
        )

    QTimer.singleShot(0, _verify_and_reassert)

    _login_diag("Entering dialog.exec()")
    result = dialog.exec()
    _login_diag(f"exec() returned {int(result)} (Accepted={int(QDialog.DialogCode.Accepted)})")
    return result == QDialog.DialogCode.Accepted
