# Phase 6E — Pharma-WINNER Style UI Redesign

**Scope:** Counter Sale product-entry and UX improvements. No database
schema, SalesDAO transaction flow, PostingEngine, accounting, stock,
purchase, GST, reporting, permission, authentication, backup/restore,
import, financial-year or printing logic was changed. ItemDAO's read-side
product list now includes linked generic names for autocomplete search.

---

## 1. Target visual style

The application was moved away from the black/dark theme to a traditional
Windows pharmacy/accounting desktop look:

- light desktop application, white main workspace
- very light blue panels, page-header strips, filter bars and table
  header rows
- soft blue-grey borders
- compact controls and dense information layout
- clear table grids with visible grid lines
- rectangular, traditional desktop buttons
- small/medium, installed system fonts (`Segoe UI`)
- minimal decoration: no large modern cards, no oversized rounded
  corners, no large empty black areas

Reference: the supplied old Pharma-WINNER application screenshot was used
as the structural/visual reference. No old branding, licence text,
company details or proprietary identifiers were copied. The application
keeps its own name, **Pharmacy Management System**.

## 2. Reference / current state

- Target reference: first supplied screenshot (old Pharma-WINNER style).
- Before: second supplied screenshot (dark theme, large dark areas).
- After: light, dense, traditional desktop layout as described here.

## 3. Theme architecture

Single source of truth: `ui/theme.py`.

- `_PALETTES` holds two complete palettes, `"light"` (default) and
  `"dark"` (night mode). `"night"` is accepted as a legacy alias.
- `DEFAULT_MODE = "light"`; `_load_mode()` returns the persisted mode and
  falls back to `light` when the file is missing or corrupt.
- `palette()` returns the active palette. The legacy contract keys used
  by every screen remain: `bg`, `surface`, `border`, `accent`,
  `accent_hover`, `text`, `text_dim`.
- Phase 6E adds richer tokens used by the shared components:
  `surface_alt`, `table_header`, `header_text`, `grid`, `selected`,
  `selected_text`, `accent_pressed`, `success`, `success_hover`,
  `danger`, `danger_hover`, `warning`, `warning_hover`, `focus`,
  `disabled_text`, `disabled_bg`.
- `nav_palette()` returns the navigation chrome colours per mode.
- `stylesheet()` returns one application-wide Qt stylesheet
  (window/dialog, inputs, combo/date, buttons incl. hover/pressed/
  disabled/focus, tables + grid + selection, headers, menus, tooltips,
  scrollbars). It is applied to the `QApplication`, so dialogs and
  unstyled screens follow the same theme; per-widget stylesheets in the
  screens always take precedence.
- `ThemeManager` persists the mode to `data/theme.json`, reloads the
  screen modules on change, and notifies listeners. The main window
  rebuilds its page stack so every page re-renders in the new mode.

### Light palette (key values)

| Token | Value | Use |
| --- | --- | --- |
| `bg` | `#ffffff` | window workspace, table bodies, inputs |
| `surface` | `#dce9f6` | page header strip, filter bars, table header row, panels |
| `surface_alt` | `#f3f8fc` | summary panels / zebra rows |
| `border` | `#9db6cc` | soft blue-grey borders + grid lines |
| `grid` | `#c5d4e2` | table grid lines |
| `accent` | `#2f6fb0` | primary actions, selection |
| `accent_hover` | `#255d94` | primary hover |
| `text` | `#14212e` | dark navy primary text |
| `text_dim` | `#55677a` | secondary text |
| `selected` | `#cfe2f3` | selected row / focus fill |
| `success` / `danger` / `warning` | `#2e7d32` / `#b23a3a` / `#b26a00` | restrained semantic colours |

## 4. Reusable components — `ui/components.py`

Style helpers (read the palette at call time, so they follow the mode):

- `label_style`, `title_style`, `section_title_style`
- `edit_style`, `combo_style`, `date_style`, `spin_style`,
  `checkbox_style`, `group_box_style`
- `btn_primary_style`, `btn_secondary_style`, `btn_success_style`,
  `btn_danger_style`, `btn_warning_style`, plus aliases
  (`BTN_GREEN`, `BTN_PRIMARY`, `BTN_SAVE`, `BTN_SECONDARY`,
  `BTN_GRAY`, `BTN_DANGER`, `BTN_ORANGE`, …)
- `table_style`, `table_header_style`, `style_data_table`
- `style_edit`, `style_combo`, `style_date`, `style_label`
- `polish_page` — central compact-table treatment applied by the main
  window to every page (visible grid, compact row height, row
  selection, consistent header)

Widgets:

- `PageHeader` — consistent light-blue page header strip
- `ActionButton` — primary/secondary/success/danger/warning button
- `FilterBar`, `SearchBar`, `FormSection`, `SummaryPanel`, `StatusLabel`

Reuse: the navigation bar, main window, login dialog, Cash Book, Bank
Book, User Management, Import Data, Financial Year and others import
`ui.components`; the remaining screens consume the same centralized
palette through `ui.theme.palette()`, so colours are not duplicated per
screen.

## 5. Main window and navigation

`ui/navigation_bar.py` now renders traditional desktop chrome:

```
┌──────────────────────────────────────────────────────────────┐
│ Pharmacy Management System   FY 2026-2027   admin/ADMIN  ☀ Day Mode  Logout │
├──────────────────────────────────────────────────────────────┤
│ Sales  Purchase  Account  Reports  Master                    │
└──────────────────────────────────────────────────────────────┘
```

- Menus: Sales, Purchase, Account, Reports, Master — unchanged contents
  and the same `menu_action_triggered(menu, action)` signal, so every
  existing page still opens exactly as before.
- Financial-year indicator: `FY <name>` (from
  `financial_year.ensure_default_financial_year()`).
- Current user: `username / role` from `auth.session`.
- `Logout`: confirms, calls `auth.session.logout()`, then re-runs the
  login dialog (closing the window if the user cancels).
- Day/Night toggle kept; label shows the action ("Day Mode"/"Night
  Mode").

`ui/main_window.py`:

- default size 1366×760, minimum 1024×640 (desktop-first; comfortable
  from 1366×768 to 1920×1080)
- applies the application-wide stylesheet on start and on theme change
- `ui.polish_page()` applied to every page for consistent tables
- keeps the existing page map (including the exact "User Master" and
  "Account Group" wiring) and permission checks.

## 6. Page headers

Every major page has one consistent header strip: light-blue
background, dark title, compact height, subtle bottom border. Pages that
already had a header now inherit the light-blue `surface`; Cash Book,
Bank Book, User Management, Import Data and Financial Year were given an
explicit `PageHeader`.

## 7. Tables

Applied consistently to Purchase History, Sales History, Counter Sale
History, Stock, Customer, Supplier, Item, Reports, Cash Book, Bank Book,
Day End, Account Ledger, Trial Balance, P&L, Balance Sheet, GST Report,
Hold Bill, Category and User Management:

- white table body (`bg`)
- visible grid lines (`gridline-color: border`, `setShowGrid(True)`)
- light-blue/grey header row (`table_header`)
- compact rows (`ROW_HEIGHT = 22`) and reduced cell padding
- readable dark text; row selection with accent background
- responsive column sizing (`Stretch`/`ResizeToContents`) with
  horizontal scrolling where a report genuinely needs it
- soft outer border instead of a borderless table

## 8. Forms and controls

- labels: dark text, left aligned
- inputs: white background, thin blue-grey border, compact height,
  visible focus border
- combo boxes / date edits: standard desktop appearance, compact
- buttons: traditional rectangular, blue primary / light-blue secondary
  / restrained red destructive, compact dimensions
- disabled buttons use the theme's muted colours; focus is visible

## 9. Transaction screens

Sales Bill, Counter Sale, Purchase Invoice, Credit Note, Debit Note,
Customer Receipt, Supplier Payment and Journal Entry keep their dense
structure — header fields → item-entry area → item table → totals →
action buttons — and inherit the light theme, grid tables and compact
controls. No transaction behaviour changed.

## Counter Sale Layout Fix

The Counter Sale page previously showed the bill history table with a
stretch factor of 1, so an empty history consumed the whole window and
the sale form lived in a large centered modal. The page was rebuilt as a
**fixed three-region desktop layout** with a fixed right-side bill panel.

### Layout structure

```
CounterSalePage
├── Region A header strip      "Sales / Counter Sale"        [New Sale]
├── body (QHBoxLayout)
│   ├── LEFT (QVBoxLayout, expanding)
│   │   ├── history table       Region A — controlled height (fixed)
│   │   ├── item entry bar      Region B — fixed 70 px, two compact rows
│   │   ├── current bill table  Region C — expanding (stretch 1)
│   │   ├── bill/customer strip Sale Header + Customer/Doctor (fixed)
│   │   └── totals + actions    Totals · Hold Bill · Save Sale · Cancel
│   └── RIGHT bill panel        fixed 236 px
│       ├── "Bill":     Edit / Delete / Print / PDF
│       └── "Current Bill":  Bill Total · CNo · Amount
```

### Fixed history region

`_apply_history_height()` sets the history table to a **fixed height** of
~28 % of the page height, clamped to 130–280 px, and re-applies it on
`resizeEvent`/`showEvent`. Because the height is fixed (min == max), an
empty history table can never expand into a giant blank area and adding
history rows can never grow the region — the table scrolls instead.

### Fixed active sale-entry region

The active sale-entry controls live in `_ItemEntryBar`, which has a fixed
70 px height and two compact rows: Item / Batch / Qty / Discount / Add,
then Pack / Location / Expiry / MRP / Available / Amount. This widget is
the first widget of the inline `_SalePanel`, so it sits directly underneath
the history table. There is no stretch factor
above it and no vertical centering anywhere in the left column, so the
entry region stays pinned to the top of the lower region.

### Expanding current bill table

`_SalePanel` puts the current bill table in a `QGroupBox` added with
stretch factor 1. It is the only expanding region: it absorbs all
remaining vertical space and grows/shrinks on window resize, while the
history, entry, bill/customer strip and totals regions keep their fixed
heights.

### Right-side bill panel

A fixed-width (236 px) panel spans the full page height with a light-blue
background and a left border. It contains the history actions
(Edit / Delete / Print / PDF, acting on the selected history row) and a
live "Current Bill" read-out (Bill Total, CNo, Amount) fed by the panel's
`totals_changed` signal. It never overlaps the tables.

### Inline New Sale / Edit / Resume

* **New Sale** resets the inline form (new bill number, current date/time,
  empty item table, default customer), keeps the sale area in the same
  Region B position and moves focus to Item Name.
* **Edit** loads the selected bill into the same inline area
  (`_SalePanel.load_invoice`); permission checks and DAO calls unchanged.
* **Resume** from Hold Bill loads through
  `open_sale_dialog_with_hold()` into the same Region B area
  (`_SalePanel.load_hold`).
* The sale logic itself was only *relocated* from `_SaleDialog` into
  `_SalePanel`; `_SaleDialog` remains as a thin modal wrapper for
  compatibility. `_open_sale_dialog()` is kept as a compatibility entry
  point that now drives the inline panel.

### Resize behaviour

Verified at 1366×768, 1600×900 and 1920×1080: the page honors each requested
width, the fixed 236 px bill panel remains visible, and no entry control
extends beyond the sale region. The two-row entry region stays fixed at
70 px and directly below Bill History. Adding bill or history rows does
not move it; only the current bill table absorbs the remaining height.

## 10. Reports

Reports use header → filters → action buttons → summary → large white
report table. The existing report cards/summary labels were restyled
through the palette rather than replaced by dashboard cards. Report
filters, calculations and exports are untouched.

## 11. Typography

- font family: installed system font `Segoe UI` (fallback `Tahoma`,
  `sans-serif`); no external font downloads
- main menu / labels / table / buttons: ~9 pt
- page titles: ~12–14 pt bold
- table headers: ~9 pt bold

## 12. Window sizes

Optimised for 1366×768, 1600×900 and 1920×1080. Tables expand with
stretch columns; forms keep their fields visible; horizontal scrolling
only where a wide report requires it; the layout uses the full window.

## 13. Light / night mode

- Light mode is the default (`DEFAULT_MODE = "light"`, and the persisted
  `data/theme.json` was reset to `light`).
- Night mode is preserved with its original dark/green look and remains
  togglable; switching reloads the screen modules, rebuilds the page
  stack and re-applies the application stylesheet. It does not touch any
  business logic. The theme round-trip is covered by a headless smoke
  test (light → dark → light).

## 14. Accessibility / usability

- readable contrast (dark navy text on white / light blue)
- visible keyboard focus borders
- obvious selected rows (accent/light-blue fill)
- clearly disabled buttons
- tooltips on navigation actions and financial-year/user indicators
- standard Windows desktop interaction patterns retained

## 15. Testing

Baseline (recorded before the redesign): 1,730 tests.

After the redesign the full suite is run twice with `python run_tests.py`
(see the Phase 6E report for the exact results). Changed Python files are
byte-compiled with `py_compile`, and a headless (`QT_QPA_PLATFORM=offscreen`)
smoke test instantiates all 35 pages plus the navigation bar and performs
a light→dark→light theme round-trip.

Focused Counter Sale layout tests live in `test_counter_sale_layout.py`
(13 GUI tests, skipped only when PySide6 is unavailable):

| # | Test | Checks |
| --- | --- | --- |
| 01 | `test_01_history_region_has_controlled_height` | history height fixed, within bounds |
| 02 | `test_02_empty_history_does_not_fill_the_page` | empty history stays compact |
| 03 | `test_03_entry_region_is_directly_below_history` | entry sits under the history |
| 04 | `test_04_entry_region_is_not_vertically_centered` | entry pinned near the top, compact |
| 05 | `test_05_bill_table_expands_below_entry` | bill table grows with the window |
| 06 | `test_06_right_bill_panel_exists` | fixed Bill / Current Bill panel |
| 07 | `test_07_adding_an_item_does_not_move_entry_region` | item add does not shift the entry |
| 08 | `test_08_history_rows_do_not_move_entry_region` | history rows do not shift the entry |
| 09 | `test_09_resize_preserves_region_order` | order stable at all three sizes |
| 10 | `test_10_new_sale_resets_and_focuses_active_area` | New Sale resets + focuses Item Name |
| 11 | `test_11_existing_buttons_remain` | all existing actions still present |
| 12 | `test_12_hold_resume_loads_into_inline_sale_area` | Hold/Resume uses the same Region B |
| 13 | `test_13_save_wiring_still_calls_sales_dao` | `SalesDAO.insert_invoice` payload unchanged |

## Counter Sale Keyboard Navigation

The active sale-entry bar keeps the existing three-region layout and uses one
editable Qt combo with one completer for Item and one for Batch. Matching
migrated records appear in the field-associated popup; placeholder rows are
skipped during keyboard navigation.

- `Down` and `Up` move the highlighted suggestion, including deterministic
  first/last-row boundary behavior.
- `Enter` accepts the highlighted Item or Batch suggestion.
- `Escape` closes the active popup and leaves focus on its input field.
- `Tab` accepts an open suggestion popup and advances through Item, Batch,
  Quantity, Discount, and Add in that order.
- Selecting Item loads available batches and moves focus to Batch.
- Selecting Batch fills Pack, Expiry, MRP, and Stock and moves focus to Qty.
- `Enter` in Quantity or Discount activates Add. A successful Add refreshes
  the bill totals and returns focus to Item for continuous keyboard billing.

The keyboard contract is covered by `test_counter_sale_keyboard.py`, including
real migrated-style item and batch records, mouse selection, popup reuse,
focus transitions, and the full Item -> Batch -> Qty -> Discount -> Add flow.

Test-infrastructure notes (not part of the UI redesign):

- `openpyxl` is required by the existing XLSX import tests and was
  installed into the project virtual environment.
- A missing `from PySide6.QtCore import QDate` import in
  `test_profit_loss.py` (used by its UI date-filter test) was added.
- `print_pdf` now raises `DocumentPrintError` for a non-existent file,
  matching its existing contract/test; generation behaviour for valid
  documents is unchanged.
- `Day End`'s summary line states "Read-only summary." to match its
  documented read-only behaviour/test.

## 16. Visual inspection

The application was to be inspected at 1366×768, 1600×900 and 1920×1080
across the Main Window, Counter Sale, Sales Bill, Purchase Invoice, Item
Master, Customer, Supplier, Stock Report, Trial Balance, Cash Book, Bank
Book, Day End and User Management, checking for clipping, overlap,
leftover black backgrounds, inconsistent tables/buttons/headers and
unused empty space. A headless instantiation pass verified every page
constructs without error in the new theme.

Counter Sale screenshots were captured at 1366×768, 1600×900 and
1920×1080 for five states — (A) empty history, (B) after New Sale,
(C) one item, (D) multiple items, (E) populated history — and the entry
region's y position was asserted unchanged between the empty and populated
states at every resolution.

## 17. Limitations

- No dedicated screenshot-based pixel regression harness exists; visual
  verification uses the headless page-instantiation smoke test, the
  focused layout assertions and offscreen screenshots.
- When a page is enlarged far beyond 1920×1080, wide transaction tables
  may still require horizontal scrolling by design.
- Night mode intentionally keeps the original dark/green palette rather
  than a blue-tinted dark variant.
- The Counter Sale bill/customer header fields sit in a compact strip
  above the totals bar (rather than above the item-entry row) so the
  entry region can stay directly beneath the history, as required.

## 18. System boundaries

Database schema, SalesDAO transaction flow, PostingEngine, accounting
posting, stock persistence, historical data, GST, report queries,
permissions, authentication, backup/restore, import, financial-year
logic, printing/document generation, and Hold Bill persistence remain
unchanged. Product search adds a read-only generic-name field to the
existing ItemDAO result; no product codes are present in the current item
schema.

## Product Search

The existing Item Name combo now opens its product popup on click, including
when the field is empty. Typing filters the 938-product migrated catalog
immediately with case-insensitive partial matching. Search terms include
item name and linked generic/drug names from `item_ingredients`; the current
database has no product-code column. An unmatched query displays
`No products found` as a non-committing status row. Selection retains the
database item ID rather than using display text as identity.

## Keyboard Navigation

Item and Batch use their existing local Qt completers and widget key event
handling. Up/Down move through the popup, Enter accepts a real suggestion,
Escape closes it, and Tab advances to the next entry control. A successful
Add returns focus to Item Name. Quantity and Discount Enter activate Add;
the layout's tab chain is Item, Batch, Quantity, Discount, Add.

Two Qt details are part of this contract:

- **Keys are routed through the combo's focus proxy.** An editable
  `QComboBox` reports itself as the focus widget (its line edit is only the
  focus *proxy*), so a physical keyboard delivers its key events to the
  combo rather than to the line edit. `_KeyboardCombo` therefore installs
  its own event filter on the combo as well as on the line edit and on the
  completer popup, so all three targets share one contract: Up/Down open or
  move the list (the list opens with a row already highlighted), Enter
  accepts, Escape closes, Tab accepts and advances. Enter is always
  consumed so it can never be swallowed by `QComboBox`'s own dropdown
  handling, and rows without a role value (`-- Select --`,
  `-- Select Batch --`, `No products found`) are never selectable, while
  plain choice lists such as sale type (which store no role value at all)
  keep all their rows selectable.
- **Tab order is declared on the combo widgets.** Because the line edits are
  focus proxies, Qt skips them during focus traversal, so declaring
  `setTabOrder(lineEdit, lineEdit)` dropped Batch out of the chain and Tab
  jumped from Item straight to Quantity. The chain is now declared as
  `item_combo -> batch_combo -> qty_edit -> discount_edit -> add_btn`,
  which traversal follows as Item, Batch, Quantity, Discount, Add.

## Batch Selection

The existing stock-batch DAO supplies batch number, expiry, pack-level MRP,
and stock; Location is read from the selected item master. The light,
scrollable popup is bounded to the application window; selecting a batch
fills location, expiry, MRP, and currently available stock. The read-only
Amount preview recalculates from unit price, quantity, and discount. No batch
values are hard-coded.

`SalesDAO.get_stock_batches_for_item()` keeps its existing filter
(`stock_qty > 0`) and its existing expiry order, but now returns **sellable
batches first and expired batches last**. The sort only reorders rows that
were already returned (nothing is added, removed or rewritten) and is needed
because migrated expiry values mix `YYYY-MM-DD` with legacy `MM/YY`, so
ordering by expiry alone put long-expired stock (for example `2014-04-30`)
at the top of the popup. With expired rows moved to the end, the keyboard
chain `Batch -> Down -> Enter` always lands on a batch that can be sold,
while expired batches stay visible for reference and are still refused by
the existing Add/save guard ("Batch … is expired. Cannot sell expired
stock.").

## Live Draft Stock

Unsaved quantities are reserved only in the active sale's in-memory rows.
The selected batch's availability is recalculated from stored stock minus
draft reservations after Add, merge, delete, clear, and resume. No stock
write occurs until the existing Save Sale transaction.

## Same Batch Merge

Adding the same item ID and stock-batch ID updates that existing bill row's
quantity, discount, and amount. Different batch IDs stay on separate rows;
deleting the row releases its entire draft reservation immediately.

## Unit/Tablet Selling

The production database was inspected read-only. Its relevant table counts
were 938 items, 7,765 stock batches, 11,829 purchase lines, and 232,715
historical sale lines. The legacy purchase schema distinguishes
`PayPackQty`/`FreePackQty` from `TotalLooseQty`; migration preserves the pack
quantities in purchase history, while the closing batch balance comes from
`TotalPurchaseQty - TotalSalesQty`. For example, a Pack Size 15 purchase can
record 5 paid packs and 75 loose units.

A read-only cross-check of all 4,717 multipack batches with purchase history
found zero exact matches for unscaled pack-count subtraction and 2,687 exact
matches for `purchase pack count * Pack Size - sale quantity`. The remaining
2,030 batches do not reconcile to either simple formula, so legacy balance
exceptions are retained rather than normalized. This supports individual
units as the stock quantity for the new counter-sale workflow, without
claiming every historical batch is internally consistent.

Historical sale rows have no explicit pack-versus-unit flag. Of 186,946
multipack sale lines, 186,939 gross line amounts match `MRP / Pack Size` per
quantity, two match full MRP per quantity, and five are exceptions. New
Counter Sale entries follow the verified dominant tablet convention: Qty 1
means one unit, and unit price is pack-level MRP divided by Pack Size. No
historical purchase, sale, or stock row is converted or rewritten.

## Save Validation

An empty, non-numeric, non-finite, zero, negative, or over-available sale
quantity is rejected before Add. Save rechecks every row's item/batch
identity, expiry, positive quantity, and aggregate current stock before
calling the unchanged transactional SalesDAO. It also rejects invalid or
negative paid amounts and bill discounts outside 0 through the bill total.
A failure focuses the relevant entry control and writes no invoice, stock,
or accounting rows. The existing Customer * requirement remains; Patient
Name and Doctor remain optional.

## Counter Sale UI Improvements

### Counter Sale Item Bar and Footer Polish

The Counter Sale page finishes as one dense, desktop-oriented billing
workspace: a single-row item entry bar, an expanding Bill Items grid, and one
fixed bottom billing section. Only visual layout changed — no database,
DAO, stock, accounting, posting, Hold Bill, permissions, financial year,
keyboard-navigation or transaction logic was touched.

#### Item entry sizing

The entry bar is a fixed 34 px row holding all twelve controls in order
(CNo, Item, Batch, Pack, Loc, Exp, MRP, Avail, Qty, Disc, Amt, + Add).

- Every control is pinned to one shared box height, measured at build time
  from the tallest natural height the platform asks for. Windows renders a
  styled combo one pixel taller than a styled line edit; unifying them keeps
  the row visually straight instead of hard-coding a number that would be
  wrong on another machine.
- Widths are content-based, not uniform: CNo 34 px fixed, Item 150–300 px,
  Batch 96–200 px, Pack 46 px, Loc/Exp/Avail 52–110 px, MRP 56–110 px,
  Qty 48 px, Disc 52–110 px, Amount 58–120 px.
- Spare width is distributed by stretch weight: Item leads (3) because it is
  the primary search field, Batch is next (2), and the read-outs share the
  rest. Item is deliberately capped at 300 px — on a 1920-wide monitor it
  stays clearly the widest control without becoming a banner across the bar,
  and the width it gives up goes into the other fields so the row fills
  evenly. A trailing stretch keeps `+ Add` flush against the right edge once
  every field has hit its maximum.
- `+ Add` is a compact fixed 78 px button — inside the 70–90 px target, with
  the same box height as the entry controls and no oversized padding.
- Captions are 10 px and measured from the real font, then capped at 26 px,
  with a 3 px right margin so each label clears its field by 4–6 px and never
  reserves a wide, mostly empty box that would steal width from the fields.
- Numeric controls (Pack, MRP, Avail, Qty, Disc, Amount) are right-aligned.
  All read-only fields keep `Qt.NoFocus`, so the existing
  Item → Batch → Qty → Discount → Add keyboard chain is untouched.

#### Table and row-action sizing

- Bill Items rows are 28 px high with a 32 px header band, visibly centred
  text, a light-blue selected-row treatment and visible blue-grey grid lines.
- Columns use fixed, content-based widths (`#` 34, Pack Size 82, Location
  106, Batch No 150, Expiry 76, MRP 76, Qty 54, Disc Amt 84, Amount 96,
  Del 72) and only **Item Name** stretches. Long item names and long batch
  numbers therefore widen the name column instead of pushing the numeric
  columns out of view or forcing a horizontal scrollbar.
- `#`, Expiry and Del headers/cells are centred; MRP, Qty, Disc Amt and
  Amount headers/cells are right-aligned.
- The per-row `Delete` is a compact table action: 56 × 22 px (inside the
  50–65 px width target), 10 px bold text, a restrained red edge on the
  light surface, and pinned inside a full-cell filler widget so it is
  centred both horizontally and vertically. Delete behaviour is unchanged.

#### Footer structure

The bottom billing section is fixed at ~98 px total and reads as one
organised block, separated from Bill Items by a subtle top border.

- **Sale Header strip** (54 px): two *independent* rows rather than one
  shared column grid, so neither row is squeezed by the other.
  Row 1 is the bill identity — Bill No 112, Date 112, Time 70, Type 110,
  each with balanced content-sized widths and a trailing stretch.
  Row 2 gives Customer (min 200), Patient (min 150) and Doctor (min 160) the
  full remaining width. All seven controls share one 22 px box height via
  compact styles that use the same colours, fonts and borders as the entry
  bar with 2 px instead of 4 px vertical padding.
- **Totals / actions row** (44 px): LEFT — Total Items (64 px, compact),
  Total Amt 96, Customer Saving 100, Round Off 92, NET AMT 112 (emphasised
  in the accent colour at 13 px), Paid 96. RIGHT — Hold Bill 96, Save Sale
  104 (primary), Cancel 86, all 26 px high and sharing the entry bar's
  button metrics.

#### Responsive desktop behaviour

Only Bill Items expands vertically. The History → Entry Bar → Bill Items →
Sale Header → Totals + Actions order is fixed, and neither the entry bar nor
the footer moves when the bill holds 0, 1, 5 or 20 lines. At 1366x768,
1600x900 and 1920x1080 the entry bar's twelve controls stay inside the bar,
the Bill Items grid fits without horizontal scrolling, and every footer
control remains fully visible with no clipping or overlap.

#### Right bill panel

Unchanged in size (236 px) and content. Its Edit / Delete / Print-PDF buttons
now share the 26 px box height used elsewhere, so they read as one group.

The existing three-region Counter Sale layout, fixed entry position, and
right-side bill panel are retained. The old Counter Sale-only From/To/
Customer/Filter row remains absent. Item and Batch popups use an explicit
white/light-blue palette even when the application night theme is active,
with compact Segoe UI text and scroll limits; other pages and their filters
are unchanged. Bill History loads 200 invoices at a time with one joined DAO
query; scrolling to the end fetches older invoices without changing the table
or history actions.

## Real-Desktop Acceptance Test

`temp/desktop_acceptance.py` runs the real `PharmacyMainWindow` on the real
Qt desktop platform (no `QT_QPA_PLATFORM`) against the migrated production
database, which is opened read-only for every check. It performs no Save
Sale and no Hold Bill, and every major table's row count is compared before
and after the run.

The required chain is executed with key events delivered to
`QGuiApplication.focusObject()` — the exact object a physical keyboard
targets:

```
type "BIO" -> Down -> Enter -> batch Down -> Enter -> Tab -> Qty 1
    -> Tab -> Discount -> Enter -> Add  (again: merge)  -> Delete -> no save
```

Result: **61/61 checks passed** — live filtering (9 of 938 products in about
100 ms), the `No products found` status row, popup placement and light
theme, focus moving Item -> Batch -> Qty, auto-filled Pack / Expiry / MRP /
Available, add -> same-batch merge -> delete with draft availability moving
20 -> 19 -> 18 -> 20 while stored `stock_qty` stayed 20, no invoice row
written, no unexpected dialog, and unchanged production row counts.

Two findings from that run are worth recording because they are properties
of the migrated data, not of the screen:

1. The alphabetically first `BIO` match (BIO D3 FEM) has three batches and
   **all three are expired** (2014 / 2017 / 2018). The canonical chain
   selects it, its batches are listed, and Add is correctly refused with
   "Batch … is expired. Cannot sell expired stock."; the script then steps
   down to the first match that has sellable stock (BIO D3 PLUS) and
   continues the same chain there. This is the expired-batch guard working
   on real data, not a failure of the keyboard flow.
2. Of BIO D3 PLUS's four sellable batches, two hold a single unit, so the
   script targets the batch with enough stock for the two-unit merge demo
   (14255775A, 20 units). The over-stock message itself
   ("Only N units are available for this batch.") is covered by the unit
   tests.
