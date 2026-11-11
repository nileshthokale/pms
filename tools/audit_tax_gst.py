"""Phase 3: Diagnose and Audit GST and Legacy Tax Mapping.

Conducts an exhaustive tax audit:
1. Item Master legacy TaxID provenance vs target items.tax_structure & legacy_tax_id.
2. Verification of TaxID codes (1..15) and their historical rate distributions.
3. Separation of VAT-era (< 2017-07-01) vs GST-era (>= 2017-07-01) purchase lines.
4. Investigation of non-standard GST-era rates (e.g. 6.0%, 12.5%, 13.5%).
5. Purchase line tax calculation vs header AddTaxAmount reconciliation.
6. Treatment for new item 944 (TaxID 11).
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


def run_tax_audit() -> dict:
    print("=== Phase 3: Comprehensive Tax & GST Audit ===")
    dump = LegacyDump(SOURCE_DUMP)
    conn = sqlite3.connect(f"file:{STAGE_DB.as_posix()}?mode=ro", uri=True)

    # 1. Item Master Tax Audit
    print("\n--- 1. Item Master Tax Provenance Audit ---")
    source_items = {}
    for r in dump.iter_rows("itemmst"):
        # ID, ItemName, UnitID, PathyID, CompanyID, PackSize, DiscountPer, ReorderStockLevel, Rate, MRP, TaxID
        source_items[r[0]] = {
            "id": r[0],
            "name": str(r[1]).strip() if r[1] is not None else "",
            "unit_id": r[2],
            "tax_id": r[10],
            "mrp": r[9],
            "rate": r[8],
        }

    item_map = dict(conn.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity = 'item'").fetchall())

    target_items = {}
    for r in conn.execute("SELECT id, item_name, tax_structure, legacy_tax_id FROM items").fetchall():
        target_items[r[0]] = {
            "id": r[0],
            "name": r[1],
            "tax_structure": r[2],
            "legacy_tax_id": r[3],
        }

    # Check provenance status
    missing_provenance_count = 0
    provenance_discrepancies = []
    tax_id_distribution = defaultdict(int)

    for leg_id, s_item in source_items.items():
        tax_id_distribution[s_item["tax_id"]] += 1
        tgt_id = item_map.get(str(leg_id))
        if tgt_id and tgt_id in target_items:
            t_item = target_items[tgt_id]
            if t_item["legacy_tax_id"] is None:
                missing_provenance_count += 1
            elif str(t_item["legacy_tax_id"]) != str(s_item["tax_id"]):
                provenance_discrepancies.append({
                    "legacy_id": leg_id,
                    "target_id": tgt_id,
                    "name": s_item["name"],
                    "source_tax_id": s_item["tax_id"],
                    "target_legacy_tax_id": t_item["legacy_tax_id"],
                })

    print(f"Total source items: {len(source_items)}")
    print(f"Target items in staging: {len(target_items)}")
    print(f"Target items with NULL legacy_tax_id: {missing_provenance_count}")
    print(f"Provenance discrepancies (conflicting values): {len(provenance_discrepancies)}")
    print(f"Source TaxID distribution across all 943 items:")
    for tid, cnt in sorted(tax_id_distribution.items(), key=lambda x: str(x[0])):
        print(f"  TaxID {tid}: {cnt} items")

    # Item 944 check
    item_944 = source_items.get(944)
    print(f"\nItem 944 in source dump: {item_944}")

    # 2. Purchase Invoices & Line Tax Audit (VAT-era vs GST-era)
    print("\n--- 2. Purchase Invoice Tax Audit (VAT vs GST) ---")
    source_pur_headers = {}
    for r in dump.iter_rows("invoicevhheader"):
        # ID, AcYearID, VhType, VhNo, VhDate, VhTime, VhNarration, VhAmount, SuppID, InvoiceNo, InvoiceDate, DueDate, GrossAmount, DiscountEntered, DiscountPer, DiscountAmt, RoundOff, LessDNAmount, AddCNAmount, AddTaxAmount, PaidAmount
        source_pur_headers[r[0]] = {
            "id": r[0],
            "vh_no": r[3],
            "date": str(r[4]),
            "amount": float(r[7] or 0),
            "gross": float(r[12] or 0),
            "discount": float(r[15] or 0),
            "round_off": float(r[16] or 0),
            "tax_amount": float(r[19] or 0),
        }

    vat_lines = []
    gst_lines = []
    vat_rate_counts = defaultdict(int)
    gst_rate_counts = defaultdict(int)

    line_calc_discrepancies = []
    header_tax_reconciliations = []

    lines_by_header = defaultdict(list)
    for r in dump.iter_rows("invoiceitemdetail"):
        # ID, VhID, ItemID, BatchNo, PackSize, ExpiryDate, PayPackQty, FreePackQty, RcvdPackQty, TotalLooseQty, Rate, MRP, DiscEntered, DiscPer, DiscAmt, Amount, TaxPer, TaxAmt, PurRate, NetRate, SaleRate, ChallanID
        vh_id = r[1]
        lines_by_header[vh_id].append(r)
        hdr = source_pur_headers.get(vh_id)
        if not hdr:
            continue
        vdate = hdr["date"]
        rate = float(r[16] or 0)
        line_amt = float(r[15] or 0)
        tax_amt = float(r[17] or 0)

        # Reconcile expected tax: round(line_amt * rate / 100, 2)
        expected_tax = round(line_amt * rate / 100.0, 2)
        diff = abs(tax_amt - expected_tax)
        if diff > 0.05 and line_amt > 0:
            line_calc_discrepancies.append({
                "vh_id": vh_id,
                "line_id": r[0],
                "date": vdate,
                "amount": line_amt,
                "tax_per": rate,
                "stored_tax_amt": tax_amt,
                "expected_tax_amt": expected_tax,
                "diff": round(diff, 2),
            })

        if vdate < "2017-07-01":
            vat_lines.append(r)
            vat_rate_counts[rate] += 1
        else:
            gst_lines.append(r)
            gst_rate_counts[rate] += 1

    print(f"Total purchase lines in source: {sum(len(v) for v in lines_by_header.values())}")
    print(f"VAT-era lines (< 2017-07-01): {len(vat_lines)}")
    print("  VAT rates distribution:")
    for r_val, c_val in sorted(vat_rate_counts.items()):
        print(f"    {r_val}%: {c_val} lines")

    print(f"\nGST-era lines (>= 2017-07-01): {len(gst_lines)}")
    print("  GST rates distribution:")
    for r_val, c_val in sorted(gst_rate_counts.items()):
        print(f"    {r_val}%: {c_val} lines")

    # Header vs Lines Tax Amount Check
    header_tax_diffs = []
    for vh_id, hdr in source_pur_headers.items():
        lines = lines_by_header.get(vh_id, [])
        sum_line_tax = sum(float(l[17] or 0) for l in lines)
        hdr_tax = hdr["tax_amount"]
        diff = abs(hdr_tax - sum_line_tax)
        if diff > 0.05:
            header_tax_diffs.append({
                "vh_id": vh_id,
                "date": hdr["date"],
                "header_tax": hdr_tax,
                "sum_line_tax": round(sum_line_tax, 2),
                "diff": round(diff, 2),
            })

    print(f"\nHeader tax vs sum of line tax discrepancies (>0.05): {len(header_tax_diffs)} of {len(source_pur_headers)} invoices")

    # 3. Investigation of 6.0% lines in GST era
    gst_6_lines = [l for l in gst_lines if float(l[16] or 0) == 6.0]
    print(f"\nGST-era lines with TaxPer = 6.0%: {len(gst_6_lines)}")
    if gst_6_lines:
        print("  Sample GST 6% lines:")
        for l in gst_6_lines[:5]:
            hdr = source_pur_headers.get(l[1], {})
            print(f"    Line ID {l[0]}: Date {hdr.get('date')} VhID {l[1]} ItemID {l[2]} Amt {l[15]} TaxAmt {l[17]}")

    conn.close()

    audit_report = {
        "item_master": {
            "total_source_items": len(source_items),
            "target_items": len(target_items),
            "missing_provenance_count": missing_provenance_count,
            "provenance_discrepancies": provenance_discrepancies,
            "tax_id_distribution": dict(tax_id_distribution),
            "item_944": item_944,
        },
        "purchase_tax": {
            "total_headers": len(source_pur_headers),
            "total_lines": sum(len(v) for v in lines_by_header.values()),
            "vat_lines_count": len(vat_lines),
            "vat_rates": dict(vat_rate_counts),
            "gst_lines_count": len(gst_lines),
            "gst_rates": dict(gst_rate_counts),
            "line_calc_discrepancies_count": len(line_calc_discrepancies),
            "sample_line_discrepancies": line_calc_discrepancies[:10],
            "header_tax_discrepancies_count": len(header_tax_diffs),
            "sample_header_discrepancies": header_tax_diffs[:10],
            "gst_6_percent_lines_count": len(gst_6_lines),
        },
    }

    out_file = ROOT / "migration_backups" / "legacy_data_refresh_tax_audit.json"
    out_file.write_text(json.dumps(audit_report, indent=2), encoding="utf-8")
    print(f"\nTax audit complete. Saved to {out_file}")
    return audit_report


if __name__ == "__main__":
    run_tax_audit()
