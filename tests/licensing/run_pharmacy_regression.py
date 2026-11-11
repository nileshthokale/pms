"""Run existing pharmacy tests in a disposable copy of source and database.

The runner never opens the production database. First prepare a read-only file
clone at temp/license_validation/pharmacy_clone.db, then invoke this script.
"""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MODULES = [
    "test_auth", "test_financial_year", "test_backup_restore",
    "test_counter_sale_posting", "test_counter_sale_save_workflow",
    "test_counter_sale_batch_integrity", "test_purchase_posting",
    "test_supplier_payment_posting", "test_customer_receipt",
    "test_patient_history_bill_wise", "test_document_printing",
    "test_counter_sale_a6_bill", "test_sales_report", "test_phase6b_wiring",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="Use original HEAD versions of modified application files")
    parser.add_argument("--modules", nargs="+", default=MODULES)
    args = parser.parse_args()
    clone = ROOT / "temp/license_validation/pharmacy_clone.db"
    if not clone.is_file():
        raise RuntimeError("Prepare an isolated database clone before testing")
    report = ROOT / "temp/license_validation" / ("pharmacy_baseline.log" if args.baseline else "pharmacy_regression.log")
    with tempfile.TemporaryDirectory(prefix="pharmacy_licensing_regression_") as directory:
        isolated = Path(directory).resolve()
        for package in ["core", "database", "screens", "ui", "licensing", "reports", "super_admin", "license_server"]:
            shutil.copytree(ROOT / package, isolated / package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for filename in ["main.py", "version.py"] + [m + ".py" for m in args.modules]:
            shutil.copyfile(ROOT / filename, isolated / filename)
        if args.baseline:
            for filename in ["database/connection.py", "main.py", "ui/main_window.py"]:
                original = subprocess.run(["git", "show", "HEAD:" + filename], cwd=ROOT, check=True, capture_output=True)
                (isolated / filename).write_bytes(original.stdout)
        (isolated / "data").mkdir()
        shutil.copyfile(clone, isolated / "data/pharmacy.db")
        runner = isolated / "isolated_runner.py"
        runner.write_text('''import json, os, pathlib, sqlite3, sys, unittest
root=pathlib.Path(__file__).resolve().parent
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['PHARMACY_DB']=str(root/'data/pharmacy.db')
os.environ['PHARMACY_TEST_PROTECTED_DB']=str(root/'data/pharmacy.db')
os.environ['PHARMACY_TEST_SAFE_DB']=str(root/'data/pharmacy.db')
os.environ['LOCALAPPDATA']=str(root/'appdata')
def guard(event, args):
 if event == 'sqlite3.connect':
  name=str(args[0])
  if name == ':memory:':return
  if name.startswith('file:'):
   from urllib.parse import unquote
   name=unquote(name[5:].split('?')[0])
  if os.name == 'nt' and name.lstrip('/')[1:3] == ':/':name=name.lstrip('/')
  path=pathlib.Path(name).resolve()
  if not path.is_relative_to(root):raise RuntimeError('Test tried to open a database outside its isolated workspace: '+str(path))
sys.addaudithook(guard)
suite=unittest.TestSuite()
for module in json.loads(sys.argv[1]):suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
result=unittest.TextTestRunner(verbosity=1).run(suite)
print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)}))
sys.exit(0 if result.wasSuccessful() else 1)
''', encoding="utf-8")
        env = os.environ.copy()
        for name in list(env):
            if name.startswith("PHARMACY_"):
                env.pop(name)
        # tempfile-generated backup targets must also stay in the disposable workspace.
        (isolated / "tmp").mkdir()
        env.update(TEMP=str(isolated / "tmp"), TMP=str(isolated / "tmp"), PYTHONPATH=str(isolated), PYTHONIOENCODING="utf-8")
        with report.open("w", encoding="utf-8") as stream:
            result = subprocess.run([sys.executable, str(runner), json.dumps(args.modules)], cwd=isolated,
                                    env=env, stdout=stream, stderr=subprocess.STDOUT)
        print(report.read_text(encoding="utf-8")[-5000:])
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
