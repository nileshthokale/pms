with open('test_purchase_invoice_pp_and_item_deletion.py', 'r', encoding='utf-8') as f:
    c = f.read()

# Replace col 15 with col 14 for PP
c = c.replace('pp_cell = dlg._table.item(row_idx, 15)', 'pp_cell = dlg._table.item(row_idx, 14)')
c = c.replace('self.assertNotEqual(dlg._table.item(0, 15).text(), "532.79")', 'self.assertNotEqual(dlg._table.item(0, 14).text(), "532.79")')
c = c.replace('self.assertNotEqual(dlg._table.item(1, 15).text(), "922.53")', 'self.assertNotEqual(dlg._table.item(1, 14).text(), "922.53")')
c = c.replace('self.assertNotEqual(dlg._table.item(2, 15).text(), "763.46")', 'self.assertNotEqual(dlg._table.item(2, 14).text(), "763.46")')
c = c.replace('self.assertNotEqual(dlg._table.item(3, 15).text(), "4416.09")', 'self.assertNotEqual(dlg._table.item(3, 14).text(), "4416.09")')

c = c.replace('self.assertEqual(dlg._table.item(0, 13).text(), "177.60")  # Pur Rate', 'self.assertEqual(dlg._table.item(0, 12).text(), "177.60")  # Pur Rate')
c = c.replace('self.assertEqual(dlg._table.item(0, 14).text(), "177.60")  # Net Rate', 'self.assertEqual(dlg._table.item(0, 13).text(), "177.60")  # Net Rate')
c = c.replace('self.assertEqual(dlg._table.item(2, 13).text(), "76.35")   # MAC RD Pur Rate', 'self.assertEqual(dlg._table.item(2, 12).text(), "76.35")   # MAC RD Pur Rate')
c = c.replace('self.assertEqual(dlg._table.item(2, 14).text(), "69.41")   # MAC RD Net Rate (with 1 free pack)', 'self.assertEqual(dlg._table.item(2, 13).text(), "69.41")   # MAC RD Net Rate (with 1 free pack)')

c = c.replace('self.assertEqual(dlg._table.item(0, 15).text(), "25")', 'self.assertEqual(dlg._table.item(0, 14).text(), "25")')
c = c.replace('self.assertEqual(dlg._table.item(1, 15).text(), "25")', 'self.assertEqual(dlg._table.item(1, 14).text(), "25")')

# ItemName is col 0, BatchNo is col 4
c = c.replace('self.assertEqual(dlg._table.item(0, 1).text(), "UBINEXT-LC TABLET")', 'self.assertEqual(dlg._table.item(0, 0).text(), "UBINEXT-LC TABLET")')
c = c.replace('self.assertEqual(dlg._table.item(0, 5).text(), "BATCH-01")', 'self.assertEqual(dlg._table.item(0, 4).text(), "BATCH-01")')
c = c.replace('self.assertEqual(dlg._table.item(1, 1).text(), "MAC RD CAPSULE")', 'self.assertEqual(dlg._table.item(1, 0).text(), "MAC RD CAPSULE")')
c = c.replace('self.assertEqual(dlg._table.item(1, 5).text(), "BATCH-03")', 'self.assertEqual(dlg._table.item(1, 4).text(), "BATCH-03")')

with open('test_purchase_invoice_pp_and_item_deletion.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('Updated test_purchase_invoice_pp_and_item_deletion.py')
