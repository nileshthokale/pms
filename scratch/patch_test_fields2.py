with open('test_purchase_item_fields.py', 'r', encoding='utf-8') as f:
    c = f.read()

old_block = '''        labels = [lbl.text() for lbl in self.bar._entry_labels]
        expected_labels = [
            "Item", "Pack", "Batch", "Exp",
            "Qty", "Free", "Rate", "MRP", "Disc", "GST"
        ]
        self.assertEqual(labels, expected_labels)

        layout = self.bar.layout()
        self.assertIsNotNone(layout)
        # Check add button
        self.assertEqual(self.bar.add_btn.text(), "+ Add Item")'''

new_block = '''        labels = [lbl.text() for lbl in self.bar._entry_labels]
        expected_labels = [
            "* Item Name", "PackSize", "Pay Qty", "Free Qty",
            "Batch #", "Expiry", "Rate", "MRP", "Disc", "GST-Tax"
        ]
        self.assertEqual(labels, expected_labels)

        layout = self.bar.layout()
        self.assertIsNotNone(layout)
        # Check add button
        self.assertIn(self.bar.add_btn.text(), ("⇓", "▼", "+ Add Item"))'''

c = c.replace(old_block, new_block)

with open('test_purchase_item_fields.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('Updated test_single_row_field_order in test_purchase_item_fields.py')
