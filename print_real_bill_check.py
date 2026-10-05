"""Section 20 real-data print check.

Copies the production database to a temporary file and prints a real stored
bill from the COPY, so ``data/pharmacy.db`` is never opened for writing and
no historical sale can be modified.
"""

import hashlib
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

before_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
before_size = SOURCE.stat().st_size

os.environ["PHARMACY_DB"] = str(COPY)

from database import document_printing as printing   # noqa: E402
from database import pharmacy_a6_receipt as a6       # noqa: E402
from database.connection import get_connection, get_db_path   # noqa: E402

print(f"production db : {SOURCE} ({before_size} bytes)")
print(f"copy db       : {COPY}")
print(f"active db     : {get_db_path()}")

def _sale_digest(conn, invoice_id):
    """Content hash of the stored sale row (plain tuples, not Row reprs)."""
    rows = [tuple(row) for row in conn.execute(
        "SELECT id, bill_no, sale_date, net_amount FROM sales_invoices WHERE id=?",
        (invoice_id,)).fetchall()]
    return hashlib.sha256(repr(rows).encode()).hexdigest()


conn = get_connection()
invoice_id, bill_no = conn.execute(
    "SELECT id, bill_no FROM sales_invoices WHERE sale_date = '2026-10-04'"
    " AND id = (SELECT MAX(id) FROM sales_invoices WHERE sale_date = '2026-10-04')"
).fetchone()
rows_before = {
    table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    for table in ("sales_invoices", "sales_invoice_items", "stock_batches",
                  "ledger_transactions")
}
row_digest_before = _sale_digest(conn, invoice_id)
conn.close()
print(f"\nreal bill used: id={invoice_id}  bill_no={bill_no}")

print()
print("=" * 62)
print("REAL BILL PRINT PREVIEW")
print("=" * 62)
print(printing.preview_pharmacy_a6_bill(invoice_id, "Sales Bill"))

out = Path(tempfile.gettempdir()) / "real_sales_bill.pdf"
path = printing.generate_counter_sale_bill(invoice_id, out)
data = Path(path).read_bytes()
print()
print(f"PDF written: {path} ({len(data)} bytes) valid={data.startswith(b'%PDF')}")

conn = get_connection()
rows_after = {
    table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    for table in ("sales_invoices", "sales_invoice_items", "stock_batches",
                  "ledger_transactions")
}
row_digest_after = _sale_digest(conn, invoice_id)
conn.close()

after_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

print()
print("=" * 62)
print("SAFETY CHECKS")
print("=" * 62)
print(f"  copy row counts unchanged      : {rows_before == rows_after}")
print(f"  copied sale row unchanged      : {row_digest_before == row_digest_after}")
print(f"  production db hash unchanged   : {before_hash == after_hash}")
print(f"  production db size unchanged   : {before_size == SOURCE.stat().st_size}")
print(f"  production db never opened for write: {str(SOURCE) != get_db_path()}")