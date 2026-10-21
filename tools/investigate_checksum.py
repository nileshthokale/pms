import sqlite3
import hashlib
import os

db_path = 'data/pharmacy.db'
h = hashlib.sha256()
with open(db_path, 'rb') as f:
    while chunk := f.read(65536):
        h.update(chunk)
current_sha = h.hexdigest().upper()
print('Current SHA256:', current_sha)
print('File size:', os.path.getsize(db_path))

con = sqlite3.connect(db_path)
cur = con.cursor()

# Check auth_audit_log
cur.execute('SELECT * FROM auth_audit_log ORDER BY id DESC LIMIT 5')
print('Latest auth_audit_log entries:')
for r in cur.fetchall():
    print(' ', r)

# Compare with baseline backup if any exists
# Check phase1_stage_baseline.json or other baseline files
if os.path.exists('migration_backups/phase1_stage_baseline.json'):
    with open('migration_backups/phase1_stage_baseline.json') as f:
        print('phase1_stage_baseline.json content:\n', f.read())

# Check baseline clone staging/pharmacy_staging_baseline.db or similar
for fname in os.listdir('staging') if os.path.exists('staging') else []:
    print('staging file:', fname)

# Let's inspect the exact difference between the baseline db and current data/pharmacy.db
