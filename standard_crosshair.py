"""Standard crosshair dialog that renders a configurable crosshair overlay."""
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional
from uuid import uuid4
from copy import deepcopy
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QLabel,
    QSlider,
    QPushButton,
    QFrame,
    QCheckBox,
    QApplication,
    QScrollArea,
    QColorDialog,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QToolButton,
    QMenu,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QAbstractItemView,
)
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPainterPath, QPen
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer

CONFIG_PATH = Path(__file__).resolve().with_name("standard_crosshair_settings.json")
MAX_CUSTOM_COLORS = 16
ALLOWED_DOT_SHAPES = {"circle", "square", "diamond"}
ALLOWED_CROSSHAIR_STYLES = {"plus", "x"}
STYLE_ANGLES = {
    "plus": {
        "show_left": 180,
        "show_right": 0,
        "show_top": -90,
        "show_bottom": 90,
    },
    "x": {
        "show_left": -135,   # top-left
        "show_right": -45,   # top-right
        "show_top": 45,      # bottom-right
        "show_bottom": 135,  # bottom-left
    },
}
STYLE_LABELS = {
    "plus": {
        "show_left": "Left",
        "show_right": "Right",
        "show_top": "Top",
        "show_bottom": "Bottom",
    },
    "x": {
        "show_left": "Top-Left",
        "show_right": "Top-Right",
        "show_top": "Bottom-Right",
        "show_bottom": "Bottom-Left",
    },
}

LINE_KEYS = ("left", "right", "top", "bottom")
ATTR_TO_LINE_KEY = {
    "show_left": "left",
    "show_right": "right",
    "show_top": "top",
    "show_bottom": "bottom",
}
LINE_KEY_TO_ATTR = {value: key for key, value in ATTR_TO_LINE_KEY.items()}
LINE_FIELD_LIMITS = {
    "length": (5, 200, "px"),
    "gap": (0, 120, "px"),
    "thickness": (1, 30, "px"),
    "angle_offset": (-90, 90, "°"),
    "tip_offset": (-80, 80, "px"),
}
LINE_LABELS = {
    "left": "Left",
    "right": "Right",
    "top": "Top",
    "bottom": "Bottom",
}
COMPONENT_TYPES = {"segment", "circle"}
COMPONENT_FIELD_LIMITS = {
    "segment": {
        "offset": (-400.0, 600.0, "px"),
        "perp_offset": (-400.0, 400.0, "px"),
        "length": (0.0, 600.0, "px"),
        "thickness": (1.0, 120.0, "px"),
        "angle_offset": (-90.0, 90.0, "°"),
        "tip_offset": (-120.0, 120.0, "px"),
    },
    "circle": {
        "offset": (-400.0, 600.0, "px"),
        "perp_offset": (-400.0, 400.0, "px"),
        "radius": (1.0, 200.0, "px"),
    },
}


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def normalize_hex_color(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return None
    raw = value.strip().upper()
    if not raw:
        return None
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) != 6:
        return None
    try:
        int(raw, 16)
    except ValueError:
        return None
    return f"#{raw}"


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
    custom_colors: List[str] = field(default_factory=list)
    crosshair_style: str = "plus"
    rotation: float = 0.0
    offset_x: int = 0
    offset_y: int = 0
    line_rounding: int = 0
    fan_enabled: bool = False
    fan_speed: int = 60
    line_profiles: dict[str, dict[str, float]] = field(default_factory=dict)
    line_components: dict[str, list[dict]] = field(default_factory=dict)
    line_layers: List[dict] = field(default_factory=list)
    draggable_mode: bool = False
    grid_snap_size: int = 5


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
    settings.dot_size = clamp(settings.dot_size, 2, 32)
    if settings.dot_shape not in ALLOWED_DOT_SHAPES:
        settings.dot_shape = "circle"
    settings.crosshair_style = settings.crosshair_style if settings.crosshair_style in ALLOWED_CROSSHAIR_STYLES else "plus"
    settings.rotation = float(settings.rotation) if isinstance(settings.rotation, (int, float)) else 0.0
    settings.rotation = settings.rotation % 360
    settings.offset_x = clamp(int(settings.offset_x), -800, 800)
    settings.offset_y = clamp(int(settings.offset_y), -800, 800)
    settings.line_rounding = clamp(int(settings.line_rounding), 0, 25)
    settings.fan_enabled = bool(settings.fan_enabled)
    settings.fan_speed = clamp(int(settings.fan_speed), -360, 360)
    normalized_colors: List[str] = []
    for value in settings.custom_colors[:MAX_CUSTOM_COLORS]:
        normalized = normalize_hex_color(value)
        if normalized and normalized not in normalized_colors:
            normalized_colors.append(normalized)
    settings.custom_colors = normalized_colors
    sanitized_profiles: dict[str, dict[str, float]] = {}
    for key in LINE_KEYS:
        raw = settings.line_profiles.get(key, {}) if isinstance(settings.line_profiles, dict) else {}
        if not isinstance(raw, dict):
            continue
        sanitized: dict[str, float] = {}
        enabled = bool(raw.get("enabled", False))
        if enabled:
            sanitized["enabled"] = True
        for field_name, (minimum, maximum, _) in LINE_FIELD_LIMITS.items():
            if field_name in raw:
                try:
                    value = float(raw[field_name])
                except (TypeError, ValueError):
                    continue
                if field_name != "tip_offset" and field_name != "angle_offset":
                    value = clamp(int(value), minimum, maximum)
                else:
                    value = max(minimum, min(maximum, value))
                sanitized[field_name] = value
        if sanitized:
            sanitized_profiles[key] = sanitized
    settings.line_profiles = sanitized_profiles

    sanitized_components: dict[str, list[dict]] = {}
    raw_components = settings.line_components if isinstance(settings.line_components, dict) else {}
    for key in LINE_KEYS:
        component_list = []
        items = raw_components.get(key, []) if isinstance(raw_components, dict) else []
        if not isinstance(items, list):
            continue
        for comp in items:
            if not isinstance(comp, dict):
                continue
            comp_type = comp.get("type")
            if comp_type not in COMPONENT_TYPES:
                continue
            limits = COMPONENT_FIELD_LIMITS[comp_type]
            sanitized_comp = {"type": comp_type}
            valid = True
            for field_name, (minimum, maximum, _) in limits.items():
                if field_name not in comp:
                    valid = False
                    break
                try:
                    value = float(comp[field_name])
                except (TypeError, ValueError):
                    valid = False
                    break
                value = max(minimum, min(maximum, value))
                sanitized_comp[field_name] = value
            if valid:
                component_list.append(sanitized_comp)
        if component_list:
            sanitized_components[key] = component_list
    settings.line_components = sanitized_components

    sanitized_layers: List[dict] = []
    raw_layers = settings.line_layers if isinstance(settings.line_layers, list) else []
    for entry in raw_layers:
        if not isinstance(entry, dict):
            continue
        layer_id = entry.get("id")
        if not isinstance(layer_id, str) or not layer_id.strip():
            layer_id = uuid4().hex
        label = str(entry.get("label") or "Custom Line")
        try:
            angle = float(entry.get("angle", 0.0)) % 360
            angle_offset = float(entry.get("angle_offset", 0.0))
            gap_value = float(entry.get("gap", settings.gap))
            length_value = float(entry.get("length", settings.length))
            thickness_value = float(entry.get("thickness", settings.thickness))
            tip_offset = float(entry.get("tip_offset", 0.0))
        except (TypeError, ValueError):
            continue
        components_data = entry.get("components", [])
        sanitized_stack: list[dict] = []
        if isinstance(components_data, list):
            for component in components_data:
                if not isinstance(component, dict):
                    continue
                comp_type = component.get("type")
                if comp_type not in COMPONENT_TYPES:
                    continue
                limits = COMPONENT_FIELD_LIMITS[comp_type]
                sanitized_component = {"type": comp_type}
                valid_component = True
                for field_name, (minimum, maximum, _) in limits.items():
                    if field_name not in component:
                        valid_component = False
                        break
                    try:
                        value = float(component[field_name])
                    except (TypeError, ValueError):
                        valid_component = False
                        break
                    sanitized_component[field_name] = max(minimum, min(maximum, value))
                if valid_component:
                    sanitized_stack.append(sanitized_component)
        sanitized_layers.append(
            {
                "id": layer_id,
                "label": label[:48],
                "enabled": bool(entry.get("enabled", True)),
                "angle": angle,
                "angle_offset": angle_offset,
                "gap": max(0.0, gap_value),
                "length": max(0.0, length_value),
                "thickness": max(0.1, thickness_value),
                "tip_offset": tip_offset,
                "components": sanitized_stack,
            }
        )
    settings.line_layers = sanitized_layers
    return settings


def save_settings_to_disk(settings: StandardCrosshairSettings) -> None:
    """Persist crosshair settings to disk."""
    try:
        CONFIG_PATH.write_text(json.dumps(asdict(settings), indent=2))
    except Exception:
        pass


def render_crosshair_on_label(
    label: QLabel,
    settings: StandardCrosshairSettings,
    extra_rotation: float = 0.0,
) -> None:
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
    pixmap = generate_crosshair_pixmap(width, height, settings, extra_rotation)
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


def generate_crosshair_pixmap(
    width: int,
    height: int,
    settings: StandardCrosshairSettings,
    extra_rotation: float = 0.0,
) -> QPixmap:
    """Create a transparent pixmap containing the configured crosshair."""
    pixmap = QPixmap(max(1, width), max(1, height))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    center_x = width / 2 + settings.offset_x
    center_y = height / 2 + settings.offset_y
    default_gap = float(max(0, settings.gap))
    default_length = float(max(0, settings.length))
    default_thickness = float(max(1, settings.thickness))
    outline = float(max(0, settings.outline))
    rounding = float(max(0, settings.line_rounding))
    total_rotation = (float(settings.rotation) + float(extra_rotation)) % 360

    color = QColor(settings.red, settings.green, settings.blue, settings.alpha)
    outline_color = QColor(0, 0, 0, settings.alpha)
    line_profiles = settings.line_profiles if isinstance(settings.line_profiles, dict) else {}
    line_component_map = settings.line_components if isinstance(settings.line_components, dict) else {}

    painter.setPen(Qt.PenStyle.NoPen)
    angle_map = STYLE_ANGLES.get(settings.crosshair_style, STYLE_ANGLES["plus"])

    def draw_segment_shape(total_angle: float, start: float, length: float, thickness: float, tip_offset: float, perp_offset: float = 0.0, component_rotation: float = 0.0) -> None:
        length = max(0.0, length)
        thickness = max(0.1, thickness)
        start_pos = start
        end_pos = start + length
        half = thickness / 2
        use_tip = abs(tip_offset) >= 0.01

        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(total_angle + total_rotation)
        painter.translate(0.0, perp_offset)
        # Apply component rotation around its own center (at start position)
        if abs(component_rotation) > 0.01:
            painter.translate(start + length / 2, 0)
            painter.rotate(component_rotation)
            painter.translate(-(start + length / 2), 0)

        def paint_path(begin: float, finish: float, half_size: float, tip: float, brush: QColor) -> None:
            painter.setBrush(brush)
            if use_tip:
                path = QPainterPath(QPointF(begin, -half_size))
                path.lineTo(QPointF(finish, -half_size + tip))
                path.lineTo(QPointF(finish, half_size + tip))
                path.lineTo(QPointF(begin, half_size))
                path.closeSubpath()
                painter.drawPath(path)
            elif rounding > 0:
                painter.drawRoundedRect(QRectF(begin, -half_size, finish - begin, half_size * 2), rounding, rounding)
            else:
                painter.drawRect(QRectF(begin, -half_size, finish - begin, half_size * 2))

        if outline > 0:
            paint_path(start_pos - outline, end_pos + outline, half + outline, tip_offset, outline_color)
        paint_path(start_pos, end_pos, half, tip_offset, color)
        painter.restore()

    def draw_circle_shape(total_angle: float, offset: float, radius: float, perp_offset: float = 0.0, component_rotation: float = 0.0) -> None:
        radius = max(0.1, radius)
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(total_angle + total_rotation)
        painter.translate(offset, perp_offset)
        # Circles don't need rotation, but parameter kept for consistency
        if outline > 0:
            painter.setBrush(outline_color)
            painter.drawEllipse(QPointF(0, 0), radius + outline, radius + outline)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(0, 0), radius, radius)
        painter.restore()

    def render_component_stack(component_stack, base_angle: float, angle_offset: float, fallback_thickness: float) -> bool:
        if not isinstance(component_stack, list) or not component_stack:
            return False
        rendered = False
        for component in component_stack:
            if not isinstance(component, dict):
                continue
            ctype = component.get("type")
            try:
                if ctype == "segment":
                    offset = float(component.get("offset", 0.0))
                    perp_offset = float(component.get("perp_offset", 0.0))
                    length = float(component.get("length", 0.0))
                    thickness = float(component.get("thickness", fallback_thickness))
                    component_angle = float(component.get("angle_offset", 0.0))
                    component_tip = float(component.get("tip_offset", 0.0))
                    draw_segment_shape(base_angle + angle_offset, offset, length, thickness, component_tip, perp_offset, component_angle)
                    rendered = True
                elif ctype == "circle":
                    offset = float(component.get("offset", 0.0))
                    perp_offset = float(component.get("perp_offset", 0.0))
                    radius = float(component.get("radius", fallback_thickness / 2))
                    draw_circle_shape(base_angle + angle_offset, offset, radius, perp_offset)
                    rendered = True
            except (TypeError, ValueError):
                continue
        return rendered

    def draw_basic_line(
        base_angle: float,
        angle_offset: float,
        line_gap: float,
        line_length: float,
        line_thickness: float,
        tip_offset: float,
    ) -> None:
        line_gap = max(0.0, line_gap)
        line_length = max(0.0, line_length)
        line_thickness = max(0.1, line_thickness)
        draw_segment_shape(base_angle + angle_offset, line_gap, line_length, line_thickness, tip_offset)

    def draw_arm(attr_name: str, base_angle: float) -> None:
        profile_key = ATTR_TO_LINE_KEY.get(attr_name, "")
        overrides = line_profiles.get(profile_key, {}) if isinstance(line_profiles, dict) else {}
        component_stack = line_component_map.get(profile_key, []) if isinstance(line_component_map, dict) else []
        use_custom = bool(overrides.get("enabled", False))
        line_gap = float(overrides.get("gap", default_gap)) if use_custom else default_gap
        line_length = float(overrides.get("length", default_length)) if use_custom else default_length
        line_thickness = float(overrides.get("thickness", default_thickness)) if use_custom else default_thickness
        angle_offset = float(overrides.get("angle_offset", 0.0)) if use_custom else 0.0
        tip_offset = float(overrides.get("tip_offset", 0.0)) if use_custom else 0.0
        if render_component_stack(component_stack, base_angle, angle_offset, line_thickness):
            return
        draw_basic_line(base_angle, angle_offset, line_gap, line_length, line_thickness, tip_offset)

    for attr, base_angle in angle_map.items():
        if getattr(settings, attr, False):
            draw_arm(attr, base_angle)

    additional_layers = settings.line_layers if isinstance(settings.line_layers, list) else []
    for layer in additional_layers:
        if not isinstance(layer, dict) or not layer.get("enabled", True):
            continue
        try:
            layer_angle = float(layer.get("angle", 0.0))
            layer_angle_offset = float(layer.get("angle_offset", 0.0))
            layer_gap = float(layer.get("gap", default_gap))
            layer_length = float(layer.get("length", default_length))
            layer_thickness = float(layer.get("thickness", default_thickness))
            layer_tip = float(layer.get("tip_offset", 0.0))
        except (TypeError, ValueError):
            continue
        component_stack = layer.get("components", [])
        if render_component_stack(component_stack, layer_angle, layer_angle_offset, layer_thickness):
            continue
        draw_basic_line(layer_angle, layer_angle_offset, layer_gap, layer_length, layer_thickness, layer_tip)

    if settings.center_dot:
        dot_size = max(2, settings.dot_size)
        half = dot_size / 2
        painter.save()
        painter.translate(center_x, center_y)
        dot_rotation = total_rotation
        shape = settings.dot_shape if settings.dot_shape in ALLOWED_DOT_SHAPES else "circle"
        if shape == "square":
            painter.rotate(dot_rotation)
            rect = QRectF(-half, -half, dot_size, dot_size)
            if outline > 0:
                painter.setBrush(outline_color)
                painter.drawRect(rect.adjusted(-outline, -outline, outline, outline))
            painter.setBrush(color)
            painter.drawRect(rect)
        elif shape == "diamond":
            painter.rotate(dot_rotation + 45)
            rect = QRectF(-half, -half, dot_size, dot_size)
            if outline > 0:
                painter.setBrush(outline_color)
                painter.drawRect(rect.adjusted(-outline, -outline, outline, outline))
            painter.setBrush(color)
            painter.drawRect(rect)
        else:
            if outline > 0:
                painter.setBrush(outline_color)
                painter.drawEllipse(QPointF(0, 0), half + outline, half + outline)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(0, 0), half, half)
        painter.restore()

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
        self.line_controls: dict[str, dict[str, object]] = {}
        self._slider_spinboxes: dict[QSlider, QSpinBox] = {}
        self.line_builder_dialog = None
        self._fan_timer = QTimer(self)
        self._fan_timer.setInterval(16)
        self._fan_timer.timeout.connect(self._on_fan_tick)
        self._fan_angle = 0.0

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

        self.setFixedSize(440, 520)

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

        layout.addWidget(self._create_slider_group())
        layout.addWidget(self._create_shape_group())
        layout.addWidget(self._create_dot_group())
        layout.addWidget(self._create_color_group())
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
        self.thickness_slider = self._add_slider(layout, "Thickness", 1, 15, self.settings.thickness, self._on_thickness)
        self.gap_slider = self._add_slider(layout, "Gap", 0, 40, self.settings.gap, self._on_gap)
        self.outline_slider = self._add_slider(layout, "Outline", 0, 5, self.settings.outline, self._on_outline, suffix="px")
        self.gap_slider = self._add_slider(layout, "Gap", 0, 40, self.settings.gap, self._on_gap)
        self.outline_slider = self._add_slider(
            layout, "Outline", 0, 5, self.settings.outline, self._on_outline, suffix="px"
        )
        return frame

    def _create_shape_group(self) -> QFrame:
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

        style_row = QHBoxLayout()
        style_row.addWidget(self._section_label("Crosshair Style"))
        self.plus_style_btn = self._create_choice_button("＋ Plus", self.settings.crosshair_style == "plus")
        self.plus_style_btn.setProperty("style_key", "plus")
        self.x_style_btn = self._create_choice_button("✕ X", self.settings.crosshair_style == "x")
        self.x_style_btn.setProperty("style_key", "x")
        self.plus_style_btn.clicked.connect(lambda: self._set_crosshair_style("plus"))
        self.x_style_btn.clicked.connect(lambda: self._set_crosshair_style("x"))
        style_row.addWidget(self.plus_style_btn)
        style_row.addWidget(self.x_style_btn)
        layout.addLayout(style_row)

        self.rotation_slider = self._add_slider(
            layout,
            "Rotation",
            0,
            360,
            int(self.settings.rotation),
            self._on_rotation,
            suffix="°",
        )
        self.offset_x_slider = self._add_slider(layout, "Horizontal Offset", -800, 800, self.settings.offset_x, self._on_offset_x, suffix="px", step=1)
        self.offset_y_slider = self._add_slider(layout, "Vertical Offset", -800, 800, self.settings.offset_y, self._on_offset_y, suffix="px", step=1)
        self.line_rounding_slider = self._add_slider(layout, "Line Corner Radius", 0, 20, self.settings.line_rounding, self._on_line_rounding, suffix="px")
        self.offset_y_slider = self._add_slider(
            layout,
            "Vertical Offset",
            -800,
            800,
            self.settings.offset_y,
            self._on_offset_y,
            suffix="px",
            step=1,
        )
        self.line_rounding_slider = self._add_slider(
            layout,
            "Line Corner Radius",
            0,
            20,
            self.settings.line_rounding,
            self._on_line_rounding,
            suffix="px",
        )

        fan_row = QHBoxLayout()
        self.fan_checkbox = QCheckBox("Enable Fan Animation")
        self.fan_checkbox.setChecked(self.settings.fan_enabled)
        self.fan_checkbox.setStyleSheet(
            """
            QCheckBox { color: #E0E0E0; font-weight: bold; }
            QCheckBox::indicator { width: 18px; height: 18px; }
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
        self.fan_checkbox.toggled.connect(self._on_fan_toggle)
        fan_row.addWidget(self.fan_checkbox)
        fan_row.addStretch()
        layout.addLayout(fan_row)

        self.fan_speed_slider = self._add_slider(
            layout,
            "Fan Speed",
            -720,
            720,
            self.settings.fan_speed,
            self._on_fan_speed,
            suffix="°/s",
            step=1,
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

        shape_row = QHBoxLayout()
        shape_row.addWidget(self._section_label("Dot Shape"))
        self.circle_btn = self._create_choice_button("◯ Circle", self.settings.dot_shape == "circle")
        self.square_btn = self._create_choice_button("▢ Square", self.settings.dot_shape == "square")
        self.diamond_btn = self._create_choice_button("◇ Diamond", self.settings.dot_shape == "diamond")
        self.circle_btn.clicked.connect(lambda: self._set_dot_shape("circle"))
        self.square_btn.clicked.connect(lambda: self._set_dot_shape("square"))
        self.diamond_btn.clicked.connect(lambda: self._set_dot_shape("diamond"))
        shape_row.addWidget(self.circle_btn)
        shape_row.addWidget(self.square_btn)
        shape_row.addWidget(self.diamond_btn)
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
        layout.setSpacing(10)
        layout.addWidget(self._section_label("Lines & Custom Shapes"))

        rows = [
            ("Left", "show_left"),
            ("Right", "show_right"),
            ("Top", "show_top"),
            ("Bottom", "show_bottom"),
        ]
        for label_text, attr in rows:
            line_key = ATTR_TO_LINE_KEY.get(attr, attr)
            section = QFrame()
            section.setStyleSheet(
                """
                QFrame {
                    background-color: rgba(40, 40, 50, 120);
                    border-radius: 10px;
                    padding: 6px;
                }
            """
            )
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(8, 6, 8, 6)
            section_layout.setSpacing(6)

            header = QHBoxLayout()
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
            header.addWidget(checkbox)
            header.addStretch()

            clone_button = QToolButton()
            clone_button.setText("Clone")
            clone_button.setCursor(Qt.CursorShape.PointingHandCursor)
            clone_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            clone_button.setStyleSheet(
                """
                QToolButton {
                    background-color: rgba(96, 125, 139, 180);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-weight: bold;
                }
                QToolButton:hover { background-color: rgba(120, 150, 160, 200); }
            """
            )
            clone_menu = QMenu(clone_button)
            clone_actions = []
            for _, target_attr in rows:
                target_key = ATTR_TO_LINE_KEY.get(target_attr, target_attr)
                if target_key == line_key:
                    continue
                action = clone_menu.addAction(target_key.title())
                action.triggered.connect(
                    lambda _, src=line_key, dest=target_key: self._clone_line_profile(src, dest)
                )
                clone_actions.append((action, target_key))
            if clone_actions:
                clone_menu.addSeparator()
                clone_all_action = clone_menu.addAction("Clone to All")
                clone_all_action.triggered.connect(lambda _, src=line_key: self._clone_line_profile(src, None))
                clone_actions.append((clone_all_action, None))
            clone_button.setMenu(clone_menu)
            header.addWidget(clone_button)

            customize_btn = QToolButton()
            customize_btn.setText("Customize")
            customize_btn.setCheckable(True)
            customize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            customize_btn.setStyleSheet(
                """
                QToolButton {
                    background-color: rgba(92, 107, 192, 180);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-weight: bold;
                }
                QToolButton:checked { background-color: rgba(76, 175, 80, 200); }
            """
            )
            header.addWidget(customize_btn)
            section_layout.addLayout(header)

            custom_frame = QFrame()
            custom_frame.setStyleSheet(
                """
                QFrame {
                    background-color: rgba(30, 30, 35, 160);
                    border-radius: 8px;
                    padding: 6px;
                }
            """
            )
            custom_frame.setVisible(False)
            customize_btn.toggled.connect(custom_frame.setVisible)

            custom_layout = QVBoxLayout(custom_frame)
            custom_layout.setContentsMargins(4, 4, 4, 4)
            custom_layout.setSpacing(6)

            custom_toggle = QCheckBox("Enable custom shape")
            custom_toggle.setStyleSheet("QCheckBox { color: #E0E0E0; font-weight: bold; }")
            custom_toggle.toggled.connect(lambda checked, key=line_key: self._on_line_custom_toggle(key, checked))
            custom_layout.addWidget(custom_toggle)

            grid = QGridLayout()
            grid.setVerticalSpacing(6)
            grid.setHorizontalSpacing(10)
            spins: dict[str, QSpinBox] = {}
            field_order = [
                ("Length", "length"),
                ("Gap", "gap"),
                ("Thickness", "thickness"),
                ("Angle", "angle_offset"),
                ("Bend Offset", "tip_offset"),
            ]
            for row_index, (title, field_name) in enumerate(field_order):
                minimum, maximum, unit = LINE_FIELD_LIMITS[field_name]
                clamp_min = int(minimum)
                clamp_max = int(maximum)
                span = clamp_max - clamp_min
                buffer = max(100, abs(span) * 2 if span else 200)
                label = QLabel(title)
                label.setStyleSheet("color: #B0B0B0; font-size: 11px;")
                spin = QSpinBox()
                spin.setRange(clamp_min - buffer, clamp_max + buffer)
                spin.setSingleStep(1)
                spin.setAccelerated(True)
                spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                spin.setStyleSheet(
                    """
                    QSpinBox {
                        background-color: rgba(40, 40, 50, 200);
                        border: 1px solid rgba(100, 100, 120, 120);
                        border-radius: 6px;
                        padding: 4px 8px;
                        color: #E0E0E0;
                        min-width: 70px;
                    }
                    QSpinBox:disabled {
                        background-color: rgba(50, 50, 60, 120);
                        color: rgba(220, 220, 220, 80);
                    }
                """
                )
                spin.valueChanged.connect(
                    lambda val, key=line_key, field=field_name, cmin=clamp_min, cmax=clamp_max:
                    self._on_line_profile_value_if_valid(key, field, val, cmin, cmax)
                )

                def make_edit_handler(spin_box: QSpinBox, key: str, field: str, min_val: float, max_val: float):
                    def handler() -> None:
                        val = spin_box.value()
                        clamped = int(max(min_val, min(max_val, val)))
                        if clamped != val:
                            spin_box.blockSignals(True)
                            spin_box.setValue(clamped)
                            spin_box.blockSignals(False)
                        self._on_line_profile_value_changed(key, field, clamped)

                    return handler

                spin.editingFinished.connect(make_edit_handler(spin, line_key, field_name, minimum, maximum))
                grid.addWidget(label, row_index, 0)
                grid.addWidget(spin, row_index, 1)
                if unit:
                    unit_label = QLabel(unit)
                    unit_label.setStyleSheet("color: #B0B0B0; font-size: 11px; padding-left: 4px;")
                    grid.addWidget(unit_label, row_index, 2)
                spins[field_name] = spin
            custom_layout.addLayout(grid)

            buttons_row = QHBoxLayout()
            reset_btn = QPushButton("Reset Line")
            reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            reset_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: rgba(255, 152, 0, 180);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: rgba(255, 171, 64, 200); }
            """
            )
            reset_btn.clicked.connect(lambda _, key=line_key: self._reset_line_profile(key))
            buttons_row.addWidget(reset_btn)
            buttons_row.addStretch()
            custom_layout.addLayout(buttons_row)

            section_layout.addWidget(custom_frame)
            layout.addWidget(section)

            self.line_controls[line_key] = {
                "checkbox": checkbox,
                "custom_frame": custom_frame,
                "custom_button": customize_btn,
                "custom_toggle": custom_toggle,
                "spins": spins,
                "clone_actions": clone_actions,
            }

        builder_card = QFrame()
        builder_card.setStyleSheet(
            """
            QFrame {
                background-color: rgba(0, 188, 212, 30);
                border-radius: 12px;
                border: 1px solid rgba(0, 188, 212, 140);
                padding: 12px;
            }
        """
        )
        builder_row = QHBoxLayout(builder_card)
        builder_row.setSpacing(12)
        builder_row.setContentsMargins(8, 4, 8, 4)
        helper = QLabel(
            "Open the advanced line builder to stack extra spokes, drag their order, and drop geometric objects much like the image editor."
        )
        helper.setWordWrap(True)
        helper.setStyleSheet("color: rgba(230, 255, 255, 200); font-weight: bold;")
        builder_row.addWidget(helper, 1)
        builder_btn = QPushButton("Open Line Builder")
        builder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        builder_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(0, 188, 212, 220);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(0, 200, 220, 240); }
        """
        )
        builder_btn.clicked.connect(self._open_line_builder)
        builder_row.addWidget(builder_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(builder_card)
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

    def _add_slider(
        self,
        layout: QVBoxLayout,
        label_text: str,
        minimum: int,
        maximum: int,
        value: int,
        callback,
        suffix: str = "px",
        step: int = 1,
    ) -> QSlider:
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

        clamp_min = minimum
        clamp_max = maximum

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setValue(value)
        slider.setSingleStep(max(1, step))
        slider.setPageStep(max(5, step * 4))
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

        spin = QSpinBox()
        span = clamp_max - clamp_min
        buffer = max(100, abs(span) * 2 if span else 200)
        spin.setRange(clamp_min - buffer, clamp_max + buffer)
        spin.setSingleStep(max(1, step))
        spin.setAccelerated(True)
        spin.setValue(value)
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        spin.setStyleSheet(
            """
            QSpinBox {
                background-color: rgba(40, 40, 50, 200);
                border: 1px solid rgba(100, 100, 120, 120);
                border-radius: 6px;
                padding: 4px 10px;
                color: #E0E0E0;
                min-width: 68px;
            }
            QSpinBox:disabled {
                background-color: rgba(55, 55, 65, 150);
                color: rgba(220, 220, 220, 90);
            }
        """
        )

        unit_label = None
        if suffix:
            unit_label = QLabel(suffix)
            unit_label.setStyleSheet("color: #B0B0B0; font-size: 11px; padding-left: 4px;")

        def on_value_change(val: int) -> None:
            if spin.value() != val:
                spin.blockSignals(True)
                spin.setValue(val)
                spin.blockSignals(False)
            callback(val)

        slider.valueChanged.connect(on_value_change)

        def on_spin_change(val: int) -> None:
            if clamp_min <= val <= clamp_max:
                if slider.value() != val:
                    slider.blockSignals(True)
                    slider.setValue(val)
                    slider.blockSignals(False)
                callback(val)

        spin.valueChanged.connect(on_spin_change)

        def on_spin_edit_finished() -> None:
            val = spin.value()
            clamped = max(clamp_min, min(clamp_max, val))
            if clamped != val:
                spin.blockSignals(True)
                spin.setValue(clamped)
                spin.blockSignals(False)
            if slider.value() != clamped:
                slider.blockSignals(True)
                slider.setValue(clamped)
                slider.blockSignals(False)
            callback(clamped)

        spin.editingFinished.connect(on_spin_edit_finished)

        self._slider_spinboxes[slider] = spin

        slider_layout.addWidget(slider)
        slider_layout.addWidget(spin)
        if unit_label is not None:
            slider_layout.addWidget(unit_label)
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
        spin = self._slider_spinboxes.get(slider)
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

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
            (getattr(self, "rotation_slider", None), int(self.settings.rotation)),
            (getattr(self, "offset_x_slider", None), self.settings.offset_x),
            (getattr(self, "offset_y_slider", None), self.settings.offset_y),
            (getattr(self, "line_rounding_slider", None), self.settings.line_rounding),
            (getattr(self, "fan_speed_slider", None), self.settings.fan_speed),
        ):
            if slider is not None:
                self._set_slider_value(slider, value)

        self._update_color_preview()
        self._update_hex_input()

        if hasattr(self, "circle_btn"):
            self._update_shape_buttons()
        self._update_style_buttons()

        for attr, checkbox in getattr(self, "line_checkboxes", {}).items():
            if checkbox is not None:
                checkbox.blockSignals(True)
                checkbox.setChecked(getattr(self.settings, attr))
                checkbox.blockSignals(False)
        self._update_line_checkbox_labels()
        self._update_line_custom_controls()
        self._update_clone_menu_labels()

        if hasattr(self, "fan_checkbox"):
            self.fan_checkbox.blockSignals(True)
            self.fan_checkbox.setChecked(self.settings.fan_enabled)
            self.fan_checkbox.blockSignals(False)

        self.label.setVisible(self.settings.visible)
        if self.settings.visible:
            self.label.raise_()
        self._update_visibility_button()
        if self.settings.fan_enabled:
            self._start_fan_timer()
        else:
            self._stop_fan_timer()
        self._render_current_state()

    def _render_current_state(self) -> None:
        extra_rotation = self._fan_angle if self.settings.fan_enabled else 0.0
        render_crosshair_on_label(self.label, self.settings, extra_rotation=extra_rotation)

    def _persist_and_render(self) -> None:
        self._render_current_state()
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

    def _start_fan_timer(self) -> None:
        if not self.settings.fan_enabled:
            return
        if not self._fan_timer.isActive():
            self._fan_timer.start()

    def _stop_fan_timer(self) -> None:
        if self._fan_timer.isActive():
            self._fan_timer.stop()
        self._fan_angle = 0.0

    def _update_overlay_draggable_state(self) -> None:
        """Toggle the WindowTransparentForInput flag based on draggable mode."""
        current_flags = self.label.windowFlags()
        if self.settings.draggable_mode:
            # Remove WindowTransparentForInput to enable mouse events
            new_flags = current_flags & ~Qt.WindowType.WindowTransparentForInput
            self.label.setWindowFlags(new_flags)
            self.label.show()
            # Install event filter for mouse handling
            if not hasattr(self.label, '_dragging_installed'):
                self.label.mousePressEvent = self._overlay_mouse_press
                self.label.mouseMoveEvent = self._overlay_mouse_move
                self.label.mouseReleaseEvent = self._overlay_mouse_release
                self.label._drag_start = None
                self.label._dragging_installed = True
        else:
            # Re-add WindowTransparentForInput to ignore mouse events
            new_flags = current_flags | Qt.WindowType.WindowTransparentForInput
            self.label.setWindowFlags(new_flags)
            self.label.show()

    def _overlay_mouse_press(self, event) -> None:
        """Handle mouse press on overlay label."""
        if event.button() == Qt.MouseButton.LeftButton and self.settings.draggable_mode:
            self.label._drag_start = event.globalPosition().toPoint()
            event.accept()

    def _overlay_mouse_move(self, event) -> None:
        """Handle mouse move on overlay label."""
        if self.label._drag_start is not None and self.settings.draggable_mode:
            delta = event.globalPosition().toPoint() - self.label._drag_start
            self.label._drag_start = event.globalPosition().toPoint()
            
            # Apply delta to offset
            new_x = self.settings.offset_x + delta.x()
            new_y = self.settings.offset_y + delta.y()
            
            # Apply grid snapping
            if self.settings.grid_snap_size > 1:
                new_x = round(new_x / self.settings.grid_snap_size) * self.settings.grid_snap_size
                new_y = round(new_y / self.settings.grid_snap_size) * self.settings.grid_snap_size
            
            self.settings.offset_x = new_x
            self.settings.offset_y = new_y
            
            # Update UI controls if they exist
            if hasattr(self, 'offset_x_slider'):
                self.offset_x_slider.blockSignals(True)
                self.offset_x_slider.setValue(new_x)
                self.offset_x_slider.blockSignals(False)
            if hasattr(self, 'offset_y_slider'):
                self.offset_y_slider.blockSignals(True)
                self.offset_y_slider.setValue(new_y)
                self.offset_y_slider.blockSignals(False)
            
            self._render_current_state()
            event.accept()

    def _overlay_mouse_release(self, event) -> None:
        """Handle mouse release on overlay label."""
        if event.button() == Qt.MouseButton.LeftButton and self.settings.draggable_mode:
            self.label._drag_start = None
            save_settings_to_disk(self.settings)
            event.accept()

    def _on_fan_tick(self) -> None:
        if not self.settings.fan_enabled:
            return
        interval_seconds = self._fan_timer.interval() / 1000.0
        self._fan_angle = (self._fan_angle + self.settings.fan_speed * interval_seconds) % 360
        self._render_current_state()

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

    def _on_rotation(self, value: int) -> None:
        self.settings.rotation = value % 360
        self._persist_and_render()

    def _on_offset_x(self, value: int) -> None:
        self.settings.offset_x = value
        self._persist_and_render()

    def _on_offset_y(self, value: int) -> None:
        self.settings.offset_y = value
        self._persist_and_render()

    def _on_line_rounding(self, value: int) -> None:
        self.settings.line_rounding = max(0, value)
        self._persist_and_render()

    def _on_fan_toggle(self, enabled: bool) -> None:
        self.settings.fan_enabled = enabled
        if enabled:
            self._start_fan_timer()
        else:
            self._stop_fan_timer()
        self._persist_and_render()

    def _on_fan_speed(self, value: int) -> None:
        self.settings.fan_speed = max(-360, min(360, value))
        if self.settings.fan_enabled and not self._fan_timer.isActive():
            self._start_fan_timer()
        self._persist_and_render()

    def _set_dot_shape(self, shape: str) -> None:
        if shape not in ALLOWED_DOT_SHAPES:
            return
        self.settings.dot_shape = shape
        self._update_shape_buttons()
        self._persist_and_render()

    def _set_crosshair_style(self, style: str) -> None:
        if style not in ALLOWED_CROSSHAIR_STYLES:
            return
        if self.settings.crosshair_style == style:
            return
        self.settings.crosshair_style = style
        self._update_style_buttons()
        self._update_line_checkbox_labels()
        self._persist_and_render()

    def _update_style_buttons(self) -> None:
        buttons = [
            getattr(self, "plus_style_btn", None),
            getattr(self, "x_style_btn", None),
        ]
        for btn in buttons:
            if btn is None:
                continue
            style_key = btn.property("style_key") or "plus"
            is_active = self.settings.crosshair_style == style_key
            btn.blockSignals(True)
            btn.setChecked(is_active)
            btn.setStyleSheet(self._choice_button_style(is_active))
            btn.blockSignals(False)

    def _update_line_checkbox_labels(self) -> None:
        labels = STYLE_LABELS.get(self.settings.crosshair_style, STYLE_LABELS["plus"])
        for attr, checkbox in self.line_checkboxes.items():
            if checkbox is None:
                continue
            checkbox.setText(labels.get(attr, attr.replace("_", " ").title()))

    def _update_line_custom_controls(self) -> None:
        for line_key, controls in self.line_controls.items():
            profile = self.settings.line_profiles.get(line_key, {}) if isinstance(self.settings.line_profiles, dict) else {}
            enabled = bool(profile.get("enabled", False))
            toggle = controls.get("custom_toggle")
            if isinstance(toggle, QCheckBox):
                toggle.blockSignals(True)
                toggle.setChecked(enabled)
                toggle.blockSignals(False)
            spins = controls.get("spins", {})
            for field_name, spin in spins.items():
                if not isinstance(spin, QSpinBox):
                    continue
                default_value = self._line_field_default(field_name)
                raw_value = profile.get(field_name, default_value)
                spin.blockSignals(True)
                spin.setValue(int(raw_value))
                spin.blockSignals(False)
                spin.setEnabled(enabled)

    def _update_clone_menu_labels(self) -> None:
        labels = STYLE_LABELS.get(self.settings.crosshair_style, STYLE_LABELS["plus"])
        for line_key, controls in self.line_controls.items():
            actions = controls.get("clone_actions", [])
            for action, target_key in actions:
                if target_key is None:
                    action.setText("Clone to All")
                    continue
                attr_name = LINE_KEY_TO_ATTR.get(target_key, target_key)
                action.setText(labels.get(attr_name, target_key.title()))

    def _line_field_default(self, field_name: str) -> int:
        if field_name == "length":
            return int(self.settings.length)
        if field_name == "gap":
            return int(self.settings.gap)
        if field_name == "thickness":
            return int(self.settings.thickness)
        return 0

    def _ensure_line_profile(self, line_key: str) -> dict[str, float]:
        if not isinstance(self.settings.line_profiles, dict):
            self.settings.line_profiles = {}
        profile = self.settings.line_profiles.get(line_key)
        if not isinstance(profile, dict):
            profile = {}
            self.settings.line_profiles[line_key] = profile
        return profile

    def _on_line_custom_toggle(self, line_key: str, enabled: bool) -> None:
        profile = self._ensure_line_profile(line_key)
        profile["enabled"] = enabled
        self._update_line_custom_controls()
        self._persist_and_render()

    def _on_line_profile_value_changed(self, line_key: str, field: str, value: int) -> None:
        minimum, maximum, _ = LINE_FIELD_LIMITS[field]
        clamped = max(minimum, min(maximum, value))
        profile = self._ensure_line_profile(line_key)
        profile[field] = clamped
        profile["enabled"] = True
        self._update_line_custom_controls()
        self._persist_and_render()

    def _on_line_profile_value_if_valid(
        self, line_key: str, field: str, value: int, minimum: int, maximum: int
    ) -> None:
        if minimum <= value <= maximum:
            self._on_line_profile_value_changed(line_key, field, value)

    def _reset_line_profile(self, line_key: str) -> None:
        if isinstance(self.settings.line_profiles, dict) and line_key in self.settings.line_profiles:
            self.settings.line_profiles.pop(line_key, None)
        self._update_line_custom_controls()
        self._persist_and_render()

    def _clone_line_profile(self, source_key: str, target_key: Optional[str]) -> None:
        if not isinstance(self.settings.line_profiles, dict):
            return
        source_profile = self.settings.line_profiles.get(source_key)
        if not isinstance(source_profile, dict):
            return
        targets = []
        if target_key is None:
            targets = [key for key in LINE_KEYS if key != source_key]
        else:
            targets = [target_key]
        for key in targets:
            self.settings.line_profiles[key] = dict(source_profile)
        self._update_line_custom_controls()
        self._persist_and_render()

    def _open_line_builder(self) -> None:
        if self.line_builder_dialog is None:
            self.line_builder_dialog = LineBuilderDialog(self)
            self.line_builder_dialog.destroyed.connect(lambda: setattr(self, "line_builder_dialog", None))
        self.line_builder_dialog.show()
        self.line_builder_dialog.raise_()
        self.line_builder_dialog.activateWindow()

    def _update_shape_buttons(self) -> None:
        if not hasattr(self, "circle_btn") or not hasattr(self, "square_btn"):
            return
        buttons = [
            (self.circle_btn, self.settings.dot_shape == "circle"),
            (self.square_btn, self.settings.dot_shape == "square"),
        ]
        if hasattr(self, "diamond_btn"):
            buttons.append((self.diamond_btn, self.settings.dot_shape == "diamond"))
        for btn, active in buttons:
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

    def _apply_custom_palette_to_dialog(self) -> None:
        if not self.settings.custom_colors:
            return
        for idx, hex_value in enumerate(self.settings.custom_colors[:MAX_CUSTOM_COLORS]):
            QColorDialog.setCustomColor(idx, QColor(hex_value))

    def _capture_custom_palette_from_dialog(self) -> None:
        collected: List[str] = []
        for idx in range(MAX_CUSTOM_COLORS):
            rgb_value = QColorDialog.customColor(idx)
            color = QColor(rgb_value)
            hex_code = color.name().upper()
            if hex_code not in collected:
                collected.append(hex_code)
        self.settings.custom_colors = collected
        save_settings_to_disk(self.settings)

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
        self._apply_custom_palette_to_dialog()
        color = QColorDialog.getColor(
            initial,
            self,
            "Pick Crosshair Color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        self._capture_custom_palette_from_dialog()
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
        preserved_palette = list(self.settings.custom_colors)
        self.settings = StandardCrosshairSettings(visible=current_visibility, custom_colors=preserved_palette)
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


class QHBoxLayoutWidget(QWidget):
    """Utility widget exposing a zero-margin horizontal layout."""

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)


class LineBuilderDialog(QWidget):
    """Advanced workspace for building custom line layers and objects."""

    def __init__(self, parent_dialog: StandardCrosshairDialog):
        super().__init__(parent_dialog)
        self.parent_dialog = parent_dialog
        self.settings = parent_dialog.settings
        self.active_scope_kind: Optional[str] = None  # "standard" or "custom"
        self.active_scope_id: Optional[str] = None
        self.segment_fields: dict[str, QDoubleSpinBox] = {}
        self.circle_fields: dict[str, QDoubleSpinBox] = {}
        self.component_insert_buttons: list[QPushButton] = []
        self.component_modify_buttons: list[QPushButton] = []
        self.show_grid = True
        self.grid_size = 20
        self.grid_snap_enabled = True
        self.dragging_component = None
        self.drag_start_pos = None
        self.selected_component = None
        self.selection_handles = []
        self.hover_handle = None
        self.rotating = False
        self.rotation_start_angle = 0
        self.resize_mode = None

        self.setWindowTitle("Advanced Line Builder")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(580, 440)

        self._build_ui()
        self._build_standard_list()
        self._build_custom_list()
        self._select_initial_scope()
        self._update_preview()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        intro = QLabel("Shape stacked lines, drag their order, and preview the result instantly.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #E0F7FA; font-weight: bold; font-size: 10px;")
        intro.setVisible(False)
        layout.addWidget(intro)

        body = QHBoxLayout()
        body.setSpacing(10)
        layout.addLayout(body, 1)

        left_panel_wrapper = QVBoxLayout()
        left_panel_wrapper.setSpacing(2)
        body.addLayout(left_panel_wrapper, 0)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(4)
        self.left_panel_toggle = QToolButton()
        self.left_panel_toggle.setText("◀")
        self.left_panel_toggle.setCheckable(True)
        self.left_panel_toggle.setChecked(True)
        self.left_panel_toggle.setToolTip("Show or hide the line lists")
        self.left_panel_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.left_panel_toggle.setStyleSheet(
            "QToolButton { background-color: rgba(0, 188, 212, 120); color: white; border: none; border-radius: 6px; padding: 3px 6px; font-weight: bold; }"
            "QToolButton:checked { background-color: rgba(0, 188, 212, 200); }"
        )
        self.left_panel_toggle.toggled.connect(self._toggle_left_panel)
        toggle_row.addWidget(self.left_panel_toggle)
        toggle_row.addStretch()
        left_panel_wrapper.addLayout(toggle_row)

        self.left_panel = QWidget()
        left_panel_layout = QVBoxLayout(self.left_panel)
        left_panel_layout.setContentsMargins(0, 0, 0, 0)
        left_panel_layout.setSpacing(6)
        left_panel_wrapper.addWidget(self.left_panel)

        left_panel = left_panel_layout

        left_panel.addWidget(self._subheading("Standard Lines"))
        self.standard_list = QListWidget()
        self.standard_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.standard_list.setStyleSheet(
            "QListWidget { background-color: rgba(34,34,44,240); border-radius: 8px; border: 1px solid rgba(255,255,255,40); }"
        )
        self.standard_list.setMaximumHeight(120)
        self.standard_list.currentRowChanged.connect(self._on_standard_selection_changed)
        left_panel.addWidget(self.standard_list)

        std_hint = QLabel("Standard lines still respect the toggles above; builder layers optional geometry on top.")
        std_hint.setWordWrap(True)
        std_hint.setStyleSheet("color: rgba(220, 220, 220, 140); font-size: 9px;")
        std_hint.setVisible(False)
        left_panel.addWidget(std_hint)

        left_panel.addWidget(self._subheading("Custom Lines"))
        self.custom_list = QListWidget()
        self.custom_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.custom_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.custom_list.setStyleSheet(
            "QListWidget { background-color: rgba(34,34,44,240); border-radius: 8px; border: 1px solid rgba(0,188,212,80); }"
        )
        self.custom_list.model().rowsMoved.connect(self._on_custom_rows_moved)
        self.custom_list.currentRowChanged.connect(self._on_custom_selection_changed)
        left_panel.addWidget(self.custom_list, 1)

        custom_hint = QLabel("Drag custom lines to reorder draw priority or stack multiple spokes at once.")
        custom_hint.setWordWrap(True)
        custom_hint.setStyleSheet("color: rgba(220, 220, 220, 140); font-size: 9px;")
        custom_hint.setVisible(False)
        left_panel.addWidget(custom_hint)

        custom_buttons = QHBoxLayout()
        custom_buttons.setSpacing(4)
        self.add_line_btn = QPushButton("＋ Add Line")
        self.add_line_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_line_btn.setStyleSheet("QPushButton { background-color: rgba(0,188,212,180); color: white; border: none; border-radius: 6px; padding: 4px 8px; font-weight: bold; }")
        self.add_line_btn.clicked.connect(self._on_add_custom_line)
        custom_buttons.addWidget(self.add_line_btn)

        self.duplicate_line_btn = QPushButton("⧉ Duplicate")
        self.duplicate_line_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.duplicate_line_btn.setStyleSheet("QPushButton { background-color: rgba(92,107,192,180); color: white; border: none; border-radius: 6px; padding: 4px 8px; font-weight: bold; }")
        self.duplicate_line_btn.clicked.connect(self._on_duplicate_custom_line)
        custom_buttons.addWidget(self.duplicate_line_btn)

        self.remove_line_btn = QPushButton("✖ Remove")
        self.remove_line_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_line_btn.setStyleSheet("QPushButton { background-color: rgba(244,67,54,180); color: white; border: none; border-radius: 6px; padding: 4px 8px; font-weight: bold; }")
        self.remove_line_btn.clicked.connect(self._on_remove_custom_line)
        custom_buttons.addWidget(self.remove_line_btn)
        left_panel.addLayout(custom_buttons)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(6)
        body.addLayout(right_panel, 2)

        right_panel.addWidget(self._create_preview_card())
        right_panel.addWidget(self._create_metadata_panel(), 3)
        right_panel.addWidget(self._create_component_panel(), 1)

        self._update_custom_buttons_state()
        self._component_buttons_enabled(False, False)

    def _subheading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #B0E1FF; font-weight: bold; font-size: 11px;")
        return label

    def _toggle_left_panel(self, visible: bool) -> None:
        self.left_panel.setVisible(visible)
        self.left_panel_toggle.setText("◀" if visible else "▶")

    def _create_preview_card(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: rgba(25, 25, 35, 230); border-radius: 8px; border: 1px solid rgba(255,255,255,30); padding: 6px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setSpacing(3)
        
        header_row = QHBoxLayout()
        header_row.addWidget(self._subheading("Live Preview"))
        
        self.grid_toggle = QCheckBox()
        self.grid_toggle.setChecked(self.show_grid)
        self.grid_toggle.setStyleSheet("QCheckBox { color: #E0E0E0; font-size: 10px; font-weight: bold; }")
        self.grid_toggle.toggled.connect(self._on_grid_toggle)
        header_row.addWidget(self.grid_toggle)
        
        self.snap_toggle = QCheckBox("⚲ Snap")
        self.snap_toggle.setChecked(self.grid_snap_enabled)
        self.snap_toggle.setStyleSheet("QCheckBox { color: #E0E0E0; font-size: 11px; font-weight: bold; }")
        self.snap_toggle.toggled.connect(self._on_snap_toggle)
        header_row.addWidget(self.snap_toggle)
        
        grid_size_wrapper = QWidget()
        grid_size_layout = QHBoxLayout(grid_size_wrapper)
        grid_size_layout.setContentsMargins(0, 0, 0, 0)
        grid_size_layout.setSpacing(5)
        
        grid_size_label = QLabel("Grid Size")
        grid_size_label.setStyleSheet("color: #B0B0B0; font-size: 12px;")
        grid_size_layout.addWidget(grid_size_label)
        
        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(5, 100)
        self.grid_size_spin.setValue(self.grid_size)
        self.grid_size_spin.setFixedWidth(50)
        self.grid_size_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.grid_size_spin.setStyleSheet(
            "QSpinBox { background-color: rgba(40, 40, 50, 200); border: 1px solid rgba(100, 100, 120, 120); border-radius: 5px; padding: 2px 4px; color: #E0E0E0; }"
        )
        self.grid_size_spin.valueChanged.connect(self._on_grid_size_changed)
        grid_size_layout.addWidget(self.grid_size_spin)
        
        px_label = QLabel("px")
        px_label.setStyleSheet("color: #B0B0B0; font-size: 10px;")
        grid_size_layout.addWidget(px_label)
    
        header_row.addWidget(grid_size_wrapper)
        header_row.addStretch()
        
        layout.addLayout(header_row)
        
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(200, 200)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "QLabel { background-color: rgba(10, 10, 15, 220); border: 1px solid rgba(255, 255, 255, 40); border-radius: 10px; }"
        )
        self.preview_label.mousePressEvent = self._preview_mouse_press
        self.preview_label.mouseMoveEvent = self._preview_mouse_move
        self.preview_label.mouseReleaseEvent = self._preview_mouse_release
        layout.addWidget(self.preview_label)
        return frame

    def _create_metadata_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: rgba(25, 25, 35, 230); border-radius: 8px; border: 1px solid rgba(255,255,255,30); padding: 8px; }"
        )
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setMinimumHeight(200)
        scroll_area.setMaximumHeight(400)
        
        scroll_widget = QWidget()
        form = QFormLayout(scroll_widget)
        form.setSpacing(4)

        self.layer_label_input = QLineEdit()
        self.layer_label_input.setPlaceholderText("Layer name")
        self.layer_label_input.textChanged.connect(self._on_layer_label_changed)
        form.addRow("Label", self.layer_label_input)

        self.layer_enabled_check = QCheckBox("Visible")
        self.layer_enabled_check.toggled.connect(self._on_layer_enabled_toggled)
        form.addRow("", self.layer_enabled_check)

        self.layer_draggable_check = QCheckBox("Draggable")
        self.layer_draggable_check.toggled.connect(self._on_layer_draggable_toggled)
        form.addRow("", self.layer_draggable_check)

        self.layer_angle_spin = self._make_spin(-720.0, 720.0, 1.0, 1)
        self.layer_angle_spin.valueChanged.connect(self._on_layer_angle_changed)
        form.addRow("Angle", self._wrap_with_unit(self.layer_angle_spin, "°"))

        self.layer_angle_offset_spin = self._make_spin(-720.0, 720.0, 1.0, 1)
        self.layer_angle_offset_spin.valueChanged.connect(self._on_layer_angle_offset_changed)
        form.addRow("Offset", self._wrap_with_unit(self.layer_angle_offset_spin, "°"))

        self.layer_gap_spin = self._make_spin(0.0, 800.0, 1.0)
        self.layer_gap_spin.valueChanged.connect(self._on_layer_gap_changed)
        form.addRow("Gap", self._wrap_with_unit(self.layer_gap_spin, "px"))

        self.layer_length_spin = self._make_spin(0.0, 800.0, 1.0)
        self.layer_length_spin.valueChanged.connect(self._on_layer_length_changed)
        form.addRow("Length", self._wrap_with_unit(self.layer_length_spin, "px"))

        self.layer_thickness_spin = self._make_spin(0.1, 240.0, 0.5)
        self.layer_thickness_spin.valueChanged.connect(self._on_layer_thickness_changed)
        form.addRow("Thickness", self._wrap_with_unit(self.layer_thickness_spin, "px"))

        self.layer_tip_spin = self._make_spin(-240.0, 240.0, 0.5)
        self.layer_tip_spin.valueChanged.connect(self._on_layer_tip_changed)
        form.addRow("Tip", self._wrap_with_unit(self.layer_tip_spin, "px"))

        scroll_area.setWidget(scroll_widget)
        
        wrapper_layout = QVBoxLayout(frame)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(scroll_area)
        
        self._set_metadata_enabled(False)
        return frame

    def _create_component_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: rgba(25, 25, 35, 230); border-radius: 8px; border: 1px solid rgba(255,255,255,30); padding: 6px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setSpacing(3)
        layout.addWidget(self._subheading("Line Objects"))

        editor_layout = QHBoxLayout()
        editor_layout.setSpacing(6)
        layout.addLayout(editor_layout, 1)

        list_column = QVBoxLayout()
        list_column.setSpacing(3)
        editor_layout.addLayout(list_column, 1)

        self.components_list = QListWidget()
        self.components_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.components_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.components_list.setStyleSheet(
            "QListWidget { background-color: rgba(34,34,44,240); border-radius: 8px; border: 1px solid rgba(255,255,255,40); }"
        )
        self.components_list.currentRowChanged.connect(self._on_component_selection_changed)
        self.components_list.model().rowsMoved.connect(self._on_component_rows_moved)
        list_column.addWidget(self.components_list, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(3)
        add_segment_btn = QPushButton("＋ Segment")
        add_segment_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_segment_btn.setStyleSheet("QPushButton { background-color: rgba(0,188,212,160); color: white; border: none; border-radius: 6px; padding: 4px 8px; font-weight: bold; min-width: 0; }")
        add_segment_btn.clicked.connect(lambda: self._add_component("segment"))
        button_row.addWidget(add_segment_btn, 1)

        add_circle_btn = QPushButton("＋ Circle")
        add_circle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_circle_btn.setStyleSheet("QPushButton { background-color: rgba(92,107,192,160); color: white; border: none; border-radius: 6px; padding: 4px 8px; font-weight: bold; min-width: 0; }")
        add_circle_btn.clicked.connect(lambda: self._add_component("circle"))
        button_row.addWidget(add_circle_btn, 1)

        duplicate_btn = QPushButton("⧉ Duplicate")
        duplicate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        duplicate_btn.setStyleSheet("QPushButton { background-color: rgba(120,144,156,160); color: white; border: none; border-radius: 6px; padding: 4px 8px; font-weight: bold; min-width: 0; }")
        duplicate_btn.clicked.connect(self._duplicate_component)
        button_row.addWidget(duplicate_btn, 1)

        remove_btn = QPushButton("✖ Remove")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet("QPushButton { background-color: rgba(244,67,54,180); color: white; border: none; border-radius: 6px; padding: 4px 8px; font-weight: bold; min-width: 0; }")
        remove_btn.clicked.connect(self._remove_component)
        button_row.addWidget(remove_btn, 1)

        move_up_btn = QPushButton("↑")
        move_up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        move_up_btn.setFixedWidth(32)
        move_up_btn.setMinimumWidth(32)
        move_up_btn.clicked.connect(lambda: self._move_component(-1))
        button_row.addWidget(move_up_btn, 0)

        move_down_btn = QPushButton("↓")
        move_down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        move_down_btn.setFixedWidth(32)
        move_down_btn.setMinimumWidth(32)
        move_down_btn.clicked.connect(lambda: self._move_component(1))
        button_row.addWidget(move_down_btn, 0)

        list_column.addLayout(button_row)
        self.component_insert_buttons = [add_segment_btn, add_circle_btn]
        self.component_modify_buttons = [duplicate_btn, remove_btn, move_up_btn, move_down_btn]

        editor_column = QVBoxLayout()
        editor_column.setSpacing(3)
        editor_layout.addLayout(editor_column, 1)

        self.component_editor_stack = QStackedWidget()
        placeholder = QLabel("Select an object to edit it.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: rgba(220, 220, 220, 150);")
        self.component_editor_stack.addWidget(placeholder)

        segment_editor = QWidget()
        segment_form = QFormLayout(segment_editor)
        segment_form.setSpacing(4)
        
        self.segment_draggable = QCheckBox("Draggable")
        self.segment_draggable.setStyleSheet("QCheckBox { color: #E0E0E0; font-weight: bold; }")
        self.segment_draggable.toggled.connect(lambda v: self._on_component_draggable_changed("segment", v))
        segment_form.addRow("", self.segment_draggable)
        
        for field in ("offset", "perp_offset", "length", "thickness", "angle_offset", "tip_offset"):
            spin = self._create_component_spinbox("segment", field)
            self.segment_fields[field] = spin
            segment_form.addRow(self._component_label(field), self._wrap_with_unit(spin, COMPONENT_FIELD_LIMITS["segment"][field][2]))
        self.component_editor_stack.addWidget(segment_editor)

        circle_editor = QWidget()
        circle_form = QFormLayout(circle_editor)
        circle_form.setSpacing(4)
        
        self.circle_draggable = QCheckBox("Draggable")
        self.circle_draggable.setStyleSheet("QCheckBox { color: #E0E0E0; font-weight: bold; }")
        self.circle_draggable.toggled.connect(lambda v: self._on_component_draggable_changed("circle", v))
        circle_form.addRow("", self.circle_draggable)
        
        for field in ("offset", "perp_offset", "radius"):
            spin = self._create_component_spinbox("circle", field)
            self.circle_fields[field] = spin
            circle_form.addRow(self._component_label(field), self._wrap_with_unit(spin, COMPONENT_FIELD_LIMITS["circle"][field][2]))
        self.component_editor_stack.addWidget(circle_editor)

        editor_column.addWidget(self.component_editor_stack)
        return frame

    def _make_spin(self, minimum: float, maximum: float, step: float, decimals: int = 1) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setAccelerated(True)
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        spin.setStyleSheet(
            "QDoubleSpinBox { background-color: rgba(40, 40, 50, 200); border: 1px solid rgba(100, 100, 120, 120); border-radius: 5px; padding: 3px 6px; color: #E0E0E0; min-width: 70px; }"
        )
        return spin

    def _component_label(self, field: str) -> QLabel:
        label_map = {
            "perp_offset": "Perp Offset"
        }
        text = label_map.get(field, field.replace("_", " ").title())
        label = QLabel(text)
        label.setStyleSheet("color: #B0B0B0; font-size: 11px; font-weight: bold;")
        return label

    def _wrap_with_unit(self, widget: QDoubleSpinBox, unit: str) -> QWidget:
        wrapper = QHBoxLayoutWidget()
        inner = wrapper.layout()
        inner.addWidget(widget)
        if unit:
            unit_label = QLabel(unit)
            unit_label.setStyleSheet("color: #B0B0B0; padding-left: 4px;")
            inner.addWidget(unit_label)
        inner.addStretch()
        return wrapper

    def _build_standard_list(self) -> None:
        self.standard_list.blockSignals(True)
        self.standard_list.clear()
        for key in LINE_KEYS:
            item = QListWidgetItem(self._standard_item_label(key))
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.standard_list.addItem(item)
        self.standard_list.blockSignals(False)

    def _build_custom_list(self, selected_id: Optional[str] = None) -> None:
        if not isinstance(self.settings.line_layers, list):
            self.settings.line_layers = []
        self.custom_list.blockSignals(True)
        self.custom_list.clear()
        for layer in self.settings.line_layers:
            item = QListWidgetItem(self._custom_layer_summary(layer))
            item.setData(Qt.ItemDataRole.UserRole, layer.get("id"))
            self.custom_list.addItem(item)
        self.custom_list.blockSignals(False)
        if selected_id:
            self._select_custom_by_id(selected_id)
        else:
            self._update_custom_buttons_state()

    def _select_initial_scope(self) -> None:
        if self.standard_list.count():
            self.standard_list.setCurrentRow(0)
        elif self.custom_list.count():
            self.custom_list.setCurrentRow(0)
        else:
            self._component_buttons_enabled(False, False)
            self._set_metadata_enabled(False)

    def _standard_item_label(self, line_key: str) -> str:
        container = self.settings.line_components if isinstance(self.settings.line_components, dict) else {}
        stack = container.get(line_key, []) if isinstance(container, dict) else []
        count = len(stack) if isinstance(stack, list) else 0
        return f"{LINE_LABELS.get(line_key, line_key.title())} ({count} objects)"

    def _custom_layer_summary(self, layer: dict) -> str:
        label = str(layer.get("label") or "Custom Line")
        angle = float(layer.get("angle", 0.0))
        status = "ON" if layer.get("enabled", True) else "OFF"
        components = layer.get("components", []) if isinstance(layer.get("components"), list) else []
        count = len(components) if isinstance(components, list) else 0
        return f"[{status}] {label} • {angle:.0f}° ({count} objects)"

    def _on_standard_selection_changed(self, row: int) -> None:
        if row < 0 or row >= len(LINE_KEYS):
            if self.active_scope_kind == "standard":
                self.active_scope_kind = None
                self.active_scope_id = None
                self._refresh_component_list()
                self._update_layer_metadata_view()
            return
        key = self.standard_list.item(row).data(Qt.ItemDataRole.UserRole)
        self.custom_list.blockSignals(True)
        self.custom_list.clearSelection()
        self.custom_list.blockSignals(False)
        self.active_scope_kind = "standard"
        self.active_scope_id = key
        self._refresh_component_list()
        self._update_layer_metadata_view()
        self._component_buttons_enabled(True, self.components_list.currentRow() >= 0)

    def _on_custom_selection_changed(self, row: int) -> None:
        if row < 0 or row >= self.custom_list.count():
            if self.active_scope_kind == "custom":
                self.active_scope_kind = None
                self.active_scope_id = None
                self._refresh_component_list()
                self._update_layer_metadata_view()
            self._update_custom_buttons_state()
            return
        item = self.custom_list.item(row)
        layer_id = item.data(Qt.ItemDataRole.UserRole)
        self.standard_list.blockSignals(True)
        self.standard_list.clearSelection()
        self.standard_list.blockSignals(False)
        self.active_scope_kind = "custom"
        self.active_scope_id = layer_id
        self._refresh_component_list()
        self._update_layer_metadata_view()
        self._component_buttons_enabled(True, self.components_list.currentRow() >= 0)
        self._update_custom_buttons_state()

    def _update_custom_buttons_state(self) -> None:
        has_selection = self.custom_list.currentRow() >= 0
        self.duplicate_line_btn.setEnabled(has_selection)
        self.remove_line_btn.setEnabled(has_selection)

    def _set_metadata_enabled(self, enabled: bool) -> None:
        self.layer_label_input.setReadOnly(not enabled)
        self.layer_enabled_check.setEnabled(enabled)
        for spin in (
            self.layer_angle_spin,
            self.layer_angle_offset_spin,
            self.layer_gap_spin,
            self.layer_length_spin,
            self.layer_thickness_spin,
            self.layer_tip_spin,
        ):
            spin.setEnabled(enabled)

    def _update_layer_metadata_view(self) -> None:
        if self.active_scope_kind == "custom":
            layer = self._current_custom_layer()
            if layer is None:
                self._set_metadata_enabled(False)
                self.layer_label_input.setText("")
                return
            self._set_metadata_enabled(True)
            self.layer_label_input.blockSignals(True)
            self.layer_label_input.setText(layer.get("label", ""))
            self.layer_label_input.blockSignals(False)
            self.layer_enabled_check.blockSignals(True)
            self.layer_enabled_check.setChecked(layer.get("enabled", True))
            self.layer_enabled_check.blockSignals(False)
            self.layer_draggable_check.blockSignals(True)
            self.layer_draggable_check.setChecked(layer.get("draggable", False))
            self.layer_draggable_check.blockSignals(False)
            for widget, value in (
                (self.layer_angle_spin, layer.get("angle", 0.0)),
                (self.layer_angle_offset_spin, layer.get("angle_offset", 0.0)),
                (self.layer_gap_spin, layer.get("gap", self.settings.gap)),
                (self.layer_length_spin, layer.get("length", self.settings.length)),
                (self.layer_thickness_spin, layer.get("thickness", self.settings.thickness)),
                (self.layer_tip_spin, layer.get("tip_offset", 0.0)),
            ):
                widget.blockSignals(True)
                widget.setValue(float(value))
                widget.blockSignals(False)
        elif self.active_scope_kind == "standard" and self.active_scope_id:
            self._set_metadata_enabled(False)
            label = LINE_LABELS.get(self.active_scope_id, "Standard Line")
            self.layer_label_input.blockSignals(True)
            self.layer_label_input.setText(f"{label} (built-in)")
            self.layer_label_input.blockSignals(False)
            self.layer_enabled_check.blockSignals(True)
            self.layer_enabled_check.setChecked(True)
            self.layer_enabled_check.blockSignals(False)
            self.layer_draggable_check.blockSignals(True)
            self.layer_draggable_check.setChecked(False)
            self.layer_draggable_check.blockSignals(False)
        else:
            self._set_metadata_enabled(False)
            self.layer_label_input.blockSignals(True)
            self.layer_label_input.setText("")
            self.layer_label_input.blockSignals(False)
            self.layer_enabled_check.blockSignals(True)
            self.layer_enabled_check.setChecked(True)
            self.layer_enabled_check.blockSignals(False)
            self.layer_draggable_check.blockSignals(True)
            self.layer_draggable_check.setChecked(False)
            self.layer_draggable_check.blockSignals(False)

    def _current_component_stack(self) -> Optional[list]:
        if self.active_scope_kind == "standard" and self.active_scope_id:
            container = self.settings.line_components
            if not isinstance(container, dict):
                self.settings.line_components = {}
                container = self.settings.line_components
            stack = container.get(self.active_scope_id)
            if not isinstance(stack, list):
                stack = []
                container[self.active_scope_id] = stack
            return stack
        if self.active_scope_kind == "custom":
            layer = self._current_custom_layer()
            if layer is None:
                return None
            components = layer.get("components")
            if not isinstance(components, list):
                components = []
                layer["components"] = components
            return components
        return None

    def _current_custom_layer(self) -> Optional[dict]:
        if self.active_scope_kind != "custom" or not self.active_scope_id:
            return None
        if not isinstance(self.settings.line_layers, list):
            self.settings.line_layers = []
        for layer in self.settings.line_layers:
            if layer.get("id") == self.active_scope_id:
                return layer
        return None

    def _current_component(self) -> Optional[dict]:
        """Get the currently selected component."""
        row = self.components_list.currentRow()
        stack = self._current_component_stack()
        if stack and 0 <= row < len(stack):
            return stack[row]
        return None

    def _refresh_component_list(self) -> None:
        self.components_list.blockSignals(True)
        self.components_list.clear()
        stack = self._current_component_stack()
        if stack:
            for component in stack:
                item = QListWidgetItem(self._component_summary(component))
                item.setData(Qt.ItemDataRole.UserRole, component)
                self.components_list.addItem(item)
        self.components_list.blockSignals(False)
        if self.components_list.count():
            self.components_list.setCurrentRow(0)
        else:
            self.components_list.clearSelection()
            self._set_component_editor_state(None)
        has_layer = stack is not None
        self._component_buttons_enabled(has_layer, self.components_list.currentRow() >= 0)

    def _component_summary(self, component: dict) -> str:
        ctype = component.get("type")
        if ctype == "segment":
            return "Segment • offset={:.1f}px length={:.1f}px".format(
                component.get("offset", 0.0),
                component.get("length", 0.0),
            )
        if ctype == "circle":
            return "Circle • offset={:.1f}px radius={:.1f}px".format(
                component.get("offset", 0.0),
                component.get("radius", 0.0),
            )
        return "Unknown object"

    def _on_component_selection_changed(self, row: int) -> None:
        stack = self._current_component_stack()
        if stack and 0 <= row < len(stack):
            component = stack[row]
            self._set_component_editor_state(component)
            self._component_buttons_enabled(True, True)
        else:
            self._set_component_editor_state(None)
            self._component_buttons_enabled(stack is not None, False)

    def _set_component_editor_state(self, component: Optional[dict]) -> None:
        if component is None:
            self.component_editor_stack.setCurrentIndex(0)
            return
        ctype = component.get("type")
        if ctype == "segment":
            self.component_editor_stack.setCurrentIndex(1)
            self.segment_draggable.blockSignals(True)
            self.segment_draggable.setChecked(component.get("draggable", False))
            self.segment_draggable.blockSignals(False)
            for field, spin in self.segment_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        elif ctype == "circle":
            self.component_editor_stack.setCurrentIndex(2)
            self.circle_draggable.blockSignals(True)
            self.circle_draggable.setChecked(component.get("draggable", False))
            self.circle_draggable.blockSignals(False)
            for field, spin in self.circle_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        else:
            self.component_editor_stack.setCurrentIndex(0)

    def _sync_component_form(self, component: Optional[dict]) -> None:
        """Update form fields to match component data (used during dragging)."""
        if component is None:
            return
        ctype = component.get("type")
        if ctype == "segment":
            for field, spin in self.segment_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        elif ctype == "circle":
            for field, spin in self.circle_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)

    def _component_buttons_enabled(self, has_layer: bool, has_component: bool) -> None:
        for btn in self.component_insert_buttons:
            btn.setEnabled(has_layer)
        for btn in self.component_modify_buttons:
            btn.setEnabled(has_layer and has_component)

    def _create_component_spinbox(self, comp_type: str, field: str) -> QDoubleSpinBox:
        minimum, maximum, _ = COMPONENT_FIELD_LIMITS[comp_type][field]
        span = maximum - minimum
        buffer = max(200.0, abs(span) * 2 if span else 200.0)
        spin = QDoubleSpinBox()
        spin.setDecimals(1)
        spin.setRange(minimum - buffer, maximum + buffer)
        spin.setSingleStep(1.0)
        spin.setAccelerated(True)
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        spin.setStyleSheet(
            "QDoubleSpinBox { background-color: rgba(40, 40, 50, 200); border: 1px solid rgba(100, 100, 120, 120); border-radius: 5px; padding: 3px 6px; color: #E0E0E0; min-width: 70px; }"
        )
        spin.valueChanged.connect(
            lambda val, name=field, cmin=minimum, cmax=maximum: self._on_component_value_if_valid(name, val, cmin, cmax)
        )
        spin.editingFinished.connect(
            lambda sb=spin, name=field, cmin=minimum, cmax=maximum: self._on_component_value_clamped(sb, name, cmin, cmax)
        )
        return spin

    def _on_component_value_if_valid(self, field: str, value: float, minimum: float, maximum: float) -> None:
        if minimum <= value <= maximum:
            self._update_current_component(field, value)

    def _on_component_value_clamped(self, spin: QDoubleSpinBox, field: str, minimum: float, maximum: float) -> None:
        value = spin.value()
        clamped = max(minimum, min(maximum, value))
        if clamped != value:
            spin.blockSignals(True)
            spin.setValue(clamped)
            spin.blockSignals(False)
        self._update_current_component(field, clamped)

    def _update_current_component(self, field: str, value: float) -> None:
        stack = self._current_component_stack()
        row = self.components_list.currentRow()
        if stack and 0 <= row < len(stack):
            stack[row][field] = value
            self.components_list.item(row).setText(self._component_summary(stack[row]))
            self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _add_component(self, comp_type: str) -> None:
        stack = self._current_component_stack()
        if comp_type not in COMPONENT_TYPES or stack is None:
            return
        component = {"type": comp_type, **self._default_component_values(comp_type)}
        stack.append(component)
        item = QListWidgetItem(self._component_summary(component))
        item.setData(Qt.ItemDataRole.UserRole, component)
        self.components_list.addItem(item)
        self.components_list.setCurrentRow(self.components_list.count() - 1)
        self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _remove_component(self) -> None:
        stack = self._current_component_stack()
        row = self.components_list.currentRow()
        if stack is None or row < 0 or row >= len(stack):
            return
        stack.pop(row)
        self.components_list.takeItem(row)
        next_row = min(row, self.components_list.count() - 1)
        if next_row >= 0:
            self.components_list.setCurrentRow(next_row)
        else:
            self.components_list.clearSelection()
            self._set_component_editor_state(None)
        self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _duplicate_component(self) -> None:
        stack = self._current_component_stack()
        row = self.components_list.currentRow()
        if stack is None or row < 0 or row >= len(stack):
            return
        copy_component = dict(stack[row])
        stack.insert(row + 1, copy_component)
        item = QListWidgetItem(self._component_summary(copy_component))
        item.setData(Qt.ItemDataRole.UserRole, copy_component)
        self.components_list.insertItem(row + 1, item)
        self.components_list.setCurrentRow(row + 1)
        self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _move_component(self, delta: int) -> None:
        if delta == 0:
            return
        stack = self._current_component_stack()
        row = self.components_list.currentRow()
        if stack is None or row < 0:
            return
        target = row + delta
        if target < 0 or target >= len(stack):
            return
        stack[row], stack[target] = stack[target], stack[row]
        item = self.components_list.takeItem(row)
        self.components_list.insertItem(target, item)
        self.components_list.setCurrentRow(target)
        self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _on_component_rows_moved(self, *_) -> None:
        stack = self._current_component_stack()
        if stack is None:
            return
        new_order = []
        for index in range(self.components_list.count()):
            component = self.components_list.item(index).data(Qt.ItemDataRole.UserRole)
            if component in stack:
                new_order.append(component)
        if len(new_order) == len(stack):
            stack[:] = new_order
            self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _default_component_values(self, comp_type: str) -> dict:
        if comp_type == "segment":
            return {
                "offset": 0.0,
                "length": 40.0,
                "thickness": 6.0,
                "angle_offset": 0.0,
                "tip_offset": 0.0,
            }
        if comp_type == "circle":
            return {
                "offset": 20.0,
                "radius": 6.0,
            }
        return {}

    def _current_scope_standard_key(self) -> Optional[str]:
        return self.active_scope_id if self.active_scope_kind == "standard" else None

    def _current_scope_custom_id(self) -> Optional[str]:
        return self.active_scope_id if self.active_scope_kind == "custom" else None

    def _on_grid_toggle(self, enabled: bool) -> None:
        self.show_grid = enabled
        self._update_preview()

    def _on_grid_size_changed(self, value: int) -> None:
        self.grid_size = value
        self._update_preview()

    def _on_snap_toggle(self, enabled: bool) -> None:
        self.grid_snap_enabled = enabled

    def _on_component_draggable_changed(self, comp_type: str, enabled: bool) -> None:
        component = self._current_component()
        if component:
            component["draggable"] = enabled
            self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _preview_mouse_press(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        
        pos = QPointF(event.pos())
        
        # Check if clicking on a selection handle
        if self.selected_component and self.selection_handles:
            for handle_type, handle_rect in self.selection_handles:
                if handle_rect.contains(pos):
                    if handle_type == "delete":
                        self._delete_current_component()
                        self.selected_component = None
                        self._update_preview()
                        return
                    elif handle_type == "rotate":
                        self.rotating = True
                        self.drag_start_pos = event.pos()
                        import math
                        # Calculate initial angle from component center to mouse
                        self.rotation_start_angle = self.selected_component.get("angle_offset", 0.0)
                        event.accept()
                        return
                    elif handle_type.startswith("resize"):
                        self.dragging_component = self.selected_component
                        self.drag_start_pos = event.pos()
                        self.resize_mode = handle_type
                        event.accept()
                        return
        
        # Check if current component is draggable - select it
        component = self._current_component()
        if component and component.get("draggable", False):
            self.selected_component = component
            self.dragging_component = component
            self.drag_start_pos = event.pos()
            self._update_preview()
            event.accept()
        else:
            # Deselect if clicking empty area
            if self.selected_component:
                self.selected_component = None
                self._update_preview()

    def _preview_mouse_move(self, event) -> None:
        import math
        
        # Handle rotation
        if self.rotating and self.drag_start_pos and self.selected_component:
            delta = event.pos() - self.drag_start_pos
            # Simple rotation based on horizontal movement
            angle_change = delta.x() * 0.5  # Sensitivity factor
            new_angle = self.rotation_start_angle + angle_change
            
            # Snap to 15-degree increments if shift is held
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                new_angle = round(new_angle / 15) * 15
            
            self.selected_component["angle_offset"] = new_angle
            self._sync_component_form(self.selected_component)
            self._update_preview()
            event.accept()
            return
        
        # Handle resizing
        if hasattr(self, 'resize_mode') and self.resize_mode and self.dragging_component and self.drag_start_pos:
            delta = event.pos() - self.drag_start_pos
            self.drag_start_pos = event.pos()
            
            if self.resize_mode == "resize_length":
                current_length = self.dragging_component.get("length", 40.0)
                new_length = max(1.0, current_length + delta.x())
                self.dragging_component["length"] = new_length
                self._sync_component_form(self.dragging_component)
                self._update_preview()
                event.accept()
                return
            elif self.resize_mode == "resize_thickness":
                current_thickness = self.dragging_component.get("thickness", 4.0)
                new_thickness = max(1.0, current_thickness + delta.y())
                self.dragging_component["thickness"] = new_thickness
                self._sync_component_form(self.dragging_component)
                self._update_preview()
                event.accept()
                return
        
        # Handle normal dragging
        if self.dragging_component is None or self.drag_start_pos is None:
            return
        
        delta = event.pos() - self.drag_start_pos
        self.drag_start_pos = event.pos()
        
        # Get the base angle for this component's line
        layer = self._current_custom_layer()
        if layer:
            base_angle = layer.get("angle", 0.0)
            angle_offset = layer.get("angle_offset", 0.0)
        else:
            # For standard lines, get the angle from the active scope
            if self.active_scope_id in ["show_left", "show_right"]:
                base_angle = 180 if self.active_scope_id == "show_left" else 0
            elif self.active_scope_id in ["show_top", "show_bottom"]:
                base_angle = 90 if self.active_scope_id == "show_top" else 270
            else:
                base_angle = 0
            angle_offset = 0
        
        # Get component's own angle offset
        component_angle = self.dragging_component.get("angle_offset", 0.0)
        total_angle = base_angle + angle_offset + component_angle
        
        # Convert angle to radians
        import math
        angle_rad = math.radians(total_angle)
        
        # Project mouse movement onto the line's direction (parallel to line)
        offset_delta = delta.x() * math.cos(angle_rad) + delta.y() * math.sin(angle_rad)
        
        # Project mouse movement perpendicular to the line (for angle_offset)
        # Perpendicular is 90 degrees from the line angle
        perp_angle_rad = angle_rad + math.pi / 2
        angle_offset_delta = delta.x() * math.cos(perp_angle_rad) + delta.y() * math.sin(perp_angle_rad)
        
        # Update offset (parallel movement)
        current_offset = self.dragging_component.get("offset", 0.0)
        new_offset = current_offset + offset_delta
        
        # Update perp_offset (perpendicular movement) instead of angle_offset
        current_perp_offset = self.dragging_component.get("perp_offset", 0.0)
        new_perp_offset = current_perp_offset + angle_offset_delta
        
        # Apply magnetic snapping to grid lines when snap is enabled
        if self.grid_snap_enabled and self.grid_size > 1:
            snap_threshold_parallel = self.grid_size / 5
            snap_threshold_perp = self.grid_size / 8  # Even smaller threshold for more responsive perpendicular movement
            
            # Snap parallel offset
            nearest_grid_offset = round(new_offset / self.grid_size) * self.grid_size
            distance_offset = abs(new_offset - nearest_grid_offset)
            if distance_offset < snap_threshold_parallel:
                new_offset = nearest_grid_offset
            
            # Snap perpendicular offset
            nearest_grid_perp = round(new_perp_offset / self.grid_size) * self.grid_size
            distance_perp = abs(new_perp_offset - nearest_grid_perp)
            if distance_perp < snap_threshold_perp:
                new_perp_offset = nearest_grid_perp
        
        # Update both offset and perp_offset
        self.dragging_component["offset"] = new_offset
        self.dragging_component["perp_offset"] = new_perp_offset
        
        # Sync UI and preview
        self._sync_component_form(self.dragging_component)
        self._update_preview()
        event.accept()
        event.accept()

    def _preview_mouse_release(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging_component is not None:
                self.dragging_component = None
                self.drag_start_pos = None
                self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())
                event.accept()
            if self.rotating:
                self.rotating = False
                self.drag_start_pos = None
                self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())
                event.accept()
            if hasattr(self, 'resize_mode'):
                self.resize_mode = None
                self.drag_start_pos = None

    def _on_add_custom_line(self) -> None:
        layer = self._create_default_layer()
        self.settings.line_layers.append(layer)
        self._build_custom_list(selected_id=layer["id"])
        self._persist(custom_id=layer["id"], refresh_custom_list=False)

    def _on_duplicate_custom_line(self) -> None:
        layer = self._current_custom_layer()
        row = self.custom_list.currentRow()
        if layer is None or row < 0:
            return
        clone = self._create_default_layer()
        clone.update(
            {
                "label": f"{layer.get('label', 'Line')} Copy",
                "angle": layer.get("angle", 0.0),
                "angle_offset": layer.get("angle_offset", 0.0),
                "gap": layer.get("gap", self.settings.gap),
                "length": layer.get("length", self.settings.length),
                "thickness": layer.get("thickness", self.settings.thickness),
                "tip_offset": layer.get("tip_offset", 0.0),
                "enabled": layer.get("enabled", True),
                "components": [dict(component) for component in layer.get("components", []) if isinstance(component, dict)],
            }
        )
        self.settings.line_layers.insert(row + 1, clone)
        self._build_custom_list(selected_id=clone["id"])
        self._persist(custom_id=clone["id"], refresh_custom_list=False)

    def _on_remove_custom_line(self) -> None:
        row = self.custom_list.currentRow()
        if row < 0 or row >= len(self.settings.line_layers):
            return
        removed_id = self.custom_list.item(row).data(Qt.ItemDataRole.UserRole)
        self.settings.line_layers = [layer for layer in self.settings.line_layers if layer.get("id") != removed_id]
        self._build_custom_list()
        if self.settings.line_layers:
            next_row = min(row, len(self.settings.line_layers) - 1)
            self.custom_list.setCurrentRow(next_row)
        else:
            self.custom_list.clearSelection()
            self.active_scope_kind = None
            self.active_scope_id = None
            self._refresh_component_list()
            self._update_layer_metadata_view()
        self._persist(refresh_custom_list=False)

    def _create_default_layer(self) -> dict:
        return {
            "id": uuid4().hex,
            "label": f"Line {len(self.settings.line_layers) + 1}",
            "enabled": True,
            "angle": 0.0,
            "angle_offset": 0.0,
            "gap": float(self.settings.gap),
            "length": float(self.settings.length),
            "thickness": float(self.settings.thickness),
            "tip_offset": 0.0,
            "components": [],
        }

    def _on_custom_rows_moved(self, *_) -> None:
        self._sync_custom_order_from_view()

    def _sync_custom_order_from_view(self) -> None:
        if not isinstance(self.settings.line_layers, list):
            self.settings.line_layers = []
        ordered: list[dict] = []
        id_to_layer = {layer.get("id"): layer for layer in self.settings.line_layers}
        for index in range(self.custom_list.count()):
            layer_id = self.custom_list.item(index).data(Qt.ItemDataRole.UserRole)
            layer = id_to_layer.get(layer_id)
            if layer:
                ordered.append(layer)
        if len(ordered) == len(self.settings.line_layers):
            self.settings.line_layers = ordered
            self._persist(custom_id=self.active_scope_id if self.active_scope_kind == "custom" else None)

    def _on_layer_label_changed(self, text: str) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        layer["label"] = text.strip() or "Custom Line"
        self._refresh_custom_item_text(layer["id"])
        self._persist(custom_id=layer["id"])

    def _on_layer_enabled_toggled(self, enabled: bool) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        layer["enabled"] = enabled
        self._refresh_custom_item_text(layer["id"])
        self._persist(custom_id=layer["id"])

    def _on_layer_draggable_toggled(self, enabled: bool) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        layer["draggable"] = enabled
        self._persist(custom_id=layer["id"])

    def _on_layer_angle_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        # Don't reset offset when changing angle - just update the angle
        layer["angle"] = value
        self._refresh_custom_item_text(layer["id"])
        self._persist(custom_id=layer["id"])

    def _on_layer_angle_offset_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        layer["angle_offset"] = value
        self._persist(custom_id=layer["id"])

    def _on_layer_gap_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        layer["gap"] = max(0.0, value)
        self._persist(custom_id=layer["id"])

    def _on_layer_length_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        layer["length"] = max(0.0, value)
        self._persist(custom_id=layer["id"])

    def _on_layer_thickness_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        layer["thickness"] = max(0.1, value)
        self._persist(custom_id=layer["id"])

    def _on_layer_tip_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        layer["tip_offset"] = value
        self._persist(custom_id=layer["id"])

    def _refresh_standard_item_text(self, line_key: Optional[str]) -> None:
        if not line_key:
            return
        for index in range(self.standard_list.count()):
            item = self.standard_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == line_key:
                item.setText(self._standard_item_label(line_key))
                break

    def _refresh_custom_item_text(self, layer_id: str) -> None:
        layer = None
        for candidate in self.settings.line_layers:
            if candidate.get("id") == layer_id:
                layer = candidate
                break
        if layer is None:
            return
        for index in range(self.custom_list.count()):
            item = self.custom_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                item.setText(self._custom_layer_summary(layer))
                break

    def _select_custom_by_id(self, layer_id: Optional[str]) -> None:
        if not layer_id:
            self.custom_list.clearSelection()
            self._update_custom_buttons_state()
            return
        for index in range(self.custom_list.count()):
            if self.custom_list.item(index).data(Qt.ItemDataRole.UserRole) == layer_id:
                self.custom_list.setCurrentRow(index)
                return
        self.custom_list.clearSelection()
        self._update_custom_buttons_state()

    def _persist(
        self,
        standard_key: Optional[str] = None,
        custom_id: Optional[str] = None,
        refresh_custom_list: bool = False,
    ) -> None:
        if refresh_custom_list:
            self._build_custom_list(custom_id)
        else:
            self._refresh_standard_item_text(standard_key)
            if custom_id:
                self._refresh_custom_item_text(custom_id)
        self.parent_dialog._update_line_custom_controls()
        self.parent_dialog._persist_and_render()
        self._update_preview()

    def _update_preview(self) -> None:
        size = self.preview_label.size()
        w = max(size.width(), 240)
        h = max(size.height(), 240)
        
        pixmap = QPixmap(w, h)
        pixmap.fill(QColor(10, 10, 15, 220))
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw grid if enabled
        if self.show_grid:
            painter.setPen(QPen(QColor(255, 255, 255, 60), 1))
            center_x = w // 2
            center_y = h // 2
            
            # Vertical lines
            x = center_x
            while x < w:
                painter.drawLine(x, 0, x, h)
                x += self.grid_size
            x = center_x - self.grid_size
            while x >= 0:
                painter.drawLine(x, 0, x, h)
                x -= self.grid_size
            
            # Horizontal lines
            y = center_y
            while y < h:
                painter.drawLine(0, y, w, y)
                y += self.grid_size
            y = center_y - self.grid_size
            while y >= 0:
                painter.drawLine(0, y, w, y)
                y -= self.grid_size
            
            # Center crosshair
            painter.setPen(QPen(QColor(255, 255, 255, 120), 1, Qt.PenStyle.DashLine))
            painter.drawLine(center_x, 0, center_x, h)
            painter.drawLine(0, center_y, w, center_y)
        
        painter.end()
        
        # Render crosshair on top using the existing function
        temp_settings = deepcopy(self.settings)
        temp_settings.offset_x = 0
        temp_settings.offset_y = 0
        temp_settings.visible = True
        
        crosshair_pixmap = generate_crosshair_pixmap(w, h, temp_settings)
        
        # Composite the crosshair onto the grid
        painter = QPainter(pixmap)
        painter.drawPixmap(0, 0, crosshair_pixmap)
        
        # Draw selection handles if a component is selected
        if self.selected_component:
            self._draw_selection_handles(painter, w, h)
        
        
        painter.end()
        
        self.preview_label.setPixmap(
            pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def _draw_selection_handles(self, painter, w: int, h: int) -> None:
        """Draw selection handles around the selected component"""
        import math
        
        # Get component position
        layer = self._current_custom_layer()
        if layer:
            base_angle = layer.get("angle", 0.0)
        else:
            if self.active_scope_id in ["show_left", "show_right"]:
                base_angle = 180 if self.active_scope_id == "show_left" else 0
            elif self.active_scope_id in ["show_top", "show_bottom"]:
                base_angle = 90 if self.active_scope_id == "show_top" else 270
            else:
                base_angle = 0
        
        offset = self.selected_component.get("offset", 0.0)
        perp_offset = self.selected_component.get("perp_offset", 0.0)
        component_angle = self.selected_component.get("angle_offset", 0.0)
        total_angle = base_angle + component_angle
        
        # Calculate component center position
        center_x = w // 2
        center_y = h // 2
        angle_rad = math.radians(total_angle)
        
        comp_x = center_x + offset * math.cos(angle_rad) - perp_offset * math.sin(angle_rad)
        comp_y = center_y + offset * math.sin(angle_rad) + perp_offset * math.cos(angle_rad)
        
        # Get component size
        if self.selected_component.get("type") == "segment":
            length = self.selected_component.get("length", 40.0)
            thickness = self.selected_component.get("thickness", 4.0)
            half_len = length / 2
            half_thick = thickness / 2 + 15
        else:  # circle
            radius = self.selected_component.get("radius", 10.0)
            half_len = radius + 15
            half_thick = radius + 15
        
        # Store handle positions for hit testing
        self.selection_handles = []
        handle_size = 24
        button_size = 28
        
        # Calculate positions relative to component angle
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        
        # Rotate handle for rotation
        rotate_x = comp_x - half_thick * sin_a
        rotate_y = comp_y + half_thick * cos_a
        
        # Delete handle (top-right corner)
        delete_x = comp_x + half_len * cos_a - half_thick * sin_a
        delete_y = comp_y + half_len * sin_a + half_thick * cos_a
        
        # Resize handle (right side for length)
        resize_x = comp_x + (half_len + 20) * cos_a
        resize_y = comp_y + (half_len + 20) * sin_a
        
        # Thickness handle (bottom)
        thick_x = comp_x + (half_thick + 20) * sin_a
        thick_y = comp_y - (half_thick + 20) * cos_a
        
        # Draw handles with icons
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Rotate handle
        painter.setBrush(QColor(100, 150, 255))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        rotate_rect = QRectF(rotate_x - button_size/2, rotate_y - button_size/2, button_size, button_size)
        painter.drawEllipse(rotate_rect)
        self.selection_handles.append(("rotate", rotate_rect))
        
        # Draw rotate icon
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        icon_radius = 6
        painter.drawArc(QRectF(rotate_x - icon_radius, rotate_y - icon_radius, icon_radius * 2, icon_radius * 2), 
                       45 * 16, 270 * 16)
        
        # Delete handle
        painter.setBrush(QColor(255, 80, 80))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        delete_rect = QRectF(delete_x - button_size/2, delete_y - button_size/2, button_size, button_size)
        painter.drawEllipse(delete_rect)
        self.selection_handles.append(("delete", delete_rect))
        
        # Draw X icon
        painter.drawLine(QPointF(delete_x - 6, delete_y - 6), QPointF(delete_x + 6, delete_y + 6))
        painter.drawLine(QPointF(delete_x + 6, delete_y - 6), QPointF(delete_x - 6, delete_y + 6))
        
        if self.selected_component.get("type") == "segment":
            # Resize length handle
            painter.setBrush(QColor(100, 255, 150))
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            resize_rect = QRectF(resize_x - handle_size/2, resize_y - handle_size/2, handle_size, handle_size)
            painter.drawRect(resize_rect)
            self.selection_handles.append(("resize_length", resize_rect))
            
            # Draw arrows icon
            painter.drawLine(QPointF(resize_x - 6, resize_y), QPointF(resize_x + 6, resize_y))
            painter.drawLine(QPointF(resize_x + 3, resize_y - 3), QPointF(resize_x + 6, resize_y))
            painter.drawLine(QPointF(resize_x + 3, resize_y + 3), QPointF(resize_x + 6, resize_y))
            
            # Thickness handle
            painter.setBrush(QColor(255, 200, 100))
            thick_rect = QRectF(thick_x - handle_size/2, thick_y - handle_size/2, handle_size, handle_size)
            painter.drawRect(thick_rect)
            self.selection_handles.append(("resize_thickness", thick_rect))


