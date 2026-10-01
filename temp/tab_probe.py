"""Offscreen focus-chain / tab-order probe for the counter-sale entry bar.

Read-only against the production DB: everything runs on the unit-test DB.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def log(msg: str = "") -> None:
    print(msg, flush=True)


def describe(w) -> str:
    if w is None:
        return "None"
    return f"{type(w).__name__}"


def main() -> int:
    from unittest import mock
    from PySide6.QtWidgets import QMessageBox

    captured = []
    patcher = mock.patch.multiple(
        QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
        critical=mock.DEFAULT, question=mock.DEFAULT,
    )
    patched = patcher.start()

    def record(kind):
        def _rec(*args, **kwargs):
            captured.append((kind, args[1] if len(args) > 1 else args[0] if args else ""))
            print(f"    [message box] {kind}: {captured[-1][1]}", flush=True)
            if kind == "question":
                return QMessageBox.Yes
            return QMessageBox.Ok
        return _rec

    for name, created in patched.items():
        created.side_effect = record(name)

    from test_counter_sale_input import _DBBase

    class Probe(_DBBase):
        pass

    Probe.setUpClass()
    case = Probe(methodName="runTest")
    case.setUp()
    case.addCleanup(lambda: None)

    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QTimer

    def _rescue():
        modal = app.activeModalWidget()
        if modal is not None:
            print(f"    [watchdog] closing modal {type(modal).__name__}", flush=True)
            modal.close()

    watchdog = QTimer()
    watchdog.timeout.connect(_rescue)
    watchdog.start(3000)

    from screens.counter_sale import CounterSalePage

    page = CounterSalePage()
    page.resize(1366, 708)
    page.show()
    app.processEvents()

    entry = page._sale_panel._entry_bar
    item = entry.item_combo
    batch = entry.batch_combo

    log("== focus proxies ==")
    for w in (item, item.lineEdit(), batch, batch.lineEdit(),
              entry.qty_edit, entry.discount_edit, entry.add_btn):
        proxy = w.focusProxy()
        log(f"  {describe(w):16} focusPolicy={w.focusPolicy()!s:14} "
            f"proxy={describe(proxy)}")

    log("== focus chain starting at item combo (focusable only) ==")
    w = item
    names = []
    for _ in range(40):
        if w.focusPolicy() != Qt.NoFocus:
            names.append(describe(w))
        w = w.nextInFocusChain()
        if w is item:
            break
    log("  " + " -> ".join(names))

    log("== Tab simulation from item combo (popup hidden) ==")
    item.lineEdit().clear()
    item.completer().popup().hide()
    item.setFocus()
    app.processEvents()
    for i in range(7):
        focus_obj = QGuiApplication.focusObject()
        log(f"  step {i}: focusWidget={describe(app.focusWidget())} "
            f"focusObject={describe(focus_obj)}")
        from PySide6.QtTest import QTest
        QTest.keyClick(app.focusWidget(), Qt.Key_Tab)
        app.processEvents()

    log("== chain from qty ==")
    entry.qty_edit.setFocus()
    app.processEvents()
    for i in range(5):
        log(f"  {describe(app.focusWidget())}")
        from PySide6.QtTest import QTest
        QTest.keyClick(app.focusWidget(), Qt.Key_Tab)
        app.processEvents()

    log("== full keyboard chain (keys sent to focusObject) ==")
    from PySide6.QtTest import QTest

    def press(key):
        obj = QGuiApplication.focusObject()
        log(f"    -> {describe(obj)} key={key}")
        QTest.keyClick(obj, key, Qt.NoModifier)
        app.processEvents()

    def state(tag):
        log(f"  [{tag}] focusWidget={describe(app.focusWidget())} "
            f"item={item.currentData()} line={item.lineEdit().text()!r} "
            f"batch={batch.currentData()} "
            f"itemPopup={item.completer().popup().isVisible()} "
            f"batchPopup={batch.completer().popup().isVisible()} "
            f"qtyFocus={entry.qty_edit.hasFocus()}")

    item.setFocus()
    item.lineEdit().clear()
    QTest.mouseClick(item.lineEdit(), Qt.LeftButton)
    app.processEvents()
    QTest.keyClicks(QGuiApplication.focusObject(), "Test")
    app.processEvents()
    state("typed")
    press(Qt.Key_Down)
    state("down")
    press(Qt.Key_Return)
    state("enter (item)")
    press(Qt.Key_Down)
    state("batch down")
    press(Qt.Key_Return)
    state("batch enter")
    QTest.keyClicks(QGuiApplication.focusObject(), "1")
    app.processEvents()
    state("qty typed")
    press(Qt.Key_Tab)
    state("tab to discount")
    press(Qt.Key_Return)
    state("enter -> add")
    log(f"  rows in bill table = {page._sale_panel._table.rowCount()}")
    log(f"  qty={entry.qty_edit.text()!r} discount={entry.discount_edit.text()!r}")

    page.hide()
    page.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
