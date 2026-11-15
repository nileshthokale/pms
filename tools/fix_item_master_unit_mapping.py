"""Fix item master unit mapping for items merged across distinct units.

Fixes the 3 items that have identical names but distinct units in Pharma-WINNER:
1. VITOMIN-Z:
   - Legacy 290: SYRUP (unit_id 30, pack_size 1) -> target ID 1234
   - Legacy 303: TABLET (unit_id 31, pack_size 10) -> new target item
2. POWERGESIC:
   - Legacy 51: TABLET (unit_id 31, pack_size 10) -> target ID 996
   - Legacy 920: GEL (unit_id 20, pack_size 1) -> new target item
3. CALTONVIT:
   - Legacy 681: TABLET (unit_id 31, pack_size 10) -> target ID 1624
   - Legacy 869: POWDER (unit_id 24, pack_size 1) -> new target item
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def fix_mapping(db_path: Path | str) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    cur.execute("BEGIN IMMEDIATE")

    # 1. VITOMIN-Z: Unmerge 303 (TABLET) from 1234 (SYRUP)
    cur.execute("SELECT * FROM items WHERE id = 1234")
    v_item = cur.fetchone()
    if not v_item:
        raise RuntimeError("Item 1234 not found")

    cur.execute("SELECT new_id FROM legacy_id_map WHERE entity = 'item' AND legacy_id = '303'")
    row_303 = cur.fetchone()
    if row_303 and row_303["new_id"] == 1234:
        print("Unmerging VITOMIN-Z (TABLET, legacy 303)...")
        # Insert TABLET item
        cur.execute(
            """INSERT INTO items (
                item_name, unit_id, company_id, category_id, pack_size,
                tax_structure, legacy_tax_id, discount, mrp, rate,
                reorder_stock_level, scheduled, location, pathy, dpco, opening_stock
            ) VALUES (
                'VITOMIN-Z', 31, ?, NULL, '10',
                '6', 6, 0.0, 0.0, 0.0,
                0, '1', '', 'ALLOPATHIC MEDICINES', 'N', 76.0
            )""",
            (v_item["company_id"],),
        )
        vitomin_tablet_id = cur.lastrowid

        # Update item 1234 (SYRUP) opening_stock
        cur.execute("UPDATE items SET opening_stock = 2.0 WHERE id = 1234")

        # Update legacy_id_map
        cur.execute(
            "UPDATE legacy_id_map SET new_id = ? WHERE entity = 'item' AND legacy_id = '303'",
            (vitomin_tablet_id,),
        )

        # Move TABLET batches (F4041 and FF5030)
        cur.execute(
            "UPDATE stock_batches SET item_id = ? WHERE id IN (7342, 466)",
            (vitomin_tablet_id,),
        )

        # Move purchase item 695
        cur.execute(
            "UPDATE purchase_invoice_items SET item_id = ? WHERE id = 695",
            (vitomin_tablet_id,),
        )

        # Move 9 sales items
        cur.execute(
            "UPDATE sales_invoice_items SET item_id = ? WHERE item_id = 1234 AND stock_batch_id IN (7342, 466)",
            (vitomin_tablet_id,),
        )

        # Move credit note item 80
        cur.execute(
            "UPDATE credit_note_items SET item_id = ? WHERE id = 80",
            (vitomin_tablet_id,),
        )

        # Update item_opening_balances
        cur.execute(
            "UPDATE item_opening_balances SET opening_stock = 2.0 WHERE item_id = 1234"
        )
        cur.execute(
            """INSERT INTO item_opening_balances (
                item_id, opening_date, opening_stock, source, notes, created_at
            ) VALUES (
                ?, '2015-04-01', 76.0, 'reconstructed_baseline',
                'Baseline stock reconstructed from batch on-hand stock and lifetime movements',
                '2026-10-22 10:24:22'
            )""",
            (vitomin_tablet_id,),
        )
        print(f"  VITOMIN-Z (TABLET) created with ID: {vitomin_tablet_id}")
    else:
        print("VITOMIN-Z TABLET already unmerged or not mapped to 1234.")

    # 2. POWERGESIC: Unmerge 920 (GEL) from 996 (TABLET)
    cur.execute("SELECT * FROM items WHERE id = 996")
    p_item = cur.fetchone()
    if not p_item:
        raise RuntimeError("Item 996 not found")

    cur.execute("SELECT new_id FROM legacy_id_map WHERE entity = 'item' AND legacy_id = '920'")
    row_920 = cur.fetchone()
    if row_920 and row_920["new_id"] == 996:
        print("Unmerging POWERGESIC (GEL, legacy 920)...")
        # Insert GEL item
        cur.execute(
            """INSERT INTO items (
                item_name, unit_id, company_id, category_id, pack_size,
                tax_structure, legacy_tax_id, discount, mrp, rate,
                reorder_stock_level, scheduled, location, pathy, dpco, opening_stock
            ) VALUES (
                'POWERGESIC', 20, ?, NULL, '1',
                '11', 11, 0.0, 0.0, 0.0,
                0, '1', '', 'ALLOPATHIC MEDICINES', 'N', 0.0
            )""",
            (p_item["company_id"],),
        )
        powergesic_gel_id = cur.lastrowid

        # Update legacy_id_map
        cur.execute(
            "UPDATE legacy_id_map SET new_id = ? WHERE entity = 'item' AND legacy_id = '920'",
            (powergesic_gel_id,),
        )

        # Move GEL batch 6702 (G8515)
        cur.execute(
            "UPDATE stock_batches SET item_id = ? WHERE id = 6702",
            (powergesic_gel_id,),
        )

        # Move purchase item for batch G8515
        cur.execute(
            "UPDATE purchase_invoice_items SET item_id = ? WHERE item_id = 996 AND batch_no = 'G8515'",
            (powergesic_gel_id,),
        )

        # Move sales items for batch G8515
        cur.execute(
            "UPDATE sales_invoice_items SET item_id = ? WHERE item_id = 996 AND batch_no = 'G8515'",
            (powergesic_gel_id,),
        )

        # Move ingredient 800 (drug 190)
        cur.execute(
            "UPDATE item_ingredients SET item_id = ? WHERE id = 800",
            (powergesic_gel_id,),
        )

        # Insert item_opening_balances
        cur.execute(
            """INSERT INTO item_opening_balances (
                item_id, opening_date, opening_stock, source, notes, created_at
            ) VALUES (
                ?, '2015-04-01', 0.0, 'reconstructed_baseline',
                'Baseline stock reconstructed from batch on-hand stock and lifetime movements',
                '2026-10-22 10:24:22'
            )""",
            (powergesic_gel_id,),
        )
        print(f"  POWERGESIC (GEL) created with ID: {powergesic_gel_id}")
    else:
        print("POWERGESIC GEL already unmerged or not mapped to 996.")

    # 3. CALTONVIT: Unmerge 869 (POWDER) from 1624 (TABLET)
    cur.execute("SELECT * FROM items WHERE id = 1624")
    c_item = cur.fetchone()
    if not c_item:
        raise RuntimeError("Item 1624 not found")

    cur.execute("SELECT new_id FROM legacy_id_map WHERE entity = 'item' AND legacy_id = '869'")
    row_869 = cur.fetchone()
    if row_869 and row_869["new_id"] == 1624:
        print("Unmerging CALTONVIT (POWDER, legacy 869)...")
        # Insert POWDER item
        cur.execute(
            """INSERT INTO items (
                item_name, unit_id, company_id, category_id, pack_size,
                tax_structure, legacy_tax_id, discount, mrp, rate,
                reorder_stock_level, scheduled, location, pathy, dpco, opening_stock
            ) VALUES (
                'CALTONVIT', 24, ?, NULL, '1',
                '13', 13, 0.0, 325.0, 0.0,
                0, '1', '', 'ALLOPATHIC MEDICINES', 'N', 0.0
            )""",
            (c_item["company_id"],),
        )
        caltonvit_powder_id = cur.lastrowid

        # Update legacy_id_map
        cur.execute(
            "UPDATE legacy_id_map SET new_id = ? WHERE entity = 'item' AND legacy_id = '869'",
            (caltonvit_powder_id,),
        )

        # Move POWDER batches
        cur.execute(
            "UPDATE stock_batches SET item_id = ? WHERE id IN (6174, 6091, 6995, 6773, 5934, 5864)",
            (caltonvit_powder_id,),
        )

        # Move purchase items
        cur.execute(
            "UPDATE purchase_invoice_items SET item_id = ? WHERE item_id = 1624 AND batch_no != 'FLT-0104'",
            (caltonvit_powder_id,),
        )

        # Move sales items
        cur.execute(
            "UPDATE sales_invoice_items SET item_id = ? WHERE item_id = 1624 AND batch_no != 'FLT-0104'",
            (caltonvit_powder_id,),
        )

        # Insert item_opening_balances
        cur.execute(
            """INSERT INTO item_opening_balances (
                item_id, opening_date, opening_stock, source, notes, created_at
            ) VALUES (
                ?, '2015-04-01', 0.0, 'reconstructed_baseline',
                'Baseline stock reconstructed from batch on-hand stock and lifetime movements',
                '2026-10-22 10:24:22'
            )""",
            (caltonvit_powder_id,),
        )
        print(f"  CALTONVIT (POWDER) created with ID: {caltonvit_powder_id}")
    else:
        print("CALTONVIT POWDER already unmerged or not mapped to 1624.")

    # Validation checks
    cur.execute("PRAGMA foreign_key_check")
    fk_errors = cur.fetchall()
    if fk_errors:
        raise RuntimeError(f"Foreign key violations: {[dict(e) for e in fk_errors]}")

    cur.execute("PRAGMA integrity_check")
    ic = [tuple(r) for r in cur.fetchall()]
    if ic != [("ok",)]:
        raise RuntimeError(f"Integrity check failed: {ic}")

    # Check that there are no merged items remaining in legacy_id_map
    cur.execute(
        "SELECT new_id, count(*), group_concat(legacy_id) FROM legacy_id_map WHERE entity = 'item' GROUP BY new_id HAVING count(*) > 1"
    )
    remaining_merged = cur.fetchall()
    if remaining_merged:
        raise RuntimeError(f"Remaining merged items in legacy_id_map: {[tuple(r) for r in remaining_merged]}")

    # Check total items count
    cur.execute("SELECT count(*) FROM items")
    total_items = cur.fetchone()[0]

    conn.commit()
    conn.close()

    print(f"\nMigration successful! Total items: {total_items}")
    return {"total_items": total_items, "fk_errors": len(fk_errors)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix item master unit mapping")
    parser.add_argument("--db", default=r"c:\Users\savan\OneDrive\Desktop\pms\data\pharmacy.db", help="Target SQLite DB")
    args = parser.parse_args()
    fix_mapping(args.db)
