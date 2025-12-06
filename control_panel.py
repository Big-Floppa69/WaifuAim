"""
Control panel widget for managing crosshair settings.
"""
from PyQt6.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QSlider, QFrame, 
                             QGraphicsDropShadowEffect)
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtCore import Qt
from utils import mirror_vertical, mirror_horizontal, get_art_list, transparent
from image_manager import ImageManagerDialog
from hotkey_manager import HotkeyManagerDialog
from standard_crosshair import StandardCrosshairDialog


class DarkControlPanel(QWidget):
    """A dark-themed control panel for managing crosshair settings."""
    
    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.label = label
        self.is_visible = False
        self.drag_position = None
        self.current_image_index = 0
        self.image_list = get_art_list()
        self.opacity_actions = {}
        self.image_manager = None
        self.hotkey_manager = None
        self.crosshair_dialog = None
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Main container with dark background and rounded edges
        main_frame = self._create_main_frame()
        
        # Layout
        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Title bar with buttons
        title_bar = self._create_title_bar()
        layout.addWidget(title_bar)
        
        # Content container
        content_frame = self._create_content_frame()
        layout.addWidget(content_frame)
        
        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_frame)
        
        self.setFixedWidth(320)
        self.adjustSize()
    
    def _create_main_frame(self):
        """Create the main frame with styling and shadow effect."""
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
        """Create the title bar with minimize and close buttons."""
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
        title = QLabel("Crosshair Control")
        title.setStyleSheet("""
            QLabel {
                color: #E0E0E0;
                font-size: 14px;
                font-weight: bold;
                background: transparent;
            }
        """)
        title_bar_layout.addWidget(title)
        title_bar_layout.addStretch()
        
        # Minimize button
        minimize_btn = self._create_window_button("−", self.hide)
        title_bar_layout.addWidget(minimize_btn)
        
        # Close button
        close_btn = self._create_window_button("×", QApplication.quit, is_close=True)
        title_bar_layout.addWidget(close_btn)
        
        return title_bar
    
    def _create_window_button(self, text, callback, is_close=False):
        """Create a minimize or close button for the title bar."""
        btn = QPushButton(text)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        hover_color = "rgba(200, 50, 50, 200)" if is_close else "rgba(90, 90, 100, 200)"
        font_size = "20px" if is_close else "18px"
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(70, 70, 80, 150);
                color: #E0E0E0;
                border: none;
                border-radius: 4px;
                font-size: {font_size};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: rgba(60, 60, 70, 200);
            }}
        """)
        btn.clicked.connect(callback)
        return btn
    
    def _create_content_frame(self):
        """Create the content frame with all controls."""
        content_frame = QFrame()
        content_frame.setStyleSheet("QFrame { background: transparent; }")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(20, 15, 20, 20)
        content_layout.setSpacing(15)
        
        # Visibility toggle button
        self.toggle_btn = self.create_button("👁️ Hide Crosshair", "#4CAF50")
        self.toggle_btn.clicked.connect(self.toggle_crosshair)
        content_layout.addWidget(self.toggle_btn)

        # Standard crosshair button
        standard_btn = self.create_button("🎯 Standard Crosshair", "#00BCD4")
        standard_btn.clicked.connect(self.open_standard_crosshair_dialog)
        content_layout.addWidget(standard_btn)
        
        # Mirror Vertical button
        mirror_v_btn = self.create_button("🔄 Mirror Vertical", "#2196F3")
        mirror_v_btn.clicked.connect(lambda: mirror_vertical(self.label, self.label.pixmap()))
        content_layout.addWidget(mirror_v_btn)
        
        # Mirror Horizontal button
        mirror_h_btn = self.create_button("↔️ Mirror Horizontal", "#03A9F4")
        mirror_h_btn.clicked.connect(lambda: mirror_horizontal(self.label, self.label.pixmap()))
        content_layout.addWidget(mirror_h_btn)
        
        # Switch image button
        switch_btn = self.create_button("🖼️ Next Image", "#9C27B0")
        switch_btn.clicked.connect(self.switch_image)
        content_layout.addWidget(switch_btn)
        
        # Manage images button
        manage_btn = self.create_button("📁 Manage Images", "#FF9800")
        manage_btn.clicked.connect(self.open_image_manager)
        content_layout.addWidget(manage_btn)
        
        # Hotkey manager button
        hotkey_btn = self.create_button("⌨️ Customize Hotkeys", "#673AB7")
        hotkey_btn.clicked.connect(self.open_hotkey_manager)
        content_layout.addWidget(hotkey_btn)
        
        # Opacity section
        self._add_opacity_controls(content_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: rgba(100, 100, 120, 80);")
        separator.setMaximumHeight(1)
        content_layout.addWidget(separator)
        
        # Hotkey info
        from hotkeys import get_current_hotkeys
        hotkey_text = get_current_hotkeys()
        info_label = QLabel(f"{hotkey_text}")
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet("""
            QLabel {
                color: rgba(200, 200, 200, 150);
                font-size: 10px;
                padding: 5px;
                background: transparent;
            }
        """)
        content_layout.addWidget(info_label)
        
        return content_frame
    
    def _add_opacity_controls(self, layout):
        """Add opacity slider and label to the layout."""
        # Opacity label
        opacity_label = QLabel("Opacity")
        opacity_label.setStyleSheet("""
            QLabel {
                color: #B0B0B0;
                font-size: 13px;
                padding: 5px 0;
                background: transparent;
            }
        """)
        layout.addWidget(opacity_label)
        
        # Opacity slider container
        opacity_container = QFrame()
        opacity_container.setStyleSheet("""
            QFrame {
                background-color: rgba(40, 40, 50, 150);
                border-radius: 10px;
                padding: 10px;
            }
        """)
        opacity_layout = QHBoxLayout(opacity_container)
        opacity_layout.setContentsMargins(10, 10, 10, 10)
        
        # Slider
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(25)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setStyleSheet("""
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
        """)
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        
        # Value label
        self.opacity_value = QLabel("100%")
        self.opacity_value.setStyleSheet("""
            QLabel {
                color: #E0E0E0;
                font-size: 14px;
                font-weight: bold;
                min-width: 45px;
                background: transparent;
            }
        """)
        
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_value)
        layout.addWidget(opacity_container)
    
    def create_button(self, text, color):
        """Create a styled button with hover effects."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {self.adjust_color_brightness(color, 1.2)};
            }}
            QPushButton:pressed {{
                background-color: {self.adjust_color_brightness(color, 0.8)};
            }}
        """)
        return btn
    
    def adjust_color_brightness(self, hex_color, factor):
        """Adjust color brightness by a factor."""
        color = QColor(hex_color)
        h, s, v, a = color.getHsv()
        v = min(255, int(v * factor))
        color.setHsv(h, s, v, a)
        return color.name()
    
    def toggle_crosshair(self):
        """Toggle crosshair visibility."""
        if self.label.isVisible():
            self.label.hide()
            self.toggle_btn.setText("👁️ Show Crosshair")
        else:
            self.label.show()
            self.toggle_btn.setText("👁️ Hide Crosshair")
    
    def change_opacity(self, value):
        """Change the opacity of the crosshair."""
        opacity = value / 100.0
        transparent(self.label, opacity)
        self.opacity_value.setText(f"{value}%")
        
        # Update check marks in tray menu
        if self.opacity_actions:
            for opacity_val, action in self.opacity_actions.items():
                action.setChecked(value == opacity_val)
    
    def set_opacity(self, value):
        """Set opacity from external source (e.g., tray menu)."""
        self.opacity_slider.setValue(value)
    
    def switch_image(self):
        """Switch to the next crosshair image."""
        # Refresh image list in case new images were added
        self.image_list = get_art_list()
        if not self.image_list:
            return
        self.current_image_index = (self.current_image_index + 1) % len(self.image_list)
        pix = QPixmap(self.image_list[self.current_image_index])
        self.label.setPixmap(pix)
    
    def open_image_manager(self):
        """Open the image manager dialog."""
        if self.image_manager is None:
            self.image_manager = ImageManagerDialog(self)
        self.image_manager.show()
        self.image_manager.raise_()
        self.image_manager.activateWindow()
    
    def open_hotkey_manager(self):
        """Open the hotkey manager dialog."""
        if self.hotkey_manager is None:
            self.hotkey_manager = HotkeyManagerDialog(self)
            # Connect signal to refresh control panel when hotkeys are updated
            self.hotkey_manager.hotkeys_updated.connect(self._refresh_hotkey_display)
        self.hotkey_manager.show()
        self.hotkey_manager.raise_()
        self.hotkey_manager.activateWindow()

    def open_standard_crosshair_dialog(self):
        """Open the standard crosshair configuration dialog."""
        if self.crosshair_dialog is None:
            self.crosshair_dialog = StandardCrosshairDialog(self.label, self)
            self.crosshair_dialog.destroyed.connect(lambda: setattr(self, "crosshair_dialog", None))
        self.crosshair_dialog.show()
        self.crosshair_dialog.raise_()
        self.crosshair_dialog.activateWindow()
    
    def _refresh_hotkey_display(self, hotkeys):
        """Refresh the hotkey info display after changes."""
        # This would require rebuilding the UI or updating the label
        # For now, we can just close and reopen the panel
        pass
    
    def toggle_panel(self):
        """Toggle the control panel visibility."""
        if self.is_visible:
            self.hide()
            self.is_visible = False
        else:
            # Position near top-right corner
            screen = QApplication.primaryScreen().geometry()
            self.move(screen.width() - self.width() - 20, 20)
            self.show()
            self.is_visible = True
    
    def mousePressEvent(self, event):
        """Handle mouse press events for dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move events for dragging."""
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
