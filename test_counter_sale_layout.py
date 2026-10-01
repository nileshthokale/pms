"""Phase 6E — Counter Sale layout tests (fixed three-region layout).

Covers the layout fix only:
  * history region has a controlled height
  * an empty history table never expands into a giant blank area
  * the active sale-entry region sits directly below the history
  * the entry region is never vertically centered and never drifts
  * the current bill table expands below the entry region
  * the right-side Bill panel exists
  * adding items / history rows does not move the entry region
  * resizing preserves the region order
  * New Sale resets the inline form and focuses Item Name
  * existing buttons and the Hold/Resume path still work
  * the existing save wiring (SalesDAO.insert_invoice) is unchanged

GUI tests are skipped only when PySide6 is unavailable.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

# Offscreen so the suite runs headless; harmless when a display exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QMessageBox, QPushButton

    from screens.counter_sale import CounterSalePage, _BillItemRow

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover - headless environments
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


def _make_row(index: int = 1) -> "_BillItemRow":
    return _BillItemRow(
        item_id=index,
        item_name=f"Item {index}",
        stock_batch_id=index,
        pack_size="10x10",
        location="A-1",
        batch_no=f"B-{index:03d}",
        expiry="12/27",
        mrp=50.0,
        sale_qty=2.0,
        discount_amount=0.0,
        amount=100.0,
    )


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CounterSaleLayoutTests(unittest.TestCase):
    """Layout/stability tests for the inline Counter Sale page."""

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            tempfile.gettempdir(), "pharmacy_counter_sale_layout.db"
        )
        if os.path.exists(cls._db_path):
            os.remove(cls._db_path)
        os.environ["PHARMACY_DB"] = cls._db_path

        from database.connection import init_database
        from database import auth, financial_year
        from database.customer_dao import CustomerDAO

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        CustomerDAO.insert("Layout Test Customer", city="Test City")
        cls._customer_id = next(
            c["id"] for c in CustomerDAO.get_all()
            if c["customer_name"] == "Layout Test Customer"
        )

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Never block on modal dialogs during layout tests.
        self._msg_patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No),
        ]
        for patcher in self._msg_patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.page = CounterSalePage()
        self.page.resize(1366, 708)
        self.page.show()
        QApplication.processEvents()
        self.page._apply_history_height()
        QApplication.processEvents()

        self.panel = self.page._sale_panel
        self.entry = self.panel._entry_bar
        self.bill_table = self.panel._table
        self.hist = self.page._hist_table
        self.totals = self.panel._totals_widget

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        QApplication.processEvents()

    # -- helpers ------------------------------------------------------
    def _y(self, widget) -> int:
        return widget.mapTo(self.page, widget.rect().topLeft()).y()

    def _assert_region_order(self):
        self.assertLess(self._y(self.hist), self._y(self.entry),
                        "history must be above the sale entry")
        self.assertLess(self._y(self.entry), self._y(self.bill_table),
                        "sale entry must be above the bill table")
        self.assertLess(self._y(self.bill_table), self._y(self.totals),
                        "bill table must be above the totals bar")

    # -- Region A: history -------------------------------------------
    def test_01_history_region_has_controlled_height(self):
        self.assertGreaterEqual(self.hist.height(), 100)
        self.assertLessEqual(self.hist.height(), self.page.height() * 0.35)
        self.assertEqual(self.hist.minimumHeight(), self.hist.maximumHeight(),
                         "history height must be fixed/controlled")

    def test_02_empty_history_does_not_fill_the_page(self):
        self.assertEqual(self.hist.rowCount(), 0)
        self.assertLess(self.hist.height(), self.page.height() * 0.5)

    # -- Region B: active sale entry ---------------------------------
    def test_03_entry_region_is_directly_below_history(self):
        expected = self._y(self.hist) + self.hist.height()
        self.assertLessEqual(abs(self._y(self.entry) - expected), 6,
                             "entry region must sit directly under the history")

    def test_04_entry_region_is_not_vertically_centered(self):
        self.assertLess(self._y(self.entry), self.page.height() * 0.55)
        self.assertLessEqual(self.entry.maximumHeight(), 72)

    def test_05_bill_table_expands_below_entry(self):
        self.assertGreater(self._y(self.bill_table), self._y(self.entry))
        self.assertGreater(self.bill_table.height(), 100,
                           "bill table must occupy real space")
        small = self.bill_table.height()
        self.page.resize(1920, 1020)
        QApplication.processEvents()
        self.page._apply_history_height()
        QApplication.processEvents()
        self.assertGreater(self.bill_table.height(), small,
                           "bill table must take the remaining space")

    # -- Right-side bill panel ---------------------------------------
    def test_06_right_bill_panel_exists(self):
        panel = self.page.findChild(type(self.totals), "BillPanel")
        self.assertIsNotNone(panel, "right-side Bill panel missing")
        self.assertGreaterEqual(panel.width(), 180)
        self.assertLessEqual(panel.width(), 300)
        titles = [g.title() for g in self.page.findChildren(QGroupBox)]
        self.assertIn("Bill", titles)
        self.assertIn("Current Bill", titles)
        self.assertGreater(panel.x(), self.bill_table.x())
        self.assertIn("Edit", [b.text() for b in panel.findChildren(QPushButton)])
        self.assertIn("Delete", [b.text() for b in panel.findChildren(QPushButton)])
        self.assertIn("Print / PDF",
                      [b.text() for b in panel.findChildren(QPushButton)])

    # -- stability ----------------------------------------------------
    def test_07_adding_an_item_does_not_move_entry_region(self):
        before = self._y(self.entry)
        self.panel._item_rows.append(_make_row(1))
        self.panel._refresh_table()
        self.panel._recalc_totals()
        QApplication.processEvents()
        self.assertEqual(self.bill_table.rowCount(), 1)
        self.assertEqual(self._y(self.entry), before,
                         "entry region moved after adding an item")

    def test_08_history_rows_do_not_move_entry_region(self):
        before = self._y(self.entry)
        height_before = self.hist.height()
        self.hist.setRowCount(150)
        QApplication.processEvents()
        self.assertEqual(self.hist.height(), height_before,
                         "history region grew with rows")
        self.assertEqual(self._y(self.entry), before,
                         "entry region moved after adding history rows")

    def test_09_resize_preserves_region_order(self):
        for width, height in ((1366, 708), (1600, 840), (1920, 1020), (1100, 600)):
            with self.subTest(size=f"{width}x{height}"):
                self.page.resize(width, height)
                QApplication.processEvents()
                self.page._apply_history_height()
                QApplication.processEvents()
                self._assert_region_order()
                self.assertLessEqual(self.hist.height(),
                                     max(240, self.page.height() * 0.35))

    # -- New Sale -----------------------------------------------------
    def test_10_new_sale_resets_and_focuses_active_area(self):
        self.panel._item_rows.append(_make_row(1))
        self.panel._refresh_table()
        self.page._on_new()
        QApplication.processEvents()
        self.assertEqual(self.bill_table.rowCount(), 0,
                         "New Sale must clear the current bill")
        self.assertTrue(self.entry.item_combo.hasFocus()
                        or QApplication.focusWidget() is self.entry.item_combo,
                        "New Sale must focus Item Name")
        self._assert_region_order()

    def test_11_existing_buttons_remain(self):
        texts = [b.text() for b in self.page.findChildren(QPushButton)]
        for required in ("New Sale", "Edit", "Delete", "Print / PDF",
                         "Save Sale", "Hold Bill", "Cancel", "+ Add"):
            self.assertIn(required, texts)

    # -- Hold / Resume ------------------------------------------------
    def test_12_hold_resume_loads_into_inline_sale_area(self):
        from database.hold_bill_dao import create_hold, get_by_id

        hold_id = create_hold(
            patient_name="Resume Patient",
            total_amount_preview=100.0,
            created_by="admin",
            items=[],
        )
        hold = get_by_id(hold_id)
        before = self._y(self.entry)

        self.page.open_sale_dialog_with_hold({"hold": hold, "items": []})
        QApplication.processEvents()

        self.assertEqual(self.panel._hold_bill_id, hold_id)
        self.assertEqual(self.panel.patient_name_edit.text(), "Resume Patient")
        self.assertEqual(self._y(self.entry), before,
                         "resumed hold must appear in the same Region B position")
        self._assert_region_order()

    # -- transaction wiring unchanged --------------------------------
    def test_13_save_wiring_still_calls_sales_dao(self):
        from screens import counter_sale as counter_sale_module
        from database.connection import get_connection
        from database.item_dao import ItemDAO

        index = self.panel.customer_combo.findData(self._customer_id)
        self.assertGreaterEqual(index, 0, "layout test customer missing")
        self.panel.customer_combo.setCurrentIndex(index)
        customer_id = self.panel.customer_combo.currentData()
        item_id = ItemDAO.insert("Layout Sale Item", pack_size="10x10", mrp=50.0)
        conn = get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO stock_batches "
                "(item_id, batch_no, expiry, pack_size, mrp, stock_qty) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, "LAYOUT-BATCH", "12/27", "10x10", 50.0, 100.0),
            )
            batch_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        self.panel._item_rows.append(_BillItemRow(
            item_id=item_id, item_name="Layout Sale Item",
            stock_batch_id=batch_id, pack_size="10x10", location="A-1",
            batch_no="LAYOUT-BATCH", expiry="12/27", mrp=50.0,
            sale_qty=2.0, discount_amount=0.0, amount=100.0,
        ))
        self.panel._refresh_table()
        self.panel._recalc_totals()

        recorded = {}

        def fake_insert_invoice(**kwargs):
            recorded.update(kwargs)
            return 1

        with mock.patch.object(counter_sale_module.SalesDAO, "insert_invoice",
                               side_effect=fake_insert_invoice):
            self.panel._on_save()

        # The inline form resets after a successful save (the modal dialog
        # used to close here), so the save is verified through the recorded
        # DAO payload plus the cleared bill table.
        self.assertEqual(self.bill_table.rowCount(), 0,
                         "sale area must reset after a successful save")
        for key in ("bill_no", "sale_date", "sale_time", "sale_type",
                    "customer_id", "patient_name", "doctor_id", "discount",
                    "paid_amount", "total_amount", "round_off", "net_amount",
                    "remarks", "items"):
            self.assertIn(key, recorded)
        self.assertEqual(recorded["customer_id"], customer_id)
        self.assertEqual(len(recorded["items"]), 1)
        self.assertEqual(recorded["items"][0]["amount"], 100.0)
        self.assertEqual(recorded["net_amount"], 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
