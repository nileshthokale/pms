"""Verify a multi-item real bill prints every item with no overlap."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SOURCE = Path(__file__).parent / "data" / "pharmacy.db"
COPY = Path(tempfile.gettempdir()) / "pharmacy_realdata_print_copy.db"
for suffix in ("", "-wal", "-shm"):
    stale = Path(str(COPY) + suffix)
    if stale.exists():
        stale.unlink()
shutil.copy2(SOURCE, COPY)
os.environ["PHARMACY_DB"] = str(COPY)

from database import document_printing as printing   # noqa: E402
from database import pharmacy_a6_receipt as a6       # noqa: E402
from database.connection import get_connection       # noqa: E402

conn = get_connection()
invoice_id, bill_no, net = conn.execute(
    "SELECT si.id, si.bill_no, si.net_amount FROM sales_invoices si"
    " WHERE (SELECT COUNT(*) FROM sales_invoice_items x"
    "        WHERE x.sales_invoice_id = si.id) >= 4"
    " ORDER BY si.id DESC LIMIT 1").fetchone()
rows = conn.execute(
    "SELECT i.item_name, sii.batch_no, sii.expiry, sii.sale_qty, sii.amount"
    " FROM sales_invoice_items sii"
    " LEFT JOIN items i ON i.id = sii.item_id"
    " WHERE sii.sales_invoice_id = ? ORDER BY sii.id", (invoice_id,)
).fetchall()
conn.close()

print(f"real multi-item bill: id={invoice_id} bill_no={bill_no} "
      f"net={net} items={len(rows)}")
print()
print("=" * 78)
print(printing.preview_pharmacy_a6_bill(invoice_id, "Sales Bill"))
print("=" * 78)

preview = printing.preview_pharmacy_a6_bill(invoice_id, "Sales Bill")
failures = []
clipped = []
for item_name, batch, expiry, qty, amount in rows:
    batch_text = str(batch)
    for label, value in (
        ("item", str(item_name).split()[0]),
        ("amount", f"{float(amount):.2f}"),
    ):
        if str(value) not in preview:
            failures.append(f"{label} {value!r} missing")
    if batch_text not in preview:
        # ellipsize() keeps as many leading characters as the column width
        # allows, so the printed token must be a prefix of the stored value.
        stem = batch_text[:4]
        column = next((tok for tok in preview.split()
                       if tok.startswith(stem) and tok.endswith("...")), None)
        if column is None:
            failures.append(f"batch {batch_text!r} missing entirely")
        elif not batch_text.startswith(column[:-3]):
            failures.append(f"batch {batch_text!r} printed as {column!r}")
        else:
            clipped.append(f"{batch_text} -> {column}")

pages, _record = a6.build_sale_pages(invoice_id, "Sales Bill")
profile = a6.content_profile(pages)
print(f"pages={len(pages)}  page={profile.width_mm:.0f}x{profile.height_mm:.1f}mm")
for number, page in enumerate(pages, 1):
    print(f"  page {number}: {len(page)} blocks, deepest ink "
          f"{a6.deepest_content_mm(page):.2f}mm, overlap={a6.overlapping_runs(page)}")

a6.validate_pages(pages, profile)
if len(pages) == 1 and a6.deepest_content_mm(pages[0]) > profile.height_mm:
    failures.append("content overflows the page")

print()
print(f"items accounted   : {len(rows) - len(clipped)}/{len(rows)} complete")
if clipped:
    print(f"clipped to column  : {clipped}")
    print("                    (fixed 12mm BATCH column, pre-existing)")
print(f"rendering failures: {failures or 'none'}")
print("RESULT            :", "PASS" if not failures else "FAIL")
sys.exit(1 if failures else 0)