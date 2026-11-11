"""UI integration only. Networking is off the Qt thread; locks never exit the app."""
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout

from licensing.gate import OperationGate, install_gate
from licensing.storage import StorageError


class ValidationThread(QThread):
    checked = Signal(object)

    def __init__(self, client, gate, activation_key=None, parent=None):
        super().__init__(parent)
        self.client, self.gate, self.activation_key = client, gate, activation_key

    def run(self):
        try:
            decision = self.client.validate(activation_key=self.activation_key, heartbeat=True)
        except StorageError:
            from licensing.client import Decision
            decision = Decision(False, "STORAGE_ERROR", "Secure licensing storage is unavailable. Contact support.", "STORAGE_ERROR")
        self.gate.set_access(decision.allowed, decision.message)
        self.checked.emit(decision)


class LicenseDialog(QDialog):
    retry_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("License validation required")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addWidget(QLabel("Your pharmacy records and backups are preserved."))
        self.connection = QLabel()
        layout.addWidget(self.connection)
        self.device = QLabel()
        self.device.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.device)
        layout.addWidget(QLabel("Activation key (provided by support):"))
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.key)
        self.retry = QPushButton("Validate over internet")
        self.retry.clicked.connect(self._retry)
        layout.addWidget(self.retry)

    def _retry(self):
        value = self.key.text().strip() or None
        self.key.clear()
        self.retry_requested.emit(value)

    def reject(self):
        # Closing the lock leaves the running pharmacy application safely restricted.
        if self.parent() is None:
            super().reject()


class LicenseController(QObject):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.gate = OperationGate()
        install_gate(self.gate)
        self.window = None
        self.dialog = None
        self.worker = None
        self.decision = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self.ticks = 0
        self.period = max(60, min(int(client.config.get("heartbeat_seconds", 300)), 600))
        if parent is not None and hasattr(parent, "aboutToQuit"):
            try:
                parent.aboutToQuit.connect(self.shutdown)
            except Exception:
                pass

    def startup(self):
        self.dialog = LicenseDialog()
        self.dialog.retry_requested.connect(self.validate)
        self.validate()
        self.dialog.exec()
        result = self.gate.allowed
        if not result and self.worker and self.worker.isRunning():
            self.worker.wait()  # bounded HTTP request; never terminate the worker
        self.dialog.deleteLater()
        self.dialog = None
        return result

    def attach(self, window):
        self.window = window
        self.validate()

    def validate(self, activation_key=None):
        if self.worker and self.worker.isRunning():
            return
        if self.dialog:
            self.dialog.retry.setEnabled(False)
            self.dialog.message.setText("Checking license securely over the internet…")
        self.worker = ValidationThread(self.client, self.gate, activation_key, self)
        self.worker.checked.connect(self._checked)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_finished(self):
        worker = self.sender()
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()

    def _checked(self, decision):
        self.decision = decision
        self.gate.set_access(decision.allowed, decision.message)
        self._present()

    def _present(self):
        if not self.decision:
            return
        if self.decision.allowed:
            if self.dialog:
                self.dialog.accept()
                if self.window:
                    self.dialog.deleteLater()
                    self.dialog = None
            if self.window:
                self.window.statusBar().showMessage(self.decision.message)
            return
        if not self.gate.ready_to_lock:
            if self.window:
                self.window.statusBar().showMessage("License restriction pending; the current database operation is finishing.")
            return
        if self.window and self.dialog is None:
            self.dialog = LicenseDialog(self.window)
            self.dialog.retry_requested.connect(self.validate)
        if self.dialog:
            self.dialog.message.setText(self.decision.message)
            self.dialog.connection.setText("Validation status: " + self.decision.connectivity.replace("_", " ").lower())
            self.dialog.device.setText("Device ID: " + self.client.state["device_id"])
            self.dialog.retry.setEnabled(True)
            self.dialog.show()
            self.dialog.raise_()

    def _tick(self):
        self.ticks += 1
        if self.ticks % 15 == 0 and not (self.worker and self.worker.isRunning()):
            try:
                self._checked(self.client.decision())
            except StorageError:
                from licensing.client import Decision
                self._checked(Decision(False, "STORAGE_ERROR", "Secure licensing storage is unavailable. Contact support.", "STORAGE_ERROR"))
        elif self.decision and not self.decision.allowed:
            self._present()
        if self.ticks % self.period == 0:
            self.validate()

    def shutdown(self):
        self.timer.stop()
        if self.worker and self.worker.isRunning():
            self.worker.wait()
        try:
            self.client.close()
        except Exception:
            pass
