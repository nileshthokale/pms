import sqlite3
con_live = sqlite3.connect('data/pharmacy.db')
con_stag = sqlite3.connect('staging/pharmacy_staging_refresh.db')

print('Live CGT26065C:', con_live.execute("SELECT id, item_id, batch_no, stock_qty FROM stock_batches WHERE batch_no = 'CGT26065C'").fetchall())
print('Staging CGT26065C:', con_stag.execute("SELECT id, item_id, batch_no, stock_qty FROM stock_batches WHERE batch_no = 'CGT26065C'").fetchall())
print('Live AC2604005C:', con_live.execute("SELECT id, item_id, batch_no, stock_qty FROM stock_batches WHERE batch_no = 'AC2604005C'").fetchall())
print('Staging AC2604005C:', con_stag.execute("SELECT id, item_id, batch_no, stock_qty FROM stock_batches WHERE batch_no = 'AC2604005C'").fetchall())
