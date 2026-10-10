"""Test pagination with different item counts."""
import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from database import document_printing as printing
from database.connection import get_connection, init_database
from database import pharmacy_a6_receipt as a6

PT_PER_MM = 72.0 / 25.4

def media_boxes(data: bytes) -> list[tuple[float, float]]:
    found = []
    for box in re.findall(rb"/MediaBox \[([^\]]+)\]", data):
        parts = [float(value) for value in box.split()]
        found.append((parts[2], parts[3]))
    return found

def page_count(data: bytes) -> int:
    match = re.search(rb"/Type\s*/Pages.*?/Count\s+(\d+)", data, re.S)
    if match:
        return int(match.group(1))
    return len(re.findall(rb"/Type\s*/Page[^s]", data))

# Set up temp database
db_path = os.path.join(tempfile.gettempdir(), "pharmacy_pagination_test.db")
if os.path.exists(db_path):
    os.remove(db_path)
os.environ["PHARMACY_DB"] = db_path
init_database()

conn = get_connection()
conn.execute("INSERT INTO customers (id, customer_name) VALUES (1,'Customer One')")
conn.execute("INSERT INTO doctors (id, doctor_name) VALUES (1,'Dr Smith')")
conn.execute("INSERT INTO units (id, unit_name) VALUES (1,'TABLET')")
conn.execute("INSERT INTO companies (id, company_name, short_name) VALUES (1,'Cipla Limited','CIPLA')")
conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate) VALUES (1,'L-CIN 250',1,1,'10x10',25.7,20)")
conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty) VALUES (1,1,'JC00541','2028-01-31','10x10',25.7,20,50)")
conn.execute(
    "INSERT INTO sales_invoices (id, bill_no, sale_date, sale_time, sale_type, customer_id, patient_name, doctor_id, discount, paid_amount, total_amount, round_off, net_amount, remarks) VALUES (1,'CS-0001','2026-09-27','10:30','Cash',1,'Sunita Patil',1,0,25.7,25.7,0,25.7,'')")
conn.commit()
conn.close()

def add_items(count):
    conn = get_connection()
    conn.execute("DELETE FROM sales_invoice_items")
    for index in range(1, count + 1):
        item_id = 100 + index
        batch_id = 100 + index
        batch_no = f"B-{index:03d}"
        conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate) VALUES (?,?,1,1,'10x10',50,40)", (item_id, f"Item {index}"))
        conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty) VALUES (?,?,?,'12/27','10x10',50,40,100)", (batch_id, item_id, batch_no))
        conn.execute(
            "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size, location, batch_no, expiry, mrp, sale_qty, discount_amount, amount) VALUES (1,?,?,?,'10x10','',?,'12/27',50,1,0,48)",
            (item_id, batch_id, batch_no))
    conn.commit()
    conn.close()

def test_pagination(item_count, expected_pages):
    add_items(item_count)
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / f"bill_{item_count}.pdf"
    output = printing.generate_pharmacy_a6_bill(1, path, "Sales Bill")
    data = Path(output).read_bytes()
    pc = page_count(data)
    boxes = media_boxes(data)
    
    all_correct = True
    for i, (w, h) in enumerate(boxes):
        w_mm = w / PT_PER_MM
        h_mm = h / PT_PER_MM
        if abs(w_mm - 105.0) > 0.5 or abs(h_mm - 140.0) > 0.5:
            all_correct = False
            print(f"  Page {i+1} dimensions wrong: {w_mm:.2f} x {h_mm:.2f} mm")
    
    status = "PASS" if (pc == expected_pages and all_correct) else "FAIL"
    print(f"  {item_count} items: {pc} pages (expected {expected_pages}) - {status}")
    tmp.cleanup()

print("Pagination tests:")
test_pagination(1, 1)
test_pagination(7, 1)
test_pagination(9, 1)
test_pagination(10, 2)
test_pagination(18, 2)
test_pagination(20, 3)