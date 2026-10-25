from PySide6.QtWidgets import QApplication
import sys
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QImage, QPainter, QColor, QPen
from PySide6.QtCore import QRectF, Qt
from PIL import Image
import numpy as np

# Test 1: Baseline (standard 700)
img1 = QImage(800, 150, QImage.Format_ARGB32)
img1.fill(QColor('white'))
p1 = QPainter(img1)
p1.setRenderHint(QPainter.Antialiasing, True)
p1.setRenderHint(QPainter.TextAntialiasing, True)
f1 = QFont('Arial', -1)
f1.setPointSizeF(8.5)
f1.setBold(True)
p1.setFont(f1)
p1.setPen(QColor('#000000'))
p1.drawText(QRectF(20, 20, 760, 40), Qt.AlignLeft | Qt.AlignVCenter, 'BIO D3 PLUS   KBC2402A   31/12/2026   QTY 1   AMT 20.00')
p1.end()
img1.save('scratch/test_base.png')

# Test 2: Weight 800 (ExtraBold) + 1px horizontal overdraw
img2 = QImage(800, 150, QImage.Format_ARGB32)
img2.fill(QColor('white'))
p2 = QPainter(img2)
p2.setRenderHint(QPainter.Antialiasing, True)
p2.setRenderHint(QPainter.TextAntialiasing, True)
f2 = QFont('Arial', -1)
f2.setPointSizeF(8.5)
f2.setWeight(QFont.Weight.ExtraBold)
p2.setFont(f2)
p2.setPen(QColor('#000000'))
r2 = QRectF(20, 20, 760, 40)
p2.drawText(r2, Qt.AlignLeft | Qt.AlignVCenter, 'BIO D3 PLUS   KBC2402A   31/12/2026   QTY 1   AMT 20.00')
p2.drawText(r2.translated(1.0, 0.0), Qt.AlignLeft | Qt.AlignVCenter, 'BIO D3 PLUS   KBC2402A   31/12/2026   QTY 1   AMT 20.00')
p2.end()
img2.save('scratch/test_extrabold_overdraw.png')

# Test 3: Weight 900 (Black) + 1px overdraw
img3 = QImage(800, 150, QImage.Format_ARGB32)
img3.fill(QColor('white'))
p3 = QPainter(img3)
p3.setRenderHint(QPainter.Antialiasing, True)
p3.setRenderHint(QPainter.TextAntialiasing, True)
f3 = QFont('Arial', -1)
f3.setPointSizeF(8.5)
f3.setWeight(QFont.Weight.Black)
p3.setFont(f3)
p3.setPen(QColor('#000000'))
r3 = QRectF(20, 20, 760, 40)
p3.drawText(r3, Qt.AlignLeft | Qt.AlignVCenter, 'BIO D3 PLUS   KBC2402A   31/12/2026   QTY 1   AMT 20.00')
p3.drawText(r3.translated(1.0, 0.0), Qt.AlignLeft | Qt.AlignVCenter, 'BIO D3 PLUS   KBC2402A   31/12/2026   QTY 1   AMT 20.00')
p3.end()
img3.save('scratch/test_black_overdraw.png')

arr1 = np.array(Image.open('scratch/test_base.png').convert('L'))
arr2 = np.array(Image.open('scratch/test_extrabold_overdraw.png').convert('L'))
arr3 = np.array(Image.open('scratch/test_black_overdraw.png').convert('L'))

print('Base 700: solid (<50)=', np.sum(arr1 < 50), 'total dark (<150)=', np.sum(arr1 < 150))
print('ExtraBold 800 + overdraw: solid (<50)=', np.sum(arr2 < 50), 'total dark (<150)=', np.sum(arr2 < 150))
print('Black 900 + overdraw: solid (<50)=', np.sum(arr3 < 50), 'total dark (<150)=', np.sum(arr3 < 150))

