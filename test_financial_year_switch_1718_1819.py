"""FY 2017-2018 vs 2018-2019 report-filter switching tests.

Proves that selecting a financial year from the navbar scopes every
applicable report to that year's inclusive 1 April - 31 March range,
preserving original transaction dates.

Scope / safety:
- Uses an isolated temporary SQLite database (``_test_fy_switch_1718_1819.db``).
- Never touches ``data/pharmacy.db``, the source SQL dump, production
  database, EXE, or ``dist/``.
- Never imports or modifies stock balances in the real database; test
  batches live only in the temporary database.
- Historical display is NOT claimed here: the development database
  currently contains no historical transactions (see audit below), so
  these tests prove filter movement + DAO isolation on seeded data.

Numbered tests:
 1-2:   view_year_bounds for 2017-2018 and 2018-2019
 3-6:   inclusive boundaries (1 Apr and 31 Mar included, neighbours excluded)
 7-8:   DAO isolation between the two years (sales + purchase) with dates preserved
 9:     every applicable report page exposes set_history_financial_year
 10-13: period-report filters switch (sales / purchase / GST / party-wise)
 14-15: P&L range switches; Trial Balance + Balance Sheet move to year-end
 16-17: Cash Book + Bank Book ranges switch
 18:     switching is view-only (active year unchanged, nothing written)
 19:     seeded transaction dates are preserved verbatim after switches
 20:     adjacent-year boundary rows never mix (2018-03-31 vs 2018-04-01)
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database import financial_year
from database.sales_report_dao import SalesReportDAO
from database.purchase_report_dao import PurchaseReportDAO

from ui.fy_view import view_year_bounds

try:
    from PySide6.QtWidgets import QApplication
    HAS_PYSIDE6 = True
    _PYSIDE_SKIP = ""
except ImportError as _exc:  # pragma: no cover
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP = f"PySide6 not available ({_exc})"


FY_1718 = ("2017-2018", "2017-04-01", "2018-03-31")
FY_1819 = ("2018-2019", "2018-04-01", "2019-03-31")

TABLES = [
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class _Base(unittest.TestCase):
    _DB_PATH = os.path.join(
        os.path.dirname(__file__), "_test_fy_switch_1718_1819.db"
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
            self.supplier_id = conn.execute(
                "INSERT INTO suppliers (supplier_name) VALUES ('SupplierA')"
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
        financial_year.create_financial_year(*FY_1718)
        self.fy_1718 = financial_year.get_financial_year_for_date("2017-06-01")
        self.fy_1819 = financial_year.create_financial_year(
            *FY_1819, activate=True
        )
        self.active = financial_year.get_active_financial_year()

    def _seed_sale(self, bill_no, sale_date, amount=100.0):
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

    def _seed_purchase(self, voucher_no, voucher_date):
        conn = get_connection()
        try:
            inv = conn.execute(
                "INSERT INTO purchase_invoices (voucher_no, voucher_date,"
                " supplier_id, net_amount) VALUES (?, ?, ?, 50.0)",
                (voucher_no, voucher_date, self.supplier_id),
            ).lastrowid
            conn.execute(
                "INSERT INTO purchase_invoice_items (purchase_invoice_id,"
                " item_id, pay_qty, rate, amount)"
                " VALUES (?, ?, 1, 50.0, 50.0)",
                (inv, self.item_id),
            )
            conn.commit()
            return inv
        finally:
            conn.close()


class TestBounds1718Vs1819(_Base):
    def test_01_view_bounds_1718(self):
        self.assertEqual(
            view_year_bounds(self.fy_1718), ("2017-04-01", "2018-03-31")
        )

    def test_02_view_bounds_1819(self):
        self.assertEqual(
            view_year_bounds(self.fy_1819), ("2018-04-01", "2019-03-31")
        )

    def test_03_first_day_1718_included(self):
        self._seed_sale("S-START-1718", "2017-04-01")
        rows = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        self.assertEqual([r["sale_date"] for r in rows], ["2017-04-01"])

    def test_04_last_day_1718_included(self):
        self._seed_sale("S-END-1718", "2018-03-31")
        rows = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        self.assertEqual([r["sale_date"] for r in rows], ["2018-03-31"])

    def test_05_first_day_1819_included(self):
        self._seed_sale("S-START-1819", "2018-04-01")
        rows = SalesReportDAO.get_sales_report(
            from_date="2018-04-01", to_date="2019-03-31"
        )["rows"]
        self.assertEqual([r["sale_date"] for r in rows], ["2018-04-01"])

    def test_06_last_day_1819_included(self):
        self._seed_sale("S-END-1819", "2019-03-31")
        rows = SalesReportDAO.get_sales_report(
            from_date="2018-04-01", to_date="2019-03-31"
        )["rows"]
        self.assertEqual([r["sale_date"] for r in rows], ["2019-03-31"])

    def test_07_neighbours_excluded(self):
        # Day before 2017-2018 and day after 2018-2019 must not leak in.
        self._seed_sale("S-BEFORE", "2017-03-31")
        self._seed_sale("S-AFTER", "2019-04-01")
        fy17 = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        fy18 = SalesReportDAO.get_sales_report(
            from_date="2018-04-01", to_date="2019-03-31"
        )["rows"]
        self.assertEqual(fy17, [])
        self.assertEqual(fy18, [])

    def test_08_dao_isolation_preserves_dates(self):
        self._seed_sale("S-1718", "2017-06-15")
        self._seed_sale("S-1819", "2018-06-15")
        self._seed_purchase("P-1718", "2017-06-15")
        self._seed_purchase("P-1819", "2018-06-15")

        sales_17 = SalesReportDAO.get_sales_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        sales_18 = SalesReportDAO.get_sales_report(
            from_date="2018-04-01", to_date="2019-03-31"
        )["rows"]
        self.assertEqual(
            [r["sale_date"] for r in sales_17], ["2017-06-15"]
        )
        self.assertEqual(
            [r["sale_date"] for r in sales_18], ["2018-06-15"]
        )

        purch_17 = PurchaseReportDAO.get_purchase_report(
            from_date="2017-04-01", to_date="2018-03-31"
        )["rows"]
        purch_18 = PurchaseReportDAO.get_purchase_report(
            from_date="2018-04-01", to_date="2019-03-31"
        )["rows"]
        self.assertEqual(
            [r["voucher_date"] for r in purch_17], ["2017-06-15"]
        )
        self.assertEqual(
            [r["voucher_date"] for r in purch_18], ["2018-06-15"]
        )


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP)
class TestReportFiltersSwitch1718Vs1819(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._app = QApplication.instance() or QApplication([])

    def _page(self, module_name, class_name):
        import importlib
        module = importlib.import_module(f"screens.{module_name}")
        return getattr(module, class_name)()

    def test_09_every_applicable_report_accepts_a_financial_year(self):
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

    def test_10_sales_filters_switch_1718_to_1819(self):
        page = self._page("sales_report", "SalesReportPage")
        page.set_history_financial_year(self.fy_1718)
        self.assertEqual(
            page._current_filters()["from_date"], "2017-04-01"
        )
        self.assertEqual(
            page._current_filters()["to_date"], "2018-03-31"
        )
        page.set_history_financial_year(self.fy_1819)
        self.assertEqual(
            page._current_filters()["from_date"], "2018-04-01"
        )
        self.assertEqual(
            page._current_filters()["to_date"], "2019-03-31"
        )

    def test_11_purchase_filters_switch_1718_to_1819(self):
        page = self._page("purchase_report", "PurchaseReportPage")
        page.set_history_financial_year(self.fy_1718)
        self.assertEqual(
            page._current_filters()["from_date"], "2017-04-01"
        )
        self.assertEqual(
            page._current_filters()["to_date"], "2018-03-31"
        )
        page.set_history_financial_year(self.fy_1819)
        self.assertEqual(
            page._current_filters()["from_date"], "2018-04-01"
        )
        self.assertEqual(
            page._current_filters()["to_date"], "2019-03-31"
        )

    def test_12_gst_and_partywise_switch_1718_to_1819(self):
        gst = self._page("gst_report", "GSTReportPage")
        gst.set_history_financial_year(self.fy_1718)
        self.assertEqual(gst._current_filters()["from_date"], "2017-04-01")
        self.assertEqual(gst._current_filters()["to_date"], "2018-03-31")
        gst.set_history_financial_year(self.fy_1819)
        self.assertEqual(gst._current_filters()["from_date"], "2018-04-01")
        self.assertEqual(gst._current_filters()["to_date"], "2019-03-31")

        party = self._page("party_wise_report", "PartyWiseReportPage")
        party.set_history_financial_year(self.fy_1718)
        self.assertEqual(
            party._current_filters()["from_date"], "2017-04-01"
        )
        self.assertEqual(
            party._current_filters()["to_date"], "2018-03-31"
        )
        party.set_history_financial_year(self.fy_1819)
        self.assertEqual(
            party._current_filters()["from_date"], "2018-04-01"
        )
        self.assertEqual(
            party._current_filters()["to_date"], "2019-03-31"
        )

    def test_13_sales_rows_follow_the_switch(self):
        self._seed_sale("S-1718", "2017-06-15")
        self._seed_sale("S-1819", "2018-06-15")
        page = self._page("sales_report", "SalesReportPage")
        page.set_history_financial_year(self.fy_1718)
        rows_17 = [
            page._table.item(i, 1).text()
            for i in range(page._table.rowCount())
        ]
        self.assertEqual(rows_17, ["2017-06-15"])
        page.set_history_financial_year(self.fy_1819)
        rows_18 = [
            page._table.item(i, 1).text()
            for i in range(page._table.rowCount())
        ]
        self.assertEqual(rows_18, ["2018-06-15"])

    def test_14_profit_loss_range_switches(self):
        page = self._page("profit_loss", "ProfitLossPage")
        page.set_history_financial_year(self.fy_1718)
        self.assertEqual(
            page.from_edit.date().toString("yyyy-MM-dd"), "2017-04-01"
        )
        self.assertEqual(
            page.to_edit.date().toString("yyyy-MM-dd"), "2018-03-31"
        )
        page.set_history_financial_year(self.fy_1819)
        self.assertEqual(
            page.from_edit.date().toString("yyyy-MM-dd"), "2018-04-01"
        )
        self.assertEqual(
            page.to_edit.date().toString("yyyy-MM-dd"), "2019-03-31"
        )

    def test_15_position_reports_move_to_year_end(self):
        for module_name, class_name in (
            ("trial_balance", "TrialBalancePage"),
            ("balance_sheet", "BalanceSheetPage"),
        ):
            page = self._page(module_name, class_name)
            page.set_history_financial_year(self.fy_1718)
            self.assertEqual(
                page.as_of_edit.date().toString("yyyy-MM-dd"),
                "2018-03-31",
                f"{class_name} did not move to 2017-2018 year-end",
            )
            page.set_history_financial_year(self.fy_1819)
            self.assertEqual(
                page.as_of_edit.date().toString("yyyy-MM-dd"),
                "2019-03-31",
                f"{class_name} did not move to 2018-2019 year-end",
            )

    def test_16_cash_and_bank_ranges_switch(self):
        cash = self._page("cash_book", "CashBookPage")
        cash.set_history_financial_year(self.fy_1718)
        self.assertEqual(cash._dates(), ("2017-04-01", "2018-03-31"))
        cash.set_history_financial_year(self.fy_1819)
        self.assertEqual(cash._dates(), ("2018-04-01", "2019-03-31"))

        bank = self._page("bank_book", "BankBookPage")
        bank.set_history_financial_year(self.fy_1718)
        self.assertEqual(bank._dates(), ("2017-04-01", "2018-03-31"))
        bank.set_history_financial_year(self.fy_1819)
        self.assertEqual(bank._dates(), ("2018-04-01", "2019-03-31"))

    def test_17_switching_back_and_forth_moves_the_range(self):
        page = self._page("sales_report", "SalesReportPage")
        page.set_history_financial_year(self.fy_1718)
        page.set_history_financial_year(self.fy_1819)
        page.set_history_financial_year(self.fy_1718)
        self.assertEqual(
            page._current_filters()["from_date"], "2017-04-01"
        )
        self.assertEqual(
            page._current_filters()["to_date"], "2018-03-31"
        )

    def test_18_switching_is_view_only_active_unchanged(self):
        before = financial_year.get_active_financial_year()["id"]
        page = self._page("sales_report", "SalesReportPage")
        page.set_history_financial_year(self.fy_1718)
        after = financial_year.get_active_financial_year()["id"]
        self.assertEqual(before, after)
        self.assertEqual(after, self.fy_1819["id"])
        # No rows were rewritten by viewing.
        conn = get_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM sales_invoices"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_19_seeded_dates_preserved_verbatim(self):
        self._seed_sale("S-1718", "2017-06-15")
        self._seed_sale("S-1819", "2018-06-15")
        page = self._page("sales_report", "SalesReportPage")
        page.set_history_financial_year(self.fy_1718)
        page.set_history_financial_year(self.fy_1819)
        conn = get_connection()
        try:
            dates = sorted(
                r[0]
                for r in conn.execute(
                    "SELECT sale_date FROM sales_invoices ORDER BY sale_date"
                ).fetchall()
            )
        finally:
            conn.close()
        self.assertEqual(dates, ["2017-06-15", "2018-06-15"])

    def test_20_boundary_rows_never_mix(self):
        self._seed_sale("S-END-1718", "2018-03-31")
        self._seed_sale("S-START-1819", "2018-04-01")
        page = self._page("sales_report", "SalesReportPage")
        page.set_history_financial_year(self.fy_1718)
        rows_17 = [
            page._table.item(i, 1).text()
            for i in range(page._table.rowCount())
        ]
        self.assertEqual(rows_17, ["2018-03-31"])
        page.set_history_financial_year(self.fy_1819)
        rows_18 = [
            page._table.item(i, 1).text()
            for i in range(page._table.rowCount())
        ]
        self.assertEqual(rows_18, ["2018-04-01"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
