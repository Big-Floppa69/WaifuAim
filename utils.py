"""
Utility functions for the crosshair application.
"""
import os
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap


# Shared UI theme colors (dark purple system)
UI_THEME = {
    "bg": "#0F0B1E",
    "bg2": "#130F2A",
    "surface": "#1A1636",
    "surface2": "#221D45",
    "text": "#E6E1FF",
    "muted": "#BDB6E6",
    "accent": "#7C5CFF",
    "accent2": "#4FD1C5",
    "danger": "#C84B6A",
    "border": "rgba(230, 225, 255, 40)",
    "border_strong": "rgba(230, 225, 255, 70)",
}


def make_key_handler(func, hotkey):
    """Create a keyboard event handler for a specific hotkey."""
    def handler(event):
        if event.name == hotkey and event.event_type == 'up':
            func()
    return handler


def mirror_vertical(label, pixmap):
    """Mirror the image vertically."""
    original_image = pixmap.toImage()
    mirrored_image = original_image.mirrored(False, True)
    label.setPixmap(QPixmap.fromImage(mirrored_image))


def mirror_horizontal(label, pixmap):
    """Mirror the image horizontally."""
    original_image = pixmap.toImage()
    mirrored_image = original_image.mirrored(True, False)
    label.setPixmap(QPixmap.fromImage(mirrored_image))


def get_art_list(folder="display_images"):
    """Get list of image files in the display_images folder."""
    exts = ('.png', '.jpg', '.jpeg', '.webp')
    files = []
    
    # Ensure folder exists
    if not os.path.exists(folder):
        os.makedirs(folder)
        return files
    
    # Get images from the folder
    for f in os.listdir(folder):
        if f.lower().endswith(exts):
            files.append(os.path.join(folder, f))
    
    return files


def transparent(label, percent):
    """Set the opacity of the label."""
    label.setWindowOpacity(percent)
