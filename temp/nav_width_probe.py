"""Measure the real content width available to Counter Sale at 1366."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QHBoxLayout, QMainWindow, QWidget,
)

app = QApplication(sys.argv)

from ui.navigation_bar import NavigationBar  # noqa: E402

for w, h in ((1366, 768), (1600, 900), (1920, 1080)):
    win = QMainWindow()
    container = QWidget()
    lay = QHBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    nav = NavigationBar()
    filler = QWidget()
    lay.addWidget(nav)
    lay.addWidget(filler, 1)
    win.setCentralWidget(container)
    win.resize(w, h)
    win.show()
    app.processEvents()
    print(f"{w}x{h}: nav={nav.width()} content={filler.width()}")
    win.close()
    app.processEvents()
