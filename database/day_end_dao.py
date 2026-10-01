"""Read-only daily operational summary over stored source and ledger data."""

from __future__ import annotations
from datetime import datetime
from typing import Any
from database.connection import get_connection
from database.cash_book_dao import CashBookDAO
from database.bank_book_dao import BankBookDAO
from database.financial_year import active_date_range


class DayEndError(ValueError):
    pass


def _date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise DayEndError("Business Date must use YYYY-MM-DD format.") from exc
    return value


class DayEndDAO:
    """Daily summary; never writes or posts accounting entries."""

    @staticmethod
    def get_sales_summary(day: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("""SELECT COUNT(*) count, COALESCE(SUM(total_amount),0) amount,
                COALESCE(SUM(discount),0) discount, COALESCE(SUM(net_amount),0) net
                FROM sales_invoices WHERE sale_date=?""", (day,)).fetchone()
            counter = conn.execute("SELECT COALESCE(SUM(net_amount),0) FROM sales_invoices WHERE sale_date=? AND sale_type='Cash'", (day,)).fetchone()[0]
            return {"count": row["count"], "amount": row["amount"], "counter_sales": counter, "discount": row["discount"], "net": row["net"]}
        finally: conn.close()

    @staticmethod
    def get_purchase_summary(day: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            row = conn.execute("""SELECT COUNT(*) count, COALESCE(SUM(total_amount),0) amount,
                COALESCE(SUM(gst_amount),0) gst, COALESCE(SUM(bill_discount),0) discount,
                COALESCE(SUM(other_amount),0) other_amount, COALESCE(SUM(round_off),0) round_off,
                COALESCE(SUM(net_amount),0) net FROM purchase_invoices WHERE voucher_date=?""", (day,)).fetchone()
            return dict(row)
        finally: conn.close()

    @staticmethod
    def get_returns_summary(day: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            credit = conn.execute("SELECT COUNT(*) count, COALESCE(SUM(total_amount),0) amount FROM credit_notes WHERE voucher_date=?", (day,)).fetchone()
            debit = conn.execute("SELECT COUNT(*) count, COALESCE(SUM(total_amount),0) amount FROM debit_notes WHERE voucher_date=?", (day,)).fetchone()
            return {"credit_count": credit["count"], "credit_amount": credit["amount"], "debit_count": debit["count"], "debit_amount": debit["amount"]}
        finally: conn.close()

    @staticmethod
    def get_receipt_summary(day: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT receipt_mode, COUNT(*) count, COALESCE(SUM(amount),0) amount FROM customer_receipts WHERE receipt_date=? GROUP BY receipt_mode", (day,)).fetchall()
            result = {"count": 0, "cash": 0.0, "bank": 0.0, "total": 0.0}
            for row in rows:
                result["count"] += row["count"]; result["total"] += row["amount"]
                if row["receipt_mode"] == "Cash": result["cash"] += row["amount"]
                elif row["receipt_mode"] in {"Bank", "Cheque", "UPI"}: result["bank"] += row["amount"]
            return result
        finally: conn.close()

    @staticmethod
    def get_payment_summary(day: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT payment_mode, COUNT(*) count, COALESCE(SUM(amount),0) amount FROM supplier_payments WHERE payment_date=? GROUP BY payment_mode", (day,)).fetchall()
            result = {"count": 0, "cash": 0.0, "bank": 0.0, "total": 0.0}
            for row in rows:
                result["count"] += row["count"]; result["total"] += row["amount"]
                if row["payment_mode"] == "Cash": result["cash"] += row["amount"]
                elif row["payment_mode"] in {"Bank", "Cheque", "UPI"}: result["bank"] += row["amount"]
            return result
        finally: conn.close()

    @staticmethod
    def get_cash_summary(day: str) -> dict[str, Any]:
        report = CashBookDAO.get_cash_book(day, day); summary = report["summary"]
        return {"opening": report["opening_balance"], "debit": summary["total_debit"], "credit": summary["total_credit"], "net": summary["net_movement"], "closing": summary["closing_balance"]}

    @staticmethod
    def get_bank_summary(day: str) -> dict[str, Any]:
        report = BankBookDAO.get_bank_book(day, day); summary = report["summary"]
        return {"opening": report["opening_balance"], "debit": summary["total_debit"], "credit": summary["total_credit"], "net": summary["net_movement"], "closing": summary["closing_balance"]}

    @staticmethod
    def get_stock_summary(day: str) -> dict[str, Any]:
        conn = get_connection()
        try:
            purchase = conn.execute("SELECT COALESCE(SUM(pii.pay_qty+pii.free_qty),0) FROM purchase_invoice_items pii JOIN purchase_invoices pi ON pi.id=pii.purchase_invoice_id WHERE pi.voucher_date=?", (day,)).fetchone()[0]
            sales = conn.execute("SELECT COALESCE(SUM(sii.sale_qty),0) FROM sales_invoice_items sii JOIN sales_invoices si ON si.id=sii.sales_invoice_id WHERE si.sale_date=?", (day,)).fetchone()[0]
            credit = conn.execute("SELECT COALESCE(SUM(cii.return_qty),0) FROM credit_note_items cii JOIN credit_notes cn ON cn.id=cii.credit_note_id WHERE cn.voucher_date=?", (day,)).fetchone()[0]
            debit = conn.execute("SELECT COALESCE(SUM(dii.return_qty),0) FROM debit_note_items dii JOIN debit_notes dn ON dn.id=dii.debit_note_id WHERE dn.voucher_date=?", (day,)).fetchone()[0]
            return {"purchase_added": purchase, "sales_removed": sales, "customer_return_added": credit, "supplier_return_removed": debit}
        finally: conn.close()

    @staticmethod
    def get_reconciliation(day: str) -> dict[str, Any]:
        """Related daily totals for the reconciliation section.

        A reliable cash-drawer "difference" cannot be calculated from
        the stored data (no opening/closing cash counts or physical
        denominations are recorded), so it is explicitly reported as
        unavailable rather than invented.
        """
        return DayEndDAO.get_day_summary(day)["reconciliation"]

    @staticmethod
    def get_day_summary(day: str) -> dict[str, Any]:
        day = _date(day)
        sales = DayEndDAO.get_sales_summary(day); purchase = DayEndDAO.get_purchase_summary(day); returns = DayEndDAO.get_returns_summary(day); receipts = DayEndDAO.get_receipt_summary(day); payments = DayEndDAO.get_payment_summary(day); cash = DayEndDAO.get_cash_summary(day); bank = DayEndDAO.get_bank_summary(day); stock = DayEndDAO.get_stock_summary(day)
        overall = {"sales": sales["net"], "purchases": purchase["net"], "customer_receipts": receipts["total"], "supplier_payments": payments["total"], "credit_notes": returns["credit_amount"], "debit_notes": returns["debit_amount"], "cash_movement": cash["net"], "bank_movement": bank["net"]}
        reconciliation = {"sales_net": sales["net"], "receipts_total": receipts["total"], "cash_movement": cash["net"], "bank_movement": bank["net"], "difference": "Not available from current stored data."}
        return {"date": day, "sales": sales, "purchases": purchase, "returns": returns, "receipts": receipts, "payments": payments, "cash": cash, "bank": bank, "stock": stock, "overall": overall, "reconciliation": reconciliation}

    @staticmethod
    def get_day_end_report(day: str) -> dict[str, Any]:
        return DayEndDAO.get_day_summary(day)

    @staticmethod
    def default_date() -> str:
        start, end = active_date_range(); today = datetime.now().strftime("%Y-%m-%d")
        return today if start <= today <= end else end
