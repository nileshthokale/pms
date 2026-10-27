with open('scratch/build_classes.py', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Bar height: set to 44
c = c.replace('self.setFixedHeight(50)', 'self.setFixedHeight(44)')

# 2. Supplier balance: separate prefix and suffix labels
old_bal = '''        self.supplier_bal_label = QLabel("(Balance=0)")
        self.supplier_bal_label.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent; padding: 2px;")
        sup_row.addWidget(self.supplier_bal_label)'''

new_bal = '''        self.sup_bal_prefix = QLabel("(Balance=")
        self.sup_bal_prefix.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.sup_bal_prefix)

        self.supplier_bal_label = QLabel("0.00")
        self.supplier_bal_label.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.supplier_bal_label)

        self.sup_bal_suffix = QLabel(")")
        self.sup_bal_suffix.setStyleSheet("color: #111827; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.sup_bal_suffix)'''

c = c.replace(old_bal, new_bal)

# 3. Update _update_supplier_balance
old_upd = '''            if abs(closing) < 1e-9:
                self.supplier_bal_label.setText("(Balance=0)")
            else:
                sign = 1.0 if closing_type == "Credit" else -1.0
                outstanding = closing * sign
                self.supplier_bal_label.setText(f"(Balance={outstanding:,.2f})")'''

new_upd = '''            if abs(closing) < 1e-9:
                self.supplier_bal_label.setText("0.00")
            else:
                sign = 1.0 if closing_type == "Credit" else -1.0
                outstanding = closing * sign
                self.supplier_bal_label.setText(f"{outstanding:,.2f}")'''

c = c.replace(old_upd, new_upd)

# And clear to 0.00
c = c.replace('self.supplier_bal_label.setText("(Balance=0)")', 'self.supplier_bal_label.setText("0.00")')

with open('scratch/build_classes.py', 'w', encoding='utf-8') as f:
    f.write(c)

print('Updated build_classes.py successfully')
