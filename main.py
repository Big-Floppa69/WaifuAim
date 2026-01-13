"""WaifuAim application.

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


APP_NAME = "WaifuAim"


def _checkbox_checkmark_qss() -> str:
    # Render a literal purple check mark (no filled square).
    # Note: '#' must be URL-encoded as '%23' in SVG for Qt style sheets.
    check_svg = (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
        "<path d='M3 8.5 L6.2 11.7 L13 5' fill='none' stroke='%237C5CFF' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/>"
        "</svg>"
    )
    return (
        "QCheckBox::indicator { width: 16px; height: 16px; image: none; background: transparent; }\n"
        "QCheckBox::indicator:unchecked { border: 1px solid rgba(230,225,255,90); border-radius: 4px; }\n"
        f"QCheckBox::indicator:checked {{ border: 1px solid rgba(124,92,255,200); border-radius: 4px; image: url(\"{check_svg}\"); }}\n"
        "QCheckBox::indicator:indeterminate { border: 1px solid rgba(230,225,255,90); border-radius: 4px; image: none; background: transparent; }\n"
    )


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

    # App identity (Windows task switcher/tray/tooltips).
    try:
        app.setApplicationName(APP_NAME)
    except Exception:
        pass
    try:
        app.setApplicationDisplayName(APP_NAME)
    except Exception:
        pass

    # Global checkbox styling.
    try:
        app.setStyleSheet((app.styleSheet() or "") + "\n" + _checkbox_checkmark_qss())
    except Exception:
        pass

    settings = {}
    try:
        settings = read_app_settings()
    except Exception:
        settings = {}
    autostart_enabled = bool(settings.get("autostart_enabled", False))

    # Base image label: keep transparent by default; art overlays are managed
    # as separate elements via the Art Manager.
    image_label = create_crosshair_label(app, image_path=None)

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
    setup_hotkeys(image_label, crosshair_label=crosshair_label, overlay_controller=art_overlay)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
