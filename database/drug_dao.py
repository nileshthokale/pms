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
    def _enrich_items_with_batches(conn, items: list[dict]) -> list[dict]:
        from database.sales_dao import SalesDAO

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

    @staticmethod
    def get_substitutes(drug_id: int) -> list[dict]:
        """Fetch all items containing the specified drug/ingredient from Item Master.

        Uses the actual Counter Sale MRP source: saleable stock batches
        (stock_qty > 0 and not expired). If available batches have differing
        MRPs, identifies the variation so the UI can show the varying MRPs
        rather than an arbitrary legacy Item Master price.
        """
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
            return DrugDAO._enrich_items_with_batches(conn, items)
        finally:
            conn.close()

    @staticmethod
    def search_substitutes(search_text: str) -> list[dict]:
        """Search substitute items by entered letters (matching drug names and item names)."""
        term = (search_text or "").strip()
        if not term:
            return []

        conn = get_connection()
        try:
            pattern = f"%{term}%"
            cur = conn.execute(
                """
                SELECT DISTINCT
                    i.id AS item_id,
                    i.item_name,
                    COALESCE(u.unit_name, '') AS unit_name,
                    i.pack_size,
                    COALESCE(i.mrp, 0.0) AS master_mrp
                FROM items i
                LEFT JOIN units u ON u.id = i.unit_id
                LEFT JOIN item_ingredients ii ON ii.item_id = i.id
                LEFT JOIN drugs d ON d.id = ii.drug_id
                WHERE d.drug_name LIKE ?
                   OR i.item_name LIKE ?
                   OR ii.drug_id IN (
                       SELECT ii2.drug_id
                       FROM item_ingredients ii2
                       JOIN items i2 ON i2.id = ii2.item_id
                       WHERE i2.item_name LIKE ?
                   )
                ORDER BY i.item_name
                """,
                (pattern, pattern, pattern),
            )
            items = [dict(r) for r in cur.fetchall()]
            return DrugDAO._enrich_items_with_batches(conn, items)
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

    @staticmethod
    def search_suggestions(query: str, limit: int = 20) -> list[dict]:
        """Search matching drugs and medicine item names for dropdown suggestions."""
        term = (query or "").strip()
        if not term:
            return []

        pattern = f"%{term}%"
        conn = get_connection()
        try:
            results = []
            seen_names = set()

            # 1. Matching drugs from drugs table
            drug_rows = conn.execute(
                """
                SELECT id, drug_name
                FROM drugs
                WHERE drug_name LIKE ?
                ORDER BY drug_name
                LIMIT ?
                """,
                (pattern, limit),
            ).fetchall()

            for r in drug_rows:
                name = r["drug_name"]
                if name.upper() not in seen_names:
                    seen_names.add(name.upper())
                    results.append({
                        "id": r["id"],
                        "name": name,
                        "kind": "drug",
                    })

            # 2. Matching medicine items from items table
            rem = limit - len(results)
            if rem > 0:
                item_rows = conn.execute(
                    """
                    SELECT id, item_name
                    FROM items
                    WHERE item_name LIKE ?
                    ORDER BY item_name
                    LIMIT ?
                    """,
                    (pattern, rem),
                ).fetchall()

                for r in item_rows:
                    name = r["item_name"]
                    if name.upper() not in seen_names:
                        seen_names.add(name.upper())
                        results.append({
                            "id": r["id"],
                            "name": name,
                            "kind": "item",
                        })

            return results
        finally:
            conn.close()

