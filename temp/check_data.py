"""Temporary script to inspect production data conventions."""
import sqlite3

conn = sqlite3.connect("data/pharmacy.db")
conn.row_factory = sqlite3.Row

# 1. Check stock for specific items bought with packs
print("=== STOCK for items bought in packs ===")
rows = conn.execute("""
    SELECT sb.id, i.item_name, sb.batch_no, sb.pack_size, sb.mrp, sb.stock_qty,
           sb.purchase_rate, sb.net_rate
    FROM stock_batches sb
    LEFT JOIN items i ON i.id = sb.item_id
    WHERE i.item_name IN ('RAZO 20', 'CETIL 250', 'MYOTOP 450 SR', 'LEVOMAC 500MG')
    ORDER BY i.item_name, sb.batch_no
""").fetchall()
for r in rows:
    print(dict(r))

# 2. Cross-check purchase qty vs stock for those items
print("\n=== PURCHASES for those items ===")
rows = conn.execute("""
    SELECT pii.pack_size, pii.pay_qty, pii.free_qty, pii.mrp, pii.rate,
           i.item_name, pi.voucher_no, pi.voucher_date
    FROM purchase_invoice_items pii
    LEFT JOIN items i ON i.id = pii.item_id
    LEFT JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id
    WHERE i.item_name IN ('RAZO 20', 'CETIL 250', 'MYOTOP 450 SR', 'LEVOMAC 500MG')
    ORDER BY i.item_name, pi.voucher_date
""").fetchall()
for r in rows:
    print(dict(r))

# 3. Sales that have been made with qty < pack_size
print("\n=== SALES with qty < pack_size (to understand current unit semantics) ===")
rows = conn.execute("""
    SELECT sii.pack_size, sii.sale_qty, sii.mrp, sii.amount,
           i.item_name, si.bill_no, si.sale_date
    FROM sales_invoice_items sii
    LEFT JOIN items i ON i.id = sii.item_id
    LEFT JOIN sales_invoices si ON si.id = sii.sales_invoice_id
    WHERE sii.pack_size NOT IN ('1', '')
    ORDER BY i.item_name, si.sale_date
    LIMIT 20
""").fetchall()
for r in rows:
    print(dict(r))

# 4. Check BIO D3 PLUS specifically
print("\n=== BIO D3 PLUS ===")
rows = conn.execute("""
    SELECT sb.*, i.item_name
    FROM stock_batches sb
    LEFT JOIN items i ON i.id = sb.item_id
    WHERE i.item_name LIKE '%BIO D3%'
""").fetchall()
for r in rows:
    print(dict(r))

# 5. Check items where pack_size is NOT '1' - how is stock_qty populated vs purchases
print("\n=== ITEMS WITH pack_size > 1: current stock vs purchases ===")
rows = conn.execute("""
    SELECT i.item_name, i.pack_size, i.mrp as item_mrp,
           SUM(sii.sale_qty) as total_sold,
           SUM(sii.amount) as total_sales_amount,
           AVG(sii.mrp) as avg_sale_mrp
    FROM items i
    LEFT JOIN sales_invoice_items sii ON sii.item_id = i.id
    WHERE CAST(i.pack_size AS INTEGER) > 1
    GROUP BY i.id
    HAVING total_sold > 0
    LIMIT 15
""").fetchall()
for r in rows:
    d = dict(r)
    if d['pack_size'] and d['pack_size'] not in ('1', ''):
        try:
            ps = int(d['pack_size'])
            if ps > 0 and d['avg_sale_mrp'] and d['total_sold']:
                # If sale_qty is in packs: amount should be qty * mrp
                # If sale_qty is in units: amount should be qty * (mrp/pack_size)
                if d['total_sold'] > 0:
                    as_packs = d['total_sales_amount'] / d['total_sold'] if d['total_sold'] else 0
                    as_units = d['total_sales_amount'] / (d['total_sold'] * ps) if d['total_sold'] * ps else 0
                    d['_implied_mrp_per_unit_if_packs'] = round(as_packs, 2)
                    d['_implied_mrp_per_unit_if_units'] = round(as_units, 2)
                    d['_item_mrp'] = d['item_mrp']
        except (ValueError, TypeError):
            pass
    print(d)

# 6. Check historical sales where pack_size > 1 - qty * mrp == amount?
print("\n=== VERIFY: qty * mrp == amount for historical sales (pack_size > 1) ===")
rows = conn.execute("""
    SELECT sii.pack_size, sii.sale_qty, sii.mrp, sii.amount, i.item_name
    FROM sales_invoice_items sii
    LEFT JOIN items i ON i.id = sii.item_id
    WHERE CAST(sii.pack_size AS INTEGER) > 1
    LIMIT 20
""").fetchall()
for r in rows:
    d = dict(r)
    ps = int(d['pack_size']) if d['pack_size'] else 1
    qty = d['sale_qty']
    mrp = d['mrp']
    amount = d['amount']
    # Theory A (current): amount = qty * mrp (treating qty as packs)
    as_packs = round(qty * mrp, 2)
    # Theory B (desired): amount = qty * mrp / pack_size (treating qty as units)
    as_units = round(qty * mrp / ps, 2)
    d['_as_packs'] = as_packs
    d['_as_units'] = as_units
    d['_amount_matches'] = 'PACKS' if abs(as_packs - amount) < 0.02 else ('UNITS' if abs(as_units - amount) < 0.02 else 'NEITHER')
    print(d)

# 7. Check BIO D3 PLUS stock batches
print("\n=== BIO D3 PLUS all info ===")
rows = conn.execute("""
    SELECT i.item_name, i.pack_size, i.mrp as item_mrp, i.rate as item_rate
    FROM items i WHERE i.item_name LIKE '%BIO D3%'
""").fetchall()
for r in rows:
    print(dict(r))

# 8. Check historical sales for BIO D3 PLUS
rows = conn.execute("""
    SELECT sii.pack_size, sii.sale_qty, sii.mrp, sii.amount, si.bill_no
    FROM sales_invoice_items sii
    LEFT JOIN items i ON i.id = sii.item_id
    LEFT JOIN sales_invoices si ON si.id = sii.sales_invoice_id
    WHERE i.item_name LIKE '%BIO D3%'
""").fetchall()
print("Sales history for BIO D3 PLUS:")
for r in rows:
    print(dict(r))

# 9. Verify the math for ALL historical sales
print("\n=== HISTORICAL SALES MATH CHECK (pack_size=1 items) ===")
rows = conn.execute("""
    SELECT sii.pack_size, sii.sale_qty, sii.mrp, sii.amount, i.item_name
    FROM sales_invoice_items sii
    LEFT JOIN items i ON i.id = sii.item_id
    WHERE sii.pack_size = '1' OR sii.pack_size = ''
    LIMIT 10
""").fetchall()
for r in rows:
    d = dict(r)
    qty = d['sale_qty']
    mrp = d['mrp']
    amount = d['amount']
    d['_qty_times_mrp'] = round(qty * mrp, 2)
    d['_match'] = abs(round(qty * mrp, 2) - amount) < 0.02
    print(d)

conn.close()
