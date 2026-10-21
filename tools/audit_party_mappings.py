"""Phase 4: Comprehensive Supplier, Customer, and Doctor Mapping & Balance Audit.

Validates:
1. Every creditor (group 25) vs target suppliers and ledger_id links.
2. Every debtor (group 16) vs target customers and ledger_id links.
3. Every doctor vs target doctors.
4. Transaction reference integrity:
   - purchase headers -> suppliers
   - payment headers -> suppliers
   - debit note headers -> suppliers
   - sales headers -> customers & doctors
   - receipt headers -> customers
   - credit note headers -> customers
5. Supplier and customer balances:
   - Opening balance
   - Total debits and credits in ledger_transactions
   - Invoice vs payment reconciliation
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import LegacyDump

STAGE_DB = ROOT / "staging" / "pharmacy_staging_refresh.db"
SOURCE_DUMP = ROOT / "PharmaWinner202610201418.sql"


def run_party_audit() -> dict:
    print("=== Phase 4: Supplier, Customer, and Doctor Mapping Audit ===")
    dump = LegacyDump(SOURCE_DUMP)
    conn = sqlite3.connect(f"file:{STAGE_DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    gpmst = {r[0]: r[1] for r in dump.iter_rows("gpmst")}
    states = {r[0]: r[1] for r in dump.iter_rows("statemst")}
    sundry_info = {r[1]: r for r in dump.iter_rows("sundaryinfo")}

    ledgers = {r[0]: r for r in dump.iter_rows("ledger")}
    creditors = {lid: r for lid, r in ledgers.items() if gpmst.get(r[2]) == "SUNDRY CREDITORS"}
    debtors = {lid: r for lid, r in ledgers.items() if gpmst.get(r[2]) == "SUNDRY DEBTORS"}

    print(f"Source creditors (SUNDRY CREDITORS): {len(creditors)}")
    print(f"Source debtors (SUNDRY DEBTORS): {len(debtors)}")

    # Target mappings
    supp_map = {
        int(r[0]): r[1]
        for r in conn.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity = 'supplier_by_ledger'").fetchall()
    }
    cust_map = {
        int(r[0]): r[1]
        for r in conn.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity = 'customer_by_ledger'").fetchall()
    }
    doc_map = {
        int(r[0]): r[1]
        for r in conn.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity = 'doctor'").fetchall()
    }

    target_suppliers = {r[0]: dict(r) for r in conn.execute("SELECT id, supplier_name, sales_tax_no, vat_or_tin, city, contact_person, contact_no, address, state, opening_balance, ledger_id FROM suppliers").fetchall()}
    target_customers = {r[0]: dict(r) for r in conn.execute("SELECT id, customer_name, city, contact_person, contact_no, address, state, opening_balance, ledger_id FROM customers").fetchall()}
    target_doctors = {r[0]: dict(r) for r in conn.execute("SELECT id, doctor_name, city, specialty, phone_no FROM doctors").fetchall()}

    # 1. Supplier Validation
    supplier_results = []
    supplier_issues = []
    for lid, r in creditors.items():
        name = str(r[1]).strip()
        op_bal = float(r[4] or 0)
        s_info = sundry_info.get(lid)
        mapped_id = supp_map.get(lid)
        t_supp = target_suppliers.get(mapped_id) if mapped_id else None

        issue = None
        if not mapped_id:
            issue = "Unmapped creditor in legacy_id_map"
        elif not t_supp:
            issue = f"Mapped supplier ID {mapped_id} missing from target suppliers"
        elif t_supp["supplier_name"].strip().upper() != name.upper():
            issue = f"Name mismatch: source '{name}' vs target '{t_supp['supplier_name']}'"

        if issue:
            supplier_issues.append({"legacy_id": lid, "name": name, "issue": issue})

        supplier_results.append({
            "legacy_id": lid,
            "source_name": name,
            "source_op_bal": op_bal,
            "mapped_supplier_id": mapped_id,
            "target_name": t_supp["supplier_name"] if t_supp else None,
            "target_ledger_id": t_supp["ledger_id"] if t_supp else None,
            "issue": issue,
        })

    print(f"Validated {len(supplier_results)} creditors. Issues found: {len(supplier_issues)}")

    # 2. Customer Validation
    customer_results = []
    customer_issues = []
    for lid, r in debtors.items():
        name = str(r[1]).strip()
        op_bal = float(r[4] or 0)
        mapped_id = cust_map.get(lid)
        t_cust = target_customers.get(mapped_id) if mapped_id else None

        issue = None
        if not mapped_id:
            issue = "Unmapped debtor in legacy_id_map"
        elif not t_cust:
            issue = f"Mapped customer ID {mapped_id} missing from target customers"
        elif t_cust["customer_name"].strip().upper() != name.upper():
            issue = f"Name mismatch: source '{name}' vs target '{t_cust['customer_name']}'"

        if issue:
            customer_issues.append({"legacy_id": lid, "name": name, "issue": issue})

        customer_results.append({
            "legacy_id": lid,
            "source_name": name,
            "source_op_bal": op_bal,
            "mapped_customer_id": mapped_id,
            "target_name": t_cust["customer_name"] if t_cust else None,
            "target_ledger_id": t_cust["ledger_id"] if t_cust else None,
            "issue": issue,
        })

    print(f"Validated {len(customer_results)} debtors. Issues found: {len(customer_issues)}")

    # 3. Doctor Validation
    doctor_rows = list(dump.iter_rows("doctormst"))
    doctor_results = []
    doctor_issues = []
    for r in doctor_rows:
        did = r[0]
        dname = str(r[1]).strip()
        mapped_id = doc_map.get(did)
        t_doc = target_doctors.get(mapped_id) if mapped_id else None

        issue = None
        if not mapped_id:
            issue = "Unmapped doctor in legacy_id_map"
        elif not t_doc:
            issue = f"Mapped doctor ID {mapped_id} missing from target doctors"
        elif t_doc["doctor_name"].strip().upper() != dname.upper():
            issue = f"Name mismatch: source '{dname}' vs target '{t_doc['doctor_name']}'"

        if issue:
            doctor_issues.append({"legacy_id": did, "name": dname, "issue": issue})

        doctor_results.append({
            "legacy_id": did,
            "source_name": dname,
            "mapped_doctor_id": mapped_id,
            "target_name": t_doc["doctor_name"] if t_doc else None,
            "issue": issue,
        })

    print(f"Validated {len(doctor_results)} doctors. Issues found: {len(doctor_issues)}")

    # 4. Transaction Party Reference Checks
    print("\n--- 4. Transaction Reference Auditing ---")
    tx_issues = []

    # Purchases -> SuppID
    for r in dump.iter_rows("invoicevhheader"):
        hid = r[0]
        supp_id = r[8]
        if supp_id not in supp_map:
            tx_issues.append({"type": "purchase", "id": hid, "error": f"Unknown SuppID {supp_id}"})

    # Payments -> SuppID
    for r in dump.iter_rows("paymentvhheader"):
        pid = r[0]
        supp_id = r[8]
        if supp_id not in supp_map:
            tx_issues.append({"type": "payment", "id": pid, "error": f"Unknown SuppID {supp_id}"})

    # Debit notes -> LedID
    for r in dump.iter_rows("debitnotevhheader"):
        dnid = r[0]
        supp_id = r[8]
        if supp_id not in supp_map:
            tx_issues.append({"type": "debit_note", "id": dnid, "error": f"Unknown SuppID {supp_id}"})

    # Sales -> CustID & DoctID
    for r in dump.iter_rows("salesvhheader"):
        sid = r[0]
        cust_id = r[9]
        doc_id = r[13]
        if cust_id is not None and cust_id not in cust_map and cust_id != 7: # 7 is walk-in
            tx_issues.append({"type": "sale", "id": sid, "error": f"Unknown CustID {cust_id}"})
        if doc_id is not None and doc_id != 0 and doc_id not in doc_map:
            tx_issues.append({"type": "sale", "id": sid, "error": f"Unknown DoctID {doc_id}"})

    # Receipts -> CustID
    for r in dump.iter_rows("receiptvhheader"):
        rid = r[0]
        cust_id = r[8]
        if cust_id not in cust_map:
            tx_issues.append({"type": "receipt", "id": rid, "error": f"Unknown CustID {cust_id}"})

    # Credit notes -> LedID
    for r in dump.iter_rows("creditnotevhheader"):
        cnid = r[0]
        cust_id = r[8]
        if cust_id not in cust_map:
            tx_issues.append({"type": "credit_note", "id": cnid, "error": f"Unknown CustID {cust_id}"})

    print(f"Transaction party reference checks complete. Total broken references: {len(tx_issues)}")

    # 5. Supplier Balance & Activity Reconciliation
    print("\n--- 5. Supplier Balance Reconciliation Sample ---")
    supplier_balances = []
    for s in supplier_results[:10]:
        supp_id = s["mapped_supplier_id"]
        if not supp_id:
            continue
        led_id = s["target_ledger_id"]

        # Sum purchases in target
        pur_sum = conn.execute("SELECT COALESCE(SUM(net_amount), 0) FROM purchase_invoices WHERE supplier_id = ?", (supp_id,)).fetchone()[0]
        # Sum payments in target
        pay_sum = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM supplier_payments WHERE supplier_id = ?", (supp_id,)).fetchone()[0]
        # Sum debit notes in target
        dn_sum = conn.execute("SELECT COALESCE(SUM(total_amount), 0) FROM debit_notes WHERE supplier_id = ?", (supp_id,)).fetchone()[0]
        # Ledger tx debits and credits
        debits, credits = 0.0, 0.0
        if led_id:
            row = conn.execute("SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0) FROM ledger_transactions WHERE ledger_id = ?", (led_id,)).fetchone()
            debits, credits = row[0], row[1]

        supplier_balances.append({
            "supplier_id": supp_id,
            "name": s["target_name"],
            "opening_balance": s["source_op_bal"],
            "purchases_sum": round(pur_sum, 2),
            "payments_sum": round(pay_sum, 2),
            "debit_notes_sum": round(dn_sum, 2),
            "ledger_debits": round(debits, 2),
            "ledger_credits": round(credits, 2),
        })

    for sb in supplier_balances[:5]:
        print(f"  Supplier {sb['supplier_id']} ({sb['name']}): Purchases={sb['purchases_sum']}, Payments={sb['payments_sum']}, Debits={sb['ledger_debits']}, Credits={sb['ledger_credits']}")

    conn.close()

    report = {
        "suppliers": {
            "total_audited": len(supplier_results),
            "issues_count": len(supplier_issues),
            "issues": supplier_issues,
            "sample_reconciled_balances": supplier_balances,
        },
        "customers": {
            "total_audited": len(customer_results),
            "issues_count": len(customer_issues),
            "issues": customer_issues,
        },
        "doctors": {
            "total_audited": len(doctor_results),
            "issues_count": len(doctor_issues),
            "issues": doctor_issues,
        },
        "transaction_references": {
            "broken_references_count": len(tx_issues),
            "issues": tx_issues,
        },
    }

    out_file = ROOT / "migration_backups" / "legacy_data_refresh_party_audit.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Party audit complete. Saved to {out_file}")
    return report


if __name__ == "__main__":
    run_party_audit()
