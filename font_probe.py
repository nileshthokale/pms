import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontMetrics

app = QApplication.instance() or QApplication(["-platform", "windows"])
sys.path.insert(0, ".")
from ui.components import readable_font
from ui.theme import TYPE_TABLE_DATA, TYPE_INPUT, TYPE_FORM_LABEL, FONT_FAMILY

print("FONT_FAMILY =", FONT_FAMILY)
for label, text, size in (
    ("table data '2029-02-28'", "2029-02-28", TYPE_TABLE_DATA),
    ("table data '29-02-2029'", "29-02-2029", TYPE_TABLE_DATA),
    ("input      '2029-02-28'", "2029-02-28", TYPE_INPUT),
    ("table data '14261266A'", "14261266A", TYPE_TABLE_DATA),
    ("input      '14261266A'", "14261266A", TYPE_INPUT),
    ("form label 'Batch'", "Batch", TYPE_FORM_LABEL),
    ("form label 'Avail'", "Avail", TYPE_FORM_LABEL),
):
    advance = QFontMetrics(readable_font(size)).horizontalAdvance(text)
    print(f"{label}: {advance} px advance")
    print("   family on platform:", readable_font(size).family(),
          "| pointSize:", readable_font(size).pointSize(),
          "| pixelSize:", readable_font(size).pixelSize())
