# Pharmacy Management System — Full Application Data Integrity Audit

**Audit Timestamp**: 2026-10-20  
**Database Audited**: `staging/pharmacy_staging.db` (SHA-256: `49cc9c21f83258838e9ec7b458bcae6bed25c48206fb0cbce3da9908649f70d5`)  
**Production Database Status**: `data/pharmacy.db` strictly guarded & read-only (SHA-256: `338aeb0ef427789f5d729cffaa3a36354f0b0360c6aee3679f89cf4905904e75`)  

---

## 1. Executive Summary & Diagnostic Findings

A comprehensive, application-wide audit was conducted across all **46 screen modules** (`screens/*.py`) and **50 Data Access Objects (DAOs)** (`database/*.py`).

Rather than isolated UI bugs, the audit identified **8 shared infrastructure and schema root causes** responsible for incorrect, missing, mismatched, or unexpected data across multiple pages:

1. **Title Bar Staging Masking** (`ui/main_window.py`): Navigating menus overwrote the title bar with static `APP_TITLE`, masking the `[STAGING / AUDIT MODE]` indicator and causing user confusion about which database was active.
2. **Expiry Date Misinterpretation in StockDAO** (`database/stock_dao.py`): `StockDAO._is_expired` and `StockDAO.get_expiring` split on `'/'` expecting `MM/YY`. Migrated legacy batches are stored in ISO format `YYYY-MM-DD` (all 7,808 rows). `_is_expired` caught `ValueError` and returned `False` for every batch, hiding all 1,549 expired batches on `StockMasterPage`.
3. **Stock Batch Availability Disparity in Sales Returns** (`database/stock_dao.py` & `screens/credit_note.py`): `StockDAO.get_stock_batches_for_item` strictly filters `WHERE stock_qty > 0`. When a customer returns an item that is sold out (0 stock on hand), the batch dropdown is empty, preventing entry of the return voucher.
4. **Party Balance Divergence Across Screens** (`database/customer_receipt_dao.py` & `database/supplier_payment_dao.py`): `CustomerReceiptDAO.get_customer_balance` and `SupplierPaymentDAO.get_supplier_balance` calculate balances purely as transactions minus payments, omitting `account_ledgers.opening_balance`. In contrast, `PartyWiseReportDAO` and `LedgerReportDAO` include opening balances, causing an apparent discrepancy for any party with an opening balance (e.g. Anand Pharma showing ₹198,364 on payment voucher vs ₹208,767 on ledger).
5. **Fragile Non-Numeric Pack Size Conversion** (`database/purchase_dao.py`): `pack_factor(pack_size)` performs `float()`. Real-world packaging strings (`"10'S"`, `"1*10"`, `"10TAB"`) raise `ValueError` and default to `1.0`, multiplying stock by 1 instead of pack size.
6. **Numeric Batch Numbers Mistaken for IDs** (`screens/counter_sale.py` & others): Manufacturers routinely use purely numeric batch numbers (e.g., `"133"`, `"001"`, `"640"`, `"1461"`). There are 1,042 pure numeric batches in `stock_batches` and 21,728 in `sales_invoice_items`. Autocomplete popups auto-selected these, leading users to believe internal database IDs were being displayed.
7. **Lexicographical Table Sorting on Formatted Monetary Amounts** (`screens/stock_master.py` & others): Inserting formatted text strings (`f"{val:.2f}"`) into `QTableWidgetItem` causes alphabetical sorting (`"100.00"` < `"20.00"`).
8. **Target Item ID vs Legacy Item ID Cognitive Confusion** (`screens/item_master.py`): Target item IDs are 946–1885, whereas legacy item IDs were 1–944. The Item Master table displayed internal database primary keys in column 0, causing confusion for staff familiar with legacy item numbers.

---

## 2. Root Cause Analysis Matrix

| ID | Common Component | Root Cause Description | Affected Screens | Evidence / Supporting Data |
|---|---|---|---|---|
| **RC-1** | `ui/main_window.py` | Window title reset on menu change | All 46 screens | Title bar reverted from `[STAGING / AUDIT MODE]` to `Pharmacy Management System v1.0.0 -- New Bill` |
| **RC-2** | `database/stock_dao.py` | `_is_expired` expects `MM/YY`, fails on `YYYY-MM-DD` | `stock_master.py`, stock search | `StockDAO.search(stock_status="Expired")` returns 0; `StockReportsDAO` finds 1,549 expired batches |
| **RC-3** | `database/stock_dao.py` | `get_stock_batches_for_item` filters `stock_qty > 0` | `credit_note.py` | Sold-out items cannot be returned because batch combo is empty |
| **RC-4** | `database/*_receipt_dao.py` | Receipt/Payment balance queries omit ledger opening balance | `customer_receipt.py`, `supplier_payment.py`, `party_wise_report.py`, `*_ledger.py` | Supplier 158 (Anand Pharma) balance ₹198,364 on voucher vs ₹208,767 on ledger (diff = ₹10,403 opening bal) |
| **RC-5** | `database/purchase_dao.py` | `pack_factor` fails on non-numeric strings (`"10'S"`, `"1*10"`) | `purchase_invoice.py`, stock reports, profit calculation | `pack_factor("10's")` returned `1.0` instead of `10.0` |
| **RC-6** | `screens/counter_sale.py` | Single-batch popup & numeric batch confusion | `counter_sale.py`, `sales_history.py` | Batch `"133"` verified as genuine manufacturer batch from invoices #5596 & #5669 |
| **RC-7** | `screens/stock_master.py` | String formatting in table item causes lexicographical sorting | `stock_master.py`, `sales_history.py` | High-value items sort incorrectly under Qt `setSortingEnabled(True)` |
| **RC-8** | `screens/item_master.py` | Table column 0 displays internal target primary key | `item_master.py` | Item 944 (`MERSILK NW 5010`) displays ID 1885 |

---

## 3. Verified Artifacts Created

The following machine-readable audit deliverables have been generated in `migration_backups/`:
- `migration_backups/full_application_data_integrity_matrix.csv`: 46 screens cataloged with domain, DAOs, batch/expiry handling, sorting risks, and integrity status.
- `migration_backups/full_application_data_integrity_audit.json`: Structural audit summary with root cause catalog.
- `migration_backups/full_application_data_integrity_exceptions.json`: Full list of exceptions cataloged by screen, severity, and description.

---

## 4. Next Implementation Steps (Post-Approval)

1. **RC-2 Fix**: Standardize `_is_expired()` and `get_expiring()` in `database/stock_dao.py` to use `parse_expiry()` from `database/expiry_report_dao.py`, supporting both `YYYY-MM-DD` and `MM/YY`.
2. **RC-3 Fix**: Add `include_zero_stock=True` parameter to `StockDAO.get_stock_batches_for_item` and invoke it in `screens/credit_note.py`.
3. **RC-4 Fix**: Update `CustomerReceiptDAO.get_customer_balance` and `SupplierPaymentDAO.get_supplier_balance` to include `account_ledgers.opening_balance` so balances match the general ledger.
4. **RC-5 Fix**: Upgrade `pack_factor` in `database/purchase_dao.py` with regex extraction to robustly handle `"10'S"`, `"1*10"`, `"10TAB"`, etc.
5. **RC-7 Fix**: Set numeric values on `Qt.EditRole` / `Qt.UserRole` for proper table column sorting.
6. **RC-8 Fix**: Add legacy ID display/search capability in `screens/item_master.py`.
