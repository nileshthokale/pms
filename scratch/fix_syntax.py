with open('screens/purchase_report.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if skip:
        skip = False
        continue
    if 'QMessageBox.critical(self, "Error", f"Failed to load invoice:' in line:
        new_lines.append('            QMessageBox.critical(self, "Error", f"Failed to load invoice: {exc}")\n')
        skip = True
    else:
        new_lines.append(line)

with open('screens/purchase_report.py', 'w', encoding='utf-8', newline='') as f:
    f.writelines(new_lines)
print("Fixed lines!")
