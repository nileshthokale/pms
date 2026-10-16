"""Verify the Counter Sale re-sizing: measure real widths, capture screenshots.

Read-only verification: the working database is snapshotted into a temp copy
(never written to), the page is built from that copy, one item row is added to
the on-screen bill (never saved), and the history table shows the copy's own
past bills.  Nothing here touches `data/pharmacy.db`, billing maths or the EXE.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _snapshot_database() -> pathlib.Path:
    """A disposable copy of the working database (read-only source)."""
    source_path = ROOT / "data" / "pharmacy.db"
    handle, staging_name = tempfile.mkstemp(
        prefix="counter_sale_verify_", suffix=".db"
    )
    os.close(handle)
    staging = pathlib.Path(staging_name)
    staging.unlink()
    if source_path.is_file():
        source = sqlite3.connect(
            f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True
        )
        target = sqlite3.connect(staging)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
    return staging


def main() -> int:
    staging = _snapshot_database()
    os.environ["PHARMACY_DB"] = str(staging)
    os.environ["PHARMACY_TEST_SAFE_DB"] = str(staging)

    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication, QMessageBox, QHeaderView

    from database import auth, financial_year
    from database.connection import init_database
    from ui import theme

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    # Any stray message box (e.g. an expired-batch warning for a demo row)
    # would block forever offscreen; answer Ok/No automatically instead.
    QMessageBox.warning = staticmethod(
        lambda *a, **k: QMessageBox.Ok)
    QMessageBox.information = staticmethod(
        lambda *a, **k: QMessageBox.Ok)
    QMessageBox.critical = staticmethod(
        lambda *a, **k: QMessageBox.Ok)
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.No)
    init_database()
    auth.ensure_auth_schema()
    financial_year.ensure_default_financial_year()
    if auth.user_count() == 0:
        auth.create_first_admin("admin", "admin-pass-1")
    auth.session.user = {
        "id": 1, "username": "admin", "role": auth.ROLE_ADMIN, "is_active": 1,
    }

    import screens

    out_dir = ROOT / "docs" / "ui_screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    def report(page, tag: str) -> None:
        panel = page._sale_panel
        entry = panel._entry_bar
        bill = panel._table
        hist = page._hist_table

        print(f"\n=== {tag} ===")

        print("Bill Items table (11 columns):")
        hv = bill.horizontalHeader()
        print(f"  viewport width: {bill.viewport().width()}")
        for i in range(bill.columnCount()):
            name = bill.horizontalHeaderItem(i).text()
            mode = QHeaderView.Stretch
            if hv.sectionResizeMode(i) == QHeaderView.Fixed:
                mode = QHeaderView.Fixed
            elif hv.sectionResizeMode(i) == QHeaderView.Interactive:
                mode = QHeaderView.Interactive
            print(f"  [{i:>2}] {name:<11} {bill.columnWidth(i):>4} px  {mode.name}")
        total = sum(bill.columnWidth(i) for i in range(bill.columnCount()))
        print(f"  total {total}  (blank strip check: "
              f"slack={bill.viewport().width() - total})")

        print("Daily Sales history table (first 13 columns):")
        hh = hist.horizontalHeader()
        print(f"  viewport width: {hist.viewport().width()}")
        for i in range(hist.columnCount()):
            name = hist.horizontalHeaderItem(i).text()
            print(f"  [{i:>2}] {name:<11} {hist.columnWidth(i):>4} px  "
                  f"{hh.sectionResizeMode(i).name}")
        total = sum(hist.columnWidth(i) for i in range(hist.columnCount()))
        print(f"  total {total}  (slack={hist.viewport().width() - total})")

        print("Item/Batch input row (12 controls):")
        fields = (
            ("cno_label", entry.cno_label), ("item_combo", entry.item_combo),
            ("batch_combo", entry.batch_combo),
            ("pack_edit", entry.pack_edit),
            ("location_edit", entry.location_edit),
            ("expiry_edit", entry.expiry_edit), ("mrp_edit", entry.mrp_edit),
            ("stock_edit", entry.stock_edit), ("qty_edit", entry.qty_edit),
            ("discount_edit", entry.discount_edit),
            ("amount_edit", entry.amount_edit), ("add_btn", entry.add_btn),
        )
        for name, widget in fields:
            print(f"  {name:<14} {widget.width():>4} px")
        row_last = fields[-1][1]
        overrun = row_last.x() + row_last.width() - entry.width()
        print(f"  row overrun check: {overrun} (must be <= 0)")
        if os.environ.get("TRACE_ENTRY_BAR"):  # diagnose fitter inputs
            layout = entry.layout()
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is not None:
                    print(f"    layout: {type(item.widget()).__name__} "
                          f"w={item.widget().width()} "
                          f"min={item.widget().minimumWidth()}")
                elif item.spacerItem() is not None:
                    print(f"    layout: spacer "
                          f"w={item.spacerItem().sizeHint().width()}")
            print(f"    entry.width()={entry.width()} "
                  f"chrome={entry._fixed_chrome_width()}")

    def exercize(page) -> None:
        """Content the user's own screenshot showed, from the snapshot copy."""
        import sqlite3

        con = sqlite3.connect(os.environ["PHARMACY_DB"])
        con.row_factory = sqlite3.Row
        batch = con.execute(
            "SELECT b.id AS batch_id, b.batch_no, b.expiry, b.mrp,"
            "       b.stock_qty, i.id AS item_id, i.item_name"
            "  FROM stock_batches b JOIN items i ON i.id = b.item_id"
            " WHERE b.batch_no <> '' ORDER BY LENGTH(b.batch_no) DESC LIMIT 1"
        ).fetchone()
        con.close()
        if batch is None:
            print("  (no batches in snapshot copy; skipping demo row)")
            return
        entry = page._sale_panel._entry_bar
        index = entry.item_combo.findData(batch["item_id"])
        if index >= 0:
            entry.item_combo.setCurrentIndex(index)
            match = entry.batch_combo.findData(batch["batch_id"])
            if match >= 0:
                entry.batch_combo.setCurrentIndex(match)
        entry.qty_edit.setText("1")
        page._sale_panel._on_add_item()   # on-screen row only; never saved

    def capture(mode: str) -> None:
        theme.theme_manager.set_mode(mode)
        app.processEvents()
        page = screens.CounterSalePage()
        page.resize(1366, 708)          # the size the layout tests use
        page.show()
        # Let the real layout settle: flush all pending resize/layout passes.
        for _ in range(6):
            app.processEvents()
        page._apply_history_height()
        for _ in range(6):
            app.processEvents()
        from ui import components as ui
        ui.polish_page(page)
        refresh = getattr(page, "refresh_theme", None)
        if callable(refresh):
            refresh()
        app.processEvents()
        report(page, f"{mode} @ 1366x708")
        exercize(page)
        app.processEvents()
        report(page, f"{mode} @ 1366x708 after adding a demo row")
        pixmap = page.grab()
        path = out_dir / f"counter_sale_resize_{mode}.png"
        pixmap.save(str(path), "PNG")
        print(f"  screenshot -> {path}")
        page.hide()
        page.deleteLater()
        app.processEvents()

    capture("light")
    capture("dark")
    theme.theme_manager.set_mode(theme.DEFAULT_MODE)

    # Text-fit sanity check with the fonts the screen actually uses.
    from ui.components import readable_font
    from ui.theme import TYPE_TABLE_DATA, TYPE_INPUT
    for label, text, point in (
        ("history/bill data  '2029-02-28'", "2029-02-28", TYPE_TABLE_DATA),
        ("entry data         '2029-02-28'", "2029-02-28", TYPE_INPUT),
        ("history/bill data  '14261266A'", "14261266A", TYPE_TABLE_DATA),
        ("entry data         '14261266A'", "14261266A", TYPE_INPUT),
    ):
        w = QFontMetrics(readable_font(point)).horizontalAdvance(text)
        print(f"{label}: {w} px advance (+ table padding ~10 px)")

    print("\nVerification finished; the working database was never modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
