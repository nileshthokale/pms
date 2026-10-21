import sqlite3
import sys
sys.path.insert(0, '.')
from database.legacy_migration import LegacyDump

con_live = sqlite3.connect('data/pharmacy.db')
con_live.row_factory = sqlite3.Row
cur_live = con_live.cursor()

print("=== Live Database: Batch CGT26065C ===")
cur_live.execute("SELECT sb.*, it.item_name FROM stock_batches sb JOIN items it ON sb.item_id = it.id WHERE sb.batch_no = 'CGT26065C'")
for r in cur_live.fetchall():
    print("  stock_batches:", dict(r))

print("\n=== Live Database: Items 944 and 1796 ===")
cur_live.execute("SELECT * FROM items WHERE id IN (944, 1796)")
for r in cur_live.fetchall():
    print("  items:", dict(r))

print("\n=== Live Database: Purchase Invoice Items for Batch CGT26065C ===")
cur_live.execute("""
    SELECT pii.*, p.invoice_no, p.invoice_date, it.item_name
    FROM purchase_invoice_items pii
    JOIN purchase_invoices p ON pii.purchase_invoice_id = p.id
    JOIN items it ON pii.item_id = it.id
    WHERE pii.batch_no = 'CGT26065C'
""")
for r in cur_live.fetchall():
    print("  purchase_invoice_items:", dict(r))

print("\n=== Live Database: Native Purchase Invoice 5714 detail items ===")
cur_live.execute("""
    SELECT pii.*, it.item_name
    FROM purchase_invoice_items pii
    JOIN items it ON pii.item_id = it.id
    WHERE pii.purchase_invoice_id = 5714
""")
for r in cur_live.fetchall():
    print("  purchase_invoice_items (inv 5714):", dict(r))

print("\n=== Legacy ID Map for Items 944 and 1796 ===")
cur_live.execute("SELECT * FROM legacy_id_map WHERE entity = 'item' AND (new_id IN (944, 1796) OR legacy_id IN ('944', '853'))")
for r in cur_live.fetchall():
    print("  legacy_id_map:", dict(r))

print("\n=== Source SQL Dump: Batch CGT26065C in stockbalance ===")
dump_new = LegacyDump('PharmaWinner202610201418.sql')
for r in dump_new.iter_rows('stockbalance'):
    if 'CGT26065C' in str(r[1]):
        print("  stockbalance dump 2:", r)

dump_old = LegacyDump('PharmaWinner202610051955.sql')
for r in dump_old.iter_rows('stockbalance'):
    if 'CGT26065C' in str(r[1]):
        print("  stockbalance dump 1:", r)
