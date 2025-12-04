"""
Hotkey management for the crosshair application.
"""
import keyboard as kb  # type: ignore
import json
import os
from PyQt6.QtGui import QPixmap
from utils import mirror_vertical, mirror_horizontal, get_art_list


# Global reference to the label
_label_ref = None


def load_hotkey_config():
    """Load hotkey configuration from file."""
    config_file = "hotkey_config.json"
    default_config = {
        "toggle_visibility": "f1",
        "mirror_vertical": "f3",
        "mirror_horizontal": "f4",
        "switch_image": "f2"
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except:
            pass
    
    return default_config


def reload_hotkeys():
    """Reload all hotkeys with new configuration."""
    if _label_ref is None:
        return
    
    # Unhook all existing hotkeys
    try:
        kb.unhook_all()
    except:
        pass
    
    # Reload configuration and setup new hotkeys
    config = load_hotkey_config()
    
    # Setup toggle visibility
    def toggle_visibility():
        if _label_ref.isVisible():
            _label_ref.hide()
        else:
            _label_ref.show()
    
    try:
        kb.add_hotkey(config.get('toggle_visibility', 'f1'), toggle_visibility)
    except:
        pass
    
    # Setup mirror vertical
    try:
        kb.add_hotkey(config.get('mirror_vertical', 'f3'), 
                     lambda: mirror_vertical(_label_ref, _label_ref.pixmap()))
    except:
        pass
    
    # Setup mirror horizontal
    try:
        kb.add_hotkey(config.get('mirror_horizontal', 'f4'), 
                     lambda: mirror_horizontal(_label_ref, _label_ref.pixmap()))
    except:
        pass
    
    # Setup switch image
    index = [0]  # Use list to make it mutable in closure
    
    def switch():
        arts = get_art_list()
        if not arts:
            return
        index[0] = (index[0] + 1) % len(arts)
        pix = QPixmap(arts[index[0]])
        _label_ref.setPixmap(pix)
    
    try:
        kb.add_hotkey(config.get('switch_image', 'f2'), switch)
    except:
        pass


def setup_hotkeys(label):
    """Initialize all hotkeys."""
    global _label_ref
    _label_ref = label
    reload_hotkeys()


def get_current_hotkeys():
    """Get current hotkey configuration as a readable string."""
    config = load_hotkey_config()
    return (
        f"Toggle = {config.get('toggle_visibility', 'f1').upper()} | "
        f"MirrorV = {config.get('mirror_vertical', 'f3').upper()} | "
        f"MirrorH = {config.get('mirror_horizontal', 'f4').upper()} | "
        f"Switch = {config.get('switch_image', 'f2').upper()}"
    )
