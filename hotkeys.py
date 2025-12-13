"""
Hotkey management for the crosshair application.
"""
import keyboard as kb  # type: ignore
import json
import os
import time
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

    def _register(hotkey: str, callback):
        """Register a hotkey string with the keyboard library.

        Supports modifier-only bindings (ctrl/alt/shift/windows) which are
        not always handled reliably by add_hotkey across platforms.
        """
        hotkey = str(hotkey or "").strip().lower()
        if not hotkey:
            return

        def _register_chord(parts: list[str]):
            # Fire once per chord-press (even if other keys are held).
            state = {"armed": True, "last": 0.0}

            def maybe_fire(_=None):
                now = time.monotonic()
                if not state["armed"]:
                    return
                if all(kb.is_pressed(p) for p in parts):
                    # small debounce
                    if now - state["last"] < 0.15:
                        return
                    state["last"] = now
                    state["armed"] = False
                    callback()

            def rearm(_=None):
                # Re-arm once the chord is no longer fully held.
                if not all(kb.is_pressed(p) for p in parts):
                    state["armed"] = True

            for p in parts:
                kb.on_press_key(p, maybe_fire)
                kb.on_release_key(p, rearm)

        try:
            parts = [p.strip() for p in hotkey.split("+") if p.strip()]
            if not parts:
                return
            _register_chord(parts)
        except Exception:
            pass
    
    # Setup toggle visibility
    def toggle_visibility():
        if _label_ref.isVisible():
            _label_ref.hide()
        else:
            _label_ref.show()
    
    _register(config.get('toggle_visibility', 'f1'), toggle_visibility)
    
    # Setup mirror vertical
    _register(config.get('mirror_vertical', 'f3'), lambda: mirror_vertical(_label_ref, _label_ref.pixmap()))
    
    # Setup mirror horizontal
    _register(config.get('mirror_horizontal', 'f4'), lambda: mirror_horizontal(_label_ref, _label_ref.pixmap()))
    
    # Setup switch image
    index = [0]  # Use list to make it mutable in closure
    
    def switch():
        arts = get_art_list()
        if not arts:
            return
        index[0] = (index[0] + 1) % len(arts)
        pix = QPixmap(arts[index[0]])
        _label_ref.setPixmap(pix)
    
    _register(config.get('switch_image', 'f2'), switch)


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
