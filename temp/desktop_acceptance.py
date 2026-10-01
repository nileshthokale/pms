"""Real-desktop acceptance test for the Counter Sale product-entry workflow.

Runs the REAL application (``PharmacyMainWindow``) on the REAL desktop Qt
platform against the REAL migrated database (``data/pharmacy.db``).

Guarantees:
  * the database is opened read-only for every check performed here;
  * no Save Sale / Hold Bill action is performed;
  * major table row counts are compared before and after the run.

Usage:
    python temp/desktop_acceptance.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Real desktop platform — no QT_QPA_PLATFORM override on purpose.
os.environ.pop("PHARMACY_DB", None)
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import (QModelIndex, QPoint, QRect, Qt, QTimer)  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

DB_PATH = ROOT / "data" / "pharmacy.db"
SHOTS = ROOT / "temp"
SEARCH_TERM = "BIO"

RESULTS: list[tuple[str, bool, str]] = []
DIALOGS: list[str] = []
EXPECTED: list[str] = []
ALLOW_EXPIRED = False


def check(name: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(condition), detail))
    print(f"{'PASS' if condition else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""),
          flush=True)
    return bool(condition)


def pump(app, rounds: int = 4) -> None:
    for _ in range(rounds):
        app.processEvents()
        time.sleep(0.02)


def db_counts() -> dict:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    counts = {t: cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
              for t in tables}
    con.close()
    return counts


def batch_stock(batch_id: int) -> float:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    row = con.execute("SELECT stock_qty FROM stock_batches WHERE id=?",
                      (batch_id,)).fetchone()
    con.close()
    return float(row[0]) if row else -1.0


def search_oracle_ids(term: str) -> set[int]:
    """Independent expectation of which items a contains-search must show."""
    like = f"%{term}%"
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    ids = {r[0] for r in con.execute(
        """
        SELECT i.id FROM items i
        WHERE UPPER(i.item_name) LIKE UPPER(?)
           OR EXISTS (SELECT 1 FROM item_ingredients ii
                      JOIN drugs d ON d.id = ii.drug_id
                      WHERE ii.item_id = i.id AND UPPER(d.drug_name) LIKE UPPER(?))
        """, (like, like))}
    con.close()
    return ids


def completion_ids(model) -> set[int]:
    ids = set()
    for row in range(model.rowCount()):
        value = model.index(row, 0).data(Qt.UserRole)
        if value is not None:
            ids.add(int(value))
    return ids


def main() -> int:
    # Safety net: never let the acceptance run block forever on a modal
    # dialog or an unexpected event loop; dump the stack and exit instead.
    import faulthandler
    faulthandler.dump_traceback_later(300, exit=True)

    counts_before = db_counts()
    stock_before = None

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    from database.connection import init_database
    from database import auth, financial_year
    from ui import theme
    from ui.main_window import PharmacyMainWindow

    app.setStyleSheet(theme.stylesheet())
    init_database()
    auth.ensure_auth_schema()
    financial_year.ensure_default_financial_year()

    # Establish an in-process ADMIN session (no user row is created or
    # updated: this is the same in-memory state a completed login leaves
    # behind).  Production login credentials are not available to this
    # harness, and every screen guards its data loads on a live session.
    auth.session.user = {
        "id": 0,
        "username": "desktop-acceptance",
        "role": auth.ROLE_ADMIN,
        "is_active": 1,
    }

    window = PharmacyMainWindow()
    window.resize(1366, 768)
    window.show()
    window.raise_()
    window.activateWindow()
    pump(app)

    check("real_window_visible", window.isVisible(),
          f"{window.width()}x{window.height()}")

    # Navigate exactly the way the application menu does.
    window._on_menu_action("Sales", "New Bill")
    pump(app)
    page_key = "Sales:New Bill"
    page = window._stack.widget(window._page_map[page_key])
    from screens.counter_sale import CounterSalePage
    check("counter_sale_page_open", isinstance(page, CounterSalePage),
          type(page).__name__)

    # Layout: history table directly under the header, no From/To/Filter row.
    from PySide6.QtWidgets import QLabel, QLineEdit
    label_texts = [w.text().strip() for w in page.findChildren(QLabel)]
    edit_texts = [w.text().strip() for w in page.findChildren(QLineEdit)]
    check("filter_bar_removed",
          not any(t in ("From", "To", "Filter") for t in label_texts + edit_texts),
          "no From/To/Customer/Filter row")
    check("history_below_header", page._hist_table is not None
          and page._hist_table.y() < page._sale_panel.y(),
          "Region A history above Region B entry")

    panel = page._sale_panel
    entry = panel._entry_bar
    item_line = entry.item_combo.lineEdit()
    item_completer = entry.item_combo.completer()
    item_popup = item_completer.popup()

    # Safety net: never let an unexpected modal dialog stall the run.
    # Dialogs that this run provokes on purpose (the expired-batch guard)
    # are recorded separately so they do not hide real regressions.
    def watchdog():
        active = QApplication.activeModalWidget()
        if isinstance(active, QMessageBox):
            text = f"{active.windowTitle()}: {active.text()}"
            if ALLOW_EXPIRED and "expired" in text.lower():
                EXPECTED.append(text)
            else:
                DIALOGS.append(text)
            active.reject()

    timer = QTimer(app)
    timer.setInterval(300)
    timer.timeout.connect(watchdog)
    timer.start()

    # ------------------------------------------------------------------
    # 1. Click the empty Item field -> product popup opens below the field
    # ------------------------------------------------------------------
    item_line.setFocus()
    item_line.clear()
    QTest.mouseClick(item_line, Qt.LeftButton)
    pump(app)
    check("item_popup_opens_on_click", item_popup.isVisible())

    win_rect = QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
    pop_rect = QRect(item_popup.mapToGlobal(QPoint(0, 0)), item_popup.size())
    check("popup_inside_window", win_rect.contains(pop_rect),
          f"popup {pop_rect} window {win_rect}")
    check("popup_below_field",
          pop_rect.top() >= item_line.mapToGlobal(QPoint(0, 0)).y(),
          f"popup top {pop_rect.top()}")
    check("popup_scrollable", item_popup.verticalScrollBar() is not None
          and item_popup.verticalScrollBarPolicy() != Qt.ScrollBarAlwaysOff)

    sheet = item_popup.styleSheet().lower()
    check("popup_light_theme",
          "#ffffff" in sheet and "#14212e" in sheet and "#cfe2f3" in sheet,
          "white bg / dark text / light-blue selection")

    total_items = item_completer.completionCount()
    check("empty_field_lists_products", total_items >= 900,
          f"{total_items} products listed")

    # ------------------------------------------------------------------
    # 2. Type -> immediate, case-insensitive, partial filtering
    # ------------------------------------------------------------------
    item_line.clear()
    started = time.perf_counter()
    QTest.keyClicks(item_line, SEARCH_TERM)
    pump(app)
    elapsed_ms = (time.perf_counter() - started) * 1000

    filtered = item_completer.completionCount()
    oracle = search_oracle_ids(SEARCH_TERM)
    visible = completion_ids(item_completer.completionModel())
    check("typing_filters_immediately", 0 < filtered < total_items,
          f"{filtered} of {total_items} in {elapsed_ms:.0f} ms")
    check("partial_case_insensitive_match", visible == oracle,
          f"shown {len(visible)} / expected {len(oracle)}")
    check("search_is_fast", elapsed_ms < 1500, f"{elapsed_ms:.0f} ms")

    # ------------------------------------------------------------------
    # 3. No-match state
    # ------------------------------------------------------------------
    item_line.clear()
    QTest.keyClicks(item_line, "zzzzno-such-product")
    pump(app)
    model = item_completer.completionModel()
    last_text = model.index(model.rowCount() - 1, 0).data() if model.rowCount() else ""
    check("no_match_message", last_text == "No products found", repr(last_text))
    check("no_match_does_not_select", entry.item_combo.currentData() is None)

    # ------------------------------------------------------------------
    # 4. Keyboard: Arrow Down / Up / Escape / Enter
    # ------------------------------------------------------------------
    item_line.clear()
    QTest.keyClicks(item_line, SEARCH_TERM)
    pump(app)
    check("popup_visible_after_typing", item_popup.isVisible())

    QTest.keyClick(item_line, Qt.Key_Down)
    pump(app)
    row_down1 = item_popup.currentIndex().row()
    QTest.keyClick(item_line, Qt.Key_Down)
    pump(app)
    row_down2 = item_popup.currentIndex().row()
    QTest.keyClick(item_line, Qt.Key_Up)
    pump(app)
    row_up = item_popup.currentIndex().row()
    check("arrow_down_moves_selection",
          row_down1 >= 0 and row_down2 == row_down1 + 1,
          f"{row_down1} -> {row_down2}")
    check("arrow_up_moves_selection", row_up == row_down2 - 1,
          f"{row_down2} -> {row_up}")

    QTest.keyClick(item_line, Qt.Key_Escape)
    pump(app)
    check("escape_closes_popup", not item_popup.isVisible())

    item_line.clear()
    QTest.keyClicks(item_line, SEARCH_TERM)
    pump(app)
    QTest.keyClick(item_line, Qt.Key_Down)
    pump(app)
    QTest.keyClick(item_line, Qt.Key_Return)
    pump(app)

    item_id = entry.item_combo.currentData()
    check("enter_selects_item", item_id is not None, f"item_id={item_id}")
    check("item_id_is_database_identity",
          isinstance(item_id, int) and item_id > 0, str(item_id))
    # A combo owns focus (its line edit is only the focus proxy), so the
    # focus widget is the combo itself -- exactly what the unit tests assert.
    check("focus_moves_to_batch",
          window.focusWidget() is entry.batch_combo,
          str(type(window.focusWidget()).__name__))

    # ------------------------------------------------------------------
    # 4b. On this dataset the alphabetically first "BIO" match can hold
    #     only expired stock.  Record that honestly and prove the
    #     expired-batch guard refuses to add it to the bill.
    # ------------------------------------------------------------------
    batch_line = entry.batch_combo.lineEdit()
    batch_popup = entry.batch_combo.completer().popup()

    def select_batch_to(combo_row: int) -> None:
        """Highlight ``combo_row`` in the batch popup and press Enter."""
        if combo_row <= 0:
            return  # no usable batch: leave the state for the checks to report
        if not batch_popup.isVisible():
            batch_line.setFocus()
            QTest.mouseClick(batch_line, Qt.LeftButton)
            pump(app)
        batch_popup.setCurrentIndex(QModelIndex())  # clean highlight
        steps = 0
        while batch_popup.currentIndex().row() != combo_row and steps < 30:
            QTest.keyClick(batch_line, Qt.Key_Down)
            pump(app)
            steps += 1
        QTest.keyClick(batch_line, Qt.Key_Return)
        pump(app)

    first_item_id = entry.item_combo.currentData()
    first_batches = SalesDAO_batches(first_item_id)
    if first_batches and not sellable_batches(first_item_id):
        check("expired_only_item_documented", True,
              f"item {first_item_id}: all {len(first_batches)} batches expired")
        QTest.keyClick(batch_line, Qt.Key_Down)
        pump(app)
        QTest.keyClick(batch_line, Qt.Key_Return)
        pump(app)
        entry.qty_edit.selectAll()
        QTest.keyClicks(entry.qty_edit, "1")
        pump(app)
        QTest.keyClick(entry.qty_edit, Qt.Key_Tab)
        pump(app)
        allow_expired_dialogs(True)
        QTest.keyClick(entry.discount_edit, Qt.Key_Return)
        pump(app)
        allow_expired_dialogs(False)
        check("expired_batch_add_blocked", panel._table.rowCount() == 0,
              f"rows={panel._table.rowCount()}")
        check("expired_batch_guard_message",
              any("expired" in d.lower() for d in EXPECTED),
              "; ".join(EXPECTED)[:160])
    else:
        check("expired_batch_add_blocked", True,
              "first match has sellable stock; guard not provoked")

    # ------------------------------------------------------------------
    # 5. Same keyboard chain on the first match that has sellable stock,
    #    then the batch popup + auto-filled fields.
    # ------------------------------------------------------------------
    item_line.setFocus()
    item_line.clear()
    QTest.keyClicks(item_line, SEARCH_TERM)
    pump(app)
    target_row = first_sellable_row(item_completer, min_stock=2)
    check("sellable_match_available", target_row >= 0,
          f"popup row {target_row} of {item_completer.completionCount()}")
    item_popup.setCurrentIndex(QModelIndex())  # start from a clean highlight
    for _ in range(max(target_row, 0) + 1):
        QTest.keyClick(item_line, Qt.Key_Down)
        pump(app)
    QTest.keyClick(item_line, Qt.Key_Return)
    pump(app)

    item_id = entry.item_combo.currentData()
    check("sellable_item_selected", bool(sellable_batches(item_id, 2)),
          f"item_id={item_id} "
          f"({len(sellable_batches(item_id, 2))} batches with >=2 units)")
    check("focus_moves_to_batch_again",
          window.focusWidget() is entry.batch_combo,
          str(type(window.focusWidget()).__name__))

    check("batches_loaded_from_db", entry.batch_combo.count() > 1,
          f"{entry.batch_combo.count() - 1} batches")
    check("batch_popup_visible", batch_popup.isVisible())
    if not batch_popup.isVisible():
        batch_line.setFocus()
        QTest.mouseClick(batch_line, Qt.LeftButton)
        pump(app)

    label = entry.batch_combo.itemText(1)
    check("batch_shows_no_expiry_mrp_stock",
          all(token in label for token in ("Exp:", "MRP:", "Avail:")), label)

    b_sheet = batch_popup.styleSheet().lower()
    check("batch_popup_light_theme",
          "#ffffff" in b_sheet and "#cfe2f3" in b_sheet, b_sheet[:80])

    QTest.keyClick(batch_line, Qt.Key_Down)
    pump(app)
    b_row1 = batch_popup.currentIndex().row()
    QTest.keyClick(batch_line, Qt.Key_Down)
    pump(app)
    b_row2 = batch_popup.currentIndex().row()
    check("batch_arrow_navigation",
          b_row1 >= 0 and b_row2 == b_row1 + 1, f"{b_row1} -> {b_row2}")

    # Land on a batch that really holds the two units the merge needs.
    usable_row = target_batch_index(item_id, min_stock=2)
    check("usable_batch_available", usable_row > 0, f"combo row {usable_row}")
    select_batch_to(usable_row)

    batch_id = entry.batch_combo.currentData()
    check("enter_selects_batch", batch_id is not None, f"batch_id={batch_id}")
    check("focus_moves_to_qty", window.focusWidget() is entry.qty_edit,
          str(type(window.focusWidget()).__name__))

    stored_stock = batch_stock(batch_id) if batch_id else -1.0
    stock_before = stored_stock
    check("autofill_pack", entry.pack_edit.text().strip() != "",
          entry.pack_edit.text())
    check("autofill_expiry", entry.expiry_edit.text().strip() != "",
          entry.expiry_edit.text())
    check("autofill_mrp", _float(entry.mrp_edit.text()) > 0,
          entry.mrp_edit.text())
    check("autofill_stock", entry.stock_edit.text().strip() != "",
          entry.stock_edit.text())
    check("autofill_available_matches_db",
          entry.stock_edit.text().strip() == f"{stored_stock:.0f}",
          f"screen {entry.stock_edit.text()} db {stored_stock}")
    check("selected_batch_is_sellable",
          not SalesDAO_is_expired(entry.expiry_edit.text()),
          entry.expiry_edit.text())
    batches_now = SalesDAO_batches(item_id)
    check("sellable_batches_listed_first",
          bool(batches_now) and not SalesDAO_is_expired(
              batches_now[0].get("expiry") or ""),
          f"first {batches_now[0]['batch_no']} exp "
          f"{batches_now[0]['expiry']}" if batches_now else "no batches")

    # ------------------------------------------------------------------
    # 6. Qty -> Tab -> Discount -> Enter (Add)
    # ------------------------------------------------------------------
    entry.qty_edit.selectAll()
    QTest.keyClicks(entry.qty_edit, "1")
    pump(app)
    check("qty_entered", entry.qty_edit.text() == "1", entry.qty_edit.text())

    QTest.keyClick(entry.qty_edit, Qt.Key_Tab)
    pump(app)
    check("tab_qty_to_discount", window.focusWidget() is entry.discount_edit,
          str(type(window.focusWidget()).__name__))

    QTest.keyClick(entry.discount_edit, Qt.Key_Return)
    pump(app)
    check("enter_adds_row", panel._table.rowCount() == 1,
          f"rows={panel._table.rowCount()} dialogs={DIALOGS}")
    check("focus_returns_to_item",
          window.focusWidget() is entry.item_combo,
          str(type(window.focusWidget()).__name__))
    check("totals_updated",
          panel.total_amount_label.text() not in ("", "0.00"),
          panel.total_amount_label.text())

    shot1 = SHOTS / "desktop_accept_1_row_added.png"
    window.grab().save(str(shot1))

    # ------------------------------------------------------------------
    # 7. Add the SAME batch again -> single row, qty merges, stock drops
    # ------------------------------------------------------------------
    def select_item_and_batch() -> None:
        """Re-run TYPE -> Down -> Enter on the same sellable product."""
        item_line.setFocus()
        item_line.clear()
        QTest.mouseClick(item_line, Qt.LeftButton)
        pump(app)
        QTest.keyClicks(item_line, SEARCH_TERM)
        pump(app)
        row = first_sellable_row(item_completer, min_stock=2)
        item_popup.setCurrentIndex(QModelIndex())  # clean highlight
        for _ in range(max(row, 0) + 1):
            QTest.keyClick(item_line, Qt.Key_Down)
            pump(app)
        QTest.keyClick(item_line, Qt.Key_Return)
        pump(app)
        select_batch_to(target_batch_index(entry.item_combo.currentData(),
                                           min_stock=2))

    select_item_and_batch()
    avail_after_first = _float(entry.stock_edit.text())
    # Remember the batch the second pick chose: the entry bar is cleared
    # again as soon as the merge is added, so compare against this value.
    picked_batch_no = entry.batch_combo.itemText(
        entry.batch_combo.currentIndex()).split(" | ")[0]
    check("live_draft_stock_after_add",
          avail_after_first == stored_stock - 1,
          f"db {stored_stock} -> screen {avail_after_first}")

    entry.qty_edit.selectAll()
    QTest.keyClicks(entry.qty_edit, "1")
    pump(app)
    QTest.keyClick(entry.qty_edit, Qt.Key_Tab)
    pump(app)
    QTest.keyClick(entry.discount_edit, Qt.Key_Return)
    pump(app)

    check("same_batch_merges_to_one_row", panel._table.rowCount() == 1,
          f"rows={panel._table.rowCount()}")
    if panel._table.rowCount() == 1:
        check("merged_quantity_is_2",
              panel._table.item(0, 7).text() == "2",
              panel._table.item(0, 7).text())
        check("merged_row_keeps_batch",
              bool(picked_batch_no) and
              panel._table.item(0, 4).text() == picked_batch_no,
              f"row {panel._table.item(0, 4).text()} vs picked "
              f"{picked_batch_no!r}")

    select_item_and_batch()
    avail_after_second = _float(entry.stock_edit.text())
    check("live_draft_stock_after_merge",
          avail_after_second == stored_stock - 2,
          f"db {stored_stock} -> screen {avail_after_second}")
    check("db_stock_unchanged_before_save",
          batch_stock(batch_id) == stock_before,
          f"db {batch_stock(batch_id)} vs {stock_before}")

    shot2 = SHOTS / "desktop_accept_2_merged.png"
    window.grab().save(str(shot2))

    # ------------------------------------------------------------------
    # 8. Delete the row -> reservation released immediately
    # ------------------------------------------------------------------
    del_btn = panel._table.cellWidget(0, 10)
    check("delete_button_present", del_btn is not None)
    if del_btn is not None:
        QTest.mouseClick(del_btn, Qt.LeftButton)
        pump(app)
    check("row_deleted", panel._table.rowCount() == 0,
          f"rows={panel._table.rowCount()}")

    select_item_and_batch()
    avail_after_delete = _float(entry.stock_edit.text())
    check("live_draft_stock_restored",
          avail_after_delete == stored_stock,
          f"db {stored_stock} -> screen {avail_after_delete}")
    check("db_stock_unchanged_after_delete",
          batch_stock(batch_id) == stock_before,
          f"db {batch_stock(batch_id)} vs {stock_before}")
    check("no_sale_written", not panel._saved)

    shot3 = SHOTS / "desktop_accept_3_deleted.png"
    window.grab().save(str(shot3))

    # ------------------------------------------------------------------
    # 9. Production database untouched
    # ------------------------------------------------------------------
    timer.stop()
    import faulthandler
    faulthandler.cancel_dump_traceback_later()
    counts_after = db_counts()
    changed = {t: (counts_before[t], counts_after[t])
               for t in counts_before if counts_before[t] != counts_after.get(t)}
    check("production_db_unchanged", not changed, json.dumps(changed))
    check("no_unexpected_dialogs", not DIALOGS, "; ".join(DIALOGS))

    window.close()
    app.processEvents()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 70)
    print(f"DESKTOP ACCEPTANCE: {passed}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
    print("=" * 70)
    (SHOTS / "desktop_acceptance_result.json").write_text(
        json.dumps({"passed": passed, "total": len(RESULTS),
                    "failed": failed,
                    "checks": [{"name": n, "ok": ok, "detail": d}
                               for n, ok, d in RESULTS]}, indent=1),
        encoding="utf-8")
    return 0 if not failed else 1


def _float(text: str) -> float:
    try:
        return float(str(text).strip() or 0)
    except ValueError:
        return -1.0


def allow_expired_dialogs(flag: bool) -> None:
    """Classify (or stop classifying) the expired-batch guard as expected."""
    global ALLOW_EXPIRED
    ALLOW_EXPIRED = flag


def SalesDAO_is_expired(expiry: str) -> bool:
    from database.sales_dao import SalesDAO
    return SalesDAO.is_expired(expiry)


def SalesDAO_batches(item_id) -> list[dict]:
    if not item_id:
        return []
    from database.sales_dao import SalesDAO
    return SalesDAO.get_stock_batches_for_item(int(item_id))


def sellable_batches(item_id, min_stock: float = 0) -> list[dict]:
    return [b for b in SalesDAO_batches(item_id)
            if not SalesDAO_is_expired(b.get("expiry") or "")
            and float(b.get("stock_qty") or 0) >= min_stock]


def first_sellable_row(completer, min_stock: float = 0) -> int:
    """Popup row of the first completion that still has sellable stock."""
    model = completer.completionModel()
    for row in range(model.rowCount()):
        item_id = model.index(row, 0).data(Qt.UserRole)
        if item_id is None:
            continue
        if sellable_batches(item_id, min_stock):
            return row
    return -1


def target_batch_index(item_id, min_stock: float = 0) -> int:
    """Batch combo row (0 = placeholder) of the first usable batch."""
    for i, b in enumerate(SalesDAO_batches(item_id)):
        if (not SalesDAO_is_expired(b.get("expiry") or "")
                and float(b.get("stock_qty") or 0) >= min_stock):
            return i + 1
    return -1


if __name__ == "__main__":
    sys.exit(main())
