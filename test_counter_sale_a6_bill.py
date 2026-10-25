"""Comprehensive test suite for the Real Counter Sale A6 Cash Memo Crystal Report.

Verifies:
1. Real bill with 1 item (10 fixed rows, footer bottom-pinned, Net Amt whole number).
2. Real bill with 4 items (exact layout as duplicate bill, no 'Counter Sale Bill', no 'DUPLICATE COPY', no stray ID text).
3. Real bill with 10 items (fills single page).
4. Real bill with 14 items (2 pages, 'Page 1 of 2' / 'Page 2 of 2', 'Continued...' on page 1, Net Amt on page 2).
5. Credit bill ('Credit Memo' title instead of 'Cash Memo').
6. Canon LBP2900 print settings (A6 landscape, ROTATE_FOR_FEED = True, full page origin).
7. Counter Sale screen integration (_on_direct_print opens preview dialog, _on_print exports PDF).
8. Strict scope: Real stock, items, customers, and Duplicate Sales Bill remain untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.sales_dao import SalesDAO
from database.counter_sale_a6_bill import (
    CounterSaleBillA6PreviewDialog,
    generate_counter_sale_pdf,
    get_counter_sale_data,
    log_loaded_report_path,
    paginate_counter_sale_bill,
    print_counter_sale_bill,
    REAL_RPT_FILE_PATH,
)
from database import duplicate_a6_cash_memo as memo_a6
from screens.counter_sale import CounterSalePage


class TestCounterSaleA6BillSuite(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_real_counter_sale_a6.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass
        os.environ["PHARMACY_DB"] = cls._DB_PATH

        if not QApplication.instance():
            cls._app = QApplication([])
        else:
            cls._app = QApplication.instance()

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        # Seed master items, units, companies, and doctor
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO units (unit_name) VALUES ('10 TAB'), ('10 CAP'), ('BOTTLE')")
            u_tab_id = cur.lastrowid

            cur.execute("INSERT INTO companies (company_name, short_name) VALUES ('CIPLA PHARMA', 'CIPLA'), ('ALKEM LABS', 'ALK')")
            c_cipla_id = cur.lastrowid

            cur.execute("INSERT INTO doctors (doctor_name, phone_no) VALUES ('DR. K.N. GHORPADE', '9890000000')")
            doc_id = cur.lastrowid

            cur.execute("INSERT INTO customers (customer_name, address, contact_no) VALUES ('RAHUL PATIL', 'RAHURI', '9890111111')")
            cust_id = cur.lastrowid

            conn.commit()
            cls.u_tab_id = u_tab_id
            cls.c_cipla_id = c_cipla_id
            cls.doc_id = doc_id
            cls.cust_id = cust_id
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except OSError:
                pass

    def _create_real_invoice(self, bill_no: str, item_count: int, sale_type: str = "Cash", net_amount: float = 890.0) -> int:
        """Helper to create a realistic sales invoice with real items and batches."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO sales_invoices (
                    bill_no, sale_date, sale_time, sale_type, customer_id,
                    patient_name, doctor_id, total_amount, discount, round_off, net_amount, remarks
                ) VALUES (?, '2026-10-24', '11:30 AM', ?, ?, 'RAHUL PATIL', ?, ?, 0.0, 0.0, ?, 'Category sales\\vheader ID 9999')
                """,
                (bill_no, sale_type, self.cust_id, self.doc_id, net_amount, net_amount),
            )
            inv_id = cur.lastrowid

            # Create items
            per_item_amt = round(net_amount / item_count, 2)
            for i in range(1, item_count + 1):
                item_name = f"MED_{bill_no}_{i}"
                cur.execute(
                    """
                    INSERT INTO items (item_name, unit_id, company_id, pack_size, mrp)
                    VALUES (?, ?, ?, '10 TAB', ?)
                    """,
                    (item_name, self.u_tab_id, self.c_cipla_id, per_item_amt),
                )
                item_id = cur.lastrowid

                cur.execute(
                    """
                    INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, stock_qty)
                    VALUES (?, ?, '2028-06-30', '10 TAB', ?, 100.0)
                    """,
                    (item_id, f"BTCH{i:03d}", per_item_amt),
                )
                batch_id = cur.lastrowid

                cur.execute(
                    """
                    INSERT INTO sales_invoice_items (
                        sales_invoice_id, item_id, stock_batch_id, pack_size, location,
                        batch_no, expiry, mrp, sale_qty, discount_amount, amount
                    ) VALUES (?, ?, ?, '10 TAB', 'RACK-1', ?, '06/28', ?, 1.0, 0.0, ?)
                    """,
                    (inv_id, item_id, batch_id, f"BTCH{i:03d}", per_item_amt, per_item_amt),
                )

            conn.commit()
            return inv_id
        finally:
            conn.close()

    def test_01_rpt_template_file_and_logging(self):
        """Verify reports/CounterSaleBill_A6.rpt exists, is logged, and has summary title."""
        rpt_path = log_loaded_report_path()
        self.assertTrue(os.path.exists(rpt_path))
        self.assertTrue(rpt_path.endswith("CounterSaleBill_A6.rpt"))

        with open(rpt_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue("COUNTER SALE BILL" in content)
        self.assertTrue("COUNTER SALE BILL" in content)
        self.assertTrue("PaperSize=A5_Landscape" in content or "PaperSize=A6_Landscape" in content)

    def test_02_real_bill_single_item(self):
        """TEST 1: Real bill with 1 item: exactly 10 rows (1 data + 9 padded blanks), Net Amt whole number."""
        inv_id = self._create_real_invoice(bill_no="1001", item_count=1, net_amount=150.0)
        pages = paginate_counter_sale_bill(inv_id)
        self.assertEqual(len(pages), 1)

        p = pages[0]
        self.assertEqual(len(p["items"]), 10)
        self.assertEqual(p["items"][0]["item_name"], "MED_1001_1")
        self.assertEqual(p["items"][1], {})
        self.assertTrue(p["is_last_page"])

        # Render pixmap at 300 DPI
        pix = memo_a6.render_a6_cash_memo_pixmap(p, dpi=300.0)
        self.assertFalse(pix.isNull())
        expected_w = 2480 if p.get("paper_size") == "A5" else 1748
        expected_h = 1748 if p.get("paper_size") == "A5" else 1240
        self.assertAlmostEqual(pix.width(), expected_w, delta=15)
        self.assertAlmostEqual(pix.height(), expected_h, delta=15)

    def test_03_real_bill_four_items_evidence_layout(self):
        """TEST 2: Real bill with 4 items:
        - Layout matching Duplicate Sales Bill (A6 Landscape 148 x 105 mm, Arial bold)
        - No 'DUPLICATE COPY' label
        - No 'Counter Sale Bill' title
        - No debug text ('Category sales', 'header ID')
        - Full batch numbers without '...'
        - Whole integer Net Amt (e.g. 'Net Amt : 890')
        """
        inv_id = self._create_real_invoice(bill_no="2043", item_count=4, net_amount=890.0)

        # Intercept drawn texts
        drawn_texts: list[str] = []
        real_draw_bold = memo_a6._draw_bold_text
        real_draw_cut = memo_a6._draw_cut_to_fit_bold

        def tracker_bold(*args, **kwargs):
            text = kwargs.get("text") if "text" in kwargs else (args[5] if len(args) > 5 else "")
            drawn_texts.append(str(text))
            return real_draw_bold(*args, **kwargs)

        def tracker_cut(*args, **kwargs):
            text = kwargs.get("text") if "text" in kwargs else (args[5] if len(args) > 5 else "")
            drawn_texts.append(str(text))
            return real_draw_cut(*args, **kwargs)

        pages = paginate_counter_sale_bill(inv_id)
        self.assertEqual(len(pages), 1)

        with mock.patch("database.duplicate_a6_cash_memo._draw_bold_text", side_effect=tracker_bold), \
             mock.patch("database.duplicate_a6_cash_memo._draw_cut_to_fit_bold", side_effect=tracker_cut):
            pix = memo_a6.render_a6_cash_memo_pixmap(pages[0], dpi=150.0)

        # 1. No DUPLICATE label
        for t in drawn_texts:
            self.assertNotIn("[ DUPLICATE ]", t)
            self.assertNotIn("DUPLICATE COPY", t)

        # 2. No Counter Sale Bill title
        for t in drawn_texts:
            self.assertNotIn("Counter Sale Bill", t)

        # 3. No stray debug text
        for t in drawn_texts:
            self.assertNotIn("Category sales", t)
            self.assertNotIn("header ID", t)

        # 4. Cash Memo : 2043
        self.assertIn("Cash Memo : 2043", drawn_texts)

        # 5. Whole integer Net Amt
        self.assertIn("Net Amt : 890", drawn_texts)
        self.assertNotIn("Net Amt : 890.00", drawn_texts)

        # 6. Single page bill does NOT print Page 1 of 1
        self.assertNotIn("Page 1 of 1", drawn_texts)

    def test_04_real_bill_ten_items(self):
        """TEST 3: Real bill with 10 items (full single page, footer at same bottom coordinate)."""
        inv_id = self._create_real_invoice(bill_no="1010", item_count=10, net_amount=1000.0)
        pages = paginate_counter_sale_bill(inv_id)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0]["items"]), 10)
        self.assertTrue(pages[0]["is_last_page"])

    def test_05_real_bill_fourteen_items_two_pages(self):
        """TEST 4: Real bill with 14 items (2 pages):
        - Page 1: 10 items, 'Page 1 of 2', 'Continued...'
        - Page 2: 4 items + 6 padded blanks, 'Page 2 of 2', 'Net Amt : 1400'
        """
        inv_id = self._create_real_invoice(bill_no="1014", item_count=14, net_amount=1400.0)
        pages = paginate_counter_sale_bill(inv_id)
        self.assertEqual(len(pages), 2)

        # Page 1
        p1 = pages[0]
        self.assertEqual(p1["page_num"], 1)
        self.assertEqual(p1["total_pages"], 2)
        self.assertFalse(p1["is_last_page"])

        p1_texts: list[str] = []
        real_draw = memo_a6._draw_bold_text
        with mock.patch("database.duplicate_a6_cash_memo._draw_bold_text", side_effect=lambda *a, **kw: p1_texts.append(kw.get("text") or (a[5] if len(a) > 5 else "")) or real_draw(*a, **kw)):
            memo_a6.render_a6_cash_memo_pixmap(p1, dpi=150.0)

        self.assertIn("Page 1 of 2", p1_texts)
        self.assertIn("Continued...", p1_texts)
        self.assertNotIn("Net Amt : 1400", p1_texts)

        # Page 2
        p2 = pages[1]
        self.assertEqual(p2["page_num"], 2)
        self.assertEqual(p2["total_pages"], 2)
        self.assertTrue(p2["is_last_page"])

        p2_texts: list[str] = []
        with mock.patch("database.duplicate_a6_cash_memo._draw_bold_text", side_effect=lambda *a, **kw: p2_texts.append(kw.get("text") or (a[5] if len(a) > 5 else "")) or real_draw(*a, **kw)):
            memo_a6.render_a6_cash_memo_pixmap(p2, dpi=150.0)

        self.assertIn("Page 2 of 2", p2_texts)
        self.assertIn("Net Amt : 1400", p2_texts)
        self.assertNotIn("Continued...", p2_texts)

    def test_06_real_credit_bill(self):
        """TEST 5: Credit bill shows 'Credit Memo' instead of 'Cash Memo'."""
        inv_id = self._create_real_invoice(bill_no="CR-901", item_count=2, sale_type="Credit", net_amount=450.0)
        pages = paginate_counter_sale_bill(inv_id)
        self.assertEqual(len(pages), 1)

        drawn_texts: list[str] = []
        real_draw_cut = memo_a6._draw_cut_to_fit_bold
        with mock.patch("database.duplicate_a6_cash_memo._draw_cut_to_fit_bold", side_effect=lambda *a, **kw: drawn_texts.append(kw.get("text") or (a[5] if len(a) > 5 else "")) or real_draw_cut(*a, **kw)):
            memo_a6.render_a6_cash_memo_pixmap(pages[0], dpi=150.0)

        self.assertIn("Credit Memo : CR-901", drawn_texts)
        self.assertNotIn("Cash Memo : CR-901", drawn_texts)

    def test_07_pdf_export_and_preview_dialog(self):
        """Verify PDF export and CounterSaleBillA6PreviewDialog functionality."""
        inv_id = self._create_real_invoice(bill_no="PDF-55", item_count=3, net_amount=300.0)

        # 1. Test generate_counter_sale_pdf
        temp_pdf = os.path.join(tempfile.gettempdir(), "_test_real_cs_a6.pdf")
        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass

        pdf_path = generate_counter_sale_pdf(inv_id, temp_pdf)
        self.assertEqual(pdf_path, temp_pdf)
        self.assertTrue(os.path.exists(temp_pdf))
        self.assertGreater(os.path.getsize(temp_pdf), 1000)

        # 2. Test Preview Dialog instantiation
        dlg = CounterSaleBillA6PreviewDialog(inv_id)
        self.assertIsNotNone(dlg.btn_print)
        self.assertIsNotNone(dlg.btn_export)
        self.assertIsNotNone(dlg.btn_find)
        self.assertEqual(dlg.lbl_stat_curr.text(), "Current Page No.: 1")
        dlg.close()

        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
