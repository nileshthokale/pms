"""Read-only: which BIO items still have sellable (non-expired) stock?"""
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "pharmacy.db"

from database.sales_dao import SalesDAO  # noqa: E402

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

items = [dict(r) for r in con.execute(
    "SELECT id, item_name FROM items WHERE UPPER(item_name) LIKE '%BIO%' "
    "ORDER BY item_name")]
print(f"{len(items)} items match BIO\n")
for it in items:
    batches = SalesDAO.get_stock_batches_for_item(it["id"])
    sellable = [b for b in batches
                if not SalesDAO.is_expired(b["expiry"] or "")]
    marker = "SELLABLE" if sellable else "expired-only"
    first = batches[0] if batches else None
    print(f"  {it['id']:>6} {it['item_name']:<22} batches={len(batches):>2} "
          f"sellable={len(sellable):>2}  {marker:<14} "
          f"first={first['batch_no'] if first else '-'} "
          f"exp={first['expiry'] if first else '-'}")
con.close()
