"""Counter Sale history: single Date control + Financial Year view.

Covers the read-only history view only:
  DATE   — one Date control, calendar popup, exact-day filtering,
            empty day, refresh on change
  FY     — clickable FY button in the top navigation, small picker popup
            fed from the existing financial_years table, FY history load,
            and Date moving to 31 March of the chosen year
  SAFETY — viewing an old FY never changes the active FY, never writes to
            the database, and New Sale still uses the live date and the
            active FY (with a Continue/Cancel warning when an old FY is open)
  MODES  — Item Wise / Bill Wise are untouched and still filtered

Every test runs against its own temporary SQLite file; ``data/pharmacy.db``
is never opened.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database, get_db_path  # noqa: E402
from database.account_roles import ensure_system_ledgers  # noqa: E402
from database.company_dao import CompanyDAO  # noqa: E402
from database.unit_dao import UnitDAO  # noqa: E402
from database.item_dao import ItemDAO  # noqa: E402
from database.supplier_dao import SupplierDAO  # noqa: E402
from database.purchase_dao import PurchaseDAO  # noqa: E402
from database.stock_dao import StockDAO  # noqa: E402
from database.sales_dao import SalesDAO  # noqa: E402
from database import financial_year  # noqa: E402

try:
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication, QPushButton

    from screens.counter_sale import (
        HISTORY_FILTER_ALL,
        HISTORY_FILTER_DATE,
        HISTORY_FILTER_FY,
        HISTORY_MODE_BILL,
        HISTORY_MODE_ITEM,
        CounterSalePage,
    )
    from ui.navigation_bar import FinancialYearPickerDialog, NavigationBar

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover - headless environments
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


_ACTIVE_FY = "2026-2027"
_OLD_FY = "2025-2026"
_OLD_FY_START = "2025-04-01"
_OLD_FY_END = "2026-03-31"
_ITEM_WISE_ROWS_ALL = 6
_BILL_WISE_ROWS_ALL = 3


def _dump_db(path: str) -> dict:
    """Snapshot every table so read-only guarantees can be proven."""
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        snapshot = {}
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        for name in names:
            snapshot[name] = conn.execute(f"SELECT * FROM {name}").fetchall()
        return snapshot
    finally:
        conn.close()


class _FakeMessageBox:
    """Stand-in for QMessageBox that records what was shown and clicked."""

    Information = "information"
    Warning = "warning"

    class ButtonRole:
        AcceptRole = "acceptrole"
        RejectRole = "rejectrole"

    last_instance = None
    click_label = None

    def __init__(self, parent=None):
        self.parent = parent
        self.window_title = None
        self.text = None
        self.icon = None
        self.buttons: dict[str, object] = {}
        self.executed = False
        _FakeMessageBox.last_instance = self

    def setWindowTitle(self, title):
        self.window_title = title

    def setIcon(self, icon):
        self.icon = icon

    def setText(self, text):
        self.text = text

    def setDefaultButton(self, button):
        self.default_button = button

    def addButton(self, label, role=None):
        self.buttons[label] = (label, role)
        return label

    def exec(self):
        self.executed = True
        chosen = _FakeMessageBox.click_label
        self._clicked = self.buttons.get(chosen, (None, None))[0]
        return 1 if self._clicked else 0

    def clickedButton(self):
        return self._clicked


class _HistorySeedMixin:
    """Shared isolated database, two financial years, and seeded sales."""

    @classmethod
    def _init_history_db(cls):
        cls._db_path = os.path.join(
            tempfile.gettempdir(), "pharmacy_counter_sale_fy_view.db"
        )
        if os.path.exists(cls._db_path):
            os.remove(cls._db_path)
        os.environ["PHARMACY_DB"] = cls._db_path
        init_database()
        cls._assert_isolated_db()

    @classmethod
    def _assert_isolated_db(cls):
        assert "data/pharmacy.db" not in get_db_path().replace("\\", "/"), (
            f"tests must never touch data/pharmacy.db (got {get_db_path()})"
        )

    def setUp(self):
        self._assert_isolated_db()
        conn = get_connection()
        try:
            for table in ("sales_invoice_items", "sales_invoices",
                          "stock_batches", "purchase_invoice_items",
                          "purchase_invoices", "items", "suppliers",
                          "units", "companies", "drugs"):
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.execute("DELETE FROM financial_years")
            conn.commit()
        finally:
            conn.close()

        financial_year.ensure_financial_year_schema()
        financial_year.create_financial_year(
            _ACTIVE_FY, "2026-04-01", "2027-03-31", activate=True
        )
        financial_year.create_financial_year(
            _OLD_FY, _OLD_FY_START, _OLD_FY_END, activate=False
        )
        self.active_fy = financial_year.get_active_financial_year()
        self.old_fy = next(
            y for y in financial_year.get_financial_years()
            if y["name"] == _OLD_FY
        )

        self.company_id = CompanyDAO.insert("FyCo", "FC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.supplier_id = SupplierDAO.insert("FySupplier")
        self._items = {}
        for name in ("FyA", "FyB", "FyC"):
            self._items[name] = ItemDAO.insert(
                item_name=name, unit_id=self.unit_id,
                company_id=self.company_id, pack_size="10x10",
            )
        ensure_system_ledgers()
        self._batches = self._seed_stock()
        self._seed_sales()

    def _seed_stock(self, qty=1000.0, rate=40.0, mrp=50.0):
        purchase_items = [{
            "item_id": item_id, "pack_size": "10x10",
            "pay_qty": qty, "free_qty": 0, "batch_no": f"B-{name}",
            "expiry": "12/28", "rate": rate, "mrp": mrp, "discount": 0,
            "gst_percent": 0, "gst_amount": 0, "amount": qty * rate,
            "purchase_rate": rate, "net_rate": rate, "pp": rate,
        } for name, item_id in self._items.items()]
        PurchaseDAO.insert_invoice(
            voucher_no="PV-FY", voucher_date="2026-02-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-FY", invoice_date="2026-02-01",
            invoice_net_amount=qty * rate * 3, bill_discount=0, due_date="",
            total_amount=qty * rate * 3, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=qty * rate * 3, round_off=0,
            net_amount=qty * rate * 3, remarks="", items=purchase_items,
        )
        return {
            name: StockDAO.get_stock_batches_for_item(item_id)[0]["id"]
            for name, item_id in self._items.items()
        }

    def _make_sale(self, bill_no, sale_date, item_names, patient=""):
        lines, total = [], 0.0
        for name in item_names:
            amount = round(2 * 50.0, 2)
            total = round(total + amount, 2)
            lines.append({
                "item_id": self._items[name],
                "stock_batch_id": self._batches[name],
                "pack_size": "10x10", "location": "",
                "batch_no": f"B-{name}", "expiry": "12/28",
                "mrp": 50.0, "sale_qty": 2.0,
                "discount_amount": 0.0, "amount": amount,
            })
        return SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date=sale_date, sale_time="10:00",
            sale_type="Cash", customer_id=None, patient_name=patient,
            doctor_id=None, discount=0.0, paid_amount=total,
            total_amount=total, round_off=0.0, net_amount=total,
            remarks="", items=lines,
        )

    def _seed_sales(self):
        # Both days sit inside the OLD financial year, so selecting it has
        # something to show while the ACTIVE year has none.
        self.id_h01 = self._make_sale("CS-F01", "2026-03-01", ["FyA", "FyB"], "Pat One")
        self.id_h02 = self._make_sale("CS-F02", "2026-03-01", ["FyA"], "Pat Two")
        self.id_h03 = self._make_sale(
            "CS-F03", "2026-03-05", ["FyA", "FyB", "FyC"], "Pat Three"
        )


# ======================================================================
# DATE control
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class HistoryDateControlTests(_HistorySeedMixin, unittest.TestCase):
    """The single Date control and its exact-day history filter."""

    @classmethod
    def setUpClass(cls):
        cls._init_history_db()
        from database import auth
        auth.ensure_auth_schema()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.page = CounterSalePage()
        self.page.resize(1280, 900)

    def tearDown(self):
        self.page.deleteLater()

    def _cell(self, row, col):
        item = self.page._hist_table.item(row, col)
        return item.text() if item is not None else ""

    def _bill_nos(self):
        return [self._cell(r, 0)
                for r in range(self.page._hist_table.rowCount())]

    def _pick(self, iso_date):
        self.page._hist_date.setDate(QDate.fromString(iso_date, "yyyy-MM-dd"))

    # -- the control itself -------------------------------------------
    def test_01_single_date_control_exists(self):
        from PySide6.QtWidgets import QDateEdit
        self.assertIsInstance(self.page._hist_date, QDateEdit)
        self.assertIsNotNone(self.page._history_filter_bar)

    def test_02_history_filter_bar_has_no_from_or_to_fields(self):
        from PySide6.QtWidgets import QDateEdit
        bar_dates = self.page._history_filter_bar.findChildren(QDateEdit)
        self.assertEqual(bar_dates, [self.page._hist_date],
                         "the history bar must hold exactly one Date control")

    def test_03_calendar_popup_is_enabled(self):
        self.assertTrue(self.page._hist_date.calendarPopup(),
                        "clicking the Date control must open a calendar")

    def test_04_date_control_is_labelled_date(self):
        from PySide6.QtWidgets import QLabel
        texts = [lbl.text() for lbl
                 in self.page._history_filter_bar.findChildren(QLabel)]
        self.assertIn("Date", texts)

    def test_05_history_date_and_bill_date_are_separate_controls(self):
        panel = self.page._sale_panel
        self.assertIsNot(self.page._hist_date, panel.sale_date,
                         "the history Date must never drive the new bill date")

    # -- filtering ----------------------------------------------------
    def test_06_selecting_a_date_filters_to_that_exact_day(self):
        self._pick("2026-03-01")
        self.assertEqual(self.page._hist_table.rowCount(), 3)
        self.assertEqual(set(self._bill_nos()), {"CS-F01", "CS-F02"})

    def test_07_selecting_the_other_date_excludes_the_first(self):
        self._pick("2026-03-05")
        self.assertEqual(self.page._hist_table.rowCount(), 3)
        self.assertEqual(set(self._bill_nos()), {"CS-F03"})

    def test_08_date_filter_mode_is_date(self):
        self._pick("2026-03-01")
        self.assertEqual(self.page._history_filter, HISTORY_FILTER_DATE)
        self.assertEqual(self.page._history_filter_dates(),
                         ("2026-03-01", "2026-03-01"))

    def test_09_day_with_no_sales_shows_the_empty_grid(self):
        self._pick("2026-03-03")
        self.assertEqual(self.page._hist_table.rowCount(), 0)

    def test_10_changing_the_date_refreshes_immediately(self):
        self._pick("2026-03-01")
        self.assertEqual(self.page._hist_table.rowCount(), 3)
        self._pick("2026-03-05")
        self.assertEqual(self.page._hist_table.rowCount(), 3)
        self.assertEqual(set(self._bill_nos()), {"CS-F03"})

    def test_11_all_dates_button_shows_every_bill(self):
        self._pick("2026-03-01")
        self.assertEqual(self.page._hist_table.rowCount(), 3)
        self.page._hist_all_btn.click()
        self.assertEqual(self.page._history_filter, HISTORY_FILTER_ALL)
        self.assertEqual(self.page._hist_table.rowCount(), _ITEM_WISE_ROWS_ALL)

    def test_12_date_filter_applies_to_bill_wise_view(self):
        self.page._hist_bill_mode.setChecked(True)
        self._pick("2026-03-01")
        self.assertEqual(self.page._hist_table.rowCount(), 2)
        self.assertEqual(self._bill_nos(), ["CS-F02", "CS-F01"])

    def test_13_item_wise_and_bill_wise_are_untouched(self):
        self.page._hist_all_btn.click()
        self.assertEqual(self.page._hist_table.rowCount(), _ITEM_WISE_ROWS_ALL)
        self.page._hist_bill_mode.setChecked(True)
        self.assertEqual(self.page._hist_table.rowCount(), _BILL_WISE_ROWS_ALL)
        bill_nos = self._bill_nos()
        self.assertEqual(len(bill_nos), len(set(bill_nos)))

    def test_14_date_filter_writes_nothing(self):
        before = _dump_db(self._db_path)
        self._pick("2026-03-01")
        self.page._hist_bill_mode.setChecked(True)
        self.page._hist_item_mode.setChecked(True)
        self.page._hist_refresh_btn.click()
        self.assertEqual(_dump_db(self._db_path), before)


# ======================================================================
# FINANCIAL YEAR button + popup
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class FinancialYearViewTests(_HistorySeedMixin, unittest.TestCase):
    """FY button in the top bar, the small picker, and FY history."""

    @classmethod
    def setUpClass(cls):
        cls._init_history_db()
        from database import auth
        auth.ensure_auth_schema()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.page = CounterSalePage()
        self.page.resize(1280, 900)
        self.nav = NavigationBar()
        self.nav.refresh_indicators()

    def tearDown(self):
        self.nav.deleteLater()
        self.page.deleteLater()

    def _cell(self, row, col):
        item = self.page._hist_table.item(row, col)
        return item.text() if item is not None else ""

    # -- the button ---------------------------------------------------
    def test_15_fy_button_exists_in_the_top_navigation(self):
        button = self.nav.fy_button
        self.assertIsInstance(button, QPushButton)
        self.assertEqual(button.objectName(), "FinancialYearButton")
        self.assertEqual(button.text(), f"FY {_ACTIVE_FY}")

    def test_16_fy_button_stays_in_the_title_strip(self):
        button = self.nav.fy_button
        self.assertIs(button.parentWidget(), self.nav.fy_button.parentWidget())
        self.assertIn(button, button.parentWidget().findChildren(QPushButton))

    def test_17_clicking_the_fy_button_opens_the_picker(self):
        opened = []

        class _Recording(FinancialYearPickerDialog):
            def exec(self):
                opened.append(self)
                return 0                      # simulate Cancel

        with mock.patch("ui.navigation_bar.FinancialYearPickerDialog", _Recording):
            self.nav.fy_button.click()
        self.assertEqual(len(opened), 1, "clicking FY must open the popup")

    def test_18_picker_lists_every_year_from_the_database(self):
        dialog = FinancialYearPickerDialog()
        years = financial_year.get_financial_years()
        self.assertEqual(dialog.combo.count(), len(years))
        listed = [dialog.combo.itemText(i) for i in range(dialog.combo.count())]
        self.assertTrue(any(_OLD_FY in text for text in listed))
        self.assertTrue(any(_ACTIVE_FY in text for text in listed))
        dialog.deleteLater()

    def test_19_picker_is_small_and_read_only(self):
        before = _dump_db(self._db_path)
        dialog = FinancialYearPickerDialog()
        self.assertLessEqual(dialog.width(), 360)
        self.assertEqual(len(dialog._years), 2)
        self.assertIsNone(dialog.selected_year())
        dialog.deleteLater()
        self.assertEqual(_dump_db(self._db_path), before)

    def test_20_picker_returns_the_chosen_year(self):
        dialog = FinancialYearPickerDialog()
        index = next(i for i in range(dialog.combo.count())
                     if _OLD_FY in dialog.combo.itemText(i))
        dialog.combo.setCurrentIndex(index)
        dialog._accept()
        self.assertEqual(dialog.selected_year()["name"], _OLD_FY)
        self.assertEqual(dialog.selected_year()["start_date"], _OLD_FY_START)
        self.assertEqual(dialog.selected_year()["end_date"], _OLD_FY_END)
        dialog.deleteLater()

    def test_21_picker_defaults_to_the_active_year(self):
        dialog = FinancialYearPickerDialog()
        chosen = dialog.combo.currentData()
        self.assertEqual(chosen, self.active_fy["id"])
        self.assertIn("(active)", dialog.combo.currentText())
        dialog.deleteLater()

    def test_22_button_choice_reaches_the_counter_sale_page(self):
        received = []
        chosen = dict(self.old_fy)
        self.nav.financial_year_view_requested.connect(received.append)
        with mock.patch.object(
            FinancialYearPickerDialog, "exec", lambda self: 0
        ), mock.patch.object(
            FinancialYearPickerDialog, "selected_year", lambda self: chosen
        ):
            self.nav.fy_button.click()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["name"], _OLD_FY)

    # -- applying the FY to the history -------------------------------
    def test_23_selecting_an_fy_loads_that_financial_year(self):
        self.page.set_history_financial_year(self.old_fy)
        self.assertEqual(self.page._history_filter, HISTORY_FILTER_FY)
        self.assertEqual(self.page._history_filter_dates(),
                         (_OLD_FY_START, _OLD_FY_END))
        self.assertEqual(self.page._hist_table.rowCount(), _ITEM_WISE_ROWS_ALL)

    def test_24_selecting_an_fy_sets_the_date_to_31_march(self):
        self.page.set_history_financial_year(self.old_fy)
        self.assertEqual(
            self.page._hist_date.date().toString("yyyy-MM-dd"), _OLD_FY_END
        )
        self.assertEqual(
            self.page._hist_date.date().toString("dd/MM/yyyy"), "31/03/2026"
        )

    def test_25_fy_view_is_one_row_per_bill_in_bill_wise(self):
        self.page.set_history_financial_year(self.old_fy)
        self.page._hist_bill_mode.setChecked(True)
        self.assertEqual(self.page._hist_table.rowCount(), _BILL_WISE_ROWS_ALL)
        bill_nos = [self._cell(r, 0) for r in range(self.page._hist_table.rowCount())]
        self.assertEqual(len(bill_nos), len(set(bill_nos)))

    def test_26_current_fy_view_shows_that_year_only(self):
        self.page.set_history_financial_year(self.active_fy)
        self.assertEqual(self.page._history_filter_dates(),
                         ("2026-04-01", "2027-03-31"))
        self.assertEqual(self.page._hist_table.rowCount(), 0)

    def test_27_picking_a_date_after_an_fy_returns_to_date_filtering(self):
        self.page.set_history_financial_year(self.old_fy)
        self.page._hist_date.setDate(QDate.fromString("2026-03-05", "yyyy-MM-dd"))
        self.assertEqual(self.page._history_filter, HISTORY_FILTER_DATE)
        self.assertEqual(self.page._hist_table.rowCount(), 3)

    def test_28_setting_a_fy_refreshes_immediately(self):
        self.page.set_history_financial_year(self.old_fy)
        self.assertGreater(self.page._hist_table.rowCount(), 0)
        self.page.set_history_financial_year(self.active_fy)
        self.assertEqual(self.page._hist_table.rowCount(), 0)


# ======================================================================
# OLD FY SAFETY — new bills must stay on the live date / active FY
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class OldFinancialYearSafetyTests(_HistorySeedMixin, unittest.TestCase):
    """Selecting an old FY must never leak into new bill creation."""

    @classmethod
    def setUpClass(cls):
        cls._init_history_db()
        from database import auth
        auth.ensure_auth_schema()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        _FakeMessageBox.last_instance = None
        _FakeMessageBox.click_label = None
        self.page = CounterSalePage()
        self.page.resize(1280, 900)
        self.page.set_history_financial_year(self.old_fy)

    def tearDown(self):
        self.page.deleteLater()

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    # -- the FY selection itself is inert -----------------------------
    def test_29_selecting_an_old_fy_does_not_change_the_active_fy(self):
        self.page.set_history_financial_year(self.old_fy)
        self.assertEqual(financial_year.get_active_financial_year()["name"],
                         _ACTIVE_FY)
        self.assertEqual(financial_year.get_active_financial_year()["id"],
                         self.active_fy["id"])

    def test_30_selecting_an_old_fy_does_not_modify_the_database(self):
        before = _dump_db(self._db_path)
        self.page.set_history_financial_year(self.old_fy)
        self.page.set_history_financial_year(self.active_fy)
        self.page.set_history_financial_year(self.old_fy)
        self.assertEqual(_dump_db(self._db_path), before)

    def test_31_selecting_an_old_fy_creates_no_financial_year(self):
        count_before = len(financial_year.get_financial_years())
        self.page.set_history_financial_year(self.old_fy)
        self.assertEqual(len(financial_year.get_financial_years()), count_before)

    def test_32_old_fy_is_detected_as_historical(self):
        self.assertTrue(self.page._viewing_historical_financial_year())
        self.page.set_history_financial_year(self.active_fy)
        self.assertFalse(self.page._viewing_historical_financial_year())

    # -- the New Sale warning ----------------------------------------
    def test_33_new_sale_with_old_fy_shows_the_warning(self):
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Cancel"
            self.page._on_new()
        box = _FakeMessageBox.last_instance
        self.assertIsNotNone(box)
        self.assertTrue(box.executed, "a warning popup must be shown")
        self.assertIn("Historical Financial Year selected", box.text)
        self.assertIn(_OLD_FY, box.text)
        self.assertIn(_ACTIVE_FY, box.text)
        self.assertEqual(set(box.buttons), {"Continue", "Cancel"})

    def test_34_cancel_prevents_new_sale(self):
        panel = self.page._sale_panel
        panel.patient_name_edit.setText("Draft Patient")
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Cancel"
            self.page._on_new()
        self.assertEqual(panel.patient_name_edit.text(), "Draft Patient",
                         "Cancel must leave the draft alone")

    def test_35_continue_starts_the_new_sale(self):
        panel = self.page._sale_panel
        panel.patient_name_edit.setText("Draft Patient")
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Continue"
            self.page._on_new()
        self.assertEqual(panel.patient_name_edit.text(), "")
        self.assertIsNone(self.page._editing_invoice_id)

    # -- the new bill's date and FY ----------------------------------
    def test_36_new_bill_uses_the_current_live_date(self):
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Continue"
            self.page._on_new()
        self.assertEqual(
            self.page._sale_panel.sale_date.date().toString("yyyy-MM-dd"),
            self._today(),
        )

    def test_37_new_bill_does_not_use_the_31_march_history_date(self):
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Continue"
            self.page._on_new()
        new_date = self.page._sale_panel.sale_date.date().toString("yyyy-MM-dd")
        self.assertNotEqual(new_date, _OLD_FY_END)

    def test_38_new_bill_date_passes_the_active_financial_year_check(self):
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Continue"
            self.page._on_new()
        new_date = self.page._sale_panel.sale_date.date().toString("yyyy-MM-dd")
        active = financial_year.get_active_financial_year()
        financial_year.validate_transaction_date(new_date)   # raises if outside
        self.assertGreaterEqual(new_date, active["start_date"])
        self.assertLessEqual(new_date, active["end_date"])

    def test_39_new_bill_does_not_use_the_old_financial_year(self):
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Continue"
            self.page._on_new()
        new_date = self.page._sale_panel.sale_date.date().toString("yyyy-MM-dd")
        self.assertFalse(
            _OLD_FY_START <= new_date <= _OLD_FY_END,
            "the new bill must not land inside the viewed old FY",
        )

    def test_40_new_bill_keeps_the_current_bill_number_rules(self):
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Continue"
            self.page._on_new()
        expected = SalesDAO.generate_next_bill_no()
        self.assertEqual(self.page._sale_panel.bill_no_edit.text(), expected)

    def test_41_history_date_stays_on_the_viewed_fy_after_new_sale(self):
        """Starting a bill must not disturb the history being viewed."""
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Continue"
            self.page._on_new()
        self.assertEqual(self.page._history_filter, HISTORY_FILTER_FY)
        self.assertEqual(self.page._viewed_financial_year()["name"], _OLD_FY)

    def test_42_new_sale_does_not_write_anything_by_itself(self):
        before = _dump_db(self._db_path)
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            _FakeMessageBox.click_label = "Continue"
            self.page._on_new()
        self.assertEqual(_dump_db(self._db_path), before)


# ======================================================================
# CURRENT FY — no behaviour change at all
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class CurrentFinancialYearBehaviourTests(_HistorySeedMixin, unittest.TestCase):
    """With the active FY in view, New Sale behaves exactly as before."""

    @classmethod
    def setUpClass(cls):
        cls._init_history_db()
        from database import auth
        auth.ensure_auth_schema()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        _FakeMessageBox.last_instance = None
        _FakeMessageBox.click_label = None
        self.page = CounterSalePage()
        self.page.resize(1280, 900)

    def tearDown(self):
        self.page.deleteLater()

    def test_43_new_sale_with_active_fy_shows_no_warning(self):
        self.page.set_history_financial_year(self.active_fy)
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            self.page._on_new()
        self.assertIsNone(_FakeMessageBox.last_instance,
                          "no warning popup for the active FY")

    def test_44_new_sale_with_no_fy_selected_shows_no_warning(self):
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            self.page._on_new()
        self.assertIsNone(_FakeMessageBox.last_instance)

    def test_45_new_sale_uses_the_live_date_and_active_fy(self):
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            self.page._on_new()
        panel = self.page._sale_panel
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(panel.sale_date.date().toString("yyyy-MM-dd"), today)
        financial_year.validate_transaction_date(today)
        self.assertTrue(panel.bill_no_edit.text())

    def test_46_new_sale_still_resets_the_form(self):
        panel = self.page._sale_panel
        panel.patient_name_edit.setText("Draft Patient")
        with mock.patch("screens.counter_sale.QMessageBox", _FakeMessageBox):
            self.page._on_new()
        self.assertEqual(panel.patient_name_edit.text(), "")
        self.assertEqual(panel._item_rows, [])

    def test_47_active_fy_is_still_active_after_viewing_the_old_one(self):
        self.page.set_history_financial_year(self.old_fy)
        self.page.set_history_financial_year(self.active_fy)
        self.assertEqual(financial_year.get_active_financial_year()["name"],
                         _ACTIVE_FY)


# ======================================================================
# Query level — the two history views and their read-only guarantee
# ======================================================================

class HistoryQueryTests(_HistorySeedMixin, unittest.TestCase):
    """SalesDAO history reads, independent of any widget."""

    @classmethod
    def setUpClass(cls):
        cls._init_history_db()

    def test_48_item_wise_returns_one_row_per_sale_item(self):
        rows = SalesDAO.get_history_page(limit=100, offset=0)
        self.assertEqual(len(rows), _ITEM_WISE_ROWS_ALL)

    def test_49_item_wise_repeats_the_bill_no_on_every_item_row(self):
        rows = SalesDAO.get_history_page(
            limit=100, offset=0, start_date="2026-03-05", end_date="2026-03-05"
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["bill_no"] for r in rows}, {"CS-F03"})
        self.assertEqual(len({r["item_name"] for r in rows}), 3)

    def test_50_item_wise_filters_an_exact_day(self):
        rows = SalesDAO.get_history_page(
            limit=100, offset=0, start_date="2026-03-01", end_date="2026-03-01"
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["invoice_id"] for r in rows}, {self.id_h01, self.id_h02})

    def test_51_bill_wise_returns_exactly_one_row_per_bill(self):
        rows = SalesDAO.get_bill_history_page(limit=100, offset=0)
        self.assertEqual(len(rows), _BILL_WISE_ROWS_ALL)
        ids = [r["invoice_id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)), "duplicate bill rows")

    def test_52_bill_wise_uses_bill_level_fields_only(self):
        row = next(r for r in SalesDAO.get_bill_history_page(limit=100)
                   if r["bill_no"] == "CS-F01")
        self.assertEqual(row["item_count"], 2)
        self.assertEqual(row["net_amount"], 200.0)
        self.assertEqual(row["sale_date"], "2026-03-01")
        for item_field in ("item_name", "batch_no", "sale_qty", "mrp"):
            self.assertNotIn(item_field, row)

    def test_53_bill_wise_filters_a_financial_year_range(self):
        rows = SalesDAO.get_bill_history_page(
            limit=100, offset=0, start_date=_OLD_FY_START, end_date=_OLD_FY_END
        )
        self.assertEqual(len(rows), _BILL_WISE_ROWS_ALL)
        bill_nos = [r["bill_no"] for r in rows]
        self.assertEqual(len(bill_nos), len(set(bill_nos)))

    def test_54_bill_wise_excludes_dates_outside_the_range(self):
        rows = SalesDAO.get_bill_history_page(
            limit=100, offset=0, start_date="2026-04-01", end_date="2027-03-31"
        )
        self.assertEqual(rows, [])

    def test_55_empty_dates_return_everything(self):
        self.assertEqual(
            len(SalesDAO.get_history_page(limit=100, start_date="", end_date="")),
            _ITEM_WISE_ROWS_ALL,
        )
        self.assertEqual(
            len(SalesDAO.get_bill_history_page(
                limit=100, start_date="", end_date="")),
            _BILL_WISE_ROWS_ALL,
        )

    def test_56_history_queries_write_nothing(self):
        before = _dump_db(self._db_path)
        SalesDAO.get_history_page(limit=100, start_date="2026-03-01")
        SalesDAO.get_bill_history_page(limit=100, start_date=_OLD_FY_START)
        self.assertEqual(_dump_db(self._db_path), before)

    def test_57_history_queries_do_not_touch_stock_or_the_ledger(self):
        stock_before = StockDAO.get_stock_batches_for_item(self._items["FyA"])
        conn = get_connection()
        try:
            ledger_before = conn.execute(
                "SELECT * FROM ledger_transactions ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        SalesDAO.get_bill_history_page(limit=100, start_date=_OLD_FY_START)
        SalesDAO.get_history_page(limit=100, start_date=_OLD_FY_START)
        self.assertEqual(
            StockDAO.get_stock_batches_for_item(self._items["FyA"]), stock_before
        )
        conn = get_connection()
        try:
            self.assertEqual(
                conn.execute("SELECT * FROM ledger_transactions ORDER BY id").fetchall(),
                ledger_before,
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)