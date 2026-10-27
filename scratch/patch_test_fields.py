with open('test_purchase_item_fields.py', 'r', encoding='utf-8') as f:
    c = f.read()

old_labels = 'expected_labels = ["Item", "Pack", "Batch", "Exp", "Qty", "Free", "Rate", "MRP", "Disc", "GST"]'
new_labels = 'expected_labels = ["* Item Name", "PackSize", "Pay Qty", "Free Qty", "Batch #", "Expiry", "Rate", "MRP", "Disc", "GST-Tax"]'
c = c.replace(old_labels, new_labels)

c = c.replace('table_exp = dlg._table.item(0, 6).text()', 'table_exp = dlg._table.item(0, 5).text()')
c = c.replace('self.assertEqual(dlg._table.item(0, 6).text(), "31-12-2029")', 'self.assertEqual(dlg._table.item(0, 5).text(), "31-12-2029")')

with open('test_purchase_item_fields.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('Updated test_purchase_item_fields.py')
