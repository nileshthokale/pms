"""Multiple Bills in One Counter Sale Window — regression tests.

Covers the feature spec on the development code path only (isolated test
database, never production data, migrations, reports or dist):

  * creating multiple bills via + Add Bill without DB writes
  * open-bill cards (CNo / Patient / Bill Total / Amount, active highlight)
  * switching restores items, batches, customer/patient/doctor, payment,
    discounts, paid and totals without mixing data
  * provisional CNo safety + sequential unique CNo on save (FY convention kept)
  * saving one bill keeps other drafts intact
  * hold / cancel / close behaviour
  * same-batch reservations across drafts, oversell prevention, single deduction
  * expired / zero / negative batches unsaleable
  * accounting posted exactly once per saved bill
  * repeated Day/Night switching with multiple drafts (no loss, no crash)

Offscreen (QT_QPA_PLATFORM=offscreen).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QGroupBox

    from screens.counter_sale import CounterSalePage, _BillItemRow

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


def _row(item_id=1, batch_id=1, qty=2.0, mrp=50.0, batch_no="BATCH-A") -> "_BillItemRow":
    return _BillItemRow(
        item_id=item_id, item_name=f"Item {item_id}",
        stock_batch_id=batch_id, pack_size="10x10", location="A-1",
        batch_no=batch_no, expiry="12/27", mrp=mrp,
        sale_qty=qty, discount_amount=0.0, amount=round(qty * mrp, 2),
    )


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class MultiBillBase(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_cs_multi_bill.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        from database.connection import init_database
        from database import auth, financial_year
        from database.customer_dao import CustomerDAO
        from database.account_roles import ensure_system_ledgers

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()
        cls._app = QApplication.instance() or QApplication([])
        cls._app.setStyle("Fusion")

    def setUp(self):
        # Clean transactional tables; keep schema/masters rebuilt per test.
        from database.connection import get_connection
        from database.company_dao import CompanyDAO
        from database.unit_dao import UnitDAO
        from database.drug_dao import DrugDAO
        from database.item_dao import ItemDAO
        from database.customer_dao import CustomerDAO
        from database.doctor_dao import DoctorDAO
        from database.supplier_dao import SupplierDAO
        from database.purchase_dao import PurchaseDAO
        from database.stock_dao import StockDAO
        from database.account_roles import ensure_system_ledgers

        conn = get_connection()
        try:
            for tbl in ("ledger_transactions", "sales_invoice_items",
                        "sales_invoices", "purchase_invoice_items",
                        "purchase_invoices", "stock_batches", "hold_bill_items",
                        "hold_bills", "items", "customers", "doctors",
                        "suppliers", "drugs", "units", "companies"):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_a = CustomerDAO.insert("Patient A Customer")
        self.customer_b = CustomerDAO.insert("Patient B Customer")
        self.customer_c = CustomerDAO.insert("Patient C Customer")
        self.doctor_a = DoctorDAO.insert("Dr A")
        self.doctor_b = DoctorDAO.insert("Dr B")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.item_id = ItemDAO.insert(item_name="MultiBillItem",
                                      unit_id=self.unit_id,
                                      company_id=self.company_id,
                                      pack_size="10x10")
        ensure_system_ledgers()
        # Stock: 100 units, MRP 50, far-future expiry.
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0,
            net_amount=4000.0, remarks="",
            items=[{"item_id": self.item_id, "pack_size": "10x10",
                    "pay_qty": 100.0, "free_qty": 0, "batch_no": "BATCH-A",
                    "expiry": "12/27", "rate": 40.0, "mrp": 50.0,
                    "discount": 0, "gst_percent": 0, "gst_amount": 0,
                    "amount": 4000.0, "purchase_rate": 40.0,
                    "net_rate": 40.0, "pp": 40.0}],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertTrue(batches)
        self.batch_id = batches[0]["id"]

        # Never block on dialogs; question defaults to Yes for close tests
        # (individual tests override where they need No).
        self._patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        self._q_yes = mock.patch.object(QMessageBox, "question",
                                        return_value=QMessageBox.Yes)
        self._q_yes.start()
        self.addCleanup(self._q_yes.stop)

        # Theme isolation: never touch data/theme.json.
        import tempfile as _tf
        from pathlib import Path as _Path
        from ui import theme as theme_mod
        self._theme_dir = _tf.TemporaryDirectory()
        self.addCleanup(self._theme_dir.cleanup)
        _tf_file = _Path(self._theme_dir.name) / "theme.json"
        _tp = mock.patch.object(theme_mod, "_THEME_FILE", _tf_file)
        _tp.start()
        self.addCleanup(_tp.stop)
        theme_mod.theme_manager.set_mode("light")
        self._app.processEvents()

    # -- helpers ------------------------------------------------------
    def _make_page(self) -> CounterSalePage:
        page = CounterSalePage()
        page.resize(1366, 708)
        page.show()
        self._app.processEvents()
        page._apply_history_height()
        self._app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater(),
                                 self._app.processEvents()))
        return page

    def _fill_panel(self, panel, customer_id, patient, doctor_id,
                    qty=2.0, paid=None, discount="0.00", sale_type="Cash"):
        panel.customer_combo.setCurrentIndex(
            panel.customer_combo.findData(customer_id))
        panel.patient_name_edit.setText(patient)
        if doctor_id is not None:
            panel.doctor_combo.setCurrentIndex(
                panel.doctor_combo.findData(doctor_id))
        st = panel.sale_type_combo.findText(sale_type)
        if st >= 0:
            panel.sale_type_combo.setCurrentIndex(st)
        panel.bill_disc_edit.setText(discount)
        panel._item_rows.clear()
        panel._item_rows.append(_row(self.item_id, self.batch_id, qty))
        panel._refresh_table()
        panel._recalc_totals()
        if paid is None:
            paid = panel.net_amt_label.text()
        panel.paid_edit.setText(str(paid))
        panel._recalc_totals()
        self._app.processEvents()

    def _pump(self, n=4):
        for _ in range(n):
            self._app.processEvents()


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestAddBillAndCards(MultiBillBase):
    def test_01_add_bill_button_visible_on_right(self):
        page = self._make_page()
        texts = [b.text() for b in page._bill_panel.findChildren(QPushButton)]
        self.assertIn("+ Add Bill", texts)
        self.assertIn("Close Bill", texts)
        titles = [g.title() for g in page._bill_panel.findChildren(QGroupBox)]
        self.assertIn("Open Bills", titles)
        self.assertNotIn("Current Bill", titles,
                         "Current Bill box was removed; cards carry CNo + total")
        # Expanded + scrollable: the list owns the freed right-panel height.
        self.assertTrue(page._open_bills_scroll.widgetResizable())

    def test_02_add_bill_creates_empty_draft_without_db_write(self):
        from database.connection import get_connection
        page = self._make_page()
        conn = get_connection()
        try:
            before = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
        finally:
            conn.close()
        preview_before = page._sale_panel.bill_no_edit.text()
        self.assertEqual(len(page._open_bills), 1)
        page._on_add_bill()
        self._pump()
        self.assertEqual(len(page._open_bills), 2)
        # New bill is empty and active; old bill unchanged in storage.
        self.assertEqual(len(page._sale_panel._item_rows), 0)
        conn = get_connection()
        try:
            after = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(before, after, "Add Bill must not create an invoice")
        # Provisional previews: distinct bill numbers in FY format, held
        # only in memory -- no invoice record, no consumed sequence number.
        preview_after = page._sale_panel.bill_no_edit.text()
        self.assertRegex(preview_after, r"^CS-\d{4}$")
        self.assertNotIn("Draft", preview_after)
        self.assertTrue(page._sale_panel._provisional_bill_no)
        self.assertNotEqual(preview_before, preview_after)
        # The two open bills carry distinct previews and distinct hidden ids.
        ids = sorted(page._open_bills.keys())
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])
        cnos = [page._open_bills[did].get("bill_no", "") for did in ids]
        self.assertEqual(len(set(cnos)), 2, "open bills must not share one CNo")
        for cno in cnos:
            self.assertRegex(cno, r"^CS-\d{4}$")
            self.assertNotIn("Draft", cno)

    def _cards(self, page):
        # Layout count is the source of truth: findChildren also sees
        # deleteLater-pending buttons until the event loop destroys them.
        widgets = []
        layout = page._open_bills_layout
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w is not None:
                widgets.append(w)
        return widgets

    def test_03_three_open_bills_all_listed(self):
        page = self._make_page()
        page._on_add_bill()
        page._on_add_bill()
        self._pump()
        self.assertEqual(len(page._open_bills), 3)
        cards = self._cards(page)
        self.assertEqual(len(cards), 3)
        for card in cards:
            text = card.text()
            # Bill-number preview (FY format, never a Draft label), name
            # slot and current total -- short enough to read unclipped.
            self.assertRegex(text.split("\n")[0], r"CS-\d{4}")
            self.assertNotIn("Draft", text)
            self.assertIn("Bill Total:", text)
            self.assertTrue(
                ("New customer" in text) or ("Patient:" in text) or ("Customer:" in text),
                f"card must show a customer/patient slot, got: {text!r}",
            )
        # Previews are distinct across the three cards.
        heads = [c.text().split("\n")[0] for c in cards]
        self.assertEqual(len(set(heads)), 3, "each open bill needs its own CNo")

    def test_04_active_bill_highlighted(self):
        page = self._make_page()
        page._on_add_bill()
        self._pump()
        cards = self._cards(page)
        self.assertEqual(len(cards), 2)
        from ui.theme import palette
        accent = palette()["accent"].lower()
        active = [c for c in cards if "Active" in c.text()]
        self.assertEqual(len(active), 1)
        self.assertIn(accent, active[0].styleSheet().lower())


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestSwitchingAndIndependence(MultiBillBase):
    def _setup_two_bills(self, page):
        panel = page._sale_panel
        # Bill 1
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=2.0, discount="5.00", sale_type="Cash")
        page._store_active_open_bill()
        first_id = page._active_open_bill_id
        first_state = panel.draft_state()
        # Bill 2
        page._on_add_bill()
        second_id = page._active_open_bill_id
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=1.0, discount="0.00", sale_type="Credit")
        # paid for credit may be partial
        panel.paid_edit.setText("10.00")
        panel._recalc_totals()
        page._store_active_open_bill()
        return first_id, second_id, first_state

    def test_05_switching_restores_complete_state(self):
        page = self._make_page()
        panel = page._sale_panel
        first_id, second_id, first_state = self._setup_two_bills(page)
        # Go back to bill 1
        page._select_open_bill(first_id)
        self._pump()
        self.assertEqual(panel.customer_combo.currentData(), self.customer_a)
        self.assertEqual(panel.patient_name_edit.text(), "Patient A")
        self.assertEqual(panel.doctor_combo.currentData(), self.doctor_a)
        self.assertEqual(panel.sale_type_combo.currentText(), "Cash")
        self.assertEqual(panel.bill_disc_edit.text(), "5.00")
        self.assertEqual(len(panel._item_rows), 1)
        self.assertEqual(panel._item_rows[0].sale_qty, 2.0)
        self.assertEqual(panel._item_rows[0].stock_batch_id, self.batch_id)
        # Totals restored exactly.
        self.assertEqual(panel.total_amount_label.text(), "100.00")
        # Return to bill 2 — nothing mixed.
        page._select_open_bill(second_id)
        self._pump()
        self.assertEqual(panel.customer_combo.currentData(), self.customer_b)
        self.assertEqual(panel.patient_name_edit.text(), "Patient B")
        self.assertEqual(panel.doctor_combo.currentData(), self.doctor_b)
        self.assertEqual(panel.sale_type_combo.currentText(), "Credit")
        self.assertEqual(len(panel._item_rows), 1)
        self.assertEqual(panel._item_rows[0].sale_qty, 1.0)
        self.assertEqual(panel.total_amount_label.text(), "50.00")
        self.assertEqual(panel.paid_edit.text(), "10.00")

    def test_06_independent_totals_and_paid(self):
        page = self._make_page()
        panel = page._sale_panel
        first_id, second_id, _ = self._setup_two_bills(page)
        page._select_open_bill(first_id)
        net1 = panel.net_amt_label.text()
        paid1 = panel.paid_edit.text()
        page._select_open_bill(second_id)
        net2 = panel.net_amt_label.text()
        paid2 = panel.paid_edit.text()
        self.assertNotEqual((net1, paid1), (net2, paid2))
        self.assertEqual(net1, "95.00")   # 100 - 5 discount
        self.assertEqual(net2, "50.00")

    def _cards_dict(self, page):
        widgets = []
        layout = page._open_bills_layout
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w is not None:
                widgets.append(w)
        return {c.text().split("\n")[0]: c.text() for c in widgets}

    def test_07_card_totals_match_panel(self):
        page = self._make_page()
        self._fill_panel(page._sale_panel, self.customer_a, "Patient A",
                         self.doctor_a, qty=2.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(page._sale_panel, self.customer_b, "Patient B",
                         self.doctor_b, qty=3.0)
        page._store_active_open_bill()
        page._refresh_open_bill_cards()
        self._pump()
        cards = self._cards_dict(page)
        self.assertEqual(len(cards), 2)
        # Bill 1 net 100.00, Bill 2 net 150.00 must appear on cards.
        joined = "\n".join(cards.values())
        self.assertIn("100.00", joined)
        self.assertIn("150.00", joined)


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestBillNumberSafety(MultiBillBase):
    def test_08_sequential_unique_cno_on_save(self):
        from database.sales_dao import SalesDAO
        page = self._make_page()
        panel = page._sale_panel
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=1.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=1.0)
        page._store_active_open_bill()
        # Distinct in-memory previews; nothing consumed yet.
        preview1 = page._open_bills[1]["bill_no"]
        preview2 = page._open_bills[2]["bill_no"]
        self.assertNotEqual(preview1, preview2)
        for pv in (preview1, preview2):
            self.assertRegex(pv, r"^CS-\d{4}$")
            self.assertNotIn("Draft", pv)
        # Save bill 1 (select it first).
        page._select_open_bill(1)
        self.assertTrue(panel._validate_for_commit())
        panel._commit_sale()
        self._pump()
        first_saved = SalesDAO.get_all()[0]["bill_no"]
        # Save bill 2 — must get the next unique number.
        self.assertTrue(panel._validate_for_commit())
        panel._commit_sale()
        self._pump()
        bills = sorted(r["bill_no"] for r in SalesDAO.get_all())
        self.assertEqual(len(bills), 2)
        self.assertEqual(len(set(bills)), 2, "duplicate CNo assigned")
        self.assertNotIn("Draft", bills[0])
        self.assertNotIn("Draft", bills[1])
        # FY convention preserved: CS-XXXX, sequential.
        for b in bills:
            self.assertTrue(b.startswith("CS-"))
        nums = sorted(int(b.split("-")[1]) for b in bills)
        self.assertEqual(nums[1], nums[0] + 1)

    def test_09_save_one_bill_keeps_others(self):
        page = self._make_page()
        panel = page._sale_panel
        for cust, pat in ((self.customer_a, "Patient A"),
                          (self.customer_b, "Patient B"),
                          (self.customer_c, "Patient C")):
            if len(page._open_bills) > 1 or panel._item_rows:
                pass
            # Fill current, then add next except after last.
            self._fill_panel(panel, cust, pat, self.doctor_a, qty=1.0)
            page._store_active_open_bill()
            if pat != "Patient C":
                page._on_add_bill()
        page._store_active_open_bill()
        self.assertEqual(len(page._open_bills), 3)
        # Save the middle bill.
        ids = sorted(page._open_bills.keys())
        page._select_open_bill(ids[1])
        panel._commit_sale()
        self._pump()
        self.assertEqual(len(page._open_bills), 2)
        remaining_patients = set()
        for did, state in page._open_bills.items():
            remaining_patients.add(state.get("patient_name"))
        self.assertIn("Patient A", remaining_patients)
        self.assertIn("Patient C", remaining_patients)
        from database.sales_dao import SalesDAO
        self.assertEqual(len(SalesDAO.get_all()), 1)


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestHoldCancelClose(MultiBillBase):
    def test_10_hold_keeps_other_drafts(self):
        from database.hold_bill_dao import get_all as hold_all
        page = self._make_page()
        panel = page._sale_panel
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=1.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=1.0)
        page._store_active_open_bill()
        stock_before = self._stock_qty()
        # Hold the active (Patient B) draft.
        panel._on_hold()
        self._pump()
        self.assertEqual(len(hold_all()), 1)
        self.assertEqual(len(page._open_bills), 1)
        # Remaining draft is Patient A, untouched.
        remaining = next(iter(page._open_bills.values()))
        self.assertEqual(remaining.get("patient_name"), "Patient A")
        self.assertEqual(self._stock_qty(), stock_before,
                         "hold must not deduct stock")

    def test_11_cancel_close_with_confirmation(self):
        page = self._make_page()
        panel = page._sale_panel
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=1.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self.assertEqual(len(page._open_bills), 2)
        # Active draft (empty) closes without question.
        page._cancel_active_open_bill()
        self._pump()
        self.assertEqual(len(page._open_bills), 1)
        # Now active has items; No keeps it.
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.No):
            page._cancel_active_open_bill()
        self.assertEqual(len(page._open_bills), 1)
        # Yes discards it and a fresh empty draft remains.
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.Yes):
            page._cancel_active_open_bill()
        self._pump()
        self.assertEqual(len(page._open_bills), 1)
        self.assertEqual(len(page._sale_panel._item_rows), 0)

    def _stock_qty(self):
        from database.stock_dao import StockDAO
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        return sum(b["stock_qty"] for b in batches)


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestStockSafety(MultiBillBase):
    def _stock_qty(self):
        from database.stock_dao import StockDAO
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        return sum(b["stock_qty"] for b in batches)

    def test_12_same_batch_reserved_across_drafts(self):
        page = self._make_page()
        panel = page._sale_panel
        # Draft 1: 6 units.
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=6.0)
        page._store_active_open_bill()
        page._on_add_bill()
        # Draft 2 sees only 94 available.
        avail = panel._available_for_batch(self.batch_id, 100.0)
        self.assertAlmostEqual(avail, 94.0)
        self.assertAlmostEqual(
            page._reserved_by_other_open_bills(self.batch_id), 6.0)
        # Draft 2: 3 units OK.
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=3.0)
        self.assertTrue(panel._validate_for_commit())
        page._store_active_open_bill()
        # Draft 1 availability for *additional* units: 100 - 6 own - 3 other.
        page._select_open_bill(1)
        self.assertAlmostEqual(panel._available_for_batch(self.batch_id, 100.0),
                               91.0)

    def test_13_oversell_blocked_at_validation(self):
        page = self._make_page()
        panel = page._sale_panel
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=6.0)
        page._store_active_open_bill()
        page._on_add_bill()
        # 95 units would oversell (6 + 95 > 100).
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=95.0)
        self.assertFalse(panel._validate_for_commit())

    def test_14_no_double_deduction_on_sequential_saves(self):
        from database.sales_dao import SalesDAO
        page = self._make_page()
        panel = page._sale_panel
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=6.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=3.0)
        page._store_active_open_bill()
        page._select_open_bill(1)
        panel._commit_sale()
        self._pump()
        self.assertAlmostEqual(self._stock_qty(), 94.0)
        panel._commit_sale()
        self._pump()
        self.assertAlmostEqual(self._stock_qty(), 91.0)
        self.assertEqual(len(SalesDAO.get_all()), 2)

    def test_15_expired_zero_negative_unsaleable(self):
        from database.sales_dao import SalesDAO
        from database.connection import get_connection
        # Expired batch never offered.
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size,"
                " mrp, stock_qty) VALUES (?, ?, ?, ?, ?, ?)",
                (self.item_id, "EXP-001", "01/20", "10x10", 50.0, 50.0))
            exp_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size,"
                " mrp, stock_qty) VALUES (?, ?, ?, ?, ?, ?)",
                (self.item_id, "ZERO-001", "12/27", "10x10", 50.0, 0.0))
            zero_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        offered = {b["id"] for b in SalesDAO.get_stock_batches_for_item(self.item_id)}
        self.assertNotIn(exp_id, offered)
        self.assertNotIn(zero_id, offered)
        self.assertTrue(SalesDAO.is_expired("01/20"))
        # Commit-time DAO also rejects expired stock.
        with self.assertRaises(ValueError):
            SalesDAO.insert_invoice(
                bill_no="CS-EXP", sale_date="2026-01-25", sale_time="10:00",
                sale_type="Cash", customer_id=self.customer_a,
                patient_name="P", doctor_id=None, discount=0.0,
                paid_amount=50.0, total_amount=50.0, round_off=0.0,
                net_amount=50.0, remarks="",
                items=[{"item_id": self.item_id, "stock_batch_id": exp_id,
                        "pack_size": "10x10", "location": "", "batch_no": "EXP-001",
                        "expiry": "01/20", "mrp": 50.0, "sale_qty": 1.0,
                        "discount_amount": 0.0, "amount": 50.0}])


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestAccountingOnce(MultiBillBase):
    def test_16_accounting_exactly_once_per_bill(self):
        from database.sales_dao import SalesDAO
        from database.accounting_posting import SOURCE_COUNTER_SALE, posting_engine
        page = self._make_page()
        panel = page._sale_panel
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=2.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=1.0)
        page._store_active_open_bill()
        page._select_open_bill(1)
        panel._commit_sale()
        self._pump()
        page._select_open_bill(sorted(page._open_bills.keys())[0])
        # Identify saved invoice (Patient A).
        saved = [r for r in SalesDAO.get_all() if r["patient_name"] == "Patient A"]
        self.assertEqual(len(saved), 1)
        rows = posting_engine.get_posting_rows(SOURCE_COUNTER_SALE, saved[0]["id"])
        self.assertGreaterEqual(len(rows), 2)
        count_before = len(rows)
        # Saving the second bill must not touch the first bill's posting.
        panel._commit_sale()
        self._pump()
        rows_after = posting_engine.get_posting_rows(SOURCE_COUNTER_SALE,
                                                     saved[0]["id"])
        self.assertEqual(len(rows_after), count_before)
        # Each invoice has exactly one active posting effect.
        for inv in SalesDAO.get_all():
            self.assertTrue(posting_engine.is_posted(SOURCE_COUNTER_SALE, inv["id"]))


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestThemeWithDrafts(MultiBillBase):
    def test_17_repeated_day_night_switch_preserves_drafts(self):
        from ui import theme as theme_mod
        page = self._make_page()
        panel = page._sale_panel
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=1.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=2.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(panel, self.customer_c, "Patient C", self.doctor_b,
                         qty=3.0)
        page._store_active_open_bill()
        self.assertEqual(len(page._open_bills), 3)

        def _live_cards():
            widgets = []
            layout = page._open_bills_layout
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if w is not None:
                    widgets.append(w)
            return widgets

        for _ in range(3):
            for mode in ("dark", "light"):
                theme_mod.theme_manager.set_mode(mode)
                self._pump(6)
                page.refresh_theme()
                panel.refresh_theme()
                self._pump(4)
                self.assertEqual(len(page._open_bills), 3)
                self.assertEqual(len(_live_cards()), 3)
                # Active draft's live edits must survive the switch.
                page._store_active_open_bill()
        # Data intact after cycling (active stored above keeps snapshot fresh).
        patients = sorted(s.get("patient_name") for s in page._open_bills.values())
        self.assertEqual(patients, ["Patient A", "Patient B", "Patient C"])
        # No stale crash: scroll + cards still themed, active still marked.
        actives = [c for c in _live_cards() if "Active" in c.text()]
        self.assertEqual(len(actives), 1)

    def test_18_bill_number_convention_kept(self):
        from database.sales_dao import SalesDAO
        self.assertRegex(SalesDAO.generate_next_bill_no(), r"^CS-\d{4}$")


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestCombinedSummary(MultiBillBase):
    """All Open Bills footer summary: count, qty, amount, net (UI-only)."""

    def _setup_three_bills(self, page):
        panel = page._sale_panel
        self._fill_panel(panel, self.customer_a, "Patient A", self.doctor_a,
                         qty=2.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(panel, self.customer_b, "Patient B", self.doctor_b,
                         qty=3.0)
        page._store_active_open_bill()
        page._on_add_bill()
        self._fill_panel(panel, self.customer_c, "Patient C", self.doctor_a,
                         qty=1.0)
        page._store_active_open_bill()
        page._refresh_combined_summary()
        self._pump()
        return panel

    def test_19_three_bills_combined_matches_sum(self):
        page = self._make_page()
        self._setup_three_bills(page)
        line1 = page._sale_panel._combined_line1.text()
        line2 = page._sale_panel._combined_line2.text()
        # 100.00 + 150.00 + 50.00, qty 2 + 3 + 1.
        self.assertIn("3 bills", line1)
        self.assertIn("Qty 6", line1)
        self.assertIn("300.00", line2)
        self.assertIn("Amt", line2)
        self.assertIn("Net", line2)

    def test_20_summary_updates_on_item_add(self):
        page = self._make_page()
        panel = self._setup_three_bills(page)
        panel._item_rows.append(_row(self.item_id, self.batch_id, 1.0))
        panel._refresh_table()
        panel._recalc_totals()
        page._store_active_open_bill()
        page._refresh_combined_summary()
        self._pump()
        line2 = panel._combined_line2.text()
        self.assertIn("350.00", line2)

    def test_21_close_unsaved_bill_decreases_total(self):
        page = self._make_page()
        self._setup_three_bills(page)
        before = page._sale_panel._combined_line2.text()
        self.assertIn("300.00", before)
        page._cancel_active_open_bill()
        self._pump()
        panel = page._sale_panel
        self.assertEqual(len(page._open_bills), 2)
        line1 = panel._combined_line1.text()
        line2 = panel._combined_line2.text()
        self.assertIn("2 bills", line1)
        self.assertIn("Qty 5", line1)
        self.assertIn("250.00", line2)

    def test_22_save_updates_summary_and_keeps_unique_cnos(self):
        from database.sales_dao import SalesDAO
        page = self._make_page()
        panel = self._setup_three_bills(page)
        kept = {did: st["bill_no"] for did, st in page._open_bills.items()}
        ids = sorted(page._open_bills.keys())
        page._select_open_bill(ids[1])
        panel._commit_sale()
        self._pump()
        self.assertEqual(len(page._open_bills), 2)
        # Saved bill took a permanent number; the rest kept their previews.
        saved = [r["bill_no"] for r in SalesDAO.get_all()]
        self.assertEqual(len(saved), 1)
        self.assertRegex(saved[0], r"^CS-\d{4}$")
        for did, state in page._open_bills.items():
            self.assertEqual(state["bill_no"], kept[did])
        line1 = panel._combined_line1.text()
        line2 = panel._combined_line2.text()
        self.assertIn("2 bills", line1)
        # 300 - 150 (the saved middle bill) = 150.
        self.assertIn("150.00", line2)

    def test_23_paid_and_discount_rules(self):
        page = self._make_page()
        panel = self._setup_three_bills(page)
        # Paid amounts never enter the combined figures.
        panel.paid_edit.setText("9999.00")
        panel._recalc_totals()
        page._refresh_combined_summary()
        self._pump()
        self.assertIn("300.00", panel._combined_line2.text())
        # A bill discount lowers the combined net but not the amount.
        panel.bill_disc_edit.setText("10.00")
        panel._recalc_totals()
        page._refresh_combined_summary()
        self._pump()
        line2 = panel._combined_line2.text()
        self.assertIn("300.00", line2)
        self.assertIn("290.00", line2)



@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestOpenBillsLayout(MultiBillBase):
    """Right-side Open Bills geometry: tight top, anchored Close, scrolling list."""

    def _cards(self, page):
        widgets = []
        layout = page._open_bills_layout
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if w is not None:
                widgets.append(w)
        return widgets

    def test_24_first_card_sits_directly_below_heading(self):
        page = self._make_page()
        page._on_add_bill()
        self._pump()
        grp = page._open_bills_group
        gy = grp.mapTo(page, grp.rect().topLeft()).y()
        cards = self._cards(page)
        self.assertGreaterEqual(len(cards), 2)
        top = min(c.mapTo(page, c.rect().topLeft()).y() for c in cards)
        self.assertLessEqual(top - gy, 34,
                             f"first card starts {top - gy}px below the heading")

    def test_25_close_bill_anchored_in_section_bottom(self):
        page = self._make_page()
        page._on_add_bill()
        self._pump()
        btn = page._close_bill_btn
        grp = page._open_bills_group
        self.assertIs(btn.parent(), grp,
                      "Close Bill must live in the Open Bills section")
        self.assertLessEqual(btn.y() + btn.height(), grp.height() + 1,
                             "Close Bill must not overflow the section")

    def test_26_list_scrolls_with_many_bills(self):
        page = self._make_page()
        for _ in range(6):
            page._on_add_bill()
        self._pump()
        sb = page._open_bills_scroll.verticalScrollBar()
        self.assertGreater(sb.maximum(), 0,
                           "bill list must scroll when many bills are open")
        self.assertEqual(len(self._cards(page)), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
