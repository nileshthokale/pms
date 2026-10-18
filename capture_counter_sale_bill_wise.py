"""Capture crisp screenshots of Counter Sale in Bill Wise mode for Night and Day modes with system fonts."""

import os
import pathlib
import sys

# Do not force offscreen so Windows TrueType fonts render cleanly
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

from database import auth
from database.connection import get_connection, init_database
from screens.counter_sale import CounterSalePage
from ui import theme

init_database()
auth.ensure_auth_schema()
if auth.user_count() == 0:
    auth.create_first_admin("admin", "admin-pass-1")
auth.session.user = {"id": 1, "username": "admin", "role": auth.ROLE_ADMIN, "is_active": 1}

ARTIFACT_DIR = pathlib.Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\e3b761b3-55c7-40fb-98cd-6e0b36ed2722")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def capture(widget, filename):
    widget.show()
    app.processEvents()
    pixmap = widget.grab()
    out_path = ARTIFACT_DIR / filename
    pixmap.save(str(out_path), "PNG")
    print(f"Captured: {out_path}")
    return out_path


def capture_bill_wise(mode_suffix=""):
    cs_page = CounterSalePage()
    cs_page.resize(1280, 720)
    cs_page._hist_bill_mode.setChecked(True)
    # Historical date with both named and empty patient records
    cs_page._hist_date.setDate(QDate(2015, 4, 1))
    cs_page._refresh_history()
    app.processEvents()

    # Capture full Counter Sale screen
    capture(cs_page, f"counter_sale_bill_wise{mode_suffix}.png")

    # Capture table region close-up
    capture(cs_page._hist_table, f"counter_sale_bill_wise_table{mode_suffix}.png")
    cs_page.close()


def main():
    # 1. Dark / Night Mode
    theme.theme_manager.set_mode("dark")
    app.processEvents()
    capture_bill_wise("_night")
    capture_bill_wise("")  # default name

    # 2. Light / Day Mode
    theme.theme_manager.set_mode("light")
    app.processEvents()
    capture_bill_wise("_day")

    print("Bill Wise screenshots (Night and Day) captured successfully!")


if __name__ == "__main__":
    main()

