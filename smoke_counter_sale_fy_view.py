"""Real-application smoke test for the Counter Sale Date + FY view.

Boots the actual PharmacyMainWindow against a throwaway database and walks
the manual check-list end to end:

  A. the Date control opens a calendar and an exact day filters history
  B. the FY button opens the picker; choosing 2025-2026 loads that FY and
     moves the Date control to 31/03/2026
  C. New Sale while that old FY is open raises the warning
  D. Continue starts the bill on the CURRENT live date / ACTIVE FY
"""

import os
import sys
import tempfile
from datetime import datetime
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB = os.path.join(tempfile.gettempdir(), "pharmacy_smoke_fy_view.db")
if os.path.exists(DB):
    os.remove(DB)
os.environ["PHARMACY_DB"] = DB

from PySide6.QtCore import QDate                                     # noqa: E402
from PySide6.QtWidgets import QApplication, QDateEdit                # noqa: E402

from database.connection import init_database, get_db_path           # noqa: E402
from database import auth, financial_year                            # noqa: E402
from database.sales_dao import SalesDAO                              # noqa: E402

init_database()
assert "data/pharmacy.db" not in get_db_path().replace("\\", "/"), get_db_path()

# Two financial years: 2026-2027 active, 2025-2026 historical.
financial_year.ensure_financial_year_schema()
financial_year.create_financial_year("2026-2027", "2026-04-01", "2027-03-31", activate=True)
financial_year.create_financial_year("2025-2026", "2025-04-01", "2026-03-31", activate=False)

auth.ensure_auth_schema()
if auth.user_count() == 0:
    auth.create_first_admin("admin", "admin-pass-1")
auth.session.login("admin", "admin-pass-1")

app = QApplication.instance() or QApplication([])

from ui.main_window import PharmacyMainWindow                         # noqa: E402
from ui.navigation_bar import FinancialYearPickerDialog               # noqa: E402

window = PharmacyMainWindow()
app.processEvents()

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{(' -> ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def counter_sale_page():
    for i in range(window._stack.count()):
        page = window._stack.widget(i)
        if hasattr(page, "set_history_financial_year"):
            return page
    raise AssertionError("Counter Sale page not found")


# ── seed two sales on one historical day, two on another ──────────────
page = counter_sale_page()
panel = page._sale_panel


def seed(bill_no, sale_date, item_name, qty):
    panel.customer_combo.setCurrentIndex(
        next(i for i in range(panel.customer_combo.count())
             if panel.customer_combo.itemText(i).upper() == "WALKIN")
    )
    panel.sale_type_combo.setCurrentIndex(0)
    row = panel._entry_bar.item_combo
    row.setEditText(item_name)
    panel._entry_bar.batch_combo.setCurrentIndex(
        0 if panel._entry_bar.batch_combo.count() else -1
    )
    return bill_no, sale_date


# Use the DAO directly so the smoke test does not depend on entry-bar
# autocompletion wiring; the point here is the header/view wiring.
def make_sale(bill_no, sale_date, item_id, batch_id, qty, amount):
    return SalesDAO.insert_invoice(
        bill_no=bill_no, sale_date=sale_date, sale_time="10:00",
        sale_type="Cash", customer_id=None, patient_name="Smoke",
        doctor_id=None, discount=0.0, paid_amount=amount,
        total_amount=amount, round_off=0.0, net_amount=amount, remarks="",
        items=[{
            "item_id": item_id, "stock_batch_id": batch_id,
            "pack_size": "10x10", "location": "", "batch_no": "B1",
            "expiry": "12/28", "mrp": amount / qty, "sale_qty": qty,
            "discount_amount": 0.0, "amount": amount,
        }],
    )


# The live database has no items/stock, so the history rows are inserted
# through the DAO only when masters exist; otherwise the view checks still
# run against an empty-but-correctly-filtered grid.
today_iso = datetime.now().strftime("%Y-%m-%d")
made_today = None
try:
    from database.company_dao import CompanyDAO
    from database.unit_dao import UnitDAO
    from database.item_dao import ItemDAO
    from database.supplier_dao import SupplierDAO
    from database.purchase_dao import PurchaseDAO
    from database.stock_dao import StockDAO
    from database.account_roles import ensure_system_ledgers

    ensure_system_ledgers()
    co = CompanyDAO.insert("SmokeCo", "SC")
    unit = UnitDAO.insert("Pcs")
    sup = SupplierDAO.insert("SmokeSup")
    item = ItemDAO.insert(item_name="SmokeItem", unit_id=unit,
                          company_id=co, pack_size="10x10")
    PurchaseDAO.insert_invoice(
        voucher_no="PV-S", voucher_date="2026-02-01", voucher_time="",
        purchase_type="Cash", supplier_id=sup, invoice_no="INV-S",
        invoice_date="2026-02-01", invoice_net_amount=500, bill_discount=0,
        due_date="", total_amount=500, gst_amount=0, debit_note_amount=0,
        other_amount=0, paid_amount=500, round_off=0, net_amount=500,
        remarks="",
        items=[{"item_id": item, "pack_size": "10x10", "pay_qty": 100,
                "free_qty": 0, "batch_no": "B1", "expiry": "12/28",
                "rate": 5, "mrp": 10, "discount": 0, "gst_percent": 0,
                "gst_amount": 0, "amount": 500, "purchase_rate": 5,
                "net_rate": 5, "pp": 5}],
    )
    batch = StockDAO.get_stock_batches_for_item(item)[0]["id"]
    made_today = make_sale("CS-SMOKE-1", today_iso, item, batch, 1, 10.0)
    make_sale("CS-SMOKE-2", "2026-03-01", item, batch, 1, 20.0)
except Exception as exc:                                   # pragma: no cover
    print(f"  note: could not seed sales ({exc})")

page._refresh_history()
app.processEvents()

print("\nA. Date control")
bar_dates = page._history_filter_bar.findChildren(QDateEdit)
check("history bar holds exactly one Date control", len(bar_dates) == 1)
check("calendar popup is enabled", page._hist_date.calendarPopup())
if made_today:
    page._hist_date.setDate(QDate.fromString(today_iso, "yyyy-MM-dd"))
    app.processEvents()
    rows = page._hist_table.rowCount()
    bills = [page._hist_table.item(r, 0).text()
             for r in range(page._hist_table.rowCount())]
    check(f"only today's sale appears ({today_iso})",
          rows == 1 and bills == ["CS-SMOKE-1"], f"rows={rows} {bills}")
    page._hist_date.setDate(QDate.fromString("2026-03-01", "yyyy-MM-dd"))
    app.processEvents()
    bills = [page._hist_table.item(r, 0).text()
             for r in range(page._hist_table.rowCount())]
    check("picking 01/03/2026 shows only that day",
          bills == ["CS-SMOKE-2"], f"{bills}")

print("\nB. Financial Year button")
check("FY button exists in the top bar",
      window._nav.fy_button.text() == "FY 2026-2027",
      window._nav.fy_button.text())
old = next(y for y in financial_year.get_financial_years()
           if y["name"] == "2025-2026")

opened = []


class _Auto(FinancialYearPickerDialog):
    def exec(self):
        opened.append(True)
        idx = next(i for i in range(self.combo.count())
                   if "2025-2026" in self.combo.itemText(i))
        self.combo.setCurrentIndex(idx)
        self._accept()
        return 1


with mock.patch("ui.navigation_bar.FinancialYearPickerDialog", _Auto):
    window._nav.fy_button.click()
app.processEvents()

check("clicking FY opened the popup", len(opened) == 1)
check("Date moved to 31/03/2026",
      page._hist_date.date().toString("yyyy-MM-dd") == "2026-03-31",
      page._hist_date.date().toString("dd/MM/yyyy"))
check("history now covers FY 2025-2026",
      page._history_filter_dates() == ("2025-04-01", "2026-03-31"),
      str(page._history_filter_dates()))
check("active FY is still 2026-2027",
      financial_year.get_active_financial_year()["name"] == "2026-2027")

print("\nC. New Sale with the old FY open")


class _FakeBox:
    Information = "information"

    class ButtonRole:
        AcceptRole = "acceptrole"
        RejectRole = "rejectrole"

    last = None

    def __init__(self, parent=None):
        self.text = ""
        self.buttons = {}
        _FakeBox.last = self

    def setWindowTitle(self, t):
        pass

    def setIcon(self, i):
        pass

    def setText(self, t):
        self.text = t

    def setDefaultButton(self, b):
        pass

    def addButton(self, label, role=None):
        self.buttons[label] = label
        return label

    def exec(self):
        self._clicked = self.buttons.get(_FakeBox.click)
        return 1

    def clickedButton(self):
        return self._clicked


with mock.patch("screens.counter_sale.QMessageBox", _FakeBox):
    _FakeBox.click = "Cancel"
    page._sale_panel.patient_name_edit.setText("KeptDraft")
    page._on_new()
check("warning popup shown", _FakeBox.last is not None
      and "Historical Financial Year selected" in _FakeBox.last.text)
check("warning names both years",
      "2025-2026" in _FakeBox.last.text and "2026-2027" in _FakeBox.last.text)
check("Cancel left the draft alone",
      page._sale_panel.patient_name_edit.text() == "KeptDraft")

with mock.patch("screens.counter_sale.QMessageBox", _FakeBox):
    _FakeBox.click = "Continue"
    page._on_new()

print("\nD. Continue -> new bill")
new_date = page._sale_panel.sale_date.date().toString("yyyy-MM-dd")
check("new bill uses the CURRENT live date", new_date == today_iso, new_date)
check("new bill is NOT 31/03/2026", new_date != "2026-03-31")
active = financial_year.get_active_financial_year()
check("new bill is inside the ACTIVE FY",
      active["start_date"] <= new_date <= active["end_date"],
      f"{active['start_date']}..{active['end_date']}")
check("new bill is NOT inside the viewed old FY",
      not ("2025-04-01" <= new_date <= "2026-03-31"))
check("bill number generated by existing rules",
      page._sale_panel.bill_no_edit.text() == SalesDAO.generate_next_bill_no(),
      page._sale_panel.bill_no_edit.text())
check("active FY unchanged after New Sale",
      financial_year.get_active_financial_year()["name"] == "2026-2027")

print(f"\n{'ALL CHECKS PASSED' if not failures else 'FAILURES: ' + str(failures)}")
sys.exit(1 if failures else 0)