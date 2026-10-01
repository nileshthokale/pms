"""Read-only inspection of the newest production rows (no writes)."""
import sqlite3
from pathlib import Path

DB = Path("data/pharmacy.db")
con = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print("=== latest sales_invoices ===")
for row in con.execute("SELECT * FROM sales_invoices ORDER BY id DESC LIMIT 3"):
    print(dict(row))

latest = con.execute("SELECT MAX(id) FROM sales_invoices").fetchone()[0]
print(f"=== items of invoice {latest} ===")
for row in con.execute(
        "SELECT * FROM sales_invoice_items WHERE sales_invoice_id=?", (latest,)):
    print(dict(row))

print("=== latest ledger_transactions ===")
for row in con.execute("SELECT * FROM ledger_transactions ORDER BY id DESC LIMIT 4"):
    print(dict(row))

print("=== latest auth_audit_log ===")
for row in con.execute("SELECT * FROM auth_audit_log ORDER BY id DESC LIMIT 3"):
    print(dict(row))

con.close()
