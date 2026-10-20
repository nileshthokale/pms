import os
import pathlib
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView
)
app = QApplication.instance() or QApplication(sys.argv)
from ui import components as ui
import ui.theme as theme

ARTIFACT_DIR = pathlib.Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\d4d9fb30-3b48-4c6f-b8e8-d32e0f0c8e59")

def capture_history_dialog(mode="light", out_name="08_history_dialog_day.png"):
    theme.theme_manager.set_mode(mode)
    p = theme.theme_manager.palette()
    dialog = QDialog()
    dialog.setWindowTitle("Recent Import History")
    dialog.resize(980, 420)
    dialog.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']};")

    dlg_layout = QVBoxLayout(dialog)
    dlg_layout.setContentsMargins(14, 12, 14, 12)
    dlg_layout.setSpacing(10)

    header_lbl = QLabel("Audit Log: Recent Master Data Imports")
    header_lbl.setFont(ui.readable_font(13, bold=True))
    dlg_layout.addWidget(header_lbl)

    history = [
        {"timestamp": "2026-10-20 11:30:00", "master_type": "Company", "filename": "companies.csv", "total_rows": 25, "inserted": 20, "updated": 5, "skipped": 0, "failed": 0},
        {"timestamp": "2026-10-20 11:15:00", "master_type": "Item", "filename": "medicines.xlsx", "total_rows": 150, "inserted": 140, "updated": 0, "skipped": 10, "failed": 0},
        {"timestamp": "2026-10-19 16:45:00", "master_type": "Supplier", "filename": "vendors.csv", "total_rows": 12, "inserted": 12, "updated": 0, "skipped": 0, "failed": 0},
    ]

    table = QTableWidget(len(history), 8)
    table.setHorizontalHeaderLabels([
        "Date/Time (UTC)", "Master Type", "Source Filename", "Total Rows",
        "Inserted", "Updated", "Skipped", "Failed",
    ])
    ui.style_data_table(table)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

    for row_index, record in enumerate(history):
        values = (
            record["timestamp"], record["master_type"], record["filename"],
            record["total_rows"], record["inserted"], record["updated"],
            record["skipped"], record["failed"],
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            table.setItem(row_index, column, item)

    dlg_layout.addWidget(table, 1)
    dialog.show()
    app.processEvents()
    pix = dialog.grab()
    pix.save(str(ARTIFACT_DIR / out_name), "PNG")
    dialog.close()
    print("Captured", out_name)

capture_history_dialog("light", "08_history_dialog_day.png")
capture_history_dialog("dark", "08_history_dialog_night.png")

