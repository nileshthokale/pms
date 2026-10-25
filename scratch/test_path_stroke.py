from PySide6.QtWidgets import QApplication
import sys
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtGui import QFont, QImage, QPainter, QColor, QPainterPath, QPen
from PySide6.QtCore import QPointF
from PIL import Image
import numpy as np

img = QImage(600, 100, QImage.Format_ARGB32)
img.fill(QColor('white'))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing, True)

font = QFont('Arial', -1)
font.setPointSizeF(8.5)
font.setWeight(QFont.Weight.Bold)

path = QPainterPath()
path.addText(QPointF(20, 50), font, 'BIO D3 PLUS  KBC2402A  31/12/2026')

# Fill path AND stroke with 0.5px pen
pen = QPen(QColor('#000000'), 0.8)
p.setPen(pen)
p.setBrush(QColor('#000000'))
p.drawPath(path)
p.end()

img.save('scratch/test_path_stroke.png')
arr = np.array(Image.open('scratch/test_path_stroke.png').convert('L'))
print('Path stroke: solid (<50)=', np.sum(arr < 50), 'total dark (<150)=', np.sum(arr < 150))

