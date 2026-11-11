import sqlite3

con_stag = sqlite3.connect('staging/pharmacy_staging_refresh.db')
con_stag.row_factory = sqlite3.Row
cur = con_stag.cursor()

# Suppliers
cur.execute('''
    SELECT s.id, s.supplier_name, s.opening_balance, al.id as ledger_id,
           COALESCE(SUM(lt.debit), 0.0) as total_debit,
           COALESCE(SUM(lt.credit), 0.0) as total_credit,
           (COALESCE(SUM(lt.credit), 0.0) - COALESCE(SUM(lt.debit), 0.0)) as ledger_balance
    FROM suppliers s
    JOIN account_ledgers al ON s.ledger_id = al.id
    LEFT JOIN ledger_transactions lt ON lt.ledger_id = al.id
    GROUP BY s.id
    HAVING ledger_balance != 0 OR total_debit != 0 OR total_credit != 0
    ORDER BY abs(ledger_balance) DESC
''')
suppliers_with_activity = [dict(r) for r in cur.fetchall()]
print(f"Suppliers with ledger activity: {len(suppliers_with_activity)}")
for s in suppliers_with_activity[:5]:
    print(s)

# Customers
cur.execute('''
    SELECT c.id, c.customer_name, c.opening_balance, al.id as ledger_id,
           COALESCE(SUM(lt.debit), 0.0) as total_debit,
           COALESCE(SUM(lt.credit), 0.0) as total_credit,
           (COALESCE(SUM(lt.debit), 0.0) - COALESCE(SUM(lt.credit), 0.0)) as ledger_balance
    FROM customers c
    JOIN account_ledgers al ON c.ledger_id = al.id
    LEFT JOIN ledger_transactions lt ON lt.ledger_id = al.id
    GROUP BY c.id
    HAVING ledger_balance != 0 OR total_debit != 0 OR total_credit != 0
    ORDER BY abs(ledger_balance) DESC
''')
customers_with_activity = [dict(r) for r in cur.fetchall()]
print(f"Customers with ledger activity: {len(customers_with_activity)}")
for c in customers_with_activity[:5]:
    print(c)
