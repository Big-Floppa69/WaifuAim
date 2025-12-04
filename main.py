"""
Zenless Zone Zero Crosshair Application

A customizable crosshair overlay with control panel and system tray integration.
"""
import sys
import time
from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

from control_panel import DarkControlPanel
from tray_icon import create_tray_icon
from hotkeys import setup_hotkeys


def create_crosshair_label(app, image_path="display_images/astra_yao.png"):
    """Create and configure the crosshair label."""
    screen = app.primaryScreen()
    screen_geometry = screen.geometry()

    label = QLabel()
    pixmap = QPixmap(image_path)

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
    
    return label


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Important for tray applications

    # Create crosshair label
    label = create_crosshair_label(app)
    label.show()

    # Ensure GUI is initialized
    app.processEvents()
    time.sleep(0.1)

    # Create control panel
    control_panel = DarkControlPanel(label)

    # Add additional delay before creating tray icon
    time.sleep(0.5)

    # Create system tray icon
    tray_icon = create_tray_icon(app, label, control_panel)

    # Setup keyboard hotkeys
    setup_hotkeys(label)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
