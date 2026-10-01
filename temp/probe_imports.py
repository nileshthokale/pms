"""Probe which import in the Counter Sale stack blocks."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("PHARMACY_DB", None)
os.environ.pop("QT_QPA_PLATFORM", None)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
log("QApplication ready")

start = time.perf_counter()
import screens
log(f"import screens took {time.perf_counter() - start:.1f}s")

start = time.perf_counter()
import ui.main_window  # noqa: E402
log(f"import ui.main_window took {time.perf_counter() - start:.1f}s")
