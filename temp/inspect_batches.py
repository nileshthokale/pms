"""Read-only inspection of the production DB batches for the acceptance item."""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "pharmacy.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print("batches for item 10501 (as returned by the DAO sort):")
import sys
sys.path.insert(0, str(DB.parent.parent))
from database.sales_dao import SalesDAO  # noqa: E402

for b in SalesDAO.get_stock_batches_for_item(10501):
    print("   ", b["id"], b["batch_no"], b["expiry"], b["stock_qty"],
          "expired=", SalesDAO.is_expired(b["expiry"]))

print("\nitems matching BIO (first 12):")
for r in con.execute(
        "SELECT id, item_name FROM items WHERE UPPER(item_name) LIKE '%BIO%' "
        "ORDER BY item_name LIMIT 12"):
    print("   ", dict(r))

print("\nexpired-stock batch counts (all items):")
row = con.execute(
    "SELECT COUNT(*) FROM stock_batches WHERE stock_qty > 0").fetchone()
print("    batches with stock:", row[0])
con.close()
