import sqlite3
import json

def get_db_conns():
    con_stag = sqlite3.connect('staging/pharmacy_staging_refresh.db')
    con_stag.row_factory = sqlite3.Row
    con_live = sqlite3.connect('data/pharmacy.db')
    con_live.row_factory = sqlite3.Row
    return con_stag, con_live

con_stag, con_live = get_db_conns()

# 1. Purchase Details
cur_stag = con_stag.cursor()
cur_stag.execute('''
    SELECT pi.id, pi.purchase_invoice_id, p.invoice_no, p.invoice_date, p.supplier_id, s.name as supplier_name,
           pi.item_id, it.name as item_name, pi.batch_no, pi.expiry,
           pi.pack_size, pi.pay_qty, pi.free_qty, pi.rate, pi.mrp, pi.gst_percent, pi.amount
    FROM purchase_invoice_items pi
    JOIN purchase_invoices p ON pi.purchase_invoice_id = p.id
    LEFT JOIN suppliers s ON p.supplier_id = s.id
    LEFT JOIN items it ON pi.item_id = it.id
    WHERE pi.id > 11892
    ORDER BY pi.id
''')
added_purchases = [dict(r) for r in cur_stag.fetchall()]
print(f"Added purchase items: {len(added_purchases)}")

# Native purchase row
cur_stag.execute('''
    SELECT pi.id, pi.purchase_invoice_id, p.invoice_no, p.invoice_date, p.supplier_id, s.name as supplier_name,
           pi.item_id, it.name as item_name, pi.batch_no, pi.expiry,
           pi.pack_size, pi.pay_qty, pi.free_qty, pi.rate, pi.mrp, pi.gst_percent, pi.amount
    FROM purchase_invoice_items pi
    JOIN purchase_invoices p ON pi.purchase_invoice_id = p.id
    LEFT JOIN suppliers s ON p.supplier_id = s.id
    LEFT JOIN items it ON pi.item_id = it.id
    WHERE pi.id = 11892
''')
native_purchase = dict(cur_stag.fetchone())
print(f"Native purchase item: {native_purchase['id']}, invoice {native_purchase['invoice_no']}")

# 2. Sales Details
cur_stag.execute('''
    SELECT count(*) FROM sales_invoice_items WHERE id > 233595
''')
added_sales_count = cur_stag.fetchone()[0]
print(f"Added sales items: {added_sales_count}")

# Check deleted invoice 72160
cur_stag.execute('''
    SELECT * FROM legacy_id_map WHERE entity = 'sale' AND legacy_id = '72160'
''')
map_72160 = cur_stag.fetchone()
print(f"Legacy sale 72160 map: {dict(map_72160) if map_72160 else None}")

# Check if target sale 71988 exists in sales_invoices
cur_stag.execute('''
    SELECT * FROM sales_invoices WHERE id = 71988
''')
row_71988 = cur_stag.fetchone()
print(f"Target sale 71988 exists in sales_invoices: {row_71988 is not None}")

# Check native sale 72048
cur_stag.execute('''
    SELECT id, invoice_no, invoice_date, customer_id, total_amount
    FROM sales_invoices WHERE id = 72048
''')
native_sale = cur_stag.fetchone()
print(f"Native sale 72048: {dict(native_sale) if native_sale else None}")

# Check collision legacy sale 72219
cur_stag.execute('''
    SELECT id, invoice_no, invoice_date, customer_id, total_amount
    FROM sales_invoices WHERE invoice_no LIKE '%72219%'
''')
coll_sale = cur_stag.fetchone()
print(f"Collision sale 72219: {dict(coll_sale) if coll_sale else None}")
