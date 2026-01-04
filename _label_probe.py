import os, sys
from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtCore import Qt, QTimer
from utils import set_label_art_from_path

mp4 = os.path.abspath('display_images/miyabi-hoshimi-miyabi.mp4')
print('mp4 exists:', os.path.exists(mp4), mp4)

app = QApplication(sys.argv)
label = QLabel()
label.setWindowFlags(
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.Tool
    | Qt.WindowType.WindowTransparentForInput
)
label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
label.setScaledContents(True)
label.resize(800, 450)
label.show()

set_label_art_from_path(label, mp4)

def check():
    pm = label.pixmap()
    print('label.pixmap is null:', (pm is None) or pm.isNull(), 'size:', (0,0) if (pm is None or pm.isNull()) else (pm.width(), pm.height()))

QTimer.singleShot(1200, check)
QTimer.singleShot(2500, app.quit)
app.exec()
