"""Phase 2: Comprehensive Source Table Audit and Mapping Classification.

Dynamically parses PharmaWinner202610201418.sql and audits every single table
against the staging database (staging/pharmacy_staging_refresh.db).
Produces:
- migration_backups/legacy_data_refresh_mapping.json
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import (
    DEMO_TABLES,
    LegacyDump,
    SOURCE_TARGETS,
    UNSUPPORTED_TABLES,
)

STAGE_DB = ROOT / "staging" / "pharmacy_staging.db"
SOURCE_DUMP = ROOT / "PharmaWinner202610201418.sql"
OUT_JSON = ROOT / "migration_backups" / "legacy_data_table_mapping.json"


# Detailed schema mapping definitions, primary keys, relationships, and missing columns
TABLE_METADATA: dict[str, dict] = {
    "accompany": {
        "target": None,
        "classification": "empty_in_source",
        "reason": "Empty in source (0 rows). Legacy accounting company profile; not needed.",
        "pk": "ID",
        "relationships": ["StartedAcYearID -> acyear.ID"],
        "missing_columns": ["CompanyName", "Address", "StartedAcDate", "StartedAcYearID"],
    },
    "acyear": {
        "target": "financial_years",
        "classification": "fully_imported",
        "reason": "Maps 1:1 to financial_years (FromDate, ToDate, FinancialYear, AcClosed).",
        "pk": "ID",
        "relationships": ["Referenced by invoicevhheader, salesvhheader, etc."],
        "missing_columns": ["FromYear", "ToYear (redundant with FinancialYear string)"],
    },
    "billsetting": {
        "target": None,
        "classification": "excluded_intentionally",
        "reason": "Legacy print formatting / printer hardware setup; application uses Qt document printing engine.",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["BillType", "LinePerPage", "CharacterPerLine", "SettingXML"],
    },
    "challanitemdetail": {
        "target": None,
        "classification": "excluded_intentionally",
        "reason": "Challan line items. The application manages inventory through purchase invoices and sales bills directly; delivery challans are unsupported.",
        "pk": "ID",
        "relationships": ["VhID -> challanvhheader.ID", "ItemID -> itemmst.ID"],
        "missing_columns": ["All columns (challan document type not modeled)"],
    },
    "challanvhheader": {
        "target": None,
        "classification": "excluded_intentionally",
        "reason": "Challan headers. Unsupported document type in current schema.",
        "pk": "ID",
        "relationships": ["AcYearID -> acyear.ID", "SuppID -> ledger.ID"],
        "missing_columns": ["All columns"],
    },
    "companymst": {
        "target": "companies",
        "classification": "partially_imported",
        "reason": "Manufacturer/company master. 1,222 source rows map to companies. Documented duplicate names (ALKEM, JAGSAM PHARMA) merged by design under UNIQUE(company_name).",
        "pk": "ID",
        "relationships": ["Referenced by itemmst.CompanyID"],
        "missing_columns": [],
    },
    "countersaleitems": {
        "target": None,
        "classification": "unsupported_by_current_schema",
        "reason": "Legacy test counter-sale lines (2 rows) dated prior to first financial year with no valid header or customer.",
        "pk": "ID",
        "relationships": ["ItemID -> itemmst.ID"],
        "missing_columns": ["All columns (unanchored transaction rows)"],
    },
    "creditnoteitemdetail": {
        "target": "credit_note_items",
        "classification": "fully_imported",
        "reason": "Customer sales return detail rows. Qty, MRP, Rate, Reason mapped to credit_note_items.",
        "pk": "ID",
        "relationships": ["VhID -> creditnotevhheader.ID", "ItemID -> items.id", "BatchNo -> stock_batches"],
        "missing_columns": ["FreeQty", "TotQty", "CNRate", "NetCNRate", "DiscEntered", "DiscPer"],
    },
    "creditnotevhdetail": {
        "target": "ledger_transactions",
        "classification": "fully_imported",
        "reason": "Double-entry accounting postings for customer credit notes mapped to ledger_transactions.",
        "pk": "ID",
        "relationships": ["VhID -> creditnotevhheader.ID", "LedID -> account_ledgers.id"],
        "missing_columns": [],
    },
    "creditnotevhheader": {
        "target": "credit_notes",
        "classification": "fully_imported",
        "reason": "Customer sales return vouchers. Mapped to credit_notes with customer_id from ledger.",
        "pk": "ID",
        "relationships": ["AcYearID -> financial_years.id", "LedID -> customers.id"],
        "missing_columns": ["DiscountEntered", "DiscountPer", "DiscountAmt", "AddedToLedger"],
    },
    "debitnoteitemdetail": {
        "target": "debit_note_items",
        "classification": "fully_imported",
        "reason": "Supplier purchase return detail rows. Qty, MRP, Rate, Reason mapped to debit_note_items.",
        "pk": "ID",
        "relationships": ["VhID -> debitnotevhheader.ID", "ItemID -> items.id", "BatchNo -> stock_batches"],
        "missing_columns": ["FreeQty", "TotQty", "DNRate", "NetDNRate", "DiscEntered", "DiscPer"],
    },
    "debitnotevhdetail": {
        "target": "ledger_transactions",
        "classification": "fully_imported",
        "reason": "Double-entry accounting postings for supplier debit notes mapped to ledger_transactions.",
        "pk": "ID",
        "relationships": ["VhID -> debitnotevhheader.ID", "LedID -> account_ledgers.id"],
        "missing_columns": [],
    },
    "debitnotevhheader": {
        "target": "debit_notes",
        "classification": "fully_imported",
        "reason": "Supplier purchase return vouchers. Mapped to debit_notes with supplier_id from ledger.",
        "pk": "ID",
        "relationships": ["AcYearID -> financial_years.id", "LedID -> suppliers.id"],
        "missing_columns": ["DiscountEntered", "DiscountPer", "DiscountAmt", "AddedToLedger"],
    },
    "demosalescreditnote": {
        "target": None,
        "classification": "empty_in_source",
        "reason": "Empty in source (0 rows). Demo sales credit note table.",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["All columns"],
    },
    "demosalesitemdetail": {
        "target": None,
        "classification": "excluded_intentionally",
        "reason": "Excluded intentionally: legacy demo transaction rows.",
        "pk": "ID",
        "relationships": ["VhID -> demosalesvhheader.ID"],
        "missing_columns": ["All columns"],
    },
    "demosalesvhdetail": {
        "target": None,
        "classification": "excluded_intentionally",
        "reason": "Excluded intentionally: legacy demo accounting postings.",
        "pk": "ID",
        "relationships": ["VhID -> demosalesvhheader.ID"],
        "missing_columns": ["All columns"],
    },
    "demosalesvhheader": {
        "target": None,
        "classification": "excluded_intentionally",
        "reason": "Excluded intentionally: legacy demo sales voucher headers.",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["All columns"],
    },
    "doctormst": {
        "target": "doctors",
        "classification": "partially_imported",
        "reason": "Doctor master. 8 source rows; duplicate 'SELF' rows merged by design under UNIQUE(doctor_name).",
        "pk": "ID",
        "relationships": ["Referenced by salesvhheader.DoctID"],
        "missing_columns": [],
    },
    "drugmst": {
        "target": "drugs",
        "classification": "fully_imported",
        "reason": "Drug/generic chemical entity master. Mapped 1:1 to drugs.",
        "pk": "ID",
        "relationships": ["Referenced by itemdrugs.DrugID"],
        "missing_columns": [],
    },
    "entryinvoicevhitem": {
        "target": None,
        "classification": "empty_in_source",
        "reason": "Empty in source (0 rows). Draft entry invoice items.",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["All columns"],
    },
    "entryinvoicevhmst": {
        "target": None,
        "classification": "empty_in_source",
        "reason": "Empty in source (0 rows). Draft entry invoice headers.",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["All columns"],
    },
    "gpmst": {
        "target": "account_groups",
        "classification": "fully_imported",
        "reason": "Legacy chart of accounts groups; classified into structured application account groups.",
        "pk": "ID",
        "relationships": ["Referenced by ledger.GroupID"],
        "missing_columns": ["BSGpID", "GpOrder", "DrCr"],
    },
    "invoicedebitnote": {
        "target": None,
        "classification": "unsupported_by_current_schema",
        "reason": "Legacy purchase invoice debit note linkage table (11 rows). Handled through invoice net calculations.",
        "pk": "ID",
        "relationships": ["InvoiceID -> invoicevhheader.ID", "DebitNoteID -> debitnotevhheader.ID"],
        "missing_columns": ["DNAmt"],
    },
    "invoiceitemdetail": {
        "target": "purchase_invoice_items",
        "classification": "fully_imported",
        "reason": "Purchase invoice line items. PayQty, FreeQty, Batch, Expiry, Rate, MRP, TaxPer, TaxAmt mapped to purchase_invoice_items.",
        "pk": "ID",
        "relationships": ["VhID -> invoicevhheader.ID", "ItemID -> items.id"],
        "missing_columns": ["RcvdPackQty", "TotalLooseQty", "SaleRate", "ChallanID"],
    },
    "invoicevhdetail": {
        "target": "ledger_transactions",
        "classification": "fully_imported",
        "reason": "Double-entry purchase accounting entries mapped to ledger_transactions.",
        "pk": "ID",
        "relationships": ["VhID -> invoicevhheader.ID", "LedID -> account_ledgers.id"],
        "missing_columns": [],
    },
    "invoicevhheader": {
        "target": "purchase_invoices",
        "classification": "fully_imported",
        "reason": "Purchase invoice headers. VoucherNo, InvoiceNo, InvoiceDate, Gross, Tax, Discount, Net mapped to purchase_invoices.",
        "pk": "ID",
        "relationships": ["AcYearID -> financial_years.id", "SuppID -> suppliers.id"],
        "missing_columns": ["DiscountEntered", "DiscountPer", "LessDNAmount", "AddCNAmount"],
    },
    "itemdrugs": {
        "target": "item_ingredients",
        "classification": "fully_imported",
        "reason": "Item-to-drug generic composition and strength mapping.",
        "pk": "ID",
        "relationships": ["ItemID -> items.id", "DrugID -> drugs.id"],
        "missing_columns": [],
    },
    "itemmst": {
        "target": "items",
        "classification": "partially_imported",
        "reason": "Item Master. 943 rows in source; historical duplicates merged under UNIQUE(item_name, unit_id). TaxID preserved as legacy_tax_id.",
        "pk": "ID",
        "relationships": ["UnitID -> units.id", "CompanyID -> companies.id", "PathyID -> items.pathy"],
        "missing_columns": ["SellLoose", "BillCompulsory"],
    },
    "journalvhdetail": {
        "target": "journal_entry_items",
        "classification": "empty_in_source",
        "reason": "Empty in source (0 rows). Supported by journal_entry_items.",
        "pk": "ID",
        "relationships": ["VhID -> journalvhheader.ID", "LedID -> account_ledgers.id"],
        "missing_columns": [],
    },
    "journalvhheader": {
        "target": "journal_entries",
        "classification": "empty_in_source",
        "reason": "Empty in source (0 rows). Supported by journal_entries.",
        "pk": "ID",
        "relationships": ["AcYearID -> financial_years.id"],
        "missing_columns": [],
    },
    "ledger": {
        "target": "account_ledgers",
        "classification": "partially_imported",
        "reason": "Chart of accounts ledgers. 123 rows; 6 system ledgers (Cash, Sales, Purchase, Bank) mapped to system roles.",
        "pk": "ID",
        "relationships": ["GroupID -> gpmst.ID"],
        "missing_columns": ["OpBalSign", "OpBalDate"],
    },
    "ledgeropbal": {
        "target": None,
        "classification": "unsupported_by_current_schema",
        "reason": "Legacy per-financial-year/month opening balance grid (552 rows). The application maintains opening balances directly on account_ledgers.",
        "pk": "ID",
        "relationships": ["LedID -> ledger.ID", "AcYearID -> acyear.ID"],
        "missing_columns": ["All columns (monthly balance matrix not modeled)"],
    },
    "pathymst": {
        "target": "items.pathy",
        "classification": "fully_imported",
        "reason": "Medical system lookup (Allopathy, Ayurvedic, Homeopathic). Stored denormalized directly as text on items.pathy.",
        "pk": "ID",
        "relationships": ["Referenced by itemmst.PathyID"],
        "missing_columns": [],
    },
    "patientmaster": {
        "target": None,
        "classification": "empty_in_source",
        "reason": "Empty in source (0 rows). Patient master not used in retail mode (patient name recorded on bill).",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["All columns"],
    },
    "paymentinvoice": {
        "target": "supplier_payment_allocations",
        "classification": "unsupported_by_current_schema",
        "reason": "Legacy payment-to-invoice allocation grid (2,671 rows). Target schema has supplier_payment_allocations, but historical allocations lack exact matching keys and are reconciled via ledger balances.",
        "pk": "ID",
        "relationships": ["PaymentID -> paymentvhheader.ID", "InvoiceID -> invoicevhheader.ID"],
        "missing_columns": ["AdjAmt", "DiscAmt"],
    },
    "paymentvhdetail": {
        "target": "ledger_transactions",
        "classification": "fully_imported",
        "reason": "Double-entry supplier payment transactions mapped to ledger_transactions.",
        "pk": "ID",
        "relationships": ["VhID -> paymentvhheader.ID", "LedID -> account_ledgers.id"],
        "missing_columns": [],
    },
    "paymentvhheader": {
        "target": "supplier_payments",
        "classification": "fully_imported",
        "reason": "Supplier payment vouchers mapped to supplier_payments with supplier_id resolved via creditor ledger.",
        "pk": "ID",
        "relationships": ["AcYearID -> financial_years.id", "SuppID -> suppliers.id"],
        "missing_columns": ["DiscountEntered", "DiscountPer", "DiscountAmt"],
    },
    "receiptinvoice": {
        "target": "customer_receipt_allocations",
        "classification": "unsupported_by_current_schema",
        "reason": "Legacy receipt-to-bill allocation grid (114 rows). Target schema has customer_receipt_allocations; customer receipts are tracked directly via customer_receipts and ledger balances.",
        "pk": "ID",
        "relationships": ["ReceiptID -> receiptvhheader.ID", "SalesID -> salesvhheader.ID"],
        "missing_columns": ["AdjAmt", "DiscAmt"],
    },
    "receiptvhdetail": {
        "target": "ledger_transactions",
        "classification": "fully_imported",
        "reason": "Double-entry customer receipt transactions mapped to ledger_transactions.",
        "pk": "ID",
        "relationships": ["VhID -> receiptvhheader.ID", "LedID -> account_ledgers.id"],
        "missing_columns": [],
    },
    "receiptvhheader": {
        "target": "customer_receipts",
        "classification": "fully_imported",
        "reason": "Customer receipt vouchers mapped to customer_receipts with customer_id resolved via debtor ledger.",
        "pk": "ID",
        "relationships": ["AcYearID -> financial_years.id", "CustID -> customers.id"],
        "missing_columns": ["DiscountEntered", "DiscountPer", "DiscountAmt"],
    },
    "salescreditnote": {
        "target": None,
        "classification": "unsupported_by_current_schema",
        "reason": "Sales invoice credit note linkage table (530 rows). Mapped through credit notes and ledger transactions.",
        "pk": "ID",
        "relationships": ["SalesID -> salesvhheader.ID", "CreditNoteID -> creditnotevhheader.ID"],
        "missing_columns": ["CNAmt"],
    },
    "salesitemdetail": {
        "target": "sales_invoice_items",
        "classification": "fully_imported",
        "reason": "Sales invoice line items. PackSize, BatchNo, Expiry, MRP, SaleQty (loose units), Rate, Amount mapped to sales_invoice_items.",
        "pk": "ID",
        "relationships": ["VhID -> salesvhheader.ID", "ItemID -> items.id", "BatchNo -> stock_batches"],
        "missing_columns": ["SalesRate", "NetSalesRate", "DiscEntered", "DiscPer"],
    },
    "salesvhdetail": {
        "target": "ledger_transactions",
        "classification": "fully_imported",
        "reason": "Double-entry sales transaction postings mapped to ledger_transactions.",
        "pk": "ID",
        "relationships": ["VhID -> salesvhheader.ID", "LedID -> account_ledgers.id"],
        "missing_columns": [],
    },
    "salesvhheader": {
        "target": "sales_invoices",
        "classification": "fully_imported",
        "reason": "Sales invoice headers (counter sales). BillNo, Date, Customer, Doctor, Discount, Total, Net mapped to sales_invoices.",
        "pk": "ID",
        "relationships": ["AcYearID -> financial_years.id", "CustID -> customers.id", "DoctID -> doctors.id"],
        "missing_columns": ["PatientAddress", "PatientPhone", "DiscountEntered", "DiscountPer", "AddDNAmount", "LessCNAmount"],
    },
    "softmaster": {
        "target": None,
        "classification": "excluded_intentionally",
        "reason": "Legacy software license and pharmacy firm profile details (1 row). The target application stores pharmacy profile separately.",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["FirmName", "Address", "Phone", "DLNo", "GSTNo", "FoodLicNo"],
    },
    "statemst": {
        "target": "customers.state / suppliers.state",
        "classification": "fully_imported",
        "reason": "Indian state lookup (1 row: MAHARASHTRA). Mapped directly to state text on customer/supplier records.",
        "pk": "ID",
        "relationships": ["Referenced by sundaryinfo.StateID"],
        "missing_columns": [],
    },
    "stockadjusted": {
        "target": "stock_batches",
        "classification": "excluded_intentionally",
        "reason": "Historical stock adjustment rows (3,410 rows). Verified: stock adjustments are already reflected inside stockbalance.TotalPurchaseQty; importing would double-count stock.",
        "pk": "ID",
        "relationships": ["ItemID -> items.id", "BatchNo -> stock_batches"],
        "missing_columns": ["AdjustedQty", "AdjustmentReason", "AdjustedDate"],
    },
    "stockbalance": {
        "target": "stock_batches",
        "classification": "fully_imported",
        "reason": "Authoritative historical closing stock balance table (7,806 rows). Quantities mapped to stock_batches.stock_qty in loose units (TotalPurchaseQty - TotalSalesQty).",
        "pk": "ItemID, BatchNo (composite legacy key)",
        "relationships": ["ItemID -> items.id"],
        "missing_columns": ["NetPurRate", "NetSalesRate"],
    },
    "sundaryinfo": {
        "target": "customers / suppliers",
        "classification": "fully_imported",
        "reason": "Sundry debtor/creditor addresses, contact persons, phone numbers, and tax/TIN numbers.",
        "pk": "ID",
        "relationships": ["LedID -> ledger.ID", "StateID -> statemst.ID"],
        "missing_columns": ["CreditPeriod", "DiscountPer", "CreditLimit (mapped where applicable)"],
    },
    "sundrybillbybillopbal": {
        "target": None,
        "classification": "empty_in_source",
        "reason": "Empty in source (0 rows). Bill-by-bill opening balances not present.",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["All columns"],
    },
    "unitmst": {
        "target": "units",
        "classification": "fully_imported",
        "reason": "Packaging unit master (TAB, CAP, SYP, INJ, etc.). Mapped 1:1 to units.",
        "pk": "ID",
        "relationships": ["Referenced by itemmst.UnitID"],
        "missing_columns": [],
    },
    "userinfo": {
        "target": "app_users",
        "classification": "partially_imported",
        "reason": "Legacy user logins (2 rows). Usernames preserved as inactive accounts; legacy password hashes are never imported for security.",
        "pk": "ID",
        "relationships": [],
        "missing_columns": ["UserPassword (intentionally omitted)", "UserType"],
    },
}


def audit_tables() -> dict:
    print(f"Reading source dump: {SOURCE_DUMP}")
    dump = LegacyDump(SOURCE_DUMP)
    src_counts = dump.count_rows()

    conn = sqlite3.connect(f"file:{STAGE_DB.as_posix()}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        target_counts: dict[str, int] = {}
        for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            tname = row[0]
            try:
                cnt = cur.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
                target_counts[tname] = cnt
            except sqlite3.Error:
                pass
    finally:
        conn.close()

    classification_map = {
        "fully_imported": "Fully imported",
        "partially_imported": "Partially imported",
        "excluded_intentionally": "Excluded intentionally",
        "unsupported_by_current_schema": "Unsupported by current schema",
        "unresolved_mapping": "Unresolved mapping",
        "empty_in_source": "Empty in source",
    }

    results = []
    category_summary: dict[str, int] = {k: 0 for k in classification_map.values()}
    total_source_rows = sum(src_counts.values())

    for tbl in sorted(dump.table_columns):
        src_rows = src_counts.get(tbl, 0)
        cols = dump.table_columns[tbl]
        meta = TABLE_METADATA.get(tbl, {
            "target": None,
            "classification": "unresolved_mapping",
            "reason": "Unmapped legacy table",
            "pk": "Unknown",
            "relationships": [],
            "missing_columns": [],
        })

        cls_code = meta["classification"]
        if src_rows == 0:
            cls_code = "empty_in_source"

        cls_label = classification_map[cls_code]
        category_summary[cls_label] += 1

        target_name = meta["target"]
        tgt_rows = None
        if target_name and target_name in target_counts:
            tgt_rows = target_counts[target_name]

        results.append({
            "source_table": tbl,
            "source_columns_count": len(cols),
            "source_columns": cols,
            "source_row_count": src_rows,
            "target_table": target_name,
            "target_row_count": tgt_rows,
            "classification": cls_label,
            "reason": meta["reason"],
            "primary_key": meta["pk"],
            "relationships": meta["relationships"],
            "missing_columns_in_target": meta["missing_columns"],
        })

    out = {
        "audit_timestamp": datetime.now().isoformat(),
        "source_dump": {
            "path": str(SOURCE_DUMP),
            "size_bytes": SOURCE_DUMP.stat().st_size,
            "total_tables": len(dump.table_columns),
            "total_rows": total_source_rows,
        },
        "target_database": {
            "path": str(STAGE_DB),
            "size_bytes": STAGE_DB.stat().st_size,
        },
        "classification_summary": category_summary,
        "tables": results,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Source table audit saved to {OUT_JSON}")
    print("\nClassification Summary:")
    for cat, cnt in category_summary.items():
        print(f"  {cat}: {cnt} tables")
    return out


if __name__ == "__main__":
    audit_tables()
