"""Phase 6B-4 Bank Book tests over isolated BANK ledger data."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.connection import get_connection, init_database
from database.bank_book_dao import BankBookDAO, BankBookError
from database.financial_year import ensure_default_financial_year


class BankBookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = os.path.join(tempfile.gettempdir(), "pharmacy_bank_book_test.db")
        if os.path.exists(cls.db_path): os.remove(cls.db_path)
        os.environ["PHARMACY_DB"] = cls.db_path; init_database(); ensure_default_financial_year()

    def setUp(self):
        conn = get_connection(); conn.execute("DELETE FROM ledger_transactions"); conn.execute("DELETE FROM account_ledgers"); conn.commit(); conn.close()
        self.bank = self._ledger("Bank", "BANK", 100); self.cash = self._ledger("Cash", "CASH", 50); self.other = self._ledger("Other", None, 0)

    def _ledger(self, name, role, opening=0, kind="Debit"):
        conn=get_connection(); cur=conn.execute("insert into account_ledgers (ledger_name,system_role,opening_balance,opening_balance_type) values (?,?,?,?)",(name,role,opening,kind)); conn.commit(); value=cur.lastrowid; conn.close(); return value
    def _txn(self, ledger, date, debit=0, credit=0, voucher="V", reference="TEST", description="particular"):
        conn=get_connection(); cur=conn.execute("insert into ledger_transactions (ledger_id,transaction_date,transaction_time,voucher_type,voucher_no,reference_type,reference_id,description,debit,credit) values (?,?,?,?,?,?,?,?,?,?)",(ledger,date,"10:00","Test",voucher,reference,1,description,debit,credit)); conn.commit(); value=cur.lastrowid; conn.close(); return value
    def report(self,start="2026-04-01",end="2027-03-31"): return BankBookDAO.get_bank_book(start,end)
    def test_01_empty(self): self.assertEqual(self.report()["rows"],[])
    def test_02_bank_found_by_role(self): self.assertEqual(BankBookDAO.get_bank_ledger()["id"],self.bank)
    def test_03_no_bank_ledger(self):
        c=get_connection(); c.execute("delete from account_ledgers where id=?",(self.bank,)); c.commit(); c.close(); self.assertIsNone(BankBookDAO.get_bank_ledger()); self.assertEqual(self.report()["rows"],[])
    def test_04_opening_balance(self): self.assertEqual(self.report()["opening_balance"],100)
    def test_05_prior_debit_opening(self): self._txn(self.bank,"2026-05-01",debit=20); self.assertEqual(BankBookDAO.get_opening_balance("2026-06-01"),120)
    def test_06_prior_credit_opening(self): self._txn(self.bank,"2026-05-01",credit=20); self.assertEqual(BankBookDAO.get_opening_balance("2026-06-01"),80)
    def test_07_first_day(self): self._txn(self.bank,"2026-06-01",debit=10); self.assertEqual(len(BankBookDAO.get_bank_book("2026-06-01","2026-06-01")["rows"]),1)
    def test_08_last_day(self): self._txn(self.bank,"2026-06-30",credit=10); self.assertEqual(len(BankBookDAO.get_bank_book("2026-06-01","2026-06-30")["rows"]),1)
    def test_09_before_excluded_rows(self): self._txn(self.bank,"2026-05-31",debit=10); self.assertEqual(len(BankBookDAO.get_bank_book("2026-06-01","2026-06-30")["rows"]),0)
    def test_10_after_excluded_rows(self): self._txn(self.bank,"2026-07-01",debit=10); self.assertEqual(len(BankBookDAO.get_bank_book("2026-06-01","2026-06-30")["rows"]),0)
    def test_11_debit_total(self): self._txn(self.bank,"2026-06-01",debit=25); self.assertEqual(self.report()["summary"]["total_debit"],25)
    def test_12_credit_total(self): self._txn(self.bank,"2026-06-01",credit=25); self.assertEqual(self.report()["summary"]["total_credit"],25)
    def test_13_net(self): self._txn(self.bank,"2026-06-01",debit=30,credit=10); self.assertEqual(self.report()["summary"]["net_movement"],20)
    def test_14_closing(self): self._txn(self.bank,"2026-06-01",debit=30,credit=10); self.assertEqual(self.report()["summary"]["closing_balance"],120)
    def test_15_running(self): self._txn(self.bank,"2026-06-01",debit=30); self._txn(self.bank,"2026-06-02",credit=10); self.assertEqual([r["balance"] for r in self.report()["rows"]],[130,120])
    def test_16_multiple(self):
        for i in range(5): self._txn(self.bank,f"2026-06-{i+1:02d}",debit=1)
        self.assertEqual(len(self.report()["rows"]),5)
    def test_17_same_day_order(self): self._txn(self.bank,"2026-06-01",debit=2,voucher="A"); self._txn(self.bank,"2026-06-01",credit=1,voucher="B"); self.assertEqual(len(self.report()["rows"]),2)
    def test_18_cash_excluded(self): self._txn(self.cash,"2026-06-01",debit=100); self.assertEqual(len(self.report()["rows"]),0)
    def test_19_other_excluded(self): self._txn(self.other,"2026-06-01",debit=100); self.assertEqual(len(self.report()["rows"]),0)
    def test_20_reference(self): self._txn(self.bank,"2026-06-01",debit=1,voucher="SP-1"); self.assertEqual(self.report()["rows"][0]["voucher_no"],"SP-1")
    def test_21_reference_type(self): self._txn(self.bank,"2026-06-01",debit=1,reference="SUPPLIER_PAYMENT"); self.assertEqual(self.report()["rows"][0]["reference_type"],"SUPPLIER_PAYMENT")
    def test_22_particulars(self): self._txn(self.bank,"2026-06-01",debit=1,description="Bank payment"); self.assertEqual(self.report()["rows"][0]["description"],"Bank payment")
    def test_23_transaction_id(self): self._txn(self.bank,"2026-06-01",debit=1); self.assertIn("id",self.report()["rows"][0])
    def test_24_invalid_from(self):
        with self.assertRaises(BankBookError): BankBookDAO.get_bank_book("bad","2026-06-01")
    def test_25_invalid_to(self):
        with self.assertRaises(BankBookError): BankBookDAO.get_bank_book("2026-06-01","bad")
    def test_26_reversed_range(self):
        with self.assertRaises(BankBookError): BankBookDAO.get_bank_book("2026-07-01","2026-06-01")
    def test_27_historical_range(self): self._txn(self.bank,"2025-01-01",debit=5); self.assertEqual(len(BankBookDAO.get_bank_book("2025-01-01","2025-01-01")["rows"]),1)
    def test_28_filter_options(self): self.assertEqual(BankBookDAO.get_filter_options(),{"from_date":"2026-04-01","to_date":"2027-03-31"})
    def test_29_summary_accessor(self): self._txn(self.bank,"2026-06-01",debit=5); self.assertEqual(BankBookDAO.get_summary("2026-04-01","2027-03-31")["total_debit"],5)
    def test_30_closing_accessor(self): self.assertEqual(BankBookDAO.get_closing_balance("2026-04-01","2027-03-31"),100)
    def test_31_credit_opening(self):
        c=get_connection(); c.execute("update account_ledgers set opening_balance=50,opening_balance_type='Credit' where id=?",(self.bank,)); c.commit(); c.close(); self.assertEqual(self.report()["opening_balance"],-50)
    def test_32_credit_opening_plus_debit(self):
        c=get_connection(); c.execute("update account_ledgers set opening_balance=50,opening_balance_type='Credit' where id=?",(self.bank,)); c.commit(); c.close(); self._txn(self.bank,"2026-06-01",debit=20); self.assertEqual(self.report()["summary"]["closing_balance"],-30)
    def test_33_read_only(self):
        before=self.counts(); self.report(); self.assertEqual(before,self.counts())
    def test_34_repeated_unchanged(self): self._txn(self.bank,"2026-06-01",debit=5); self.assertEqual(self.report(),self.report())
    def test_35_no_posting_on_view(self): self._txn(self.bank,"2026-06-01",debit=5); before=self.counts(); self.report(); self.assertEqual(before,self.counts())
    def counts(self):
        c=get_connection(); value=(c.execute("select count(*) from ledger_transactions").fetchone()[0],c.execute("select count(*) from stock_batches").fetchone()[0]); c.close(); return value
    def test_36_unrelated_ledger_unchanged(self): self._txn(self.other,"2026-06-01",debit=9); before=self.other_count(); self.report(); self.assertEqual(before,self.other_count())
    def other_count(self):
        c=get_connection(); value=c.execute("select count(*) from ledger_transactions where ledger_id=?",(self.other,)).fetchone()[0]; c.close(); return value
    def test_37_boundary_opening_excludes_same_day(self): self._txn(self.bank,"2026-06-02",debit=3); self.assertEqual(BankBookDAO.get_opening_balance("2026-06-02"),100)
    def test_38_date_order(self): self._txn(self.bank,"2026-06-02",debit=1); self._txn(self.bank,"2026-06-01",debit=1); self.assertEqual(self.report("2026-06-01","2026-06-02")["rows"][0]["transaction_date"],"2026-06-01")
    def test_39_role_identification_after_rename(self):
        c=get_connection(); c.execute("update account_ledgers set ledger_name='Renamed Bank' where id=?",(self.bank,)); c.commit(); c.close(); self.assertEqual(BankBookDAO.get_bank_ledger()["id"],self.bank)
    def test_40_net_formula(self): self._txn(self.bank,"2026-06-01",debit=7,credit=2); s=self.report()["summary"]; self.assertEqual(s["net_movement"],s["total_debit"]-s["total_credit"])
    def test_41_closing_formula(self): self._txn(self.bank,"2026-06-01",debit=7,credit=2); r=self.report(); self.assertEqual(r["summary"]["closing_balance"],r["opening_balance"]+r["summary"]["net_movement"])
    def test_42_reference_id(self): self._txn(self.bank,"2026-06-01",debit=1); self.assertEqual(self.report()["rows"][0]["reference_id"],1)
    def test_43_time(self): self._txn(self.bank,"2026-06-01",debit=1); self.assertEqual(self.report()["rows"][0]["transaction_time"],"10:00")
    def test_44_ledger_id(self): self._txn(self.bank,"2026-06-01",debit=1); self.assertEqual(self.report()["rows"][0]["ledger_id"],self.bank)
    def test_45_no_arbitrary_sql(self): self.assertFalse(hasattr(BankBookDAO,"execute_sql"))
    def test_46_production_not_targeted(self): self.assertNotEqual(os.path.abspath(self.db_path),os.path.abspath("data/pharmacy.db"))
    def test_47_no_mysql_reference(self): self.assertNotIn("mysql",Path(__import__("database.bank_book_dao",fromlist=["__file__"]).__file__).read_text(encoding="utf-8").lower())
    def test_48_pdf_contains_bank_row(self):
        from database.document_printing import generate_document
        path=Path(self.db_path).with_name("bank_book_test.pdf"); self._txn(self.bank,"2026-06-01",debit=5,voucher="BP-1",description="Bank entry"); report=self.report("2026-06-01","2026-06-01"); output=generate_document("Bank Book",{"voucher_no":"BP-1"},[{"item_name":f"{r['voucher_no']} {r['description']}"} for r in report["rows"]],path); self.assertIn(b"Bank entry",Path(output).read_bytes()); path.unlink(missing_ok=True)
    def test_49_empty_message_condition(self): self.assertEqual(self.report()["rows"],[])
    def test_50_bank_summary_uses_only_bank(self): self._txn(self.cash,"2026-06-01",debit=50); self._txn(self.bank,"2026-06-01",debit=5); self.assertEqual(self.report()["summary"]["total_debit"],5)
    def test_51_bank_book_does_not_change_cash_book(self):
        self._txn(self.cash,"2026-06-01",debit=5); before=self.counts(); self.report(); self.assertEqual(before,self.counts())


if __name__ == "__main__": unittest.main()
