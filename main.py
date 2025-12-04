import sys
import os
from PyQt6.QtWidgets import QApplication, QLabel, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QPixmap, QIcon, QAction
from PyQt6.QtCore import Qt
import keyboard as kb  # type: ignore
import threading


def make_key_handler(func, hotkey):
    def handler(event):
        if event.name == hotkey and event.event_type == 'up':
            func()
    return handler


def mirror(label, pixmap):
    original_image = pixmap.toImage()
    mirrored_image = original_image.mirrored(True, False)
    label.setPixmap(QPixmap.fromImage(mirrored_image))


def get_art_list():
    exts = ('.png', '.jpg', '.jpeg', '.webp')
    files = []
    for f in os.listdir('.'):
        if f.lower().endswith(exts) and 'tray' not in f.lower():
            files.append(f)
    return files


def mirror_hot_key(label):
    kb.add_hotkey('alt', lambda: mirror(label, label.pixmap()))


def hide_hot_key(label):
    def toggle_visibility():
        if label.isVisible():
            label.hide()
        else:
            label.show()

    handler = make_key_handler(toggle_visibility, 'f1')
    kb.hook(handler)


def art_switch_hot_key(label):
    arts = get_art_list()
    if not arts:
        return

    index = 0

    def switch():
        nonlocal index
        index = (index + 1) % len(arts)
        pix = QPixmap(arts[index])
        label.setPixmap(pix)

    kb.add_hotkey('f2', switch)


def transparent(label, percent):
    label.setWindowOpacity(percent)


def main():
    app = QApplication(sys.argv)

    screen = app.primaryScreen()
    screen_geometry = screen.geometry()

    label = QLabel()
    pixmap = QPixmap("astra_yao.png")

    label.setFixedWidth(screen_geometry.width())
    label.setFixedHeight(screen_geometry.height())
    label.setPixmap(pixmap)
    label.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
        | Qt.WindowType.WindowTransparentForInput
    )
    label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    label.setScaledContents(True)
    label.show()

    tray_icon = QSystemTrayIcon(QIcon("astra_yao_tray.png"), parent=app)

    tray_menu = QMenu()

    exit_action = QAction("Exit")
    exit_action.triggered.connect(app.quit)

    hide_action = QAction('Hide')
    hide_action.triggered.connect(label.hide)

    show_action = QAction('Show')
    show_action.triggered.connect(label.show)

    mirror_action = QAction('Mirror')
    mirror_action.triggered.connect(lambda: mirror(label, label.pixmap()))

    transparent_action = QMenu('Transparent')

    transparent_100_action = QAction('100%')
    transparent_100_action.triggered.connect(lambda: transparent(label, 1.0))

    transparent_75_action = QAction('75%')
    transparent_75_action.triggered.connect(lambda: transparent(label, 0.75))

    transparent_50_action = QAction('50%')
    transparent_50_action.triggered.connect(lambda: transparent(label, 0.5))

    transparent_25_action = QAction('25%')
    transparent_25_action.triggered.connect(lambda: transparent(label, 0.25))

    transparent_action.addAction(transparent_100_action)
    transparent_action.addAction(transparent_75_action)
    transparent_action.addAction(transparent_50_action)
    transparent_action.addAction(transparent_25_action)

    tray_menu.addAction(hide_action)
    tray_menu.addAction(show_action)
    tray_menu.addAction(mirror_action)
    tray_menu.addMenu(transparent_action)
    tray_menu.addAction(exit_action)

    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()

    threading.Thread(target=mirror_hot_key, args=(label,), daemon=True).start()
    threading.Thread(target=hide_hot_key, args=(label,), daemon=True).start()
    threading.Thread(target=art_switch_hot_key, args=(label,), daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
