"""Instrumented pagination dump for a many-item receipt."""

import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PHARMACY_DB"] = os.path.join(
    tempfile.gettempdir(), "pharmacy_bill_renderer.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import pharmacy_a6_receipt as a6          # noqa: E402
from database.connection import get_connection          # noqa: E402

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 40

conn = get_connection()
conn.execute("DELETE FROM sales_invoice_items")
for index in range(1, COUNT + 1):
    item_id = 100 + index
    conn.execute(
        "INSERT OR IGNORE INTO items (id, item_name, unit_id, company_id, pack_size, mrp, rate)"
        " VALUES (?,?,1,1,'10x10',50,40)", (item_id, f"Item {index}"))
    conn.execute(
        "INSERT OR IGNORE INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp,"
        " purchase_rate, stock_qty) VALUES (?,?,?,'12/27','10x10',50,40,100)",
        (item_id, item_id, f"B-{index:03d}"))
    conn.execute(
        "INSERT INTO sales_invoice_items (sales_invoice_id, item_id, stock_batch_id, pack_size,"
        " location, batch_no, expiry, mrp, sale_qty, discount_amount, amount)"
        " VALUES (1,?,?,'10x10','A-1',?,'12/27',50,1,0,48)",
        (item_id, item_id, f"B-{index:03d}"))
conn.commit()
conn.close()

profile = a6.PHARMACY_A6
record, items = a6.load_sale(1, "Sales Bill")
blocks = a6.build_layout(record, items, {}, {}, profile)

head = [b for b in blocks if b.kind in {"header", "rule", "colhead"}]
repeating = [b for b in blocks if getattr(b, "repeat", False)]
tail = [b for b in blocks if b.kind in {"totals", "footer"}]
body = [b for b in blocks
        if b.kind not in {"header", "rule", "colhead", "totals", "footer"}]

print(f"items              : {len(items)}")
print(f"limit (content h)  : {profile.content_height_mm:.2f} mm")
print(f"head               : {sum(b.height_mm for b in head):.2f} mm ({len(head)} blocks)")
print(f"repeating          : {sum(b.height_mm for b in repeating):.2f} mm")
print(f"tail               : {sum(b.height_mm for b in tail):.2f} mm ({len(tail)} blocks)")
print(f"body               : {sum(b.height_mm for b in body):.2f} mm ({len(body)} blocks)")
print()
pages = a6.paginate(blocks, profile)
print(f"pages: {len(pages)}")
for number, page in enumerate(pages, 1):
    start = page[0].top_mm
    end = page[-1].top_mm + page[-1].height_mm
    deep = a6.deepest_content_mm(page)
    flag = "  <-- OVERFLOW" if deep > profile.height_mm else ""
    print(f"  page {number}: {len(page):3d} blocks  "
          f"start {start:7.2f}  block-end {end:7.2f}  deepest ink {deep:7.2f}{flag}")
    for block in page:
        if a6.deepest_content_mm([block]) + block.top_mm > profile.height_mm:
            for run in block.runs:
                if run.y_mm > profile.height_mm:
                    print(f"        offending run y={run.y_mm:.2f} {run.text[:40]!r} "
                          f"(block kind={block.kind} top={block.top_mm:.2f} h={block.height_mm:.2f})")