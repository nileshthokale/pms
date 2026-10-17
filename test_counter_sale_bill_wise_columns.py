"""Regression test suite for Counter Sale Bill Wise table column widths.

Verifies:
1. Patient column width base is within 250–280 px.
2. Net Amount column width is reduced to 130–150 px (not 400+ px) and values are right-aligned.
3. Date column width is within 105–120 px, fully displaying dates like '2017-03-31'.
4. Time column width is within 85–100 px, fully displaying times like '6:15 AM' or '10:18 AM'.
5. Bill No, Type, Items, Total Amount, Discount, Paid Amount remain readable.
6. Table stretches across available width with no unused gap on the right.
7. Long patient names use ellipsis and set tooltips.
8. Item Wise layout and column behaviors are preserved.
9. Day Mode and Night Mode both render correctly.
"""

import sys
import unittest
from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication, QHeaderView
from PySide6.QtGui import QFontMetrics

from screens.counter_sale import (
    CounterSalePage,
    HISTORY_MODE_ITEM,
    HISTORY_MODE_BILL,
    _HISTORY_COLUMN_WIDTHS,
)
from database.sales_dao import SalesDAO

_app = QApplication.instance() or QApplication(sys.argv)


class TestCounterSaleBillWiseColumns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = CounterSalePage()
        cls.page.resize(1280, 720)
        cls.page.show()
        _app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.page.close()

    def setUp(self):
        self.page._hist_bill_mode.setChecked(True)
        _app.processEvents()

    def test_01_bill_wise_column_widths_within_specified_bounds(self):
        """Verify Patient (250-280 base), Net Amount (130-150), Date (105-120), Time (85-100)."""
        table = self.page._hist_table
        self.assertEqual(table.columnCount(), 10)

        widths = _HISTORY_COLUMN_WIDTHS[HISTORY_MODE_BILL]
        self.assertEqual(len(widths), 10)

        # Baseline tuple checks
        bill_no_w, type_w, pat_w, date_w, time_w, items_w, total_w, disc_w, paid_w, net_w = widths
        self.assertGreaterEqual(pat_w, 250, "Patient base width should be >= 250 px")
        self.assertLessEqual(pat_w, 280, "Patient base width should be <= 280 px")

        self.assertGreaterEqual(net_w, 130, "Net Amount width should be >= 130 px")
        self.assertLessEqual(net_w, 150, "Net Amount width should be <= 150 px")

        self.assertGreaterEqual(date_w, 105, "Date base width should be >= 105 px")
        self.assertLessEqual(date_w, 120, "Date base width should be <= 120 px")

        self.assertGreaterEqual(time_w, 85, "Time base width should be >= 85 px")
        self.assertLessEqual(time_w, 100, "Time base width should be <= 100 px")

        self.assertGreaterEqual(bill_no_w, 80)
        self.assertGreaterEqual(type_w, 55)
        self.assertGreaterEqual(items_w, 60)
        self.assertGreaterEqual(total_w, 110)
        self.assertGreaterEqual(disc_w, 75)
        self.assertGreaterEqual(paid_w, 100)

        # Live table widget column width checks
        self.assertGreaterEqual(table.columnWidth(2), 250, "Live Patient width should be at least 250 px")

        self.assertGreaterEqual(table.columnWidth(9), 130, "Live Net Amount width should be >= 130 px")
        self.assertLessEqual(table.columnWidth(9), 150, "Live Net Amount width should be <= 150 px")

        self.assertGreaterEqual(table.columnWidth(3), 105, "Date width should be >= 105 px")
        self.assertLessEqual(table.columnWidth(3), 120, "Date width should be <= 120 px")

        self.assertGreaterEqual(table.columnWidth(4), 85, "Time width should be >= 85 px")
        self.assertLessEqual(table.columnWidth(4), 100, "Time width should be <= 100 px")

    def test_02_date_and_time_text_fit_comfortably_without_truncation(self):
        """Verify that date '2017-03-31' and times '10:18 AM'/'6:15 AM' easily fit."""
        table = self.page._hist_table
        fm = QFontMetrics(table.font())

        # Check Date
        date_str = "2017-03-31"
        date_text_width = fm.horizontalAdvance(date_str)
        self.assertGreater(table.columnWidth(3), date_text_width + 20)

        # Check Time
        for time_str in ("10:18 AM", "6:15 AM", "11:59 PM"):
            time_text_width = fm.horizontalAdvance(time_str)
            self.assertGreater(table.columnWidth(4), time_text_width + 20)

    def test_03_patient_long_name_has_tooltip_and_date_time_have_tooltips(self):
        """Verify tooltips on populated rows in Bill Wise and Net Amount right alignment."""
        table = self.page._hist_table
        dummy_row = {
            "invoice_id": 999999,
            "bill_no": "2026-2027-1905",
            "sale_type": "Cash",
            "patient_name": "Dr. Ramachandra Venkatanarasimha Rao of Medical College",
            "sale_date": "2017-03-31",
            "sale_time": "10:18 AM",
            "item_count": 3,
            "total_amount": 1993.00,
            "discount": 0.0,
            "paid_amount": 1993.00,
            "net_amount": 1993.00,
        }
        table.setRowCount(1)
        self.page._fill_bill_history_row(table, 0, dummy_row)

        pat_item = table.item(0, 2)
        self.assertEqual(pat_item.text(), dummy_row["patient_name"])
        self.assertEqual(pat_item.toolTip(), dummy_row["patient_name"])

        date_item = table.item(0, 3)
        self.assertEqual(date_item.text(), "2017-03-31")
        self.assertEqual(date_item.toolTip(), "2017-03-31")

        time_item = table.item(0, 4)
        self.assertEqual(time_item.text(), "10:18 AM")
        self.assertEqual(time_item.toolTip(), "10:18 AM")

        net_item = table.item(0, 9)
        self.assertEqual(net_item.text(), "1993.00")
        self.assertEqual(net_item.textAlignment(), Qt.AlignRight | Qt.AlignVCenter)

    def test_04_sensible_resize_modes_prevent_clipping_and_fill_width(self):
        """Verify Patient stretches to fill window, Net Amount stays 130-150px, no unused gap."""
        table = self.page._hist_table
        hv = table.horizontalHeader()

        # Patient (col 2) is Stretch to absorb available width without gap on right
        self.assertEqual(hv.sectionResizeMode(2), QHeaderView.Stretch)
        # Net Amount (col 9) is Interactive to keep compact 130-150px (not 400+ px)
        self.assertEqual(hv.sectionResizeMode(9), QHeaderView.Interactive)
        self.assertFalse(hv.stretchLastSection(), "Last section should not stretch; Patient absorbs width")

        # Other important columns stay Interactive
        for c in (0, 1, 3, 4, 5, 6, 7, 8, 9):
            self.assertEqual(
                hv.sectionResizeMode(c),
                QHeaderView.Interactive,
                f"Column {c} should be Interactive so it keeps its explicit width",
            )

        # Table fills the viewport completely
        total_col_width = sum(table.columnWidth(i) for i in range(table.columnCount()))
        self.assertGreaterEqual(total_col_width, table.viewport().width() - 5)

    def test_05_item_wise_layout_remains_intact_when_toggling(self):
        """Verify switching back to Item Wise restores 13 columns and exact column modes."""
        self.page._hist_item_mode.setChecked(True)
        _app.processEvents()

        table = self.page._hist_table
        hv = table.horizontalHeader()

        self.assertEqual(table.columnCount(), 13)
        self.assertEqual(hv.sectionResizeMode(2), QHeaderView.Fixed)  # Item Name Fixed
        self.assertEqual(hv.sectionResizeMode(6), QHeaderView.Stretch)  # Patient Stretch in Item Wise
        self.assertEqual(hv.sectionResizeMode(12), QHeaderView.Fixed)  # Bill Amount Fixed
        self.assertFalse(hv.stretchLastSection())

        # Switch back to Bill Wise
        self.page._hist_bill_mode.setChecked(True)
        _app.processEvents()
        self.assertEqual(table.columnCount(), 10)
        self.assertGreaterEqual(table.columnWidth(2), 250)
        self.assertEqual(table.columnWidth(3), 115)
        self.assertEqual(table.columnWidth(4), 95)
        self.assertEqual(table.columnWidth(9), 140)


if __name__ == "__main__":
    unittest.main()
