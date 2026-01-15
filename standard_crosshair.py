"""Standard crosshair dialog that renders a configurable crosshair overlay."""
import json
import random
import ctypes
import weakref
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Callable, Dict, Set
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
    QDialog,
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
    QComboBox,
    QInputDialog,
    QSizePolicy,
    QSizeGrip,
)
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPainterPath, QPen, QKeySequence, QShortcut, QRegion
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer

from utils import UI_THEME, tr_lit, apply_language_to_object_tree

CONFIG_PATH = Path(__file__).resolve().with_name("standard_crosshair_settings.json")
PROFILES_IMPORT_PATH = Path(__file__).resolve().with_name("crosshair_profiles.json")
HOTKEY_CONFIG_PATH = Path(__file__).resolve().with_name("hotkey_config.json")
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
    "angle_offset": (-720, 720, "°"),
    "tip_offset": (-80, 80, "px"),
}
LINE_LABELS = {
    "left": "Left",
    "right": "Right",
    "top": "Top",
    "bottom": "Bottom",
}
COMPONENT_FIELD_LIMITS = {
    "segment": {
        "offset": (-400.0, 600.0, "px"),
        "perp_offset": (-400.0, 400.0, "px"),
        "length": (0.0, 600.0, "px"),
        "thickness": (1.0, 120.0, "px"),
        "angle_offset": (-720.0, 720.0, "°"),
        "tip_offset": (-120.0, 120.0, "px"),
    },
    "circle": {
        "offset": (-400.0, 600.0, "px"),
        "perp_offset": (-400.0, 400.0, "px"),
        "radius": (1.0, 200.0, "px"),
    },
    "polygon": {
        "offset": (-400.0, 600.0, "px"),
        "perp_offset": (-400.0, 400.0, "px"),
        "radius": (1.0, 240.0, "px"),
        "sides": (3.0, 12.0, ""),
        "angle_offset": (-720.0, 720.0, "°"),
    },
}


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("1", "true", "yes", "y", "on"):
            return True
        if raw in ("0", "false", "no", "n", "off", ""):
            return False
    return default


def _unique_preset_name(existing: dict, name: str) -> str:
    base = (name or "Imported").strip()[:32] or "Imported"
    if base not in existing:
        return base
    i = 2
    while True:
        candidate = f"{base} ({i})"
        if candidate not in existing:
            return candidate
        i += 1


def _merge_external_presets(settings: "StandardCrosshairSettings") -> None:
    """Merge presets from `crosshair_profiles.json` into settings.presets.

    Supported formats:
    - {"presets": {"Name": { ...preset dict... }, ...}}
    - {"Name": { ...preset dict... }, ...}
    - [{"name": "Name", ...preset dict...}, ...]

    Name conflicts are resolved by renaming ("Name (2)", "Name (3)", ...).
    """
    try:
        if not PROFILES_IMPORT_PATH.exists():
            return
        raw = json.loads(PROFILES_IMPORT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return

    if not isinstance(getattr(settings, "presets", None), dict):
        settings.presets = {}
    target: dict[str, dict] = settings.presets

    def maybe_add(name: str, preset: object) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        if not isinstance(preset, dict):
            return
        final_name = _unique_preset_name(target, name.strip())
        target[final_name] = dict(preset)

    if isinstance(raw, dict):
        container = raw.get("presets") if isinstance(raw.get("presets"), dict) else raw
        if isinstance(container, dict):
            for n, p in container.items():
                maybe_add(str(n), p)
        elif isinstance(raw.get("presets"), list):
            for entry in raw.get("presets", []):
                if isinstance(entry, dict) and "name" in entry:
                    name = str(entry.get("name", "")).strip()
                    preset = dict(entry)
                    preset.pop("name", None)
                    maybe_add(name, preset)
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and "name" in entry:
                name = str(entry.get("name", "")).strip()
                preset = dict(entry)
                preset.pop("name", None)
                maybe_add(name, preset)


# Extend supported types. Internally we keep "segment" for backward compatibility
# but present it as "Line" in the UI.
COMPONENT_TYPES = {"segment", "circle", "square", "triangle", "polygon", "curve"}
COMPONENT_FIELD_LIMITS.update(
    {
        "square": {
            "offset": (-400.0, 600.0, "px"),
            "perp_offset": (-400.0, 400.0, "px"),
            "size": (1.0, 300.0, "px"),
            "angle_offset": (-720.0, 720.0, "°"),
        },
        "triangle": {
            "offset": (-400.0, 600.0, "px"),
            "perp_offset": (-400.0, 400.0, "px"),
            "radius": (1.0, 240.0, "px"),
            "angle_offset": (-720.0, 720.0, "°"),
        },
        "curve": {
            "offset": (-400.0, 600.0, "px"),
            "perp_offset": (-400.0, 400.0, "px"),
            "thickness": (0.5, 120.0, "px"),
            "angle_offset": (-720.0, 720.0, "°"),
            "start_dx": (-600.0, 600.0, "px"),
            "start_dy": (-600.0, 600.0, "px"),
            "ctrl_dx": (-600.0, 600.0, "px"),
            "ctrl_dy": (-600.0, 600.0, "px"),
            "end_dx": (-600.0, 600.0, "px"),
            "end_dy": (-600.0, 600.0, "px"),
        },
    }
)


def _default_component_field_value(comp_type: str, field_name: str) -> float:
    if comp_type == "segment":
        defaults = {
            "offset": 0.0,
            "perp_offset": 0.0,
            "length": 40.0,
            "thickness": 6.0,
            "angle_offset": 0.0,
            "tip_offset": 0.0,
        }
        return float(defaults.get(field_name, 0.0))
    if comp_type == "circle":
        defaults = {
            "offset": 20.0,
            "perp_offset": 0.0,
            "radius": 6.0,
        }
        return float(defaults.get(field_name, 0.0))
    if comp_type == "polygon":
        defaults = {
            "offset": 20.0,
            "perp_offset": 0.0,
            "radius": 10.0,
            "sides": 3.0,
            "angle_offset": 0.0,
        }
        return float(defaults.get(field_name, 0.0))
    if comp_type == "square":
        defaults = {
            "offset": 20.0,
            "perp_offset": 0.0,
            "size": 18.0,
            "angle_offset": 0.0,
        }
        return float(defaults.get(field_name, 0.0))
    if comp_type == "triangle":
        defaults = {
            "offset": 20.0,
            "perp_offset": 0.0,
            "radius": 12.0,
            "angle_offset": 0.0,
        }
        return float(defaults.get(field_name, 0.0))
    if comp_type == "curve":
        defaults = {
            "offset": 0.0,
            "perp_offset": 0.0,
            "thickness": 3.0,
            "angle_offset": 0.0,
            "start_dx": -20.0,
            "start_dy": 0.0,
            "ctrl_dx": 0.0,
            "ctrl_dy": 0.0,
            "end_dx": 20.0,
            "end_dy": 0.0,
        }
        return float(defaults.get(field_name, 0.0))
    return 0.0


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
    # Overall scale in percent. 100 = normal size, 200 = 2x, 0 = hidden.
    global_scale: int = 100
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

    # Hold-fade: fade crosshair out while a key/button is held.
    hold_fade_enabled: bool = False
    hold_fade_key: str = "mouse_left"  # mouse_left/mouse_right/mouse_middle/shift/ctrl/alt/space/a/...
    hold_fade_keys: list[str] = field(default_factory=list)  # optional multi-bindings (preferred)

    # Randomize behavior
    randomize_mode: str = "preset"  # preset/absolute
    randomize_hotkey_enabled: bool = False

    # Presets
    active_preset: str = "Default"
    presets: dict[str, dict] = field(default_factory=dict)


def _normalize_hotkey_token(token: str) -> str:
    token = str(token or "").strip().lower()
    if not token:
        return ""
    aliases = {
        "`": "grave",
        "~": "grave",
        "mouse4": "mouse_x1",
        "mouse5": "mouse_x2",
        "mouse_4": "mouse_x1",
        "mouse_5": "mouse_x2",
        "x1": "mouse_x1",
        "x2": "mouse_x2",
        "mb4": "mouse_x1",
        "mb5": "mouse_x2",
    }
    return aliases.get(token, token)


def _normalize_hotkey_chord(chord: str) -> str:
    parts = [p.strip() for p in str(chord or "").split("+") if p.strip()]
    parts = [_normalize_hotkey_token(p) for p in parts]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    order = {"ctrl": 0, "alt": 1, "shift": 2, "windows": 3}
    return "+".join(sorted(set(parts), key=lambda t: (order.get(t, 50), t)))


def _load_hotkey_config_from_disk() -> dict:
    try:
        with open(HOTKEY_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_hotkey_config_to_disk(config: dict) -> None:
    try:
        with open(HOTKEY_CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=4, ensure_ascii=False)
    except Exception:
        pass


def _get_single_hotkey_binding(action: str) -> str:
    cfg = _load_hotkey_config_from_disk()
    v = cfg.get(action)
    if isinstance(v, list) and v:
        return str(v[0] or "").strip().lower()
    if isinstance(v, str):
        return str(v or "").strip().lower()
    return ""


def _get_single_hotkey_binding_normalized(action: str) -> str:
    return _normalize_hotkey_chord(_get_single_hotkey_binding(action))


def _set_single_hotkey_binding(action: str, chord: str) -> None:
    action = str(action or "").strip()
    if not action:
        return
    chord = _normalize_hotkey_chord(chord)
    cfg = _load_hotkey_config_from_disk()
    cfg[action] = [chord] if chord else []
    _save_hotkey_config_to_disk(cfg)


def _settings_to_preset_dict(settings: StandardCrosshairSettings) -> dict:
    data = asdict(settings)
    data.pop("presets", None)
    data.pop("active_preset", None)
    # Visibility is a global toggle, not a per-preset property.
    data.pop("visible", None)
    # These are global toggles/behaviors and should not be saved inside presets.
    # Keeping them out prevents Randomize/Presets from unexpectedly changing
    # user hotkeys/hold-fade behavior.
    data.pop("hold_fade_enabled", None)
    data.pop("hold_fade_key", None)
    data.pop("hold_fade_keys", None)
    data.pop("randomize_hotkey_enabled", None)
    return data


def _apply_preset_dict_to_settings(settings: StandardCrosshairSettings, preset: dict) -> None:
    if not isinstance(preset, dict):
        return
    for key, value in preset.items():
        if key in (
            "presets",
            "active_preset",
            "visible",
            # Global-only keys: ignore them even if present in older presets.
            "hold_fade_enabled",
            "hold_fade_key",
            "hold_fade_keys",
            "randomize_hotkey_enabled",
        ):
            continue
        if hasattr(settings, key):
            setattr(settings, key, value)


def _bind_settings_to_label(label: QLabel, settings: StandardCrosshairSettings) -> None:
    setattr(label, "_standard_crosshair_settings", settings)


def _ensure_fan_timer(label: QLabel) -> QTimer:
    timer = getattr(label, "_standard_crosshair_fan_timer", None)
    if isinstance(timer, QTimer):
        return timer

    timer = QTimer(label)
    timer.setInterval(16)

    def on_tick() -> None:
        settings = getattr(label, "_standard_crosshair_settings", None)
        if not isinstance(settings, StandardCrosshairSettings):
            return
        if not getattr(settings, "fan_enabled", False):
            return
        interval_seconds = timer.interval() / 1000.0
        angle = float(getattr(label, "_standard_crosshair_fan_angle", 0.0))
        angle = (angle + float(getattr(settings, "fan_speed", 0)) * interval_seconds) % 360
        setattr(label, "_standard_crosshair_fan_angle", angle)
        render_crosshair_on_label(label, settings, extra_rotation=angle)

    timer.timeout.connect(on_tick)
    setattr(label, "_standard_crosshair_fan_timer", timer)
    setattr(label, "_standard_crosshair_fan_angle", 0.0)
    return timer


def _sync_fan_timer_state(label: QLabel, settings: StandardCrosshairSettings) -> None:
    timer = _ensure_fan_timer(label)
    if getattr(settings, "fan_enabled", False):
        if not timer.isActive():
            timer.start()
    else:
        if timer.isActive():
            timer.stop()
        setattr(label, "_standard_crosshair_fan_angle", 0.0)


def _vk_from_hold_key(key: str) -> Optional[int]:
    key = str(key or "").strip().lower()
    if not key:
        return None

    mapping = {
        "mouse_left": 0x01,
        "mouse_right": 0x02,
        "mouse_middle": 0x04,
        "mouse_x1": 0x05,
        "mouse_x2": 0x06,
        "shift": 0x10,
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "space": 0x20,
        "tab": 0x09,
        "escape": 0x1B,
        "esc": 0x1B,
        "enter": 0x0D,
        "return": 0x0D,
        "capslock": 0x14,
        "backspace": 0x08,
        "grave": 0xC0,
        "`": 0xC0,
        "~": 0xC0,
    }
    if key.startswith("f") and key[1:].isdigit():
        try:
            n = int(key[1:])
            if 1 <= n <= 24:
                return 0x70 + (n - 1)
        except Exception:
            pass
    arrows = {
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
    }
    if key in arrows:
        return arrows[key]
    if key in mapping:
        return mapping[key]
    if len(key) == 1:
        ch = key
        if "a" <= ch <= "z":
            return ord(ch.upper())
        if "0" <= ch <= "9":
            return ord(ch)
    return None


def _is_hold_key_pressed(key: str) -> bool:
    # Allow chords like "ctrl+alt+f1".
    parts = [p.strip().lower() for p in str(key or "").split("+") if p.strip()]
    if not parts:
        return False

    for part in parts:
        vk = _vk_from_hold_key(part)
        if vk is None:
            return False
        try:
            state = ctypes.windll.user32.GetAsyncKeyState(int(vk))
            if not bool(state & 0x8000):
                return False
        except Exception:
            return False
    return True


class HoldKeyCaptureEdit(QLineEdit):
    """Read-only field that captures a hold key/chord when clicked.

    - Click to start capture.
    - Press a key / mouse button to set.
    - Press Esc to cancel.
    """

    key_captured = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._capturing = False
        self._previous_text = ""
        self._captured_keys: List[str] = []
        self._captured_mods: Set[str] = set()
        self._finalize_timer = QTimer(self)
        self._finalize_timer.setSingleShot(True)
        self._finalize_timer.setInterval(450)
        self._finalize_timer.timeout.connect(self._finalize_capture)

    def _finalize_capture(self) -> None:
        if not self._capturing:
            return
        keys = [k for k in self._captured_keys if isinstance(k, str) and k.strip()]
        mods = {m for m in self._captured_mods if isinstance(m, str) and m.strip()}

        if not keys and not mods:
            return

        order = ["ctrl", "alt", "shift", "windows"]
        mod_list = [m for m in order if m in mods]
        chord = "+".join([*mod_list, *keys])
        chord = _normalize_hotkey_chord(chord)

        self._capturing = False
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self.key_captured.emit(chord)

    def begin_capture(self) -> None:
        if self._capturing:
            return
        self._previous_text = self.text()
        self._capturing = True
        self._captured_keys = []
        self._captured_mods = set()
        try:
            self._finalize_timer.stop()
        except Exception:
            pass
        try:
            self.setText(tr_lit("Press a key… (Esc to cancel)"))
        except Exception:
            self.setText("Press a key… (Esc to cancel)")
        try:
            self.grabKeyboard()
        except Exception:
            pass

    def cancel_capture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        try:
            self._finalize_timer.stop()
        except Exception:
            pass
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self.setText(self._previous_text)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        # First click arms capture; the click itself should not be captured.
        if not self._capturing:
            self.begin_capture()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):  # type: ignore[override]
        if not self._capturing:
            super().mousePressEvent(event)
            return

        mods = []
        try:
            m = QApplication.keyboardModifiers()
            if m & Qt.KeyboardModifier.ControlModifier:
                mods.append("ctrl")
            if m & Qt.KeyboardModifier.AltModifier:
                mods.append("alt")
            if m & Qt.KeyboardModifier.ShiftModifier:
                mods.append("shift")
            if m & Qt.KeyboardModifier.MetaModifier:
                mods.append("windows")
        except Exception:
            pass

        btn = event.button()
        mouse = None
        if btn == Qt.MouseButton.LeftButton:
            mouse = "mouse_left"
        elif btn == Qt.MouseButton.RightButton:
            mouse = "mouse_right"
        elif btn == Qt.MouseButton.MiddleButton:
            mouse = "mouse_middle"
        elif btn == Qt.MouseButton.XButton1:
            mouse = "mouse_x1"
        elif btn == Qt.MouseButton.XButton2:
            mouse = "mouse_x2"
        if mouse is None:
            return

        # Mouse capture finalizes immediately.
        chord = "+".join([*mods, mouse]) if mods else mouse
        chord = _normalize_hotkey_chord(chord)
        self._capturing = False
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self.key_captured.emit(chord)
        event.accept()

    def keyPressEvent(self, event):  # type: ignore[override]
        if not self._capturing:
            super().keyPressEvent(event)
            return

        if event.key() in (Qt.Key.Key_Escape,):
            self.cancel_capture()
            event.accept()
            return

        key_name = None
        k = event.key()
        if k in (Qt.Key.Key_Control,):
            key_name = "ctrl"
        elif k in (Qt.Key.Key_Shift,):
            key_name = "shift"
        elif k in (Qt.Key.Key_Alt,):
            key_name = "alt"
        elif k in (Qt.Key.Key_Meta,):
            key_name = "windows"
        elif k in (Qt.Key.Key_Space,):
            key_name = "space"
        elif k in (Qt.Key.Key_Tab,):
            key_name = "tab"
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            key_name = "enter"
        elif k in (Qt.Key.Key_Backspace,):
            key_name = "backspace"
        elif k in (Qt.Key.Key_CapsLock,):
            key_name = "capslock"
        elif k in (Qt.Key.Key_QuoteLeft,):
            key_name = "grave"
        elif Qt.Key.Key_F1 <= k <= Qt.Key.Key_F24:
            key_name = f"f{int(k) - int(Qt.Key.Key_F1) + 1}"
        elif k == Qt.Key.Key_Left:
            key_name = "left"
        elif k == Qt.Key.Key_Right:
            key_name = "right"
        elif k == Qt.Key.Key_Up:
            key_name = "up"
        elif k == Qt.Key.Key_Down:
            key_name = "down"
        else:
            text = (event.text() or "").strip().lower()
            if len(text) == 1 and ("a" <= text <= "z" or "0" <= text <= "9" or text in ("`", "~")):
                key_name = "grave" if text in ("`", "~") else text

        if not key_name:
            return

        # Track modifiers separately so we can support multi-key chords like "q+w".
        try:
            m = event.modifiers()
            if m & Qt.KeyboardModifier.ControlModifier:
                self._captured_mods.add("ctrl")
            if m & Qt.KeyboardModifier.AltModifier:
                self._captured_mods.add("alt")
            if m & Qt.KeyboardModifier.ShiftModifier:
                self._captured_mods.add("shift")
            if m & Qt.KeyboardModifier.MetaModifier:
                self._captured_mods.add("windows")
        except Exception:
            pass

        # Put modifiers into the modifiers set (not the key list).
        if key_name in ("ctrl", "alt", "shift", "windows"):
            try:
                self._captured_mods.add(key_name)
            except Exception:
                pass

            # Don't finalize on modifiers alone; wait for a non-modifier key.
            try:
                self._finalize_timer.stop()
            except Exception:
                pass
        else:
            if key_name not in self._captured_keys:
                self._captured_keys.append(key_name)

            # Finalize shortly after the last keypress.
            try:
                self._finalize_timer.start()
            except Exception:
                pass
        event.accept()

    def focusOutEvent(self, event):  # type: ignore[override]
        if self._capturing:
            self.cancel_capture()
        super().focusOutEvent(event)


def _ensure_hold_fade_timer(label: QLabel) -> QTimer:
    timer = getattr(label, "_standard_crosshair_hold_fade_timer", None)
    if isinstance(timer, QTimer):
        return timer

    timer = QTimer(label)
    timer.setInterval(16)

    def on_tick() -> None:
        settings = getattr(label, "_standard_crosshair_settings", None)
        if not isinstance(settings, StandardCrosshairSettings):
            return
        if not bool(getattr(settings, "hold_fade_enabled", False)):
            return

        keys = getattr(settings, "hold_fade_keys", None)
        if isinstance(keys, list) and [k for k in keys if str(k or "").strip()]:
            held = False
            for k in keys:
                kk = str(k or "").strip().lower()
                if not kk:
                    continue
                if _is_hold_key_pressed(kk):
                    held = True
                    break
        else:
            key = str(getattr(settings, "hold_fade_key", "mouse_left") or "mouse_left")
            held = _is_hold_key_pressed(key)
        target = 0.0 if held else 1.0

        try:
            cur = float(getattr(label, "_standard_crosshair_hold_fade_alpha", 1.0))
        except Exception:
            cur = 1.0

        # Smooth approach (~120-200ms feel).
        speed = 0.18
        cur = cur + (target - cur) * speed
        if abs(cur - target) < 0.01:
            cur = target

        prev = getattr(label, "_standard_crosshair_hold_fade_alpha", None)
        try:
            setattr(label, "_standard_crosshair_hold_fade_alpha", float(max(0.0, min(1.0, cur))))
        except Exception:
            return

        try:
            if prev is not None and abs(float(prev) - cur) < 0.002:
                return
        except Exception:
            pass

        extra = float(getattr(label, "_standard_crosshair_fan_angle", 0.0)) if getattr(settings, "fan_enabled", False) else 0.0
        render_crosshair_on_label(label, settings, extra_rotation=extra)

    timer.timeout.connect(on_tick)
    setattr(label, "_standard_crosshair_hold_fade_timer", timer)
    setattr(label, "_standard_crosshair_hold_fade_alpha", 1.0)
    return timer


def _sync_hold_fade_timer_state(label: QLabel, settings: StandardCrosshairSettings) -> None:
    timer = _ensure_hold_fade_timer(label)
    if bool(getattr(settings, "hold_fade_enabled", False)):
        if not timer.isActive():
            timer.start()
    else:
        if timer.isActive():
            timer.stop()
        try:
            setattr(label, "_standard_crosshair_hold_fade_alpha", 1.0)
        except Exception:
            pass


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

    # Sanitize/migrate hold-fade keys.
    try:
        raw_keys = getattr(settings, "hold_fade_keys", None)
        if isinstance(raw_keys, list):
            cleaned = [str(k or "").strip().lower() for k in raw_keys if str(k or "").strip()]
            settings.hold_fade_keys = cleaned
        else:
            settings.hold_fade_keys = []
    except Exception:
        settings.hold_fade_keys = []

    # Back-compat: ensure single key is normalized.
    try:
        single = str(getattr(settings, "hold_fade_key", "mouse_left") or "mouse_left").strip().lower()
        settings.hold_fade_key = single or "mouse_left"
    except Exception:
        settings.hold_fade_key = "mouse_left"

    # Seed presets (templates) for older configs or first-run.
    presets_ok = isinstance(getattr(settings, "presets", None), dict) and bool(settings.presets)
    if not presets_ok:
        _seed_builtin_presets(settings)

    # Optional: merge presets from external import file.
    _merge_external_presets(settings)

    # Do not auto-apply the active preset on startup.
    # Presets are applied explicitly when selected, and any manual edits should
    # persist across restarts even if the last-selected preset name remains.

    presets = settings.presets if isinstance(getattr(settings, "presets", None), dict) else {}
    active_name = settings.active_preset if isinstance(getattr(settings, "active_preset", None), str) else "Default"
    settings.gap = max(0, settings.gap)
    settings.dot_size = clamp(settings.dot_size, 2, 200)
    if settings.dot_shape not in ALLOWED_DOT_SHAPES:
        settings.dot_shape = "circle"
    settings.crosshair_style = settings.crosshair_style if settings.crosshair_style in ALLOWED_CROSSHAIR_STYLES else "plus"
    settings.rotation = float(settings.rotation) if isinstance(settings.rotation, (int, float)) else 0.0
    settings.rotation = settings.rotation % 360
    settings.offset_x = clamp(int(settings.offset_x), -800, 800)
    settings.offset_y = clamp(int(settings.offset_y), -800, 800)
    try:
        settings.randomize_mode = str(getattr(settings, "randomize_mode", "preset") or "preset").strip().lower()
    except Exception:
        settings.randomize_mode = "preset"
    if settings.randomize_mode in ("normal", "full"):
        settings.randomize_mode = "absolute"
    if settings.randomize_mode not in ("preset", "absolute"):
        settings.randomize_mode = "preset"
    settings.line_rounding = clamp(int(settings.line_rounding), 0, 400)
    settings.fan_enabled = bool(settings.fan_enabled)
    settings.fan_speed = clamp(int(settings.fan_speed), -2000, 2000)
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
            # Migrate old polygon -> triangle (per new UX).
            if comp_type == "polygon":
                comp_type = "triangle"
            if comp_type not in COMPONENT_TYPES:
                continue
            limits = COMPONENT_FIELD_LIMITS[comp_type]
            sanitized_comp = {"type": comp_type}
            for field_name, (minimum, maximum, _) in limits.items():
                raw_value = comp.get(field_name, None)
                if raw_value is None:
                    value = _default_component_field_value(comp_type, field_name)
                else:
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        value = _default_component_field_value(comp_type, field_name)
                sanitized_comp[field_name] = max(minimum, min(maximum, value))
            if comp_type == "curve" and "points" in comp:
                pts = comp.get("points")
                if isinstance(pts, list):
                    sanitized_pts: list[list[float]] = []
                    for p in pts:
                        if (
                            isinstance(p, (list, tuple))
                            and len(p) == 2
                            and isinstance(p[0], (int, float))
                            and isinstance(p[1], (int, float))
                        ):
                            sanitized_pts.append([float(p[0]), float(p[1])])
                    if len(sanitized_pts) >= 2:
                        sanitized_comp["points"] = sanitized_pts
            if "draggable" in comp:
                sanitized_comp["draggable"] = _coerce_bool(comp.get("draggable"), default=True)
            if "_standard_base" in comp:
                sanitized_comp["_standard_base"] = _coerce_bool(comp.get("_standard_base"), default=False)
            if "_standard_linked" in comp:
                sanitized_comp["_standard_linked"] = _coerce_bool(comp.get("_standard_linked"), default=True)
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
                # Migrate old polygon -> triangle (per new UX).
                if comp_type == "polygon":
                    comp_type = "triangle"
                if comp_type not in COMPONENT_TYPES:
                    continue
                limits = COMPONENT_FIELD_LIMITS[comp_type]
                sanitized_component = {"type": comp_type}
                for field_name, (minimum, maximum, _) in limits.items():
                    raw_value = component.get(field_name, None)
                    if raw_value is None:
                        value = _default_component_field_value(comp_type, field_name)
                    else:
                        try:
                            value = float(raw_value)
                        except (TypeError, ValueError):
                            value = _default_component_field_value(comp_type, field_name)
                    sanitized_component[field_name] = max(minimum, min(maximum, value))
                if comp_type == "curve" and "points" in component:
                    pts = component.get("points")
                    if isinstance(pts, list):
                        sanitized_pts: list[list[float]] = []
                        for p in pts:
                            if (
                                isinstance(p, (list, tuple))
                                and len(p) == 2
                                and isinstance(p[0], (int, float))
                                and isinstance(p[1], (int, float))
                            ):
                                sanitized_pts.append([float(p[0]), float(p[1])])
                        if len(sanitized_pts) >= 2:
                            sanitized_component["points"] = sanitized_pts
                if "draggable" in component:
                    sanitized_component["draggable"] = _coerce_bool(component.get("draggable"), default=True)
                if "_standard_base" in component:
                    sanitized_component["_standard_base"] = _coerce_bool(component.get("_standard_base"), default=False)
                if "_standard_linked" in component:
                    sanitized_component["_standard_linked"] = _coerce_bool(component.get("_standard_linked"), default=True)
                sanitized_stack.append(sanitized_component)
        sanitized_layers.append(
            {
                "id": layer_id,
                "label": label[:48],
                "enabled": _coerce_bool(entry.get("enabled", True), default=True),
                "draggable": _coerce_bool(entry.get("draggable", False), default=False),
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

    # Normalize presets and ensure at least one exists.
    normalized_presets: dict[str, dict] = {}
    for name, preset in (presets.items() if isinstance(presets, dict) else []):
        if not isinstance(name, str) or not name.strip():
            continue
        if isinstance(preset, dict):
            normalized_presets[name.strip()[:32]] = dict(preset)
    if not normalized_presets:
        normalized_presets = {"Default": _settings_to_preset_dict(settings)}
        active_name = "Default"
    if active_name not in normalized_presets:
        active_name = next(iter(normalized_presets.keys()))
    settings.presets = normalized_presets
    settings.active_preset = active_name
    return settings


def _seed_builtin_presets(settings: StandardCrosshairSettings) -> None:
    """Populate the built-in preset list.

    This should match the presets users see on first run.
    """
    base = _settings_to_preset_dict(settings)
    templates: dict[str, dict] = {"Default": base}

    dot = dict(base)
    dot.update(
        {
            "crosshair_style": "plus",
            "center_dot": True,
            "dot_shape": "circle",
            "dot_size": 6,
            "length": 0,
            "gap": 0,
            "thickness": 0,
            "outline": 0,
        }
    )
    templates["Dot"] = dot

    small_plus = dict(base)
    small_plus.update(
        {
            "crosshair_style": "plus",
            "center_dot": False,
            "length": 18,
            "gap": 6,
            "thickness": 3,
            "outline": 1,
        }
    )
    templates["Small Plus"] = small_plus

    circle_dot = dict(base)
    circle_dot.update(
        {
            "crosshair_style": "circle",
            "center_dot": True,
            "dot_shape": "circle",
            "dot_size": 5,
            "length": 22,
            "gap": 8,
            "thickness": 3,
            "outline": 1,
        }
    )
    templates["Circle + Dot"] = circle_dot

    settings.presets = templates
    if not isinstance(getattr(settings, "active_preset", None), str) or settings.active_preset not in templates:
        settings.active_preset = "Default"


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
    try:
        fade_alpha = float(getattr(label, "_standard_crosshair_hold_fade_alpha", 1.0))
    except Exception:
        fade_alpha = 1.0
    fade_alpha = max(0.0, min(1.0, fade_alpha))
    pixmap = generate_crosshair_pixmap(width, height, settings, extra_rotation, opacity_multiplier=fade_alpha)
    label.setPixmap(pixmap)


def initialize_standard_crosshair(label: QLabel) -> StandardCrosshairSettings:
    """Apply saved settings to the label at startup."""
    settings = load_settings_from_disk()
    _bind_settings_to_label(label, settings)
    _sync_fan_timer_state(label, settings)
    _sync_hold_fade_timer_state(label, settings)
    render_crosshair_on_label(label, settings)
    label.setVisible(settings.visible)
    if settings.visible:
        label.raise_()
    else:
        label.hide()
    return settings


def randomize_standard_crosshair(label: QLabel) -> None:
    """Randomize the standard crosshair bound to a label.

    Intended for global hotkey usage (works even when the editor dialog is closed).
    """
    settings = getattr(label, "_standard_crosshair_settings", None)
    if not isinstance(settings, StandardCrosshairSettings):
        settings = load_settings_from_disk()
        _bind_settings_to_label(label, settings)

    if not bool(getattr(settings, "randomize_hotkey_enabled", False)):
        return

    # If the dialog is open (embedded or floating), delegate to the same handler
    # as the Randomize button so behavior always matches the UI.
    try:
        dlg_ref = getattr(label, "_standard_crosshair_dialog_ref", None)
        dlg = dlg_ref() if callable(dlg_ref) else None
        fn = getattr(dlg, "_on_randomize_clicked", None)
        if callable(fn):
            fn()
            return
    except Exception:
        pass

    mode = str(getattr(settings, "randomize_mode", "preset") or "preset").strip().lower()
    if mode in ("normal", "full"):
        mode = "absolute"
    if mode not in ("preset", "absolute"):
        mode = "preset"

    if mode == "preset":
        # Randomize must not change hotkey/hold-fade toggles.
        preserve_randomize_hotkey = bool(getattr(settings, "randomize_hotkey_enabled", False))
        preserve_hold_fade_enabled = bool(getattr(settings, "hold_fade_enabled", False))
        preserve_hold_fade_key = str(getattr(settings, "hold_fade_key", "mouse_left") or "mouse_left")
        preserve_hold_fade_keys = getattr(settings, "hold_fade_keys", None)
        if not isinstance(preserve_hold_fade_keys, list):
            preserve_hold_fade_keys = []

        presets = settings.presets if isinstance(settings.presets, dict) else {}
        names = [n for n in presets.keys() if isinstance(n, str) and n.strip()]
        if not names:
            return

        # Prefer switching away from the currently active preset so a hotkey press
        # always results in an observable change when multiple presets exist.
        cur = str(getattr(settings, "active_preset", "") or "").strip()
        pool = [n for n in names if n != cur] if len(names) > 1 else list(names)
        chosen = random.choice(pool or names)
        preset = presets.get(chosen)
        if isinstance(preset, dict):
            settings.active_preset = chosen
            _apply_preset_dict_to_settings(settings, preset)

        try:
            settings.randomize_hotkey_enabled = preserve_randomize_hotkey
            settings.hold_fade_enabled = preserve_hold_fade_enabled
            settings.hold_fade_key = preserve_hold_fade_key
            settings.hold_fade_keys = list(preserve_hold_fade_keys)
        except Exception:
            pass
    else:
        # Absolute random: mixes sane + chaos.
        chaos = bool(random.random() < 0.35)
        if not chaos:
            settings.global_scale = int(random.randint(60, 180))
            settings.length = int(random.randint(10, 220))
            settings.thickness = int(random.randint(1, 18))
            settings.gap = int(random.randint(0, 80))
            settings.outline = int(random.randint(0, 10))
            settings.rotation = float(random.randint(0, 359))
            settings.offset_x = 0
            settings.offset_y = 0
            settings.line_rounding = int(random.randint(0, 40))

            settings.fan_enabled = bool(random.random() < 0.25)
            settings.fan_speed = int(random.randint(-240, 240))

            settings.crosshair_style = random.choice(["plus", "x"])
            settings.center_dot = bool(random.random() < 0.6)
            settings.dot_shape = random.choice(["circle", "square", "diamond"])
            settings.dot_size = int(random.randint(2, 20))

            settings.red = int(random.randint(0, 255))
            settings.green = int(random.randint(0, 255))
            settings.blue = int(random.randint(0, 255))
            settings.alpha = int(random.randint(120, 255))
        else:
            settings.global_scale = int(random.randint(25, 1000))
            settings.length = int(random.randint(5, 1500))
            settings.thickness = int(random.randint(1, 200))
            settings.gap = int(random.randint(0, 600))
            settings.outline = int(random.randint(0, 60))
            settings.rotation = float(random.randint(0, 359))
            settings.offset_x = 0
            settings.offset_y = 0
            settings.line_rounding = int(random.randint(0, 400))

            settings.fan_enabled = bool(random.getrandbits(1))
            settings.fan_speed = int(random.randint(-2000, 2000))

            settings.crosshair_style = random.choice(["plus", "x"])
            settings.center_dot = bool(random.getrandbits(1))
            settings.dot_shape = random.choice(["circle", "square", "diamond"])
            settings.dot_size = int(random.randint(2, 200))

            settings.red = int(random.randint(0, 255))
            settings.green = int(random.randint(0, 255))
            settings.blue = int(random.randint(0, 255))
            settings.alpha = int(random.randint(30, 255))

    save_settings_to_disk(settings)
    _sync_fan_timer_state(label, settings)
    _sync_hold_fade_timer_state(label, settings)
    extra = float(getattr(label, "_standard_crosshair_fan_angle", 0.0)) if getattr(settings, "fan_enabled", False) else 0.0
    render_crosshair_on_label(label, settings, extra_rotation=extra)


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
    opacity_multiplier: float = 1.0,
) -> QPixmap:
    """Create a transparent pixmap containing the configured crosshair."""
    pixmap = QPixmap(max(1, width), max(1, height))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    try:
        opacity_multiplier = float(opacity_multiplier)
    except Exception:
        opacity_multiplier = 1.0
    opacity_multiplier = max(0.0, min(1.0, opacity_multiplier))
    if opacity_multiplier != 1.0:
        try:
            painter.setOpacity(opacity_multiplier)
        except Exception:
            pass

    try:
        scale_factor = float(getattr(settings, "global_scale", 100) or 0) / 100.0
    except Exception:
        scale_factor = 1.0
    scale_factor = max(0.0, min(100.0, scale_factor))

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
        if scale_factor != 1.0:
            painter.scale(scale_factor, scale_factor)
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
        if scale_factor != 1.0:
            painter.scale(scale_factor, scale_factor)
        painter.rotate(total_angle + total_rotation)
        painter.translate(offset, perp_offset)
        # Circles don't need rotation, but parameter kept for consistency
        if outline > 0:
            painter.setBrush(outline_color)
            painter.drawEllipse(QPointF(0, 0), radius + outline, radius + outline)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(0, 0), radius, radius)
        painter.restore()

    def draw_polygon_shape(
        total_angle: float,
        offset: float,
        radius: float,
        sides: int,
        perp_offset: float = 0.0,
        component_rotation: float = 0.0,
    ) -> None:
        import math

        radius = max(0.1, float(radius))
        sides = int(max(3, min(12, sides)))
        painter.save()
        painter.translate(center_x, center_y)
        if scale_factor != 1.0:
            painter.scale(scale_factor, scale_factor)
        painter.rotate(total_angle + total_rotation)
        painter.translate(offset, perp_offset)
        if abs(component_rotation) > 0.01:
            painter.rotate(component_rotation)

        step = (2.0 * math.pi) / float(sides)
        path = QPainterPath()
        for i in range(sides):
            a = (i * step) - (math.pi / 2.0)  # start at top
            x = radius * math.cos(a)
            y = radius * math.sin(a)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()

        if outline > 0:
            painter.setBrush(outline_color)
            painter.drawPath(path)
        painter.setBrush(color)
        painter.drawPath(path)
        painter.restore()

    def draw_square_shape(
        total_angle: float,
        offset: float,
        size: float,
        perp_offset: float = 0.0,
        component_rotation: float = 0.0,
    ) -> None:
        size = max(0.1, float(size))
        half = size / 2.0
        painter.save()
        painter.translate(center_x, center_y)
        if scale_factor != 1.0:
            painter.scale(scale_factor, scale_factor)
        painter.rotate(total_angle + total_rotation)
        painter.translate(offset, perp_offset)
        if abs(component_rotation) > 0.01:
            painter.rotate(component_rotation)

        rect = QRectF(-half, -half, size, size)
        if outline > 0:
            painter.setBrush(outline_color)
            painter.drawRect(rect.adjusted(-outline, -outline, outline, outline))
        painter.setBrush(color)
        painter.drawRect(rect)
        painter.restore()

    def draw_curve_shape(
        total_angle: float,
        offset: float,
        perp_offset: float,
        start_dx: float,
        start_dy: float,
        ctrl_dx: float,
        ctrl_dy: float,
        end_dx: float,
        end_dy: float,
        thickness: float,
        component_rotation: float = 0.0,
    ) -> None:
        thickness = max(0.1, float(thickness))
        painter.save()
        painter.translate(center_x, center_y)
        if scale_factor != 1.0:
            painter.scale(scale_factor, scale_factor)
        painter.rotate(total_angle + total_rotation)
        painter.translate(offset, perp_offset)
        if abs(component_rotation) > 0.01:
            painter.rotate(component_rotation)

        path = QPainterPath()
        path.moveTo(QPointF(float(start_dx), float(start_dy)))
        path.quadTo(QPointF(float(ctrl_dx), float(ctrl_dy)), QPointF(float(end_dx), float(end_dy)))

        cap = Qt.PenCapStyle.RoundCap if rounding > 0 else Qt.PenCapStyle.SquareCap
        join = Qt.PenJoinStyle.RoundJoin if rounding > 0 else Qt.PenJoinStyle.MiterJoin

        if outline > 0:
            pen_o = QPen(outline_color)
            pen_o.setCapStyle(cap)
            pen_o.setJoinStyle(join)
            pen_o.setWidthF(thickness + (2.0 * outline))
            painter.setPen(pen_o)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        pen = QPen(color)
        pen.setCapStyle(cap)
        pen.setJoinStyle(join)
        pen.setWidthF(thickness)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()

    def draw_curve_poly_shape(
        total_angle: float,
        offset: float,
        perp_offset: float,
        points: list[list[float]],
        thickness: float,
        component_rotation: float = 0.0,
    ) -> None:
        thickness = max(0.1, float(thickness))
        if not points or len(points) < 2:
            return
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(total_angle + total_rotation)
        painter.translate(offset, perp_offset)
        if abs(component_rotation) > 0.01:
            painter.rotate(component_rotation)

        pts: list[QPointF] = []
        for p in points:
            if isinstance(p, (list, tuple)) and len(p) == 2 and isinstance(p[0], (int, float)) and isinstance(p[1], (int, float)):
                pts.append(QPointF(float(p[0]), float(p[1])))
        if len(pts) < 2:
            painter.restore()
            return

        path = QPainterPath()
        path.moveTo(pts[0])
        if len(pts) == 2:
            path.lineTo(pts[1])
        else:
            # Smooth freehand polyline using quadratic midpoints.
            for i in range(1, len(pts) - 1):
                mid = QPointF((pts[i].x() + pts[i + 1].x()) / 2.0, (pts[i].y() + pts[i + 1].y()) / 2.0)
                path.quadTo(pts[i], mid)
            path.lineTo(pts[-1])

        cap = Qt.PenCapStyle.RoundCap if rounding > 0 else Qt.PenCapStyle.SquareCap
        join = Qt.PenJoinStyle.RoundJoin if rounding > 0 else Qt.PenJoinStyle.MiterJoin

        if outline > 0:
            pen_o = QPen(outline_color)
            pen_o.setCapStyle(cap)
            pen_o.setJoinStyle(join)
            pen_o.setWidthF(thickness + (2.0 * outline))
            painter.setPen(pen_o)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        pen = QPen(color)
        pen.setCapStyle(cap)
        pen.setJoinStyle(join)
        pen.setWidthF(thickness)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
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
                elif ctype == "polygon":
                    offset = float(component.get("offset", 0.0))
                    perp_offset = float(component.get("perp_offset", 0.0))
                    radius = float(component.get("radius", fallback_thickness / 2))
                    sides = int(round(float(component.get("sides", 3.0))))
                    component_angle = float(component.get("angle_offset", 0.0))
                    # Legacy: polygon is treated as triangle in the new UX.
                    draw_polygon_shape(base_angle + angle_offset, offset, radius, 3, perp_offset, component_angle)
                    rendered = True
                elif ctype == "triangle":
                    offset = float(component.get("offset", 0.0))
                    perp_offset = float(component.get("perp_offset", 0.0))
                    radius = float(component.get("radius", fallback_thickness / 2))
                    component_angle = float(component.get("angle_offset", 0.0))
                    draw_polygon_shape(base_angle + angle_offset, offset, radius, 3, perp_offset, component_angle)
                    rendered = True
                elif ctype == "square":
                    offset = float(component.get("offset", 0.0))
                    perp_offset = float(component.get("perp_offset", 0.0))
                    size = float(component.get("size", fallback_thickness * 2.0))
                    component_angle = float(component.get("angle_offset", 0.0))
                    draw_square_shape(base_angle + angle_offset, offset, size, perp_offset, component_angle)
                    rendered = True
                elif ctype == "curve":
                    offset = float(component.get("offset", 0.0))
                    perp_offset = float(component.get("perp_offset", 0.0))
                    thickness = float(component.get("thickness", fallback_thickness))
                    component_angle = float(component.get("angle_offset", 0.0))
                    pts = component.get("points")
                    if isinstance(pts, list):
                        if len(pts) >= 2:
                            draw_curve_poly_shape(
                                base_angle + angle_offset,
                                offset,
                                perp_offset,
                                pts,
                                thickness,
                                component_angle,
                            )
                            rendered = True
                            continue
                        # If points exist but are too short, don't draw legacy bezier.
                        continue

                    else:
                        start_dx = float(component.get("start_dx", -20.0))
                        start_dy = float(component.get("start_dy", 0.0))
                        ctrl_dx = float(component.get("ctrl_dx", 0.0))
                        ctrl_dy = float(component.get("ctrl_dy", 0.0))
                        end_dx = float(component.get("end_dx", 20.0))
                        end_dy = float(component.get("end_dy", 0.0))
                        draw_curve_shape(
                            base_angle + angle_offset,
                            offset,
                            perp_offset,
                            start_dx,
                            start_dy,
                            ctrl_dx,
                            ctrl_dy,
                            end_dx,
                            end_dy,
                            thickness,
                            component_angle,
                        )
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


class _CrosshairResizeOverlay(QWidget):
    """Small, transparent overlay used to resize the standard crosshair via mouse drag.

    It is intentionally not full-screen to avoid blocking input across the whole desktop.
    """

    def __init__(self, dialog: "StandardCrosshairDialog", target_label: QLabel):
        super().__init__(None)
        self._dialog = dialog
        self._target_label = target_label

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self._dragging = False
        self._start_pos = None
        self._start_length = 0
        self._start_gap = 0

        size = 260
        self.resize(size, size)
        # Circular input region so clicks outside the circle pass through.
        self.setMask(QRegion(0, 0, size, size, QRegion.RegionType.Ellipse))
        self._reposition_to_center()

    def _reposition_to_center(self) -> None:
        try:
            rect = self._target_label.geometry()
            center = rect.center()
            self.move(int(center.x() - self.width() / 2), int(center.y() - self.height() / 2))
            self.raise_()
        except Exception:
            return

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return

        self._dragging = True
        self._start_pos = event.globalPosition().toPoint()
        self._start_length = int(getattr(self._dialog.settings, "length", 0) or 0)
        self._start_gap = int(getattr(self._dialog.settings, "gap", 0) or 0)
        event.accept()

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if not self._dragging or self._start_pos is None:
            event.ignore()
            return

        pos = event.globalPosition().toPoint()
        dx = pos.x() - self._start_pos.x()
        dy = pos.y() - self._start_pos.y()

        # Drag mapping:
        # - Horizontal: Length
        # - Vertical: Gap ("wider" = larger gap)
        length = self._start_length + int(dx / 6)
        gap = self._start_gap + int(dy / 6)

        length = max(5, min(80, length))
        gap = max(0, min(40, gap))

        self._dialog._apply_length_gap_from_drag(length, gap)
        event.accept()

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._start_pos = None
            event.accept()
            return
        event.ignore()


class StandardCrosshairDialog(QWidget):
    """Floating dialog that lets users tweak a basic crosshair."""

    visibility_changed = pyqtSignal(bool)
    presets_changed = pyqtSignal()

    def __init__(
        self,
        label: QLabel,
        parent=None,
        *,
        embedded: bool = False,
        on_request_close: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.label = label

        # Allow global hotkeys to find the active dialog and reuse its handlers.
        try:
            setattr(self.label, "_standard_crosshair_dialog_ref", weakref.ref(self))
        except Exception:
            pass
        try:
            self.destroyed.connect(lambda *_: setattr(self.label, "_standard_crosshair_dialog_ref", None))
        except Exception:
            pass

        self._embedded = bool(embedded)
        self._on_request_close = on_request_close
        self.settings = load_settings_from_disk()
        _bind_settings_to_label(self.label, self.settings)
        _sync_fan_timer_state(self.label, self.settings)
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

        # Mouse-driven resize overlay (centered, only active while this dialog is open)
        self._resize_overlay = None
        self._size_grip = None

        if not self._embedded:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._init_ui()
        self._sync_controls_from_settings()

        try:
            apply_language_to_object_tree(self)
        except Exception:
            pass

        try:
            self._resize_overlay = _CrosshairResizeOverlay(self, self.label)
            self._resize_overlay.show()
        except Exception:
            self._resize_overlay = None

    def closeEvent(self, event):  # type: ignore[override]
        try:
            if self._resize_overlay is not None:
                self._resize_overlay.close()
        except Exception:
            pass
        super().closeEvent(event)

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        try:
            if self._resize_overlay is not None:
                self._resize_overlay._reposition_to_center()
                self._resize_overlay.show()
        except Exception:
            pass

    def hideEvent(self, event):  # type: ignore[override]
        try:
            if self._resize_overlay is not None:
                self._resize_overlay.hide()
        except Exception:
            pass
        super().hideEvent(event)

    def _apply_length_gap_from_drag(self, length: int, gap: int) -> None:
        changed = False

        if length != self.settings.length:
            self.settings.length = length
            if getattr(self, "length_slider", None) is not None:
                self._set_slider_value(self.length_slider, length)
            changed = True

        if gap != self.settings.gap:
            self.settings.gap = gap
            if getattr(self, "gap_slider", None) is not None:
                self._set_slider_value(self.gap_slider, gap)
            changed = True

        if changed:
            self._persist_and_render()

    def _init_ui(self) -> None:
        main_frame = QFrame(self)
        main_frame.setObjectName("mainFrame")
        if self._embedded:
            # When embedded in the control panel, don't render an extra rounded
            # container; the panel already provides the chrome.
            main_frame.setStyleSheet(
                "QFrame#mainFrame { background: transparent; border: none; border-radius: 0px; }"
            )
        else:
            main_frame.setStyleSheet(
                f"""
                QFrame#mainFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 {UI_THEME['bg']}, stop:1 {UI_THEME['bg2']});
                    border-radius: 15px;
                    border: 1px solid {UI_THEME['border']};
                }}
            """
            )

        main_layout = QVBoxLayout(main_frame)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        if not self._embedded:
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

        # Resize handle for the frameless window (standalone only).
        if not self._embedded:
            self._size_grip = QSizeGrip(main_frame)
            self._size_grip.setFixedSize(16, 16)
            self._size_grip.setStyleSheet("QSizeGrip { background: transparent; }")

        wrapper_layout = QVBoxLayout(self)
        # Embedded should feel like a full page.
        if self._embedded:
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
        else:
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(main_frame)

        # Keep the dialog compact by default (still resizable) when standalone.
        if not self._embedded:
            self.setMinimumSize(410, 500)
            self.resize(460, 500)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        try:
            if not self._embedded and self._size_grip is not None:
                margin = 8
                self._size_grip.move(
                    self.width() - self._size_grip.width() - margin,
                    self.height() - self._size_grip.height() - margin,
                )
                self._size_grip.raise_()
        except Exception:
            pass

    def _create_title_bar(self) -> QFrame:
        title_bar = QFrame()
        title_bar.setStyleSheet(
            f"""
            QFrame {{
                background-color: {UI_THEME['surface']};
                border-top-left-radius: 15px;
                border-top-right-radius: 15px;
                border-bottom: 1px solid {UI_THEME['border']};
            }}
        """
        )
        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(15, 8, 8, 8)

        title_label = QLabel("🎯 WaifuAim")
        title_label.setStyleSheet(
            f"""
            QLabel {{
                color: {UI_THEME['text']};
                font-size: 14px;
                font-weight: 700;
                background: transparent;
            }}
        """
        )
        layout.addWidget(title_label)
        layout.addStretch()

        close_btn = self._create_button("×", UI_THEME["danger"], size=28)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        return title_bar

    def _create_content_frame(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: transparent; }")
        layout = QVBoxLayout(frame)
        # Add a little breathing room when embedded so content doesn't hug panel edges.
        layout.setContentsMargins(14 if self._embedded else 12, 10 if self._embedded else 12, 14 if self._embedded else 12, 12 if self._embedded else 14)
        layout.setSpacing(10)

        info = QLabel(tr_lit("Choose or edit a preset for generated crosshairs."))
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {UI_THEME['muted']};")
        layout.addWidget(info)

        # Presets
        presets_frame = QFrame()
        if self._embedded:
            presets_frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        else:
            presets_frame.setStyleSheet(
                f"""
                QFrame {{
                    background-color: {UI_THEME['surface']};
                    border-radius: 12px;
                    padding: 8px;
                    border: 1px solid {UI_THEME['border']};
                }}
            """
            )
        presets_outer = QVBoxLayout(presets_frame)
        presets_outer.setContentsMargins(0 if self._embedded else 8, 0 if self._embedded else 6, 0 if self._embedded else 8, 0 if self._embedded else 6)
        presets_outer.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        preset_label = QLabel(tr_lit("Preset"))
        preset_label.setStyleSheet(f"color: {UI_THEME['text']}; font-weight: 600; font-size: 11px;")
        top_row.addWidget(preset_label)

        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet(
            f"""
            QComboBox {{
                background-color: {UI_THEME['surface2']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 10px;
                padding: 4px 10px;
                color: {UI_THEME['text']};
            }}
            QComboBox:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QComboBox QAbstractItemView {{
                background-color: {UI_THEME['surface']};
                color: {UI_THEME['text']};
                selection-background-color: {UI_THEME['accent']};
                selection-color: white;
                border: 1px solid {UI_THEME['border']};
                outline: none;
            }}
        """
        )
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preset_combo.setFixedHeight(26)
        top_row.addWidget(self.preset_combo, 1)
        presets_outer.addLayout(top_row)

        def make_small_btn(text: str, bg: str, fg: str = "white") -> QPushButton:
            btn = QPushButton(text)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {bg};
                    color: {fg};
                    border: 1px solid {UI_THEME['border']};
                    border-radius: 10px;
                    padding: 3px 10px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background-color: {self._adjust_color(bg, 1.08)}; }}
                QPushButton:pressed {{ background-color: {self._adjust_color(bg, 0.92)}; }}
                """
            )
            return btn

        self.preset_save_btn = make_small_btn(tr_lit("Save"), UI_THEME["accent"])
        self.preset_save_as_btn = make_small_btn(tr_lit("Save As"), UI_THEME["surface2"], fg=UI_THEME["text"])
        self.preset_delete_btn = make_small_btn(tr_lit("Delete"), UI_THEME["danger"])
        self.preset_reset_btn = make_small_btn(tr_lit("Reset"), UI_THEME["surface2"], fg=UI_THEME["text"])

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addStretch()
        bottom_row.addWidget(self.preset_reset_btn)
        bottom_row.addWidget(self.preset_save_btn)
        bottom_row.addWidget(self.preset_save_as_btn)
        bottom_row.addWidget(self.preset_delete_btn)
        presets_outer.addLayout(bottom_row)
        layout.addWidget(presets_frame)

        layout.addWidget(self._create_accordion_section(tr_lit("Basic"), self._create_slider_group(carded=False), expanded=False, key="basic"))
        layout.addWidget(self._create_accordion_section(tr_lit("Transform"), self._create_shape_group(carded=False), expanded=False, key="transform"))
        layout.addWidget(self._create_accordion_section(tr_lit("Dot"), self._create_dot_group(carded=False), expanded=False, key="dot"))
        layout.addWidget(self._create_accordion_section(tr_lit("Color"), self._create_color_group(carded=False), expanded=False, key="color"))

        # Line Builder: keep as a standalone button card (no accordion wrapper).
        layout.addWidget(self._create_projection_group(carded=False))
        return frame

    def _create_accordion_section(self, title: str, content: QWidget, *, expanded: bool = False, key: Optional[str] = None) -> QFrame:
        wrapper = QFrame()
        try:
            if key:
                wrapper.setProperty("accordion_key", str(key))
        except Exception:
            pass
        wrapper.setStyleSheet(
            f"""
            QFrame {{
                background-color: {UI_THEME['surface']};
                border-radius: 12px;
                border: 1px solid {UI_THEME['border']};
            }}
            """
        )
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(8)

        header = QToolButton()
        header.setText(tr_lit(str(title or "Section")))
        header.setCheckable(True)
        header.setChecked(bool(expanded))
        header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        try:
            if key:
                header.setObjectName(f"accordionHeader_{str(key)}")
                header.setProperty("accordion_key", str(key))
        except Exception:
            pass
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.setStyleSheet(
            f"""
            QToolButton {{
                background: transparent;
                border: none;
                color: {UI_THEME['text']};
                font-size: 12px;
                font-weight: 800;
                padding: 4px 2px;
            }}
            QToolButton:hover {{ color: {UI_THEME['text']}; }}
            """
        )

        content.setVisible(bool(expanded))

        def on_toggle(checked: bool) -> None:
            content.setVisible(bool(checked))
            header.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

        header.toggled.connect(on_toggle)

        outer.addWidget(header)
        outer.addWidget(content)
        return wrapper

    def get_accordion_state(self) -> Dict[str, bool]:
        """Return expanded/collapsed state for known accordion sections.

        Keys are stable (language-independent) strings like "basic".
        """
        out: Dict[str, bool] = {}
        try:
            wrappers = self.findChildren(QFrame)
        except Exception:
            wrappers = []
        for w in wrappers:
            try:
                key = w.property("accordion_key")
            except Exception:
                key = None
            if not isinstance(key, str) or not key:
                continue
            header = None
            try:
                headers = w.findChildren(QToolButton)
                header = headers[0] if headers else None
            except Exception:
                header = None
            if header is None:
                continue
            try:
                out[key] = bool(header.isChecked())
            except Exception:
                continue
        return out

    def set_accordion_state(self, state: Optional[Dict[str, bool]]) -> None:
        """Restore expanded/collapsed state saved by get_accordion_state()."""
        if not isinstance(state, dict) or not state:
            return
        try:
            wrappers = self.findChildren(QFrame)
        except Exception:
            wrappers = []
        for w in wrappers:
            try:
                key = w.property("accordion_key")
            except Exception:
                key = None
            if not isinstance(key, str) or key not in state:
                continue
            desired = bool(state.get(key, False))

            header = None
            try:
                headers = w.findChildren(QToolButton)
                header = headers[0] if headers else None
            except Exception:
                header = None
            if header is None:
                continue

            # Find the content widget (second item in the wrapper's layout).
            content = None
            try:
                lay = w.layout()
                if lay is not None and lay.count() >= 2:
                    content = lay.itemAt(1).widget()
            except Exception:
                content = None

            try:
                header.blockSignals(True)
                header.setChecked(desired)
            except Exception:
                pass
            finally:
                try:
                    header.blockSignals(False)
                except Exception:
                    pass

            try:
                if content is not None:
                    content.setVisible(desired)
            except Exception:
                pass
            try:
                header.setArrowType(Qt.ArrowType.DownArrow if desired else Qt.ArrowType.RightArrow)
            except Exception:
                pass

    def _refresh_presets_ui(self) -> None:
        if not hasattr(self, "preset_combo"):
            return
        if not isinstance(self.settings.presets, dict) or not self.settings.presets:
            self.settings.presets = {"Default": _settings_to_preset_dict(self.settings)}
            self.settings.active_preset = "Default"
        if self.settings.active_preset not in self.settings.presets:
            self.settings.active_preset = next(iter(self.settings.presets.keys()))

        names = sorted(self.settings.presets.keys(), key=lambda s: s.lower())
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(names)
        idx = self.preset_combo.findText(self.settings.active_preset)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)

        if not getattr(self, "_presets_wired", False):
            self.preset_combo.currentTextChanged.connect(self._on_preset_selected)
            self.preset_save_btn.clicked.connect(self._save_to_current_preset)
            self.preset_save_as_btn.clicked.connect(self._save_as_preset)
            self.preset_delete_btn.clicked.connect(self._delete_current_preset)
            self.preset_reset_btn.clicked.connect(self._reset_presets)
            self._presets_wired = True

    def _on_preset_selected(self, name: str) -> None:
        if not name or name not in self.settings.presets:
            return
        self.settings.active_preset = name
        _apply_preset_dict_to_settings(self.settings, self.settings.presets[name])
        self._sync_controls_from_settings()
        self._persist_and_render()
        self.presets_changed.emit()

    def _save_to_current_preset(self) -> None:
        name = self.settings.active_preset
        if not name:
            return
        self.settings.presets[name] = _settings_to_preset_dict(self.settings)
        self._persist_and_render()
        self.presets_changed.emit()

    def _save_as_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok:
            return
        name = (name or "").strip()[:32]
        if not name:
            return
        self.settings.presets[name] = _settings_to_preset_dict(self.settings)
        self.settings.active_preset = name
        self._refresh_presets_ui()
        self._persist_and_render()
        self.presets_changed.emit()

    def _delete_current_preset(self) -> None:
        if not isinstance(self.settings.presets, dict) or len(self.settings.presets) <= 1:
            return
        name = self.settings.active_preset
        if not name or name not in self.settings.presets:
            return
        self.settings.presets.pop(name, None)
        self.settings.active_preset = next(iter(self.settings.presets.keys()))
        self._refresh_presets_ui()
        self._on_preset_selected(self.settings.active_preset)
        self.presets_changed.emit()

    def _reset_presets(self) -> None:
        """Reset only the currently-selected preset to factory defaults."""
        if not isinstance(self.settings.presets, dict) or not self.settings.presets:
            return
        active = self.settings.active_preset if isinstance(self.settings.active_preset, str) else "Default"
        if not active:
            active = "Default"

        # Preserve current visibility so Reset doesn't unexpectedly hide/show.
        current_visible = bool(getattr(self.settings, "visible", True))

        defaults = StandardCrosshairSettings()
        _seed_builtin_presets(defaults)
        baseline = defaults.presets.get(active)
        if not isinstance(baseline, dict):
            baseline = defaults.presets.get("Default", {})

        _apply_preset_dict_to_settings(self.settings, baseline)
        self.settings.visible = current_visible

        # Overwrite only the active preset.
        self.settings.presets[active] = _settings_to_preset_dict(self.settings)

        self._refresh_presets_ui()
        self._sync_controls_from_settings()
        self._persist_and_render()
        self.presets_changed.emit()

    def _create_slider_group(self, *, carded: bool = True) -> QFrame:
        frame = QFrame()
        if carded:
            frame.setStyleSheet(
                f"""
                QFrame {{
                    background-color: {UI_THEME['surface']};
                    border-radius: 12px;
                    border: 1px solid {UI_THEME['border']};
                }}
            """
            )
        else:
            frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0 if not carded else 8, 0 if not carded else 8, 0 if not carded else 8, 0 if not carded else 8)
        layout.setSpacing(8)

        self.global_scale_slider = self._add_slider(
            layout,
            "Size",
            0,
            10000,
            int(getattr(self.settings, "global_scale", 100) or 100),
            self._on_global_scale,
            suffix="%",
            step=1,
        )
        self.length_slider = self._add_slider(layout, "Length", 5, 80, self.settings.length, self._on_length)
        self.thickness_slider = self._add_slider(layout, "Thickness", 1, 15, self.settings.thickness, self._on_thickness)
        self.gap_slider = self._add_slider(layout, "Gap", 0, 40, self.settings.gap, self._on_gap)
        self.outline_slider = self._add_slider(layout, "Outline", 0, 5, self.settings.outline, self._on_outline, suffix="px")
        return frame

    def _create_shape_group(self, *, carded: bool = True) -> QFrame:
        frame = QFrame()
        if carded:
            frame.setStyleSheet(
                f"""
                QFrame {{
                    background-color: {UI_THEME['surface']};
                    border-radius: 12px;
                    border: 1px solid {UI_THEME['border']};
                }}
            """
            )
        else:
            frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0 if not carded else 8, 0 if not carded else 8, 0 if not carded else 8, 0 if not carded else 8)
        layout.setSpacing(8)

        style_row = QHBoxLayout()
        style_row.addWidget(self._section_label(tr_lit("Crosshair Style")))
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

        fan_row = QHBoxLayout()
        self.fan_checkbox = QCheckBox(tr_lit("Enable Fan Animation"))
        self.fan_checkbox.setChecked(self.settings.fan_enabled)
        self.fan_checkbox.setStyleSheet(
            f"QCheckBox {{ color: {UI_THEME['text']}; font-weight: 600; }}"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
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

        # Hold-fade: fade crosshair while a key/button is held.
        fade_row = QHBoxLayout()
        self.hold_fade_checkbox = QCheckBox(tr_lit("Fade while holding"))
        self.hold_fade_checkbox.setChecked(bool(getattr(self.settings, "hold_fade_enabled", False)))
        self.hold_fade_checkbox.setStyleSheet(self.fan_checkbox.styleSheet())
        self.hold_fade_checkbox.toggled.connect(self._on_hold_fade_toggle)
        fade_row.addWidget(self.hold_fade_checkbox)

        selector_style = (
            f"QComboBox {{ background-color: {UI_THEME['surface2']}; color: {UI_THEME['text']}; border: 1px solid {UI_THEME['border']}; border-radius: 10px; padding: 4px 10px; font-size: 11px; font-weight: 800; }}"
            f"QComboBox:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background-color: {UI_THEME['surface']}; color: {UI_THEME['text']}; border: 1px solid {UI_THEME['border']}; selection-background-color: {UI_THEME['accent']}; }}"
        )

        self.hold_fade_key_edit = HoldKeyCaptureEdit()
        self.hold_fade_key_edit.setFixedHeight(26)
        self.hold_fade_key_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {UI_THEME['surface2']}; color: {UI_THEME['text']}; border: 1px solid {UI_THEME['border']}; border-radius: 10px; padding: 4px 10px; font-size: 11px; font-weight: 800; }}"
            f"QLineEdit:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}"
        )
        self.hold_fade_key_edit.setToolTip(tr_lit("Click, then press a key or mouse button"))
        self.hold_fade_key_edit.setText(str(getattr(self.settings, "hold_fade_key", "mouse_left") or "mouse_left"))
        self.hold_fade_key_edit.key_captured.connect(self._on_hold_fade_key_captured)
        fade_row.addStretch()
        fade_row.addWidget(self.hold_fade_key_edit)
        layout.addLayout(fade_row)

        # Randomize
        rand_row = QHBoxLayout()
        rand_row.addWidget(self._section_label(tr_lit("Randomize")))
        self.randomize_mode_combo = QComboBox()
        self.randomize_mode_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.randomize_mode_combo.setStyleSheet(selector_style)
        self.randomize_mode_combo.addItem(tr_lit("From Presets"), "preset")
        self.randomize_mode_combo.addItem(tr_lit("Absolute Random"), "absolute")
        try:
            cur_mode = str(getattr(self.settings, "randomize_mode", "preset") or "preset").strip().lower()
        except Exception:
            cur_mode = "preset"
        if cur_mode in ("normal", "full"):
            cur_mode = "absolute"
        idx = self.randomize_mode_combo.findData(cur_mode)
        if idx >= 0:
            self.randomize_mode_combo.setCurrentIndex(idx)
        self.randomize_mode_combo.currentIndexChanged.connect(self._on_randomize_mode_changed)
        rand_row.addWidget(self.randomize_mode_combo, 1)
        self.randomize_btn = QPushButton(tr_lit("Randomize"))
        self.randomize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.randomize_btn.setFixedHeight(26)
        self.randomize_btn.setStyleSheet(
            f"QPushButton {{ background-color: {UI_THEME['surface2']}; color: {UI_THEME['text']}; border: 1px solid {UI_THEME['border']}; border-radius: 10px; padding: 3px 10px; font-weight: 700; }}"
            f"QPushButton:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}"
        )
        self.randomize_btn.clicked.connect(self._on_randomize_clicked)
        rand_row.addWidget(self.randomize_btn)
        layout.addLayout(rand_row)

        rand_hotkey_row = QHBoxLayout()
        self.randomize_hotkey_checkbox = QCheckBox(tr_lit("Enable randomize hotkey"))
        self.randomize_hotkey_checkbox.setChecked(bool(getattr(self.settings, "randomize_hotkey_enabled", False)))
        self.randomize_hotkey_checkbox.setStyleSheet(self.fan_checkbox.styleSheet())
        self.randomize_hotkey_checkbox.toggled.connect(self._on_randomize_hotkey_toggle)
        rand_hotkey_row.addWidget(self.randomize_hotkey_checkbox)

        self.randomize_hotkey_key_edit = HoldKeyCaptureEdit()
        self.randomize_hotkey_key_edit.setFixedHeight(26)
        self.randomize_hotkey_key_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {UI_THEME['surface2']}; color: {UI_THEME['text']}; border: 1px solid {UI_THEME['border']}; border-radius: 10px; padding: 4px 10px; font-size: 11px; font-weight: 800; }}"
            f"QLineEdit:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}"
        )
        self.randomize_hotkey_key_edit.setToolTip(tr_lit("Click, then press a key or mouse button"))
        self.randomize_hotkey_key_edit.setText(_get_single_hotkey_binding_normalized("randomize_crosshair"))
        self.randomize_hotkey_key_edit.key_captured.connect(self._on_randomize_hotkey_key_captured)
        rand_hotkey_row.addStretch()
        rand_hotkey_row.addWidget(self.randomize_hotkey_key_edit)
        layout.addLayout(rand_hotkey_row)

        return frame

    def _create_dot_group(self, *, carded: bool = True) -> QFrame:
        frame = QFrame()
        if carded:
            frame.setStyleSheet(
                f"""
                QFrame {{
                    background-color: {UI_THEME['surface']};
                    border-radius: 12px;
                    border: 1px solid {UI_THEME['border']};
                }}
            """
            )
        else:
            frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0 if not carded else 8, 0 if not carded else 8, 0 if not carded else 8, 0 if not carded else 8)
        layout.setSpacing(8)

        self.center_dot_check = QCheckBox(tr_lit("Add Center Dot"))
        self.center_dot_check.setStyleSheet(
            f"QCheckBox {{ color: {UI_THEME['text']}; font-weight: 600; }}"
            "QCheckBox::indicator { width: 18px; height: 18px; }"
        )
        self.center_dot_check.toggled.connect(self._on_center_dot_toggled)
        layout.addWidget(self.center_dot_check)

        shape_row = QHBoxLayout()
        shape_row.addWidget(self._section_label(tr_lit("Dot Shape")))
        self.circle_btn = self._create_choice_button(tr_lit("◯ Circle"), self.settings.dot_shape == "circle")
        self.square_btn = self._create_choice_button(tr_lit("▢ Square"), self.settings.dot_shape == "square")
        self.diamond_btn = self._create_choice_button(tr_lit("◇ Diamond"), self.settings.dot_shape == "diamond")
        self.circle_btn.clicked.connect(lambda: self._set_dot_shape("circle"))
        self.square_btn.clicked.connect(lambda: self._set_dot_shape("square"))
        self.diamond_btn.clicked.connect(lambda: self._set_dot_shape("diamond"))
        shape_row.addWidget(self.circle_btn)
        shape_row.addWidget(self.square_btn)
        shape_row.addWidget(self.diamond_btn)
        layout.addLayout(shape_row)

        self.dot_size_slider = self._add_slider(
            layout, tr_lit("Dot Size"), 2, 200, self.settings.dot_size, self._on_dot_size, suffix="px"
        )

        return frame

    def _create_projection_group(self, *, carded: bool = True) -> QFrame:
        frame = QFrame()
        if carded:
            frame.setStyleSheet(
                f"""
                QFrame {{
                    background-color: {UI_THEME['surface']};
                    border-radius: 12px;
                    border: 1px solid {UI_THEME['border']};
                }}
            """
            )
        else:
            frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0 if not carded else 12, 0 if not carded else 12, 0 if not carded else 12, 0 if not carded else 12)
        layout.setSpacing(10)

        builder_card = QFrame()
        builder_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {UI_THEME['surface2']};
                border-radius: 12px;
                border: 1px solid {UI_THEME['border']};
                padding: 10px;
            }}
        """
        )
        builder_row = QHBoxLayout(builder_card)
        builder_row.setSpacing(0)
        builder_row.setContentsMargins(8, 6, 8, 6)
        builder_btn = QPushButton(tr_lit("Open Line Builder"))
        builder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        builder_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        builder_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {UI_THEME['surface']};
                color: {UI_THEME['text']};
                border: 1px solid {UI_THEME['accent']};
                border-radius: 12px;
                padding: 12px 18px;
                font-size: 13px;
                font-weight: 650;
            }}
            QPushButton:hover {{ background-color: {UI_THEME['surface2']}; }}
            QPushButton:pressed {{ background-color: {UI_THEME['surface']}; }}
        """
        )
        builder_btn.clicked.connect(self._open_line_builder)
        builder_row.addWidget(builder_btn, 1)
        layout.addWidget(builder_card)
        return frame

    def _create_color_group(self, *, carded: bool = True) -> QFrame:
        frame = QFrame()
        if carded:
            frame.setStyleSheet(
                f"""
                QFrame {{
                    background-color: {UI_THEME['surface']};
                    border-radius: 12px;
                    border: 1px solid {UI_THEME['border']};
                }}
            """
            )
        else:
            frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0 if not carded else 8, 0 if not carded else 8, 0 if not carded else 8, 0 if not carded else 8)
        layout.setSpacing(8)

        self.color_preview = QLabel()
        self.color_preview.setFixedHeight(20)
        self.color_preview.setStyleSheet(self._color_preview_style())
        layout.addWidget(self.color_preview)

        self.red_slider = self._add_slider(layout, tr_lit("Red"), 0, 255, self.settings.red, self._on_red, suffix="")
        self.green_slider = self._add_slider(layout, tr_lit("Green"), 0, 255, self.settings.green, self._on_green, suffix="")
        self.blue_slider = self._add_slider(layout, tr_lit("Blue"), 0, 255, self.settings.blue, self._on_blue, suffix="")
        self.alpha_slider = self._add_slider(layout, tr_lit("Alpha"), 25, 255, self.settings.alpha, self._on_alpha, suffix="")

        picker_layout = QHBoxLayout()
        picker_layout.setSpacing(8)

        self.hex_input = QLineEdit()
        self.hex_input.setMaxLength(7)
        self.hex_input.setPlaceholderText("#00FF90")
        self.hex_input.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: {UI_THEME['surface2']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 10px;
                padding: 5px 10px;
                color: {UI_THEME['text']};
                font-weight: 600;
            }}
            QLineEdit:focus {{
                border: 1px solid {UI_THEME['accent']};
            }}
        """
        )
        self.hex_input.editingFinished.connect(self._on_hex_input_finished)
        picker_layout.addWidget(self.hex_input)

        palette_btn = QPushButton(tr_lit("🎨 Palette"))
        palette_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        palette_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {UI_THEME['surface2']};
                color: {UI_THEME['text']};
                border: 1px solid {UI_THEME['accent']};
                border-radius: 12px;
                padding: 7px 14px;
                font-weight: 650;
            }}
            QPushButton:hover {{
                background-color: {UI_THEME['surface']};
                border: 1px solid {UI_THEME['border_strong']};
            }}
            QPushButton:pressed {{
                background-color: {self._adjust_color(UI_THEME['surface2'], 0.92)};
            }}
        """
        )
        palette_btn.clicked.connect(self._open_color_dialog)
        picker_layout.addWidget(palette_btn)

        layout.addLayout(picker_layout)
        return frame

    def _color_preview_style(self) -> str:
        color = QColor(self.settings.red, self.settings.green, self.settings.blue, self.settings.alpha)
        return (
            "background-color: rgba({r}, {g}, {b}, {a}); border-radius: 10px; border: 1px solid {border};"
        ).format(r=color.red(), g=color.green(), b=color.blue(), a=color.alpha(), border=UI_THEME["border"])

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
        row.setSpacing(2)
        text = QLabel(tr_lit(label_text))
        text.setStyleSheet(f"color: {UI_THEME['muted']}; font-size: 11px; font-weight: 650;")
        row.addWidget(text)

        slider_frame = QFrame()
        slider_frame.setStyleSheet(
            f"""
            QFrame {{
                background-color: {UI_THEME['surface2']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 12px;
                padding: 4px 6px;
            }}
        """
        )
        slider_layout = QHBoxLayout(slider_frame)
        slider_layout.setContentsMargins(6, 4, 6, 4)
        slider_layout.setSpacing(8)

        clamp_min = minimum
        clamp_max = maximum

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setValue(value)
        slider.setSingleStep(max(1, step))
        slider.setPageStep(max(5, step * 4))
        slider.setFixedHeight(14)
        slider.setMaximumWidth(170)
        slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                border: none;
                height: 4px;
                background: rgba(230, 225, 255, 35);
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {UI_THEME['accent']};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {UI_THEME['accent']};
                border: 1px solid {UI_THEME['border']};
                width: 12px;
                margin: -6px 0;
                border-radius: 6px;
            }}
            QSlider::handle:horizontal:hover {{
                border: 1px solid {UI_THEME['border_strong']};
            }}
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
        spin.setObjectName("SliderValueSpin")
        spin.setStyleSheet(
            f"""
            QAbstractSpinBox#SliderValueSpin {{
                background-color: {UI_THEME['surface2']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 10px;
                padding: 0px 4px;
                color: {UI_THEME['text']};
                min-width: 32px;
                max-width: 40px;
                min-height: 20px;
                max-height: 20px;
                font-size: 11px;
            }}
            QAbstractSpinBox#SliderValueSpin QLineEdit {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                color: {UI_THEME['text']};
                selection-background-color: {UI_THEME['accent']};
                selection-color: white;
                qproperty-alignment: AlignCenter;
            }}
            QAbstractSpinBox#SliderValueSpin:focus {{ border: 1px solid {UI_THEME['border_strong']}; }}
            QAbstractSpinBox#SliderValueSpin:disabled {{
                background-color: rgba(120, 120, 140, 60);
                color: rgba(255, 255, 255, 120);
            }}
        """
        )

        unit_label = None
        if suffix:
            unit_label = QLabel(suffix)
            unit_label.setObjectName("SliderUnitBadge")
            unit_label.setStyleSheet(
                f"""
                QLabel#SliderUnitBadge {{
                    background-color: {UI_THEME['surface2']};
                    color: {UI_THEME['muted']};
                    border: 1px solid {UI_THEME['border']};
                    border-radius: 10px;
                    padding: 0px 4px;
                    font-size: 10px;
                }}
                """
            )
            # Make px badge pill-rounded and compact.
            unit_label.setFixedSize(24, 20)
            unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

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
                background-color: {UI_THEME['surface2']};
                color: {UI_THEME['text']};
                border: none;
                border-radius: 6px;
                font-size: 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {UI_THEME['surface']};
            }}
        """
        )
        return btn

    def _create_primary_button(self, text: str, color: str) -> QPushButton:
        btn = QPushButton(tr_lit(text))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {color};
                color: {UI_THEME['text']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 12px;
                padding: 10px 18px;
                font-size: 13px;
                font-weight: 650;
            }}
            QPushButton:hover {{
                background-color: {self._adjust_color(color, 1.15)};
                border: 1px solid {UI_THEME['border_strong']};
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
        self._refresh_presets_ui()
        if hasattr(self, "center_dot_check"):
            self.center_dot_check.blockSignals(True)
            self.center_dot_check.setChecked(self.settings.center_dot)
            self.center_dot_check.blockSignals(False)

        for slider, value in (
            (getattr(self, "global_scale_slider", None), int(getattr(self.settings, "global_scale", 100) or 100)),
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

        if hasattr(self, "hold_fade_checkbox"):
            self.hold_fade_checkbox.blockSignals(True)
            self.hold_fade_checkbox.setChecked(bool(getattr(self.settings, "hold_fade_enabled", False)))
            self.hold_fade_checkbox.blockSignals(False)
        if hasattr(self, "hold_fade_key_edit"):
            key = str(getattr(self.settings, "hold_fade_key", "mouse_left") or "mouse_left")
            try:
                self.hold_fade_key_edit.blockSignals(True)
                self.hold_fade_key_edit.setText(key)
                self.hold_fade_key_edit.blockSignals(False)
            except Exception:
                pass

        if hasattr(self, "randomize_mode_combo"):
            mode = str(getattr(self.settings, "randomize_mode", "preset") or "preset").strip().lower()
            idx = self.randomize_mode_combo.findData(mode)
            self.randomize_mode_combo.blockSignals(True)
            if idx >= 0:
                self.randomize_mode_combo.setCurrentIndex(idx)
            self.randomize_mode_combo.blockSignals(False)
        if hasattr(self, "randomize_hotkey_checkbox"):
            self.randomize_hotkey_checkbox.blockSignals(True)
            self.randomize_hotkey_checkbox.setChecked(bool(getattr(self.settings, "randomize_hotkey_enabled", False)))
            self.randomize_hotkey_checkbox.blockSignals(False)

        self.label.setVisible(self.settings.visible)
        if self.settings.visible:
            self.label.raise_()
        self._update_visibility_button()
        _bind_settings_to_label(self.label, self.settings)
        _sync_fan_timer_state(self.label, self.settings)
        _sync_hold_fade_timer_state(self.label, self.settings)
        self._render_current_state()

    def _render_current_state(self) -> None:
        self._sync_linked_standard_base_components()
        _sync_hold_fade_timer_state(self.label, self.settings)
        extra_rotation = float(getattr(self.label, "_standard_crosshair_fan_angle", 0.0)) if self.settings.fan_enabled else 0.0
        render_crosshair_on_label(self.label, self.settings, extra_rotation=extra_rotation)

    def _persist_and_render(self) -> None:
        # Keep runtime label state in sync so global hotkeys read updated settings.
        _bind_settings_to_label(self.label, self.settings)
        _sync_fan_timer_state(self.label, self.settings)
        _sync_hold_fade_timer_state(self.label, self.settings)
        self._render_current_state()
        save_settings_to_disk(self.settings)

    def _sync_linked_standard_base_components(self) -> None:
        """Keep seeded standard base objects in sync with global/per-line values.

        This preserves the behavior of the main Length/Gap/Thickness sliders even
        after the standard lines are represented as editable objects in the builder.
        """
        components = self.settings.line_components
        if not isinstance(components, dict):
            return
        profiles = self.settings.line_profiles if isinstance(self.settings.line_profiles, dict) else {}

        default_gap = float(max(0, self.settings.gap))
        default_length = float(max(0, self.settings.length))
        default_thickness = float(max(1, self.settings.thickness))

        for line_key in LINE_KEYS:
            stack = components.get(line_key)
            if not isinstance(stack, list) or not stack:
                continue
            base = stack[0]
            if not isinstance(base, dict):
                continue
            if not bool(base.get("_standard_base", False)):
                continue
            if not bool(base.get("_standard_linked", True)):
                continue
            if base.get("type") != "segment":
                continue

            profile = profiles.get(line_key, {}) if isinstance(profiles, dict) else {}
            use_custom = bool(profile.get("enabled", False))
            gap = float(profile.get("gap", default_gap)) if use_custom else default_gap
            length = float(profile.get("length", default_length)) if use_custom else default_length
            thickness = float(profile.get("thickness", default_thickness)) if use_custom else default_thickness
            tip = float(profile.get("tip_offset", 0.0)) if use_custom else 0.0

            base["offset"] = gap
            base["length"] = max(0.0, length)
            base["thickness"] = max(1.0, thickness)
            base["tip_offset"] = tip
            if "draggable" not in base:
                base["draggable"] = True

    def _toggle_visibility(self) -> None:
        if not hasattr(self, "visibility_btn"):
            return
        hidden = self.visibility_btn.isChecked()
        self.label.setVisible(not hidden)
        if self.label.isVisible():
            self.label.raise_()
        self.settings.visible = self.label.isVisible()
        self._update_visibility_button()
        save_settings_to_disk(self.settings)
        self.visibility_changed.emit(self.label.isVisible())

    def _update_visibility_button(self) -> None:
        if not hasattr(self, "visibility_btn"):
            return
        hidden = not self.label.isVisible()
        self.visibility_btn.blockSignals(True)
        self.visibility_btn.setChecked(hidden)
        self.visibility_btn.blockSignals(False)
        self.visibility_btn.setText("👁️ Show Crosshair" if hidden else "👁️ Hide Crosshair")

    def _start_fan_timer(self) -> None:
        _sync_fan_timer_state(self.label, self.settings)

    def _stop_fan_timer(self) -> None:
        _sync_fan_timer_state(self.label, self.settings)

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
        # Fan ticks are handled by the label-attached timer.
        return

    def sync_with_label(self) -> None:
        """Synchronize the dialog toggle with the current label visibility."""
        self.settings.visible = self.label.isVisible()
        self._update_visibility_button()
        save_settings_to_disk(self.settings)
        self.sync_hotkeys_from_config()

    def sync_hotkeys_from_config(self) -> None:
        """Refresh hotkey text fields from hotkey_config.json."""
        try:
            edit = getattr(self, "randomize_hotkey_key_edit", None)
            if isinstance(edit, QLineEdit):
                edit.setText(_get_single_hotkey_binding_normalized("randomize_crosshair"))
        except Exception:
            pass

        # If something external updated the setting, keep the checkbox in sync.
        try:
            cb = getattr(self, "randomize_hotkey_checkbox", None)
            if isinstance(cb, QCheckBox):
                cb.blockSignals(True)
                cb.setChecked(bool(getattr(self.settings, "randomize_hotkey_enabled", False)))
                cb.blockSignals(False)
        except Exception:
            try:
                cb.blockSignals(False)  # type: ignore[name-defined]
            except Exception:
                pass

    def _on_center_dot_toggled(self, checked: bool) -> None:
        self.settings.center_dot = checked
        self._persist_and_render()

    def _on_length(self, value: int) -> None:
        self.settings.length = value
        self._persist_and_render()

    def _on_global_scale(self, value: int) -> None:
        self.settings.global_scale = max(0, min(10000, int(value)))
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
        _sync_fan_timer_state(self.label, self.settings)
        self._persist_and_render()

    def _on_fan_speed(self, value: int) -> None:
        self.settings.fan_speed = max(-360, min(360, value))
        _sync_fan_timer_state(self.label, self.settings)
        self._persist_and_render()

    def _on_hold_fade_toggle(self, enabled: bool) -> None:
        self.settings.hold_fade_enabled = bool(enabled)
        _sync_hold_fade_timer_state(self.label, self.settings)
        self._persist_and_render()

    def _on_hold_fade_key_changed(self, _index: int) -> None:
        combo = getattr(self, "hold_fade_key_combo", None)
        if combo is None:
            return
        key = combo.currentData()
        self.settings.hold_fade_key = str(key or "mouse_left")
        _sync_hold_fade_timer_state(self.label, self.settings)
        self._persist_and_render()

    def _on_hold_fade_key_captured(self, key: str) -> None:
        key = str(key or "").strip().lower()
        if not key:
            return
        self.settings.hold_fade_key = key
        edit = getattr(self, "hold_fade_key_edit", None)
        if isinstance(edit, QLineEdit):
            try:
                edit.setText(key)
            except Exception:
                pass
        _sync_hold_fade_timer_state(self.label, self.settings)
        self._persist_and_render()

    def _on_randomize_mode_changed(self, _index: int) -> None:
        combo = getattr(self, "randomize_mode_combo", None)
        if combo is None:
            return
        mode = str(combo.currentData() or "preset").strip().lower()
        if mode not in ("preset", "absolute"):
            mode = "preset"
        self.settings.randomize_mode = mode
        save_settings_to_disk(self.settings)

    def _on_randomize_hotkey_toggle(self, enabled: bool) -> None:
        try:
            self.settings.randomize_hotkey_enabled = bool(enabled)
        except Exception:
            return
        self._persist_and_render()

    def _on_randomize_hotkey_key_captured(self, key: str) -> None:
        key = str(key or "").strip().lower()
        if not key:
            return
        _set_single_hotkey_binding("randomize_crosshair", key)
        edit = getattr(self, "randomize_hotkey_key_edit", None)
        if isinstance(edit, QLineEdit):
            try:
                edit.setText(key)
            except Exception:
                pass
        try:
            from hotkeys import reload_hotkeys

            reload_hotkeys()
        except Exception:
            pass

    def _on_randomize_clicked(self) -> None:
        mode = None
        combo = getattr(self, "randomize_mode_combo", None)
        if combo is not None:
            mode = combo.currentData()
        mode = str(mode or "preset").strip().lower()

        if mode in ("normal", "full"):
            mode = "absolute"

        try:
            self.settings.randomize_mode = mode if mode in ("preset", "absolute") else "preset"
        except Exception:
            pass

        if mode == "preset":
            presets = self.settings.presets if isinstance(self.settings.presets, dict) else {}
            names = [n for n in presets.keys() if isinstance(n, str) and n.strip()]
            if not names:
                return

            # Prefer switching away from the currently active preset so clicking
            # Randomize always changes something when multiple presets exist.
            cur = str(getattr(self.settings, "active_preset", "") or "").strip()
            pool = [n for n in names if n != cur] if len(names) > 1 else list(names)
            chosen = random.choice(pool or names)

            # Randomize must not change hotkey/hold-fade toggles.
            preserve_randomize_hotkey = bool(getattr(self.settings, "randomize_hotkey_enabled", False))
            preserve_hold_fade_enabled = bool(getattr(self.settings, "hold_fade_enabled", False))
            preserve_hold_fade_key = str(getattr(self.settings, "hold_fade_key", "mouse_left") or "mouse_left")
            preserve_hold_fade_keys = getattr(self.settings, "hold_fade_keys", None)
            if not isinstance(preserve_hold_fade_keys, list):
                preserve_hold_fade_keys = []

            self._on_preset_selected(chosen)

            try:
                self.settings.randomize_hotkey_enabled = preserve_randomize_hotkey
                self.settings.hold_fade_enabled = preserve_hold_fade_enabled
                self.settings.hold_fade_key = preserve_hold_fade_key
                self.settings.hold_fade_keys = list(preserve_hold_fade_keys)
            except Exception:
                pass

            try:
                self.randomize_hotkey_checkbox.blockSignals(True)
                self.randomize_hotkey_checkbox.setChecked(preserve_randomize_hotkey)
            except Exception:
                pass
            finally:
                try:
                    self.randomize_hotkey_checkbox.blockSignals(False)
                except Exception:
                    pass

            try:
                self.hold_fade_checkbox.blockSignals(True)
                self.hold_fade_checkbox.setChecked(preserve_hold_fade_enabled)
            except Exception:
                pass
            finally:
                try:
                    self.hold_fade_checkbox.blockSignals(False)
                except Exception:
                    pass

            try:
                self.hold_fade_key_edit.setText(preserve_hold_fade_key)
            except Exception:
                pass

            self._persist_and_render()
            return

        chaos = bool(random.random() < 0.35)
        if not chaos:
            self.settings.global_scale = int(random.randint(60, 180))
            self.settings.length = int(random.randint(10, 220))
            self.settings.thickness = int(random.randint(1, 18))
            self.settings.gap = int(random.randint(0, 80))
            self.settings.outline = int(random.randint(0, 10))
            self.settings.rotation = float(random.randint(0, 359))
            self.settings.offset_x = 0
            self.settings.offset_y = 0
            self.settings.line_rounding = int(random.randint(0, 40))

            self.settings.fan_enabled = bool(random.random() < 0.25)
            self.settings.fan_speed = int(random.randint(-240, 240))

            self.settings.crosshair_style = random.choice(["plus", "x"])
            self.settings.center_dot = bool(random.random() < 0.6)
            self.settings.dot_shape = random.choice(["circle", "square", "diamond"])
            self.settings.dot_size = int(random.randint(2, 20))

            self.settings.red = int(random.randint(0, 255))
            self.settings.green = int(random.randint(0, 255))
            self.settings.blue = int(random.randint(0, 255))
            self.settings.alpha = int(random.randint(120, 255))
        else:
            self.settings.global_scale = int(random.randint(25, 1000))
            self.settings.length = int(random.randint(5, 1500))
            self.settings.thickness = int(random.randint(1, 200))
            self.settings.gap = int(random.randint(0, 600))
            self.settings.outline = int(random.randint(0, 60))
            self.settings.rotation = float(random.randint(0, 359))
            self.settings.offset_x = 0
            self.settings.offset_y = 0
            self.settings.line_rounding = int(random.randint(0, 400))

            self.settings.fan_enabled = bool(random.getrandbits(1))
            self.settings.fan_speed = int(random.randint(-2000, 2000))

            self.settings.crosshair_style = random.choice(["plus", "x"])
            self.settings.center_dot = bool(random.getrandbits(1))
            self.settings.dot_shape = random.choice(["circle", "square", "diamond"])
            self.settings.dot_size = int(random.randint(2, 200))

            self.settings.red = int(random.randint(0, 255))
            self.settings.green = int(random.randint(0, 255))
            self.settings.blue = int(random.randint(0, 255))
            self.settings.alpha = int(random.randint(30, 255))

        self._refresh_presets_ui()
        self._sync_controls_from_settings()
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
        btn = QPushButton(tr_lit(text))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setCheckable(True)
        btn.setStyleSheet(self._choice_button_style(active))
        btn.setChecked(active)
        return btn

    def _choice_button_style(self, active: bool) -> str:
        base = UI_THEME["accent"] if active else UI_THEME["surface2"]
        border = UI_THEME["border_strong"] if active else UI_THEME["border"]
        return f"""
        QPushButton {{
            background-color: {base};
            color: {UI_THEME['text']};
            border: 1px solid {border};
            border-radius: 12px;
            padding: 8px 12px;
            font-weight: 600;
        }}
        QPushButton:pressed {{
            background-color: {self._adjust_color(base, 0.9)};
        }}
        """

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(tr_lit(text))
        label.setStyleSheet(f"color: {UI_THEME['muted']}; font-size: 11px; font-weight: 800;")
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

    def _color_dialog_stylesheet(self) -> str:
        # QColorDialog has a fairly complex internal widget tree; keep styling broad.
        return f"""
        QColorDialog, QColorDialog QWidget {{
            background-color: {UI_THEME['surface']};
            color: {UI_THEME['text']};
        }}
        QColorDialog QFrame, QColorDialog QScrollArea, QColorDialog QAbstractScrollArea {{
            background-color: {UI_THEME['surface']};
        }}
        QColorDialog QLabel {{
            color: {UI_THEME['text']};
        }}
        QColorDialog QGroupBox {{
            border: 1px solid {UI_THEME['border']};
            border-radius: 10px;
            margin-top: 10px;
            padding: 8px;
            background-color: {UI_THEME['surface2']};
        }}
        QColorDialog QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: {UI_THEME['muted']};
        }}
        QColorDialog QPushButton {{
            background-color: {UI_THEME['surface2']};
            color: {UI_THEME['text']};
            border: 1px solid {UI_THEME['border']};
            border-radius: 10px;
            padding: 7px 12px;
            font-weight: 700;
        }}
        QColorDialog QPushButton:hover {{
            border: 1px solid {UI_THEME['border_strong']};
            background-color: {UI_THEME['surface']};
        }}
        QColorDialog QPushButton:pressed {{
            background-color: {UI_THEME['surface2']};
        }}
        QColorDialog QLineEdit, QColorDialog QSpinBox, QColorDialog QDoubleSpinBox {{
            background-color: {UI_THEME['surface2']};
            color: {UI_THEME['text']};
            border: 1px solid {UI_THEME['border']};
            border-radius: 10px;
            padding: 4px 8px;
        }}
        QColorDialog QLineEdit:focus, QColorDialog QSpinBox:focus, QColorDialog QDoubleSpinBox:focus {{
            border: 1px solid {UI_THEME['accent']};
        }}
        QColorDialog QAbstractItemView {{
            background-color: {UI_THEME['surface']};
            color: {UI_THEME['text']};
            selection-background-color: {UI_THEME['accent']};
            selection-color: {UI_THEME['bg']};
            border: 1px solid {UI_THEME['border']};
            outline: none;
        }}
        QColorDialog QSlider::groove:horizontal {{
            border: none;
            height: 4px;
            background: rgba(230, 225, 255, 35);
            border-radius: 2px;
        }}
        QColorDialog QSlider::sub-page:horizontal {{
            background: {UI_THEME['accent']};
            border-radius: 2px;
        }}
        QColorDialog QSlider::handle:horizontal {{
            background: {UI_THEME['accent']};
            border: 1px solid {UI_THEME['border']};
            width: 12px;
            margin: -6px 0;
            border-radius: 6px;
        }}
        QColorDialog QSlider::handle:horizontal:hover {{
            border: 1px solid {UI_THEME['border_strong']};
        }}
        QColorPicker, QColorLuminancePicker {{
            border: 1px solid {UI_THEME['border']};
            border-radius: 10px;
        }}
        """

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
        dialog = QColorDialog(initial, self)
        dialog.setWindowTitle(tr_lit("Pick Crosshair Color"))
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, True)
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dialog.setStyleSheet(self._color_dialog_stylesheet())
        # QColorDialog builds most of its internal widget tree on show.
        # Apply translations a tick later so labels/buttons exist.
        try:
            apply_language_to_object_tree(dialog)
            QTimer.singleShot(0, lambda: apply_language_to_object_tree(dialog))
            QTimer.singleShot(50, lambda: apply_language_to_object_tree(dialog))
        except Exception:
            pass
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._capture_custom_palette_from_dialog()
            return
        color = dialog.currentColor()
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
        preserved_presets = dict(self.settings.presets) if isinstance(self.settings.presets, dict) else {}
        preserved_active = self.settings.active_preset if isinstance(self.settings.active_preset, str) else "Default"
        self.settings = StandardCrosshairSettings(
            visible=current_visibility,
            custom_colors=preserved_palette,
            presets=preserved_presets,
            active_preset=preserved_active,
        )
        # Reset should also clear any line builder objects.
        self.settings.line_components = {}
        self.settings.line_layers = []
        self.settings.line_profiles = {}
        # Overwrite current preset with the reset state.
        if isinstance(self.settings.presets, dict):
            self.settings.presets[self.settings.active_preset] = _settings_to_preset_dict(self.settings)
        # Close line builder so it re-opens with the new settings reference.
        if self.line_builder_dialog is not None:
            try:
                self.line_builder_dialog.close()
            except Exception:
                pass
            self.line_builder_dialog = None
        _bind_settings_to_label(self.label, self.settings)
        _sync_fan_timer_state(self.label, self.settings)
        self._sync_controls_from_settings()
        save_settings_to_disk(self.settings)

    def mousePressEvent(self, event):  # type: ignore[override]
        if getattr(self, "_embedded", False):
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if getattr(self, "_embedded", False):
            super().mouseMoveEvent(event)
            return
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
        self.square_fields: dict[str, QDoubleSpinBox] = {}
        self.triangle_fields: dict[str, QDoubleSpinBox] = {}
        self.curve_fields: dict[str, QDoubleSpinBox] = {}
        self.component_insert_buttons: list[QPushButton] = []
        self.component_modify_buttons: list[QPushButton] = []
        self.show_grid = True
        self.grid_size = 20
        self.grid_snap_enabled = True
        self.grid_diag_pos = False  # x + y = k * grid_size
        self.grid_diag_neg = False  # x - y = k * grid_size
        self.dragging_component = None
        self.drag_start_pos = None
        self.selected_component = None
        self.selection_handles = []
        self.hover_handle = None
        self.rotating = False
        self.rotation_start_angle = 0
        self.resize_mode = None
        self._last_mouse_pos_pixmap: Optional[QPointF] = None
        self._snap_guides: dict[str, float] = {}
        self._preview_pixmap_size: tuple[int, int] = (0, 0)
        self._preview_scale: float = 1.0
        self._preview_offset: tuple[float, float] = (0.0, 0.0)
        self._pending_checkpoint_key: Optional[str] = None
        self._drag_grab_delta_along: float = 0.0
        self._drag_grab_delta_perp: float = 0.0

        # Draw mode (click-drag to create objects)
        self.draw_mode_enabled: bool = False
        self.draw_mode_type: str = "curve"  # curve
        self._drawing_component: Optional[dict] = None
        self._draw_start_pos: Optional[QPointF] = None
        self._draw_start_along: float = 0.0
        self._draw_start_perp: float = 0.0
        self._draw_last_along: float = 0.0
        self._draw_last_perp: float = 0.0

        # Curve handle dragging
        self._curve_drag_handle: Optional[str] = None

        # Undo/redo history (snapshot-based)
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._history_suspended: bool = False
        self._history_group_key: Optional[str] = None
        self._history_group_timer: QTimer = QTimer(self)
        self._history_group_timer.setSingleShot(True)
        self._history_group_timer.timeout.connect(self._end_history_group)

        self.setWindowTitle(tr_lit("Advanced Line Builder"))
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(580, 440)

        self._build_ui()
        self._ensure_standard_base_objects()
        self._build_standard_list()
        self._build_custom_list()
        self._select_initial_scope()
        self._update_preview()
        self._update_history_buttons()

    def _return_to_settings(self) -> None:
        self.close()

    def closeEvent(self, event):  # type: ignore[override]
        try:
            # Only restore/focus the parent if the settings dialog is a standalone window.
            if getattr(self, "parent_dialog", None) is not None and not bool(
                getattr(self.parent_dialog, "_embedded", False)
            ):
                self.parent_dialog.show()
                self.parent_dialog.raise_()
                self.parent_dialog.activateWindow()
        except Exception:
            pass
        super().closeEvent(event)

    def _ensure_standard_base_objects(self) -> None:
        """Seed each standard line with a base segment object if empty."""
        if not isinstance(self.settings.line_components, dict):
            self.settings.line_components = {}

        profiles = self.settings.line_profiles if isinstance(self.settings.line_profiles, dict) else {}
        default_gap = float(max(0, self.settings.gap))
        default_length = float(max(0, self.settings.length))
        default_thickness = float(max(1, self.settings.thickness))

        for line_key in LINE_KEYS:
            stack = self.settings.line_components.get(line_key)
            if not isinstance(stack, list):
                stack = []
                self.settings.line_components[line_key] = stack
            if stack:
                continue

            profile = profiles.get(line_key, {}) if isinstance(profiles, dict) else {}
            use_custom = bool(profile.get("enabled", False))
            gap = float(profile.get("gap", default_gap)) if use_custom else default_gap
            length = float(profile.get("length", default_length)) if use_custom else default_length
            thickness = float(profile.get("thickness", default_thickness)) if use_custom else default_thickness
            tip = float(profile.get("tip_offset", 0.0)) if use_custom else 0.0

            stack.append(
                {
                    "type": "segment",
                    "offset": gap,
                    "perp_offset": 0.0,
                    "length": max(0.0, length),
                    "thickness": max(1.0, thickness),
                    "angle_offset": 0.0,
                    "tip_offset": tip,
                    "draggable": True,
                    "_standard_base": True,
                    "_standard_linked": True,
                }
            )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self.back_btn = QPushButton(tr_lit("← Back"))
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setToolTip(tr_lit("Return to Crosshair Settings"))
        self.back_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 10px; padding: 6px 10px; font-weight: 600; }"
            "QPushButton:hover { background-color: "
            + UI_THEME["surface"]
            + "; border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
        self.back_btn.clicked.connect(self._return_to_settings)
        top_row.addWidget(self.back_btn)
        top_row.addStretch()
        layout.addLayout(top_row)

        intro = QLabel(tr_lit("Shape stacked lines, drag their order, and preview the result instantly."))
        intro.setWordWrap(True)
        intro.setStyleSheet(
            "color: " + UI_THEME["muted"] + "; font-weight: 600; font-size: 10px;"
        )
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
            "QToolButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 6px; font-weight: 600; }"
            "QToolButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QToolButton:checked { background-color: "
            + UI_THEME["accent"]
            + "; color: "
            + UI_THEME["bg"]
            + "; border: 1px solid "
            + UI_THEME["accent"]
            + "; }"
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
            "QListWidget { background-color: "
            + UI_THEME["surface"]
            + "; border-radius: 10px; border: 1px solid "
            + UI_THEME["border"]
            + "; }"
            "QListWidget::item { padding: 6px 8px; color: "
            + UI_THEME["text"]
            + "; }"
            "QListWidget::item:selected { background-color: "
            + UI_THEME["accent"]
            + "; color: "
            + UI_THEME["bg"]
            + "; border-radius: 8px; }"
        )
        self.standard_list.setMaximumHeight(120)
        self.standard_list.currentRowChanged.connect(self._on_standard_selection_changed)
        left_panel.addWidget(self.standard_list)

        std_hint = QLabel(tr_lit("Standard lines still respect the toggles above; builder layers optional geometry on top."))
        std_hint.setWordWrap(True)
        std_hint.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 9px;")
        std_hint.setVisible(False)
        left_panel.addWidget(std_hint)

        custom_header = QWidget()
        custom_header_layout = QHBoxLayout(custom_header)
        custom_header_layout.setContentsMargins(0, 0, 0, 0)
        custom_header_layout.setSpacing(6)
        custom_header_layout.addWidget(self._subheading("Custom Lines"))
        custom_header_layout.addStretch()

        def make_header_btn(text: str, bg: str, tooltip: str) -> QPushButton:
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(22)
            btn.setMinimumWidth(28)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {bg}; color: {UI_THEME['text']}; border: 1px solid {UI_THEME['border']}; border-radius: 8px; padding: 2px 8px; font-weight: 700; }}"
                f"QPushButton:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}"
                "QPushButton:disabled { background-color: rgba(120,120,140,60); color: rgba(255,255,255,120); border: 1px solid rgba(230,225,255,30); }"
            )
            return btn

        self.add_line_btn = make_header_btn("＋", UI_THEME["accent"], "Add a custom line")
        self.add_line_btn.clicked.connect(self._on_add_custom_line)
        custom_header_layout.addWidget(self.add_line_btn)

        self.duplicate_line_btn = make_header_btn(
            "⧉", UI_THEME["surface2"], "Duplicate selected custom line"
        )
        self.duplicate_line_btn.clicked.connect(self._on_duplicate_custom_line)
        custom_header_layout.addWidget(self.duplicate_line_btn)

        self.remove_line_btn = make_header_btn("✖", UI_THEME["danger"], "Remove selected custom line")
        self.remove_line_btn.clicked.connect(self._on_remove_custom_line)
        custom_header_layout.addWidget(self.remove_line_btn)

        left_panel.addWidget(custom_header)
        self.custom_list = QListWidget()
        self.custom_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.custom_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.custom_list.setStyleSheet(
            "QListWidget { background-color: "
            + UI_THEME["surface"]
            + "; border-radius: 10px; border: 1px solid "
            + UI_THEME["border"]
            + "; }"
            "QListWidget::item { padding: 6px 8px; color: "
            + UI_THEME["text"]
            + "; }"
            "QListWidget::item:selected { background-color: "
            + UI_THEME["accent"]
            + "; color: "
            + UI_THEME["bg"]
            + "; border-radius: 8px; }"
        )
        self.custom_list.model().rowsMoved.connect(self._on_custom_rows_moved)
        self.custom_list.currentRowChanged.connect(self._on_custom_selection_changed)
        left_panel.addWidget(self.custom_list, 1)

        custom_hint = QLabel(tr_lit("Drag custom lines to reorder draw priority or stack multiple spokes at once."))
        custom_hint.setWordWrap(True)
        custom_hint.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 9px;")
        custom_hint.setVisible(False)
        left_panel.addWidget(custom_hint)

        # Show all objects (segments/circles) for the current line scope.
        left_panel.addWidget(self._subheading("Objects"))
        self.components_list = QListWidget()
        self.components_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.components_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.components_list.setStyleSheet(
            "QListWidget { background-color: "
            + UI_THEME["surface"]
            + "; border-radius: 10px; border: 1px solid "
            + UI_THEME["border"]
            + "; }"
            "QListWidget::item { padding: 6px 8px; color: "
            + UI_THEME["text"]
            + "; }"
            "QListWidget::item:selected { background-color: "
            + UI_THEME["accent"]
            + "; color: "
            + UI_THEME["bg"]
            + "; border-radius: 8px; }"
        )
        self.components_list.currentRowChanged.connect(self._on_component_selection_changed)
        self.components_list.model().rowsMoved.connect(self._on_component_rows_moved)
        left_panel.addWidget(self.components_list, 1)

        # (Buttons moved into the Custom Lines header.)

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
        label.setStyleSheet(
            "color: " + UI_THEME["text"] + "; font-weight: 700; font-size: 11px;"
        )
        return label

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        try:
            apply_language_to_object_tree(self)
        except Exception:
            pass

    def _toggle_left_panel(self, visible: bool) -> None:
        self.left_panel.setVisible(visible)
        self.left_panel_toggle.setText("◀" if visible else "▶")

    def _create_preview_card(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: "
            + UI_THEME["surface"]
            + "; border-radius: 12px; border: 1px solid "
            + UI_THEME["border"]
            + "; padding: 6px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setSpacing(3)
        
        header_row = QHBoxLayout()
        header_row.addWidget(self._subheading("Live Preview"))
        
        self.grid_toggle = QCheckBox()
        self.grid_toggle.setChecked(self.show_grid)
        self.grid_toggle.setStyleSheet(
            "QCheckBox { color: " + UI_THEME["text"] + "; font-size: 10px; font-weight: 600; }"
            "QCheckBox::indicator { width: 14px; height: 14px; }"
        )
        self.grid_toggle.toggled.connect(self._on_grid_toggle)
        header_row.addWidget(self.grid_toggle)
        
        self.snap_toggle = QCheckBox(tr_lit("⚲ Snap"))
        self.snap_toggle.setChecked(self.grid_snap_enabled)
        self.snap_toggle.setStyleSheet(
            "QCheckBox { color: " + UI_THEME["text"] + "; font-size: 11px; font-weight: 600; }"
            "QCheckBox::indicator { width: 14px; height: 14px; }"
        )
        self.snap_toggle.toggled.connect(self._on_snap_toggle)
        header_row.addWidget(self.snap_toggle)

        # Diagonal grid toggles (optional overlay, uses the same grid size).
        self.diag_pos_toggle = QCheckBox("/\\")
        self.diag_pos_toggle.setToolTip("Diagonal grid: x + y")
        self.diag_pos_toggle.setChecked(self.grid_diag_pos)
        self.diag_pos_toggle.setStyleSheet(self.snap_toggle.styleSheet())
        self.diag_pos_toggle.toggled.connect(self._on_diag_pos_toggle)
        header_row.addWidget(self.diag_pos_toggle)

        self.diag_neg_toggle = QCheckBox("\\/")
        self.diag_neg_toggle.setToolTip("Diagonal grid: x - y")
        self.diag_neg_toggle.setChecked(self.grid_diag_neg)
        self.diag_neg_toggle.setStyleSheet(self.snap_toggle.styleSheet())
        self.diag_neg_toggle.toggled.connect(self._on_diag_neg_toggle)
        header_row.addWidget(self.diag_neg_toggle)
        
        grid_size_wrapper = QWidget()
        grid_size_layout = QHBoxLayout(grid_size_wrapper)
        grid_size_layout.setContentsMargins(0, 0, 0, 0)
        grid_size_layout.setSpacing(5)
        
        grid_size_label = QLabel(tr_lit("Grid Size"))
        grid_size_label.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 12px;")
        grid_size_layout.addWidget(grid_size_label)
        
        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(5, 100)
        self.grid_size_spin.setValue(self.grid_size)
        self.grid_size_spin.setFixedWidth(50)
        self.grid_size_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.grid_size_spin.setStyleSheet(
            "QSpinBox { background-color: "
            + UI_THEME["surface2"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 2px 6px; color: "
            + UI_THEME["text"]
            + "; }"
            "QSpinBox:focus { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
        self.grid_size_spin.valueChanged.connect(self._on_grid_size_changed)
        grid_size_layout.addWidget(self.grid_size_spin)
        
        px_label = QLabel("px")
        px_label.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 10px;")
        grid_size_layout.addWidget(px_label)
    
        header_row.addWidget(grid_size_wrapper)
        header_row.addStretch()
        
        layout.addLayout(header_row)
        
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(200, 200)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "QLabel { background-color: "
            + UI_THEME["bg"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 12px; }"
        )
        self.preview_label.mousePressEvent = self._preview_mouse_press
        self.preview_label.mouseMoveEvent = self._preview_mouse_move
        self.preview_label.mouseReleaseEvent = self._preview_mouse_release
        layout.addWidget(self.preview_label)

        return frame

    def _create_metadata_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: "
            + UI_THEME["surface"]
            + "; border-radius: 12px; border: 1px solid "
            + UI_THEME["border"]
            + "; padding: 8px; }"
        )
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setMinimumHeight(200)
        scroll_area.setMaximumHeight(400)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setSpacing(4)

        self.layer_label_input = QLineEdit()
        self.layer_label_input.setPlaceholderText("Layer name")
        self.layer_label_input.textChanged.connect(self._on_layer_label_changed)
        form.addRow("Label", self.layer_label_input)

        self.layer_enabled_check = QCheckBox(tr_lit("Visible"))
        self.layer_enabled_check.toggled.connect(self._on_layer_enabled_toggled)
        form.addRow("", self.layer_enabled_check)

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

        scroll_layout.addWidget(form_widget)

        # Selected object options live here (clearer, close to metadata).
        scroll_layout.addWidget(self._subheading("Selected Object"))

        self.component_editor_stack = QStackedWidget()
        placeholder = QLabel(tr_lit("Select an object to edit it."))
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: " + UI_THEME["muted"] + ";")
        self.component_editor_stack.addWidget(placeholder)

        segment_editor = QWidget()
        segment_form = QFormLayout(segment_editor)
        segment_form.setSpacing(4)

        self.segment_draggable = QCheckBox(tr_lit("Draggable"))
        self.segment_draggable.setStyleSheet(
            "QCheckBox { color: " + UI_THEME["text"] + "; font-weight: 600; }"
        )
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

        self.circle_draggable = QCheckBox(tr_lit("Draggable"))
        self.circle_draggable.setStyleSheet(
            "QCheckBox { color: " + UI_THEME["text"] + "; font-weight: 600; }"
        )
        self.circle_draggable.toggled.connect(lambda v: self._on_component_draggable_changed("circle", v))
        circle_form.addRow("", self.circle_draggable)

        for field in ("offset", "perp_offset", "radius"):
            spin = self._create_component_spinbox("circle", field)
            self.circle_fields[field] = spin
            circle_form.addRow(self._component_label(field), self._wrap_with_unit(spin, COMPONENT_FIELD_LIMITS["circle"][field][2]))
        self.component_editor_stack.addWidget(circle_editor)

        square_editor = QWidget()
        square_form = QFormLayout(square_editor)
        square_form.setSpacing(4)

        self.square_draggable = QCheckBox(tr_lit("Draggable"))
        self.square_draggable.setStyleSheet(
            "QCheckBox { color: " + UI_THEME["text"] + "; font-weight: 600; }"
        )
        self.square_draggable.toggled.connect(lambda v: self._on_component_draggable_changed("square", v))
        square_form.addRow("", self.square_draggable)

        for field in ("offset", "perp_offset", "size", "angle_offset"):
            spin = self._create_component_spinbox("square", field)
            self.square_fields[field] = spin
            square_form.addRow(self._component_label(field), self._wrap_with_unit(spin, COMPONENT_FIELD_LIMITS["square"][field][2]))
        self.component_editor_stack.addWidget(square_editor)

        triangle_editor = QWidget()
        triangle_form = QFormLayout(triangle_editor)
        triangle_form.setSpacing(4)

        self.triangle_draggable = QCheckBox(tr_lit("Draggable"))
        self.triangle_draggable.setStyleSheet(
            "QCheckBox { color: " + UI_THEME["text"] + "; font-weight: 600; }"
        )
        self.triangle_draggable.toggled.connect(lambda v: self._on_component_draggable_changed("triangle", v))
        triangle_form.addRow("", self.triangle_draggable)

        for field in ("offset", "perp_offset", "radius", "angle_offset"):
            spin = self._create_component_spinbox("triangle", field)
            self.triangle_fields[field] = spin
            triangle_form.addRow(self._component_label(field), self._wrap_with_unit(spin, COMPONENT_FIELD_LIMITS["triangle"][field][2]))
        self.component_editor_stack.addWidget(triangle_editor)

        curve_editor = QWidget()
        curve_form = QFormLayout(curve_editor)
        curve_form.setSpacing(4)

        self.curve_draggable = QCheckBox(tr_lit("Draggable"))
        self.curve_draggable.setStyleSheet(
            "QCheckBox { color: " + UI_THEME["text"] + "; font-weight: 600; }"
        )
        self.curve_draggable.toggled.connect(lambda v: self._on_component_draggable_changed("curve", v))
        curve_form.addRow("", self.curve_draggable)

        # Keep curve point editing on-canvas; only expose basic transforms here.
        for field in ("offset", "perp_offset", "thickness", "angle_offset"):
            spin = self._create_component_spinbox("curve", field)
            self.curve_fields[field] = spin
            curve_form.addRow(self._component_label(field), self._wrap_with_unit(spin, COMPONENT_FIELD_LIMITS["curve"][field][2]))
        self.component_editor_stack.addWidget(curve_editor)

        scroll_layout.addWidget(self.component_editor_stack)

        scroll_area.setWidget(scroll_widget)
        
        wrapper_layout = QVBoxLayout(frame)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(scroll_area)
        
        self._set_metadata_enabled(False)
        return frame

    def _create_component_panel(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background-color: "
            + UI_THEME["surface"]
            + "; border-radius: 12px; border: 1px solid "
            + UI_THEME["border"]
            + "; padding: 6px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setSpacing(6)
        layout.addWidget(self._subheading("Selected Object"))

        # Tools: add objects + switch shape + duplicate/delete.
        tools_row = QHBoxLayout()
        tools_row.setSpacing(6)

        self.quick_add_segment_btn = QPushButton("＋ Line")
        self.quick_add_segment_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_add_segment_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 8px; font-weight: 600; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
        self.quick_add_segment_btn.clicked.connect(lambda: self._add_component("segment", self._last_mouse_pos_pixmap))
        tools_row.addWidget(self.quick_add_segment_btn)

        self.quick_add_circle_btn = QPushButton("＋ Circle")
        self.quick_add_circle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_add_circle_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 8px; font-weight: 600; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
        self.quick_add_circle_btn.clicked.connect(lambda: self._add_component("circle", self._last_mouse_pos_pixmap))
        tools_row.addWidget(self.quick_add_circle_btn)

        self.quick_add_square_btn = QPushButton("＋ Square")
        self.quick_add_square_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_add_square_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 8px; font-weight: 600; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
        self.quick_add_square_btn.clicked.connect(lambda: self._add_component("square", self._last_mouse_pos_pixmap))
        tools_row.addWidget(self.quick_add_square_btn)

        self.quick_add_triangle_btn = QPushButton("＋ Triangle")
        self.quick_add_triangle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_add_triangle_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 8px; font-weight: 600; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
        self.quick_add_triangle_btn.clicked.connect(lambda: self._add_component("triangle", self._last_mouse_pos_pixmap))
        tools_row.addWidget(self.quick_add_triangle_btn)

        self.draw_toggle = QToolButton()
        self.draw_toggle.setText("✎ Draw")
        self.draw_toggle.setCheckable(True)
        self.draw_toggle.setToolTip("Click-drag on the canvas to draw a new object")
        self.draw_toggle.setStyleSheet(
            "QToolButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 8px; font-weight: 700; }"
            "QToolButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QToolButton:checked { background-color: "
            + UI_THEME["accent"]
            + "; color: "
            + UI_THEME["bg"]
            + "; border: 1px solid "
            + UI_THEME["accent"]
            + "; }"
        )
        self.draw_toggle.toggled.connect(self._on_draw_mode_toggled)
        tools_row.addWidget(self.draw_toggle)

        tools_row.addStretch()

        self.quick_duplicate_btn = QPushButton("⧉")
        self.quick_duplicate_btn.setToolTip("Duplicate selected object")
        self.quick_duplicate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_duplicate_btn.setFixedWidth(34)
        self.quick_duplicate_btn.setEnabled(False)
        self.quick_duplicate_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 6px; font-weight: 700; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QPushButton:disabled { background-color: rgba(120,120,140,60); color: rgba(255,255,255,120); border: 1px solid rgba(230,225,255,30); }"
        )
        self.quick_duplicate_btn.clicked.connect(self._duplicate_component)
        tools_row.addWidget(self.quick_duplicate_btn)

        self.quick_delete_btn = QPushButton("✖")
        self.quick_delete_btn.setToolTip("Delete selected object")
        self.quick_delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_delete_btn.setFixedWidth(34)
        self.quick_delete_btn.setEnabled(False)
        self.quick_delete_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["danger"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["danger"]
            + "; border-radius: 8px; padding: 3px 6px; font-weight: 800; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QPushButton:disabled { background-color: rgba(200,75,106,80); color: rgba(255,255,255,120); border: 1px solid rgba(200,75,106,80); }"
        )
        self.quick_delete_btn.clicked.connect(self._remove_component)
        tools_row.addWidget(self.quick_delete_btn)

        self.undo_btn = QPushButton("↶")
        self.undo_btn.setToolTip("Undo (Ctrl+Z)")
        self.undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_btn.setFixedWidth(34)
        self.undo_btn.setEnabled(False)
        self.undo_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 6px; font-weight: 800; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QPushButton:disabled { background-color: rgba(120,120,140,60); color: rgba(255,255,255,120); border: 1px solid rgba(230,225,255,30); }"
        )
        self.undo_btn.clicked.connect(self._undo)
        tools_row.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("↷")
        self.redo_btn.setToolTip("Redo (Ctrl+Y)")
        self.redo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.redo_btn.setFixedWidth(34)
        self.redo_btn.setEnabled(False)
        self.redo_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 6px; font-weight: 800; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QPushButton:disabled { background-color: rgba(120,120,140,60); color: rgba(255,255,255,120); border: 1px solid rgba(230,225,255,30); }"
        )
        self.redo_btn.clicked.connect(self._redo)
        tools_row.addWidget(self.redo_btn)

        layout.addLayout(tools_row)

        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._redo)

        hint = QLabel("Select an object on the canvas (or in the left list) to edit its properties in Metadata.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 9px;")
        layout.addWidget(hint)

        # No visible insert/modify buttons (use left list + tools row).
        self.component_insert_buttons = []
        self.component_modify_buttons = []
        return frame

    def _make_spin(self, minimum: float, maximum: float, step: float, decimals: int = 1) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setAccelerated(True)
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        spin.setStyleSheet(
            "QDoubleSpinBox { background-color: "
            + UI_THEME["surface2"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 8px; padding: 3px 8px; color: "
            + UI_THEME["text"]
            + "; min-width: 70px; }"
            "QDoubleSpinBox:focus { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
        return spin

    def _component_label(self, field: str) -> QLabel:
        label_map = {
            "perp_offset": "Perp Offset"
        }
        text = label_map.get(field, field.replace("_", " ").title())
        label = QLabel(text)
        label.setStyleSheet(
            "color: " + UI_THEME["muted"] + "; font-size: 11px; font-weight: 700;"
        )
        return label

    def _wrap_with_unit(self, widget: QDoubleSpinBox, unit: str) -> QWidget:
        wrapper = QHBoxLayoutWidget()
        inner = wrapper.layout()
        inner.addWidget(widget)
        if unit:
            unit_label = QLabel(unit)
            unit_label.setStyleSheet("color: " + UI_THEME["muted"] + "; padding-left: 4px;")
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
        label = str(LINE_LABELS.get(line_key, line_key.title()))
        return f"{tr_lit(label)} ({count} {tr_lit('objects')})"

    def _custom_layer_summary(self, layer: dict) -> str:
        label = str(layer.get("label") or "Custom Line")
        angle = float(layer.get("angle", 0.0))
        status = "ON" if layer.get("enabled", True) else "OFF"
        components = layer.get("components", []) if isinstance(layer.get("components"), list) else []
        count = len(components) if isinstance(components, list) else 0
        return f"[{status}] {label} • {angle:.0f}° ({count} {tr_lit('objects')})"

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
        else:
            self._set_metadata_enabled(False)
            self.layer_label_input.blockSignals(True)
            self.layer_label_input.setText("")
            self.layer_label_input.blockSignals(False)
            self.layer_enabled_check.blockSignals(True)
            self.layer_enabled_check.setChecked(True)
            self.layer_enabled_check.blockSignals(False)

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
        prev_selected = self.selected_component
        self.components_list.blockSignals(True)
        self.components_list.clear()
        stack = self._current_component_stack()
        if stack:
            for component in stack:
                item = QListWidgetItem(self._component_summary(component))
                item.setData(Qt.ItemDataRole.UserRole, component)
                self.components_list.addItem(item)
        self.components_list.blockSignals(False)

        # Preserve selection if possible; otherwise don't auto-select anything.
        if prev_selected is not None and stack and prev_selected in stack:
            self.selected_component = prev_selected
            self._select_component_row_for(prev_selected)
            self._set_component_editor_state(prev_selected)
            if hasattr(self, "quick_duplicate_btn"):
                self.quick_duplicate_btn.setEnabled(True)
            if hasattr(self, "quick_delete_btn"):
                self.quick_delete_btn.setEnabled(True)
        else:
            self.selected_component = None
            self.components_list.clearSelection()
            self._set_component_editor_state(None)
            if hasattr(self, "quick_duplicate_btn"):
                self.quick_duplicate_btn.setEnabled(False)
            if hasattr(self, "quick_delete_btn"):
                self.quick_delete_btn.setEnabled(False)

        has_layer = stack is not None
        self._component_buttons_enabled(has_layer, self.components_list.currentRow() >= 0)

    def _component_summary(self, component: dict) -> str:
        ctype = component.get("type")
        if ctype == "segment":
            return f"{tr_lit('Line')} • {tr_lit('offset')}={{:.1f}}px {tr_lit('length')}={{:.1f}}px".format(
                component.get("offset", 0.0),
                component.get("length", 0.0),
            )
        if ctype == "circle":
            return f"{tr_lit('Circle')} • {tr_lit('offset')}={{:.1f}}px {tr_lit('radius')}={{:.1f}}px".format(
                component.get("offset", 0.0),
                component.get("radius", 0.0),
            )
        if ctype in ("polygon", "triangle"):
            return f"{tr_lit('Triangle')} • r={{:.1f}}px".format(float(component.get("radius", 0.0)))
        if ctype == "square":
            return f"{tr_lit('Square')} • {tr_lit('size')}={{:.1f}}px".format(float(component.get("size", 0.0)))
        if ctype == "curve":
            pts = component.get("points")
            if isinstance(pts, list) and len(pts) >= 2:
                return f"{tr_lit('Curve')} • {tr_lit('pts')}={{}} {tr_lit('thickness')}={{:.1f}}px".format(
                    len(pts), float(component.get("thickness", 0.0))
                )
            return f"{tr_lit('Curve')} • {tr_lit('thickness')}={{:.1f}}px".format(float(component.get("thickness", 0.0)))
        return tr_lit("Unknown object")

    def retranslate_dynamic_texts(self) -> None:
        try:
            apply_language_to_object_tree(self)
        except Exception:
            pass
        try:
            self._build_standard_list()
        except Exception:
            pass
        try:
            self._build_custom_list(selected_id=self.active_scope_id if self.active_scope_kind == "custom" else None)
        except Exception:
            pass
        try:
            self._refresh_component_list()
        except Exception:
            pass
        try:
            self._update_layer_metadata_view()
        except Exception:
            pass

    def _on_component_selection_changed(self, row: int) -> None:
        stack = self._current_component_stack()
        if stack and 0 <= row < len(stack):
            component = stack[row]
            self._set_component_editor_state(component)
            self.selected_component = component
            if hasattr(self, "quick_duplicate_btn"):
                self.quick_duplicate_btn.setEnabled(True)
            if hasattr(self, "quick_delete_btn"):
                self.quick_delete_btn.setEnabled(True)
            if hasattr(self, "selected_shape_combo"):
                self.selected_shape_combo.blockSignals(True)
                self.selected_shape_combo.setEnabled(True)
                ctype = component.get("type")
                if ctype == "segment":
                    self.selected_shape_combo.setCurrentIndex(0)
                elif ctype == "circle":
                    self.selected_shape_combo.setCurrentIndex(1)
                elif ctype == "square":
                    self.selected_shape_combo.setCurrentIndex(2)
                elif ctype in ("triangle", "polygon"):
                    self.selected_shape_combo.setCurrentIndex(3)
                else:  # curve
                    self.selected_shape_combo.setCurrentIndex(4)
                self.selected_shape_combo.blockSignals(False)
            self._component_buttons_enabled(True, True)
        else:
            self._set_component_editor_state(None)
            self.selected_component = None
            if hasattr(self, "quick_duplicate_btn"):
                self.quick_duplicate_btn.setEnabled(False)
            if hasattr(self, "quick_delete_btn"):
                self.quick_delete_btn.setEnabled(False)
            if hasattr(self, "selected_shape_combo"):
                self.selected_shape_combo.blockSignals(True)
                self.selected_shape_combo.setEnabled(False)
                self.selected_shape_combo.setCurrentIndex(0)
                self.selected_shape_combo.blockSignals(False)
            self._component_buttons_enabled(stack is not None, False)

    def _set_component_editor_state(self, component: Optional[dict]) -> None:
        if component is None:
            self.component_editor_stack.setCurrentIndex(0)
            return
        ctype = component.get("type")
        if ctype == "segment":
            self.component_editor_stack.setCurrentIndex(1)
            self.segment_draggable.blockSignals(True)
            self.segment_draggable.setChecked(component.get("draggable", True))
            self.segment_draggable.blockSignals(False)
            for field, spin in self.segment_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        elif ctype == "circle":
            self.component_editor_stack.setCurrentIndex(2)
            self.circle_draggable.blockSignals(True)
            self.circle_draggable.setChecked(component.get("draggable", True))
            self.circle_draggable.blockSignals(False)
            for field, spin in self.circle_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        elif ctype == "square":
            self.component_editor_stack.setCurrentIndex(3)
            self.square_draggable.blockSignals(True)
            self.square_draggable.setChecked(component.get("draggable", True))
            self.square_draggable.blockSignals(False)
            for field, spin in self.square_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        elif ctype in ("triangle", "polygon"):
            self.component_editor_stack.setCurrentIndex(4)
            self.triangle_draggable.blockSignals(True)
            self.triangle_draggable.setChecked(component.get("draggable", True))
            self.triangle_draggable.blockSignals(False)
            for field, spin in self.triangle_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        elif ctype == "curve":
            self.component_editor_stack.setCurrentIndex(5)
            self.curve_draggable.blockSignals(True)
            self.curve_draggable.setChecked(component.get("draggable", True))
            self.curve_draggable.blockSignals(False)
            for field, spin in self.curve_fields.items():
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
        elif ctype == "square":
            for field, spin in self.square_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        elif ctype in ("triangle", "polygon"):
            for field, spin in self.triangle_fields.items():
                spin.blockSignals(True)
                spin.setValue(float(component.get(field, 0.0)))
                spin.blockSignals(False)
        elif ctype == "curve":
            for field, spin in self.curve_fields.items():
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
            self._checkpoint(f"component:{row}:{field}")
            component = stack[row]
            if isinstance(component, dict) and component.get("_standard_base") and component.get("_standard_linked", True):
                if field in ("offset", "length", "thickness", "tip_offset", "perp_offset"):
                    component["_standard_linked"] = False
            stack[row][field] = value
            self.components_list.item(row).setText(self._component_summary(stack[row]))
            self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _add_component(self, comp_type: str, pos: Optional[QPointF] = None) -> None:
        stack = self._current_component_stack()
        if comp_type not in COMPONENT_TYPES or stack is None:
            return
        self._checkpoint("add_component")
        component = {"type": comp_type, **self._default_component_values(comp_type)}

        # Add at cursor (like dropping an element onto the canvas).
        if isinstance(pos, QPointF):
            import math

            w, h = self._preview_pixmap_size if isinstance(getattr(self, "_preview_pixmap_size", None), tuple) else (240, 240)
            center_x = int(w) // 2
            center_y = int(h) // 2
            x_rel = float(pos.x()) - float(center_x)
            y_rel = float(pos.y()) - float(center_y)

            base_angle, layer_angle_offset = self._current_line_angles()
            angle_rad = math.radians(base_angle + layer_angle_offset)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)

            # Screen-space (x,y) -> (along, perp)
            anchor_along = x_rel * cos_a + y_rel * sin_a
            perp = -x_rel * sin_a + y_rel * cos_a

            if comp_type == "segment":
                length = float(component.get("length", 40.0))
                component["offset"] = float(anchor_along) - (length / 2.0)
            else:
                component["offset"] = float(anchor_along)
            component["perp_offset"] = float(perp)
        stack.append(component)
        item = QListWidgetItem(self._component_summary(component))
        item.setData(Qt.ItemDataRole.UserRole, component)
        self.components_list.addItem(item)
        self.components_list.setCurrentRow(self.components_list.count() - 1)
        self.selected_component = component
        if hasattr(self, "quick_duplicate_btn"):
            self.quick_duplicate_btn.setEnabled(True)
        if hasattr(self, "quick_delete_btn"):
            self.quick_delete_btn.setEnabled(True)
        self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _remove_component(self) -> None:
        stack = self._current_component_stack()
        row = self.components_list.currentRow()
        if stack is None or row < 0 or row >= len(stack):
            return
        self._checkpoint("remove_component")
        stack.pop(row)
        self.components_list.takeItem(row)
        next_row = min(row, self.components_list.count() - 1)
        if next_row >= 0:
            self.components_list.setCurrentRow(next_row)
        else:
            # Ensure selection state is fully cleared.
            self.components_list.setCurrentRow(-1)
            self.components_list.clearSelection()
            self.selected_component = None
            self._set_component_editor_state(None)
            if hasattr(self, "quick_duplicate_btn"):
                self.quick_duplicate_btn.setEnabled(False)
            if hasattr(self, "quick_delete_btn"):
                self.quick_delete_btn.setEnabled(False)
            self._component_buttons_enabled(stack is not None, False)
        self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _duplicate_component(self) -> None:
        stack = self._current_component_stack()
        row = self.components_list.currentRow()
        if stack is None or row < 0 or row >= len(stack):
            return
        self._checkpoint("duplicate_component")
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
        self._checkpoint("reorder_components")
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
                "perp_offset": 0.0,
                "length": 40.0,
                "thickness": 6.0,
                "angle_offset": 0.0,
                "tip_offset": 0.0,
                "draggable": True,
            }
        if comp_type == "circle":
            return {
                "offset": 20.0,
                "perp_offset": 0.0,
                "radius": 6.0,
                "draggable": True,
            }
        if comp_type == "square":
            return {
                "offset": 20.0,
                "perp_offset": 0.0,
                "size": 18.0,
                "angle_offset": 0.0,
                "draggable": True,
            }
        if comp_type == "triangle":
            return {
                "offset": 20.0,
                "perp_offset": 0.0,
                "radius": 12.0,
                "angle_offset": 0.0,
                "draggable": True,
            }
        if comp_type == "curve":
            return {
                "offset": 0.0,
                "perp_offset": 0.0,
                "thickness": float(max(1, getattr(self.settings, "thickness", 6))),
                "angle_offset": 0.0,
                "start_dx": -20.0,
                "start_dy": 0.0,
                "ctrl_dx": 0.0,
                "ctrl_dy": 0.0,
                "end_dx": 20.0,
                "end_dy": 0.0,
                "draggable": True,
            }
        return {}

    def _select_component_row_for(self, component: dict) -> None:
        stack = self._current_component_stack()
        if not stack:
            return
        try:
            index = stack.index(component)
        except ValueError:
            # Fallback: try to match by identity in case of duplicates.
            index = -1
            for i, c in enumerate(stack):
                if c is component:
                    index = i
                    break
        if index >= 0 and self.components_list.currentRow() != index:
            self.components_list.setCurrentRow(index)

    def _hit_test_component(self, pos: QPointF) -> Optional[dict]:
        import math

        stack = self._current_component_stack()
        if not stack:
            return None

        base_angle, angle_offset = self._current_line_angles()
        line_angle = base_angle + angle_offset
        line_rad = math.radians(line_angle)
        w, h = self._preview_pixmap_size if isinstance(getattr(self, "_preview_pixmap_size", None), tuple) else (240, 240)
        center_x = int(w) // 2
        center_y = int(h) // 2

        # Iterate topmost first (last drawn)
        padding = 8.0
        for component in reversed(stack):
            ctype = component.get("type")
            offset = float(component.get("offset", 0.0))
            perp_offset = float(component.get("perp_offset", 0.0))

            if ctype == "segment":
                length = float(component.get("length", 0.0))
                thickness = float(component.get("thickness", 1.0))
                anchor_offset = offset + (length / 2.0)
                comp_x = center_x + anchor_offset * math.cos(line_rad) - perp_offset * math.sin(line_rad)
                comp_y = center_y + anchor_offset * math.sin(line_rad) + perp_offset * math.cos(line_rad)

                orient_angle = line_angle + float(component.get("angle_offset", 0.0))
                orient_rad = math.radians(orient_angle)
                cos_a = math.cos(orient_rad)
                sin_a = math.sin(orient_rad)
                dx = float(pos.x()) - comp_x
                dy = float(pos.y()) - comp_y
                local_x = dx * cos_a + dy * sin_a
                local_y = -dx * sin_a + dy * cos_a
                if abs(local_x) <= (length / 2.0 + padding) and abs(local_y) <= (thickness / 2.0 + padding):
                    return component

            elif ctype == "circle":
                radius = float(component.get("radius", 0.0))
                anchor_offset = offset
                comp_x = center_x + anchor_offset * math.cos(line_rad) - perp_offset * math.sin(line_rad)
                comp_y = center_y + anchor_offset * math.sin(line_rad) + perp_offset * math.cos(line_rad)
                dx = float(pos.x()) - comp_x
                dy = float(pos.y()) - comp_y
                if dx * dx + dy * dy <= (radius + padding) * (radius + padding):
                    return component

            elif ctype == "polygon":
                # Legacy polygons treated as triangles (radius-based hit test).
                radius = float(component.get("radius", 0.0))
                anchor_offset = offset
                comp_x = center_x + anchor_offset * math.cos(line_rad) - perp_offset * math.sin(line_rad)
                comp_y = center_y + anchor_offset * math.sin(line_rad) + perp_offset * math.cos(line_rad)
                dx = float(pos.x()) - comp_x
                dy = float(pos.y()) - comp_y
                if dx * dx + dy * dy <= (radius + padding) * (radius + padding):
                    return component

            elif ctype == "triangle":
                radius = float(component.get("radius", 0.0))
                anchor_offset = offset
                comp_x = center_x + anchor_offset * math.cos(line_rad) - perp_offset * math.sin(line_rad)
                comp_y = center_y + anchor_offset * math.sin(line_rad) + perp_offset * math.cos(line_rad)
                dx = float(pos.x()) - comp_x
                dy = float(pos.y()) - comp_y
                if dx * dx + dy * dy <= (radius + padding) * (radius + padding):
                    return component

            elif ctype == "square":
                size = float(component.get("size", 0.0))
                anchor_offset = offset
                comp_x = center_x + anchor_offset * math.cos(line_rad) - perp_offset * math.sin(line_rad)
                comp_y = center_y + anchor_offset * math.sin(line_rad) + perp_offset * math.cos(line_rad)
                dx = float(pos.x()) - comp_x
                dy = float(pos.y()) - comp_y
                # Approximate hit test using bounding circle.
                radius = (size * 0.7071) if size > 0 else 0.0
                if dx * dx + dy * dy <= (radius + padding) * (radius + padding):
                    return component

            elif ctype == "curve":
                thickness = float(component.get("thickness", 3.0))
                threshold = max(padding, (thickness / 2.0) + 6.0)
                threshold2 = threshold * threshold

                raw_pts = component.get("points")
                if isinstance(raw_pts, list) and len(raw_pts) >= 2:
                    offset = float(component.get("offset", 0.0))
                    perp_offset = float(component.get("perp_offset", 0.0))
                    poly: list[QPointF] = []
                    for p in raw_pts:
                        if not (isinstance(p, (list, tuple)) and len(p) == 2):
                            continue
                        if not (isinstance(p[0], (int, float)) and isinstance(p[1], (int, float))):
                            continue
                        poly.append(self._line_coords_to_pixmap(offset + float(p[0]), perp_offset + float(p[1])))
                    for i in range(1, len(poly)):
                        a = poly[i - 1]
                        b = poly[i]
                        vx = b.x() - a.x()
                        vy = b.y() - a.y()
                        wx = float(pos.x()) - a.x()
                        wy = float(pos.y()) - a.y()
                        seg_len2 = float(vx * vx + vy * vy)
                        if seg_len2 > 1e-6:
                            tproj = max(0.0, min(1.0, float((wx * vx + wy * vy) / seg_len2)))
                            proj_x = a.x() + tproj * vx
                            proj_y = a.y() + tproj * vy
                            dx = float(pos.x()) - float(proj_x)
                            dy = float(pos.y()) - float(proj_y)
                            if dx * dx + dy * dy <= threshold2:
                                return component
                else:
                    pts = self._curve_handle_points_pixmap(component)
                    p0 = pts["start"]
                    p1 = pts["ctrl"]
                    p2 = pts["end"]

                    prev = p0
                    for i in range(1, 17):
                        t = i / 16.0
                        mt = 1.0 - t
                        x = (mt * mt) * p0.x() + (2.0 * mt * t) * p1.x() + (t * t) * p2.x()
                        y = (mt * mt) * p0.y() + (2.0 * mt * t) * p1.y() + (t * t) * p2.y()
                        curr = QPointF(float(x), float(y))

                        vx = curr.x() - prev.x()
                        vy = curr.y() - prev.y()
                        wx = float(pos.x()) - prev.x()
                        wy = float(pos.y()) - prev.y()
                        seg_len2 = float(vx * vx + vy * vy)
                        if seg_len2 > 1e-6:
                            tproj = max(0.0, min(1.0, float((wx * vx + wy * vy) / seg_len2)))
                            proj_x = prev.x() + tproj * vx
                            proj_y = prev.y() + tproj * vy
                            dx = float(pos.x()) - float(proj_x)
                            dy = float(pos.y()) - float(proj_y)
                            if dx * dx + dy * dy <= threshold2:
                                return component
                        prev = curr

        return None

    def _current_scope_standard_key(self) -> Optional[str]:
        return self.active_scope_id if self.active_scope_kind == "standard" else None

    def _current_scope_custom_id(self) -> Optional[str]:
        return self.active_scope_id if self.active_scope_kind == "custom" else None

    def _current_line_angles(self) -> tuple[float, float]:
        """Return (base_angle, angle_offset) for the active scope."""
        layer = self._current_custom_layer()
        if layer:
            return float(layer.get("angle", 0.0)), float(layer.get("angle_offset", 0.0))

        style_angles = STYLE_ANGLES.get(self.settings.crosshair_style, STYLE_ANGLES["plus"])
        line_key = str(self.active_scope_id or "")
        attr = LINE_KEY_TO_ATTR.get(line_key)
        base_angle = float(style_angles.get(attr, 0.0)) if attr else 0.0
        return base_angle, 0.0

    def _on_grid_toggle(self, enabled: bool) -> None:
        self.show_grid = enabled
        self._update_preview()

    def _on_grid_size_changed(self, value: int) -> None:
        self.grid_size = value
        self._update_preview()

    def _on_snap_toggle(self, enabled: bool) -> None:
        self.grid_snap_enabled = enabled

    def _on_diag_pos_toggle(self, enabled: bool) -> None:
        self.grid_diag_pos = bool(enabled)
        self._update_preview()

    def _on_diag_neg_toggle(self, enabled: bool) -> None:
        self.grid_diag_neg = bool(enabled)
        self._update_preview()

    def _on_component_draggable_changed(self, comp_type: str, enabled: bool) -> None:
        component = self._current_component()
        if component:
            self._checkpoint("component_draggable")
            component["draggable"] = enabled
            self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())

    def _on_selected_shape_combo_changed(self, index: int) -> None:
        mapping = {
            0: "segment",
            1: "circle",
            2: "square",
            3: "triangle",
            4: "curve",
        }
        new_type = mapping.get(int(index), "segment")
        self._convert_selected_component_type(new_type)

    def _convert_selected_component_type(self, new_type: str) -> None:
        stack = self._current_component_stack()
        row = self.components_list.currentRow() if hasattr(self, "components_list") else -1
        if not stack or row < 0 or row >= len(stack):
            return

        old = stack[row]
        if not isinstance(old, dict):
            return
        if old.get("type") == new_type:
            return

        self._checkpoint("convert_shape")

        converted = {"type": new_type, **self._default_component_values(new_type)}
        converted["offset"] = float(old.get("offset", converted.get("offset", 0.0)))
        converted["perp_offset"] = float(old.get("perp_offset", converted.get("perp_offset", 0.0)))
        if "draggable" in old:
            converted["draggable"] = _coerce_bool(old.get("draggable"), default=True)
        if "_standard_base" in old:
            converted["_standard_base"] = _coerce_bool(old.get("_standard_base"), default=False)
        if "_standard_linked" in old:
            converted["_standard_linked"] = _coerce_bool(old.get("_standard_linked"), default=True)

        if new_type == "segment":
            converted["thickness"] = float(old.get("thickness", max(1.0, float(old.get("radius", 6.0)))))
            converted["angle_offset"] = float(old.get("angle_offset", 0.0))
            converted["tip_offset"] = float(old.get("tip_offset", 0.0))
        elif new_type == "circle":
            converted["radius"] = float(old.get("radius", max(1.0, float(old.get("thickness", 6.0)))))
        elif new_type == "square":
            converted["size"] = float(old.get("size", max(1.0, float(old.get("radius", 10.0)) * 2.0)))
            converted["angle_offset"] = float(old.get("angle_offset", 0.0))
        elif new_type == "triangle":
            converted["radius"] = float(old.get("radius", max(1.0, float(old.get("thickness", 6.0)))))
            converted["angle_offset"] = float(old.get("angle_offset", 0.0))
        else:  # curve
            thickness = float(old.get("thickness", max(1.0, float(getattr(self.settings, "thickness", 6)))))
            converted["thickness"] = thickness
            converted["angle_offset"] = float(old.get("angle_offset", 0.0))

            # If converting from a freehand curve, estimate length from endpoints.
            length = float(old.get("length", 40.0))
            if old.get("type") == "circle":
                length = float(old.get("radius", 6.0)) * 4.0
            elif old.get("type") in ("triangle", "polygon"):
                length = float(old.get("radius", 12.0)) * 3.0
            elif old.get("type") == "square":
                length = float(old.get("size", 18.0))
            elif old.get("type") == "curve":
                pts = old.get("points")
                if isinstance(pts, list) and len(pts) >= 2:
                    try:
                        x0, y0 = float(pts[0][0]), float(pts[0][1])
                        x1, y1 = float(pts[-1][0]), float(pts[-1][1])
                        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
                    except Exception:
                        pass
            length = max(1.0, length)
            converted["start_dx"] = -length / 2.0
            converted["start_dy"] = 0.0
            converted["ctrl_dx"] = 0.0
            converted["ctrl_dy"] = 0.0
            converted["end_dx"] = length / 2.0
            converted["end_dy"] = 0.0

        stack[row] = converted
        self.selected_component = converted

        item = self.components_list.item(row) if hasattr(self, "components_list") else None
        if item is not None:
            item.setText(self._component_summary(converted))
            item.setData(Qt.ItemDataRole.UserRole, converted)

        self._set_component_editor_state(converted)
        self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())
        self._update_preview()

    def _preview_mouse_press(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = self._map_label_to_pixmap(QPointF(event.pos()))

        # Draw mode: click-drag creates a new object.
        if getattr(self, "draw_mode_enabled", False):
            stack = self._current_component_stack()
            if stack is None:
                return
            self._checkpoint("draw")
            self._snap_guides = {}
            self._drawing_component = None
            self._draw_start_pos = pos
            along, perp = self._pixmap_to_line_coords(pos)
            self._draw_start_along = along
            self._draw_start_perp = perp
            self._draw_last_along = along
            self._draw_last_perp = perp

            comp_type = "curve"
            component = {"type": comp_type, **self._default_component_values(comp_type)}
            component["draggable"] = _coerce_bool(component.get("draggable", True), default=True)

            component["offset"] = along
            component["perp_offset"] = perp
            component["thickness"] = float(max(1, getattr(self.settings, "thickness", 6)))
            component["angle_offset"] = 0.0
            # Freehand curve points relative to anchor (offset/perp_offset).
            # Keep 2 points so a stroke appears immediately as you drag.
            component["points"] = [[0.0, 0.0], [0.0, 0.0]]

            stack.append(component)
            item = QListWidgetItem(self._component_summary(component))
            item.setData(Qt.ItemDataRole.UserRole, component)
            self.components_list.addItem(item)
            self.components_list.setCurrentRow(self.components_list.count() - 1)
            self.selected_component = component
            self._drawing_component = component
            self._set_component_editor_state(component)
            self._update_preview()
            event.accept()
            return
        
        # Check if clicking on a selection handle
        if self.selected_component and self.selection_handles:
            for handle_type, handle_rect in self.selection_handles:
                if handle_rect.contains(pos):
                    if handle_type in ("curve_start", "curve_ctrl", "curve_end"):
                        if self.selected_component.get("type") == "curve":
                            self._curve_drag_handle = handle_type
                            self.drag_start_pos = pos
                            self._pending_checkpoint_key = "curve_edit"
                            event.accept()
                            return
                    if handle_type == "delete":
                        self._remove_component()
                        self.selected_component = self._current_component()
                        self._update_preview()
                        return
                    elif handle_type == "duplicate":
                        self._duplicate_component()
                        self.selected_component = self._current_component()
                        self._update_preview()
                        return
                    elif handle_type == "rotate":
                        self.rotating = True
                        self.drag_start_pos = pos
                        self._pending_checkpoint_key = "rotate"
                        import math
                        # Calculate initial angle from component center to mouse
                        self.rotation_start_angle = self.selected_component.get("angle_offset", 0.0)
                        event.accept()
                        return
                    elif handle_type.startswith("resize"):
                        self.dragging_component = self.selected_component
                        self.drag_start_pos = pos
                        self.resize_mode = handle_type
                        self._pending_checkpoint_key = "resize"
                        event.accept()
                        return
        
        # Canva-like: click to select any object under the cursor.
        hit = self._hit_test_component(pos)
        if hit is not None:
            self.selected_component = hit
            self._select_component_row_for(hit)
            if hasattr(self, "quick_duplicate_btn"):
                self.quick_duplicate_btn.setEnabled(True)
            if hasattr(self, "quick_delete_btn"):
                self.quick_delete_btn.setEnabled(True)
            # Only start dragging if this object is marked draggable.
            if hit.get("draggable", True):
                self.dragging_component = hit
                self.drag_start_pos = pos
                self._pending_checkpoint_key = "drag"

                # Compute grab offset in line-local coordinates (absolute drag, not cumulative deltas).
                mouse_along, mouse_perp = self._pixmap_to_line_coords(pos)
                if hit.get("type") == "segment":
                    length = float(hit.get("length", 40.0))
                    anchor_along = float(hit.get("offset", 0.0)) + (length / 2.0)
                else:
                    anchor_along = float(hit.get("offset", 0.0))
                anchor_perp = float(hit.get("perp_offset", 0.0))
                self._drag_grab_delta_along = float(anchor_along) - float(mouse_along)
                self._drag_grab_delta_perp = float(anchor_perp) - float(mouse_perp)
            else:
                self.dragging_component = None
                self.drag_start_pos = None
            self._update_preview()
            event.accept()
            return

        # Deselect if clicking empty area
        if self.selected_component:
            self.selected_component = None
            self.dragging_component = None
            self.resize_mode = None
            self.rotating = False
            if hasattr(self, "quick_duplicate_btn"):
                self.quick_duplicate_btn.setEnabled(False)
            if hasattr(self, "quick_delete_btn"):
                self.quick_delete_btn.setEnabled(False)
            self._update_preview()

    def _preview_mouse_move(self, event) -> None:
        import math

        raw_pos = self._map_label_to_pixmap(QPointF(event.pos()))
        self._last_mouse_pos_pixmap = raw_pos
        current_pos = raw_pos

        # Draw mode in-progress update
        if getattr(self, "draw_mode_enabled", False) and self._drawing_component is not None and self._draw_start_pos is not None:
            comp = self._drawing_component
            # Snap drawing to grid if enabled.
            # Freehand curves should never snap (snapping makes the stroke feel point-to-point).
            if comp.get("type") != "curve":
                current_pos = self._snap_pixmap_point(current_pos)
            dx = float(current_pos.x()) - float(self._draw_start_pos.x())
            dy = float(current_pos.y()) - float(self._draw_start_pos.y())
            dist = (dx * dx + dy * dy) ** 0.5

            along2, perp2 = self._pixmap_to_line_coords(current_pos)

            if comp.get("type") == "segment":
                import math

                a0 = float(self._draw_start_along)
                p0 = float(self._draw_start_perp)
                a1 = float(along2)
                p1 = float(perp2)

                da = a1 - a0
                dp = p1 - p0
                length = max(1.0, (da * da + dp * dp) ** 0.5)

                # Place segment center at the midpoint between press and current.
                center_along = (a0 + a1) / 2.0
                center_perp = (p0 + p1) / 2.0
                comp["offset"] = float(center_along) - (length / 2.0)
                comp["perp_offset"] = float(center_perp)
                comp["length"] = float(length)

                # Rotate the segment so it matches the drag direction.
                # (angle_offset is relative to the current scope axis.)
                comp["angle_offset"] = float(math.degrees(math.atan2(dp, da))) if (abs(da) > 1e-6 or abs(dp) > 1e-6) else 0.0
            elif comp.get("type") == "curve":
                a1 = float(along2)
                p1 = float(perp2)
                # Freehand: append points relative to anchor (offset/perp_offset).
                anchor_a = float(comp.get("offset", 0.0))
                anchor_p = float(comp.get("perp_offset", 0.0))
                rel_a = float(a1 - anchor_a)
                rel_p = float(p1 - anchor_p)
                pts = comp.get("points")
                if not isinstance(pts, list):
                    pts = [[0.0, 0.0], [0.0, 0.0]]
                    comp["points"] = pts

                # Always keep the last point at the cursor, and append samples as we move.
                min_step = 0.75
                if len(pts) < 2:
                    pts.append([rel_a, rel_p])
                else:
                    # If we're far enough from the previous fixed sample, append; otherwise update the live tail.
                    prev = pts[-2]
                    try:
                        pa = float(prev[0])
                        pp = float(prev[1])
                    except (TypeError, ValueError, IndexError):
                        pa, pp = 0.0, 0.0
                    ddx = rel_a - pa
                    ddy = rel_p - pp
                    if (ddx * ddx + ddy * ddy) >= (min_step * min_step):
                        pts.append([rel_a, rel_p])
                    else:
                        pts[-1] = [rel_a, rel_p]
            elif comp.get("type") == "circle":
                comp["radius"] = max(1.0, dist)
            elif comp.get("type") == "square":
                comp["size"] = max(1.0, max(abs(dx), abs(dy)) * 2.0)
            else:  # triangle
                comp["radius"] = max(1.0, dist)

            # Update list row text
            row = self.components_list.currentRow()
            if row >= 0:
                item = self.components_list.item(row)
                if item is not None:
                    item.setText(self._component_summary(comp))
                    item.setData(Qt.ItemDataRole.UserRole, comp)

            self._sync_component_form(comp)
            self._update_preview()
            event.accept()
            return

        # Curve control-point drag
        if (
            self._curve_drag_handle
            and self.selected_component
            and self.selected_component.get("type") == "curve"
            and self.drag_start_pos is not None
        ):
            if self._pending_checkpoint_key == "curve_edit":
                self._checkpoint("curve_edit")
                self._pending_checkpoint_key = None

            cur = self.selected_component
            current_pos = self._map_label_to_pixmap(QPointF(event.pos()))
            current_pos = self._snap_pixmap_point(current_pos)

            along, perp = self._pixmap_to_line_coords(current_pos)
            anchor_along = float(cur.get("offset", 0.0))
            anchor_perp = float(cur.get("perp_offset", 0.0))
            rot = math.radians(float(cur.get("angle_offset", 0.0)))
            cos_r = math.cos(rot)
            sin_r = math.sin(rot)

            rx = float(along) - anchor_along
            ry = float(perp) - anchor_perp
            # Invert rotation: rotate by -rot
            dx_local = rx * cos_r + ry * sin_r
            dy_local = -rx * sin_r + ry * cos_r

            if self._curve_drag_handle == "curve_start":
                cur["start_dx"] = float(dx_local)
                cur["start_dy"] = float(dy_local)
            elif self._curve_drag_handle == "curve_ctrl":
                cur["ctrl_dx"] = float(dx_local)
                cur["ctrl_dy"] = float(dy_local)
            else:
                cur["end_dx"] = float(dx_local)
                cur["end_dy"] = float(dy_local)

            row = self.components_list.currentRow()
            if row >= 0:
                item = self.components_list.item(row)
                if item is not None:
                    item.setText(self._component_summary(cur))
                    item.setData(Qt.ItemDataRole.UserRole, cur)

            self._sync_component_form(cur)
            self._update_preview()
            event.accept()
            return
        
        # Handle rotation
        if self.rotating and self.drag_start_pos and self.selected_component:
            if self._pending_checkpoint_key == "rotate":
                self._checkpoint("rotate")
                self._pending_checkpoint_key = None
            self._snap_guides = {}
            delta = current_pos - self.drag_start_pos
            self.drag_start_pos = current_pos
            # Simple rotation based on horizontal movement (invert so it matches cursor direction)
            angle_change = -delta.x() * 0.5  # Sensitivity factor
            new_angle = float(self.selected_component.get("angle_offset", 0.0)) + angle_change
            
            # Snap rotation using the existing Snap toggle (Shift also works as an override).
            if self.grid_snap_enabled or (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                new_angle = round(new_angle / 15) * 15
            
            self.selected_component["angle_offset"] = new_angle
            self._sync_component_form(self.selected_component)
            self._update_preview()
            event.accept()
            return
        
        # Handle resizing
        if hasattr(self, 'resize_mode') and self.resize_mode and self.dragging_component and self.drag_start_pos:
            if self._pending_checkpoint_key == "resize":
                self._checkpoint("resize")
                self._pending_checkpoint_key = None
            self._snap_guides = {}
            delta = current_pos - self.drag_start_pos
            self.drag_start_pos = current_pos

            # Compute orientation (line angle + component rotation)
            base_angle, layer_angle_offset = self._current_line_angles()

            component_angle = float(self.dragging_component.get("angle_offset", 0.0))
            orient_rad = math.radians(base_angle + layer_angle_offset + component_angle)
            cos_o = math.cos(orient_rad)
            sin_o = math.sin(orient_rad)

            # Projections along the component axis and its normal
            along = delta.x() * cos_o + delta.y() * sin_o
            normal = -delta.x() * sin_o + delta.y() * cos_o
            
            if self.resize_mode == "resize_length":
                current_length = float(self.dragging_component.get("length", 40.0))
                new_length = max(1.0, current_length + along)
                delta_len = new_length - current_length

                # Keep segment midpoint fixed (offset + length/2 stays constant)
                current_offset = float(self.dragging_component.get("offset", 0.0))
                if self.dragging_component.get("_standard_base") and self.dragging_component.get("_standard_linked", True):
                    self.dragging_component["_standard_linked"] = False
                self.dragging_component["offset"] = current_offset - (delta_len / 2.0)
                self.dragging_component["length"] = new_length
                self._sync_component_form(self.dragging_component)
                self._update_preview()
                event.accept()
                return
            elif self.resize_mode == "resize_thickness":
                current_thickness = float(self.dragging_component.get("thickness", 4.0))
                new_thickness = max(1.0, current_thickness + normal)
                if self.dragging_component.get("_standard_base") and self.dragging_component.get("_standard_linked", True):
                    self.dragging_component["_standard_linked"] = False
                self.dragging_component["thickness"] = new_thickness
                self._sync_component_form(self.dragging_component)
                self._update_preview()
                event.accept()
                return
        
        # Handle normal dragging
        if self.dragging_component is None or self.drag_start_pos is None:
            return

        if self._pending_checkpoint_key == "drag":
            self._checkpoint("drag")
            self._pending_checkpoint_key = None

        # Absolute dragging in line-local coords (avoids jitter/roughness when snapping).
        mouse_along, mouse_perp = self._pixmap_to_line_coords(current_pos)
        desired_anchor_along = float(mouse_along) + float(self._drag_grab_delta_along)
        desired_perp_offset = float(mouse_perp) + float(self._drag_grab_delta_perp)

        if self.dragging_component.get("type") == "segment":
            length = float(self.dragging_component.get("length", 40.0))
            new_offset = desired_anchor_along - (length / 2.0)
            anchor_offset = desired_anchor_along
        else:
            new_offset = desired_anchor_along
            anchor_offset = desired_anchor_along

        new_perp_offset = desired_perp_offset
        
        # Apply magnetic snapping to grid guides when snap is enabled
        grid_size = self._effective_grid_size()
        if self.grid_snap_enabled and grid_size > 1:
            self._snap_guides = {}

            base_angle, angle_offset = self._current_line_angles()
            angle_rad = math.radians(base_angle + angle_offset)

            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)

            # Snap using component anchor (segment midpoint / circle center).
            anchor_offset = float(anchor_offset)

            # Convert (anchor_along, perp) -> screen-space coords (relative to center)
            x_rel = anchor_offset * cos_a - new_perp_offset * sin_a
            y_rel = anchor_offset * sin_a + new_perp_offset * cos_a

            # IMPORTANT: snap to the *visible* grid (screen space),
            # including optional diagonal guides.
            x_rel, y_rel, snap_meta = self._snap_screen_point_with_guides(float(x_rel), float(y_rel), int(grid_size))

            # Record snapped guide(s) so we can highlight them.
            if isinstance(snap_meta, dict):
                if "x" in snap_meta:
                    self._snap_guides["x"] = (self._preview_pixmap_size[0] / 2.0) + float(snap_meta["x"])
                if "y" in snap_meta:
                    self._snap_guides["y"] = (self._preview_pixmap_size[1] / 2.0) + float(snap_meta["y"])
                if "diag_pos" in snap_meta:
                    self._snap_guides["diag_pos"] = float(snap_meta["diag_pos"])
                if "diag_neg" in snap_meta:
                    self._snap_guides["diag_neg"] = float(snap_meta["diag_neg"])

            # Align-to-other object anchors (quick tidy-up guides).
            stack = self._current_component_stack() or []
            align_threshold = min(4.0, float(grid_size) / 8.0)
            for other in stack:
                if not isinstance(other, dict) or other is self.dragging_component:
                    continue
                other_type = other.get("type")
                if other_type == "segment":
                    other_len = float(other.get("length", 40.0))
                    other_anchor = float(other.get("offset", 0.0)) + (other_len / 2.0)
                else:
                    other_anchor = float(other.get("offset", 0.0))
                other_perp = float(other.get("perp_offset", 0.0))
                other_x = other_anchor * cos_a - other_perp * sin_a
                other_y = other_anchor * sin_a + other_perp * cos_a

                if abs(x_rel - other_x) < align_threshold:
                    x_rel = other_x
                    self._snap_guides["x"] = (self._preview_pixmap_size[0] / 2.0) + float(other_x)
                if abs(y_rel - other_y) < align_threshold:
                    y_rel = other_y
                    self._snap_guides["y"] = (self._preview_pixmap_size[1] / 2.0) + float(other_y)

            # Convert back screen-space -> (anchor_along, perp)
            anchor_offset = x_rel * cos_a + y_rel * sin_a
            new_perp_offset = -x_rel * sin_a + y_rel * cos_a

            # Convert anchor -> stored offset
            if self.dragging_component.get("type") == "segment":
                length = float(self.dragging_component.get("length", 40.0))
                new_offset = anchor_offset - (length / 2.0)
            else:
                new_offset = anchor_offset
        else:
            self._snap_guides = {}
        
        # Update both offset and perp_offset
        if self.dragging_component.get("_standard_base") and self.dragging_component.get("_standard_linked", True):
            self.dragging_component["_standard_linked"] = False
        self.dragging_component["offset"] = new_offset
        self.dragging_component["perp_offset"] = new_perp_offset
        
        # Sync UI and preview
        self._sync_component_form(self.dragging_component)
        self._update_preview()
        event.accept()

    def _preview_mouse_release(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            ended_action = False
            if getattr(self, "draw_mode_enabled", False) and self._drawing_component is not None:
                self._drawing_component = None
                self._draw_start_pos = None
                self._snap_guides = {}
                self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())
                self._pending_checkpoint_key = None
                ended_action = True

                self._end_history_group()
                event.accept()
                return
            if self.dragging_component is not None:
                self.dragging_component = None
                self.drag_start_pos = None
                self._snap_guides = {}
                self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())
                self._pending_checkpoint_key = None
                ended_action = True
                event.accept()
            if self.rotating:
                self.rotating = False
                self.drag_start_pos = None
                self._snap_guides = {}
                self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())
                self._pending_checkpoint_key = None
                ended_action = True
                event.accept()
            if hasattr(self, 'resize_mode'):
                self.resize_mode = None
                self.drag_start_pos = None
                self._snap_guides = {}
                self._pending_checkpoint_key = None
                ended_action = True

            if ended_action:
                self._end_history_group()

            # End curve point editing
            if self._curve_drag_handle is not None:
                self._curve_drag_handle = None
                self.drag_start_pos = None
                self._persist(self._current_scope_standard_key(), self._current_scope_custom_id())
                self._pending_checkpoint_key = None
                self._end_history_group()
                event.accept()

    def _on_add_custom_line(self) -> None:
        self._checkpoint("add_custom_line")
        layer = self._create_default_layer()
        self.settings.line_layers.append(layer)
        self._build_custom_list(selected_id=layer["id"])
        self._persist(custom_id=layer["id"], refresh_custom_list=False)

    def _on_duplicate_custom_line(self) -> None:
        layer = self._current_custom_layer()
        row = self.custom_list.currentRow()
        if layer is None or row < 0:
            return
        self._checkpoint("duplicate_custom_line")
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
        self._checkpoint("remove_custom_line")
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
        self._checkpoint("reorder_custom_lines")
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
        self._checkpoint("layer:label")
        layer["label"] = text.strip() or "Custom Line"
        self._refresh_custom_item_text(layer["id"])
        self._persist(custom_id=layer["id"])

    def _on_layer_enabled_toggled(self, enabled: bool) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        self._checkpoint("layer:enabled")
        layer["enabled"] = enabled
        self._refresh_custom_item_text(layer["id"])
        self._persist(custom_id=layer["id"])

    def _on_layer_draggable_toggled(self, enabled: bool) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        self._checkpoint("layer:draggable")
        layer["draggable"] = enabled
        # Apply to all objects so the toggle actually affects dragging behavior.
        stack = self._current_component_stack()
        if isinstance(stack, list):
            for comp in stack:
                if isinstance(comp, dict):
                    comp["draggable"] = enabled
        if self.selected_component is not None:
            self._sync_component_form(self.selected_component)
        self._persist(custom_id=layer["id"])

    def _on_layer_angle_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        self._checkpoint("layer:angle")
        # Don't reset offset when changing angle - just update the angle
        layer["angle"] = value
        self._refresh_custom_item_text(layer["id"])
        self._persist(custom_id=layer["id"])

    def _on_layer_angle_offset_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        self._checkpoint("layer:angle_offset")
        layer["angle_offset"] = value
        self._persist(custom_id=layer["id"])

    def _on_layer_gap_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        self._checkpoint("layer:gap")
        layer["gap"] = max(0.0, value)
        self._persist(custom_id=layer["id"])

    def _on_layer_length_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        self._checkpoint("layer:length")
        layer["length"] = max(0.0, value)
        self._persist(custom_id=layer["id"])

    def _on_layer_thickness_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        self._checkpoint("layer:thickness")
        layer["thickness"] = max(0.1, value)
        self._persist(custom_id=layer["id"])

    def _on_layer_tip_changed(self, value: float) -> None:
        layer = self._current_custom_layer()
        if layer is None:
            return
        self._checkpoint("layer:tip")
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

        self._preview_pixmap_size = (w, h)
        label_w = max(1, size.width())
        label_h = max(1, size.height())
        scale = min(label_w / w, label_h / h)
        scaled_w = w * scale
        scaled_h = h * scale
        offset_x = (label_w - scaled_w) / 2.0
        offset_y = (label_h - scaled_h) / 2.0
        self._preview_scale = scale
        self._preview_offset = (offset_x, offset_y)

        grid_size = self._effective_grid_size()
        
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
                x += grid_size
            x = center_x - grid_size
            while x >= 0:
                painter.drawLine(x, 0, x, h)
                x -= grid_size
            
            # Horizontal lines
            y = center_y
            while y < h:
                painter.drawLine(0, y, w, y)
                y += grid_size
            y = center_y - grid_size
            while y >= 0:
                painter.drawLine(0, y, w, y)
                y -= grid_size
            
            # Center crosshair
            painter.setPen(QPen(QColor(255, 255, 255, 120), 1, Qt.PenStyle.DashLine))
            painter.drawLine(center_x, 0, center_x, h)
            painter.drawLine(0, center_y, w, center_y)

            # Optional diagonal grid overlays (follow grid size).
            # These diagonals align to the same grid intersections as the
            # axis-aligned lines, so each cell can be visually "sliced".
            if getattr(self, "grid_diag_pos", False) or getattr(self, "grid_diag_neg", False):
                painter.setPen(QPen(QColor(255, 255, 255, 35), 1))
                half_w = w / 2.0
                half_h = h / 2.0
                step = max(1, int(grid_size))
                max_c = int((half_w + half_h) + step * 2)
                n_max = int(max_c / step) + 2

                def draw_diag_pos(c: float) -> None:
                    # x + y = c (relative to center)
                    pts: list[tuple[float, float]] = []
                    x = -half_w
                    y = c - x
                    if -half_h <= y <= half_h:
                        pts.append((x, y))
                    x = half_w
                    y = c - x
                    if -half_h <= y <= half_h:
                        pts.append((x, y))
                    y = -half_h
                    x = c - y
                    if -half_w <= x <= half_w:
                        pts.append((x, y))
                    y = half_h
                    x = c - y
                    if -half_w <= x <= half_w:
                        pts.append((x, y))
                    if len(pts) >= 2:
                        (x1, y1), (x2, y2) = pts[0], pts[1]
                        painter.drawLine(int(center_x + x1), int(center_y + y1), int(center_x + x2), int(center_y + y2))

                def draw_diag_neg(c: float) -> None:
                    # x - y = c (relative to center)
                    pts: list[tuple[float, float]] = []
                    x = -half_w
                    y = x - c
                    if -half_h <= y <= half_h:
                        pts.append((x, y))
                    x = half_w
                    y = x - c
                    if -half_h <= y <= half_h:
                        pts.append((x, y))
                    y = -half_h
                    x = y + c
                    if -half_w <= x <= half_w:
                        pts.append((x, y))
                    y = half_h
                    x = y + c
                    if -half_w <= x <= half_w:
                        pts.append((x, y))
                    if len(pts) >= 2:
                        (x1, y1), (x2, y2) = pts[0], pts[1]
                        painter.drawLine(int(center_x + x1), int(center_y + y1), int(center_x + x2), int(center_y + y2))

                if getattr(self, "grid_diag_pos", False):
                    for n in range(-n_max, n_max + 1):
                        draw_diag_pos(float(n * step))
                if getattr(self, "grid_diag_neg", False):
                    for n in range(-n_max, n_max + 1):
                        draw_diag_neg(float(n * step))
        
        painter.end()
        
        # Render crosshair on top using the existing function
        temp_settings = deepcopy(self.settings)
        temp_settings.offset_x = 0
        temp_settings.offset_y = 0
        temp_settings.visible = True
        
        crosshair_pixmap = generate_crosshair_pixmap(w, h, temp_settings, extra_rotation=0.0, opacity_multiplier=1.0)
        
        # Composite the crosshair onto the grid
        painter = QPainter(pixmap)
        painter.drawPixmap(0, 0, crosshair_pixmap)

        # Draw snap guides on top (only during active drag).
        if self.dragging_component is not None and isinstance(getattr(self, "_snap_guides", None), dict) and self._snap_guides:
            pen = QPen(QColor(0, 188, 212, 200), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            gx = self._snap_guides.get("x")
            gy = self._snap_guides.get("y")
            if isinstance(gx, (int, float)):
                painter.drawLine(int(gx), 0, int(gx), h)
            if isinstance(gy, (int, float)):
                painter.drawLine(0, int(gy), w, int(gy))

            center_x = float(w) / 2.0
            center_y = float(h) / 2.0
            half_w = float(w) / 2.0
            half_h = float(h) / 2.0

            def _draw_diag_pos_guide(c: float) -> None:
                # x + y = c (relative to center)
                pts: list[tuple[float, float]] = []
                x = -half_w
                y = c - x
                if -half_h <= y <= half_h:
                    pts.append((x, y))
                x = half_w
                y = c - x
                if -half_h <= y <= half_h:
                    pts.append((x, y))
                y = -half_h
                x = c - y
                if -half_w <= x <= half_w:
                    pts.append((x, y))
                y = half_h
                x = c - y
                if -half_w <= x <= half_w:
                    pts.append((x, y))
                if len(pts) >= 2:
                    (x1, y1), (x2, y2) = pts[0], pts[1]
                    painter.drawLine(int(center_x + x1), int(center_y + y1), int(center_x + x2), int(center_y + y2))

            def _draw_diag_neg_guide(c: float) -> None:
                # x - y = c (relative to center)
                pts: list[tuple[float, float]] = []
                x = -half_w
                y = x - c
                if -half_h <= y <= half_h:
                    pts.append((x, y))
                x = half_w
                y = x - c
                if -half_h <= y <= half_h:
                    pts.append((x, y))
                y = -half_h
                x = y + c
                if -half_w <= x <= half_w:
                    pts.append((x, y))
                y = half_h
                x = y + c
                if -half_w <= x <= half_w:
                    pts.append((x, y))
                if len(pts) >= 2:
                    (x1, y1), (x2, y2) = pts[0], pts[1]
                    painter.drawLine(int(center_x + x1), int(center_y + y1), int(center_x + x2), int(center_y + y2))

            gdp = self._snap_guides.get("diag_pos")
            gdn = self._snap_guides.get("diag_neg")
            if isinstance(gdp, (int, float)):
                _draw_diag_pos_guide(float(gdp))
            if isinstance(gdn, (int, float)):
                _draw_diag_neg_guide(float(gdn))
        
        # Draw selection handles if a component is selected
        if self.selected_component:
            self._draw_selection_handles(painter, w, h)
        
        
        painter.end()
        
        self.preview_label.setPixmap(
            pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def _map_label_to_pixmap(self, pos: QPointF) -> QPointF:
        scale = self._preview_scale if self._preview_scale else 1.0
        offset_x, offset_y = self._preview_offset
        return QPointF((pos.x() - offset_x) / scale, (pos.y() - offset_y) / scale)

    def _effective_grid_size(self) -> int:
        spin = getattr(self, "grid_size_spin", None)
        if isinstance(spin, QSpinBox):
            return int(spin.value())
        return int(self.grid_size)

    def _pixmap_to_line_coords(self, pos: QPointF) -> tuple[float, float]:
        """Convert a pixmap-space point into (along, perp) for the current scope."""
        import math

        w, h = self._preview_pixmap_size if isinstance(getattr(self, "_preview_pixmap_size", None), tuple) else (240, 240)
        center_x = int(w) // 2
        center_y = int(h) // 2
        x_rel = float(pos.x()) - float(center_x)
        y_rel = float(pos.y()) - float(center_y)

        base_angle, layer_angle_offset = self._current_line_angles()
        angle_rad = math.radians(base_angle + layer_angle_offset)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        along = x_rel * cos_a + y_rel * sin_a
        perp = -x_rel * sin_a + y_rel * cos_a
        return float(along), float(perp)

    def _line_coords_to_pixmap(self, along: float, perp: float) -> QPointF:
        """Convert (along, perp) in current scope into pixmap-space point."""
        import math

        w, h = self._preview_pixmap_size if isinstance(getattr(self, "_preview_pixmap_size", None), tuple) else (240, 240)
        center_x = int(w) // 2
        center_y = int(h) // 2

        base_angle, layer_angle_offset = self._current_line_angles()
        angle_rad = math.radians(base_angle + layer_angle_offset)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        x_rel = float(along) * cos_a - float(perp) * sin_a
        y_rel = float(along) * sin_a + float(perp) * cos_a
        return QPointF(float(center_x) + x_rel, float(center_y) + y_rel)

    def _curve_handle_points_pixmap(self, component: dict) -> dict[str, QPointF]:
        """Return pixmap-space points for curve start/control/end."""
        import math

        anchor_along = float(component.get("offset", 0.0))
        anchor_perp = float(component.get("perp_offset", 0.0))
        rot = math.radians(float(component.get("angle_offset", 0.0)))
        cos_r = math.cos(rot)
        sin_r = math.sin(rot)

        def to_line(dx: float, dy: float) -> tuple[float, float]:
            xr = float(dx) * cos_r - float(dy) * sin_r
            yr = float(dx) * sin_r + float(dy) * cos_r
            return anchor_along + xr, anchor_perp + yr

        s_along, s_perp = to_line(float(component.get("start_dx", -20.0)), float(component.get("start_dy", 0.0)))
        c_along, c_perp = to_line(float(component.get("ctrl_dx", 0.0)), float(component.get("ctrl_dy", 0.0)))
        e_along, e_perp = to_line(float(component.get("end_dx", 20.0)), float(component.get("end_dy", 0.0)))

        return {
            "start": self._line_coords_to_pixmap(s_along, s_perp),
            "ctrl": self._line_coords_to_pixmap(c_along, c_perp),
            "end": self._line_coords_to_pixmap(e_along, e_perp),
        }

    def _snap_pixmap_point(self, pos: QPointF) -> QPointF:
        """Snap a pixmap-space point to the visible grid (screen space)."""
        if not self.grid_snap_enabled:
            return pos

        grid_size = self._effective_grid_size()
        if grid_size <= 1:
            return pos

        w, h = self._preview_pixmap_size if isinstance(getattr(self, "_preview_pixmap_size", None), tuple) else (240, 240)
        center_x = float(int(w) // 2)
        center_y = float(int(h) // 2)

        x_rel = float(pos.x()) - center_x
        y_rel = float(pos.y()) - center_y

        x_rel, y_rel = self._snap_screen_point(x_rel, y_rel, grid_size)

        return QPointF(center_x + x_rel, center_y + y_rel)

    def _snap_screen_point(self, x_rel: float, y_rel: float, grid_size: int) -> tuple[float, float]:
        """Snap a screen-space point (relative to center) to enabled guides."""
        if not self.grid_snap_enabled or grid_size <= 1:
            return x_rel, y_rel

        snap_threshold = max(4.0, float(grid_size) / 6.0)
        candidates: list[tuple[float, float]] = []

        # Axis-aligned grid
        nx = round(x_rel / grid_size) * grid_size
        if abs(x_rel - nx) < snap_threshold:
            candidates.append((nx, y_rel))

        ny = round(y_rel / grid_size) * grid_size
        if abs(y_rel - ny) < snap_threshold:
            candidates.append((x_rel, ny))

        # Diagonal grids: x+y=c and x-y=c, where c steps by grid_size.
        # These align to the same grid intersections as the axis grid.
        root2 = 1.41421356237

        if getattr(self, "grid_diag_pos", False):
            s = x_rel + y_rel
            ns = round(s / grid_size) * grid_size
            if abs(s - ns) < (snap_threshold * root2):
                delta = (ns - s) / 2.0
                candidates.append((x_rel + delta, y_rel + delta))

        if getattr(self, "grid_diag_neg", False):
            d = x_rel - y_rel
            nd = round(d / grid_size) * grid_size
            if abs(d - nd) < (snap_threshold * root2):
                delta = (nd - d) / 2.0
                candidates.append((x_rel + delta, y_rel - delta))

        if not candidates:
            return x_rel, y_rel

        best_x, best_y = x_rel, y_rel
        best_dist2 = 1e18
        for cx, cy in candidates:
            dx = cx - x_rel
            dy = cy - y_rel
            dist2 = dx * dx + dy * dy
            if dist2 < best_dist2:
                best_dist2 = dist2
                best_x, best_y = cx, cy

        return best_x, best_y

    def _snap_screen_point_with_guides(
        self, x_rel: float, y_rel: float, grid_size: int
    ) -> tuple[float, float, dict[str, float]]:
        """Snap a screen-space point and return which guide was used.

        Returned guide keys:
        - x: snapped x (relative-to-center)
        - y: snapped y (relative-to-center)
        - diag_pos: snapped constant c for x+y=c
        - diag_neg: snapped constant c for x-y=c
        """
        if not self.grid_snap_enabled or grid_size <= 1:
            return x_rel, y_rel, {}

        snap_threshold = max(4.0, float(grid_size) / 6.0)
        candidates: list[tuple[float, float, dict[str, float]]] = []

        # Axis-aligned grid
        nx = round(x_rel / grid_size) * grid_size
        if abs(x_rel - nx) < snap_threshold:
            candidates.append((nx, y_rel, {"x": float(nx)}))

        ny = round(y_rel / grid_size) * grid_size
        if abs(y_rel - ny) < snap_threshold:
            candidates.append((x_rel, ny, {"y": float(ny)}))

        # Diagonal grids: x+y=c and x-y=c, where c steps by grid_size.
        root2 = 1.41421356237

        if getattr(self, "grid_diag_pos", False):
            s = x_rel + y_rel
            ns = round(s / grid_size) * grid_size
            if abs(s - ns) < (snap_threshold * root2):
                delta = (ns - s) / 2.0
                candidates.append((x_rel + delta, y_rel + delta, {"diag_pos": float(ns)}))

        if getattr(self, "grid_diag_neg", False):
            d = x_rel - y_rel
            nd = round(d / grid_size) * grid_size
            if abs(d - nd) < (snap_threshold * root2):
                delta = (nd - d) / 2.0
                candidates.append((x_rel + delta, y_rel - delta, {"diag_neg": float(nd)}))

        if not candidates:
            return x_rel, y_rel, {}

        best_x, best_y = x_rel, y_rel
        best_meta: dict[str, float] = {}
        best_dist2 = 1e18
        for cx, cy, meta in candidates:
            dx = cx - x_rel
            dy = cy - y_rel
            dist2 = dx * dx + dy * dy
            if dist2 < best_dist2:
                best_dist2 = dist2
                best_x, best_y = cx, cy
                best_meta = meta

        return best_x, best_y, best_meta

    def _on_draw_mode_toggled(self, enabled: bool) -> None:
        self.draw_mode_enabled = bool(enabled)
        # Cancel any in-progress drag/rotate/resize when entering draw mode.
        if self.draw_mode_enabled:
            self.dragging_component = None
            self.rotating = False
            self.resize_mode = None

    def _on_draw_type_changed(self, index: int) -> None:
        self.draw_mode_type = "curve"

    def _capture_history_state(self) -> dict:
        return {
            "line_components": deepcopy(self.settings.line_components) if isinstance(self.settings.line_components, dict) else {},
            "line_layers": deepcopy(self.settings.line_layers) if isinstance(self.settings.line_layers, list) else [],
            "active_scope_kind": self.active_scope_kind,
            "active_scope_id": self.active_scope_id,
            "standard_row": int(self.standard_list.currentRow()) if hasattr(self, "standard_list") else -1,
            "custom_row": int(self.custom_list.currentRow()) if hasattr(self, "custom_list") else -1,
            "component_row": int(self.components_list.currentRow()) if hasattr(self, "components_list") else -1,
        }

    def _restore_history_state(self, state: dict) -> None:
        self._history_suspended = True
        try:
            self.settings.line_components = deepcopy(state.get("line_components", {}))
            self.settings.line_layers = deepcopy(state.get("line_layers", []))

            self._build_standard_list()
            self._build_custom_list(selected_id=state.get("active_scope_id") if state.get("active_scope_kind") == "custom" else None)

            kind = state.get("active_scope_kind")
            if kind == "standard":
                row = int(state.get("standard_row", 0))
                self.standard_list.setCurrentRow(max(-1, row))
            elif kind == "custom":
                row = int(state.get("custom_row", -1))
                self.custom_list.setCurrentRow(max(-1, row))
            else:
                self.standard_list.setCurrentRow(-1)
                self.custom_list.setCurrentRow(-1)

            self._refresh_component_list()
            comp_row = int(state.get("component_row", -1))
            if comp_row >= 0:
                self.components_list.setCurrentRow(comp_row)

            self._update_layer_metadata_view()
            self._update_preview()
        finally:
            self._history_suspended = False

        self.parent_dialog._persist_and_render()
        self._update_history_buttons()

    def _end_history_group(self) -> None:
        self._history_group_key = None

    def _checkpoint(self, key: str) -> None:
        if self._history_suspended:
            return

        # Coalesce rapid edits of the same kind into one undo step.
        if self._history_group_key != key:
            self._history_group_key = key
            self._undo_stack.append(self._capture_history_state())
            self._redo_stack.clear()
        self._history_group_timer.start(700)
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        if hasattr(self, "undo_btn"):
            self.undo_btn.setEnabled(len(self._undo_stack) > 0)
        if hasattr(self, "redo_btn"):
            self.redo_btn.setEnabled(len(self._redo_stack) > 0)

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._history_group_timer.stop()
        self._history_group_key = None
        current = self._capture_history_state()
        state = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_history_state(state)

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._history_group_timer.stop()
        self._history_group_key = None
        current = self._capture_history_state()
        state = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_history_state(state)

    def _draw_selection_handles(self, painter, w: int, h: int) -> None:
        """Draw selection handles around the selected component"""
        import math
        
        # Get component position
        base_angle, layer_angle_offset = self._current_line_angles()
        
        offset = self.selected_component.get("offset", 0.0)
        perp_offset = self.selected_component.get("perp_offset", 0.0)
        component_angle = float(self.selected_component.get("angle_offset", 0.0))
        line_angle = base_angle + layer_angle_offset
        orient_angle = line_angle + component_angle
        
        # Calculate component center position (segment midpoint / circle center)
        center_x = w // 2
        center_y = h // 2

        line_rad = math.radians(line_angle)
        if self.selected_component.get("type") == "segment":
            length = float(self.selected_component.get("length", 40.0))
            anchor_offset = float(offset) + (length / 2.0)
        else:
            anchor_offset = float(offset)

        comp_x = center_x + anchor_offset * math.cos(line_rad) - float(perp_offset) * math.sin(line_rad)
        comp_y = center_y + anchor_offset * math.sin(line_rad) + float(perp_offset) * math.cos(line_rad)
        
        # Get component size for handle placement
        ctype = self.selected_component.get("type")
        if ctype == "segment":
            length = float(self.selected_component.get("length", 40.0))
            thickness = float(self.selected_component.get("thickness", 4.0))
            half_len = length / 2.0
            half_thick = thickness / 2.0 + 15.0
        elif ctype == "square":
            size = float(self.selected_component.get("size", 18.0))
            half_len = (size / 2.0) + 15.0
            half_thick = (size / 2.0) + 15.0
        elif ctype == "curve":
            # For freehand curves (points list), use bounds based on the points; for bezier curves, use handle points.
            raw_pts = self.selected_component.get("points")
            if isinstance(raw_pts, list) and len(raw_pts) >= 2:
                offset = float(self.selected_component.get("offset", 0.0))
                perp_offset = float(self.selected_component.get("perp_offset", 0.0))

                min_x = float("inf")
                max_x = float("-inf")
                min_y = float("inf")
                max_y = float("-inf")

                for p in raw_pts:
                    if not (isinstance(p, (list, tuple)) and len(p) == 2):
                        continue
                    if not (isinstance(p[0], (int, float)) and isinstance(p[1], (int, float))):
                        continue
                    pt = self._line_coords_to_pixmap(offset + float(p[0]), perp_offset + float(p[1]))
                    min_x = min(min_x, float(pt.x()))
                    max_x = max(max_x, float(pt.x()))
                    min_y = min(min_y, float(pt.y()))
                    max_y = max(max_y, float(pt.y()))

                if min_x != float("inf"):
                    comp_x = (min_x + max_x) / 2.0
                    comp_y = (min_y + max_y) / 2.0
                    half_len = ((max_x - min_x) / 2.0) + 15.0
                    half_thick = ((max_y - min_y) / 2.0) + 15.0
                else:
                    half_len = 30.0
                    half_thick = 30.0
            else:
                pts = self._curve_handle_points_pixmap(self.selected_component)
                p0 = pts["start"]
                p1 = pts["ctrl"]
                p2 = pts["end"]

                # Expand bounds by sampling the curve.
                min_x = min(p0.x(), p1.x(), p2.x())
                max_x = max(p0.x(), p1.x(), p2.x())
                min_y = min(p0.y(), p1.y(), p2.y())
                max_y = max(p0.y(), p1.y(), p2.y())
                for i in range(1, 17):
                    t = i / 16.0
                    mt = 1.0 - t
                    x = (mt * mt) * p0.x() + (2.0 * mt * t) * p1.x() + (t * t) * p2.x()
                    y = (mt * mt) * p0.y() + (2.0 * mt * t) * p1.y() + (t * t) * p2.y()
                    min_x = min(min_x, float(x))
                    max_x = max(max_x, float(x))
                    min_y = min(min_y, float(y))
                    max_y = max(max_y, float(y))

                comp_x = (min_x + max_x) / 2.0
                comp_y = (min_y + max_y) / 2.0
                half_len = ((max_x - min_x) / 2.0) + 15.0
                half_thick = ((max_y - min_y) / 2.0) + 15.0
        else:  # circle / triangle / legacy polygon
            radius = float(self.selected_component.get("radius", 10.0))
            half_len = radius + 15.0
            half_thick = radius + 15.0
        
        # Store handle positions for hit testing
        self.selection_handles = []
        handle_size = 24
        button_size = 28

        # Slight spacing to make controls look cleaner
        pad = 10
        
        # Calculate positions relative to component orientation
        orient_rad = math.radians(orient_angle)
        cos_a = math.cos(orient_rad)
        sin_a = math.sin(orient_rad)
        
        # Unit vectors: along (cos_a, sin_a) and normal (-sin_a, cos_a)
        u_x, u_y = cos_a, sin_a
        n_x, n_y = -sin_a, cos_a

        # Rotate handle (above)
        rotate_x = comp_x + n_x * (half_thick + pad + button_size)
        rotate_y = comp_y + n_y * (half_thick + pad + button_size)

        # Delete handle (above-right)
        delete_x = comp_x + u_x * (half_len + pad + button_size / 2) + n_x * (half_thick + pad + button_size / 2)
        delete_y = comp_y + u_y * (half_len + pad + button_size / 2) + n_y * (half_thick + pad + button_size / 2)

        # Duplicate handle (above-left)
        duplicate_x = comp_x - u_x * (half_len + pad + button_size / 2) + n_x * (half_thick + pad + button_size / 2)
        duplicate_y = comp_y - u_y * (half_len + pad + button_size / 2) + n_y * (half_thick + pad + button_size / 2)

        # Resize handle (right, along axis)
        resize_x = comp_x + u_x * (half_len + pad + button_size)
        resize_y = comp_y + u_y * (half_len + pad + button_size)

        # Thickness handle (below, along -normal)
        thick_x = comp_x - n_x * (half_thick + pad + button_size)
        thick_y = comp_y - n_y * (half_thick + pad + button_size)
        
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

        # Duplicate handle
        painter.setBrush(QColor(100, 255, 150))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        duplicate_rect = QRectF(duplicate_x - button_size/2, duplicate_y - button_size/2, button_size, button_size)
        painter.drawEllipse(duplicate_rect)
        self.selection_handles.append(("duplicate", duplicate_rect))

        # Draw copy icon (two overlapping squares)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        s = 9
        painter.drawRect(QRectF(duplicate_x - s + 3, duplicate_y - s + 3, s * 2, s * 2))
        painter.drawRect(QRectF(duplicate_x - s, duplicate_y - s, s * 2, s * 2))
        
        # Delete handle
        painter.setBrush(QColor(255, 80, 80))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        delete_rect = QRectF(delete_x - button_size/2, delete_y - button_size/2, button_size, button_size)
        painter.drawEllipse(delete_rect)
        self.selection_handles.append(("delete", delete_rect))
        
        # Draw X icon
        painter.drawLine(QPointF(delete_x - 6, delete_y - 6), QPointF(delete_x + 6, delete_y + 6))
        painter.drawLine(QPointF(delete_x + 6, delete_y - 6), QPointF(delete_x - 6, delete_y + 6))

        if self.selected_component.get("type") == "curve" and not (
            isinstance(self.selected_component.get("points"), list) and len(self.selected_component.get("points")) >= 2
        ):
            pts = self._curve_handle_points_pixmap(self.selected_component)
            start_pt = pts["start"]
            ctrl_pt = pts["ctrl"]
            end_pt = pts["end"]

            # Start / end handles (green), control handle (orange)
            painter.setPen(QPen(QColor(255, 255, 255), 2))

            painter.setBrush(QColor(100, 255, 150))
            start_rect = QRectF(start_pt.x() - handle_size / 2, start_pt.y() - handle_size / 2, handle_size, handle_size)
            painter.drawRect(start_rect)
            self.selection_handles.append(("curve_start", start_rect))

            end_rect = QRectF(end_pt.x() - handle_size / 2, end_pt.y() - handle_size / 2, handle_size, handle_size)
            painter.drawRect(end_rect)
            self.selection_handles.append(("curve_end", end_rect))

            painter.setBrush(QColor(255, 200, 100))
            ctrl_rect = QRectF(ctrl_pt.x() - handle_size / 2, ctrl_pt.y() - handle_size / 2, handle_size, handle_size)
            painter.drawEllipse(ctrl_rect)
            self.selection_handles.append(("curve_ctrl", ctrl_rect))
        
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


