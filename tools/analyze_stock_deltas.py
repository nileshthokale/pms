import sys
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT))
from database.legacy_migration import LegacyDump, _pack, _text, _number, _date

dump_old = LegacyDump(r'C:\Users\Nilesh\Downloads\PharmaWinner202610051955.sql')
dump_new = LegacyDump(r'PharmaWinner202610201418.sql')

con_live = sqlite3.connect('data/pharmacy.db')
con_live.row_factory = sqlite3.Row
cur = con_live.cursor()

# Get legacy item map
item_map = { r['legacy_id']: r['new_id'] for r in cur.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity = 'item'").fetchall() }
print(f"Total mapped legacy items: {len(item_map)}")

def parse_dump_stock(dump):
    # key: (target_item_id, batch_str) -> dict of properties
    stock_dict = {}
    unmapped_items = set()
    total_rows = 0
    for r in dump.iter_rows('stockbalance'):
        total_rows += 1
        leg_item_id = str(r[0])
        tgt_item_id = item_map.get(leg_item_id)
        if not tgt_item_id:
            unmapped_items.add(leg_item_id)
            continue
        batch_str = _text(r[1])
        pur_qty = _number(r[6])
        sale_qty = _number(r[9])
        net_loose = pur_qty - sale_qty
        expiry = _date(r[2])
        mrp = _number(r[3])
        rate = _number(r[4])
        net_rate = _number(r[5])
        pack_size = _pack(r[7])

        key = (tgt_item_id, batch_str)
        # In case of duplicate keys in stockbalance
        if key in stock_dict:
            existing = stock_dict[key]
            existing['net_loose'] += net_loose
        else:
            stock_dict[key] = {
                'legacy_item_id': leg_item_id,
                'target_item_id': tgt_item_id,
                'batch_no': batch_str,
                'expiry': expiry,
                'mrp': mrp,
                'rate': rate,
                'net_rate': net_rate,
                'pack_size': pack_size,
                'net_loose': net_loose
            }
    return stock_dict, unmapped_items, total_rows

stock_old, unmapped_old, total_old = parse_dump_stock(dump_old)
stock_new, unmapped_new, total_new = parse_dump_stock(dump_new)

print(f"Dump 1 (Oct 05): total rows={total_old}, mapped keys={len(stock_old)}, unmapped legacy items={len(unmapped_old)}")
print(f"Dump 2 (Oct 20): total rows={total_new}, mapped keys={len(stock_new)}, unmapped legacy items={len(unmapped_new)}")

# Now compute deltas
all_keys = set(stock_old.keys()) | set(stock_new.keys())
print(f"Total union of stock keys: {len(all_keys)}")

deltas = {}
zero_deltas = 0
nonzero_deltas = 0
new_keys_count = 0
removed_keys_count = 0

for k in all_keys:
    old_val = stock_old.get(k, {}).get('net_loose', 0.0)
    new_val = stock_new.get(k, {}).get('net_loose', 0.0)
    delta = new_val - old_val
    if k not in stock_old:
        new_keys_count += 1
    elif k not in stock_new:
        removed_keys_count += 1
    
    if abs(delta) > 0.001:
        nonzero_deltas += 1
        deltas[k] = {
            'old_val': old_val,
            'new_val': new_val,
            'delta': delta,
            'meta': stock_new.get(k) or stock_old.get(k)
        }
    else:
        zero_deltas += 1

print(f"Zero delta keys (no change in legacy): {zero_deltas}")
print(f"Nonzero delta keys (changed in legacy): {nonzero_deltas}")
print(f"  New keys in Dump 2: {new_keys_count}")
print(f"  Removed keys in Dump 2: {removed_keys_count}")

# Check our two incident batches
cgt_key = None
ace_key = None
for k, v in deltas.items():
    if k[1] == 'CGT26065C':
        cgt_key = (k, v)
    if k[1] == 'AC2604005C':
        ace_key = (k, v)

print("CGT incident delta:", cgt_key)
print("ACE incident delta:", ace_key)
