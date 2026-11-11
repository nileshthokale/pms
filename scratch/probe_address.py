from database.connection import get_connection
from database.purchase_dao import pack_factor

conn = get_connection()
cur = conn.cursor()

cur.execute("""
    SELECT
        i.id AS item_id,
        i.item_name,
        COALESCE(u.unit_name, '') AS unit_name,
        COALESCE(NULLIF(sii.pack_size, ''), i.pack_size, '1') AS pack_size,
        sii.sale_qty,
        sii.amount,
        COALESCE(NULLIF(sb.purchase_rate, 0), NULLIF(sb.net_rate, 0), i.rate, 0.0) AS purchase_rate
    FROM sales_invoice_items sii
    JOIN sales_invoices si ON si.id = sii.sales_invoice_id
    JOIN items i ON i.id = sii.item_id
    LEFT JOIN units u ON u.id = i.unit_id
    LEFT JOIN stock_batches sb ON sb.id = sii.stock_batch_id
    WHERE si.doctor_id = 9 AND si.sale_date >= '2026-04-01' AND si.sale_date <= '2026-10-19'
    ORDER BY i.item_name COLLATE NOCASE ASC
""")
raw_rows = [dict(r) for r in cur.fetchall()]

grouped = {}
for r in raw_rows:
    item_id = r["item_id"]
    qty = float(r.get("sale_qty") or 0.0)
    amt = float(r.get("amount") or 0.0)
    rate = float(r.get("purchase_rate") or 0.0)
    factor = pack_factor(r.get("pack_size", "1"))
    unit_cost = (rate / factor) if factor > 0 else rate
    cost = qty * unit_cost

    if item_id not in grouped:
        grouped[item_id] = {
            "item_name": r["item_name"],
            "unit_name": r["unit_name"],
            "sales_qty": 0.0,
            "sales_amount": 0.0,
            "purchase_cost": 0.0,
        }
    grouped[item_id]["sales_qty"] += qty
    grouped[item_id]["sales_amount"] += amt
    grouped[item_id]["purchase_cost"] += cost

print("First 10 grouped items:")
for item_id, g in list(grouped.items())[:10]:
    s_amt = round(g["sales_amount"], 2)
    p_cost = round(g["purchase_cost"], 2)
    profit = round(s_amt - p_cost, 2)
    print(f"{g['item_name']:<20} | Unit: {g['unit_name']:<8} | Qty: {g['sales_qty']:>5} | Sales: {s_amt:>8.2f} | Purch: {p_cost:>8.2f} | Profit: {profit:>8.2f}")

conn.close()

