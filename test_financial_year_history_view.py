"""Financial-year history view tests.

Covers the reported defect: when an old financial year is selected the
application must show that year's complete transaction history, not records
mixed across several years.

Numbered tests:
   1-3:   view_year_bounds helper (real bounds and both fallbacks)
   4-8:   financial-year date boundaries at the query level
   9-16:  report screens follow the financial-year selection
  17-18:  master data stays available across financial years
  19-22:  back-entry confirmation rules
"""

import os
import sqlite3
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database import financial_year
from database.sales_report_dao import SalesReportDAO

from ui.fy_view import view_year_bounds

try:
    from PySide6.QtWidgets import QApplication

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


FY_2016 = ("2016-2017", "2016-04-01", "2017-03-31")
FY_2017 = ("2017-2018", "2017-04-01", "2018-03-31")
FY_2026 = ("2026-2027", "2026-04-01", "2027-03-31")

TABLES = [
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class _BaseTest(unittest.TestCase):
    _DB_PATH = os.path.join(
        os.path.dirname(__file__), "_test_fy_history_view.db"
    )

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in TABLES:
                conn.execute(f"DELETE FROM {tbl}")
            conn.execute("DELETE FROM financial_years")
            conn.commit()
            self.customer_id = conn.execute(
                "INSERT INTO customers (customer_name) VALUES ('CustomerA')"
            ).lastrowid
            self.unit_id = conn.execute(
                "INSERT INTO units (unit_name) VALUES ('Pcs')"
            ).lastrowid
            self.item_id = conn.execute(
                "INSERT INTO items (item_name, unit_id) VALUES ('ItemA', ?)",
                (self.unit_id,),
            ).lastrowid
            self.batch_id = conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, stock_qty)"
                " VALUES (?, 'BATCH-A', 100)",
                (self.item_id,),
            ).lastrowid
            conn.commit()
        finally:
            conn.close()

        # Three non-overlapping years, with 2026-2027 active.
        financial_year.create_financial_year(*FY_2016)
        financial_year.create_financial_year(*FY_2017)
        self.active = financial_year.create_financial_year(*FY_2026, activate=True)
        self.fy_2017 = financial_year.get_financial_year_for_date("2017-06-01")
        self.fy_2016 = financial_year.get_financial_year_for_date("2016-06-01")

    # ── helpers ──────────────────────────────────────────────────────
    def _seed_sale(self, bill_no: str, sale_date: str, amount: float = 100.0):
        conn = get_connection()
        try:
            inv = conn.execute(
                "INSERT INTO sales_invoices (bill_no, sale_date, customer_id,"
                " net_amount) VALUES (?, ?, ?, ?)",
                (bill_no, sale_date, self.customer_id, amount),
            ).lastrowid
            conn.execute(
                "INSERT INTO sales_invoice_items (sales_invoice_id, item_id,"
                " stock_batch_id, batch_no, sale_qty, amount)"
                " VALUES (?, ?, ?, 'BATCH-A', 1, ?)",
                (inv, self.item_id, self.batch_id, amount),
            )
            conn.commit()
            return inv
        finally:
            conn.close()

    def _dates(self, rows):
        return sorted({r["sale_date"] for r in rows})


# ══════════════════════════════════════════════════════════════════════
# 1-3: the shared bounds helper
# ══════════════════════════════════════════════════════════════════════

class TestViewYearBounds(_BaseTest):
    def test_01_returns_year_bounds(self):
        self.assertEqual(
            view_year_bounds(self.fy_2017), ("2017-04-01", "2018-03-31")
        )

    def test_02_none_falls_back_to_active(self):
        self.assertEqual(
            view_year_bounds(None), ("2026-04-01", "2027-03-31")
        )

    def test_03_malformed_falls_back_to_active(self):
        for bad in ({"start_date": "", "end_date": ""}, {"start_date": "2017-04-01"}):
            self.assertEqual(
                view_year_bounds(bad), ("2026-04-01", "2027-03-31")
            )


# ══════════════════════════════════════════════════════════════════════
# 4-8: date boundaries (1 April .. 31 March, inclusive)
# ══════════════════════════════════════════════════════════════════════

class TestFinancialYearBoundaries(_BaseTest):
    def test_04_first_day_is_included(self):
        self._seed_sale("B-1", "2017-04-01")
        rows = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        self.assertEqual(self._dates(rows), ["2017-04-01"])

    def test_05_last_day_is_included(self):
        self._seed_sale("B-1", "2018-03-31")
        rows = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        self.assertEqual(self._dates(rows), ["2018-03-31"])

    def test_06_day_before_start_is_excluded(self):
        self._seed_sale("B-1", "2017-03-31")
        rows = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        self.assertEqual(rows, [])

    def test_07_day_after_end_is_excluded(self):
        self._seed_sale("B-1", "2018-04-01")
        rows = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        self.assertEqual(rows, [])

    def test_08_adjacent_years_do_not_mix(self):
        self._seed_sale("B-2016", "2016-05-02")
        self._seed_sale("B-2017a", "2017-04-01")
        self._seed_sale("B-2017b", "2018-03-31")
        self._seed_sale("B-2018", "2018-04-01")

        this_year = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        self.assertEqual(
            self._dates(this_year), ["2017-04-01", "2018-03-31"]
        )

        last_year = SalesReportDAO.get_sales_report(
            from_date="2016-04-01", to_date="2017-03-31"
        )["rows"]
        self.assertEqual(self._dates(last_year), ["2016-05-02"])

        # Unbounded — the old default — is what mixed every year together.
        everything = SalesReportDAO.get_sales_report()["rows"]
        self.assertEqual(len(self._dates(everything)), 4)


# ══════════════════════════════════════════════════════════════════════
# 9-16: report screens follow the financial-year selection
# ══════════════════════════════════════════════════════════════════════

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestReportScreensFollowFinancialYear(_BaseTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._app = QApplication.instance() or QApplication([])

    def _page(self, module_name, class_name):
        import importlib
        module = importlib.import_module(f"screens.{module_name}")
        return getattr(module, class_name)()

    def test_09_every_report_page_accepts_a_financial_year(self):
        pages = [
            ("sales_report", "SalesReportPage"),
            ("purchase_report", "PurchaseReportPage"),
            ("gst_report", "GSTReportPage"),
            ("party_wise_report", "PartyWiseReportPage"),
            ("trial_balance", "TrialBalancePage"),
            ("profit_loss", "ProfitLossPage"),
            ("balance_sheet", "BalanceSheetPage"),
            ("cash_book", "CashBookPage"),
            ("bank_book", "BankBookPage"),
        ]
        for module_name, class_name in pages:
            page = self._page(module_name, class_name)
            self.assertTrue(
                callable(getattr(page, "set_history_financial_year", None)),
                f"{class_name} does not follow the financial year",
            )

    def test_10_sales_report_opens_scoped_to_the_active_year(self):
        page = self._page("sales_report", "SalesReportPage")
        self.assertTrue(page.from_check.isChecked())
        self.assertTrue(page.to_check.isChecked())
        self.assertEqual(
            page._current_filters()["from_date"], "2026-04-01"
        )
        self.assertEqual(page._current_filters()["to_date"], "2027-03-31")

    def test_11_sales_report_shows_only_the_selected_years_rows(self):
        self._seed_sale("B-2016", "2016-05-02")
        self._seed_sale("B-2017", "2017-06-15")
        self._seed_sale("B-2026", "2026-05-05")

        page = self._page("sales_report", "SalesReportPage")
        page.set_history_financial_year(self.fy_2017)

        self.assertEqual(page.from_edit.date().toString("yyyy-MM-dd"), "2017-04-01")
        self.assertEqual(page.to_edit.date().toString("yyyy-MM-dd"), "2018-03-31")
        rows = [page._table.item(i, 1).text() for i in range(page._table.rowCount())]
        self.assertEqual(rows, ["2017-06-15"])

    def test_12_switching_back_and_forth_moves_the_range(self):
        page = self._page("sales_report", "SalesReportPage")

        page.set_history_financial_year(self.fy_2017)
        self.assertEqual(
            page._current_filters()["from_date"], "2017-04-01"
        )
        self.assertEqual(page._current_filters()["to_date"], "2018-03-31")

        page.set_history_financial_year(self.active)
        self.assertEqual(
            page._current_filters()["from_date"], "2026-04-01"
        )
        self.assertEqual(page._current_filters()["to_date"], "2027-03-31")

    def test_13_selecting_a_year_keeps_the_filter_ticked(self):
        page = self._page("sales_report", "SalesReportPage")
        page.from_check.setChecked(False)
        page.to_check.setChecked(False)
        page.set_history_financial_year(self.fy_2017)
        self.assertTrue(page.from_check.isChecked())
        self.assertTrue(page.to_check.isChecked())

    def test_14_purchase_report_follows_the_year(self):
        page = self._page("purchase_report", "PurchaseReportPage")
        page.set_history_financial_year(self.fy_2016)
        self.assertEqual(
            page._current_filters()["from_date"], "2016-04-01"
        )
        self.assertEqual(page._current_filters()["to_date"], "2017-03-31")

    def test_15_position_reports_move_to_the_year_end(self):
        for module_name, class_name in (
            ("trial_balance", "TrialBalancePage"),
            ("balance_sheet", "BalanceSheetPage"),
        ):
            page = self._page(module_name, class_name)
            page.set_history_financial_year(self.fy_2017)
            self.assertEqual(
                page.as_of_edit.date().toString("yyyy-MM-dd"), "2018-03-31",
                f"{class_name} as-of date did not follow the year",
            )

    def test_16_cash_book_follows_the_year(self):
        page = self._page("cash_book", "CashBookPage")
        page.set_history_financial_year(self.fy_2017)
        self.assertEqual(
            page._dates(), ("2017-04-01", "2018-03-31")
        )


# ══════════════════════════════════════════════════════════════════════
# 17-18: master data is not year-filtered
# ══════════════════════════════════════════════════════════════════════

class TestMasterDataAcrossYears(_BaseTest):
    def test_17_items_have_no_financial_year_column(self):
        conn = get_connection()
        try:
            columns = {
                r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()
            }
        finally:
            conn.close()
        self.assertNotIn("financial_year_id", columns)
        self.assertNotIn("fy_id", columns)

    def test_18_master_rows_survive_a_year_switch(self):
        from database.item_dao import ItemDAO
        from database.customer_dao import CustomerDAO

        before = len(ItemDAO.get_all())
        financial_year.set_active_financial_year(self.fy_2017["id"])
        self.assertEqual(len(ItemDAO.get_all()), before)
        self.assertTrue(CustomerDAO.get_all())


# ══════════════════════════════════════════════════════════════════════
# 19-22: back-entry confirmation
# ══════════════════════════════════════════════════════════════════════

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestConfirmTransactionDate(_BaseTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from ui import fy_view
        self._fy_view = fy_view

        class _Recorder:
            """Stands in for QMessageBox so no dialog is ever shown.

            ``Yes``/``No`` are the real standard-button flags as plain ints,
            because ``confirm_transaction_date`` combines them with ``|``.
            """

            Yes = 16384
            No = 65536

            def __init__(self):
                self.answer = self.No
                self.warnings = []
                self.questions = []

            def question(self, parent, title, text, *args, **kwargs):
                self.questions.append((title, text))
                return self.answer

            def warning(self, parent, title, text, *args, **kwargs):
                self.warnings.append((title, text))
                return None

        self._original = fy_view.QMessageBox
        self._Recorder = _Recorder

    def tearDown(self):
        self._fy_view.QMessageBox = self._original

    def _install(self, confirm: bool = False):
        recorder = self._Recorder()
        recorder.answer = self._Recorder.Yes if confirm else self._Recorder.No
        self._fy_view.QMessageBox = recorder
        return recorder

    def test_19_date_inside_active_year_is_silent(self):
        recorder = self._install()
        self.assertTrue(
            self._fy_view.confirm_transaction_date(None, "2026-05-05")
        )
        self.assertEqual(recorder.questions, [])
        self.assertEqual(recorder.warnings, [])

    def test_20_date_in_another_year_asks_and_yes_proceeds(self):
        recorder = self._install(confirm=True)
        self.assertTrue(
            self._fy_view.confirm_transaction_date(None, "2017-06-15")
        )
        self.assertEqual(len(recorder.questions), 1)
        self.assertIn("2017-2018", recorder.questions[0][1])

    def test_21_date_in_another_year_asks_and_no_cancels(self):
        recorder = self._install(confirm=False)
        self.assertFalse(
            self._fy_view.confirm_transaction_date(None, "2017-06-15")
        )
        self.assertEqual(len(recorder.questions), 1)

    def test_22_date_outside_every_year_is_refused(self):
        recorder = self._install(confirm=True)
        self.assertFalse(
            self._fy_view.confirm_transaction_date(None, "2015-01-01")
        )
        self.assertEqual(recorder.questions, [])
        self.assertEqual(len(recorder.warnings), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
