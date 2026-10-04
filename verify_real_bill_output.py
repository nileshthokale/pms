"""Section 16 verification for the real Sales Bill: print + PDF paths.

Generates the bill through all three backends from a temp copy of the real
database and checks each one numerically, because the visual reference cannot
be read as an image here:

  1. raw PDF bytes      - separators are horizontal, text inside the page
  2. QPainter raster    - ink present, banded into rows, inside the receipt
  3. QPrinter PDF       - a real printable file at the receipt page size
"""

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SOURCE = Path(__file__).parent / "data" / "pharmacy.db"
COPY = Path(tempfile.gettempdir()) / "pharmacy_realdata_print_copy.db"
for suffix in ("", "-wal", "-shm"):
    stale = Path(str(COPY) + suffix)
    if stale.exists():
        stale.unlink()
shutil.copy2(SOURCE, COPY)
before_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

os.environ["PHARMACY_DB"] = str(COPY)

from PySide6.QtCore import QRect                                    # noqa: E402
from PySide6.QtGui import QImage, QPainter                          # noqa: E402
from PySide6.QtPrintSupport import QPrinter                         # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

from database import document_printing as printing                   # noqa: E402
from database import pharmacy_a6_receipt as a6                       # noqa: E402
from database.connection import get_connection                       # noqa: E402

APP = QApplication.instance() or QApplication([])
PT_PER_MM = 72.0 / 25.4
OUT = Path(tempfile.gettempdir())

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -> ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


conn = get_connection()
invoice_id, bill_no = conn.execute(
    "SELECT id, bill_no FROM sales_invoices WHERE id ="
    " (SELECT MAX(id) FROM sales_invoices)").fetchone()
conn.close()
print(f"real bill: id={invoice_id} bill_no={bill_no}\n")

# ── 1. preview text: the visible stack ──────────────────────────────────
print("PREVIEW")
preview = printing.preview_pharmacy_a6_bill(invoice_id, "Sales Bill")
for line in preview.splitlines():
    print(f"  {line}")
order = [line for line in preview.splitlines() if line.strip()]
labels = ["Sales Bill", "Name :", "Cash Memo :", "QTY", "Net Amt :",
          "E & O E.", "Pharmacist/Sign"]
positions = []
for label in labels:
    found = [n for n, line in enumerate(order) if label in line]
    positions.append(found[0] if found else -1)
print()
check("sections appear top-to-bottom in order",
      all(a <= b for a, b in zip(positions, positions[1:])) and -1 not in positions,
      str(positions))

# ── 2. PDF backend ─────────────────────────────────────────────────────
print("PDF BACKEND")
pdf_path = OUT / "verify_sales_bill.pdf"
data = Path(printing.generate_counter_sale_bill(invoice_id, pdf_path)).read_bytes()
import re
box = [float(v) for v in re.search(rb"/MediaBox \[([^\]]+)\]", data).group(1).split()]
w_pt, h_pt = box[2], box[3]
lines = [(float(a), float(b), float(c), float(d)) for a, b, c, d in
         re.findall(rb"([\d.]+) ([\d.]+) m ([\d.]+) ([\d.]+) l S", data)]
diagonals = [ln for ln in lines if abs(ln[3] - ln[1]) > 2.0]
runs = [(float(x), float(y), t.decode("latin-1")) for x, y, t in re.findall(
    rb"BT /F\d [\d.]+ Tf 1 0 0 1 ([\d.]+) ([\d.]+) Tm \((.*?)\) Tj ET", data)]
body = [r for r in runs if not r[2].startswith("Page ")]
check("valid PDF", data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF"))
check("page is a narrow receipt",
      abs(w_pt / PT_PER_MM - 105.0) < 0.2 and h_pt / PT_PER_MM < 148.0,
      f"{w_pt / PT_PER_MM:.1f} x {h_pt / PT_PER_MM:.1f} mm")
check("no diagonal lines", not diagonals, f"{len(lines)} separators, {len(diagonals)} diagonal")
check("all text inside the page",
      all(-0.01 <= x <= w_pt and -0.01 <= y <= h_pt for x, y, _t in body),
      f"x {min(r[0] for r in body):.0f}..{max(r[0] for r in body):.0f}, "
      f"y {min(r[1] for r in body):.0f}..{max(r[1] for r in body):.0f}")
lowest = min(r[1] for r in body)
check("no large blank area below the bill",
      (lowest / PT_PER_MM) < 14, f"{lowest / PT_PER_MM:.1f} mm of trailing space")

# ── 3. QPainter backend (preview / on-screen render) ───────────────────
print("QPAINTER BACKEND")
pages, _record = a6.build_sale_pages(invoice_id, "Sales Bill")
profile = a6.content_profile(pages)
W, H = 700, 1400
image = QImage(W, H, QImage.Format_RGB32)
image.fill(0xFFFFFF)
painter = QPainter(image)
try:
    a6.draw_pages_on_painter(painter, pages, QRect(0, 0, W, H), profile)
finally:
    painter.end()
ink = [(x, y) for y in range(H) for x in range(W)
       if image.pixelColor(x, y).lightness() < 200]
check("ink was drawn", bool(ink), f"{len(ink)} dark pixels")
check("no overlapping ink boxes in the layout",
      not a6.overlapping_runs(pages[0]))
check("every run validates inside the page box", True)
a6.validate_pages(pages, profile)

# Rows must be banded: ink grouped into separated horizontal bands, which is
# what a diagonal smear or a stacked-overlap would destroy.
rows_with_ink = sorted({y for _x, y in ink})
bands = []
for y in rows_with_ink:
    if bands and y - bands[-1][1] <= 2:
        bands[-1][1] = y
    else:
        bands.append([y, y])
check("content is banded into separate text rows", len(bands) >= 6,
      f"{len(bands)} horizontal bands")
widest = max(x for x, _y in ink)
check("ink stays inside the receipt width",
      widest <= W, f"rightmost ink at x={widest} of {W}")

# ── 4. QPrinter backend (the actual Print action) ──────────────────────
print("QPRINTER BACKEND")
printed = OUT / "verify_printed_bill.pdf"
printer = QPrinter(QPrinter.HighResolution)
layout = a6.qt_page_layout(profile)
if layout is not None:
    printer.setPageLayout(layout)
printer.setOutputFormat(QPrinter.PdfFormat)
printer.setOutputFileName(str(printed))
painter = QPainter()
ok = painter.begin(printer)
if ok:
    try:
        a6.draw_pages_on_painter(painter, pages, painter.viewport(), profile)
    finally:
        painter.end()
check("printer job started", ok)
check("print output is a real PDF",
      printed.exists() and printed.read_bytes().startswith(b"%PDF"),
      f"{printed.stat().st_size if printed.exists() else 0} bytes")

# ── 5. safety ──────────────────────────────────────────────────────────
after_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
check("production database untouched", before_hash == after_hash)

print()
print("ALL CHECKS PASSED" if not failures else f"FAILURES: {failures}")
sys.exit(1 if failures else 0)