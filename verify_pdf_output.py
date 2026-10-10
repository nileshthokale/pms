"""Generate a sample A6 PDF and verify its dimensions."""
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
db_path = os.path.join(tempfile.gettempdir(), "pharmacy_verify_test.db")
if os.path.exists(db_path):
    os.remove(db_path)
os.environ["PHARMACY_DB"] = db_path
init_database()

# Insert test data
conn = get_connection()
conn.execute("INSERT INTO customers (id, customer_name) VALUES (1,'Customer One')")
conn.execute("INSERT INTO doctors (id, doctor_name) VALUES (1,'Dr Smith')")
conn.execute("INSERT INTO units (id, unit_name) VALUES (1,'TABLET')")
conn.execute("INSERT INTO companies (id, company_name, short_name) VALUES (1,'Cipla Limited','CIPLA')")
conn.execute("INSERT INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate) VALUES (1,'L-CIN 250',1,1,'10x10',25.7,20)")
conn.execute("INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty) VALUES (1,1,'JC00541','2028-01-31','10x10',25.7,20,50)")
conn.execute(
    "INSERT INTO sales_invoices (id, bill_no, sale_date, sale_time, sale_type, customer_id, patient_name, doctor_id, discount, paid_amount, total_amount, round_off, net_amount, remarks) VALUES (1,'CS-0001','2026-09-27','10:30','Cash',1,'Sunita Patil',1,0,25.7,25.7,0,25.7,'')")
conn.execute(
    "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size, location, batch_no, expiry, mrp, sale_qty, discount_amount, amount) VALUES (1,1,1,'10x10','','JC00541','2028-01-31',25.7,1,0,25.70)")
conn.commit()
conn.close()

# Generate PDF
tmp = tempfile.TemporaryDirectory()
path = Path(tmp.name) / "test_bill.pdf"
output = printing.generate_pharmacy_a6_bill(1, path, "Sales Bill")
data = Path(output).read_bytes()

print(f"PDF generated: {output}")
print(f"File size: {len(data)} bytes")
print(f"Starts with %PDF-1.4: {data.startswith(b'%PDF-1.4')}")
print(f"Ends with %%EOF: {data.rstrip().endswith(b'%%EOF')}")

# Check page dimensions
boxes = media_boxes(data)
print(f"\nMedia boxes: {boxes}")
for i, (w, h) in enumerate(boxes):
    w_mm = w / PT_PER_MM
    h_mm = h / PT_PER_MM
    print(f"  Page {i+1}: {w_mm:.2f} x {h_mm:.2f} mm")

# Check page count
pc = page_count(data)
print(f"\nPage count: {pc}")

# Check content
print(f"\nContains 'Sales Bill': {b'Sales Bill' in data}")
print(f"Contains 'SHREE SAMARTH': {b'SHREE SAMARTH' in data}")
print(f"Contains 'GHORPADE HOSPITAL': {b'GHORPADE HOSPITAL' in data}")
print(f"Contains 'Name : Sunita Patil': {b'Name : Sunita Patil' in data}")
print(f"Contains 'Doctor : Dr Smith': {b'Doctor : Dr Smith' in data}")
print(f"Contains 'Cash Memo : CS-0001': {b'Cash Memo : CS-0001' in data}")
print(f"Contains 'Date : 2026-09-27': {b'Date : 2026-09-27' in data}")
print(f"Contains 'QTY': {b'QTY' in data}")
print(f"Contains 'UNIT': {b'UNIT' in data}")
print(f"Contains 'DESCRIPTION': {b'DESCRIPTION' in data}")
print(f"Contains 'COMP.': {b'COMP.' in data}")
print(f"Contains 'BATCH': {b'BATCH' in data}")
print(f"Contains 'EXP. DT': {b'EXP. DT' in data}")
print(f"Contains 'AMT': {b'AMT' in data}")
print(f"Contains 'L-CIN 250': {b'L-CIN 250' in data}")
print(f"Contains 'CIPLA': {b'CIPLA' in data}")
print(f"Contains 'JC00541': {b'JC00541' in data}")
print(f"Contains '31/01/2028': {b'31/01/2028' in data}")
print(f"Contains '25.70': {b'25.70' in data}")
print(f"Contains 'Net Amt :': {b'Net Amt :' in data}")
print(f"Contains 'E & O E.': {b'E & O E.' in data}")
print(f"Contains 'Pharmacist/Sign': {b'Pharmacist/Sign' in data}")
print(f"Contains 'AHMEDNAGAR': {b'AHMEDNAGAR' in data}")

# Verify page dimensions match 105x140mm
if boxes:
    w_mm = boxes[0][0] / PT_PER_MM
    h_mm = boxes[0][1] / PT_PER_MM
    print(f"\nPage dimensions: {w_mm:.2f} x {h_mm:.2f} mm")
    print(f"Width is 105mm: {abs(w_mm - 105.0) < 0.5}")
    print(f"Height is 140mm: {abs(h_mm - 140.0) < 0.5}")

tmp.cleanup()