from database.connection import get_connection


class ItemDAO:
    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT
                    i.id,
                    i.item_name,
                    COALESCE(generic_names.generic_name, '') AS generic_name,
                    i.unit_id,
                    u.unit_name,
                    i.company_id,
                    c.company_name,
                    i.category_id,
                    cat.category_name,
                    i.pack_size,
                    i.tax_structure,
                    i.discount,
                    i.mrp,
                    i.rate,
                    i.reorder_stock_level,
                    i.scheduled,
                    i.location,
                    i.pathy,
                    i.dpco
                FROM items i
                LEFT JOIN units u ON i.unit_id = u.id
                LEFT JOIN companies c ON i.company_id = c.id
                LEFT JOIN categories cat ON i.category_id = cat.id
                LEFT JOIN (
                    SELECT ii.item_id, GROUP_CONCAT(DISTINCT d.drug_name) AS generic_name
                    FROM item_ingredients ii
                    JOIN drugs d ON d.id = ii.drug_id
                    GROUP BY ii.item_id
                ) generic_names ON generic_names.item_id = i.id
                ORDER BY i.item_name"""
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(item_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT
                    i.id,
                    i.item_name,
                    i.unit_id,
                    u.unit_name,
                    i.company_id,
                    c.company_name,
                    i.category_id,
                    cat.category_name,
                    i.pack_size,
                    i.tax_structure,
                    i.discount,
                    i.mrp,
                    i.rate,
                    i.reorder_stock_level,
                    i.scheduled,
                    i.location,
                    i.pathy,
                    i.dpco
                FROM items i
                LEFT JOIN units u ON i.unit_id = u.id
                LEFT JOIN companies c ON i.company_id = c.id
                LEFT JOIN categories cat ON i.category_id = cat.id
                WHERE i.id = ?""",
                (item_id,),
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
                    "SELECT 1 FROM items WHERE item_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM items WHERE item_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def search(name: str, category_id: int | None = None) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT
                    i.id,
                    i.item_name,
                    i.unit_id,
                    u.unit_name,
                    i.company_id,
                    c.company_name,
                    i.category_id,
                    cat.category_name,
                    i.pack_size,
                    i.tax_structure,
                    i.discount,
                    i.mrp,
                    i.rate,
                    i.reorder_stock_level,
                    i.scheduled,
                    i.location,
                    i.pathy,
                    i.dpco
                FROM items i
                LEFT JOIN units u ON i.unit_id = u.id
                LEFT JOIN companies c ON i.company_id = c.id
                LEFT JOIN categories cat ON i.category_id = cat.id
                WHERE i.item_name LIKE ?
                AND (? IS NULL OR i.category_id = ?)
                ORDER BY i.item_name""",
                (f"%{name}%", category_id, category_id),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def insert(
        item_name: str,
        unit_id: int | None = None,
        company_id: int | None = None,
        pack_size: str = "",
        tax_structure: str = "",
        discount: float = 0.0,
        mrp: float = 0.0,
        rate: float = 0.0,
        reorder_stock_level: int = 0,
        scheduled: str = "",
        location: str = "",
        pathy: str = "",
        dpco: str = "",
        category_id: int | None = None,
    ) -> int:
        conn = get_connection()
        try:
            ItemDAO._validate_category_assignment(conn, category_id)
            cursor = conn.execute(
                """INSERT INTO items (
                    item_name, unit_id, company_id, category_id, pack_size,
                    tax_structure, discount, mrp, rate,
                    reorder_stock_level, scheduled, location, pathy, dpco
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_name, unit_id, company_id, category_id, pack_size,
                    tax_structure, discount, mrp, rate,
                    reorder_stock_level, scheduled, location, pathy, dpco,
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def update(
        item_id: int,
        item_name: str,
        unit_id: int | None = None,
        company_id: int | None = None,
        pack_size: str = "",
        tax_structure: str = "",
        discount: float = 0.0,
        mrp: float = 0.0,
        rate: float = 0.0,
        reorder_stock_level: int = 0,
        scheduled: str = "",
        location: str = "",
        pathy: str = "",
        dpco: str = "",
        category_id: int | None = None,
    ) -> None:
        conn = get_connection()
        try:
            existing = conn.execute("SELECT category_id FROM items WHERE id = ?", (item_id,)).fetchone()
            if not existing:
                raise ValueError("Item not found.")
            ItemDAO._validate_category_assignment(conn, category_id, existing["category_id"])
            conn.execute(
                """UPDATE items SET
                    item_name = ?,
                    unit_id = ?,
                    company_id = ?,
                    category_id = ?,
                    pack_size = ?,
                    tax_structure = ?,
                    discount = ?,
                    mrp = ?,
                    rate = ?,
                    reorder_stock_level = ?,
                    scheduled = ?,
                    location = ?,
                    pathy = ?,
                    dpco = ?
                WHERE id = ?""",
                (
                    item_name, unit_id, company_id, category_id, pack_size,
                    tax_structure, discount, mrp, rate,
                    reorder_stock_level, scheduled, location, pathy, dpco,
                    item_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _validate_category_assignment(conn, category_id: int | None, existing_category_id: int | None = None) -> None:
        """Allow blank categories and preserve an existing inactive selection.

        New items can only select active categories.  An item already linked to
        a category remains editable after that category is deactivated, but it
        cannot be changed to a different inactive category.
        """
        if category_id is None:
            return
        category = conn.execute("SELECT is_active FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not category:
            raise ValueError("Selected category does not exist.")
        if not category["is_active"] and category_id != existing_category_id:
            raise ValueError("Inactive categories cannot be selected for a new item.")

    @staticmethod
    def get_ingredients(item_id: int) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT
                    ii.id,
                    ii.item_id,
                    ii.drug_id,
                    d.drug_name,
                    ii.power
                FROM item_ingredients ii
                LEFT JOIN drugs d ON ii.drug_id = d.id
                WHERE ii.item_id = ?
                ORDER BY ii.id""",
                (item_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def save_ingredients(item_id: int, ingredients: list[dict]) -> None:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM item_ingredients WHERE item_id = ?", (item_id,))
            for ing in ingredients:
                conn.execute(
                    "INSERT INTO item_ingredients (item_id, drug_id, power) VALUES (?, ?, ?)",
                    (item_id, ing["drug_id"], ing["power"]),
                )
            conn.commit()
        finally:
            conn.close()
