"""Step probe: find where the desktop acceptance script stalls."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("PHARMACY_DB", None)
os.environ.pop("QT_QPA_PLATFORM", None)

import faulthandler  # noqa: E402

faulthandler.dump_traceback_later(60, exit=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


log("imports start")
from PySide6.QtWidgets import QApplication
log("QtWidgets ok")
from PySide6.QtTest import QTest
log("QtTest ok")
from PySide6.QtCore import QTimer
log("QtCore ok")

app = QApplication(sys.argv)
log("QApplication created")
app.setStyle("Fusion")
log("style set")

from ui import theme
app.setStyleSheet(theme.stylesheet())
log("stylesheet applied")

from database.connection import init_database
from database import auth, financial_year
init_database()
log("init_database done")
auth.ensure_auth_schema()
log("auth schema done")
financial_year.ensure_default_financial_year()
log("financial year done")

from ui.main_window import PharmacyMainWindow
log("import main window")
window = PharmacyMainWindow()
log("main window constructed")
window.resize(1366, 768)
window.show()
window.raise_()
window.activateWindow()
app.processEvents()
log(f"window shown visible={window.isVisible()} {window.width()}x{window.height()}")

window.grab().save(str(ROOT / "temp" / "probe_window.png"))
log("screenshot saved")

window.close()
app.processEvents()
log("done")
