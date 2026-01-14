"""WaifuAim application.

A customizable crosshair overlay with control panel and system tray integration.
"""
import sys
import time

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QProxyStyle, QStyle

from control_panel import DarkControlPanel
from tray_icon import create_tray_icon
from hotkeys import setup_hotkeys
from standard_crosshair import initialize_standard_crosshair
from utils import read_app_settings, set_label_art_from_path
from art_overlay import ArtOverlayController


APP_NAME = "WaifuAim"


class _PurpleCheckBoxStyle(QProxyStyle):
    """Draw a real purple checkmark for all QCheckBox indicators.

    This avoids stylesheet/SVG inconsistencies where the checked state only looks
    slightly brighter with no visible mark.
    """

    _BORDER_UNCHECKED = QColor(230, 225, 255, 90)
    _BORDER_CHECKED = QColor(124, 92, 255, 200)
    _CHECK = QColor(124, 92, 255)

    def pixelMetric(self, metric, option=None, widget=None):  # type: ignore[override]
        if metric in (
            QStyle.PixelMetric.PM_IndicatorWidth,
            QStyle.PixelMetric.PM_IndicatorHeight,
        ):
            return 16
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):  # type: ignore[override]
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox or option is None or painter is None:
            return super().drawPrimitive(element, option, painter, widget)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        r = QRectF(option.rect)
        # Make room for pen width.
        r = r.adjusted(1.0, 1.0, -1.0, -1.0)
        radius = min(4.0, r.width() / 3.5, r.height() / 3.5)

        state = option.state
        checked = bool(state & QStyle.StateFlag.State_On)
        indeterminate = bool(state & QStyle.StateFlag.State_NoChange)

        border = self._BORDER_CHECKED if checked else self._BORDER_UNCHECKED
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(r, radius, radius)

        if indeterminate and not checked:
            pen = QPen(QColor(230, 225, 255, 170), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            y = r.y() + r.height() * 0.5
            painter.drawLine(
                QPointF(r.x() + r.width() * 0.22, y),
                QPointF(r.x() + r.width() * 0.78, y),
            )

        if checked:
            pen = QPen(self._CHECK, max(2.0, r.width() * 0.16))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)

            x = r.x()
            y = r.y()
            w = r.width()
            h = r.height()
            path = QPainterPath()
            path.moveTo(x + w * 0.22, y + h * 0.56)
            path.lineTo(x + w * 0.42, y + h * 0.76)
            path.lineTo(x + w * 0.80, y + h * 0.30)
            painter.drawPath(path)

        painter.restore()
        return


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

    # Ensure checkboxes have a visible checkmark (✔) when active.
    try:
        app.setStyle(_PurpleCheckBoxStyle(app.style()))
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
