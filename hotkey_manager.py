"""
Hotkey Manager Dialog for customizing keyboard shortcuts.
"""
import json
import os
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QGraphicsDropShadowEffect,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSizeGrip,
)
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtCore import Qt, pyqtSignal
from utils import UI_THEME


class HotkeyLineEdit(QLineEdit):
    """Custom line edit that captures key combinations."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Click and press a key...")
        self.current_key = ""
        self.original_key = ""
        self._captured_tokens: set[str] = set()
        self._held_tokens: set[str] = set()
        
    def focusInEvent(self, event):
        """Store original key when focused."""
        super().focusInEvent(event)
        self.original_key = self.current_key
        self._captured_tokens.clear()
        self._held_tokens.clear()
        self.setText("Press a key or ESC to cancel...")
        self.setStyleSheet(self.styleSheet() + "color: rgba(200, 200, 220, 150);")
        
    def focusOutEvent(self, event):
        """Restore color when focus lost."""
        super().focusOutEvent(event)
        if self.text() == "Press a key or ESC to cancel...":
            self.setText(self.current_key)
        self._captured_tokens.clear()
        self._held_tokens.clear()
        self.setStyleSheet(self.styleSheet().replace("color: rgba(200, 200, 220, 150);", "color: #E0E0E0;"))
        
    def keyPressEvent(self, event: QKeyEvent):
        """Capture key press and display it."""
        if event.isAutoRepeat():
            event.accept()
            return

        key = event.key()
        
        # Handle Escape to cancel
        if key == Qt.Key.Key_Escape:
            self.current_key = self.original_key
            self.setText(self.current_key if self.current_key else "")
            self.clearFocus()
            return

        token = self._event_to_token(event)
        if not token or token == "unknown":
            event.accept()
            return

        self._held_tokens.add(token)
        self._captured_tokens.add(token)

        # Also include currently-held modifiers even if their keyPress event was missed.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._captured_tokens.add("ctrl")
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._captured_tokens.add("alt")
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._captured_tokens.add("shift")
        if event.modifiers() & Qt.KeyboardModifier.MetaModifier:
            self._captured_tokens.add("windows")

        preview = self._format_tokens(self._captured_tokens)
        if preview:
            self.setText(preview)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.isAutoRepeat():
            event.accept()
            return

        token = self._event_to_token(event)
        if token:
            self._held_tokens.discard(token)

        # Finalize when all keys are released.
        if not self._held_tokens and self._captured_tokens:
            self.current_key = self._format_tokens(self._captured_tokens)
            self.setText(self.current_key)
            self._captured_tokens.clear()
            self._held_tokens.clear()
            self.clearFocus()
            event.accept()
            return

        super().keyReleaseEvent(event)

    def _event_to_token(self, event: QKeyEvent) -> str:
        key = event.key()
        if key == Qt.Key.Key_Control:
            return "ctrl"
        if key == Qt.Key.Key_Alt:
            return "alt"
        if key == Qt.Key.Key_Shift:
            return "shift"
        if key == Qt.Key.Key_Meta:
            return "windows"
        return self._get_key_name(key)

    def _format_tokens(self, tokens: set[str]) -> str:
        if not tokens:
            return ""
        order = {"ctrl": 0, "alt": 1, "shift": 2, "windows": 3}
        return "+".join(sorted(tokens, key=lambda t: (order.get(t, 50), t)))
    
    def _get_key_name(self, key):
        """Convert Qt key code to keyboard library format."""
        # Function keys
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            return f"f{key - Qt.Key.Key_F1 + 1}"
        
        # Letter keys
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(key).lower()
        
        # Number keys
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(key)
        
        # Special keys
        special_keys = {
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Insert: "insert",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "page up",
            Qt.Key.Key_PageDown: "page down",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
        }
        
        return special_keys.get(key, chr(key).lower() if key < 256 else "unknown")


class HotkeyManagerDialog(QWidget):
    """Dialog for managing keyboard shortcuts."""
    
    hotkeys_updated = pyqtSignal(dict)  # Signal emitted when hotkeys are saved
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.drag_position = None
        # Resizing (frameless)
        self._resize_margin = 7
        self._resizing = False
        self._resize_edges: set[str] = set()
        self._resize_start_pos = None
        self._resize_start_geom = None
        self._size_grip = None

        self.config_file = "hotkey_config.json"
        # key_name -> list[HotkeyLineEdit] (multiple bindings per action)
        self.hotkey_inputs: dict[str, list[HotkeyLineEdit]] = {}
        # key_name -> list[QWidget] row widgets (edit + delete)
        self._hotkey_row_widgets: dict[str, list[QWidget]] = {}
        # key_name -> QVBoxLayout that holds the HotkeyLineEdit rows (plus an add-row widget at the end)
        self._hotkey_inputs_layouts: dict[str, QVBoxLayout] = {}
        self._hotkey_add_row_widgets: dict[str, QWidget] = {}
        self.default_hotkeys = {
            "toggle_visibility": ["f1"],
            "mirror_vertical": ["f3"],
            "mirror_horizontal": ["f4"],
            "switch_image": ["f2"],
            # Hold this key while dragging the selected art element (optional).
            # Default is empty = no key required while Art Manager is open.
            "hold_to_drag": [],
        }
        self.current_hotkeys = self.load_hotkeys()
        self.init_ui()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        try:
            from hotkeys import pause_hotkeys
            pause_hotkeys()
        except Exception:
            pass
        # Ensure the tool window is interactive even when opened from tray/overlay contexts.
        try:
            self.raise_()
            self.activateWindow()
            self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        except Exception:
            pass

    def closeEvent(self, event):  # type: ignore[override]
        try:
            from hotkeys import resume_hotkeys
            resume_hotkeys()
        except Exception:
            pass
        super().closeEvent(event)
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Main container
        main_frame = self._create_main_frame()
        
        # Layout
        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Title bar
        title_bar = self._create_title_bar()
        self._title_bar = title_bar
        layout.addWidget(title_bar)
        
        # Content frame
        content_frame = self._create_content_frame()
        layout.addWidget(content_frame)
        
        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_frame)

        # Resize handle for the frameless dialog.
        self._size_grip = QSizeGrip(main_frame)
        self._size_grip.setFixedSize(16, 16)
        self._size_grip.setStyleSheet("QSizeGrip { background: transparent; }")

        # Resizable window (frameless), but keep a sensible minimum.
        # The dialog can grow vertically when multiple hotkeys are added; the
        # content scrolls instead of squishing.
        self.setMinimumSize(720, 560)
        self.resize(820, 760)
        self.center_on_screen()

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        try:
            if self._size_grip is not None:
                margin = 8
                self._size_grip.move(
                    self.width() - self._size_grip.width() - margin,
                    self.height() - self._size_grip.height() - margin,
                )
                self._size_grip.raise_()
        except Exception:
            pass

    def _hit_test_edges(self, pos) -> set[str]:
        m = int(self._resize_margin)
        edges: set[str] = set()
        x = int(pos.x())
        y = int(pos.y())
        if x <= m:
            edges.add("left")
        if x >= self.width() - m:
            edges.add("right")
        if y <= m:
            edges.add("top")
        if y >= self.height() - m:
            edges.add("bottom")
        return edges

    def _cursor_for_edges(self, edges: set[str]):
        if not edges:
            return Qt.CursorShape.ArrowCursor
        if edges == {"left"} or edges == {"right"}:
            return Qt.CursorShape.SizeHorCursor
        if edges == {"top"} or edges == {"bottom"}:
            return Qt.CursorShape.SizeVerCursor
        if ("left" in edges and "top" in edges) or ("right" in edges and "bottom" in edges):
            return Qt.CursorShape.SizeFDiagCursor
        return Qt.CursorShape.SizeBDiagCursor
    
    def _create_main_frame(self):
        """Create the main frame with styling."""
        main_frame = QFrame(self)
        main_frame.setObjectName("mainFrame")
        main_frame.setStyleSheet(
            "QFrame#mainFrame { background-color: "
            + UI_THEME["bg"]
            + "; border-radius: 15px; border: 1px solid "
            + UI_THEME["border"]
            + "; }"
        )
        
        # Add shadow effect
        # shadow = QGraphicsDropShadowEffect(self)
        # shadow.setBlurRadius(30)
        # shadow.setColor(QColor(0, 0, 0, 180))
        # shadow.setOffset(0, 5)
        # main_frame.setGraphicsEffect(shadow)
        
        return main_frame
    
    def _create_title_bar(self):
        """Create the title bar."""
        title_bar = QFrame()
        title_bar.setStyleSheet(
            "QFrame { background-color: "
            + UI_THEME["surface"]
            + "; border-top-left-radius: 15px; border-top-right-radius: 15px;"
            + " border-bottom: 1px solid "
            + UI_THEME["border"]
            + "; }"
        )
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(15, 8, 8, 8)
        title_bar_layout.setSpacing(5)
        
        # Title
        title = QLabel("⌨️ Hotkey Manager")
        title.setStyleSheet(
            "QLabel { color: "
            + UI_THEME["text"]
            + "; font-size: 16px; font-weight: 900; background: transparent; }"
        )
        title_bar_layout.addWidget(title)
        title_bar_layout.addStretch()
        
        # Close button
        close_btn = self._create_window_button("×", self.close)
        title_bar_layout.addWidget(close_btn)
        
        return title_bar
    
    def _create_window_button(self, text, callback):
        """Create a close button."""
        btn = QPushButton(text)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 6px; font-size: 20px; font-weight: 900; }"
            "QPushButton:hover { background-color: "
            + UI_THEME["danger"]
            + "; border: 1px solid "
            + UI_THEME["danger"]
            + "; }"
            "QPushButton:pressed { background-color: "
            + UI_THEME["surface"]
            + "; }"
        )
        btn.clicked.connect(callback)
        return btn
    
    def _create_content_frame(self):
        """Create the content frame with hotkey settings."""
        content_frame = QFrame()
        content_frame.setStyleSheet("QFrame { background: transparent; }")
        outer = QVBoxLayout(content_frame)
        outer.setContentsMargins(25, 20, 25, 25)
        outer.setSpacing(18)
        
        # Info label
        info = QLabel("Click on a field and press a key combination to set a hotkey.\nPress ESC to cancel while editing.")
        info.setWordWrap(True)
        info.setStyleSheet(
            "QLabel { color: "
            + UI_THEME["muted"]
            + "; font-size: 13px; padding: 12px; background-color: "
            + UI_THEME["surface"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 12px; }"
        )
        # Hotkey settings live in a scroll area so adding bindings won't squash
        # the UI; it will expand and become scrollable.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        scroll_body = QWidget()
        scroll_body.setStyleSheet("QWidget { background: transparent; }")
        content_layout = QVBoxLayout(scroll_body)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)

        content_layout.addWidget(info)

        # Hotkey settings
        self._add_hotkey_setting(content_layout, "Toggle Visibility", "toggle_visibility")
        self._add_hotkey_setting(content_layout, "Mirror Vertical", "mirror_vertical")
        self._add_hotkey_setting(content_layout, "Mirror Horizontal", "mirror_horizontal")
        self._add_hotkey_setting(content_layout, "Switch Image", "switch_image")
        self._add_hotkey_setting(content_layout, "Hold to Drag Element", "hold_to_drag")

        content_layout.addStretch(1)

        scroll.setWidget(scroll_body)
        outer.addWidget(scroll, 1)
        
        # Action buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        # Reset button
        reset_btn = self._create_button("Reset to Defaults", role="neutral")
        reset_btn.clicked.connect(self.reset_to_defaults)
        buttons_layout.addWidget(reset_btn)
        
        # Save button
        save_btn = self._create_button("Save Hotkeys", role="primary")
        save_btn.clicked.connect(self.save_hotkeys)
        buttons_layout.addWidget(save_btn)
        
        outer.addLayout(buttons_layout)
        
        return content_frame
    
    def _add_hotkey_setting(self, layout, label_text, key_name):
        """Add a hotkey setting row."""
        row = QFrame()
        row.setStyleSheet(
            "QFrame { background-color: "
            + UI_THEME["surface"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 12px; padding: 5px; }"
        )
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        
        # Label
        label = QLabel(label_text)
        label.setStyleSheet(
            "QLabel { color: "
            + UI_THEME["text"]
            + "; font-size: 14px; background: transparent; }"
        )
        label.setMinimumWidth(180)
        row_layout.addWidget(label)

        # Input fields (unlimited bindings per action via '+')
        current_values = self.current_hotkeys.get(key_name, [])
        if isinstance(current_values, str):
            current_values = [current_values]
        if not isinstance(current_values, list):
            current_values = []
        current_values = [str(v or "").strip().lower() for v in current_values if str(v or "").strip()]
        if not current_values:
            current_values = [""]

        inputs_container = QFrame()
        inputs_container.setStyleSheet("QFrame { background: transparent; }")
        inputs_layout = QVBoxLayout(inputs_container)
        inputs_layout.setContentsMargins(0, 0, 0, 0)
        inputs_layout.setSpacing(8)

        self.hotkey_inputs[key_name] = []
        self._hotkey_row_widgets[key_name] = []
        self._hotkey_inputs_layouts[key_name] = inputs_layout

        # Add-row widget (always last) so we can insert new edits above it.
        add_row = QFrame()
        add_row.setStyleSheet("QFrame { background: transparent; }")
        add_row_layout = QHBoxLayout(add_row)
        add_row_layout.setContentsMargins(0, 0, 0, 0)
        add_row_layout.setSpacing(0)

        add_btn = QPushButton("+")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setToolTip("Add another hotkey")
        add_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_btn.setFixedHeight(34)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 10px; font-size: 18px; font-weight: 900; text-align: center; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QPushButton:pressed { background-color: "
            + UI_THEME["surface"]
            + "; }"
        )
        add_btn.clicked.connect(lambda: self._add_binding_row(key_name))
        add_row_layout.addWidget(add_btn, 1)

        self._hotkey_add_row_widgets[key_name] = add_row
        inputs_layout.addWidget(add_row)

        for v in current_values:
            self._add_binding_row(key_name, initial_value=v)

        row_layout.addWidget(inputs_container)
        
        layout.addWidget(row)
    
    def _create_button(self, text: str, role: str = "neutral"):
        """Create a themed button."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        if role == "primary":
            bg = UI_THEME["accent"]
            fg = UI_THEME["bg"]
            border = UI_THEME["accent"]
        elif role == "danger":
            bg = UI_THEME["danger"]
            fg = UI_THEME["text"]
            border = UI_THEME["danger"]
        else:
            bg = UI_THEME["surface2"]
            fg = UI_THEME["text"]
            border = UI_THEME["border"]

        btn.setStyleSheet(
            "QPushButton { background-color: "
            + bg
            + "; color: "
            + fg
            + "; border: 1px solid "
            + border
            + "; border-radius: 12px; padding: 14px; font-size: 13px; font-weight: 800; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QPushButton:pressed { background-color: "
            + UI_THEME["surface"]
            + "; }"
            "QPushButton:disabled { background-color: rgba(120,120,140,60); color: rgba(255,255,255,120); border: 1px solid rgba(230,225,255,30); }"
        )
        return btn
    
    def _adjust_color_brightness(self, hex_color, factor):
        """Adjust the brightness of a hex color."""
        color = QColor(hex_color)
        h, s, v, a = color.getHsv()
        v = min(255, int(v * factor))
        color.setHsv(h, s, v, a)
        return color.name()
    
    def reset_to_defaults(self):
        """Reset all hotkeys to defaults."""
        for key_name in list(self.hotkey_inputs.keys()):
            defaults = self.default_hotkeys.get(key_name, [])
            if isinstance(defaults, str):
                defaults = [defaults]
            if not isinstance(defaults, list):
                defaults = []
            defaults = [str(v or "").strip().lower() for v in defaults if str(v or "").strip()]
            if not defaults:
                defaults = [""]
            self._set_action_bindings(key_name, defaults)

    def _make_hotkey_input(self, placeholder: str, initial_value: str) -> HotkeyLineEdit:
        input_field = HotkeyLineEdit()
        input_field.setText(str(initial_value or "").strip().lower())
        input_field.current_key = str(initial_value or "").strip().lower()
        input_field.setPlaceholderText(placeholder)
        input_field.setStyleSheet(
            "QLineEdit { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 2px solid "
            + UI_THEME["border"]
            + "; border-radius: 10px; padding: 10px; font-size: 13px; min-height: 18px; }"
            "QLineEdit:focus { border: 2px solid "
            + UI_THEME["accent"]
            + "; }"
        )
        return input_field

    def _add_binding_row(self, key_name: str, *, initial_value: str = "") -> None:
        inputs_layout = self._hotkey_inputs_layouts.get(key_name)
        if inputs_layout is None:
            return
        edits = self.hotkey_inputs.setdefault(key_name, [])
        add_row_widget = self._hotkey_add_row_widgets.get(key_name)
        insert_index = max(0, inputs_layout.count() - (1 if add_row_widget is not None else 0))

        placeholder = f"Hotkey {len(edits) + 1}" if len(edits) > 0 else "Hotkey 1"
        input_field = self._make_hotkey_input(placeholder, initial_value)
        row = QFrame()
        row.setStyleSheet("QFrame { background: transparent; }")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(input_field, 1)

        del_btn = QPushButton("×")
        del_btn.setFixedSize(28, 28)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setToolTip("Remove this hotkey")
        del_btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 10px; font-size: 18px; font-weight: 900; }"
            "QPushButton:hover { background-color: "
            + UI_THEME["danger"]
            + "; border: 1px solid "
            + UI_THEME["danger"]
            + "; }"
            "QPushButton:pressed { background-color: "
            + UI_THEME["surface"]
            + "; }"
        )
        del_btn.clicked.connect(lambda: self._remove_binding_row(key_name, input_field))
        row_layout.addWidget(del_btn)

        edits.append(input_field)
        self._hotkey_row_widgets.setdefault(key_name, []).append(row)
        inputs_layout.insertWidget(insert_index, row)

    def _remove_binding_row(self, key_name: str, edit: HotkeyLineEdit) -> None:
        edits = self.hotkey_inputs.get(key_name) or []
        if edit not in edits:
            return

        # Keep at least one input row so the UI doesn't collapse.
        if len(edits) <= 1:
            try:
                edit.current_key = ""
                edit.setText("")
            except Exception:
                pass
            return

        idx = edits.index(edit)
        edits.pop(idx)

        rows = self._hotkey_row_widgets.get(key_name) or []
        row = rows.pop(idx) if idx < len(rows) else None
        if row is not None:
            try:
                row.setParent(None)
                row.deleteLater()
            except Exception:
                pass
        else:
            try:
                edit.setParent(None)
                edit.deleteLater()
            except Exception:
                pass

        # Renumber placeholders after deletion.
        self._renumber_action_placeholders(key_name)

    def _renumber_action_placeholders(self, key_name: str) -> None:
        edits = self.hotkey_inputs.get(key_name) or []
        for i, e in enumerate(edits, start=1):
            try:
                e.setPlaceholderText(f"Hotkey {i}")
            except Exception:
                pass

    def _set_action_bindings(self, key_name: str, values: list[str]) -> None:
        inputs_layout = self._hotkey_inputs_layouts.get(key_name)
        if inputs_layout is None:
            return

        # Remove existing row widgets.
        for row in self._hotkey_row_widgets.get(key_name, []) or []:
            try:
                row.setParent(None)
                row.deleteLater()
            except Exception:
                pass
        self.hotkey_inputs[key_name] = []
        self._hotkey_row_widgets[key_name] = []

        # Ensure at least one row.
        cleaned = [str(v or "").strip().lower() for v in (values or []) if str(v or "").strip()]
        if not cleaned:
            cleaned = [""]

        for v in cleaned:
            self._add_binding_row(key_name, initial_value=v)

        self._renumber_action_placeholders(key_name)
    
    def save_hotkeys(self):
        """Save the current hotkey configuration."""
        # Collect all hotkeys
        new_hotkeys = {}
        for key_name, edits in self.hotkey_inputs.items():
            values = []
            for edit in edits:
                hk = str(edit.current_key or "").strip().lower()
                if hk:
                    values.append(hk)
            # Keep file format stable (always a list). Empty list disables the action hotkey.
            new_hotkeys[key_name] = values
        
        # Check for duplicates across all non-empty bindings
        hotkey_values = []
        for v in new_hotkeys.values():
            if isinstance(v, str):
                v = [v]
            if isinstance(v, list):
                for hk in v:
                    hk = str(hk or "").strip().lower()
                    if hk:
                        hotkey_values.append(hk)
        if len(hotkey_values) != len(set(hotkey_values)):
            QMessageBox.warning(
                self,
                "Duplicate Hotkeys",
                "You have assigned the same hotkey to multiple actions. Please use unique hotkeys."
            )
            return
        
        # Save to file
        try:
            with open(self.config_file, 'w') as f:
                json.dump(new_hotkeys, f, indent=4)
            
            self.current_hotkeys = new_hotkeys
            self.hotkeys_updated.emit(new_hotkeys)
            
            # Reload hotkeys immediately
            from hotkeys import reload_hotkeys
            reload_hotkeys()
            
            QMessageBox.information(
                self,
                "Hotkeys Saved",
                "Hotkeys have been saved and applied successfully!"
            )
            self.close()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save hotkeys: {str(e)}"
            )
    
    def load_hotkeys(self):
        """Load hotkeys from config file."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    raw = json.load(f)
                    if not isinstance(raw, dict):
                        return self.default_hotkeys.copy()
                    normalized = {}
                    for key, defaults in self.default_hotkeys.items():
                        v = raw.get(key, defaults)
                        if isinstance(v, str):
                            v = [v]
                        if not isinstance(v, list):
                            v = list(defaults)
                        v = [str(x or "").strip().lower() for x in v if str(x or "").strip()]
                        normalized[key] = v
                    return normalized
            except:
                pass
        return self.default_hotkeys.copy()
    
    def center_on_screen(self):
        """Center the dialog on screen."""
        screen = self.screen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
    
    def mousePressEvent(self, event):
        """Handle mouse press for window dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._hit_test_edges(event.position())
            if edges:
                self._resizing = True
                self._resize_edges = edges
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
                event.accept()
                return

            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for window dragging."""
        if self._resizing and self._resize_start_pos is not None and self._resize_start_geom is not None:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geom = self._resize_start_geom
            x = geom.x()
            y = geom.y()
            w = geom.width()
            h = geom.height()

            if "left" in self._resize_edges:
                x = geom.x() + delta.x()
                w = geom.width() - delta.x()
            if "right" in self._resize_edges:
                w = geom.width() + delta.x()
            if "top" in self._resize_edges:
                y = geom.y() + delta.y()
                h = geom.height() - delta.y()
            if "bottom" in self._resize_edges:
                h = geom.height() + delta.y()

            w = max(self.minimumWidth(), w)
            h = max(self.minimumHeight(), h)
            self.setGeometry(x, y, w, h)
            event.accept()
            return

        # Update cursor when hovering near edges.
        if event.buttons() == Qt.MouseButton.NoButton:
            edges = self._hit_test_edges(event.position())
            self.setCursor(self._cursor_for_edges(edges))

        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            self._resize_edges = set()
            self._resize_start_pos = None
            self._resize_start_geom = None
            self.drag_position = None
        super().mouseReleaseEvent(event)
