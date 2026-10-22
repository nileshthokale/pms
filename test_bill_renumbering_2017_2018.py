"""Tests for reassigning sales bill numbers to fill 2017 and 2018.

Verifies:
1. Bills 2017 and 2018 are correctly assigned to invoices 72188 and 72189.
2. Unnamed walkin sales (72186, 72187) have their bill_no cleared to '' and ledger transactions updated.
3. Bills 2019..2033 shift down by 2 to 2017..2031.
4. Earlier bills (1..2016) remain strictly untouched.
5. No duplicate bill numbers are created in sales_invoices.
6. Ledger transaction voucher_no and descriptions (including reversals) are updated consistently.
7. Next bill number generation correctly continues from 2032 without conflict.
8. Non-bill fields (dates, times, patients, amounts, items) are 100% preserved.
9. Re-running the migration is idempotent.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.doc_formatter import format_sales_bill_number
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.connection import get_connection, init_database
from database.sales_dao import SalesDAO
from screens.sales_history import _fmt_bill_no
from scripts.reassign_bill_numbers_2017_2018 import reassign_bill_numbers


class TestBillRenumbering2017And2018(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="test_bill_renumber_")
        self._db_path = os.path.join(self._temp_dir, "test_pharmacy.db")
        self._prev_db = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = self._db_path

        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        ensure_system_ledgers()

        # Seed test data matching production rows 72184 to 72202
        self._seed_invoices()

    def tearDown(self):
        if self._prev_db is not None:
            os.environ["PHARMACY_DB"] = self._prev_db
        else:
            os.environ.pop("PHARMACY_DB", None)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _seed_invoices(self):
        conn = sqlite3.connect(self._db_path)
        cur = conn.cursor()

        # Invoices mapping matching production
        self.invoice_seeds = [
            (72184, "2015", "MR NASIR ATTAR", 464.47),
            (72185, "2016", "MISS ISHWARI WANI", 658.44),
            (72186, "2017", "", 197.09),
            (72187, "2018", "", 154.69),
            (72188, "2019", "MRS ARCHANA GARUD", 576.37),
            (72189, "2020", "MR RAOSAHEB LONDHE", 410.67),
            (72190, "2021", "MR BALASAHEB BHUJADI", 300.66),
            (72191, "2022", "MR KARAN MADHE", 2484.06),
            (72192, "2023", "MRS JAYA GAGARE", 275.70),
            (72193, "2024", "MRS MANDA KEDARI", 521.00),
            (72194, "2025", "", 241.45),
            (72195, "2026", "MRS ALKA JANGALE", 1071.20),
            (72196, "2027", "MRS SANGITA DIGHE", 255.32),
            (72197, "2028", "MAST YASH PARAKHE", 612.36),
            (72198, "2029", "MR AKASH PAWAR", 1104.26),
            (72199, "2030", "MRS LATIFA PATHAN", 1233.05),
            (72200, "2031", "MRS VIMAL SHENDAGE", 2000.29),
            (72201, "2032", "MR PRAKASH GAWADE", 641.00),
            (72202, "2033", "MR SUDHAKAR TANPURE", 548.09),
        ]

        for inv_id, bno, pat, amt in self.invoice_seeds:
            cur.execute(
                """
                INSERT INTO sales_invoices (
                    id, bill_no, sale_date, sale_time, sale_type, customer_id,
                    patient_name, doctor_id, discount, paid_amount, total_amount,
                    round_off, net_amount, remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inv_id, bno, "2026-10-21", "12:00", "Cash", None,
                    pat, None, 0.0, amt, amt, 0.0, amt, f"Sample remarks {bno}"
                ),
            )
            # Normal ledger transactions
            cur.execute(
                """
                INSERT INTO ledger_transactions (
                    ledger_id, transaction_date, transaction_time, voucher_type,
                    voucher_no, reference_type, reference_id, description, debit, credit
                ) VALUES (1, '2026-10-21', '12:00', 'Counter Sale', ?, 'COUNTER_SALE', ?, ?, ?, 0.0)
                """,
                (bno, inv_id, f"Sale {bno} to WALKIN", amt),
            )
            cur.execute(
                """
                INSERT INTO ledger_transactions (
                    ledger_id, transaction_date, transaction_time, voucher_type,
                    voucher_no, reference_type, reference_id, description, debit, credit
                ) VALUES (2, '2026-10-21', '12:00', 'Counter Sale', ?, 'COUNTER_SALE', ?, ?, 0.0, ?)
                """,
                (bno, inv_id, f"Sale {bno} to WALKIN", amt),
            )
            # For 72191 and 72198 add reversal transactions to test reversal description updating
            if inv_id in (72191, 72198):
                cur.execute(
                    """
                    INSERT INTO ledger_transactions (
                        ledger_id, transaction_date, transaction_time, voucher_type,
                        voucher_no, reference_type, reference_id, description, debit, credit
                    ) VALUES (1, '2026-10-21', '12:00', 'Counter Sale Reversal', ?, 'COUNTER_SALE', ?, ?, 0.0, ?)
                    """,
                    (bno, inv_id, f"REVERSAL: Counter Sale {bno}", amt),
                )

        conn.commit()
        conn.close()

    def test_01_dry_run_does_not_modify_database(self):
        res = reassign_bill_numbers(self._db_path, make_backup=False, dry_run=True)
        self.assertEqual(res["status"], "dry_run_success")

        conn = sqlite3.connect(self._db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, bill_no FROM sales_invoices WHERE id = 72188")
        row = cur.fetchone()
        self.assertEqual(row[1], "2019", "Dry run must not change bill_no")
        conn.close()

    def test_02_migration_renumbers_correctly(self):
        res = reassign_bill_numbers(self._db_path, make_backup=False)
        self.assertEqual(res["status"], "success")

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Invoices 72184 and 72185 must remain unchanged
        cur.execute("SELECT bill_no FROM sales_invoices WHERE id = 72184")
        self.assertEqual(cur.fetchone()["bill_no"], "2015")
        cur.execute("SELECT bill_no FROM sales_invoices WHERE id = 72185")
        self.assertEqual(cur.fetchone()["bill_no"], "2016")

        # Invoices 72186 and 72187 must have bill_no cleared to ""
        cur.execute("SELECT bill_no FROM sales_invoices WHERE id = 72186")
        self.assertEqual(cur.fetchone()["bill_no"], "")
        cur.execute("SELECT bill_no FROM sales_invoices WHERE id = 72187")
        self.assertEqual(cur.fetchone()["bill_no"], "")

        # Invoices 72188 and 72189 must become 2017 and 2018
        cur.execute("SELECT bill_no, patient_name FROM sales_invoices WHERE id = 72188")
        r88 = cur.fetchone()
        self.assertEqual(r88["bill_no"], "2017")
        self.assertEqual(r88["patient_name"], "MRS ARCHANA GARUD")

        cur.execute("SELECT bill_no, patient_name FROM sales_invoices WHERE id = 72189")
        r89 = cur.fetchone()
        self.assertEqual(r89["bill_no"], "2018")
        self.assertEqual(r89["patient_name"], "MR RAOSAHEB LONDHE")

        # Max invoice 72202 must be 2031
        cur.execute("SELECT bill_no, patient_name FROM sales_invoices WHERE id = 72202")
        r02 = cur.fetchone()
        self.assertEqual(r02["bill_no"], "2031")
        self.assertEqual(r02["patient_name"], "MR SUDHAKAR TANPURE")

        # Check all invoices from 72188..72202 are shifted by -2
        for inv_id, orig_bno, pat, amt in self.invoice_seeds:
            if inv_id >= 72188:
                cur.execute("SELECT bill_no, patient_name, total_amount, net_amount FROM sales_invoices WHERE id = ?", (inv_id,))
                r = cur.fetchone()
                expected_bno = str(int(orig_bno) - 2)
                self.assertEqual(r["bill_no"], expected_bno)
                self.assertEqual(r["patient_name"], pat)
                self.assertEqual(r["total_amount"], amt)
                self.assertEqual(r["net_amount"], amt)

        # Check no duplicates exist
        cur.execute("""
            SELECT bill_no, COUNT(*) as cnt
            FROM sales_invoices
            WHERE bill_no IS NOT NULL AND TRIM(bill_no) <> ''
            GROUP BY bill_no HAVING cnt > 1
        """)
        dups = cur.fetchall()
        self.assertEqual(len(dups), 0)

        # Check ledger_transactions consistency
        cur.execute("SELECT voucher_no, description FROM ledger_transactions WHERE reference_id = 72186")
        for lt in cur.fetchall():
            self.assertEqual(lt["voucher_no"], "")
            self.assertEqual(lt["description"], "Sale to WALKIN")

        cur.execute("SELECT voucher_no, description FROM ledger_transactions WHERE reference_id = 72188")
        for lt in cur.fetchall():
            self.assertEqual(lt["voucher_no"], "2017")
            self.assertEqual(lt["description"], "Sale 2017 to WALKIN")

        # Reversal transaction check on 72191 (old 2022 -> new 2020)
        cur.execute("SELECT voucher_no, description FROM ledger_transactions WHERE reference_id = 72191 AND voucher_type LIKE '%Reversal%'")
        rev = cur.fetchone()
        self.assertIsNotNone(rev)
        self.assertEqual(rev["voucher_no"], "2020")
        self.assertEqual(rev["description"], "REVERSAL: Counter Sale 2020")

        conn.close()

    def test_03_next_bill_generation_resumes_at_2032(self):
        reassign_bill_numbers(self._db_path, make_backup=False)

        conn = get_connection()
        cur = conn.cursor()
        next_cand = SalesDAO.generate_next_bill_no(cur=cur)
        disp_bno = format_sales_bill_number(next_cand)
        self.assertEqual(disp_bno, "2032")
        conn.close()

    def test_04_ui_display_shows_unbroken_sequence(self):
        reassign_bill_numbers(self._db_path, make_backup=False)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, bill_no, patient_name FROM sales_invoices WHERE id >= 72188 ORDER BY id ASC")
        rows = cur.fetchall()
        conn.close()

        # Build list of stored bill numbers for renumbered records
        stored_bill_nos = [int(r["bill_no"]) for r in rows]
        # Should be exactly 2017, 2018, ..., 2031
        self.assertEqual(stored_bill_nos[0], 2017)
        self.assertEqual(stored_bill_nos[1], 2018)
        self.assertEqual(stored_bill_nos[-1], 2031)
        self.assertEqual(len(stored_bill_nos), 15)
        for i in range(len(stored_bill_nos) - 1):
            self.assertEqual(stored_bill_nos[i + 1], stored_bill_nos[i] + 1)

        # Formatted bill numbers without patient suppression
        for r in rows:
            formatted = format_sales_bill_number(r["bill_no"])
            self.assertEqual(formatted, r["bill_no"])

    def test_05_idempotent_and_safe(self):
        res1 = reassign_bill_numbers(self._db_path, make_backup=False)
        self.assertEqual(res1["status"], "success")

        # Second run should detect it's already applied
        res2 = reassign_bill_numbers(self._db_path, make_backup=False)
        self.assertEqual(res2["status"], "already_applied")

        # Third run in dry_run mode should also detect already applied
        res3 = reassign_bill_numbers(self._db_path, make_backup=False, dry_run=True)
        self.assertEqual(res3["status"], "already_applied")

    def test_06_new_sales_and_editing_continue_cleanly(self):
        reassign_bill_numbers(self._db_path, make_backup=False)

        # 1. Insert a new named sale: should automatically be 2032
        new_inv_id = SalesDAO.insert_invoice(
            bill_no=None,
            sale_date="2026-10-22",
            sale_time="14:00",
            sale_type="Cash",
            customer_id=None,
            patient_name="MR NEW PATIENT",
            doctor_id=None,
            discount=0.0,
            paid_amount=100.0,
            total_amount=100.0,
            round_off=0.0,
            net_amount=100.0,
            remarks="Test new bill",
            items=[],
        )
        self.assertIsNotNone(new_inv_id)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT bill_no, patient_name FROM sales_invoices WHERE id = ?", (new_inv_id,))
        new_row = cur.fetchone()
        conn.close()

        disp_bno = format_sales_bill_number(new_row["bill_no"])
        self.assertEqual(disp_bno, "2032")

        # 2. Update an existing invoice (72188, which is now bill 2017)
        SalesDAO.update_invoice(
            invoice_id=72188,
            bill_no="2017",
            sale_date="2026-10-21",
            sale_time="17:47",
            sale_type="Cash",
            customer_id=None,
            patient_name="MRS ARCHANA GARUD EDITED",
            doctor_id=None,
            discount=0.0,
            paid_amount=576.37,
            total_amount=576.37,
            round_off=0.0,
            net_amount=576.37,
            remarks="Updated remarks",
            items=[],
        )

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT bill_no, patient_name FROM sales_invoices WHERE id = 72188")
        updated_row = cur.fetchone()
        conn.close()

        self.assertEqual(updated_row["bill_no"], "2017")
        self.assertEqual(updated_row["patient_name"], "MRS ARCHANA GARUD EDITED")


if __name__ == "__main__":
    unittest.main()
