"""Real-desktop focus/key-routing diagnostic.

Uses ``QGuiApplication.focusObject()`` — the exact object a physical
keyboard targets — instead of sending events directly to a widget.

Read-only: nothing is saved, no database row is written.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("PHARMACY_DB", None)
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import Qt, QObject  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


def pump(app, rounds: int = 5) -> None:
    for _ in range(rounds):
        app.processEvents()


def key(app, code, text: str = "") -> None:
    """Deliver a key exactly where a physical keyboard would."""
    obj = QGuiApplication.focusObject()
    event = Qt.QKeyEvent if False else None  # placeholder (unused)
    from PySide6.QtGui import QKeyEvent
    ev = QKeyEvent(QEvent_Type_KeyPress, code, Qt.NoModifier, text)
    QTest.keyClick(obj, code, Qt.NoModifier)
    pump(app)


def QEvent_Type_KeyPress():
    from PySide6.QtCore import QEvent
    return QEvent.KeyPress


def describe(obj) -> str:
    if obj is None:
        return "None"
    name = type(obj).__name__
    extra = ""
    if isinstance(obj, QWidget):
        extra = f" hasFocus={obj.hasFocus()}"
    return f"{name}{extra}"


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
    item_popup = entry.item_combo.completer().popup()
    batch_popup = entry.batch_combo.completer().popup()

    def state(tag: str) -> None:
        log(f"  [{tag}] focusWidget={describe(app.focusWidget())} "
            f"focusObject={describe(QGuiApplication.focusObject())} "
            f"itemPopup={item_popup.isVisible()} batchPopup={batch_popup.isVisible()}")
        log(f"      item_line={item_line.text()!r} "
            f"item_idx={entry.item_combo.currentIndex()} "
            f"item_data={entry.item_combo.currentData()} "
            f"popup_idx={item_popup.currentIndex().row()} "
            f"popup_rows={item_popup.model().rowCount()}")

    item_line.setFocus()
    item_line.clear()
    QTest.mouseClick(item_line, Qt.LeftButton)
    pump(app)
    state("item field clicked")

    QTest.keyClicks(QGuiApplication.focusObject(), "BIO")
    pump(app)
    state("typed BIO")

    QTest.keyClick(QGuiApplication.focusObject(), Qt.Key_Down)
    pump(app)
    state("ArrowDown")

    QTest.keyClick(QGuiApplication.focusObject(), Qt.Key_Return)
    pump(app)
    log("  after item Enter:")
    state("item selected")
    log(f"  batch popup visible={batch_popup.isVisible()} "
        f"batch_combo.currentData={entry.batch_combo.currentData()} "
        f"batch_line.hasFocus={batch_line.hasFocus()}")

    QTest.keyClick(QGuiApplication.focusObject(), Qt.Key_Down)
    pump(app)
    state("batch ArrowDown")
    log(f"  batch index={entry.batch_combo.currentIndex()} "
        f"text={entry.batch_combo.currentText()[:40]!r}")

    QTest.keyClick(QGuiApplication.focusObject(), Qt.Key_Return)
    pump(app)
    log("  after batch Enter:")
    state("batch selected")
    log(f"  qty.hasFocus={entry.qty_edit.hasFocus()} "
        f"batch={entry.batch_combo.currentText()[:40]!r} "
        f"mrp={entry.mrp_edit.text()} avail={entry.stock_edit.text()}")

    QTest.keyClick(QGuiApplication.focusObject(), Qt.Key_Tab)
    pump(app)
    state("Tab")

    # Type the quantity wherever focus now is and continue the chain.
    QTest.keyClicks(QGuiApplication.focusObject(), "1")
    pump(app)
    log(f"  qty text={entry.qty_edit.text()!r}")
    QTest.keyClick(QGuiApplication.focusObject(), Qt.Key_Tab)
    pump(app)
    state("Tab 2")
    QTest.keyClick(QGuiApplication.focusObject(), Qt.Key_Return)
    pump(app)
    log(f"  rows after Enter in discount={page._sale_panel._table.rowCount()}")

    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
