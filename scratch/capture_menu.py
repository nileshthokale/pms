"""Capture the Reports menu and Doctor's Reports submenu rendered onto a QPixmap."""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QMenu

app = QApplication.instance() or QApplication(sys.argv)
app.setStyle("Fusion")

from database.connection import init_database
from database import auth, financial_year
from ui.navigation_bar import NavigationBar
import ui.theme as theme

init_database()
auth.ensure_auth_schema()
financial_year.ensure_default_financial_year()

ARTIFACT_DIR = pathlib.Path(r"C:\Users\Nilesh\.gemini\antigravity\brain\5c72c679-6399-48c2-829a-79346dcbd088")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

nav = NavigationBar()
nav.show()
app.processEvents()

# Find Reports button
reports_btn = next(
    btn for btn in nav.findChildren(QPushButton)
    if btn.objectName() == "NavButton" and btn.text() == "Reports"
)
reports_menu = reports_btn.menu()
doc_action = next(a for a in reports_menu.actions() if a.text() == "Doctor's Reports")
sub_menu = doc_action.menu()

reports_menu.adjustSize()
sub_menu.adjustSize()

rm_size = reports_menu.sizeHint()
sm_size = sub_menu.sizeHint()

# Create combined canvas
total_w = rm_size.width() + sm_size.width() + 10
total_h = max(rm_size.height(), sm_size.height() + 80)

pixmap = QPixmap(total_w, total_h)
pixmap.fill(QColor(0, 0, 0, 0))

painter = QPainter(pixmap)
reports_menu.render(painter, QPoint(0, 0))

# Find Y offset of doc_action
act_geom = reports_menu.actionGeometry(doc_action)
sub_y = act_geom.top()
sub_menu.render(painter, QPoint(rm_size.width() - 2, sub_y))
painter.end()

menu_path = ARTIFACT_DIR / "doctors_reports_menu.png"
pixmap.save(str(menu_path), "PNG")
print(f"Captured: {menu_path}")

nav.close()
sys.exit(0)
