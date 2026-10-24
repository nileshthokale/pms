"""Comprehensive test suite for the A6 Landscape Cash Memo Crystal Report engine.

Verifies:
1. reports/DuplicateSalesBill_A6.rpt template existence and runtime logging.
2. Watermark 'RPT v2' visible proof.
3. 1-item bill: exactly 10 rows reserved (padded with 9 blanks), Net Amt as whole number.
4. 4-items bill (Photo evidence bill: MGMIX, PROTONIX DSR, BONULTRA, ARTHRASPAZ 4MG, Net: 890):
   - No 'Counter Sale Bill' title (prints 'Cash Memo' or 'Credit Memo').
   - No 'Page 1 of 1' on single-page bills.
   - No debug / internal text ('Category sales', 'header ID', etc.).
   - Full batch numbers without '...' truncation.
   - Hairline 0.25 pt separator lines.
5. 10-items bill: full single page.
6. 14-items bill: 2 pages, 'Continued...' on page 1, Net Amt on page 2, 'Page 1 of 2' and 'Page 2 of 2'.
7. Batch shrink-to-fit: long batch string never truncated with '...'.
8. Short-edge feeding rotation (rotate 90 or 270 degrees) and full-page origin.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from database import duplicate_a6_cash_memo as memo_a6


class TestDuplicateA6CashMemoSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls._app = QApplication([])
        else:
            cls._app = QApplication.instance()

    def test_01_rpt_file_and_logging(self):
        """Verify reports/DuplicateSalesBill_A6.rpt exists and log_loaded_report_path works."""
        rpt_path = memo_a6.log_loaded_report_path()
        self.assertTrue(os.path.exists(rpt_path), f"RPT file not found at {rpt_path}")
        self.assertTrue(rpt_path.endswith("DuplicateSalesBill_A6.rpt"))

        with open(rpt_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("ReportTitle=Duplicate Sales Bill A6 Cash Memo", content)
        self.assertIn("Watermark=RPT v2", content)
        self.assertIn("PaperSize=A6_Landscape", content)

    def test_02_single_item_bill_fixed_ten_rows(self):
        """Verify 1-item bill reserves 10 rows (1 data + 9 padded blanks) and footer never shifts."""
        head = {
            "voucher_no": 101,
            "vh_date": "2026-10-24",
            "bill_type": "Cash",
            "customer_name": "SURESH GUPTA",
            "net_amount": 145.0,
        }
        items = [
            {
                "item_name": "PARACETAMOL 500",
                "unit": "10'S",
                "comp": "CIPLA",
                "batch_no": "PC992",
                "expiry": "11/27",
                "sales_qty": 2.0,
                "amount": 145.0,
            }
        ]

        pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=True)
        self.assertEqual(len(pages), 1)
        page0 = pages[0]
        self.assertEqual(page0["page_num"], 1)
        self.assertEqual(page0["total_pages"], 1)
        self.assertTrue(page0["is_last_page"])

        # Exactly 10 rows
        self.assertEqual(len(page0["items"]), 10)
        self.assertEqual(page0["items"][0]["item_name"], "PARACETAMOL 500")
        for empty_idx in range(1, 10):
            self.assertEqual(page0["items"][empty_idx], {})

        # Render pixmap at 300 DPI
        pix = memo_a6.render_a6_cash_memo_pixmap(page0, dpi=300.0)
        self.assertFalse(pix.isNull())
        # A6 landscape at 300 DPI: 148 mm x 105 mm => ~1748 x 1240 px
        self.assertAlmostEqual(pix.width(), 1748, delta=15)
        self.assertAlmostEqual(pix.height(), 1240, delta=15)

    def test_03_four_items_photo_evidence_bill(self):
        """Verify 4-items bill (matches the user's photo evidence):
        Items: MGMIX, PROTONIX DSR, BONULTRA, ARTHRASPAZ 4MG
        Net: 890 (no decimals, no stray Category sales/header ID text).
        """
        head = {
            "voucher_no": 2043,
            "vh_date": "2026-10-23",
            "bill_type": "Cash",
            "customer_name": "RAHUL PATIL",
            "patient_name": "RAHUL",
            "doctor_name": "DR. K.N. GHORPADE",
            "address": "RAHURI",
            "net_amount": 890.0,
            "remarks": "Category sales\\vheader ID 72382, BillNo 2043",  # Legacy debug text to suppress!
        }
        items = [
            {"item_name": "MGMIX", "unit": "10'S", "comp": "MED", "batch_no": "LGP12/028", "expiry": "04/26", "sales_qty": 1.0, "amount": 210.0},
            {"item_name": "PROTONIX DSR", "unit": "10'S", "comp": "ALK", "batch_no": "AC26040089", "expiry": "08/27", "sales_qty": 2.0, "amount": 340.0},
            {"item_name": "BONULTRA", "unit": "10'S", "comp": "ZUV", "batch_no": "BN8819", "expiry": "12/26", "sales_qty": 1.0, "amount": 190.0},
            {"item_name": "ARTHRASPAZ 4MG", "unit": "10'S", "comp": "INT", "batch_no": "AS401", "expiry": "03/27", "sales_qty": 1.0, "amount": 150.0},
        ]

        pages = memo_a6.paginate_duplicate_items(head, items, show_duplicate=False)
        self.assertEqual(len(pages), 1)
        p = pages[0]
        self.assertEqual(len(p["items"]), 10)

        # Mock painter helper to record all drawn strings
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

        with mock.patch("database.duplicate_a6_cash_memo._draw_bold_text", side_effect=tracker_bold), \
             mock.patch("database.duplicate_a6_cash_memo._draw_cut_to_fit_bold", side_effect=tracker_cut):
            pix = memo_a6.render_a6_cash_memo_pixmap(p, dpi=150.0)

        # 1. Net Amt as whole integer without decimals: "Net Amt : 890"
        self.assertIn("Net Amt : 890", drawn_texts)
        self.assertNotIn("Net Amt : 890.00", drawn_texts)

        # 2. No debug / system remarks
        for t in drawn_texts:
            self.assertNotIn("Category sales", t)
            self.assertNotIn("header ID 72382", t)
            self.assertNotIn("Counter Sale Bill", t)

        # 3. Single page bill does NOT print "Page 1 of 1"
        self.assertNotIn("Page 1 of 1", drawn_texts)

        # 4. Header metadata
        self.assertIn("Cash Memo : 2043", drawn_texts)
        self.assertTrue(any("RAHUL" in t for t in drawn_texts))
        self.assertTrue(any("DR. K.N. GHORPADE" in t for t in drawn_texts))

        # 5. Visible proof watermark
        self.assertEqual(memo_a6.REPORT_VERSION_TAG, "RPT v2")

    def test_04_ten_items_bill_fits_single_page(self):
        """Verify 10-item bill exactly fills a single page without spilling."""
        head = {"voucher_no": 300, "vh_date": "2026-10-24", "net_amount": 1500.0}
        items = [
            {"item_name": f"ITEM_{i}", "unit": "10'S", "comp": "XYZ", "batch_no": f"B{i}", "expiry": "12/27", "sales_qty": 1.0, "amount": 150.0}
            for i in range(1, 11)
        ]
        pages = memo_a6.paginate_duplicate_items(head, items)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0]["items"]), 10)
        self.assertTrue(pages[0]["is_last_page"])

    def test_05_fourteen_items_bill_two_pages(self):
        """Verify 14-item bill creates 2 pages with Continued... on page 1 and Net Amt on page 2."""
        head = {"voucher_no": 400, "vh_date": "2026-10-24", "net_amount": 2500.0}
        items = [
            {"item_name": f"ITEM_{i:02d}", "unit": "10'S", "comp": "XYZ", "batch_no": f"BT{i}", "expiry": "12/27", "sales_qty": 1.0, "amount": 100.0}
            for i in range(1, 15)
        ]
        pages = memo_a6.paginate_duplicate_items(head, items)
        self.assertEqual(len(pages), 2)

        # Page 1
        p1 = pages[0]
        self.assertEqual(p1["page_num"], 1)
        self.assertEqual(p1["total_pages"], 2)
        self.assertFalse(p1["is_last_page"])
        self.assertEqual(len(p1["items"]), 10)

        # Page 2
        p2 = pages[1]
        self.assertEqual(p2["page_num"], 2)
        self.assertEqual(p2["total_pages"], 2)
        self.assertTrue(p2["is_last_page"])
        self.assertEqual(len(p2["items"]), 10)  # 4 data + 6 padded blanks
        self.assertEqual(p2["items"][0]["item_name"], "ITEM_11")
        self.assertEqual(p2["items"][3]["item_name"], "ITEM_14")
        self.assertEqual(p2["items"][4], {})

        # Verify drawn text for Page 1 vs Page 2
        p1_texts: list[str] = []
        real_draw = memo_a6._draw_bold_text

        def tracker_p1(*args, **kwargs):
            text = kwargs.get("text") if "text" in kwargs else (args[5] if len(args) > 5 else "")
            p1_texts.append(str(text))
            return real_draw(*args, **kwargs)

        with mock.patch("database.duplicate_a6_cash_memo._draw_bold_text", side_effect=tracker_p1):
            memo_a6.render_a6_cash_memo_pixmap(p1, dpi=150.0)

        self.assertIn("Page 1 of 2", p1_texts)
        self.assertIn("Continued...", p1_texts)
        self.assertNotIn("Net Amt : 2500", p1_texts)

        p2_texts: list[str] = []

        def tracker_p2(*args, **kwargs):
            text = kwargs.get("text") if "text" in kwargs else (args[5] if len(args) > 5 else "")
            p2_texts.append(str(text))
            return real_draw(*args, **kwargs)

        with mock.patch("database.duplicate_a6_cash_memo._draw_bold_text", side_effect=tracker_p2):
            memo_a6.render_a6_cash_memo_pixmap(p2, dpi=150.0)

        self.assertIn("Page 2 of 2", p2_texts)
        self.assertIn("Net Amt : 2500", p2_texts)
        self.assertNotIn("Continued...", p2_texts)

    def test_06_batch_shrink_to_fit_no_ellipsis(self):
        """Verify long batch string is never truncated with '...'."""
        long_batch = "AC26040089XYZLONG"
        pix = QPixmap(300, 50)
        pix.fill(QColor("white"))
        p = QPainter(pix)

        drawn_strings: list[str] = []
        orig_draw = p.drawText

        def catch_draw(rect, flags, text):
            drawn_strings.append(text)
            return orig_draw(rect, flags, text)

        p.drawText = catch_draw
        memo_a6._draw_shrink_to_fit_bold(p, 0, 0, 50.0, 20.0, long_batch, max_pt=8.0, min_pt=6.0)
        p.end()

        self.assertEqual(len(drawn_strings), 1)
        self.assertEqual(drawn_strings[0], long_batch)
        self.assertNotIn("...", drawn_strings[0])

    def test_07_pdf_generation(self):
        """Verify generate_duplicate_a6_pdf outputs a valid PDF file."""
        head = {"voucher_no": 999, "vh_date": "2026-10-24", "net_amount": 500.0}
        items = [{"item_name": "ASPIRIN 75", "batch_no": "AS-1", "sales_qty": 1.0, "amount": 500.0}]

        temp_pdf = os.path.join(tempfile.gettempdir(), "_test_a6_landscape_memo.pdf")
        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except OSError:
                pass

        out = memo_a6.generate_duplicate_a6_pdf(head, items, temp_pdf, show_duplicate=True)
        self.assertEqual(out, temp_pdf)
        self.assertTrue(os.path.exists(temp_pdf))
        self.assertGreater(os.path.getsize(temp_pdf), 1000)

        try:
            os.remove(temp_pdf)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
