"""Acceptance check for the Sales Bill review/edit popup.

Runs the real Counter Sale workflow against a COPY of the current migrated
database (real items, real batches, real prices).  Nothing is migrated,
cleared or generated, and the production data/pharmacy.db is never written to.
"""

import os
import shutil
import sys
import tempfile

PROD_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "data", "pharmacy.db")
WORK_DB = os.path.join(tempfile.gettempdir(), "pms_acceptance_sales_bill.db")
for suffix in ("", "-wal", "-shm"):
    if os.path.exists(WORK_DB + suffix):
        os.remove(WORK_DB + suffix)
shutil.copy2(PROD_DB, WORK_DB)
os.environ["PHARMACY_DB"] = WORK_DB
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from unittest import mock  # noqa: E402

app = QApplication.instance() or QApplication([])

from database.connection import get_connection, init_database  # noqa: E402
from database.sales_dao import SalesDAO  # noqa: E402
from database.customer_dao import CustomerDAO  # noqa: E402
from database.accounting_posting import SOURCE_COUNTER_SALE  # noqa: E402
from database import auth  # noqa: E402
from screens.counter_sale import CounterSalePage  # noqa: E402

init_database()

# Editing an existing bill is permission-gated, so sign in as the migrated
# admin exactly as the desktop app does after a real login.
auth.session.user = next(
    (dict(r) for r in get_connection().execute(
        "SELECT * FROM app_users WHERE role = 'ADMIN' AND is_active = 1"
    ).fetchall()),
    None,
)
if auth.session.user is None:
    raise SystemExit("no active admin available for the edit check")
print(f"signed in as {auth.session.user['username']}\n")


def stock_of(batch_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT stock_qty FROM stock_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        return float(row["stock_qty"]) if row else None
    finally:
        conn.close()


def ledger_rows(reference_id=None):
    """Ledger transactions produced by the accounting engine."""
    conn = get_connection()
    try:
        if reference_id is None:
            return conn.execute(
                "SELECT COUNT(*) c FROM ledger_transactions"
            ).fetchone()["c"]
        return conn.execute(
            "SELECT COUNT(*) c FROM ledger_transactions "
            "WHERE reference_type = ? AND reference_id = ?",
            (SOURCE_COUNTER_SALE, reference_id),
        ).fetchone()["c"]
    finally:
        conn.close()


def bill_no_present(table, bill_no):
    for row in range(table.rowCount()):
        if table.item(row, 0).text() == bill_no:
            return True
    return False


def invoice_count():
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) c FROM sales_invoices").fetchone()["c"]
    finally:
        conn.close()


def pick_real_batch():
    """A real migrated item + batch that is in stock and not expired."""
    for batch in SalesDAO.get_all_stock_batches():
        if float(batch.get("stock_qty") or 0) >= 5 and not SalesDAO.is_expired(
            batch.get("expiry", "")
        ):
            return batch
    raise SystemExit("no usable real batch found")


def fill(page, batch, qty, discount):
    panel = page._sale_panel
    customer_id = CustomerDAO.get_all()[0]["id"]
    idx = panel.customer_combo.findData(customer_id)
    panel.customer_combo.setCurrentIndex(idx)
    panel.patient_name_edit.setText("Acceptance Patient")

    bar = panel._entry_bar
    item_index = bar.item_combo.findData(batch["item_id"])
    bar.item_combo.setCurrentIndex(item_index)
    batch_index = bar.batch_combo.findData(batch["id"])
    bar.batch_combo.setCurrentIndex(batch_index)
    bar.qty_edit.setText(str(qty))
    bar.discount_edit.setText(str(discount))
    bar.add_btn.click()
    return panel


def build_page():
    page = CounterSalePage()
    page.resize(1366, 768)
    page.show()
    app.processEvents()
    return page


results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"{'PASS' if condition else 'FAIL'}  {name}  {detail}")


# Never block on real modal dialogs during this scripted run.
mock.patch.multiple(
    QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
    critical=mock.DEFAULT, question=mock.DEFAULT,
).start()

batch = pick_real_batch()
print(f"real batch: item={batch['item_id']} batch={batch['batch_no']} "
      f"stock={batch['stock_qty']} exp={batch['expiry']}\n")

# ---------------------------------------------------------------- scenario 1
print("--- Scenario 1: open popup, edit, then Close (nothing saved) ---")
page = build_page()
panel = fill(page, batch, qty=2, discount=0.0)
base_stock = stock_of(batch["id"])
base_invoices = invoice_count()
base_ledger = ledger_rows()

panel._on_save()
app.processEvents()
check("popup opens after Save Sale", hasattr(panel, "_review_dialog"))

dlg = panel._review_dialog
popup_panel = dlg._panel
check("popup title is Sales Bill", dlg.windowTitle() == "Sales Bill",
      dlg.windowTitle())
check("popup is modal", dlg.isModal())
check("popup is compact, not full-screen",
      700 < dlg.width() <= 900 and 450 <= dlg.height() <= 560,
      f"{dlg.width()}x{dlg.height()}")
check("stock untouched when popup opens", stock_of(batch["id"]) == base_stock,
      f"{stock_of(batch['id'])} == {base_stock}")

# Edit inside the popup through its own controls: remove the qty=2 line and
# re-add the same item/batch at qty=3.
before_amount = float(popup_panel.total_amount_label.text())
popup_panel._delete_item(0)
bar = popup_panel._entry_bar
bar.item_combo.setCurrentIndex(bar.item_combo.findData(batch["item_id"]))
bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(batch["id"]))
bar.qty_edit.setText("3")
bar.discount_edit.setText("0")
bar.add_btn.click()
after_amount = float(popup_panel.total_amount_label.text())
check("editing qty in popup recalculates amount", after_amount > before_amount,
      f"{before_amount} -> {after_amount}")
check("editing in popup does not touch stock",
      stock_of(batch["id"]) == base_stock, f"{stock_of(batch['id'])}")

# Set a bill discount and confirm Net Receivable follows.
popup_panel.bill_disc_edit.setText("5")
check("discount recalculates net receivable",
      float(popup_panel.net_amt_label.text())
      == round(after_amount - 5, 2),
      popup_panel.net_amt_label.text())

dlg.reject()
app.processEvents()
check("Close saves nothing", invoice_count() == base_invoices)
check("Close leaves stock unchanged", stock_of(batch["id"]) == base_stock)
check("Close leaves ledger unchanged", ledger_rows() == base_ledger)
check("Close releases popup handle", not hasattr(panel, "_review_dialog"))

print("\n--- Popup size at the supported resolutions ---")
from screens.counter_sale import SalesBillReviewDialog  # noqa: E402
for label, (rw, rh) in (("1366x768", (1366, 768)), ("1600x900", (1600, 900))):
    w, h = SalesBillReviewDialog.target_size(rw, rh)
    check(f"size at {label} is compact and in range",
          750 <= w <= 900 and 450 <= h <= 545, f"{w}x{h}")
    print(f"        {label} -> {w} x {h}")

print("\n--- Popup is centred over the Counter Sale screen ---")
page_c = build_page()
fill(page_c, batch, qty=1, discount=0.0)
page_c._sale_panel._on_save()
app.processEvents()
dlg_c = page_c._sale_panel._review_dialog
pg = page_c.geometry()
dg = dlg_c.geometry()
check("popup is horizontally centred over its parent",
      abs((dg.center().x()) - (pg.center().x())) <= 40,
      f"popup x={dg.x()} w={dg.width()} parent x={pg.x()} w={pg.width()}")
check("popup stays inside the parent screen area",
      dg.left() >= pg.left() - 1 and dg.right() <= pg.right() + 1
      and dg.top() >= pg.top() - 1 and dg.bottom() <= pg.bottom() + 1,
      f"popup={dg.getRect()} parent={pg.getRect()}")
check("Counter Sale history stays visible behind the popup",
      page_c._hist_table.isVisible() and page_c._sale_panel.isVisible())
dlg_c.reject()
app.processEvents()

# ---------------------------------------------------------------- scenario 2
def run_commit_scenario(clicks, qty):
    """Save a full sale through the popup, clicking Save ``clicks`` times.

    Returns the observable effect so two runs can be compared: one click and a
    double click must produce exactly the same single set of side effects.
    """
    page = build_page()
    panel = fill(page, batch, qty=qty, discount=1.0)
    panel.bill_disc_edit.setText("2")
    panel._recalc_totals()

    pre_stock = stock_of(batch["id"])
    pre_invoices = invoice_count()
    pre_ledger = ledger_rows()
    expected_net = float(panel.net_amt_label.text())

    panel._on_save()
    app.processEvents()
    dlg = panel._review_dialog
    opened = dlg is not None
    stock_before_final = stock_of(batch["id"])

    for _ in range(clicks):
        dlg._final_save_btn.click()
    app.processEvents()

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, net_amount, patient_name FROM sales_invoices "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    return {
        "opened": opened,
        "stock_before_final": stock_before_final,
        "pre_stock": pre_stock,
        "stock_after": stock_of(batch["id"]),
        "invoices_delta": invoice_count() - pre_invoices,
        "ledger_delta": ledger_rows() - pre_ledger,
        "ledger_for_invoice": ledger_rows(row["id"]),
        "patient": row["patient_name"],
        "net_amount": row["net_amount"],
        "expected_net": expected_net,
        "bill_no": page._hist_table.item(0, 0).text(),
        "history_amount": page._hist_table.item(0, 12).text(),
        "history_has_bill": bill_no_present(page._hist_table,
                                            page._hist_table.item(0, 0).text()),
        "popup_closed": not hasattr(panel, "_review_dialog"),
        "history_rows": page._hist_table.rowCount(),
    }


print("\n--- Scenario 2: review then final Save (single click) ---")
single = run_commit_scenario(clicks=1, qty=3)
check("popup opens after Save Sale", single["opened"])
check("stock untouched before final Save",
      single["stock_before_final"] == single["pre_stock"],
      f"{single['stock_before_final']} == {single['pre_stock']}")
check("exactly one invoice created", single["invoices_delta"] == 1,
      str(single["invoices_delta"]))
check("stock reduced exactly once by the sold qty",
      single["stock_after"] == single["pre_stock"] - 3,
      f"{single['pre_stock']} -> {single['stock_after']}")
check("accounting posted for the new invoice", single["ledger_for_invoice"] > 0,
      f"{single['ledger_for_invoice']} ledger rows")
check("popup closed after final Save", single["popup_closed"])
check("history amount matches net receivable",
      abs(float(single["history_amount"]) - single["expected_net"]) < 0.01,
      f"history={single['history_amount']} expected={single['expected_net']}")
check("patient recorded correctly",
      single["patient"] == "Acceptance Patient", single["patient"])

conn = get_connection()
try:
    item_count = conn.execute(
        "SELECT COUNT(*) c FROM sales_invoice_items WHERE sales_invoice_id = ?",
        (conn.execute("SELECT id FROM sales_invoices ORDER BY id DESC LIMIT 1")
         .fetchone()["id"],),
    ).fetchone()["c"]
finally:
    conn.close()
check("one set of bill items written", item_count == 1, str(item_count))

print("\n--- Scenario 2b: double click on Save creates nothing extra ---")
double = run_commit_scenario(clicks=2, qty=2)
check("double click still creates exactly one invoice",
      double["invoices_delta"] == 1, str(double["invoices_delta"]))
check("double click deducts stock exactly once",
      double["stock_after"] == double["pre_stock"] - 2,
      f"{double['pre_stock']} -> {double['stock_after']}")
check("double click posts the same single ledger set",
      double["ledger_for_invoice"] == single["ledger_for_invoice"],
      f"single={single['ledger_for_invoice']} double={double['ledger_for_invoice']}")

print("\n--- Scenario 2c: committed bill is visible in Sales History ---")
page3 = build_page()
check("history lists the new bills without a restart",
      bill_no_present(page3._hist_table, single["bill_no"])
      and bill_no_present(page3._hist_table, double["bill_no"]),
      f"{single['bill_no']}, {double['bill_no']}")

# ---------------------------------------------------------------- scenario 3
print("\n--- Scenario 3: editing an existing sale updates in place ---")
page_edit = build_page()
for row in range(page_edit._hist_table.rowCount()):
    if page_edit._hist_table.item(row, 0).text() == single["bill_no"]:
        page_edit._hist_table.selectRow(row)
        break
page_edit._on_edit()
app.processEvents()
pre_invoices = invoice_count()
panel3 = page_edit._sale_panel
check("existing bill loaded into the sale area",
      panel3._invoice is not None)
panel3._on_save()
app.processEvents()
dlg3 = panel3._review_dialog
check("edit opens the same review popup", dlg3 is not None)
check("edit popup carries the existing invoice",
      dlg3._panel._invoice is not None)
dlg3._panel.bill_disc_edit.setText("3")
dlg3._final_save_btn.click()
app.processEvents()
check("edit does not create a duplicate invoice",
      invoice_count() == pre_invoices,
      f"{pre_invoices} -> {invoice_count()}")
check("edited bill keeps its number",
      bill_no_present(build_page()._hist_table, single["bill_no"]),
      single["bill_no"])

print("\n================ SUMMARY ================")
failed = [r for r in results if not r[1]]
print(f"checks: {len(results)}   passed: {len(results) - len(failed)}   "
      f"failed: {len(failed)}")
for name, _, detail in failed:
    print("  FAILED:", name, detail)

for suffix in ("", "-wal", "-shm"):
    if os.path.exists(WORK_DB + suffix):
        os.remove(WORK_DB + suffix)
sys.exit(1 if failed else 0)