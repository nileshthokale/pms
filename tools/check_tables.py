import sqlite3

con = sqlite3.connect('staging/pharmacy_staging_refresh.db')
tables = [t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)

for t in tables:
    if 'purchase' in t or 'sale' in t:
        count = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {count} rows")
