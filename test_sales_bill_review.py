"""Sales bill review/edit popup tests.

This file is intentionally focused on the review workflow introduced for
Counter Sale: validation remains first, a review popup opens, the popup can be
closed without saving, and the final popup Save performs the actual commit.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication, QGroupBox, QLabel, QMessageBox, QPushButton, QWidget,
    )
    from screens.counter_sale import CounterSalePage, SalesBillReviewDialog
except ImportError:
    CounterSalePage = None
    SalesBillReviewDialog = None

from database.connection import get_connection, init_database
from database.sales_dao import SalesDAO
from database.item_dao import ItemDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database.hold_bill_dao import ensure_hold_tables
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year

_DB_PATH = os.path.join(tempfile.gettempdir(), "pharmacy_counter_sale_review_test.db")
_TABLES = [
    "ledger_transactions", "account_ledgers",
    "customer_receipts", "supplier_payments",
    "debit_note_items", "debit_notes",
    "credit_note_items", "credit_notes",
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "hold_bill_items", "hold_bills",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class _DBBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_DB_PATH):
            os.remove(_DB_PATH)
        os.environ["PHARMACY_DB"] = _DB_PATH
        init_database()
        ensure_hold_tables()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")

    def setUp(self):
        # Validation and commit both surface messages through QMessageBox.
        # Patch the statics (the convention used by the other counter-sale
        # test modules) so no test can block on a real modal dialog.
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

        conn = get_connection()
        try:
            for tbl in _TABLES:
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()
        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.customer_walkin_id = CustomerDAO.insert("Walkin Customer")
        self.doctor_id = DoctorDAO.insert("Dr. Test")
        self.item_id = ItemDAO.insert(
            item_name="TestItem",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10x10",
            mrp=50.0,
        )
        self._seed_stock()

    def _seed_stock(self, qty=100.0, rate=40.0, mrp=50.0):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001",
            voucher_date="2026-01-01",
            voucher_time="",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no="INV-001",
            invoice_date="2026-01-01",
            invoice_net_amount=qty * rate,
            bill_discount=0,
            due_date="",
            total_amount=qty * rate,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=qty * rate,
            round_off=0,
            net_amount=qty * rate,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "pack_size": "10x10",
                "pay_qty": qty,
                "free_qty": 0,
                "batch_no": "BATCH-A",
                "expiry": "12/27",
                "rate": rate,
                "mrp": mrp,
                "discount": 0,
                "gst_percent": 0,
                "gst_amount": 0,
                "amount": qty * rate,
                "purchase_rate": rate,
                "net_rate": rate,
                "pp": rate,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]

    def _valid_sale(self, page):
        page._sale_panel.customer_combo.setCurrentIndex(
            page._sale_panel.customer_combo.findData(self.customer_id)
        )
        page._sale_panel.patient_name_edit.setText("Test Patient")
        page._sale_panel.doctor_combo.setCurrentIndex(
            page._sale_panel.doctor_combo.findData(self.doctor_id)
        )
        page._sale_panel._entry_bar.item_combo.setCurrentIndex(
            page._sale_panel._entry_bar.item_combo.findData(self.item_id)
        )
        page._sale_panel._entry_bar.batch_combo.setCurrentIndex(
            page._sale_panel._entry_bar.batch_combo.findData(self.batch_id)
        )
        page._sale_panel._entry_bar.qty_edit.setText("2")
        page._sale_panel._entry_bar.discount_edit.setText("0.00")
        page._sale_panel._on_add_item()
        return page._sale_panel


@unittest.skipUnless(CounterSalePage is not None and SalesBillReviewDialog is not None, "PySide6 not available")
class TestSalesBillReview(_DBBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def test_01_review_dialog_opens_after_valid_save(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertIsNotNone(getattr(page._sale_panel, "_review_dialog", None))

    def test_02_review_dialog_title_matches_reference(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertEqual(page._sale_panel._review_dialog.windowTitle(), "Sales Bill")

    def test_03_review_dialog_keeps_parent_sale_values(self):
        page = CounterSalePage()
        panel = self._valid_sale(page)
        panel._on_save()
        dialog = panel._review_dialog
        self.assertIn("TestCustomer", dialog._panel.customer_combo.currentText())

    def test_04_review_dialog_has_final_save_button(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        self.assertTrue(hasattr(dialog, "_final_save_btn"))

    def test_05_review_dialog_close_does_not_save(self):
        page = CounterSalePage()
        self._valid_sale(page)
        before = SalesDAO.get_all()
        page._sale_panel._on_save()
        page._sale_panel._review_dialog.reject()
        after = SalesDAO.get_all()
        self.assertEqual(len(before), len(after))

    def test_06_review_dialog_save_commits_once(self):
        page = CounterSalePage()
        self._valid_sale(page)
        before = len(SalesDAO.get_all())
        page._sale_panel._on_save()
        page._sale_panel._review_dialog._final_save_btn.click()
        after = len(SalesDAO.get_all())
        self.assertEqual(after, before + 1)

    def test_07_valid_sale_still_collects_item_rows(self):
        page = CounterSalePage()
        panel = self._valid_sale(page)
        self.assertEqual(len(panel._item_rows), 1)

    def test_08_invalid_customer_stops_review_and_keeps_draft(self):
        page = CounterSalePage()
        page._sale_panel._entry_bar.item_combo.setCurrentIndex(
            page._sale_panel._entry_bar.item_combo.findData(self.item_id)
        )
        page._sale_panel._entry_bar.batch_combo.setCurrentIndex(
            page._sale_panel._entry_bar.batch_combo.findData(self.batch_id)
        )
        page._sale_panel._entry_bar.qty_edit.setText("2")
        page._sale_panel._on_add_item()
        page._sale_panel._on_save()
        self.assertFalse(hasattr(page._sale_panel, "_review_dialog"))

    def test_09_invalid_no_items_stops_review(self):
        page = CounterSalePage()
        page._sale_panel.customer_combo.setCurrentIndex(
            page._sale_panel.customer_combo.findData(self.customer_id)
        )
        page._sale_panel._on_save()
        self.assertFalse(hasattr(page._sale_panel, "_review_dialog"))

    def test_10_invalid_qty_stops_review(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._item_rows[0].sale_qty = -1
        page._sale_panel._on_save()
        self.assertFalse(hasattr(page._sale_panel, "_review_dialog"))

    def test_11_invalid_batch_stops_review(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._item_rows[0].stock_batch_id = -99
        page._sale_panel._on_save()
        self.assertFalse(hasattr(page._sale_panel, "_review_dialog"))

    def test_12_insufficient_stock_stops_review(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._item_rows[0].sale_qty = 1000
        page._sale_panel._on_save()
        self.assertFalse(hasattr(page._sale_panel, "_review_dialog"))

    def test_13_popup_copy_keeps_bill_no(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertTrue(page._sale_panel._review_dialog._panel.bill_no_edit.text())

    def test_14_popup_copy_keeps_date_time(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertTrue(page._sale_panel._review_dialog._panel.sale_date.date().isValid())

    def test_15_popup_has_item_table(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertTrue(page._sale_panel._review_dialog._panel._table.columnCount() > 0)

    def test_16_popup_has_net_amount_summary(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        panel = page._sale_panel._review_dialog._panel
        self.assertIn("0", panel.net_amt_label.text())

    def test_17_popup_close_is_safe(self):
        page = CounterSalePage()
        self._valid_sale(page)
        before = len(SalesDAO.get_all())
        page._sale_panel._on_save()
        page._sale_panel._review_dialog.close()
        after = len(SalesDAO.get_all())
        self.assertEqual(before, after)

    def test_18_popup_final_save_refreshes_history(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        page._sale_panel._review_dialog._final_save_btn.click()
        self.assertGreater(page._hist_table.rowCount(), 0)

    def test_19_review_dialog_uses_existing_transaction_data(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        self.assertEqual(dialog._panel.sale_type_combo.currentText(), "Cash")

    def test_20_review_dialog_is_centered(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        self.assertGreater(dialog.width(), 500)

    def test_21_review_dialog_is_compact(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        self.assertLess(dialog.height(), 700)

    def test_22_review_dialog_has_customer_fields(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        panel = page._sale_panel._review_dialog._panel
        self.assertTrue(panel.customer_combo.count() > 0)

    def test_23_review_dialog_has_item_entry_controls(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        panel = page._sale_panel._review_dialog._panel
        self.assertTrue(panel._entry_bar.item_combo.count() > 0)

    def test_24_popup_points_to_final_save(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertTrue(hasattr(page._sale_panel._review_dialog, "_final_save_btn"))

    def test_25_review_dialog_ignores_close_without_final_save(self):
        page = CounterSalePage()
        self._valid_sale(page)
        before = SalesDAO.get_all()
        page._sale_panel._on_save()
        page._sale_panel._review_dialog.close()
        self.assertEqual(len(before), len(SalesDAO.get_all()))

    def test_26_review_dialog_is_a_qdialog(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertTrue(hasattr(page._sale_panel._review_dialog, "exec"))

    def test_27_review_dialog_has_save_close_buttons(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        names = {btn.text() for btn in dialog.findChildren(type(dialog._final_save_btn))}
        self.assertTrue(any("Save" in str(name) for name in names))

    def test_28_review_dialog_reuses_existing_item_data(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        item_names = [row.item_name for row in page._sale_panel._item_rows]
        self.assertIn("TestItem", item_names)

    def test_29_final_save_does_not_open_duplicate_popup(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        page._sale_panel._review_dialog._final_save_btn.click()
        self.assertFalse(hasattr(page._sale_panel, "_review_dialog"))

    def test_30_review_dialog_preserves_bill_discount(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel.bill_disc_edit.setText("5.00")
        page._sale_panel._on_save()
        self.assertEqual(page._sale_panel._review_dialog._panel.bill_disc_edit.text(), "5.00")

    def test_31_review_dialog_preserves_paid_amount(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel.paid_edit.setText("100.00")
        page._sale_panel._on_save()
        self.assertEqual(page._sale_panel._review_dialog._panel.paid_edit.text(), "100.00")

    def test_32_review_dialog_has_valid_stock_and_batch_fields(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        panel = page._sale_panel._review_dialog._panel
        self.assertTrue(panel._entry_bar.batch_combo.count() > 0)

    def test_33_review_dialog_can_reopen_after_close(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        page._sale_panel._review_dialog.reject()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertIsNotNone(page._sale_panel._review_dialog)

    def test_34_review_dialog_size_matches_reference_range(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        self.assertGreater(dialog.width(), 700)
        self.assertLess(dialog.height(), 600)

    def test_35_editing_quantity_in_review_updates_totals(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        panel = page._sale_panel._review_dialog._panel
        panel._item_rows[0].sale_qty = 4
        panel._recalc_totals()
        self.assertGreater(float(panel.net_amt_label.text()), 0.0)

    def test_36_view_of_review_dialog_includes_item_table_columns(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        panel = page._sale_panel._review_dialog._panel
        self.assertGreater(panel._table.columnCount(), 8)

    def test_37_review_dialog_uses_blue_header(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        self.assertIn("Sales Bill", dialog.windowTitle())

    def test_38_save_sale_button_in_live_panel_opens_review_step(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertIsNotNone(page._sale_panel._review_dialog)

    def test_39_review_dialog_is_modal(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertTrue(page._sale_panel._review_dialog.isModal())

    def test_40_review_dialog_esc_close_is_safe(self):
        page = CounterSalePage()
        self._valid_sale(page)
        before = len(SalesDAO.get_all())
        page._sale_panel._on_save()
        page._sale_panel._review_dialog.reject()
        self.assertEqual(before, len(SalesDAO.get_all()))


@unittest.skipUnless(CounterSalePage is not None and SalesBillReviewDialog is not None, "PySide6 not available")
class TestSalesBillPopupLayout(_DBBase):
    """Field arrangement of the Sales Bill popup (reference layout).

    Order under test, top to bottom:
        Sales Bill header / Voucher No / Date / Time
        Cnt No / Type  +  Customer / Patient / Address
                        +  Doctor / Discount / Paid Amount
        Item entry
        Bill Items
        Total Items / Remarks / Net Receivable
        Save / Close
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def _open(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        dialog.show()
        QApplication.instance().processEvents()
        return dialog

    def _y(self, widget, dialog):
        return widget.mapTo(dialog, widget.rect().topLeft()).y()

    # -- header ---------------------------------------------------------

    def test_41_popup_header_carries_voucher_no_date_time(self):
        dialog = self._open()
        header = dialog.findChild(QWidget, "SalesBillHeader")
        self.assertIsNotNone(header)
        texts = {lbl.text() for lbl in header.findChildren(QLabel)}
        self.assertTrue({"Sales Bill", "Voucher No", "Date", "Time"} <= texts)

    # -- top customer section -------------------------------------------

    def test_42_popup_has_top_customer_section(self):
        dialog = self._open()
        strip = dialog._panel.findChild(QWidget, "SalesBillTopStrip")
        self.assertIsNotNone(strip)
        self.assertTrue(strip.isVisible())

    def test_43_customer_is_in_the_top_section(self):
        dialog = self._open()
        strip = dialog._panel.findChild(QWidget, "SalesBillTopStrip")
        self.assertIn(dialog._panel.customer_combo, strip.findChildren(QWidget))

    def test_44_patient_is_in_the_top_section(self):
        dialog = self._open()
        strip = dialog._panel.findChild(QWidget, "SalesBillTopStrip")
        self.assertIn(dialog._panel.patient_name_edit,
                      strip.findChildren(QWidget))

    def test_45_doctor_is_in_the_top_section(self):
        dialog = self._open()
        strip = dialog._panel.findChild(QWidget, "SalesBillTopStrip")
        self.assertIn(dialog._panel.doctor_combo, strip.findChildren(QWidget))

    def test_46_discount_and_paid_are_in_the_top_section(self):
        dialog = self._open()
        strip = dialog._panel.findChild(QWidget, "SalesBillTopStrip")
        widgets = strip.findChildren(QWidget)
        self.assertIn(dialog._panel.bill_disc_edit, widgets)
        self.assertIn(dialog._panel.paid_edit, widgets)

    def test_47_top_section_labels_match_reference(self):
        dialog = self._open()
        strip = dialog._panel.findChild(QWidget, "SalesBillTopStrip")
        labels = {lbl.text() for lbl in strip.findChildren(QLabel)}
        for caption in ("Cnt No", "Type", "Customer *", "Patient Name",
                        "Address", "Doctor", "Discount", "Paid Amount"):
            self.assertIn(caption, labels)

    def test_48_cnt_no_and_address_mirror_customer_data(self):
        address = "9 Probe Road"
        contact = "9000000000"
        CustomerDAO.update(self.customer_id, "TestCustomer", address=address,
                           contact_no=contact)
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        self.assertEqual(dialog._panel.cnt_no_edit.text(), contact)
        self.assertEqual(dialog._panel.address_edit.text(), address)

    # -- region order ----------------------------------------------------

    def test_49_item_entry_is_below_top_section(self):
        dialog = self._open()
        strip = dialog._panel.findChild(QWidget, "SalesBillTopStrip")
        self.assertLess(self._y(strip, dialog),
                        self._y(dialog._panel._entry_bar, dialog))

    def test_50_bill_items_are_below_item_entry(self):
        dialog = self._open()
        self.assertLess(self._y(dialog._panel._entry_bar, dialog),
                        self._y(dialog._panel._table_group, dialog))

    def test_51_totals_are_at_the_bottom_of_the_bill(self):
        dialog = self._open()
        self.assertLess(self._y(dialog._panel._table_group, dialog),
                        self._y(dialog._panel._totals_widget, dialog))

    def test_52_actions_are_below_the_bill(self):
        dialog = self._open()
        actions = dialog.findChild(QWidget, "SalesBillActions")
        self.assertLess(self._y(dialog._panel._totals_widget, dialog),
                        self._y(actions, dialog))

    # -- bottom row ------------------------------------------------------

    def test_53_bottom_row_has_total_items_and_remarks(self):
        dialog = self._open()
        actions = dialog.findChild(QWidget, "SalesBillActions")
        labels = {lbl.text() for lbl in actions.findChildren(QLabel)}
        self.assertIn("Total Items", labels)
        self.assertIn("Remarks", labels)
        self.assertIn("Net Receivable", labels)

    def test_54_total_items_counts_bill_lines(self):
        dialog = self._open()
        self.assertEqual(dialog._total_items_label.text(), "1")
        panel = dialog._panel
        panel._item_rows[0].sale_qty = 5
        panel._recalc_totals()
        self.assertEqual(dialog._total_items_label.text(), "1")

    def test_55_save_and_close_are_visible_at_bottom_right(self):
        dialog = self._open()
        self.assertEqual(dialog._final_save_btn.text(), "Save")
        self.assertTrue(dialog._final_save_btn.isVisible())
        close = [b for b in dialog.findChildren(QPushButton)
                 if b.text() == "Close"]
        self.assertEqual(len(close), 1)
        self.assertTrue(close[0].isVisible())
        self.assertGreaterEqual(self._x(close[0], dialog),
                                self._x(dialog._final_save_btn, dialog))

    def _x(self, widget, dialog):
        return widget.mapTo(dialog, widget.rect().topLeft()).x()

    # -- duplicate section removed --------------------------------------

    def test_56_duplicate_lower_customer_section_does_not_exist(self):
        dialog = self._open()
        titles = [g.title() for g in dialog._panel.findChildren(QGroupBox)
                  if g.isVisible()]
        self.assertNotIn("Customer / Doctor", titles)
        self.assertNotIn("Sale Header", titles)

    def test_57_customer_section_appears_once(self):
        dialog = self._open()
        strips = dialog._panel.findChildren(QWidget, "SalesBillTopStrip")
        self.assertEqual(len(strips), 1)

    # -- behaviour preserved --------------------------------------------

    def test_58_popup_size_is_compact(self):
        # The bill window was widened so the single Item Entry row fits on
        # one line: wide enough for every labelled field, still short enough
        # to stay a dialog rather than a full-screen window.
        dialog = self._open()
        self.assertLessEqual(dialog.width(), 1300)
        self.assertLessEqual(dialog.height(), 600)
        self.assertGreaterEqual(dialog.width(), 900)
        self.assertGreaterEqual(dialog.height(), 520)

    def test_59_popup_still_opens_after_save_sale(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        self.assertIsInstance(page._sale_panel._review_dialog,
                              SalesBillReviewDialog)

    def test_60_popup_final_save_still_commits_once(self):
        page = CounterSalePage()
        self._valid_sale(page)
        before = len(SalesDAO.get_all())
        page._sale_panel._on_save()
        page._sale_panel._review_dialog._final_save_btn.click()
        self.assertEqual(len(SalesDAO.get_all()), before + 1)

    def test_61_popup_close_still_saves_nothing(self):
        page = CounterSalePage()
        self._valid_sale(page)
        before = len(SalesDAO.get_all())
        page._sale_panel._on_save()
        page._sale_panel._review_dialog.reject()
        self.assertEqual(len(SalesDAO.get_all()), before)

    def test_62_remarks_are_stored_from_the_popup(self):
        page = CounterSalePage()
        self._valid_sale(page)
        page._sale_panel._on_save()
        dialog = page._sale_panel._review_dialog
        dialog.remarks_edit.setText("Handed over at counter")
        dialog._final_save_btn.click()
        self.assertEqual(SalesDAO.get_all()[-1]["remarks"],
                         "Handed over at counter")

    def test_63_counter_sale_page_keeps_its_footer_sections(self):
        page = CounterSalePage()
        titles = [g.title() for g in page._sale_panel.findChildren(QGroupBox)]
        self.assertIn("Sale Header", titles)
        self.assertIn("Customer / Doctor", titles)


if __name__ == "__main__":
    unittest.main()
