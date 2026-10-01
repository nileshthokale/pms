"""Phase 6B-3 Cash Book tests over isolated ledger data."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.connection import get_connection, init_database
from database.cash_book_dao import CashBookDAO, CashBookError
from database.financial_year import ensure_default_financial_year


class CashBookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_cash_book_test.db")
        if os.path.exists(cls.db_path): os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path; init_database(); ensure_default_financial_year()

    def setUp(self):
        conn = get_connection()
        conn.execute("DELETE FROM ledger_transactions"); conn.execute("DELETE FROM account_ledgers")
        conn.commit(); conn.close()
        self.cash = self._ledger("Cash", "CASH", 100, "Debit")
        self.bank = self._ledger("Bank", "BANK", 500, "Debit")
        self.other = self._ledger("Other", None, 0, "Debit")

    def _ledger(self, name, role, opening=0, kind="Debit"):
        conn = get_connection(); cur = conn.execute("insert into account_ledgers (ledger_name,system_role,opening_balance,opening_balance_type) values (?,?,?,?)", (name,role,opening,kind)); conn.commit(); value = cur.lastrowid; conn.close(); return value

    def _txn(self, ledger, date, debit=0, credit=0, voucher="V", reference="TEST", description="particular"):
        conn = get_connection(); cur = conn.execute("insert into ledger_transactions (ledger_id,transaction_date,transaction_time,voucher_type,voucher_no,reference_type,reference_id,description,debit,credit) values (?,?,?,?,?,?,?,?,?,?)", (ledger,date,"10:00","Test",voucher,reference,1,description,debit,credit)); conn.commit(); value = cur.lastrowid; conn.close(); return value

    def report(self, start="2026-04-01", end="2027-03-31"): return CashBookDAO.get_cash_book(start, end)
    def test_01_empty_cash_book(self): self.assertEqual(self.report()["rows"], [])
    def test_02_cash_ledger_found_by_role(self): self.assertEqual(CashBookDAO.get_cash_ledger()["id"], self.cash)
    def test_03_no_cash_ledger(self):
        conn=get_connection(); conn.execute("delete from account_ledgers where id=?",(self.cash,)); conn.commit(); conn.close(); self.assertIsNone(CashBookDAO.get_cash_ledger()); self.assertEqual(self.report()["rows"], [])
    def test_04_opening_ledger_balance(self): self.assertEqual(self.report()["opening_balance"], 100)
    def test_05_opening_prior_debit(self): self._txn(self.cash,"2026-05-01",debit=20); self.assertEqual(CashBookDAO.get_opening_balance("2026-06-01"),120)
    def test_06_opening_prior_credit(self): self._txn(self.cash,"2026-05-01",credit=20); self.assertEqual(CashBookDAO.get_opening_balance("2026-06-01"),80)
    def test_07_first_day_included(self): self._txn(self.cash,"2026-06-01",debit=10); self.assertEqual(len(CashBookDAO.get_cash_book("2026-06-01","2026-06-01")["rows"]),1)
    def test_08_prior_day_excluded_rows(self): self._txn(self.cash,"2026-05-31",debit=10); self.assertEqual(len(CashBookDAO.get_cash_book("2026-06-01","2026-06-30")["rows"]),0)
    def test_09_last_day_included(self): self._txn(self.cash,"2026-06-30",credit=10); self.assertEqual(len(CashBookDAO.get_cash_book("2026-06-01","2026-06-30")["rows"]),1)
    def test_10_after_day_excluded(self): self._txn(self.cash,"2026-07-01",credit=10); self.assertEqual(len(CashBookDAO.get_cash_book("2026-06-01","2026-06-30")["rows"]),0)
    def test_11_debit_total(self): self._txn(self.cash,"2026-06-01",debit=25); self.assertEqual(self.report()["summary"]["total_debit"],25)
    def test_12_credit_total(self): self._txn(self.cash,"2026-06-01",credit=25); self.assertEqual(self.report()["summary"]["total_credit"],25)
    def test_13_net_movement(self): self._txn(self.cash,"2026-06-01",debit=30,credit=10); self.assertEqual(self.report()["summary"]["net_movement"],20)
    def test_14_closing_balance(self): self._txn(self.cash,"2026-06-01",debit=30,credit=10); self.assertEqual(self.report()["summary"]["closing_balance"],120)
    def test_15_running_balance(self): self._txn(self.cash,"2026-06-01",debit=30); self._txn(self.cash,"2026-06-02",credit=10); rows=self.report()["rows"]; self.assertEqual([r["balance"] for r in rows],[130,120])
    def test_16_multiple_transactions(self):
        for i in range(5): self._txn(self.cash,f"2026-06-{i+1:02d}",debit=1)
        self.assertEqual(len(self.report()["rows"]),5)
    def test_17_same_day_order(self): self._txn(self.cash,"2026-06-01",debit=2,voucher="A"); self._txn(self.cash,"2026-06-01",credit=1,voucher="B"); self.assertEqual(len(self.report()["rows"]),2)
    def test_18_bank_excluded(self): self._txn(self.bank,"2026-06-01",debit=100); self.assertEqual(len(self.report()["rows"]),0)
    def test_19_other_ledger_excluded(self): self._txn(self.other,"2026-06-01",debit=100); self.assertEqual(len(self.report()["rows"]),0)
    def test_20_bank_role_not_cash(self): self.assertNotEqual(CashBookDAO.get_cash_ledger()["id"], self.bank)
    def test_21_reference_number(self): self._txn(self.cash,"2026-06-01",debit=1,voucher="CR-1"); self.assertEqual(self.report()["rows"][0]["voucher_no"],"CR-1")
    def test_22_reference_type(self): self._txn(self.cash,"2026-06-01",debit=1,reference="CUSTOMER_RECEIPT"); self.assertEqual(self.report()["rows"][0]["reference_type"],"CUSTOMER_RECEIPT")
    def test_23_particulars(self): self._txn(self.cash,"2026-06-01",debit=1,description="Cash receipt"); self.assertEqual(self.report()["rows"][0]["description"],"Cash receipt")
    def test_24_transaction_id(self): self._txn(self.cash,"2026-06-01",debit=1); self.assertIn("id",self.report()["rows"][0])
    def test_25_invalid_from_date(self):
        with self.assertRaises(CashBookError): CashBookDAO.get_cash_book("bad","2026-06-01")
    def test_26_invalid_to_date(self):
        with self.assertRaises(CashBookError): CashBookDAO.get_cash_book("2026-06-01","bad")
    def test_27_reversed_range(self):
        with self.assertRaises(CashBookError): CashBookDAO.get_cash_book("2026-07-01","2026-06-01")
    def test_28_manual_historical_range(self): self._txn(self.cash,"2025-01-01",debit=5); self.assertEqual(len(CashBookDAO.get_cash_book("2025-01-01","2025-01-01")["rows"]),1)
    def test_29_active_fy_filter_options(self): self.assertEqual(CashBookDAO.get_filter_options(),{"from_date":"2026-04-01","to_date":"2027-03-31"})
    def test_30_summary_accessor(self): self._txn(self.cash,"2026-06-01",debit=5); self.assertEqual(CashBookDAO.get_summary("2026-04-01","2027-03-31")["total_debit"],5)
    def test_31_closing_accessor(self): self.assertEqual(CashBookDAO.get_closing_balance("2026-04-01","2027-03-31"),100)
    def test_32_credit_opening_balance(self):
        conn=get_connection(); conn.execute("update account_ledgers set opening_balance=50,opening_balance_type='Credit' where id=?",(self.cash,)); conn.commit(); conn.close(); self.assertEqual(self.report()["opening_balance"],-50)
    def test_33_credit_opening_plus_debit(self):
        conn=get_connection(); conn.execute("update account_ledgers set opening_balance=50,opening_balance_type='Credit' where id=?",(self.cash,)); conn.commit(); conn.close(); self._txn(self.cash,"2026-06-01",debit=20); self.assertEqual(self.report()["summary"]["closing_balance"],-30)
    def test_34_rows_are_read_only(self):
        before=self.counts(); self.report(); self.assertEqual(before,self.counts())
    def test_35_repeated_report_unchanged(self): self._txn(self.cash,"2026-06-01",debit=5); first=self.report(); second=self.report(); self.assertEqual(first,second)
    def counts(self):
        conn=get_connection(); result=(conn.execute("select count(*) from ledger_transactions").fetchone()[0],conn.execute("select count(*) from stock_batches").fetchone()[0]); conn.close(); return result
    def test_36_no_posting_on_view(self): self._txn(self.cash,"2026-06-01",debit=5); before=self.counts(); self.report(); self.assertEqual(before,self.counts())
    def test_37_unrelated_ledger_unchanged(self): self._txn(self.other,"2026-06-01",debit=9); before=self._other_count(); self.report(); self.assertEqual(before,self._other_count())
    def _other_count(self):
        conn=get_connection(); value=conn.execute("select count(*) from ledger_transactions where ledger_id=?",(self.other,)).fetchone()[0]; conn.close(); return value
    def test_38_empty_summary(self): self.assertEqual(self.report()["summary"]["closing_balance"],100)
    def test_39_opening_before_period(self): self._txn(self.cash,"2026-04-01",debit=3); self.assertEqual(CashBookDAO.get_opening_balance("2026-04-02"),103)
    def test_40_boundary_opening_excludes_same_day(self): self._txn(self.cash,"2026-04-02",debit=3); self.assertEqual(CashBookDAO.get_opening_balance("2026-04-02"),100)
    def test_41_date_order(self): self._txn(self.cash,"2026-06-02",debit=1); self._txn(self.cash,"2026-06-01",debit=1); self.assertEqual(self.report("2026-06-01","2026-06-02")["rows"][0]["transaction_date"],"2026-06-01")
    def test_42_no_arbitrary_sql_api(self): self.assertFalse(hasattr(CashBookDAO,"execute_sql"))
    def test_43_cash_ledger_by_system_role(self):
        conn=get_connection(); conn.execute("update account_ledgers set ledger_name='Renamed Cash' where id=?",(self.cash,)); conn.commit(); conn.close(); self.assertEqual(CashBookDAO.get_cash_ledger()["id"],self.cash)
    def test_44_summary_net_formula(self): self._txn(self.cash,"2026-06-01",debit=7,credit=2); summary=self.report()["summary"]; self.assertEqual(summary["net_movement"],summary["total_debit"]-summary["total_credit"])
    def test_45_closing_formula(self): self._txn(self.cash,"2026-06-01",debit=7,credit=2); result=self.report(); self.assertEqual(result["summary"]["closing_balance"],result["opening_balance"]+result["summary"]["net_movement"])
    def test_46_reference_id_preserved(self): self._txn(self.cash,"2026-06-01",debit=1); self.assertEqual(self.report()["rows"][0]["reference_id"],1)
    def test_47_time_preserved(self): self._txn(self.cash,"2026-06-01",debit=1); self.assertEqual(self.report()["rows"][0]["transaction_time"],"10:00")
    def test_48_transaction_ledger_id_preserved(self): self._txn(self.cash,"2026-06-01",debit=1); self.assertEqual(self.report()["rows"][0]["ledger_id"],self.cash)
    def test_49_production_path_not_used(self): self.assertNotEqual(os.path.abspath(self.db_path),os.path.abspath("data/pharmacy.db"))
    def test_50_no_mysql_reference(self): self.assertNotIn("mysql",Path(__import__("database.cash_book_dao",fromlist=["__file__"]).__file__).read_text(encoding="utf-8").lower())
    def test_51_pdf_contains_cash_book_rows(self):
        from database.document_printing import generate_document
        path = Path(self.db_path).with_name("cash_book_test.pdf")
        self._txn(self.cash, "2026-06-01", debit=5, voucher="CR-1", description="Cash receipt")
        report = self.report("2026-06-01", "2026-06-01")
        rows = [{"item_name": " | ".join((r["transaction_date"], r["voucher_no"], r["description"], f"{r['debit'] or 0:.2f}", f"{r['credit'] or 0:.2f}", f"{r['balance']:.2f}"))} for r in report["rows"]]
        output = generate_document("Cash Book", {"voucher_no": "CR-1"}, rows, path)
        self.assertIn(b"Cash receipt", Path(output).read_bytes())
        path.unlink(missing_ok=True)


if __name__ == "__main__": unittest.main()
