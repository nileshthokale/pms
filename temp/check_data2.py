"""Verify purchase/stock convention."""
import sqlite3

conn = sqlite3.connect("data/pharmacy.db")
conn.row_factory = sqlite3.Row

# RAZO 20: pack_size=15, MRP=126.0
print("=== RAZO 20 STOCK BATCHES ===")
rows = conn.execute(
    "SELECT sb.*, i.item_name FROM stock_batches sb "
    "LEFT JOIN items i ON i.id = sb.item_id "
    "WHERE i.item_name = 'RAZO 20'"
).fetchall()
for r in rows:
    print(dict(r))

print("\n=== RAZO 20 RECENT PURCHASES ===")
rows = conn.execute(
    "SELECT pii.pack_size, pii.pay_qty, pii.free_qty, pii.mrp, i.item_name "
    "FROM purchase_invoice_items pii "
    "LEFT JOIN items i ON i.id = pii.item_id "
    "WHERE i.item_name = 'RAZO 20' "
    "ORDER BY pii.id DESC LIMIT 5"
).fetchall()
for r in rows:
    print(dict(r))

print("\n=== RAZO 20 SALES (all) ===")
rows = conn.execute(
    "SELECT sii.pack_size, sii.sale_qty, sii.mrp, sii.amount, si.bill_no "
    "FROM sales_invoice_items sii "
    "LEFT JOIN items i ON i.id = sii.item_id "
    "LEFT JOIN sales_invoices si ON si.id = sii.sales_invoice_id "
    "WHERE i.item_name = 'RAZO 20' "
    "ORDER BY si.sale_date DESC LIMIT 10"
).fetchall()
for r in rows:
    print(dict(r))

# Check BIO D3 PLUS - the specific MRP 341.34 item
print("\n=== BIO D3 PLUS STOCK ===")
rows = conn.execute(
    "SELECT sb.*, i.item_name FROM stock_batches sb "
    "LEFT JOIN items i ON i.id = sb.item_id "
    "WHERE i.item_name LIKE '%BIO D3%'"
).fetchall()
for r in rows:
    print(dict(r))

print("\n=== BIO D3 PLUS PURCHASES ===")
rows = conn.execute(
    "SELECT pii.pack_size, pii.pay_qty, pii.free_qty, pii.mrp, i.item_name, pi.voucher_no, pi.voucher_date "
    "FROM purchase_invoice_items pii "
    "LEFT JOIN items i ON i.id = pii.item_id "
    "LEFT JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id "
    "WHERE i.item_name LIKE '%BIO D3%' "
    "ORDER BY pi.voucher_date DESC LIMIT 5"
).fetchall()
for r in rows:
    print(dict(r))

print("\n=== BIO D3 PLUS SALES (recent) ===")
rows = conn.execute(
    "SELECT sii.pack_size, sii.sale_qty, sii.mrp, sii.amount, si.bill_no, si.sale_date "
    "FROM sales_invoice_items sii "
    "LEFT JOIN items i ON i.id = sii.item_id "
    "LEFT JOIN sales_invoices si ON si.id = sii.sales_invoice_id "
    "WHERE i.item_name LIKE '%BIO D3%' "
    "ORDER BY si.sale_date DESC LIMIT 10"
).fetchall()
for r in rows:
    d = dict(r)
    ps = int(d['pack_size']) if d['pack_size'] else 1
    d['_unit_price'] = round(d['mrp'] / ps, 4) if ps > 0 else 0
    d['_amount_if_units'] = round(d['sale_qty'] * d['mrp'] / ps, 2) if ps > 0 else 0
    d['_amount_if_packs'] = round(d['sale_qty'] * d['mrp'], 2)
    d['_match'] = 'UNITS' if abs(d['_amount_if_units'] - d['amount']) < 0.02 else (
        'PACKS' if abs(d['_amount_if_packs'] - d['amount']) < 0.02 else 'NEITHER'
    )
    print(d)

# Check CETIL 250: pack_size=6, pay_qty=10, free_qty=1
print("\n=== CETIL 250 STOCK ===")
rows = conn.execute(
    "SELECT sb.*, i.item_name FROM stock_batches sb "
    "LEFT JOIN items i ON i.id = sb.item_id "
    "WHERE i.item_name = 'CETIL 250'"
).fetchall()
for r in rows:
    print(dict(r))

print("\n=== CETIL 250 PURCHASES ===")
rows = conn.execute(
    "SELECT pii.pack_size, pii.pay_qty, pii.free_qty, pii.mrp, i.item_name "
    "FROM purchase_invoice_items pii "
    "LEFT JOIN items i ON i.id = pii.item_id "
    "WHERE i.item_name = 'CETIL 250' "
    "ORDER BY pii.id DESC LIMIT 5"
).fetchall()
for r in rows:
    print(dict(r))

print("\n=== CETIL 250 SALES ===")
rows = conn.execute(
    "SELECT sii.pack_size, sii.sale_qty, sii.mrp, sii.amount, si.bill_no "
    "FROM sales_invoice_items sii "
    "LEFT JOIN items i ON i.id = sii.item_id "
    "LEFT JOIN sales_invoices si ON si.id = sii.sales_invoice_id "
    "WHERE i.item_name = 'CETIL 250' "
    "ORDER BY si.sale_date DESC LIMIT 10"
).fetchall()
for r in rows:
    print(dict(r))

# Check how purchases add stock: verify qty_to_add = pay_qty + free_qty
print("\n=== PURCHASE DAO LINE 190: qty_to_add = pay_qty + free_qty ===")
print("For CETIL 250: pay_qty=10, free_qty=1, pack_size=6")
print("qty_to_add = 10 + 1 = 11")
print("If this is in packs: stock += 11 * 6 = 66 units")
print("If this is in units: stock += 11 units")
print("Current stock:", end=" ")

rows = conn.execute(
    "SELECT SUM(sb.stock_qty) as total FROM stock_batches sb "
    "LEFT JOIN items i ON i.id = sb.item_id "
    "WHERE i.item_name = 'CETIL 250'"
).fetchall()
for r in rows:
    print(dict(r))

conn.close()
