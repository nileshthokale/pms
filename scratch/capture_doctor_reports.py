"""Directly capture crisp screenshots of Doctor's Reports."""

import os
import pathlib
import sys

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

from database.connection import init_database
from database import auth, financial_year
from screens.doctor_reports import DoctorwiseItemSalePage, DoctorwiseItemSaleDetailsPage
from ui import theme

init_database()
auth.ensure_auth_schema()
financial_year.ensure_default_financial_year()

ARTIFACT_DIR = pathlib.Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\5c72c679-6399-48c2-829a-79346dcbd088")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def capture(widget, filename):
    widget.show()
    app.processEvents()
    pixmap = widget.grab()
    out_path = ARTIFACT_DIR / filename
    pixmap.save(str(out_path), "PNG")
    print(f"Captured: {out_path}")
    return out_path


def main():
    # ── 1. Doctorwise Item Sale (Report 1) - Day Mode ─────────────────
    theme.theme_manager.set_mode("light")
    p1 = DoctorwiseItemSalePage()
    p1.resize(1280, 720)
    p1.from_date_edit.setDate(QDate(2026, 4, 1))
    p1.to_date_edit.setDate(QDate(2026, 10, 19))
    idx1 = p1.doctor_combo.findData(9)  # DR.K.N.GHORPADE
    if idx1 >= 0:
        p1.doctor_combo.setCurrentIndex(idx1)
    p1.generate_report()
    app.processEvents()

    capture(p1, "doctorwise_item_sale_day.png")
    if p1._pages:
        # Also capture the rendered report canvas directly
        capture(p1.viewer.canvas, "doctorwise_item_sale_canvas.png")
    p1.close()

    # ── 2. Doctorwise Item Sale Details (Report 2) - Day Mode ──────────
    p2 = DoctorwiseItemSaleDetailsPage()
    p2.resize(1280, 720)
    p2.from_date_edit.setDate(QDate(2026, 4, 1))
    p2.to_date_edit.setDate(QDate(2026, 10, 19))
    idx2 = p2.doctor_combo.findData(9)  # DR.K.N.GHORPADE
    if idx2 >= 0:
        p2.doctor_combo.setCurrentIndex(idx2)
    p2.generate_report()
    app.processEvents()

    capture(p2, "doctorwise_item_sale_details_day.png")
    if p2._pages:
        capture(p2.viewer.canvas, "doctorwise_item_sale_details_canvas.png")
    p2.close()

    # ── 3. Night Mode ─────────────────────────────────────────────────
    theme.theme_manager.set_mode("dark")
    p1_dark = DoctorwiseItemSalePage()
    p1_dark.resize(1280, 720)
    p1_dark.from_date_edit.setDate(QDate(2026, 4, 1))
    p1_dark.to_date_edit.setDate(QDate(2026, 10, 19))
    if idx1 >= 0:
        p1_dark.doctor_combo.setCurrentIndex(idx1)
    p1_dark.generate_report()
    app.processEvents()
    capture(p1_dark, "doctorwise_item_sale_night.png")
    p1_dark.close()

    p2_dark = DoctorwiseItemSaleDetailsPage()
    p2_dark.resize(1280, 720)
    p2_dark.from_date_edit.setDate(QDate(2026, 4, 1))
    p2_dark.to_date_edit.setDate(QDate(2026, 10, 19))
    if idx2 >= 0:
        p2_dark.doctor_combo.setCurrentIndex(idx2)
    p2_dark.generate_report()
    app.processEvents()
    capture(p2_dark, "doctorwise_item_sale_details_night.png")
    p2_dark.close()

    # Reset to light mode
    theme.theme_manager.set_mode("light")
    print("Done captures!")


if __name__ == "__main__":
    main()

