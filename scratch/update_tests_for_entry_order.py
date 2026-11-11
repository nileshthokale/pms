# Update tests to reflect new order: Item, Pack, Qty, Free, Batch, Exp, Rate, MRP, Disc, GST, Add

with open('test_purchase_single_row_layout.py', 'r', encoding='utf-8') as f:
    t = f.read()

old_labels = 'expected_labels = ["Item", "Pack", "Batch", "Exp", "Qty", "Free", "Rate", "MRP", "Disc", "GST"]'
new_labels = 'expected_labels = ["Item", "Pack", "Qty", "Free", "Batch", "Exp", "Rate", "MRP", "Disc", "GST"]'
assert old_labels in t, "old_labels not found in test_purchase_single_row_layout.py"
t = t.replace(old_labels, new_labels)

old_geoms = """                geoms = [
                    ("Item", bar.item_combo.parentWidget().geometry()),
                    ("Pack", bar.pack_edit.parentWidget().geometry()),
                    ("Batch", bar.batch_edit.parentWidget().geometry()),
                    ("Exp", bar.expiry_edit.parentWidget().geometry()),
                    ("Qty", bar.pay_qty_edit.parentWidget().geometry()),
                    ("Free", bar.free_qty_edit.parentWidget().geometry()),
                    ("Rate", bar.rate_edit.parentWidget().geometry()),
                    ("MRP", bar.mrp_edit.parentWidget().geometry()),
                    ("Disc", bar.discount_edit.parentWidget().geometry()),
                    ("GST", bar.gst_edit.parentWidget().geometry()),
                    ("Add", bar.add_btn.geometry()),
                ]"""

new_geoms = """                geoms = [
                    ("Item", bar.item_combo.parentWidget().geometry()),
                    ("Pack", bar.pack_edit.parentWidget().geometry()),
                    ("Qty", bar.pay_qty_edit.parentWidget().geometry()),
                    ("Free", bar.free_qty_edit.parentWidget().geometry()),
                    ("Batch", bar.batch_edit.parentWidget().geometry()),
                    ("Exp", bar.expiry_edit.parentWidget().geometry()),
                    ("Rate", bar.rate_edit.parentWidget().geometry()),
                    ("MRP", bar.mrp_edit.parentWidget().geometry()),
                    ("Disc", bar.discount_edit.parentWidget().geometry()),
                    ("GST", bar.gst_edit.parentWidget().geometry()),
                    ("Add", bar.add_btn.geometry()),
                ]"""

t = t.replace(old_geoms.replace("\n", "\r\n"), new_geoms.replace("\n", "\r\n"))
if old_geoms in t:
    t = t.replace(old_geoms, new_geoms)

old_focus = """        expected_focus_order = [
            bar.batch_edit,
            bar.expiry_edit._line,
            bar.pay_qty_edit,
            bar.free_qty_edit,
            bar.rate_edit,
            bar.mrp_edit,
            bar.discount_edit,
            bar.add_btn,
        ]"""

new_focus = """        expected_focus_order = [
            bar.pay_qty_edit,
            bar.free_qty_edit,
            bar.batch_edit,
            bar.expiry_edit._line,
            bar.rate_edit,
            bar.mrp_edit,
            bar.discount_edit,
            bar.add_btn,
        ]"""

t = t.replace(old_focus.replace("\n", "\r\n"), new_focus.replace("\n", "\r\n"))
if old_focus in t:
    t = t.replace(old_focus, new_focus)

with open('test_purchase_single_row_layout.py', 'w', encoding='utf-8', newline='') as f:
    f.write(t)

print("test_purchase_single_row_layout.py updated successfully!")

with open('test_purchase_item_fields.py', 'r', encoding='utf-8') as f:
    t2 = f.read()

old_fields_doc = """        Item -> Pack -> Batch -> Exp -> Qty -> Free -> Rate -> MRP -> Disc -> GST -> + Add Item
        \"\"\"
        labels = [lbl.text() for lbl in self.bar._entry_labels]
        expected_labels = [
            "Item", "Pack", "Batch", "Exp",
            "Qty", "Free", "Rate", "MRP", "Disc", "GST"
        ]"""

new_fields_doc = """        Item -> Pack -> Qty -> Free -> Batch -> Exp -> Rate -> MRP -> Disc -> GST -> + Add Item
        \"\"\"
        labels = [lbl.text() for lbl in self.bar._entry_labels]
        expected_labels = [
            "Item", "Pack", "Qty", "Free",
            "Batch", "Exp", "Rate", "MRP", "Disc", "GST"
        ]"""

t2 = t2.replace(old_fields_doc.replace("\n", "\r\n"), new_fields_doc.replace("\n", "\r\n"))
if old_fields_doc in t2:
    t2 = t2.replace(old_fields_doc, new_fields_doc)

with open('test_purchase_item_fields.py', 'w', encoding='utf-8', newline='') as f:
    f.write(t2)

print("test_purchase_item_fields.py updated successfully!")
