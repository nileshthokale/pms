"""Crop + magnify regions of an acceptance screenshot for visual inspection.

Usage:  python -m tools_screenshot_crop <png> <x> <y> <w> <h> <scale> <out.png>
"""
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QGuiApplication

app = QGuiApplication(sys.argv)
src, x, y, w, h, scale, out = sys.argv[1:8]
img = QImage(src)
print("source size:", img.width(), "x", img.height())
crop = img.copy(QRect(int(x), int(y), int(w), int(h)))
big = crop.scaled(crop.width() * int(scale), crop.height() * int(scale),
                  Qt.KeepAspectRatio, Qt.FastTransformation)
big.save(out)
print("wrote", out, big.width(), "x", big.height())
