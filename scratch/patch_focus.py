with open('scratch/build_classes.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace(
    'self.btn_item_edit.setToolTip("Edit selected item master")',
    'self.btn_item_edit.setToolTip("Edit selected item master")\n        self.btn_item_edit.setFocusPolicy(Qt.NoFocus)'
)
c = c.replace(
    'self.btn_item_hist.setToolTip("View item purchase history")',
    'self.btn_item_hist.setToolTip("View item purchase history")\n        self.btn_item_hist.setFocusPolicy(Qt.NoFocus)'
)
c = c.replace(
    'self.btn_supplier_edit.setToolTip("Edit selected supplier master")',
    'self.btn_supplier_edit.setToolTip("Edit selected supplier master")\n        self.btn_supplier_edit.setFocusPolicy(Qt.NoFocus)'
)

with open('scratch/build_classes.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('Updated build_classes.py with NoFocus')
