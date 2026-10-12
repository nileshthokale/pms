"""Focused acceptance coverage for the FY-bounded Purchase Report."""

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database import financial_year
from database.document_printing import generate_purchase_report_pdf
from database.purchase_report_dao import PurchaseReportDAO

try:
    from PySide6.QtWidgets import QApplication
    from screens.purchase_report import PurchaseReportPage
    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


class _PurchaseReportFixture(unittest.TestCase):
    db_path = os.path.join(os.path.dirname(__file__), "_test_purchase_report_fy.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path
        init_database()

    def setUp(self):
        conn = get_connection()
        try:
            for table in ("purchase_invoice_items", "purchase_invoices", "items", "suppliers", "units", "companies", "financial_years"):
                conn.execute(f"DELETE FROM {table}")
            self.company = conn.execute("INSERT INTO companies (company_name, short_name) VALUES ('Acme Pharma', 'ACME')").lastrowid
            self.company_two = conn.execute("INSERT INTO companies (company_name, short_name) VALUES ('Other Pharma', 'OTHER')").lastrowid
            unit = conn.execute("INSERT INTO units (unit_name) VALUES ('Pcs')").lastrowid
            self.item = conn.execute("INSERT INTO items (item_name, unit_id, company_id) VALUES ('Pain Relief', ?, ?)", (unit, self.company)).lastrowid
            self.item_two = conn.execute("INSERT INTO items (item_name, unit_id, company_id) VALUES ('Vitamin C', ?, ?)", (unit, self.company_two)).lastrowid
            self.supplier = conn.execute("INSERT INTO suppliers (supplier_name) VALUES ('Alpha Distributors')").lastrowid
            self.supplier_two = conn.execute("INSERT INTO suppliers (supplier_name) VALUES ('Beta Distributors')").lastrowid
            conn.commit()
        finally:
            conn.close()
        self.fy_2017 = financial_year.create_financial_year("2017-2018", "2017-04-01", "2018-03-31")
        self.fy_2018 = financial_year.create_financial_year("2018-2019", "2018-04-01", "2019-03-31")
        self.fy_2026 = financial_year.create_financial_year("2026-2027", "2026-04-01", "2027-03-31", activate=True)

    def purchase(self, voucher, date, *, supplier=None, item=None, invoice="INV-A", batch="B-01"):
        conn = get_connection()
        try:
            purchase_id = conn.execute(
                "INSERT INTO purchase_invoices (voucher_no, voucher_date, supplier_id, invoice_no, total_amount, net_amount) VALUES (?, ?, ?, ?, 10, 10)",
                (voucher, date, supplier or self.supplier, invoice),
            ).lastrowid
            conn.execute(
                "INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, pay_qty, rate, amount, purchase_rate, net_rate) VALUES (?, ?, ?, 1, 10, 10, 10, 10)",
                (purchase_id, item or self.item, batch),
            )
            conn.commit()
        finally:
            conn.close()


class TestPurchaseReportQueryBoundaries(_PurchaseReportFixture):
    def test_voucher_date_bounds_are_inclusive_and_filters_combine(self):
        self.purchase("PV-before", "2017-03-31")
        self.purchase("PV-first", "2017-04-01", invoice="IN-2017", batch="MATCH")
        self.purchase("PV-last", "2018-03-31", supplier=self.supplier_two, item=self.item_two)
        self.purchase("PV-next", "2018-04-01")
        report = PurchaseReportDAO.get_purchase_report(from_date="2017-04-01", to_date="2018-03-31")
        self.assertEqual([row["voucher_no"] for row in report["rows"]], ["PV-first", "PV-last"])
        combined = PurchaseReportDAO.get_purchase_report(
            from_date="2017-04-01", to_date="2018-03-31", supplier_id=self.supplier,
            company_id=self.company, item_id=self.item, invoice_no="2017", batch_no="MATCH",
        )
        self.assertEqual([row["voucher_no"] for row in combined["rows"]], ["PV-first"])


@unittest.skipUnless(HAS_QT, "PySide6 is required for Purchase Report UI tests")
class TestPurchaseReportFinancialYearView(_PurchaseReportFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def dates_in_page(self, page):
        return [page._table.item(row, 1).text() for row in range(page._table.rowCount())]

    def test_opening_defaults_to_active_financial_year(self):
        self.purchase("PV-old", "2017-06-15")
        self.purchase("PV-current", "2026-04-01")
        page = PurchaseReportPage()
        self.assertEqual(page._current_filters()["from_date"], "2026-04-01")
        self.assertEqual(page._current_filters()["to_date"], "2027-03-31")
        self.assertEqual(self.dates_in_page(page), ["2026-04-01"])

    def test_switch_clear_refresh_and_back_never_escape_selected_year(self):
        self.purchase("PV-2017a", "2017-04-01")
        self.purchase("PV-2017b", "2018-03-31")
        self.purchase("PV-2018", "2018-04-01")
        self.purchase("PV-2026", "2026-04-01")
        page = PurchaseReportPage()
        active_id = financial_year.get_active_financial_year()["id"]
        for year, expected in (
            (self.fy_2017, ["2017-04-01", "2018-03-31"]),
            (self.fy_2018, ["2018-04-01"]),
            (self.fy_2026, ["2026-04-01"]),
            (self.fy_2017, ["2017-04-01", "2018-03-31"]),
        ):
            page.set_history_financial_year(year)
            self.assertEqual(self.dates_in_page(page), expected)
            self.assertEqual(financial_year.get_active_financial_year()["id"], active_id)
        page._on_clear()
        page._on_refresh()
        self.assertEqual(page._current_filters()["from_date"], "2017-04-01")
        self.assertEqual(page._current_filters()["to_date"], "2018-03-31")
        self.assertEqual(self.dates_in_page(page), ["2017-04-01", "2018-03-31"])

    def test_supplier_company_and_item_autocomplete_select_database_ids(self):
        page = PurchaseReportPage()
        for edit, text, expected_id in (
            (page.supplier_edit, "pha dis", self.supplier),
            (page.company_edit, "cme ph", self.company),
            (page.item_edit, "in rel", self.item),
        ):
            edit._on_text_edited(text)
            self.assertEqual(edit.completer().completionCount(), 1)
            edit._on_completion_activated(edit.completer().completionModel().index(0, 0))
            self.assertEqual(edit.selected_id, expected_id)
        filters = page._current_filters()
        self.assertEqual(filters["supplier_id"], self.supplier)
        self.assertEqual(filters["company_id"], self.company)
        self.assertEqual(filters["item_id"], self.item)


class TestPurchaseReportPrint(unittest.TestCase):
    def test_pdf_is_landscape_paginated_and_has_filters_and_totals(self):
        rows = [{"voucher_no": f"PV-{i:03d}", "voucher_date": "2018-04-01", "invoice_no": "INV",
                 "invoice_date": "2018-04-01", "supplier_name": "Alpha", "item_name": "Item",
                 "company_name": "Acme", "pack_size": "10x10", "batch_no": "B", "expiry": "12/27",
                 "pay_qty": 1, "free_qty": 0, "rate": 10, "mrp": 12, "discount": 0, "gst_percent": 5,
                 "gst_amount": .5, "amount": 10, "purchase_rate": 10, "net_rate": 10} for i in range(40)]
        summary = {"total_bills": 40, "total_pay_qty": 40, "total_free_qty": 0,
                   "total_gross": 400, "total_gst": 20, "total_discount": 0, "total_net": 420}
        with tempfile.TemporaryDirectory() as directory:
            path = generate_purchase_report_pdf(rows, summary, "2018-2019", "Financial year: 2018-2019 | Supplier: Alpha", os.path.join(directory, "report.pdf"))
            with open(path, "rb") as pdf:
                content = pdf.read().decode("latin-1")
        self.assertIn("/MediaBox [0 0 842 595]", content)
        self.assertIn("Financial Year: 2018-2019", content)
        self.assertIn("Totals: Bills: 40", content)
        self.assertIn("Page 1 of 2", content)
        self.assertGreaterEqual(content.count("Voucher"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
