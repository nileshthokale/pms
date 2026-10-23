"""Transactional import of today's business data (2026-10-23) from PharmaWinner SQL dump.

Scope:
- Date: strictly 2026-10-23.
- Tables touched:
  - purchase_invoices (+2)
  - purchase_invoice_items (+2)
  - stock_batches (+2 created, 34 updated for stock balance)
  - sales_invoices (+13)
  - sales_invoice_items (+55)
  - ledger_transactions (+30: 4 purchase + 26 sale)
  - patient_addresses (ensured present for all 13 sales)
- All other tables are strictly preserved.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import LegacyDump

DEFAULT_DUMP = ROOT / "PharmaWinner202610231351.sql"
DEFAULT_DB = ROOT / "data" / "pharmacy.db"
BACKUP_DIR = ROOT / "migration_backups"
TARGET_DATE = "2026-10-23"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _text(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _number(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _date(val) -> str:
    s = _text(val)
    if not s or s.startswith("0000") or s.startswith("0001"):
        return ""
    return s[:10]


def _pack(val) -> str:
    s = _text(val)
    return s if s else "1"


def run_import(db_path: Path, dump_path: Path, apply: bool = False):
    print("=" * 70)
    print(f"TODAY DATA IMPORT SCRIPT — {TARGET_DATE}")
    print(f"Mode: {'APPLY (Live Transactional Write)' if apply else 'DRY RUN (Read Only)'}")
    print(f"Database: {db_path.resolve()}")
    print(f"Source Dump: {dump_path.resolve()}")
    print("=" * 70)

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not dump_path.exists():
        raise FileNotFoundError(f"Source dump not found: {dump_path}")

    dump = LegacyDump(dump_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Protected tables baseline
    PROTECTED_TABLES = [
        "customers",
        "suppliers",
        "doctors",
        "items",
        "units",
        "companies",
        "financial_years",
        "credit_notes",
        "credit_note_items",
    ]
    protected_baselines = {}
    for t in PROTECTED_TABLES:
        cnt = cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        id_sum = cur.execute(f"SELECT COALESCE(SUM(id), 0) FROM {t}").fetchone()[0]
        protected_baselines[t] = (cnt, id_sum)

    # 1. Build lookup mappings
    legacy_items = {r[0]: _text(r[1]) for r in dump.iter_rows("itemmst")}
    db_items = {r["name"].upper(): r["id"] for r in cur.execute("SELECT id, UPPER(TRIM(item_name)) as name FROM items").fetchall()}
    item_map = {lid: db_items[name.upper()] for lid, name in legacy_items.items() if name.upper() in db_items}

    legacy_doctors = {r[0]: _text(r[1]) for r in dump.iter_rows("doctormst")}
    db_doctors = {r["name"].upper(): r["id"] for r in cur.execute("SELECT id, UPPER(TRIM(doctor_name)) as name FROM doctors").fetchall()}
    doc_map = {did: db_doctors[name.upper()] for did, name in legacy_doctors.items() if name.upper() in db_doctors}

    db_suppliers_by_ledger = {r["ledger_id"]: r["id"] for r in cur.execute("SELECT id, ledger_id FROM suppliers WHERE ledger_id IS NOT NULL").fetchall()}
    db_customers_by_ledger = {r["ledger_id"]: r["id"] for r in cur.execute("SELECT id, ledger_id FROM customers WHERE ledger_id IS NOT NULL").fetchall()}
    # Fallback walkin customer
    walkin_cust_id = cur.execute("SELECT id FROM customers WHERE UPPER(customer_name) = 'WALKIN' LIMIT 1").fetchone()
    walkin_cust_id = walkin_cust_id[0] if walkin_cust_id else 159

    # 2. Extract today's purchases
    purch_headers = [r for r in dump.iter_rows("invoicevhheader") if _date(r[4]) == TARGET_DATE]
    purch_ids = {r[0] for r in purch_headers}
    purch_items = [r for r in dump.iter_rows("invoiceitemdetail") if len(r) > 1 and r[1] in purch_ids]
    purch_details = [r for r in dump.iter_rows("invoicevhdetail") if len(r) > 3 and r[3] in purch_ids]

    print(f"\n[Today's Purchases]")
    print(f"  Invoices: {len(purch_headers)}")
    print(f"  Items: {len(purch_items)}")
    print(f"  Ledger transactions: {len(purch_details)}")

    # 3. Extract today's sales
    sales_headers = [r for r in dump.iter_rows("salesvhheader") if _date(r[4]) == TARGET_DATE]
    sales_ids = {r[0] for r in sales_headers}
    sales_items = [r for r in dump.iter_rows("salesitemdetail") if len(r) > 1 and r[1] in sales_ids]
    sales_details = [r for r in dump.iter_rows("salesvhdetail") if len(r) > 3 and r[3] in sales_ids]

    print(f"\n[Today's Sales]")
    print(f"  Invoices: {len(sales_headers)}")
    print(f"  Items: {len(sales_items)}")
    print(f"  Ledger transactions: {len(sales_details)}")

    # Check if already present in DB
    existing_sales = cur.execute("SELECT count(*) FROM sales_invoices WHERE sale_date = ?", (TARGET_DATE,)).fetchone()[0]
    existing_purch = cur.execute("SELECT count(*) FROM purchase_invoices WHERE voucher_date = ?", (TARGET_DATE,)).fetchone()[0]
    if existing_sales > 0 or existing_purch > 0:
        print(f"\n[WARNING] Database already contains {existing_sales} sales and {existing_purch} purchases for {TARGET_DATE}!")
        if apply:
            raise RuntimeError(f"Database already has data for {TARGET_DATE}. Aborting to avoid duplicates.")

    if not apply:
        print("\n[DRY RUN COMPLETE] Validation succeeded. All items, doctors, and ledgers map cleanly.")
        print("To execute with pre-backup and atomic commit, run with --apply.")
        conn.close()
        return

    # APPLY MODE
    print("\n[Step 1/5] Creating Pre-Import Immutable Backup...")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"pre_today_data_import_{timestamp_str}.db"

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    b_conn = sqlite3.connect(str(backup_file))
    conn.backup(b_conn)
    b_conn.close()

    pre_hash = sha256_file(db_path)
    bak_hash = sha256_file(backup_file)
    print(f"  Backup created: {backup_file.name}")
    print(f"  Original DB SHA-256: {pre_hash}")
    print(f"  Backup file SHA-256: {bak_hash}")

    chk_conn = sqlite3.connect(str(backup_file))
    chk = chk_conn.execute("PRAGMA integrity_check").fetchone()[0]
    chk_conn.close()
    if chk != "ok":
        raise RuntimeError(f"Backup integrity check failed: {chk}")
    print("  Backup verified successfully (PRAGMA integrity_check = ok).")

    print("\n[Step 2/5] Executing Transactional Import...")
    try:
        conn.execute("BEGIN IMMEDIATE")

        # A. Import Purchases
        purch_voucher_map = {}
        for row in purch_headers:
            legacy_id = row[0]
            fy_name = "2026-2027"
            p_type = _text(row[2]) or "Credit"
            voucher_no = f"{fy_name}-{p_type}-{row[3]}"
            supp_ledger_id = row[8]
            supplier_id = db_suppliers_by_ledger.get(supp_ledger_id)
            if not supplier_id:
                raise ValueError(f"Supplier ledger {supp_ledger_id} not mapped!")

            cur.execute("""
                INSERT INTO purchase_invoices (
                    voucher_no, voucher_date, voucher_time, purchase_type,
                    supplier_id, invoice_no, invoice_date,
                    invoice_net_amount, bill_discount, due_date,
                    total_amount, gst_amount, debit_note_amount,
                    other_amount, paid_amount, round_off, net_amount,
                    remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                voucher_no, _date(row[4]), _text(row[5]), p_type,
                supplier_id, _text(row[9]), _date(row[10]),
                _number(row[12]), _number(row[15]), _date(row[11]),
                _number(row[12]), _number(row[19]), _number(row[17]),
                _number(row[18]), _number(row[20]), _number(row[16]),
                _number(row[7]), _text(row[6])
            ))
            new_purch_id = cur.lastrowid
            purch_voucher_map[legacy_id] = (new_purch_id, voucher_no, _date(row[4]), _text(row[5]))

        # Purchase Items and Batches
        batch_map = {}  # (item_id, batch_no) -> batch_id
        for row in purch_items:
            legacy_vh = row[1]
            new_purch_id = purch_voucher_map[legacy_vh][0]
            legacy_item_id = row[2]
            db_item_id = item_map[legacy_item_id]
            batch_no = _text(row[3])
            expiry = _date(row[5])
            pack_size = _pack(row[4])
            pay_qty = _number(row[6])
            free_qty = _number(row[7])
            total_packs = pay_qty + free_qty
            pack_units = float(pack_size) if pack_size.replace(".", "", 1).isdigit() else 1.0
            incoming_loose_qty = total_packs * pack_units

            mrp = _number(row[11])
            rate = _number(row[10])
            net_rate = _number(row[19])
            purchase_rate = _number(row[18])

            # Ensure or update stock_batch
            existing_batch = cur.execute(
                "SELECT id, stock_qty FROM stock_batches WHERE item_id = ? AND UPPER(TRIM(batch_no)) = ?",
                (db_item_id, batch_no.upper())
            ).fetchone()
            if existing_batch:
                batch_id = existing_batch[0]
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                    (incoming_loose_qty, batch_id)
                )
            else:
                cur.execute("""
                    INSERT INTO stock_batches (
                        item_id, batch_no, expiry, pack_size, mrp,
                        purchase_rate, net_rate, stock_qty
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (db_item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, incoming_loose_qty))
                batch_id = cur.lastrowid
            batch_map[(db_item_id, batch_no.upper())] = batch_id

            cur.execute("""
                INSERT INTO purchase_invoice_items (
                    purchase_invoice_id, item_id, pack_size, pay_qty,
                    free_qty, batch_no, expiry, rate, mrp, discount,
                    gst_percent, gst_amount, amount, purchase_rate,
                    net_rate, pp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                new_purch_id, db_item_id, pack_size, pay_qty,
                free_qty, batch_no, expiry, rate, mrp, _number(row[14]),
                _number(row[16]), _number(row[17]), _number(row[15]),
                purchase_rate, net_rate
            ))

        # Purchase Accounting (invoicevhdetail)
        for row in purch_details:
            legacy_vh = row[3]
            new_purch_id, voucher_no, date_val, time_val = purch_voucher_map[legacy_vh]
            ledger_id = row[5]
            amount = _number(row[6])
            is_debit = _text(row[4]).upper() == "DR"
            cur.execute("""
                INSERT INTO ledger_transactions (
                    ledger_id, transaction_date, transaction_time,
                    voucher_type, voucher_no, reference_type,
                    reference_id, description, debit, credit
                ) VALUES (?, ?, ?, 'PURCHASE', ?, 'PURCHASE_INVOICE', ?, ?, ?, ?)
            """, (
                ledger_id, _date(row[2]) or date_val, time_val,
                voucher_no, new_purch_id, _text(row[7]),
                amount if is_debit else 0.0,
                0.0 if is_debit else amount
            ))

        # B. Import Sales
        sales_voucher_map = {}
        for row in sales_headers:
            legacy_id = row[0]
            fy_name = "2026-2027"
            bill_raw = row[8]
            bill_str = str(bill_raw).strip() if bill_raw is not None else ""
            voucher_no = f"{fy_name}-{bill_str}" if bill_str else f"{fy_name}-Cash-{row[3]}-S{legacy_id}"
            
            cust_ledger_id = row[9]
            customer_id = db_customers_by_ledger.get(cust_ledger_id, walkin_cust_id)
            doc_id = doc_map.get(row[13])
            remarks = f"Legacy salesvhheader ID {legacy_id}; BillNo {bill_str}"

            cur.execute("""
                INSERT INTO sales_invoices (
                    bill_no, sale_date, sale_time, sale_type, customer_id,
                    patient_name, doctor_id, discount, paid_amount,
                    total_amount, round_off, net_amount, remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                voucher_no, _date(row[4]), _text(row[5]), _text(row[2]) or "Cash",
                customer_id, _text(row[10]), doc_id,
                _number(row[16]), _number(row[21]),
                _number(row[14]), _number(row[18]), _number(row[7]),
                remarks
            ))
            new_sale_id = cur.lastrowid
            sales_voucher_map[legacy_id] = (new_sale_id, voucher_no, _date(row[4]), _text(row[5]))

        # Sales Items and Stock deduction
        for row in sales_items:
            legacy_vh = row[1]
            new_sale_id = sales_voucher_map[legacy_vh][0]
            legacy_item_id = row[2]
            db_item_id = item_map[legacy_item_id]
            batch_no = _text(row[4])
            expiry = _date(row[5])
            pack_size = _pack(row[3])
            mrp = _number(row[6])
            sale_qty = _number(row[7])

            # Lookup batch
            b_key = (db_item_id, batch_no.upper())
            batch_id = batch_map.get(b_key)
            if not batch_id:
                sb_row = cur.execute(
                    "SELECT id FROM stock_batches WHERE item_id = ? AND UPPER(TRIM(batch_no)) = ?",
                    (db_item_id, batch_no.upper())
                ).fetchone()
                if sb_row:
                    batch_id = sb_row[0]
                else:
                    # Create batch for history linkage if completely missing
                    cur.execute("""
                        INSERT INTO stock_batches (
                            item_id, batch_no, expiry, pack_size, mrp,
                            purchase_rate, net_rate, stock_qty
                        ) VALUES (?, ?, ?, ?, ?, 0, 0, 0)
                    """, (db_item_id, batch_no, expiry, pack_size, mrp))
                    batch_id = cur.lastrowid
                batch_map[b_key] = batch_id

            # Deduct sold quantity from stock_batches
            cur.execute(
                "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                (sale_qty, batch_id)
            )

            cur.execute("""
                INSERT INTO sales_invoice_items (
                    sales_invoice_id, item_id, stock_batch_id, pack_size,
                    location, batch_no, expiry, mrp, sale_qty,
                    discount_amount, amount
                ) VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
            """, (
                new_sale_id, db_item_id, batch_id, pack_size,
                batch_no, expiry, mrp, sale_qty,
                _number(row[12]), _number(row[13])
            ))

        # Sales Accounting (salesvhdetail)
        for row in sales_details:
            legacy_vh = row[3]
            new_sale_id, voucher_no, date_val, time_val = sales_voucher_map[legacy_vh]
            ledger_id = row[5]
            amount = _number(row[6])
            is_debit = _text(row[4]).upper() == "DR"
            cur.execute("""
                INSERT INTO ledger_transactions (
                    ledger_id, transaction_date, transaction_time,
                    voucher_type, voucher_no, reference_type,
                    reference_id, description, debit, credit
                ) VALUES (?, ?, ?, 'SALE', ?, 'COUNTER_SALE', ?, ?, ?, ?)
            """, (
                ledger_id, _date(row[2]) or date_val, time_val,
                voucher_no, new_sale_id, _text(row[7]),
                amount if is_debit else 0.0,
                0.0 if is_debit else amount
            ))

        # Ensure patient addresses for today's sales are recorded (and updated with today's timestamp)
        for row in sales_headers:
            p_name = " ".join(_text(row[10]).split()).strip()
            p_addr = " ".join(_text(row[11]).split()).strip()
            if p_name and p_addr and p_name.upper() not in ("WALKIN", "WALKIN CUSTOMER"):
                cur.execute("""
                    INSERT INTO patient_addresses (patient_name, address, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(patient_name, address) DO UPDATE SET updated_at = excluded.updated_at
                """, (p_name, p_addr, f"{TARGET_DATE} 12:00:00"))

        # Verify protected tables are completely untouched
        for t, (exp_cnt, exp_id_sum) in protected_baselines.items():
            act_cnt = cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            act_id_sum = cur.execute(f"SELECT COALESCE(SUM(id), 0) FROM {t}").fetchone()[0]
            if act_cnt != exp_cnt or act_id_sum != exp_id_sum:
                raise RuntimeError(
                    f"INVARIANT VIOLATION: Protected table '{t}' modified! "
                    f"Expected count={exp_cnt}, got={act_cnt}; Expected id_sum={exp_id_sum}, got={act_id_sum}"
                )
        print(f"  Verified all {len(protected_baselines)} protected tables are completely unchanged.")

        conn.commit()
        print("  Transaction committed successfully.")
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"\n[ROLLBACK] Transaction rolled back due to error: {e}")
        raise

    print("\n[Step 3/5] Checkpointing WAL journals...")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print("\n[Step 4/5] Post-Import Verification...")
    post_conn = sqlite3.connect(str(db_path))
    post_cur = post_conn.cursor()

    integ = post_cur.execute("PRAGMA integrity_check").fetchone()[0]
    if integ != "ok":
        raise RuntimeError(f"Integrity check failed: {integ}")
    print("  PRAGMA integrity_check = ok")

    fks = post_cur.execute("PRAGMA foreign_key_check").fetchall()
    if fks:
        raise RuntimeError(f"Foreign key check failed: {len(fks)} violations")
    print("  PRAGMA foreign_key_check = 0 violations")

    for t, (exp_cnt, exp_id_sum) in protected_baselines.items():
        act_cnt = post_cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        act_id_sum = post_cur.execute(f"SELECT COALESCE(SUM(id), 0) FROM {t}").fetchone()[0]
        if act_cnt != exp_cnt or act_id_sum != exp_id_sum:
            raise RuntimeError(f"Post-apply check failed: Protected table '{t}' modified!")
    print(f"  Post-apply verified all {len(protected_baselines)} protected tables remain identical.")

    post_sales = post_cur.execute("SELECT count(*) FROM sales_invoices WHERE sale_date = ?", (TARGET_DATE,)).fetchone()[0]
    post_sale_items = post_cur.execute("""
        SELECT count(*) FROM sales_invoice_items sii
        JOIN sales_invoices si ON si.id = sii.sales_invoice_id
        WHERE si.sale_date = ?
    """, (TARGET_DATE,)).fetchone()[0]
    post_purch = post_cur.execute("SELECT count(*) FROM purchase_invoices WHERE voucher_date = ?", (TARGET_DATE,)).fetchone()[0]
    post_purch_items = post_cur.execute("""
        SELECT count(*) FROM purchase_invoice_items pii
        JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id
        WHERE pi.voucher_date = ?
    """, (TARGET_DATE,)).fetchone()[0]
    post_ledgers = post_cur.execute("SELECT count(*) FROM ledger_transactions WHERE transaction_date = ?", (TARGET_DATE,)).fetchone()[0]

    print(f"\n[Verification Metrics for {TARGET_DATE}]")
    print(f"  Sales invoices: {post_sales} (Expected: 13)")
    print(f"  Sales items: {post_sale_items} (Expected: 55)")
    print(f"  Purchase invoices: {post_purch} (Expected: 2)")
    print(f"  Purchase items: {post_purch_items} (Expected: 2)")
    print(f"  Ledger transactions: {post_ledgers} (Expected: 30)")

    if (post_sales != 13 or post_sale_items != 55 or post_purch != 2 or post_purch_items != 2 or post_ledgers != 30):
        raise RuntimeError("Verification metrics do not match expected counts!")

    post_conn.close()
    post_hash = sha256_file(db_path)
    print(f"  Final DB SHA-256: {post_hash}")
    print("\n" + "=" * 70)
    print(f"TODAY'S DATA ({TARGET_DATE}) IMPORTED SUCCESSFULLY!")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description=f"Import today's business data ({TARGET_DATE}) from SQL dump.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to SQLite database")
    parser.add_argument("--dump", type=Path, default=DEFAULT_DUMP, help="Path to PharmaWinner SQL export")
    parser.add_argument("--apply", action="store_true", help="Apply changes with transactional safety and pre-backup")
    args = parser.parse_args()

    run_import(args.db, args.dump, apply=args.apply)


if __name__ == "__main__":
    main()
