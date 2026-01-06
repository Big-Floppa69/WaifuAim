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
from standard_crosshair import initialize_standard_crosshair
from utils import read_app_settings, set_label_art_from_path
from art_overlay import ArtOverlayController


def create_crosshair_label(app, image_path: str | None = None):
    """Create and configure a full-screen overlay label."""
    screen = app.primaryScreen()
    screen_geometry = screen.geometry()

    label = QLabel()
    if not image_path:
        pixmap = QPixmap(screen_geometry.width(), screen_geometry.height())
        pixmap.fill(Qt.GlobalColor.transparent)
        label.setPixmap(pixmap)

    label.setFixedWidth(screen_geometry.width())
    label.setFixedHeight(screen_geometry.height())

    # If this is an image-based overlay, load it through the colorblind-aware
    # pipeline so the persisted mode affects the displayed image.
    if image_path:
        try:
            set_label_art_from_path(label, image_path)
        except Exception:
            label.setPixmap(QPixmap(image_path))
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

    settings = {}
    try:
        settings = read_app_settings()
    except Exception:
        settings = {}
    autostart_enabled = bool(settings.get("autostart_enabled", False))

    # Base image label: keep transparent by default; art overlays are managed
    # as separate elements via the Art Manager.
    image_label = create_crosshair_label(app, image_path=None)
    if not autostart_enabled:
        image_label.show()

    # Create separate label for generated crosshair overlay and load saved settings
    crosshair_label = create_crosshair_label(app, image_path=None)
    initialize_standard_crosshair(crosshair_label)
    if autostart_enabled:
        try:
            crosshair_label.hide()
        except Exception:
            pass
    else:
        try:
            crosshair_label.show()
        except Exception:
            pass

    # Art overlays (separate element layers managed by Art Manager).
    art_overlay = ArtOverlayController(app, crosshair_overlay=crosshair_label)
    try:
        art_overlay.set_all_visible(False)
    except Exception:
        pass

    # Ensure GUI is initialized
    app.processEvents()
    time.sleep(0.1)

    # Create control panel
    control_panel = DarkControlPanel(image_label, crosshair_label, art_overlay_controller=art_overlay)

    # Add additional delay before creating tray icon
    time.sleep(0.5)

    # Create system tray icon
    tray_icon = create_tray_icon(app, image_label, control_panel)

    # Setup keyboard hotkeys
    setup_hotkeys(image_label, overlay_controller=art_overlay)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
