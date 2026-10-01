"""Real-desktop focus diagnostic for the Item -> Batch -> Qty keyboard chain.

Read-only: no Save/Hold is performed and no database row is written.
Keys are delivered to ``QApplication.focusWidget()``, i.e. exactly where a
physical keyboard would send them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("PHARMACY_DB", None)
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def pump(app, rounds: int = 4) -> None:
    for _ in range(rounds):
        app.processEvents()


def target(app):
    return QApplication.focusWidget()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from database.connection import init_database
    from database import auth, financial_year
    from ui import theme
    from ui.main_window import PharmacyMainWindow

    app.setStyleSheet(theme.stylesheet())
    init_database()
    auth.ensure_auth_schema()
    financial_year.ensure_default_financial_year()
    auth.session.user = {"id": 0, "username": "focus-probe",
                         "role": auth.ROLE_ADMIN, "is_active": 1}

    window = PharmacyMainWindow()
    window.resize(1366, 768)
    window.show()
    window.raise_()
    window.activateWindow()
    pump(app)
    window._on_menu_action("Sales", "New Bill")
    pump(app)

    page = window._stack.widget(window._page_map["Sales:New Bill"])
    entry = page._sale_panel._entry_bar
    item_line = entry.item_combo.lineEdit()
    batch_line = entry.batch_combo.lineEdit()

    item_line.setFocus()
    item_line.clear()
    QTest.mouseClick(item_line, Qt.LeftButton)
    pump(app)
    QTest.keyClicks(item_line, "BIO")
    pump(app)
    QTest.keyClick(item_line, Qt.Key_Down)
    pump(app)
    QTest.keyClick(item_line, Qt.Key_Return)
    pump(app)

    log(f"after item Enter: focus={type(target(app)).__name__} "
        f"batch_combo.hasFocus={entry.batch_combo.hasFocus()} "
        f"batch_line.hasFocus={batch_line.hasFocus()}")

    before = batch_line.text()
    t = target(app)
    QTest.keyClicks(t, "x")
    pump(app)
    log(f"keystroke sent to focus widget -> batch line: {before!r} -> {batch_line.text()!r}")

    batch_line.clear()
    batch_line.setText(before)
    QTest.keyClick(t, Qt.Key_Down)
    pump(app)
    log(f"Down on focus widget -> current batch idx {entry.batch_combo.currentIndex()} "
        f"popup visible {entry.batch_combo.completer().popup().isVisible()}")
    QTest.keyClick(t, Qt.Key_Return)
    pump(app)
    log(f"after batch Enter: focus={type(target(app)).__name__} "
        f"qty.hasFocus={entry.qty_edit.hasFocus()} "
        f"batch_data={entry.batch_combo.currentData()}")

    t2 = target(app)
    QTest.keyClick(t2, Qt.Key_Tab)
    pump(app)
    log(f"Tab -> focus={type(target(app)).__name__} "
        f"is_discount={target(app) is entry.discount_edit}")

    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
