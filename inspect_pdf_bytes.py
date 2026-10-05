"""Byte-level inspection of a generated Sales Bill PDF.

Parses the raw content stream to prove:
  * no rule is drawn as a long diagonal
  * every text run sits inside the page box
  * the page height follows the content instead of a fixed sheet
"""

import re
import sys
from pathlib import Path

PT_PER_MM = 72.0 / 25.4

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"C:\Users\savan\AppData\Local\Temp\real_sales_bill.pdf")
data = path.read_bytes()

box = re.search(rb"/MediaBox \[([^\]]+)\]", data).group(1).split()
width_pt, height_pt = float(box[2]), float(box[3])
print(f"file            : {path}  ({len(data)} bytes)")
print(f"valid PDF       : {data.startswith(b'%PDF')}  "
      f"ends with %%EOF: {data.rstrip().endswith(b'%%EOF')}")
print(f"page size       : {width_pt:.2f} x {height_pt:.2f} pt = "
      f"{width_pt / PT_PER_MM:.1f} x {height_pt / PT_PER_MM:.1f} mm")
print()

print("rule (separator) commands:")
diagonals = 0
for match in re.findall(rb"([\d.]+) ([\d.]+) m ([\d.]+) ([\d.]+) l S", data):
    x0, y0, x1, y1 = (float(v) for v in match)
    delta_y = abs(y1 - y0)
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if delta_y > 2.0:
        diagonals += 1
    verdict = "DIAGONAL" if delta_y > 2.0 else "horizontal"
    print(f"  ({x0:7.2f},{y0:7.2f}) -> ({x1:7.2f},{y1:7.2f})"
          f"   len={length:6.2f}pt  dy={y1 - y0:5.2f}  {verdict}")
print()
print(f"DIAGONAL LINES  : {diagonals}")
print()

runs = re.findall(
    rb"BT /F(\d) ([\d.]+) Tf 1 0 0 1 ([\d.]+) ([\d.]+) Tm \((.*?)\) Tj ET", data)
# The "Page N of M" stamp is chrome, not bill content: exclude it when judging
# layout gaps and the trailing blank area.
body = [r for r in runs if not r[4].startswith(b"Page ")]
xs = [float(r[2]) for r in body]
ys = [float(r[3]) for r in body]
print(f"text runs       : {len(body)} content runs (+{len(runs) - len(body)} page stamp)")
print(f"x range         : {min(xs):.2f} .. {max(xs):.2f} pt   (page width {width_pt:.2f})")
print(f"y range         : {min(ys):.2f} .. {max(ys):.2f} pt   (page height {height_pt:.2f})")
inside_x = all(0 <= x <= width_pt for x in xs)
inside_y = all(0 <= y <= height_pt for y in ys)
print(f"all inside page : x={inside_x}  y={inside_y}")
print()
# Vertical gaps between successive text baselines: an overlap shows up as a
# near-zero gap; a correct stack shows regular positive gaps.
ordered = sorted({round(y, 1) for y in ys}, reverse=True)
gaps = [round(ordered[i] - ordered[i + 1], 1) for i in range(len(ordered) - 1)]
print(f"text baselines  : {ordered}")
print(f"vertical gaps   : {gaps}")
print(f"min gap (pt)    : {min(gaps) if gaps else 'n/a'}  -> "
      f"{'STACKED (no overlap)' if not gaps or min(gaps) >= 5.0 else 'POSSIBLE OVERLAP'}")
# PDF y is measured from the BOTTOM of the page, so the blank space below the
# lowest text is simply that lowest baseline.
blank_bottom = min(ys)
print()
print(f"blank below last content: {blank_bottom:.2f} pt "
      f"({blank_bottom / PT_PER_MM:.1f} mm, bottom margin is "
      f"{5.0:.1f} mm) -> "
      f"{'tight receipt' if blank_bottom / PT_PER_MM < 14 else 'large blank area'}")