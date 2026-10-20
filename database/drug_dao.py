from __future__ import annotations

from database.connection import get_connection


class DrugDAO:
    """Data access object for the drugs table."""

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, drug_name FROM drugs ORDER BY drug_name"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(drug_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, drug_name FROM drugs WHERE id = ?",
                (drug_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def name_exists(name: str, exclude_id: int | None = None) -> bool:
        conn = get_connection()
        try:
            if exclude_id is not None:
                row = conn.execute(
                    "SELECT 1 FROM drugs WHERE drug_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM drugs WHERE drug_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def insert(drug_name: str) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO drugs (drug_name) VALUES (?)",
                (drug_name,),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def update(drug_id: int, drug_name: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE drugs SET drug_name = ? WHERE id = ?",
                (drug_name, drug_id),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_substitutes(drug_id: int) -> list[dict]:
        """Fetch all items containing the specified drug/ingredient from Item Master.

        Uses the actual Counter Sale MRP source: saleable stock batches
        (stock_qty > 0 and not expired). If available batches have differing
        MRPs, identifies the variation so the UI can show the varying MRPs
        rather than an arbitrary legacy Item Master price.
        """
        from database.sales_dao import SalesDAO

        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT DISTINCT
                    i.id AS item_id,
                    i.item_name,
                    COALESCE(u.unit_name, '') AS unit_name,
                    i.pack_size,
                    COALESCE(i.mrp, 0.0) AS master_mrp
                FROM item_ingredients ii
                JOIN items i ON i.id = ii.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                WHERE ii.drug_id = ?
                ORDER BY i.item_name
                """,
                (drug_id,),
            )
            items = [dict(r) for r in cur.fetchall()]

            results = []
            for it in items:
                item_id = it["item_id"]
                batch_rows = conn.execute(
                    """
                    SELECT id, batch_no, expiry, mrp, stock_qty
                    FROM stock_batches
                    WHERE item_id = ? AND stock_qty > 0
                    ORDER BY expiry, batch_no
                    """,
                    (item_id,),
                ).fetchall()

                saleable = [
                    dict(b) for b in batch_rows
                    if not SalesDAO.is_expired(b["expiry"] or "")
                ]
                saleable.sort(
                    key=lambda b: (b.get("expiry") or "", b.get("batch_no") or "")
                )

                available_mrps = [
                    float(b["mrp"]) for b in saleable
                    if b.get("mrp") is not None and float(b["mrp"]) > 0
                ]

                if available_mrps:
                    min_mrp = min(available_mrps)
                    max_mrp = max(available_mrps)
                    fefo_mrp = float(saleable[0]["mrp"])
                    has_variation = (min_mrp != max_mrp)
                else:
                    # Fallback when no active stock: look at latest recorded batch
                    last_batch = conn.execute(
                        """
                        SELECT mrp FROM stock_batches
                        WHERE item_id = ? AND mrp > 0
                        ORDER BY expiry DESC, id DESC LIMIT 1
                        """,
                        (item_id,),
                    ).fetchone()
                    if last_batch and last_batch[0]:
                        fallback_mrp = float(last_batch[0])
                    else:
                        fallback_mrp = float(it["master_mrp"] or 0.0)
                    min_mrp = fallback_mrp
                    max_mrp = fallback_mrp
                    fefo_mrp = fallback_mrp
                    has_variation = False

                it["mrp"] = min_mrp
                it["min_mrp"] = min_mrp
                it["max_mrp"] = max_mrp
                it["fefo_mrp"] = fefo_mrp
                it["has_variation"] = has_variation
                it["saleable_batches"] = saleable
                results.append(it)

            return results
        finally:
            conn.close()

    @staticmethod
    def get_drugs_for_item(item_id: int) -> list[dict]:
        """Fetch all drugs linked to an item via item_ingredients."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT d.id, d.drug_name
                FROM item_ingredients ii
                JOIN drugs d ON d.id = ii.drug_id
                WHERE ii.item_id = ?
                ORDER BY d.drug_name
                """,
                (item_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

