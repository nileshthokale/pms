"""Read-only: BIO items with a sellable batch holding at least 2 units."""
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
for it in items:
    batches = SalesDAO.get_stock_batches_for_item(it["id"])
    good = [b for b in batches
            if not SalesDAO.is_expired(b["expiry"] or "")
            and float(b["stock_qty"]) >= 2]
    print(f"  {it['id']:>6} {it['item_name']:<22} good={len(good)}  "
          + ", ".join(f"{b['batch_no']} exp={b['expiry']} qty={b['stock_qty']:.0f}"
                      for b in batches))
con.close()
