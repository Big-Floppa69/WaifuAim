"""Standard crosshair dialog that renders a configurable crosshair overlay."""
from dataclasses import dataclass
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QPushButton,
    QFrame,
    QCheckBox,
    QApplication,
)
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtCore import Qt, QPointF


@dataclass
class StandardCrosshairSettings:
    """Container for standard crosshair values."""

    center_dot: bool = False
    length: int = 28
    thickness: int = 4
    gap: int = 10
    outline: int = 1
    red: int = 0
    green: int = 255
    blue: int = 120
    alpha: int = 255


def generate_crosshair_pixmap(width: int, height: int, settings: StandardCrosshairSettings) -> QPixmap:
    """Create a transparent pixmap containing the configured crosshair."""
    pixmap = QPixmap(max(1, width), max(1, height))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    center_x = width / 2
    center_y = height / 2
    gap = settings.gap
    length = settings.length
    thickness = max(1, settings.thickness)

    def draw_lines(pen: QPen) -> None:
        painter.setPen(pen)
        painter.drawLine(
            int(center_x - gap - length), int(center_y), int(center_x - gap), int(center_y)
        )
        painter.drawLine(
            int(center_x + gap), int(center_y), int(center_x + gap + length), int(center_y)
        )
        painter.drawLine(
            int(center_x), int(center_y - gap - length), int(center_x), int(center_y - gap)
        )
        painter.drawLine(
            int(center_x), int(center_y + gap), int(center_x), int(center_y + gap + length)
        )

    if settings.outline > 0:
        outline_pen = QPen(QColor(0, 0, 0, settings.alpha))
        outline_pen.setWidth(thickness + settings.outline * 2)
        outline_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        draw_lines(outline_pen)

    color_pen = QPen(QColor(settings.red, settings.green, settings.blue, settings.alpha))
    color_pen.setWidth(thickness)
    color_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    draw_lines(color_pen)

    if settings.center_dot:
        painter.setBrush(QColor(settings.red, settings.green, settings.blue, settings.alpha))
        painter.setPen(Qt.PenStyle.NoPen)
        dot_size = max(thickness + 2, 4)
        painter.drawEllipse(QPointF(center_x, center_y), dot_size / 2, dot_size / 2)

    painter.end()
    return pixmap


class StandardCrosshairDialog(QWidget):
    """Floating dialog that lets users tweak a basic crosshair."""

    def __init__(self, label: QLabel, parent=None):
        super().__init__(parent)
        self.label = label
        self.settings = StandardCrosshairSettings()
        self.drag_position = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._init_ui()
        self._apply_settings()

    def _init_ui(self) -> None:
        main_frame = QFrame(self)
        main_frame.setObjectName("mainFrame")
        main_frame.setStyleSheet(
            """
            QFrame#mainFrame {
                background-color: rgba(20, 20, 25, 240);
                border-radius: 15px;
                border: 1px solid rgba(100, 100, 120, 100);
            }
        """
        )

        main_layout = QVBoxLayout(main_frame)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._create_title_bar())
        main_layout.addWidget(self._create_content_frame())

        wrapper_layout = QVBoxLayout(self)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(main_frame)

        self.setFixedWidth(360)

    def _create_title_bar(self) -> QFrame:
        title_bar = QFrame()
        title_bar.setStyleSheet(
            """
            QFrame {
                background-color: rgba(30, 30, 35, 255);
                border-top-left-radius: 15px;
                border-top-right-radius: 15px;
            }
        """
        )
        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(15, 8, 8, 8)

        title_label = QLabel("🎯 Standard Crosshair")
        title_label.setStyleSheet(
            """
            QLabel {
                color: #E0E0E0;
                font-size: 14px;
                font-weight: bold;
                background: transparent;
            }
        """
        )
        layout.addWidget(title_label)
        layout.addStretch()

        close_btn = self._create_button("×", "rgba(200, 50, 50, 200)", size=28)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        return title_bar

    def _create_content_frame(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: transparent; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(12)

        info = QLabel("Configure a simple crosshair without importing images.")
        info.setWordWrap(True)
        info.setStyleSheet("color: rgba(200, 200, 200, 170);")
        layout.addWidget(info)

        self.visibility_btn = self._create_primary_button("👁️ Hide Crosshair", "#607D8B")
        self.visibility_btn.setCheckable(True)
        self.visibility_btn.clicked.connect(self._toggle_visibility)
        layout.addWidget(self.visibility_btn)

        self.center_dot_check = QCheckBox("Add Center Dot")
        self.center_dot_check.setStyleSheet(
            """
            QCheckBox { color: #E0E0E0; font-weight: bold; }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid rgba(120, 120, 140, 200);
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border: 2px solid #357a38;
                border-radius: 4px;
            }
        """
        )
        self.center_dot_check.stateChanged.connect(self._on_center_dot_changed)
        layout.addWidget(self.center_dot_check)

        layout.addWidget(self._create_slider_group())
        layout.addWidget(self._create_color_group())

        buttons_row = QHBoxLayout()
        reset_btn = self._create_primary_button("↺ Reset", "#FF9800")
        reset_btn.clicked.connect(self._reset_defaults)
        buttons_row.addWidget(reset_btn)

        apply_btn = self._create_primary_button("Apply", "#4CAF50")
        apply_btn.clicked.connect(self._apply_settings)
        buttons_row.addWidget(apply_btn)

        layout.addLayout(buttons_row)
        return frame

    def _create_slider_group(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            """
            QFrame {
                background-color: rgba(30, 30, 35, 200);
                border-radius: 12px;
                padding: 12px;
            }
        """
        )
        layout = QVBoxLayout(frame)
        layout.setSpacing(10)

        self.length_slider = self._add_slider(layout, "Length", 5, 80, self.settings.length, self._on_length)
        self.thickness_slider = self._add_slider(
            layout, "Thickness", 1, 15, self.settings.thickness, self._on_thickness
        )
        self.gap_slider = self._add_slider(layout, "Gap", -20, 40, self.settings.gap, self._on_gap)
        self.outline_slider = self._add_slider(
            layout, "Outline", 0, 5, self.settings.outline, self._on_outline, suffix="px"
        )
        return frame

    def _create_color_group(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            """
            QFrame {
                background-color: rgba(30, 30, 35, 200);
                border-radius: 12px;
                padding: 12px;
            }
        """
        )
        layout = QVBoxLayout(frame)
        layout.setSpacing(10)

        self.color_preview = QLabel()
        self.color_preview.setFixedHeight(24)
        self.color_preview.setStyleSheet(self._color_preview_style())
        layout.addWidget(self.color_preview)

        self.red_slider = self._add_slider(layout, "Red", 0, 255, self.settings.red, self._on_red, suffix="")
        self.green_slider = self._add_slider(layout, "Green", 0, 255, self.settings.green, self._on_green, suffix="")
        self.blue_slider = self._add_slider(layout, "Blue", 0, 255, self.settings.blue, self._on_blue, suffix="")
        self.alpha_slider = self._add_slider(layout, "Alpha", 25, 255, self.settings.alpha, self._on_alpha, suffix="")
        return frame

    def _color_preview_style(self) -> str:
        color = QColor(self.settings.red, self.settings.green, self.settings.blue, self.settings.alpha)
        return (
            "background-color: rgba({r}, {g}, {b}, {a}); border-radius: 8px; border: 1px solid rgba(255,255,255,0.2);"
        ).format(r=color.red(), g=color.green(), b=color.blue(), a=color.alpha())

    def _add_slider(self, layout: QVBoxLayout, label_text: str, minimum: int, maximum: int, value: int,
                    callback, suffix: str = "px") -> QSlider:
        row = QVBoxLayout()
        text = QLabel(label_text)
        text.setStyleSheet("color: #B0B0B0; font-size: 12px;")
        row.addWidget(text)

        slider_frame = QFrame()
        slider_frame.setStyleSheet(
            """
            QFrame {
                background-color: rgba(40, 40, 50, 150);
                border-radius: 10px;
                padding: 6px 10px;
            }
        """
        )
        slider_layout = QHBoxLayout(slider_frame)
        slider_layout.setContentsMargins(6, 4, 6, 4)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setValue(value)
        slider.setStyleSheet(
            """
            QSlider::groove:horizontal {
                border: none;
                height: 8px;
                background: rgba(60, 60, 70, 200);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #667eea, stop:1 #764ba2);
                border: none;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #764ba2, stop:1 #667eea);
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #667eea, stop:1 #764ba2);
                border-radius: 4px;
            }
        """
        )

        value_label = QLabel(f"{value}{suffix}")
        value_label.setStyleSheet("color: #E0E0E0; font-weight: bold; min-width: 48px;")

        def on_value_change(val: int) -> None:
            value_label.setText(f"{val}{suffix}")
            callback(val)

        slider.valueChanged.connect(on_value_change)

        slider_layout.addWidget(slider)
        slider_layout.addWidget(value_label)
        row.addWidget(slider_frame)
        layout.addLayout(row)
        return slider

    def _create_button(self, text: str, hover_color: str, size: int = 32) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(size, size)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(70, 70, 80, 150);
                color: #E0E0E0;
                border: none;
                border-radius: 6px;
                font-size: 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: rgba(60, 60, 70, 200);
            }}
        """
        )
        return btn

    def _create_primary_button(self, text: str, color: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {self._adjust_color(color, 1.15)};
            }}
            QPushButton:pressed {{
                background-color: {self._adjust_color(color, 0.85)};
            }}
        """
        )
        return btn

    def _adjust_color(self, hex_color: str, factor: float) -> str:
        color = QColor(hex_color)
        h, s, v, a = color.getHsv()
        v = min(255, max(0, int(v * factor)))
        color.setHsv(h, s, v, a)
        return color.name()

    def _toggle_visibility(self) -> None:
        if self.visibility_btn.isChecked():
            self.label.hide()
            self.visibility_btn.setText("👁️ Show Crosshair")
        else:
            self.label.show()
            self.visibility_btn.setText("👁️ Hide Crosshair")

    def _on_center_dot_changed(self, state: int) -> None:
        self.settings.center_dot = state == Qt.CheckState.Checked
        self._apply_settings()

    def _on_length(self, value: int) -> None:
        self.settings.length = value
        self._apply_settings()

    def _on_thickness(self, value: int) -> None:
        self.settings.thickness = value
        self._apply_settings()

    def _on_gap(self, value: int) -> None:
        self.settings.gap = value
        self._apply_settings()

    def _on_outline(self, value: int) -> None:
        self.settings.outline = value
        self._apply_settings()

    def _on_red(self, value: int) -> None:
        self.settings.red = value
        self._update_color_preview()
        self._apply_settings()

    def _on_green(self, value: int) -> None:
        self.settings.green = value
        self._update_color_preview()
        self._apply_settings()

    def _on_blue(self, value: int) -> None:
        self.settings.blue = value
        self._update_color_preview()
        self._apply_settings()

    def _on_alpha(self, value: int) -> None:
        self.settings.alpha = value
        self._update_color_preview()
        self._apply_settings()

    def _update_color_preview(self) -> None:
        self.color_preview.setStyleSheet(self._color_preview_style())

    def _apply_settings(self) -> None:
        width = self.label.width() or (self.label.pixmap().width() if self.label.pixmap() else 0)
        height = self.label.height() or (self.label.pixmap().height() if self.label.pixmap() else 0)
        if width == 0 or height == 0:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.geometry()
                width = geo.width()
                height = geo.height()
            else:
                width, height = 1920, 1080
        pixmap = generate_crosshair_pixmap(width, height, self.settings)
        self.label.setPixmap(pixmap)

    def _reset_defaults(self) -> None:
        self.settings = StandardCrosshairSettings()
        self.center_dot_check.setChecked(self.settings.center_dot)
        self.length_slider.setValue(self.settings.length)
        self.thickness_slider.setValue(self.settings.thickness)
        self.gap_slider.setValue(self.settings.gap)
        self.outline_slider.setValue(self.settings.outline)
        self.red_slider.setValue(self.settings.red)
        self.green_slider.setValue(self.settings.green)
        self.blue_slider.setValue(self.settings.blue)
        self.alpha_slider.setValue(self.settings.alpha)
        self._update_color_preview()
        self._apply_settings()

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        self.drag_position = None
        super().mouseReleaseEvent(event)
