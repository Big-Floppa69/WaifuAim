"""Standard crosshair dialog that renders a configurable crosshair overlay."""
import json
from dataclasses import dataclass, asdict
from pathlib import Path
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
    QScrollArea,
    QColorDialog,
    QLineEdit,
)
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal

CONFIG_PATH = Path("standard_crosshair_settings.json")


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
    visible: bool = False
    dot_shape: str = "circle"  # circle or square
    dot_size: int = 6
    show_left: bool = True
    show_right: bool = True
    show_top: bool = True
    show_bottom: bool = True


def load_settings_from_disk() -> StandardCrosshairSettings:
    """Load saved crosshair settings if available."""
    settings = StandardCrosshairSettings()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            for key, value in data.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
        except Exception:
            pass
    settings.gap = max(0, settings.gap)
    if settings.dot_shape not in {"circle", "square"}:
        settings.dot_shape = "circle"
        settings.dot_size = min(32, max(2, settings.dot_size))
    return settings


def save_settings_to_disk(settings: StandardCrosshairSettings) -> None:
    """Persist crosshair settings to disk."""
    try:
        CONFIG_PATH.write_text(json.dumps(asdict(settings), indent=2))
    except Exception:
        pass


def render_crosshair_on_label(label: QLabel, settings: StandardCrosshairSettings) -> None:
    """Render the configured crosshair onto the provided label."""
    width = label.width() or (label.pixmap().width() if label.pixmap() else 0)
    height = label.height() or (label.pixmap().height() if label.pixmap() else 0)
    if width == 0 or height == 0:
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            width = geo.width()
            height = geo.height()
        else:
            width, height = 1920, 1080
    pixmap = generate_crosshair_pixmap(width, height, settings)
    label.setPixmap(pixmap)


def initialize_standard_crosshair(label: QLabel) -> StandardCrosshairSettings:
    """Apply saved settings to the label at startup."""
    settings = load_settings_from_disk()
    render_crosshair_on_label(label, settings)
    label.setVisible(settings.visible)
    if settings.visible:
        label.raise_()
    else:
        label.hide()
    return settings


def save_crosshair_visibility(is_visible: bool) -> None:
    """Update only the visibility flag in the persisted settings."""
    settings = load_settings_from_disk()
    settings.visible = is_visible
    save_settings_to_disk(settings)


def generate_crosshair_pixmap(width: int, height: int, settings: StandardCrosshairSettings) -> QPixmap:
    """Create a transparent pixmap containing the configured crosshair."""
    pixmap = QPixmap(max(1, width), max(1, height))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    center_x = width / 2
    center_y = height / 2
    gap = float(settings.gap)
    length = float(settings.length)
    thickness = float(max(1, settings.thickness))
    outline = float(max(0, settings.outline))

    color = QColor(settings.red, settings.green, settings.blue, settings.alpha)
    outline_color = QColor(0, 0, 0, settings.alpha)
    half_thickness = thickness / 2

    segments = []
    if settings.show_left:
        segments.append(QRectF(center_x - gap - length, center_y - half_thickness, length, thickness))
    if settings.show_right:
        segments.append(QRectF(center_x + gap, center_y - half_thickness, length, thickness))
    if settings.show_top:
        segments.append(QRectF(center_x - half_thickness, center_y - gap - length, thickness, length))
    if settings.show_bottom:
        segments.append(QRectF(center_x - half_thickness, center_y + gap, thickness, length))

    painter.setPen(Qt.PenStyle.NoPen)
    for rect in segments:
        if outline > 0:
            painter.setBrush(outline_color)
            painter.drawRect(rect.adjusted(-outline, -outline, outline, outline))
        painter.setBrush(color)
        painter.drawRect(rect)

    if settings.center_dot:
        dot_size = max(2, settings.dot_size)
        half = dot_size / 2
        if settings.dot_shape == "square":
            if outline > 0:
                painter.setBrush(outline_color)
                painter.drawRect(
                    QRectF(center_x - half - outline, center_y - half - outline, dot_size + outline * 2, dot_size + outline * 2)
                )
            painter.setBrush(color)
            painter.drawRect(QRectF(center_x - half, center_y - half, dot_size, dot_size))
        else:
            if outline > 0:
                painter.setBrush(outline_color)
                painter.drawEllipse(QPointF(center_x, center_y), half + outline, half + outline)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(center_x, center_y), half, half)

    painter.end()
    return pixmap


class StandardCrosshairDialog(QWidget):
    """Floating dialog that lets users tweak a basic crosshair."""

    visibility_changed = pyqtSignal(bool)

    def __init__(self, label: QLabel, parent=None):
        super().__init__(parent)
        self.label = label
        self.settings = load_settings_from_disk()
        self.drag_position = None
        self.hex_input = None
        self._hex_syncing = False
        self.line_checkboxes = {}

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._init_ui()
        self._sync_controls_from_settings()

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

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        scroll_content = self._create_content_frame()
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

        wrapper_layout = QVBoxLayout(self)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(main_frame)

        self.setFixedSize(360, 520)

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
        self._update_visibility_button()

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
        self.center_dot_check.toggled.connect(self._on_center_dot_toggled)
        layout.addWidget(self.center_dot_check)

        layout.addWidget(self._create_slider_group())
        layout.addWidget(self._create_color_group())
        layout.addWidget(self._create_dot_group())
        layout.addWidget(self._create_projection_group())

        buttons_row = QHBoxLayout()
        reset_btn = self._create_primary_button("↺ Reset", "#FF9800")
        reset_btn.clicked.connect(self._reset_defaults)
        buttons_row.addWidget(reset_btn)

        apply_btn = self._create_primary_button("Apply", "#4CAF50")
        apply_btn.clicked.connect(self._persist_and_render)
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
        self.gap_slider = self._add_slider(layout, "Gap", 0, 40, self.settings.gap, self._on_gap)
        self.outline_slider = self._add_slider(
            layout, "Outline", 0, 5, self.settings.outline, self._on_outline, suffix="px"
        )
        return frame

    def _create_dot_group(self) -> QFrame:
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

        shape_row = QHBoxLayout()
        shape_row.addWidget(self._section_label("Dot Shape"))
        self.circle_btn = self._create_choice_button("◯ Circle", self.settings.dot_shape == "circle")
        self.square_btn = self._create_choice_button("▢ Square", self.settings.dot_shape == "square")
        self.circle_btn.clicked.connect(lambda: self._set_dot_shape("circle"))
        self.square_btn.clicked.connect(lambda: self._set_dot_shape("square"))
        shape_row.addWidget(self.circle_btn)
        shape_row.addWidget(self.square_btn)
        layout.addLayout(shape_row)

        self.dot_size_slider = self._add_slider(
            layout, "Dot Size", 2, 32, self.settings.dot_size, self._on_dot_size, suffix="px"
        )

        return frame

    def _create_projection_group(self) -> QFrame:
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
        layout.setSpacing(6)
        layout.addWidget(self._section_label("Line Visibility"))

        rows = [
            ("Left", "show_left"),
            ("Right", "show_right"),
            ("Top", "show_top"),
            ("Bottom", "show_bottom"),
        ]
        for label_text, attr in rows:
            checkbox = QCheckBox(label_text)
            checkbox.setChecked(getattr(self.settings, attr))
            checkbox.setStyleSheet(
                """
                QCheckBox { color: #E0E0E0; font-weight: bold; }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
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
            checkbox.toggled.connect(lambda checked, name=attr: self._on_line_toggle(name, checked))
            self.line_checkboxes[attr] = checkbox
            layout.addWidget(checkbox)
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

        picker_layout = QHBoxLayout()
        picker_layout.setSpacing(8)

        self.hex_input = QLineEdit()
        self.hex_input.setMaxLength(7)
        self.hex_input.setPlaceholderText("#00FF90")
        self.hex_input.setStyleSheet(
            """
            QLineEdit {
                background-color: rgba(40, 40, 50, 200);
                border: 1px solid rgba(100, 100, 120, 120);
                border-radius: 6px;
                padding: 6px 10px;
                color: #E0E0E0;
                font-weight: bold;
            }
            QLineEdit:focus {
                border: 1px solid #00ACC1;
            }
        """
        )
        self.hex_input.editingFinished.connect(self._on_hex_input_finished)
        picker_layout.addWidget(self.hex_input)

        palette_btn = QPushButton("🎨 Palette")
        palette_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        palette_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #26A69A;
            }
            QPushButton:pressed {
                background-color: #00796B;
            }
        """
        )
        palette_btn.clicked.connect(self._open_color_dialog)
        picker_layout.addWidget(palette_btn)

        layout.addLayout(picker_layout)
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

    def _set_slider_value(self, slider: QSlider, value: int) -> None:
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)

    def _sync_controls_from_settings(self) -> None:
        if hasattr(self, "center_dot_check"):
            self.center_dot_check.blockSignals(True)
            self.center_dot_check.setChecked(self.settings.center_dot)
            self.center_dot_check.blockSignals(False)

        for slider, value in (
            (getattr(self, "length_slider", None), self.settings.length),
            (getattr(self, "thickness_slider", None), self.settings.thickness),
            (getattr(self, "gap_slider", None), self.settings.gap),
            (getattr(self, "outline_slider", None), self.settings.outline),
            (getattr(self, "dot_size_slider", None), self.settings.dot_size),
            (getattr(self, "red_slider", None), self.settings.red),
            (getattr(self, "green_slider", None), self.settings.green),
            (getattr(self, "blue_slider", None), self.settings.blue),
            (getattr(self, "alpha_slider", None), self.settings.alpha),
        ):
            if slider is not None:
                self._set_slider_value(slider, value)

        self._update_color_preview()
        self._update_hex_input()

        if hasattr(self, "circle_btn"):
            self._update_shape_buttons()

        for attr, checkbox in getattr(self, "line_checkboxes", {}).items():
            if checkbox is not None:
                checkbox.blockSignals(True)
                checkbox.setChecked(getattr(self.settings, attr))
                checkbox.blockSignals(False)

        self.label.setVisible(self.settings.visible)
        if self.settings.visible:
            self.label.raise_()
        self._update_visibility_button()
        render_crosshair_on_label(self.label, self.settings)

    def _persist_and_render(self) -> None:
        render_crosshair_on_label(self.label, self.settings)
        save_settings_to_disk(self.settings)

    def _toggle_visibility(self) -> None:
        hidden = self.visibility_btn.isChecked()
        self.label.setVisible(not hidden)
        if self.label.isVisible():
            self.label.raise_()
        self.settings.visible = self.label.isVisible()
        self._update_visibility_button()
        save_settings_to_disk(self.settings)
        self.visibility_changed.emit(self.label.isVisible())

    def _update_visibility_button(self) -> None:
        hidden = not self.label.isVisible()
        self.visibility_btn.blockSignals(True)
        self.visibility_btn.setChecked(hidden)
        self.visibility_btn.blockSignals(False)
        self.visibility_btn.setText("👁️ Show Crosshair" if hidden else "👁️ Hide Crosshair")

    def sync_with_label(self) -> None:
        """Synchronize the dialog toggle with the current label visibility."""
        self.settings.visible = self.label.isVisible()
        self._update_visibility_button()
        save_settings_to_disk(self.settings)

    def _on_center_dot_toggled(self, checked: bool) -> None:
        self.settings.center_dot = checked
        self._persist_and_render()

    def _on_length(self, value: int) -> None:
        self.settings.length = value
        self._persist_and_render()

    def _on_thickness(self, value: int) -> None:
        self.settings.thickness = value
        self._persist_and_render()

    def _on_gap(self, value: int) -> None:
        self.settings.gap = value
        self._persist_and_render()

    def _on_outline(self, value: int) -> None:
        self.settings.outline = value
        self._persist_and_render()

    def _set_dot_shape(self, shape: str) -> None:
        if shape not in {"circle", "square"}:
            return
        self.settings.dot_shape = shape
        self._update_shape_buttons()
        self._persist_and_render()

    def _update_shape_buttons(self) -> None:
        if not hasattr(self, "circle_btn") or not hasattr(self, "square_btn"):
            return
        for btn, active in (
            (self.circle_btn, self.settings.dot_shape == "circle"),
            (self.square_btn, self.settings.dot_shape == "square"),
        ):
            btn.setStyleSheet(self._choice_button_style(active))

    def _create_choice_button(self, text: str, active: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setCheckable(True)
        btn.setStyleSheet(self._choice_button_style(active))
        btn.setChecked(active)
        return btn

    def _choice_button_style(self, active: bool) -> str:
        base = "#5C6BC0" if active else "rgba(70,70,80,150)"
        border = "#90CAF9" if active else "rgba(255,255,255,0.15)"
        return f"""
        QPushButton {{
            background-color: {base};
            color: white;
            border: 1px solid {border};
            border-radius: 8px;
            padding: 8px 12px;
            font-weight: bold;
        }}
        QPushButton:pressed {{
            background-color: {self._adjust_color(base, 0.9)};
        }}
        """

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #B0B0B0; font-size: 12px; font-weight: bold;")
        return label

    def _on_dot_size(self, value: int) -> None:
        self.settings.dot_size = value
        self._persist_and_render()

    def _on_line_toggle(self, attr: str, enabled: bool) -> None:
        if hasattr(self.settings, attr):
            setattr(self.settings, attr, enabled)
            self._persist_and_render()

    def _on_red(self, value: int) -> None:
        self.settings.red = value
        self._update_color_preview()
        self._update_hex_input()
        self._persist_and_render()

    def _on_green(self, value: int) -> None:
        self.settings.green = value
        self._update_color_preview()
        self._update_hex_input()
        self._persist_and_render()

    def _on_blue(self, value: int) -> None:
        self.settings.blue = value
        self._update_color_preview()
        self._update_hex_input()
        self._persist_and_render()

    def _on_alpha(self, value: int) -> None:
        self.settings.alpha = value
        self._update_color_preview()
        self._persist_and_render()

    def _update_color_preview(self) -> None:
        self.color_preview.setStyleSheet(self._color_preview_style())

    def _update_hex_input(self) -> None:
        if not isinstance(self.hex_input, QLineEdit):
            return
        self._hex_syncing = True
        self.hex_input.setText(
            "#{:02X}{:02X}{:02X}".format(self.settings.red, self.settings.green, self.settings.blue)
        )
        self._hex_syncing = False

    def _on_hex_input_finished(self) -> None:
        if self._hex_syncing or not isinstance(self.hex_input, QLineEdit):
            return
        raw = self.hex_input.text().strip()
        if not raw:
            return
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) != 6:
            self._update_hex_input()
            return
        try:
            red = int(raw[0:2], 16)
            green = int(raw[2:4], 16)
            blue = int(raw[4:6], 16)
        except ValueError:
            self._update_hex_input()
            return
        self.settings.red = red
        self.settings.green = green
        self.settings.blue = blue
        for slider, value in (
            (getattr(self, "red_slider", None), red),
            (getattr(self, "green_slider", None), green),
            (getattr(self, "blue_slider", None), blue),
        ):
            if slider is not None:
                self._set_slider_value(slider, value)
        self._update_color_preview()
        self._persist_and_render()

    def _open_color_dialog(self) -> None:
        initial = QColor(self.settings.red, self.settings.green, self.settings.blue, self.settings.alpha)
        color = QColorDialog.getColor(
            initial,
            self,
            "Pick Crosshair Color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not color.isValid():
            return
        self.settings.red = color.red()
        self.settings.green = color.green()
        self.settings.blue = color.blue()
        self.settings.alpha = color.alpha()
        for slider, value in (
            (getattr(self, "red_slider", None), self.settings.red),
            (getattr(self, "green_slider", None), self.settings.green),
            (getattr(self, "blue_slider", None), self.settings.blue),
            (getattr(self, "alpha_slider", None), self.settings.alpha),
        ):
            if slider is not None:
                self._set_slider_value(slider, value)
        self._update_color_preview()
        self._update_hex_input()
        self._persist_and_render()

    def _reset_defaults(self) -> None:
        current_visibility = self.settings.visible
        self.settings = StandardCrosshairSettings(visible=current_visibility)
        self._sync_controls_from_settings()
        save_settings_to_disk(self.settings)

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
