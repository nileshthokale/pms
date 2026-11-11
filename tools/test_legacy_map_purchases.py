import sqlite3
import sys
sys.path.insert(0, '.')
from database.legacy_migration import LegacyDump

dump = LegacyDump('PharmaWinner202610201418.sql')
dump_items = {}
for r in dump.iter_rows('invoiceitemdetail'):
    hdr = int(r[1])
    if hdr >= 5718:
        det = int(r[0])
        item = int(r[2])
        batch = str(r[3]).strip("'\"")
        tax = r[8]
        dump_items[(hdr, item, batch)] = (det, tax)

con = sqlite3.connect('staging/pharmacy_staging_refresh.db')
con.row_factory = sqlite3.Row
cur = con.cursor()

# Get legacy maps
inv_map = { r['new_id']: int(r['legacy_id']) for r in cur.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity = 'purchase'").fetchall() }
item_map = { r['new_id']: int(r['legacy_id']) for r in cur.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity = 'item'").fetchall() }

cur.execute('''
    SELECT pi.id, pi.purchase_invoice_id, pi.item_id, pi.batch_no
    FROM purchase_invoice_items pi
    WHERE pi.id > 11892
    ORDER BY pi.id
''')
matched = 0
for r in cur.fetchall():
    leg_hdr = inv_map.get(r['purchase_invoice_id'])
    leg_item = item_map.get(r['item_id'])
    det_tax = dump_items.get((leg_hdr, leg_item, r['batch_no']))
    if det_tax:
        matched += 1
    print(f"Target ID: {r['id']}, LegHdr: {leg_hdr}, LegItem: {leg_item}, Batch: {r['batch_no']}, DetTax: {det_tax}")

print(f"Matched {matched} of 22")
