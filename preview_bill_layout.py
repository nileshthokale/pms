"""Print-only preview dump for a real stored sale (temp DB, no real data touched)."""

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB = os.path.join(tempfile.gettempdir(), "pharmacy_bill_preview.db")
if os.path.exists(DB):
    os.remove(DB)
os.environ["PHARMACY_DB"] = DB

from database.connection import init_database, get_connection, get_db_path   # noqa: E402
from database import document_printing as printing                          # noqa: E402
from database import pharmacy_a6_receipt as a6                              # noqa: E402

init_database()
assert "data/pharmacy.db" not in get_db_path().replace("\\", "/"), get_db_path()

conn = get_connection()
conn.execute("DELETE FROM sales_invoice_items")
conn.execute("DELETE FROM sales_invoices")
conn.execute("DELETE FROM stock_batches")
conn.execute("DELETE FROM items")
conn.execute("DELETE FROM units")
conn.execute("DELETE FROM companies")
conn.execute("DELETE FROM customers")
conn.execute("DELETE FROM doctors")
conn.execute("INSERT INTO customers (id, customer_name) VALUES (1,'Customer One')")
conn.execute("INSERT INTO doctors (id, doctor_name) VALUES (1,'Dr Smith')")
conn.execute("INSERT INTO units (id, unit_name) VALUES (1,'TABLET')")
conn.execute("INSERT INTO units (id, unit_name) VALUES (2,'BOTTLE')")
conn.execute("INSERT INTO companies (id, company_name, short_name) VALUES (1,'Cipla Ltd','CIPLA')")
conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
             " VALUES (1,'L-CIN 250',1,1,'10x10',25.7,20)")
conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
             " VALUES (2,'Azithromycin 500mg Tablets',1,1,'10x10',54.0,44)")
conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
             " purchase_rate, stock_qty) VALUES (1,1,'JC00541','2028-01-31','10x10',25.7,20,50)")
conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
             " purchase_rate, stock_qty) VALUES (2,2,'AZ90012','12/27','10x10',54.0,44,50)")
conn.execute(
    "INSERT INTO sales_invoices (id, bill_no, sale_date, sale_time, sale_type, customer_id,"
    " patient_name, doctor_id, discount, paid_amount, total_amount, round_off, net_amount, remarks)"
    " VALUES (1,'CS-0001','2026-10-04','10:30','Cash',1,'Sunita Patil',1,0,79.7,79.7,0,79.7,'')")
conn.execute(
    "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
    " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
    " VALUES (1,1,1,'10x10','','JC00541','2028-01-31',25.7,1,0,25.70)")
conn.execute(
    "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
    " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
    " VALUES (1,2,2,'10x10','','AZ90012','12/27',54.0,1,0,54.00)")
conn.commit()
conn.close()

print("=" * 60)
print("PLAIN PREVIEW")
print("=" * 60)
print(printing.preview_pharmacy_a6_bill(1, "Sales Bill"))

out = Path(tempfile.gettempdir()) / "bill_preview.pdf"
path = printing.generate_counter_sale_bill(1, out)
data = Path(path).read_bytes()
print()
print("=" * 60)
print(f"PDF: {path}  ({len(data)} bytes)  valid={data.startswith(b'%PDF')}")
print("=" * 60)
for marker in (b"SAMARTH", b"GHORPADE", b"RAHURI", b"AHMEDNAGAR", b"GSTIN"):
    print(f"  contains {marker.decode():12s} -> {marker in data}")
for marker in (b"TABLET", b"CIPLA", b"JC00541", b"31/01/2028", b"12/2027",
               b"Cash Memo", b"Name :", b"Doctor :", b"Net Amt", b"25.70",
               b"54.00", b"E & O E.", b"Pharmacist/Sign"):
    print(f"  contains {marker.decode():16s} -> {marker in data}")