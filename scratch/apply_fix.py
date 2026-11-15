import shutil
import sqlite3
from pathlib import Path
import sys

ROOT = Path(r"c:\Users\savan\OneDrive\Desktop\pms")
sys.path.insert(0, str(ROOT))

from tools.fix_item_master_unit_mapping import fix_mapping

db_path = ROOT / "data" / "pharmacy.db"
backup_path = ROOT / "data" / "pharmacy_backup_before_unit_unmerge.db"

# Backup
shutil.copy2(db_path, backup_path)
print(f"Backed up {db_path} to {backup_path}")

# Run fix
res = fix_mapping(db_path)
print("fix_mapping executed successfully:", res)

# Verify
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT i.id, i.item_name, u.unit_name, i.pack_size, lim.legacy_id
    FROM items i
    LEFT JOIN units u ON i.unit_id = u.id
    LEFT JOIN legacy_id_map lim ON lim.entity = 'item' AND lim.new_id = i.id
    WHERE i.item_name IN ('POWERGESIC', 'VITOMIN-Z', 'CALTONVIT')
    ORDER BY i.item_name, i.id
""").fetchall()

print("\n--- Verified unmerged items in pharmacy.db ---")
for r in rows:
    print(dict(r))

conn.close()
