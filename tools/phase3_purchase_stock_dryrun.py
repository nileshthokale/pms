"""Phase 3 dry run — purchase history + stock reconciliation (OFFLINE ONLY).

Reads PharmaWinner202610051955.sql with the offline dump parser and writes
migration_backups/phase3_dry_run.md + .json.  Never opens any database:
no writes are possible by construction (no sqlite import, no DB path).

Unit semantics (verified against the dump):
- purchase pay/free quantities are PACKS; new stock_qty uses the same unit
  (pay_qty + free_qty), matching the application's posting engine.
- sales SalesQty is LOOSE units; packs = SalesQty / PackSize (10x pattern
  verified; per-batch PackSize is consistent across all 233,598 rows).
- credit/debit-note Qty is LOOSE units (packs = Qty / PackSize).
- TotalLooseQty / RcvdPackQty have no target column (new schema tracks
  packs only) and are reported as unsupported, not converted.
- GST-era = VhDate >= 2017-07-01 AND rate in {0,5,12,18,28}; everything else
  is VAT-era.  Historical TaxPer is preserved verbatim, never converted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import LegacyDump  # noqa: E402

DEFAULT_SOURCE = ROOT / "PharmaWinner202610051955.sql"
GST_CUTOFF = "2017-07-01"
GST_RATES = {0, 5, 12, 18, 28}


def num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def is_bad_date(value) -> bool:
    return not value or value in ("0000-00-00", "0001-01-01")


def clean_date(value) -> str:
    value = "" if value is None else str(value).strip()
    return "" if is_bad_date(value) else value[:10]


def classify_tax_era(date: str, rate: float) -> str:
    """GST-era only for dated GST-rate rows on/after the cutoff."""
    if date and date >= GST_CUTOFF and rate in GST_RATES:
        return "GST"
    return "VAT"


def sales_packs(qty: float, pack_size: float) -> float | None:
    if pack_size:
        return qty / pack_size
    return None


def compose_voucher(fy_name: str, vhtype: str, vhno) -> str:
    return f"{fy_name}-{vhtype}-{vhno}"


def pack_text(value) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


# Target column maps (old -> new); None = no target (unsupported).
HEADER_MAP = [
    ("ID", "id", "preserved explicit"),
    ("AcYearID+VhType+VhNo", "voucher_no", "FY name-Type-No composition"),
    ("VhDate", "voucher_date", "verbatim (no bad dates found)"),
    ("VhTime", "voucher_time", "verbatim"),
    ("VhType", "purchase_type", "verbatim Cash/Credit"),
    ("SuppID", "supplier_id", "direct: ledger IDs preserved in Phase 2"),
    ("InvoiceNo", "invoice_no", "verbatim"),
    ("InvoiceDate", "invoice_date", "verbatim"),
    ("DueDate", "due_date", "verbatim"),
    ("GrossAmount", "total_amount", "verbatim"),
    ("DiscountEntered", None, "free-text entry mode, no target"),
    ("DiscountPer", "bill_discount", "verbatim percent"),
    ("DiscountAmt", None, "header discount amount, no target column"),
    ("RoundOff", "round_off", "verbatim"),
    ("LessDNAmount", None, "debit-note allocation, no target"),
    ("AddCNAmount", None, "credit-note allocation, no target"),
    ("AddTaxAmount", "gst_amount", "verbatim header tax total"),
    ("PaidAmount", None, "payments belong to a later phase"),
    ("VhAmount", "invoice_net_amount", "verbatim voucher total"),
    ("VhNarration", "remarks", "verbatim"),
]
LINE_MAP = [
    ("ID", "id", "preserved explicit"),
    ("VhID", "purchase_invoice_id", "via preserved header IDs"),
    ("ItemID", "item_id", "direct: item IDs preserved in Phase 1"),
    ("PackSize", "pack_size", "smallint to TEXT"),
    ("PayPackQty", "pay_qty", "packs, verbatim"),
    ("FreePackQty", "free_qty", "packs, verbatim"),
    ("RcvdPackQty", None, "equals pay+free; no target"),
    ("TotalLooseQty", None, "loose units; new schema tracks packs only"),
    ("BatchNo", "batch_no", "verbatim (never empty in source)"),
    ("ExpiryDate", "expiry", "verbatim YYYY-MM-DD"),
    ("Rate", "rate", "verbatim"),
    ("MRP", "mrp", "verbatim"),
    ("DiscEntered", None, "free-text entry mode, no target"),
    ("DiscPer", "discount", "verbatim percent"),
    ("DiscAmt", None, "line discount amount, no target column"),
    ("Amount", "amount", "verbatim"),
    ("TaxPer", "gst_percent", "VERBATIM incl. VAT-era rates; never converted"),
    ("TaxAmt", "gst_amount", "verbatim"),
    ("PurRate", "purchase_rate", "verbatim"),
    ("NetRate", "net_rate", "verbatim"),
    ("SaleRate", None, "same-as-MRP duplicate, no target"),
    ("ChallanID", None, "challans are a separate unmapped document type"),
]
BATCH_MAP = [
    ("ItemID", "item_id", "direct"),
    ("BatchNo", "batch_no", "verbatim; (item,batch) unique in source"),
    ("ExpiryDate", "expiry", "verbatim"),
    ("MRP", "mrp", "verbatim"),
    ("Rate", "purchase_rate", "verbatim"),
    ("NetPurRate", "net_rate", "verbatim"),
    ("PackSize", "pack_size", "smallint to TEXT"),
    ("TotalPurchaseQty-TotalSalesQty", "stock_qty", "pack-unit net, verbatim"),
    ("NetSalesRate/TotalSalesQty", None, "sales history, not a stock field"),
]


def build_report(dump: LegacyDump) -> dict:
    items = {r[0] for r in dump.iter_rows("itemmst")}
    ledgers = {r[0] for r in dump.iter_rows("ledger")}
    creditors = {r[0] for r in dump.iter_rows("ledger") if r[2] == 25}
    fy = {r[0]: r[3] for r in dump.iter_rows("acyear")}
    headers = list(dump.iter_rows("invoicevhheader"))
    lines = list(dump.iter_rows("invoiceitemdetail"))
    header_ids = {r[0] for r in headers}

    findings: dict[str, list] = defaultdict(list)
    # -- header checks --
    missing_supplier = sorted({r[8] for r in headers} - creditors)
    for s in missing_supplier:
        findings["missing_supplier"].append(s)
    dup_bill = {k: v for k, v in
                Counter((r[1], r[8], (r[9] or "").strip()) for r in headers).items() if v > 1}
    dup_voucher = {k: v for k, v in
                   Counter((r[1], r[2], r[3]) for r in headers).items() if v > 1}
    bad_vhdate = [r[0] for r in headers if is_bad_date(r[4])]
    # -- line checks --
    missing_item = sorted({r[2] for r in lines} - items)
    orphan_lines = [r[0] for r in lines if r[1] not in header_ids]
    neg_pay = [r[0] for r in lines if num(r[6]) < 0]
    zero_qty = [r[0] for r in lines if num(r[6]) + num(r[7]) == 0]
    tax_dist = dict(sorted(Counter(r[16] for r in lines).items(), key=lambda x: str(x[0])))
    vat_rates = sorted({t for t in tax_dist if num(t) not in GST_RATES}, key=str)
    # -- batch/stock evidence --
    purch = defaultdict(float)
    for r in lines:
        purch[(r[2], r[3] or "")] += num(r[6]) + num(r[7])
    vhdate = {}
    for r in headers:
        vhdate[r[0]] = clean_date(r[4])
    sales_packs = defaultdict(float)
    for r in dump.iter_rows("salesitemdetail"):
        ps = num(r[3])
        if ps:
            sales_packs[(r[2], r[4] or "")] += num(r[7]) / ps
    cn = defaultdict(float)
    for r in dump.iter_rows("creditnoteitemdetail"):
        ps = num(r[6])
        q = num(r[8]) + num(r[9])
        cn[(r[4], r[5] or "")] += (q / ps) if ps else q
    dn = defaultdict(float)
    for r in dump.iter_rows("debitnoteitemdetail"):
        ps = num(r[6])
        q = num(r[8]) + num(r[9])
        dn[(r[4], r[5] or "")] += (q / ps) if ps else q
    adj = defaultdict(float)
    for r in dump.iter_rows("stockadjusted"):
        adj[(r[3], r[4] or "")] += num(r[6])
    sb = {}
    for r in dump.iter_rows("stockbalance"):
        sb[(r[0], r[1] or "")] = num(r[6]) - num(r[9])
    sb_items_unknown = sorted({k[0] for k in sb} - items)
    negatives = sorted([(k, v) for k, v in sb.items() if v < 0])
    zero_nets = sum(1 for v in sb.values() if v == 0)
    positive_nets = sum(1 for v in sb.values() if v > 0)

    def close(a, b):
        return abs(a - b) < 0.005

    matched = mismatched_over = mismatched_under = 0
    exceptions = []
    universe = set(sb) | set(purch) | set(sales_packs) | set(cn) | set(dn) | set(adj)
    for k in universe:
        computed = (purch.get(k, 0) - sales_packs.get(k, 0) + cn.get(k, 0)
                    - dn.get(k, 0) + adj.get(k, 0))
        actual = sb.get(k, 0)
        if close(computed, actual):
            matched += 1
        elif actual > computed:
            mismatched_over += 1
            if len(exceptions) < 30:
                exceptions.append({"key": list(k), "purch": purch.get(k, 0),
                                   "sales_packs": round(sales_packs.get(k, 0), 2),
                                   "cn": cn.get(k, 0), "dn": dn.get(k, 0),
                                   "adj": adj.get(k, 0), "stockbalance": actual})
        else:
            mismatched_under += 1
    # history-only keys needing zero-qty batches
    hist_only = sorted((set(purch) | set(sales_packs) | set(cn) | set(dn)) - set(sb))
    # challan evidence
    chal_keys = set()
    for r in dump.iter_rows("challanitemdetail"):
        chal_keys.add((r[2], r[3] or ""))
    linked = sum(1 for r in lines if (r[21] or 0) not in (0, "0", None))
    # GST vs VAT on purchase lines (dated evidence)
    era = Counter()
    for r in lines:
        d = vhdate.get(r[1], "")
        era[classify_tax_era(d, num(r[16]))] += 1

    return {
        "source_file": str(dump.path),
        "source_bytes": dump.size_bytes,
        "expected": {"purchase_headers": len(headers), "purchase_lines": len(lines),
                     "stock_batches": len(sb),
                     "history_only_batches": len(hist_only)},
        "header_map": HEADER_MAP,
        "line_map": LINE_MAP,
        "batch_map": BATCH_MAP,
        "missing_suppliers": missing_supplier,
        "duplicate_bill_numbers": dup_bill,
        "duplicate_vouchers": dup_voucher,
        "bad_voucher_dates": bad_vhdate,
        "missing_items": missing_item,
        "orphan_lines": orphan_lines,
        "negative_pay_lines": neg_pay,
        "zero_qty_lines": zero_qty,
        "line_tax_distribution": {str(k): v for k, v in tax_dist.items()},
        "vat_only_tax_rates": [str(v) for v in vat_rates],
        "line_tax_era": dict(era),
        "stockbalance_items_unknown": sb_items_unknown,
        "negative_nets": [{"item": k[0], "batch": k[1], "qty": v} for k, v in negatives],
        "zero_nets": zero_nets,
        "positive_nets": positive_nets,
        "reconciliation": {"matched": matched, "over": mismatched_over,
                           "under": mismatched_under,
                           "adjustments_included": True},
        "history_only_batches": [list(k) for k in hist_only[:50]],
        "history_only_count": len(hist_only),
        "challan": {"headers": dump.count_rows().get("challanvhheader", 0),
                    "lines": dump.count_rows().get("challanitemdetail", 0),
                    "batch_keys": len(chal_keys),
                    "keys_also_purchased": len(chal_keys & set(purch)),
                    "invoice_lines_with_challanid": linked,
                    "treatment": "excluded as purchase documents (separate receipt type); "
                                 "no double counting"},
        "sales_evidence": {"lines": dump.count_rows().get("salesitemdetail", 0),
                           "batch_keys": len(sales_packs),
                           "unit": "loose SalesQty converted via per-row PackSize"},
        "returns_evidence": {
            "creditnote_lines": dump.count_rows().get("creditnoteitemdetail", 0),
            "debitnote_lines": dump.count_rows().get("debitnoteitemdetail", 0),
            "unit": "loose Qty converted via per-row PackSize"},
        "adjustment_evidence": {"rows": dump.count_rows().get("stockadjusted", 0),
                                "keys": len(adj),
                                "treatment": "counted once as movement evidence; final rule "
                                             "needs owner decision (see reconciliation)"},
        "exceptions": exceptions,
        "migration_order": ["purchase_invoices (headers, IDs preserved)",
                            "purchase_invoice_items (lines, IDs preserved)",
                            "stock_batches from stockbalance nets (authoritative current stock)",
                            "zero-qty history batches for linked-but-absent (item,batch)",
                            "sqlite_sequence cursors to max IDs"],
        "validation_checks": ["header/line counts equal source",
                              "voucher_no unique", "supplier/item refs resolve",
                              "no negative pay/rate rows beyond reported list",
                              "stock qty equals stockbalance nets exactly",
                              "transaction tables for other phases still empty",
                              "integrity_check ok, foreign_key_check 0"],
        "schema_notes": [
            "New tables are empty: legacy header IDs 1..5717 and line IDs 1..12322 "
            "can be preserved explicitly.",
            "RcvdPackQty/TotalLooseQty/SaleRate/DiscEntered/DiscAmt/header "
            "DiscountAmt/LessDN/AddCN/PaidAmount/ChallanID have no target columns.",
            "Historical TaxPer (incl. VAT-era 5.5/6/12.5/13.5) maps verbatim to "
            "gst_percent; era is determined by VhDate, never by number."],
    }


def render_markdown(rep: dict) -> str:
    L = ["# Phase 3 Dry Run — Purchases + Stock (NO DB WRITES)", "",
         f"- Source: `{rep['source_file']}` ({rep['source_bytes']:,} bytes, READ-ONLY)", "",
         "## 1. Table mappings", "",
         "### Purchase headers (`invoicevhheader` → `purchase_invoices`)", ""]
    for old, new, note in rep["header_map"]:
        L.append(f"- `{old}` → `{new or 'NO TARGET'}` ({note})")
    L += ["", "### Purchase lines (`invoiceitemdetail` → `purchase_invoice_items`)", ""]
    for old, new, note in rep["line_map"]:
        L.append(f"- `{old}` → `{new or 'NO TARGET'}` ({note})")
    L += ["", "### Batches (`stockbalance` → `stock_batches`)", ""]
    for old, new, note in rep["batch_map"]:
        L.append(f"- `{old}` → `{new or 'NO TARGET'}` ({note})")
    L += ["", "## 2. Expected counts",
          f"- purchase headers: {rep['expected']['purchase_headers']}",
          f"- purchase lines: {rep['expected']['purchase_lines']}",
          f"- stock batches (stockbalance nets): {rep['expected']['stock_batches']}",
          f"- history-only zero batches: {rep['expected']['history_only_batches']}",
          "", "## 3. Reference checks",
          f"- missing suppliers: {rep['missing_suppliers']}",
          f"- missing items: {rep['missing_items']}",
          f"- orphan lines: {len(rep['orphan_lines'])}",
          f"- duplicate bill numbers: {len(rep['duplicate_bill_numbers'])}",
          f"- duplicate vouchers: {len(rep['duplicate_vouchers'])}",
          f"- bad voucher dates: {len(rep['bad_voucher_dates'])}",
          f"- negative-pay lines: {len(rep['negative_pay_lines'])}",
          f"- zero-qty lines: {len(rep['zero_qty_lines'])}",
          "", "## 4. Batch/stock quantities",
          f"- stockbalance keys: {rep['expected']['stock_batches']}",
          f"- zero nets: {rep['zero_nets']}, positive: {rep['positive_nets']}, "
          f"negative: {len(rep['negative_nets'])}",
          f"- items unknown to Phase 1: {rep['stockbalance_items_unknown']}",
          f"- history-only batches: {rep['history_only_count']}",
          "", "## 5. Sales/returns/adjustment dependencies",
          f"- sales lines: {rep['sales_evidence']['lines']} "
          f"({rep['sales_evidence']['batch_keys']} batches, {rep['sales_evidence']['unit']})",
          f"- credit-note lines: {rep['returns_evidence']['creditnote_lines']}, "
          f"debit-note lines: {rep['returns_evidence']['debitnote_lines']} "
          f"({rep['returns_evidence']['unit']})",
          f"- adjustments: {rep['adjustment_evidence']['rows']} rows "
          f"({rep['adjustment_evidence']['treatment']})",
          f"- challans: {rep['challan']['headers']} headers / {rep['challan']['lines']} lines "
          f"({rep['challan']['treatment']})",
          "", "## 6. VAT/GST handling",
          f"- line TaxPer distribution: {json.dumps(rep['line_tax_distribution'])}",
          f"- VAT-only rates (never converted): {rep['vat_only_tax_rates']}",
          f"- dated line era split: {json.dumps(rep['line_tax_era'])}",
          "", "## 7. Reconciliation result",
          f"- matched: {rep['reconciliation']['matched']}, "
          f"over: {rep['reconciliation']['over']}, under: {rep['reconciliation']['under']}",
          "- Rule: stockbalance nets are authoritative for current stock; purchases give "
          "history. Residuals (loose-unit rounding, unrecorded movements, opening stock) "
          "must NOT be forced to balance. Negative nets need an owner rule.",
          "", "## 8. Schema compatibility: see schema_notes in JSON; no ID conflicts "
          "(targets empty).",
          "", "## 9. Migration order"]
    L += [f"- {s}" for s in rep["migration_order"]]
    L += ["", "## 10. Validation checks"]
    L += [f"- {s}" for s in rep["validation_checks"]]
    L += ["", "## Exceptions (first 30 over-balance keys)"]
    for e in rep["exceptions"]:
        L.append(f"- {json.dumps(e)}")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(ROOT / "migration_backups" / "phase3_dry_run.md"))
    ap.add_argument("--json", default=str(ROOT / "migration_backups" / "phase3_dry_run.json"))
    args = ap.parse_args(argv)
    dump = LegacyDump(DEFAULT_SOURCE)
    rep = build_report(dump)
    Path(args.report).write_text(render_markdown(rep), encoding="utf-8")
    Path(args.json).write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(f"headers={rep['expected']['purchase_headers']} "
          f"lines={rep['expected']['purchase_lines']} "
          f"batches={rep['expected']['stock_batches']}")
    print(f"written: {args.report}\nwritten: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
