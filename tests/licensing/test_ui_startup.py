"""Exercise asynchronous startup validation and the normal window on a clone."""
from pathlib import Path
import shutil

from tests.licensing.conftest import ROOT
from licensing.gate import install_gate


def test_startup_worker_and_existing_window_with_verified_license(activated, monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    source = ROOT / "temp/license_validation/pharmacy_clone.db"
    target = tmp_path / "licensed_startup.db"
    shutil.copyfile(source, target)
    monkeypatch.setenv("PHARMACY_DB", str(target))
    monkeypatch.setenv("PHARMACY_TEST_PROTECTED_DB", str(ROOT / "data/pharmacy.db"))
    monkeypatch.setenv("PHARMACY_TEST_SAFE_DB", str(target))
    from PySide6.QtWidgets import QApplication
    from licensing.qt import LicenseController
    from database import auth
    from ui.main_window import PharmacyMainWindow
    app = QApplication.instance() or QApplication([])
    controller = LicenseController(activated["client"], app)
    try:
        assert controller.startup()
        assert controller.gate.allowed
        window = PharmacyMainWindow()
        assert window._page_map
        window.show()
        app.processEvents()
        controller.window = window
        controller._checked(activated["client"].decision())
        assert controller.dialog is None
        window.close()
        window.deleteLater()
    finally:
        controller.shutdown()
        controller.deleteLater()
        app.processEvents()
        install_gate(None)
