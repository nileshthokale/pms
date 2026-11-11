import sys

path = 'screens/counter_sale.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

target = """        if self._popup_mode:
            # Discount / Paid Amount live in the popup's top strip, so the
            # summary row keeps only the calculated values.  The same
            # widgets are created there - nothing is duplicated.
            self._add_total_field(layout, "Total Amt", "total_amount_label",
                                  width=96)
            self._add_total_field(layout, "Customer Saving", "customer_saving_label",
                                  width=110)
            self._add_total_field(layout, "Yours", "yours_label",
                                  width=90)
            self._add_total_field(layout, "Round Off", "round_off_label",
                                  width=92)
            self._add_total_field(layout, "NET AMT", "net_amt_label",
                                  width=112, emphasised=True)
            layout.addStretch()
            return

        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._add_total_field(layout, "Total Items", "total_items_label",
                              width=76, emphasised=False)
        self._add_total_field(layout, "Total Amt", "total_amount_label",
                              width=100, visible=False)
        self._add_total_field(layout, "Bill Disc", "bill_disc_edit",
                              width=90, visible=False)
        self._add_total_field(layout, "Customer Saving", "customer_saving_label",
                              width=110)
        self._add_total_field(layout, "Yours", "yours_label",
                              width=90)
        self._add_total_field(layout, "Round Off", "round_off_label",
                              width=85)
        self._add_total_field(layout, "NET AMT", "net_amt_label",
                              width=115, emphasised=True)
        self._add_total_field(layout, "Paid", "paid_edit", width=95, visible=False)"""

replacement = """        if self._popup_mode:
            # Discount / Paid Amount live in the popup's top strip, so the
            # summary row keeps only the calculated values.  The same
            # widgets are created there - nothing is duplicated.
            self._add_total_field(layout, "Total Amt", "total_amount_label",
                                  width=125)
            self._add_total_field(layout, "Customer Saving", "customer_saving_label",
                                  width=180)
            self._add_total_field(layout, "Yours", "yours_label",
                                  width=100)
            self._add_total_field(layout, "Round Off", "round_off_label",
                                  width=110)
            self._add_total_field(layout, "NET AMT", "net_amt_label",
                                  width=145, emphasised=True)
            layout.addStretch()
            return

        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(16)

        self._add_total_field(layout, "Total Items", "total_items_label",
                              width=120, emphasised=False)
        self._add_total_field(layout, "Total Amt", "total_amount_label",
                              width=125, visible=False)
        self._add_total_field(layout, "Bill Disc", "bill_disc_edit",
                              width=100, visible=False)
        self._add_total_field(layout, "Customer Saving", "customer_saving_label",
                              width=180)
        self._add_total_field(layout, "Yours", "yours_label",
                              width=100)
        self._add_total_field(layout, "Round Off", "round_off_label",
                              width=110)
        self._add_total_field(layout, "NET AMT", "net_amt_label",
                              width=145, emphasised=True)
        self._add_total_field(layout, "Paid", "paid_edit", width=100, visible=False)"""

if target not in content:
    print("Error: target not found")
    sys.exit(1)

content = content.replace(target, replacement, 1)

target_shortcuts = '''        shortcuts_text = (
            "Pur. Invoice: [Ctrl+I]   Challan: [Ctrl+H]   Adjust: [Ctrl+A]   "
            "DebitNote : [Ctrl+D]   CreditNote : [Ctrl+C]   Supp. Payment: [Ctrl+P]   "
            "Cust. Receipt: [Ctrl+R]   Counter Sales: [Ctrl+S]"
        )'''

replacement_shortcuts = '''        shortcuts_text = (
            "Pur. Invoice: [Ctrl+I]   •   Challan: [Ctrl+H]   •   Adjust: [Ctrl+A]   •   "
            "DebitNote: [Ctrl+D]   •   CreditNote: [Ctrl+C]   •   Supp. Payment: [Ctrl+P]   •   "
            "Cust. Receipt: [Ctrl+R]   •   Counter Sales: [Ctrl+S]"
        )'''

if target_shortcuts not in content:
    print("Error: target_shortcuts not found")
    sys.exit(1)

content = content.replace(target_shortcuts, replacement_shortcuts, 1)

with open(path, 'w', encoding='utf-8', newline='\r\n') as f:
    f.write(content)

print("Successfully updated!")
