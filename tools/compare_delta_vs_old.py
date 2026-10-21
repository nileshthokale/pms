import sys
sys.path.insert(0, '.')
import sqlite3
from tools.analyze_stock_deltas import deltas, stock_new, stock_old

con_live = sqlite3.connect('data/pharmacy.db')
con_stag = sqlite3.connect('staging/pharmacy_staging_refresh.db')

live_batches = { (r[1], r[2]): r[7] for r in con_live.execute("SELECT id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty FROM stock_batches").fetchall() }
stag_batches = { (r[1], r[2]): r[7] for r in con_stag.execute("SELECT id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty FROM stock_batches").fetchall() }

# Batches that were updated in staging
updated_in_staging = set()
for k, s_qty in stag_batches.items():
    if k in live_batches:
        l_qty = live_batches[k]
        if abs(s_qty - l_qty) > 0.001:
            updated_in_staging.add(k)
    else:
        updated_in_staging.add(k)

print(f"Total batches modified in old refresh staging: {len(updated_in_staging)}")
print(f"Total keys with non-zero delta between dumps: {len(deltas)}")

delta_keys = set(deltas.keys())
in_staging_not_delta = updated_in_staging - delta_keys
in_delta_not_staging = delta_keys - updated_in_staging

print(f"Modified in old staging but zero delta between dumps: {len(in_staging_not_delta)}")
for k in in_staging_not_delta:
    print(f"  {k}: live={live_batches.get(k)}, stag={stag_batches.get(k)}, dump1={stock_old.get(k,{}).get('net_loose')}, dump2={stock_new.get(k,{}).get('net_loose')}")

print(f"In delta but not in updated_in_staging: {len(in_delta_not_staging)}")
for k in in_delta_not_staging:
    print(f"  {k}: delta={deltas[k]['delta']}")
