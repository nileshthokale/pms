"""Check if old Pharma-WINNER/MySQL system exists."""
import os

# Check for any MySQL configs, old system files
project_root = r"C:\Users\Nilesh\OneDrive\Desktop\Pharmacy Management System"

# Check for any .sql dumps
for f in os.listdir(project_root):
    if f.endswith('.sql') or 'pharma' in f.lower() or 'winner' in f.lower():
        print(f"Found: {f}")

# Check if there are any config files pointing to MySQL
for root, dirs, files in os.walk(project_root):
    for fname in files:
        if fname.endswith('.py') or fname.endswith('.json') or fname.endswith('.cfg'):
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', errors='ignore') as fh:
                    content = fh.read(2000)
                    if 'mysql' in content.lower() or 'pymysql' in content.lower() or 'pharma winner' in content.lower():
                        print(f"Found MySQL reference in: {fpath}")
            except:
                pass

print("Check complete.")
