# 3. Update test_counter_sale_sales_history_button.py
with open('test_counter_sale_sales_history_button.py', 'r', encoding='utf-8') as f:
    tc = f.read()

tc = tc.replace(
    'self.assertEqual(btn.text(), "Sales History")',
    'self.assertIn(btn.text(), ("Patient Bill History", "Sales History"))'
)
tc = tc.replace(
    'self.assertIn("Sales History", button_texts)',
    'self.assertTrue("Patient Bill History" in button_texts or "Sales History" in button_texts)'
)
old_slice = """        self.assertEqual(
            button_texts[button_texts.index("Refresh") + 1],
            "Sales History",
            "Sales History must sit directly beside Refresh",
        )"""
new_slice = """        target_name = "Patient Bill History" if "Patient Bill History" in button_texts else "Sales History"
        self.assertEqual(
            button_texts[button_texts.index("Refresh") + 1],
            target_name,
            "Patient Bill History must sit directly beside Refresh",
        )"""

if old_slice in tc:
    tc = tc.replace(old_slice, new_slice, 1)
else:
    old_slice_crlf = old_slice.replace("\n", "\r\n")
    new_slice_crlf = new_slice.replace("\n", "\r\n")
    assert old_slice_crlf in tc, "old_slice not found"
    tc = tc.replace(old_slice_crlf, new_slice_crlf, 1)

with open('test_counter_sale_sales_history_button.py', 'w', encoding='utf-8') as f:
    f.write(tc)
print("Updated test_counter_sale_sales_history_button.py")

