import sqlite3

con = sqlite3.connect('data/pharmacy.db')
con.row_factory = sqlite3.Row
cur = con.cursor()

tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"Total tables in data/pharmacy.db: {len(tables)}")

for t in sorted(tables):
    if t == 'sqlite_sequence':
        continue
    cnt = cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    # check max id if id column exists
    cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
    max_id = None
    if 'id' in cols:
        max_id = cur.execute(f"SELECT max(id) FROM {t}").fetchone()[0]
    print(f"  {t:30s}: count={cnt:6d}, max_id={max_id}")

print("\nsqlite_sequence:")
for r in cur.execute("SELECT * FROM sqlite_sequence").fetchall():
    print(f"  {r['name']}: {r['seq']}")
