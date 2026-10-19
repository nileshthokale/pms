"""Purchase Reports DAO.

Read-only data access for the 6 Crystal-Reports-style Purchase Reports:
1. Companywise Itemwise Purchase
2. Companywise Supplierwise Purchase
3. Supplierwise Itemwise Purchase (Invoice)
4. Supplierwise Itemwise Purchase (Challan)
5. Itemwise Purchase
6. Itemwise Batchwise Purchase

Strictly read-only; aggregates stored source transactions without altering
or recalculating ledger postings or stock.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from database.connection import get_connection


class PurchaseReportsDAO:
    """Read-only DAO for the 6 purchase report forms."""

    @staticmethod
    def get_filter_companies() -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT id, company_name, COALESCE(short_name, '') AS short_name
                FROM companies
                ORDER BY company_name COLLATE NOCASE ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_filter_suppliers() -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT id, supplier_name, COALESCE(address, '') AS address, COALESCE(city, '') AS city
                FROM suppliers
                ORDER BY supplier_name COLLATE NOCASE ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_filter_items() -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    i.id,
                    i.item_name,
                    COALESCE(u.unit_name, '') AS form,
                    COALESCE(c.short_name, '') AS company_code,
                    COALESCE(c.company_name, '') AS company_name
                FROM items i
                LEFT JOIN units u ON u.id = i.unit_id
                LEFT JOIN companies c ON c.id = i.company_id
                ORDER BY i.item_name COLLATE NOCASE ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_companywise_itemwise_purchase(
        from_date: str, to_date: str, company_id: int
    ) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    i.id AS item_id,
                    i.item_name AS item_name,
                    COALESCE(u.unit_name, '') AS form,
                    pi.voucher_no AS voucher_no,
                    pi.voucher_date AS voucher_date,
                    pi.purchase_type AS purchase_type,
                    COALESCE(pii.batch_no, '') AS batch_no,
                    COALESCE(pii.pack_size, '') AS pack_size,
                    COALESCE(pii.expiry, '') AS expiry,
                    COALESCE(pii.rate, 0.0) AS rate,
                    COALESCE(pii.pay_qty, 0.0) AS pay_qty,
                    COALESCE(pii.free_qty, 0.0) AS free_qty,
                    COALESCE(pii.amount, 0.0) AS amount
                FROM purchase_invoices pi
                JOIN purchase_invoice_items pii ON pii.purchase_invoice_id = pi.id
                JOIN items i ON i.id = pii.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                WHERE pi.voucher_date >= ? AND pi.voucher_date <= ?
                  AND i.company_id = ?
                ORDER BY i.item_name COLLATE NOCASE ASC, pi.voucher_date ASC, pi.voucher_no ASC, pi.id ASC, pii.id ASC
                """,
                (from_date, to_date, company_id),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_companywise_supplierwise_purchase(
        from_date: str, to_date: str, company_id: int
    ) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    s.id AS supplier_id,
                    s.supplier_name AS supplier_name,
                    COALESCE(s.address, '') AS address,
                    COALESCE(s.city, '') AS city,
                    SUM(COALESCE(pii.amount, 0.0)) AS amount
                FROM purchase_invoices pi
                JOIN purchase_invoice_items pii ON pii.purchase_invoice_id = pi.id
                JOIN items i ON i.id = pii.item_id
                JOIN suppliers s ON s.id = pi.supplier_id
                WHERE pi.voucher_date >= ? AND pi.voucher_date <= ?
                  AND i.company_id = ?
                GROUP BY s.id, s.supplier_name, s.address, s.city
                ORDER BY s.supplier_name COLLATE NOCASE ASC
                """,
                (from_date, to_date, company_id),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_supplierwise_itemwise_purchase(
        from_date: str, to_date: str, supplier_id: int, is_challan: bool = False
    ) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            if is_challan:
                type_filter = "LOWER(pi.purchase_type) = 'challan'"
            else:
                type_filter = "(pi.purchase_type IS NULL OR LOWER(pi.purchase_type) != 'challan')"

            cur = conn.execute(
                f"""
                SELECT
                    i.id AS item_id,
                    i.item_name AS item_name,
                    COALESCE(c.short_name, '') AS company_code,
                    pi.voucher_no AS voucher_no,
                    pi.voucher_date AS voucher_date,
                    COALESCE(pi.invoice_no, '') AS invoice_no,
                    COALESCE(pi.invoice_date, '') AS invoice_date,
                    pi.purchase_type AS purchase_type,
                    COALESCE(pii.batch_no, '') AS batch_no,
                    COALESCE(pii.pack_size, '') AS pack_size,
                    COALESCE(pii.expiry, '') AS expiry,
                    COALESCE(pii.rate, 0.0) AS rate,
                    COALESCE(pii.pay_qty, 0.0) AS pay_qty,
                    COALESCE(pii.free_qty, 0.0) AS free_qty,
                    COALESCE(pii.amount, 0.0) AS amount
                FROM purchase_invoices pi
                JOIN purchase_invoice_items pii ON pii.purchase_invoice_id = pi.id
                JOIN items i ON i.id = pii.item_id
                LEFT JOIN companies c ON c.id = i.company_id
                WHERE pi.voucher_date >= ? AND pi.voucher_date <= ?
                  AND pi.supplier_id = ?
                  AND {type_filter}
                ORDER BY i.item_name COLLATE NOCASE ASC, pi.voucher_date ASC, pi.voucher_no ASC, pi.id ASC, pii.id ASC
                """,
                (from_date, to_date, supplier_id),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_itemwise_purchase(
        from_date: str, to_date: str, item_id: int
    ) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    COALESCE(pi.invoice_no, '') AS invoice_no,
                    pi.purchase_type AS purchase_type,
                    pi.voucher_no AS voucher_no,
                    pi.voucher_date AS voucher_date,
                    COALESCE(s.supplier_name, '') AS supplier_name,
                    COALESCE(pii.batch_no, '') AS batch_no,
                    COALESCE(pii.rate, 0.0) AS rate,
                    COALESCE(pii.pay_qty, 0.0) AS pay_qty,
                    COALESCE(pii.free_qty, 0.0) AS free_qty,
                    COALESCE(pii.amount, 0.0) AS amount
                FROM purchase_invoices pi
                JOIN purchase_invoice_items pii ON pii.purchase_invoice_id = pi.id
                LEFT JOIN suppliers s ON s.id = pi.supplier_id
                WHERE pi.voucher_date >= ? AND pi.voucher_date <= ?
                  AND pii.item_id = ?
                ORDER BY pi.voucher_date ASC, pi.voucher_no ASC, pi.id ASC, pii.id ASC
                """,
                (from_date, to_date, item_id),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_itemwise_batchwise_purchase(
        from_date: str, to_date: str, item_id: int
    ) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    COALESCE(pi.invoice_no, '') AS invoice_no,
                    pi.purchase_type AS purchase_type,
                    pi.voucher_no AS voucher_no,
                    pi.voucher_date AS voucher_date,
                    COALESCE(s.supplier_name, '') AS supplier_name,
                    COALESCE(pii.batch_no, '') AS batch_no,
                    COALESCE(pii.rate, 0.0) AS rate,
                    COALESCE(pii.pay_qty, 0.0) AS pay_qty,
                    COALESCE(pii.free_qty, 0.0) AS free_qty,
                    COALESCE(pii.amount, 0.0) AS amount
                FROM purchase_invoices pi
                JOIN purchase_invoice_items pii ON pii.purchase_invoice_id = pi.id
                LEFT JOIN suppliers s ON s.id = pi.supplier_id
                WHERE pi.voucher_date >= ? AND pi.voucher_date <= ?
                  AND pii.item_id = ?
                ORDER BY pii.batch_no COLLATE NOCASE ASC, pi.voucher_date ASC, pi.voucher_no ASC, pi.id ASC, pii.id ASC
                """,
                (from_date, to_date, item_id),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
