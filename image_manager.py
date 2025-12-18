"""
Image Manager Dialog for adding and managing crosshair images.
"""
import os
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QListWidget, QListWidgetItem, QFileDialog, 
                             QLabel, QFrame, QGraphicsDropShadowEffect, 
                             QMessageBox, QApplication)
from PyQt6.QtGui import QPixmap, QColor, QIcon
from PyQt6.QtCore import Qt, QSize
from image_editor import ImageEditorDialog
from utils import UI_THEME


class ImageManagerDialog(QWidget):
    """Dialog for managing crosshair images."""
    
    def __init__(self, parent=None, images_folder="display_images"):
        super().__init__(parent)
        # Use absolute path to ensure we have proper path handling
        self.images_folder = os.path.abspath(images_folder)
        self.drag_position = None
        self.image_editor = None
        self.init_ui()
        self.load_images()
    
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
        
        self.setFixedSize(500, 600)
        self.center_on_screen()
    
    def _create_main_frame(self):
        """Create the main frame with styling and shadow effect."""
        main_frame = QFrame(self)
        main_frame.setObjectName("mainFrame")
        main_frame.setStyleSheet(
            "QFrame#mainFrame {"
            "background-color: "
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
        title = QLabel("🖼️ Image Manager")
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
        
        # Info label
        info_label = QLabel("Manage your crosshair images")
        info_label.setStyleSheet(
            "QLabel { color: "
            + UI_THEME["muted"]
            + "; font-size: 12px; padding: 5px; background: transparent; }"
        )
        content_layout.addWidget(info_label)
        
        # Image list
        self.image_list = QListWidget()
        self.image_list.setStyleSheet(
            "QListWidget { background-color: "
            + UI_THEME["surface"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 10px; color: "
            + UI_THEME["text"]
            + "; padding: 6px; font-size: 13px; }"
            "QListWidget::item { padding: 8px; border-radius: 8px; margin: 2px; }"
            "QListWidget::item:selected { background-color: "
            + UI_THEME["accent"]
            + "; color: "
            + UI_THEME["bg"]
            + "; }"
            "QListWidget::item:hover { background-color: "
            + UI_THEME["surface2"]
            + "; }"
        )
        self.image_list.setIconSize(QSize(48, 48))
        content_layout.addWidget(self.image_list)
        
        # Button container
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        # Add image button
        add_btn = self._create_button("➕ Add Image", role="neutral")
        add_btn.clicked.connect(self.add_image)
        button_layout.addWidget(add_btn)
        
        # Edit image button
        edit_btn = self._create_button("✏️ Edit", role="neutral")
        edit_btn.clicked.connect(self.edit_image)
        button_layout.addWidget(edit_btn)
        
        # Remove image button
        remove_btn = self._create_button("🗑️ Remove", role="danger")
        remove_btn.clicked.connect(self.remove_image)
        button_layout.addWidget(remove_btn)
        
        content_layout.addLayout(button_layout)
        
        # Refresh button
        refresh_btn = self._create_button("🔄 Refresh List", role="primary")
        refresh_btn.clicked.connect(self.load_images)
        content_layout.addWidget(refresh_btn)
        
        # Info text
        info_text = QLabel("Supported formats: PNG, JPG, JPEG, WEBP")
        info_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_text.setStyleSheet("""
            QLabel {
                color: rgba(200, 200, 200, 120);
                font-size: 10px;
                padding: 5px;
                background: transparent;
            }
        """)
        content_layout.addWidget(info_text)
        
        return content_frame
    
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
            + "; border-radius: 10px; padding: 12px 20px; font-size: 13px; font-weight: 700; }"
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
    
    def load_images(self):
        """Load and display images from the images folder."""
        self.image_list.clear()
        
        # Ensure folder exists
        abs_folder_path = os.path.abspath(self.images_folder)
        if not os.path.exists(abs_folder_path):
            os.makedirs(abs_folder_path)
            return
        
        # Load images
        exts = ('.png', '.jpg', '.jpeg', '.webp')
        for filename in sorted(os.listdir(self.images_folder)):
            if filename.lower().endswith(exts):
                file_path = os.path.join(self.images_folder, filename)
                item = QListWidgetItem(filename)
                
                # Try to load thumbnail
                try:
                    pixmap = QPixmap(file_path)
                    if not pixmap.isNull():
                        # Create thumbnail
                        scaled_pixmap = pixmap.scaled(48, 48, 
                                                      Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation)
                        item.setIcon(QIcon(scaled_pixmap))
                except Exception:
                    pass
                
                self.image_list.addItem(item)
    
    def add_image(self):
        """Open file dialog to add a new image."""
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter("Images (*.png *.jpg *.jpeg *.webp)")
        
        if file_dialog.exec():
            files = file_dialog.selectedFiles()
            
            # Ensure folder exists
            if not os.path.exists(self.images_folder):
                os.makedirs(self.images_folder)
            
            for file_path in files:
                try:
                    filename = os.path.basename(file_path)
                    # Normalize the path to ensure it's correct
                    dest_path = os.path.normpath(os.path.join(self.images_folder, filename))
                    
                    # Ensure folder exists
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    
                    # Check if file already exists
                    if os.path.exists(dest_path):
                        reply = QMessageBox.question(
                            self, 
                            'File Exists',
                            f'{filename} already exists. Overwrite?',
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if reply == QMessageBox.StandardButton.No:
                            continue
                    
                    # Copy file with error handling
                    try:
                        shutil.copy2(file_path, dest_path)
                    except PermissionError:
                        # If permission error, try to fix by ensuring directory exists
                        os.makedirs(self.images_folder, exist_ok=True)
                        # Try again with normalized path
                        shutil.copy2(file_path, dest_path)
                    
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        'Error',
                        f'Failed to add {os.path.basename(file_path)}: {str(e)}'
                    )
            
            # Refresh list
            self.load_images()
            
            # Ask if user wants to edit the first added image
            if files:
                reply = QMessageBox.question(
                    self,
                    'Edit Image',
                    'Would you like to edit the added image(s)?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    # Edit the first added image
                    first_file = files[0]
                    filename = os.path.basename(first_file)
                    dest_path = os.path.join(self.images_folder, filename)
                    
                    if self.image_editor is None:
                        self.image_editor = ImageEditorDialog(dest_path)
                        self.image_editor.image_saved.connect(self.on_image_saved)
                    else:
                        self.image_editor.load_image(dest_path)
                    
                    self.image_editor.show()
                    self.image_editor.raise_()
                    self.image_editor.activateWindow()
    
    def edit_image(self):
        """Open the image editor for the selected image."""
        current_item = self.image_list.currentItem()
        if not current_item:
            QMessageBox.information(
                self,
                'No Selection',
                'Please select an image to edit.'
            )
            return
        
        filename = current_item.text()
        file_path = os.path.join(self.images_folder, filename)
        
        # Create or show image editor
        if self.image_editor is None:
            self.image_editor = ImageEditorDialog(file_path)
            self.image_editor.image_saved.connect(self.on_image_saved)
        else:
            self.image_editor.load_image(file_path)
        
        self.image_editor.show()
        self.image_editor.raise_()
        self.image_editor.activateWindow()
    
    def on_image_saved(self, file_path):
        """Handle image saved signal from editor."""
        self.load_images()
    
    def remove_image(self):
        """Remove the selected image."""
        current_item = self.image_list.currentItem()
        if not current_item:
            QMessageBox.information(
                self,
                'No Selection',
                'Please select an image to remove.'
            )
            return
        
        filename = current_item.text()
        
        # Confirm deletion
        reply = QMessageBox.question(
            self,
            'Confirm Deletion',
            f'Are you sure you want to delete {filename}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                file_path = os.path.join(self.images_folder, filename)
                os.remove(file_path)
                self.load_images()
            except Exception as e:
                QMessageBox.warning(
                    self,
                    'Error',
                    f'Failed to delete {filename}: {str(e)}'
                )
    
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
