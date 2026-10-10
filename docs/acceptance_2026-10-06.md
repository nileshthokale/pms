# Acceptance Verification — 2026-10-06

Follow-up to `docs/final_desktop_acceptance.md` (2026-10-05, verdict NOT READY, 5 blockers).
This report records the exact outcome of the five assigned items. Categories used:
**PASS** · **BLOCKED — ENVIRONMENT** · **BLOCKED — OWNER ACCOUNTING DECISION** · **FAIL**.

**Method.** Direct code inspection, live Qt probing (`QT_QPA_PLATFORM=offscreen` for
widget geometry; real `QPrinterInfo` for printer discovery), PDF byte measurement,
and test runs. This agent cannot view images: no screenshot or paper output was
visually inspected. All layout verdicts are geometry arithmetic (`QFontMetrics`,
widget rects, PDF MediaBox), not eye inspection.

**Code changed in this session (accounting rules untouched, no fake equity):**

| File | Change |
|---|---|
| `test_a6_pharmacy_printing.py` (`test_83`) | Stale environment assumption fixed (see §1) |
| `database/pharmacy_a6_receipt.py` (`supported_page_size_mm`) | Genuine defect fixed: `size.size(size.Millimeter)` raised `AttributeError` for every entry and was swallowed, so the function always returned `[]`. Now uses `QPageSize.Millimeter` and returns the printer's real size list |
| `screens/counter_sale.py` (`bill_no_edit`) | `setFixedWidth(112)` → `setFixedWidth(220)` so the full FY bill number reads in full (see §3) |

---

## 1. Single test failure — PASS (fixed, verified)

Full suite before the fix: **2,757 tests, 1 failure** at
`test_a6_pharmacy_printing.py:582`:

```python
def test_83_default_printer_is_not_hard_coded(self):
    name = a6.default_printer_name()
    self.assertNotIn("Canon", name)   # line 582
```

Failure output: `AssertionError: 'Canon' unexpectedly found in 'Canon LBP2900'`.

**Root cause.** The test asserted something about the *environment* (that no Canon
printer is the OS default) instead of something about the *code*. The
implementation is correct:

```python
def default_printer_name() -> str:
    """The Windows default printer, never hard-coded."""
    ...
    return str(QPrinterInfo.defaultPrinterName() or "")
```

It delegates to the OS and contains no vendor string. Determination:

- **A. TRUE — the test incorrectly assumed Canon is absent.** Installing the real
  Canon LBP2900 (now the Windows default) broke the assertion.
- **B. TRUE — detection works:** `available_printers()` returns
  `['OneNote (Desktop)', 'Microsoft Print to PDF', 'Canon LBP2900']` and
  `default_printer_name()` returns `'Canon LBP2900'`. The newly installed
  printer is detected correctly.
- **C. FALSE — the application/print path is not wrong.** `print_pharmacy_a6_bill`
  never calls `setPrinterName` and contains no `Canon`/`LBP2900` string
  (guarded by `test_101`); it uses the Qt page layout and the print dialog's
  printer choice.

**Fix (test only, deterministic, platform-safe, not disabled).** `test_83` now
guards the hard-code requirement against *source* (`inspect.getsource`: no
`Canon`/`LBP2900`, must delegate to `QPrinterInfo.defaultPrinterName`), asserts
the return type is `str`, and proves environment-independent detection with
mocked `QPrinterInfo.defaultPrinterName` returning `"Canon LBP2900"` and `""`.
The A6 verification itself is unchanged and still enforced by `test_84`
(no vendor string in the module), `test_100` (`setPageLayout`), and `test_101`
(no forced printer name).

**Reruns.**

| Scope | Result |
|---|---|
| Focused A6 (`test_a6_pharmacy_printing`) | **103 tests, OK** |
| Full suite (`run_tests.py`) | **Ran 2,757 tests, OK — 0 failures** |

---

## 2. Real Canon A6 acceptance — BLOCKED — ENVIRONMENT (physical step only)

Printer state measured live via `QPrinterInfo`:

| Check | Result |
|---|---|
| Printer detected | **PASS** — `Canon LBP2900` in `available_printers()` (3 printers total) |
| Default printer | **PASS** — `default_printer_name() == 'Canon LBP2900'`, nothing hard-coded |
| Print job generated (app path, simulated to PDF via `QPrinter` + `draw_pages_on_painter`) | **PASS** — valid PDF produced |
| Saved-PDF page size | **PASS** — MediaBox `297.64 × 419.53 pt` = **105.0 × 148.0 mm** |
| Print-job page size | **PASS** — MediaBox `297 × 420 pt` = **104.8 × 148.2 mm portrait** (Qt whole-point rounding, −0.2 mm width; driver-level, negligible) |
| Portrait, no landscape | **PASS** — profile `105.0 × 148.0 Portrait`, `QPageLayout` orientation `Portrait`, height > width on both outputs |
| Automatic content-height shrinking | **PASS (absent)** — `content_profile()` is the identity function; every page emits the full sheet (this also resolves the 2026-10-05 finding where pages shrank to 105 × 50.75 mm) |
| Clipping / overlap | **PASS** — `validate_pages` passes; layout-model overlap checks green (tests 65–67, renderer tests 7–9); all PDF text inside the page box |
| Unexpected scaling | **PASS** — profile `scale_percent == 100`; print path uses `printer.setPageLayout(A6 layout)`, no ad-hoc scaling |
| Receipt content readable | **PASS (byte-level)** — item name, batch, bill title and amounts present in the PDF stream; body fonts ≥ 6 pt per tests 74–75 |
| **Physical output 105 × 148 mm on paper** | **BLOCKED — ENVIRONMENT — no paper was printed or measured by this agent. Physical PASS is NOT claimed.** |

**Operator note (environment, not code).** The Canon driver reports 15 page sizes
and has **no native A6 entry** (closest is custom `109.0 × 148.2 mm` labelled
`bills`). The application always submits an explicit A6 layout, but the person
printing must select the matching A6/custom paper in the Canon driver dialog;
otherwise the driver itself may scale or clip. The required human step is: print
one Counter Sale bill on the LBP2900, measure the sheet (must be 105 × 148 mm
portrait), and confirm the content reads without shrinkage, clipping, or
rotation.

---

## 3. Counter number `2026-2027-Cash-0015` — PASS (with one disclosed limitation)

Measured: the value needs **209 px** at the 11 px label font
(`QFontMetrics.horizontalAdvance`).

| Rendering | Result |
|---|---|
| `Bill No` metadata field (`bill_no_edit`, now fixed 220 px) | **PASS** — full `2026-2027-Cash-0015` visible, no clipping, zero row overlaps at 1366×768 and 1920×1080, 11 px readable |
| Tooltip support | **PASS** — retained (`setToolTip(full value)` in `set_cno`) |
| Adjacent-control overlap | **PASS** — geometry audit at both resolutions: no overlaps |

**Disclosed limitation (design constraint, not a defect fix).** The entry-row
`CNo` mirror stays compact (109 px, ellipsis + full tooltip). Widening it to fit
209 px was attempted and reverted because it violates four enforced layout
contracts verified by test: the Item field must stay the widest entry control
and the 12-control row must fit at 1366×768 (`test_01_item_is_the_widest_entry_control`,
`test_04_row_fits_at_1366x768`, `test_06b_item_is_the_expanding_widest_field` ×2 —
all four failed with a 220 px mirror, all pass with the compact mirror). The
authoritative, fully readable rendering is the `Bill No` field; the mirror's
ellipsis+tooltip is its documented overflow-safe behaviour.

---

## 4. Balance sheet — BLOCKED — OWNER ACCOUNTING DECISION

No accounting rules changed. No equity invented. Live DAO readout
(`BalanceSheetDAO.get_totals()` on `data/pharmacy.db`, 2026-10-06):

| Item | Result |
|---|---|
| Migrated equity ledgers (groups `Equity`/`Capital`) | **0** — query returns `NONE` |
| Total Assets | **₹14,342,485.97** live (2026-10-05 snapshot: ₹14,341,727.47; Δ +₹758.50 from live postings between snapshot and this run) |
| Total Liabilities | **₹7,590,615.22** (matches snapshot exactly) |
| Total Equity | **blank / 0** — `get_equity()` returns `[]`; no legitimate equity balance available |
| Report status | **UNBALANCED**, difference **₹6,751,870.75** |
| P&L treatment | **Not rolled into equity under the documented design** — `Sales` (₹−22,719,985.12), `Purchase` (₹15,695,070.37) and `DISCOUNT RECEVIED` sit in `unclassified`; the DAO states *"No P&L-to-equity mechanism is defined yet"* |

This stays an **OWNER DECISION / DATA BLOCKER** until the owner provides
legitimate opening capital/equity data or approves the documented accounting
treatment. Nothing was modified to make the report balance.

---

## 5. Final status

### NOT READY — 2 open items (neither is an application defect fix away)

| # | Item | Category |
|---|---|---|
| 1 | §1 test failure | **PASS** — fixed and green (2,757/2,757) |
| 2 | Canon A6: detection, job generation, geometry, readability | **PASS** |
| 2b | Canon A6: physical paper observed at 105 × 148 mm | **BLOCKED — ENVIRONMENT** — needs a human print + ruler check |
| 3 | Counter number fully rendered + tooltip kept | **PASS** (mirror limitation disclosed) |
| 4 | Balance sheet balances | **BLOCKED — OWNER ACCOUNTING DECISION** — needs legitimate opening equity data or approved treatment |
| — | Visual appearance sign-off | **BLOCKED — ENVIRONMENT** — this agent cannot view images; no screenshot or printout was eye-inspected. A human must review the GUI and the test print |

**Strongly verified this session:** full automated suite 2,757/2,757 green ·
A6 profile exactly 105 × 148 mm portrait at 100% on both output paths ·
Canon LBP2900 detected as system default with no hard-coded printer names ·
counter suites (layout/entry/input/readability/popup, 223 tests) green ·
production accounting logic untouched.

**Not claimed:** physical print PASS · visual/readability-by-eye acceptance ·
any equity figure.
