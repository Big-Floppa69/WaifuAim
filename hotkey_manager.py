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


class HotkeyLineEdit(QLineEdit):
    """Custom line edit that captures key combinations."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Click and press a key...")
        self.current_key = ""
        self.original_key = ""
        
    def focusInEvent(self, event):
        """Store original key when focused."""
        super().focusInEvent(event)
        self.original_key = self.current_key
        self.setText("Press a key or ESC to cancel...")
        self.setStyleSheet(self.styleSheet() + "color: rgba(200, 200, 220, 150);")
        
    def focusOutEvent(self, event):
        """Restore color when focus lost."""
        super().focusOutEvent(event)
        if self.text() == "Press a key or ESC to cancel...":
            self.setText(self.current_key)
        self.setStyleSheet(self.styleSheet().replace("color: rgba(200, 200, 220, 150);", "color: #E0E0E0;"))
        
    def keyPressEvent(self, event: QKeyEvent):
        """Capture key press and display it."""
        key = event.key()
        
        # Handle Escape to cancel
        if key == Qt.Key.Key_Escape:
            self.current_key = self.original_key
            self.setText(self.current_key if self.current_key else "")
            self.clearFocus()
            return
        
        # Ignore modifier-only presses
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
            
        # Get key name
        key_name = self._get_key_name(key)
        
        # Build modifier string
        modifiers = []
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            modifiers.append("ctrl")
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            modifiers.append("alt")
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            modifiers.append("shift")
            
        # Combine modifiers and key
        if modifiers:
            self.current_key = "+".join(modifiers) + "+" + key_name
        else:
            self.current_key = key_name
            
        self.setText(self.current_key)
        self.clearFocus()
    
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
        self.hotkey_inputs = {}
        self.default_hotkeys = {
            "toggle_visibility": "f1",
            "mirror_vertical": "f3",
            "mirror_horizontal": "f4",
            "switch_image": "f2"
        }
        self.current_hotkeys = self.load_hotkeys()
        self.init_ui()
        
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
        main_frame.setStyleSheet("""
            QFrame#mainFrame {
                background-color: rgba(20, 20, 25, 240);
                border-radius: 15px;
                border: 1px solid rgba(100, 100, 120, 100);
            }
        """)
        
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
        title_bar.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 35, 255);
                border-top-left-radius: 15px;
                border-top-right-radius: 15px;
            }
        """)
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(15, 8, 8, 8)
        title_bar_layout.setSpacing(5)
        
        # Title
        title = QLabel("⌨️ Hotkey Manager")
        title.setStyleSheet("""
            QLabel {
                color: #E0E0E0;
                font-size: 16px;
                font-weight: bold;
                background: transparent;
            }
        """)
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
        btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(70, 70, 80, 150);
                color: #E0E0E0;
                border: none;
                border-radius: 4px;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(200, 50, 50, 200);
            }
            QPushButton:pressed {
                background-color: rgba(60, 60, 70, 200);
            }
        """)
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
        info.setStyleSheet("""
            QLabel {
                color: rgba(200, 200, 220, 200);
                font-size: 13px;
                padding: 12px;
                background-color: rgba(40, 40, 50, 150);
                border-radius: 8px;
            }
        """)
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
        reset_btn = self._create_button("Reset to Defaults", "#FF5722")
        reset_btn.clicked.connect(self.reset_to_defaults)
        buttons_layout.addWidget(reset_btn)
        
        # Save button
        save_btn = self._create_button("Save Hotkeys", "#4CAF50")
        save_btn.clicked.connect(self.save_hotkeys)
        buttons_layout.addWidget(save_btn)
        
        content_layout.addLayout(buttons_layout)
        
        return content_frame
    
    def _add_hotkey_setting(self, layout, label_text, key_name):
        """Add a hotkey setting row."""
        row = QFrame()
        row.setStyleSheet("""
            QFrame {
                background-color: rgba(40, 40, 50, 150);
                border-radius: 8px;
                padding: 5px;
            }
        """)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        
        # Label
        label = QLabel(label_text)
        label.setStyleSheet("""
            QLabel {
                color: #E0E0E0;
                font-size: 14px;
                background: transparent;
            }
        """)
        label.setMinimumWidth(180)
        row_layout.addWidget(label)
        
        # Input field
        input_field = HotkeyLineEdit()
        input_field.setText(self.current_hotkeys.get(key_name, ""))
        input_field.current_key = self.current_hotkeys.get(key_name, "")
        input_field.setStyleSheet("""
            QLineEdit {
                background-color: rgba(60, 60, 70, 200);
                color: #E0E0E0;
                border: 2px solid rgba(103, 126, 234, 100);
                border-radius: 6px;
                padding: 12px;
                font-size: 13px;
                min-height: 20px;
            }
            QLineEdit:focus {
                border: 2px solid rgba(103, 126, 234, 255);
            }
        """)
        self.hotkey_inputs[key_name] = input_field
        row_layout.addWidget(input_field)
        
        layout.addWidget(row)
    
    def _create_button(self, text, color):
        """Create a styled button."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Calculate hover color
        hover_color = self._adjust_color_brightness(color, 1.2)
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 14px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {self._adjust_color_brightness(color, 0.8)};
            }}
        """)
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
        for key_name, input_field in self.hotkey_inputs.items():
            default_key = self.default_hotkeys.get(key_name, "")
            input_field.setText(default_key)
            input_field.current_key = default_key
    
    def save_hotkeys(self):
        """Save the current hotkey configuration."""
        # Collect all hotkeys
        new_hotkeys = {}
        for key_name, input_field in self.hotkey_inputs.items():
            hotkey = input_field.current_key.strip()
            if hotkey:
                new_hotkeys[key_name] = hotkey
            else:
                new_hotkeys[key_name] = self.default_hotkeys.get(key_name, "")
        
        # Check for duplicates
        hotkey_values = list(new_hotkeys.values())
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
                    return json.load(f)
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
