# Counter Sale Batch Integrity & Selection Resolution Report

## 1. Executive Summary

This report documents the thorough investigation, root-cause isolation, code remediation, and automated verification for the reported Counter Sale defects:
1. **Verification of the running database** and investigation of the window title bar lacking `[STAGING / AUDIT MODE]`.
2. **Deep-dive investigation of the screenshot entries**:
   - `STASHPain` — batch `133`
   - `LUMIA 2K` — batch `GKH0615A`
   - `ARTHRASPAZ 4MG` — batch `CUM03ADB`
   - `PANTORET DSR` — batch `LC-8615`
   - `TENDOMAC` — batch `MML/26/006`
3. **Root cause analysis of the blank Batch entry field** while `TENDOMAC` remained in the item field.
4. **Correction of Counter Sale batch selection, validation, and editing behavior**.
5. **Comprehensive regression test suite** verifying 10 critical batch handling scenarios.

---

## 2. Verification of the Running Database & Window Title

### Exact Database Path Identification
Inspection of `database/connection.py`, `launch_staging.py`, `run_staging.ps1`, and the active SQLite files confirms:
- **Default Resolution**: In `database/connection.py`, `get_db_path()` returns `os.environ.get("PHARMACY_DB") or _default_db_path()`. In development mode, `_default_db_path()` resolves to `data/pharmacy.db`.
- **Active Database State**: Inspection of `data/pharmacy.db` showed:
  - File size: `45,350,912 bytes`
  - Record counts: `items: 940`, `purchase_invoices: 5723`, `sales_invoices: 72176`, `credit_notes: 1354`, `stock_batches: 7808`.
  - Auth logs: User `pratap` logged in at `13:00:59 UTC` (18:30 local).
  - Business transactions: Contains latest invoice #72184 (Bill No `2015`) created by user for patient `MR NASIR ATTAR` on 2026-10-20.
- **Staging Database State** (`staging/pharmacy_staging.db`):
  - File size: `45,350,912 bytes`
  - SHA-256: `49cc9c21f83258838e9ec7b458bcae6bed25c48206fb0cbce3da9908649f70d5` (100% byte-identical to post-migration state).
  - Record counts: `items: 940`, `purchase_invoices: 5723`, `sales_invoices: 72175`, `credit_notes: 1354`, `stock_batches: 7808`.

### Why the Screenshot Showed `Pharmacy Management System v1.0.0 -- New Bill`
Two contributing factors were identified:
1. **Direct Application Launch**: The user session captured in the screenshot was launched via `python main.py` or the standard desktop shortcut, where `PHARMACY_DB` was not set, thus opening `data/pharmacy.db`.
2. **Title Overwrite Defect in `ui/main_window.py`**:
   - `ui/main_window.py` previously executed `from version import APP_TITLE` at module import time.
   - When any menu item was clicked (e.g. `Sales -> New Bill`), `_on_menu_action` executed:
     ```python
     self.setWindowTitle(f"{APP_TITLE}  -  {action}")
     ```
   - Because `APP_TITLE` was bound at import time to the static string `"Pharmacy Management System v1.0.0"`, any dynamic override (such as `version.APP_TITLE = staging_title` in `launch_staging.py`) was wiped out as soon as the user navigated to `New Bill`!
   - **Remediation**: Implemented dynamic `_get_window_title(action)` in `ui/main_window.py` that checks `os.environ.get("PHARMACY_STAGING_MODE") == "1"`. In staging mode, the title permanently retains `[STAGING / AUDIT MODE]`.

---

## 3. Investigation of the Exact Screenshot Entries

Every displayed entry was queried against `stock_batches`, `purchase_invoice_items`, `purchase_invoices`, `legacy_id_map`, and the source legacy SQL dump `PharmaWinner202610201418.sql`.

| Medicine Name | Target Item ID | Legacy Item ID | Stored Batch ID | Stored Batch No | Expiry Date | Current Stock | Batch MRP | Source SQL Dump Provenance |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **STASHPain** | 1689 | 746 | **7059** | **`133`** | 2027-09-30 | 13.0 units | 126.00 | `stockbalance`: `(746, '133', '2027-09-30', 126, 96, 84, 42, 1, 189, 29)`. `invoiceitemdetail`: lines 12081 & 12232. |
| **LUMIA 2K** | 1712 | 769 | **7023** | **`GKH0615A`** | 2027-05-31 | 28.0 units | 115.31 | `stockbalance` & `invoiceitemdetail` match `GKH0615A`, Expiry 2027-05-31. |
| **ARTHRASPAZ 4MG** | 1646 | 703 | **7803** | **`CUM03ADB`** | 2028-07-31 | 50.0 units | 249.00 | `invoiceitemdetail` & `stockbalance` match `CUM03ADB`, Expiry 2028-07-31. |
| **PANTORET DSR** | 1738 | 795 | **7158** | **`LC-8615`** | 2028-04-30 | 88.0 units | 120.00 | Purchase #5677 from Royal Medical Hub LLP; dump matches `LC-8615`. |
| **TENDOMAC** | 1351 | 408 | **7094** | **`MML/26/006`** | 2028-04-30 | 18.0 units | 462.00 | Purchases #5629, #5678, #5693; dump matches `MML/26/006`. |

### Crucial Finding on Batch `133`
- Batch `133` is **NOT an internal database primary key**; the internal database primary key is `id = 7059`.
- Batch `133` is **NOT an item ID**; the target item ID is `1689` (legacy ID `746`).
- Batch `133` is **NOT a mapping artifact**; it is the **actual manufacturer batch number** printed on the physical packaging and billed by supplier Shriniwas Agencies on invoice 7465 (dated 2026-07-13) and invoice 11610 (dated 2026-08-31).
- The manufacturer of Stashpain uses sequential short-number batches: "24", "27", "28", "30", "32", "33", "35", "36", "37", "38", "39", "40", "41", "43", "44", "45", "46", "49", "51", "52", "55", "57", "58", "6", "62", "64", "65", "66", "68", "69", "69.", "8", "069", "100", "110", "133", "142", "151", "160", "165", "192".
- Therefore, displaying `"133"` in Counter Sale is **100% accurate and correct**.

---

## 4. Root Cause: Why the Batch Entry Field Was Blank for `TENDOMAC`

When the user added `TENDOMAC` (or selected it in the item combo), the Batch entry field remained blank. The root causes were isolated:

1. **The Single-Batch Popup Suppression Defect**:
   - In `screens/counter_sale.py`, `_focus_batch()` was defined as:
     ```python
     def _focus_batch(self):
         self.batch_combo.lineEdit().setFocus()
         if self.batch_combo.count() > 1:
             self.batch_combo._show_completion_popup()
     ```
   - Notice the strict inequality `> 1`.
   - When an item has **exactly 1 batch** (like `TENDOMAC`, which has only batch `MML/26/006`), `self.batch_combo.count()` is 1.
   - `1 > 1` evaluated to `False`, so `_show_completion_popup()` was **suppressed**.
2. **Mandatory Unselected Initial State (Rule 5)**:
   - When an item is selected, `_on_item_changed` deliberately sets `self.batch_combo.setCurrentIndex(-1)` and clears `self.batch_combo.lineEdit()`.
   - This prevents silently auto-selecting the first batch.
3. **Compound Effect**:
   - Because `setCurrentIndex(-1)` cleared the field and `_show_completion_popup()` was suppressed for single-batch items, the Batch entry field sat completely blank.
   - None of the dependent fields (Expiry, MRP, Stock, Pack Size, Amount) could populate because `currentIndex` was `-1`.
   - Pressing Enter in the empty line edit did nothing because `_KeyboardCombo` saw an empty string with no popup visible.
   - Clicking `+ Add` caused validation to reject with `"Please select an item and batch."`
   - To the operator, it appeared as though `TENDOMAC` had missing batches or a broken batch lookup.

---

## 5. Summary of Code Changes

### 1. `screens/counter_sale.py`
- **Fixed `_focus_batch`**: Changed `if self.batch_combo.count() > 1:` to `if self.batch_combo.count() >= 1:`. For single-batch items, the completion popup now opens automatically on focus, displaying the batch number, expiry, MRP, and stock, allowing the operator to select it with Enter or a click.
- **Added Dynamic Placeholders**:
  - When an item has available batches: `line_edit.setPlaceholderText("Select batch")`.
  - When an item has zero available stock: `line_edit.setPlaceholderText("No stock available")`.
- **Strict Batch-to-Item Ownership Validation**:
  - In `_ItemEntryBar.get_current_data()`: Added assertion that `batch["item_id"] == item_id`.
  - In `_SalePanel._on_add_item()`: Added check rejecting addition if `batch["item_id"] != data["item_id"]`.
- **Implemented Bill Line Editing (`edit_row`) & Restoration (`restore_row`)**:
  - Added `_ItemEntryBar.restore_row(row)`: Restores an existing line's exact item, exact batch, expiry, MRP, pack size, quantity, and discount without silently substituting a different batch.
  - Added `_SalePanel.edit_row(idx)`: Removes the row from the table and restores it into the entry bar for modification.
  - Connected `self._table.doubleClicked` to `_on_table_double_clicked` so double-clicking any row in the Bill Items table loads it into the entry bar for editing.

### 2. `ui/main_window.py`
- Implemented `_get_window_title(action: str)`: Dynamically checks `os.environ.get("PHARMACY_STAGING_MODE") == "1"`.
- When in staging mode, the window title preserves `[STAGING / AUDIT MODE]` across all page transitions and menu clicks (e.g. `Pharmacy Management System [STAGING / AUDIT MODE] v1.0.0 - New Bill`).

---

## 6. Regression Test Suite & Verification Results

A dedicated test suite [`test_counter_sale_batch_integrity.py`](file:///c:/Users/Nilesh/OneDrive/Desktop/Pharmacy Management System/test_counter_sale_batch_integrity.py) was implemented covering all required scenarios:

| Test Case | Description | Result |
| :--- | :--- | :---: |
| `test_01_numeric_alphabetic_mixed_batches` | Verifies numeric batch `'133'` is displayed as `'133'` (not ID `7059`). | **PASS** |
| `test_02_single_batch_item_opens_popup` | Verifies single-batch item (`TENDOMAC`) opens completion popup on focus and allows explicit selection. | **PASS** |
| `test_03_multi_batch_item_selection` | Verifies multi-batch item (`LUMIA 2K`) allows choosing between batches with differing MRPs. | **PASS** |
| `test_04_item_selection_without_batch` | Verifies item selection without batch keeps Batch empty and prevents adding to bill. | **PASS** |
| `test_05_switching_items_clears_stale_data` | Verifies switching items invalidates previous batch and clears MRP, Expiry, Stock, and Amount. | **PASS** |
| `test_06_add_several_items_different_batches` | Verifies adding 4 items with numeric, alphabetic, and alphanumeric batches preserves identities. | **PASS** |
| `test_07_edit_and_restore_line_details` | Verifies double-clicking a bill table row restores exact batch, MRP, and expiry for editing. | **PASS** |
| `test_08_empty_stock_item_displays_placeholder` | Verifies item with 0 stock shows `"No stock available"` placeholder and blocks selection. | **PASS** |
| `test_09_prevent_item_batch_mismatch` | Verifies `get_current_data()` rejects a batch belonging to a different item ID. | **PASS** |
| `test_10_staging_branding_title_preservation` | Verifies `_get_window_title("New Bill")` preserves `[STAGING / AUDIT MODE]`. | **PASS** |

### Execution Output
```
Ran 10 tests in 2.625s

OK
```

All 10 tests pass completely. In addition, existing test suites (`test_counter_sale_mrp_and_batch_fixes.py`, `test_counter_sale_edit_dialog.py`, and `test_legacy_refresh_verification.py`) were executed and verified passing.

---

## 7. Safety & Promotion Status

- **Staging Database** (`staging/pharmacy_staging.db`): Verified intact (`49cc9c21f83258838e9ec7b458bcae6bed25c48206fb0cbce3da9908649f70d5`, integrity ok, 0 foreign key violations).
- **Active Database** (`data/pharmacy.db`): Contains 72,176 sales (migrated data + live user test sale 72184).
- **Executable**: No packaged binaries or dist artifacts were modified.
- **Safety Gate**: Staging was NOT modified during this bug fix. All fixes apply cleanly to both staging and live environments.
