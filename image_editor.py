"""
Image Editor Dialog with positioning tools.
"""
import os
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QGraphicsDropShadowEffect, 
                             QMessageBox, QApplication, QSlider, QFileDialog,
                             QGraphicsView, QGraphicsScene, QGraphicsPixmapItem)
from PyQt6.QtGui import QPixmap, QColor, QPainter, QPen
from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from utils import UI_THEME


class ImageCanvas(QGraphicsView):
    """Custom canvas with centered guides and draggable image."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # Canvas settings
        self.setStyleSheet(
            "QGraphicsView { background-color: "
            + UI_THEME["bg2"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 12px; }"
        )
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        
        # Image item
        self.image_item = None
        self.original_pixmap = None
        self.zoom_level = 1.0
        self.rotation_angle = 0
        
        # Canvas size (1920x1080 for crosshair preview)
        self.canvas_width = 1920
        self.canvas_height = 1080
        self.setSceneRect(0, 0, self.canvas_width, self.canvas_height)
        self.setFixedSize(800, 450)  # Display at ~40% scale
        self.scale(800 / self.canvas_width, 450 / self.canvas_height)
        
    def drawBackground(self, painter, rect):
        """Draw background with center guides."""
        super().drawBackground(painter, rect)
        
        # Draw center lines
        painter.setPen(QPen(QColor(UI_THEME["muted"]), 2, Qt.PenStyle.DashLine))
        
        # Vertical center line
        center_x = self.canvas_width / 2
        painter.drawLine(int(center_x), 0, int(center_x), self.canvas_height)
        
        # Horizontal center line
        center_y = self.canvas_height / 2
        painter.drawLine(0, int(center_y), self.canvas_width, int(center_y))
        
        # Draw center crosshair
        painter.setPen(QPen(QColor(UI_THEME["accent"]), 1))
        crosshair_size = 20
        painter.drawLine(int(center_x - crosshair_size), int(center_y), 
                        int(center_x + crosshair_size), int(center_y))
        painter.drawLine(int(center_x), int(center_y - crosshair_size), 
                        int(center_x), int(center_y + crosshair_size))
    
    def set_image(self, pixmap):
        """Set the image to display and center it."""
        self.original_pixmap = pixmap
        self.rotation_angle = 0
        self.zoom_level = 1.0
        self._update_image()
    
    def _update_image(self):
        """Update the displayed image with current transformations."""
        if self.original_pixmap is None:
            return
        
        # Remove old image
        if self.image_item:
            self.scene.removeItem(self.image_item)
        
        # Apply transformations
        pixmap = self.original_pixmap.scaled(
            int(self.original_pixmap.width() * self.zoom_level),
            int(self.original_pixmap.height() * self.zoom_level),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        # Create new item
        self.image_item = QGraphicsPixmapItem(pixmap)
        self.image_item.setFlags(
            QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable
        )
        
        # Apply rotation
        self.image_item.setTransformOriginPoint(pixmap.width() / 2, pixmap.height() / 2)
        self.image_item.setRotation(self.rotation_angle)
        
        # Center the image
        center_x = self.canvas_width / 2 - pixmap.width() / 2
        center_y = self.canvas_height / 2 - pixmap.height() / 2
        self.image_item.setPos(center_x, center_y)
        
        self.scene.addItem(self.image_item)
    
    def set_zoom(self, zoom):
        """Set zoom level (0.1 to 3.0)."""
        self.zoom_level = zoom
        self._update_image()
    
    def set_rotation(self, angle):
        """Set rotation angle."""
        self.rotation_angle = angle
        self._update_image()
    
    def get_final_image(self):
        """Get the final positioned image as QPixmap."""
        if not self.image_item:
            return None
        
        # Create a transparent canvas
        final_image = QPixmap(self.canvas_width, self.canvas_height)
        final_image.fill(Qt.GlobalColor.transparent)
        
        # Paint the scene onto it
        painter = QPainter(final_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # Only render the image item
        self.scene.render(painter, QRectF(0, 0, self.canvas_width, self.canvas_height),
                         QRectF(0, 0, self.canvas_width, self.canvas_height))
        painter.end()
        
        return final_image


class ImageEditorDialog(QWidget):
    """Dialog for editing images with positioning tools."""
    
    image_saved = pyqtSignal(str)  # Signal emitted when image is saved
    
    def __init__(self, image_path=None, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.drag_position = None
        self.current_pixmap = None
        
        self.init_ui()
        
        if image_path and os.path.exists(image_path):
            self.load_image(image_path)
    
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
        
        self.setFixedSize(900, 700)
        self.center_on_screen()
    
    def _create_main_frame(self):
        """Create the main frame with styling and shadow effect."""
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
        """Create the title bar with close button."""
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
        title = QLabel("✂️ Image Editor")
        title.setStyleSheet(
            "QLabel { color: "
            + UI_THEME["text"]
            + "; font-size: 14px; font-weight: 800; background: transparent; }"
        )
        title_bar_layout.addWidget(title)
        title_bar_layout.addStretch()
        
        # Close button
        close_btn = self._create_window_button("×", self.close)
        title_bar_layout.addWidget(close_btn)
        
        return title_bar
    
    def _create_window_button(self, text, callback):
        """Create a close button for the title bar."""
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
        """Create the content frame with all controls."""
        content_frame = QFrame()
        content_frame.setStyleSheet("QFrame { background: transparent; }")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(20, 15, 20, 20)
        content_layout.setSpacing(15)
        
        # Canvas
        self.canvas = ImageCanvas()
        content_layout.addWidget(self.canvas)
        
        # Controls section
        controls_frame = self._create_controls_section()
        content_layout.addWidget(controls_frame)
        
        # Action buttons
        buttons_layout = self._create_action_buttons()
        content_layout.addLayout(buttons_layout)
        
        return content_frame
    
    def _create_controls_section(self):
        """Create the controls section with sliders."""
        controls_frame = QFrame()
        controls_frame.setStyleSheet(
            "QFrame { background-color: "
            + UI_THEME["surface"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 12px; padding: 15px; }"
        )
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setSpacing(12)
        
        # Zoom control
        zoom_layout = QHBoxLayout()
        zoom_label = QLabel("Zoom:")
        zoom_label.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 12px;")
        zoom_layout.addWidget(zoom_label)
        
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(10)
        self.zoom_slider.setMaximum(300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setStyleSheet(self._get_slider_style())
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        zoom_layout.addWidget(self.zoom_slider)
        
        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setStyleSheet(
            "color: " + UI_THEME["text"] + "; font-size: 12px; min-width: 45px;"
        )
        zoom_layout.addWidget(self.zoom_value_label)
        
        controls_layout.addLayout(zoom_layout)
        
        # Rotation control
        rotation_layout = QHBoxLayout()
        rotation_label = QLabel("Rotation:")
        rotation_label.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 12px;")
        rotation_layout.addWidget(rotation_label)
        
        self.rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.rotation_slider.setMinimum(0)
        self.rotation_slider.setMaximum(359)
        self.rotation_slider.setValue(0)
        self.rotation_slider.setStyleSheet(self._get_slider_style())
        self.rotation_slider.valueChanged.connect(self.on_rotation_changed)
        rotation_layout.addWidget(self.rotation_slider)
        
        self.rotation_value_label = QLabel("0°")
        self.rotation_value_label.setStyleSheet(
            "color: " + UI_THEME["text"] + "; font-size: 12px; min-width: 45px;"
        )
        rotation_layout.addWidget(self.rotation_value_label)
        
        controls_layout.addLayout(rotation_layout)
        
        return controls_frame
    
    def _get_slider_style(self):
        """Get slider stylesheet."""
        return (
            "QSlider::groove:horizontal { border: none; height: 6px; background: "
            + UI_THEME["surface2"]
            + "; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: "
            + UI_THEME["accent"]
            + "; border-radius: 3px; }"
            "QSlider::handle:horizontal { background: "
            + UI_THEME["accent"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; width: 16px; margin: -5px 0; border-radius: 8px; }"
            "QSlider::handle:horizontal:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
    
    def _create_action_buttons(self):
        """Create action buttons layout."""
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        # Load image button
        load_btn = self._create_button("📁 Load Image", role="neutral")
        load_btn.clicked.connect(self.load_image_dialog)
        buttons_layout.addWidget(load_btn)
        
        # Reset button
        reset_btn = self._create_button("🔄 Reset", role="neutral")
        reset_btn.clicked.connect(self.reset_image)
        buttons_layout.addWidget(reset_btn)
        
        # Save button
        save_btn = self._create_button("💾 Save", role="primary")
        save_btn.clicked.connect(self.save_image)
        buttons_layout.addWidget(save_btn)
        
        return buttons_layout
    
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
            + "; border-radius: 10px; padding: 10px 16px; font-size: 12px; font-weight: 700; }"
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
        """Adjust color brightness by a factor."""
        color = QColor(hex_color)
        h, s, v, a = color.getHsv()
        v = min(255, int(v * factor))
        color.setHsv(h, s, v, a)
        return color.name()
    
    def center_on_screen(self):
        """Center the dialog on the screen."""
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
    
    def load_image_dialog(self):
        """Open file dialog to load an image."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        
        if file_path:
            self.load_image(file_path)
    
    def load_image(self, file_path):
        """Load an image into the editor."""
        try:
            self.image_path = file_path
            
            # Load image as QPixmap
            self.current_pixmap = QPixmap(file_path)
            if self.current_pixmap.isNull():
                raise ValueError("Failed to load image")
            
            self.canvas.set_image(self.current_pixmap)
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load image: {str(e)}")
    
    def reset_image(self):
        """Reset image to original state."""
        if self.image_path and os.path.exists(self.image_path):
            self.load_image(self.image_path)
            self.zoom_slider.setValue(100)
            self.rotation_slider.setValue(0)
    
    def save_image(self):
        """Save the edited image."""
        if self.canvas.image_item is None:
            QMessageBox.information(self, "No Image", "No image to save.")
            return
        
        # Get save location
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Image",
            "display_images/edited_image.png",
            "PNG Image (*.png)"
        )
        
        if file_path:
            try:
                # Get final image from canvas
                final_pixmap = self.canvas.get_final_image()
                
                # Save
                final_pixmap.save(file_path, "PNG")
                
                QMessageBox.information(self, "Success", f"Image saved to:\n{file_path}")
                self.image_saved.emit(file_path)
                
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save image: {str(e)}")
    
    def on_zoom_changed(self, value):
        """Handle zoom slider change."""
        zoom = value / 100.0
        self.canvas.set_zoom(zoom)
        self.zoom_value_label.setText(f"{value}%")
    
    def on_rotation_changed(self, value):
        """Handle rotation slider change."""
        self.canvas.set_rotation(value)
        self.rotation_value_label.setText(f"{value}°")
    
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
