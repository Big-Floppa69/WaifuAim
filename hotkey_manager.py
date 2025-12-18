"""
Hotkey Manager Dialog for customizing keyboard shortcuts.
"""
import json
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QGraphicsDropShadowEffect, QLineEdit,
                             QMessageBox)
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
        self.config_file = "hotkey_config.json"
        # key_name -> list[HotkeyLineEdit] (multiple bindings per action)
        self.hotkey_inputs: dict[str, list[HotkeyLineEdit]] = {}
        self.default_hotkeys = {
            "toggle_visibility": ["f1", ""],
            "mirror_vertical": ["f3", ""],
            "mirror_horizontal": ["f4", ""],
            "switch_image": ["f2", ""],
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
        layout.addWidget(title_bar)
        
        # Content frame
        content_frame = self._create_content_frame()
        layout.addWidget(content_frame)
        
        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_frame)
        
        self.setFixedSize(650, 550)
        self.center_on_screen()
    
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
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(25, 20, 25, 25)
        content_layout.setSpacing(18)
        
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
        content_layout.addWidget(info)
        
        # Hotkey settings
        self._add_hotkey_setting(content_layout, "Toggle Visibility", "toggle_visibility")
        self._add_hotkey_setting(content_layout, "Mirror Vertical", "mirror_vertical")
        self._add_hotkey_setting(content_layout, "Mirror Horizontal", "mirror_horizontal")
        self._add_hotkey_setting(content_layout, "Switch Image", "switch_image")
        
        content_layout.addStretch()
        
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
        
        content_layout.addLayout(buttons_layout)
        
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
        
        # Input fields (two bindings per action)
        current_values = self.current_hotkeys.get(key_name, ["", ""])
        if isinstance(current_values, str):
            current_values = [current_values, ""]
        if not isinstance(current_values, list):
            current_values = ["", ""]
        current_values = [str(v or "").strip().lower() for v in current_values]
        while len(current_values) < 2:
            current_values.append("")

        inputs_container = QFrame()
        inputs_container.setStyleSheet("QFrame { background: transparent; }")
        inputs_layout = QVBoxLayout(inputs_container)
        inputs_layout.setContentsMargins(0, 0, 0, 0)
        inputs_layout.setSpacing(8)

        edits: list[HotkeyLineEdit] = []
        for i in range(2):
            input_field = HotkeyLineEdit()
            input_field.setText(current_values[i])
            input_field.current_key = current_values[i]
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
            input_field.setPlaceholderText(f"Hotkey {i + 1} (optional)" if i == 1 else "Hotkey 1")
            edits.append(input_field)
            inputs_layout.addWidget(input_field)

        self.hotkey_inputs[key_name] = edits
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
        for key_name, edits in self.hotkey_inputs.items():
            defaults = self.default_hotkeys.get(key_name, ["", ""])
            if isinstance(defaults, str):
                defaults = [defaults, ""]
            while len(defaults) < 2:
                defaults.append("")
            for i, edit in enumerate(edits):
                value = str(defaults[i] or "").strip().lower()
                edit.setText(value)
                edit.current_key = value
    
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
            # Keep file format stable (always a list), pad to 2 for UI.
            while len(values) < 2:
                values.append("")
            new_hotkeys[key_name] = values[:2]
        
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
                            v = [v, ""]
                        if not isinstance(v, list):
                            v = list(defaults)
                        v = [str(x or "").strip().lower() for x in v]
                        while len(v) < 2:
                            v.append("")
                        normalized[key] = v[:2]
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
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for window dragging."""
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
