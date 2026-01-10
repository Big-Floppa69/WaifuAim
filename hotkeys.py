"""
Hotkey management for the crosshair application.
"""
import keyboard as kb  # type: ignore
import json
import os
import time
from PyQt6.QtGui import QPixmap
from utils import mirror_vertical, mirror_horizontal, get_art_list, set_label_art_from_path


# Global reference to the label
_label_ref = None
_overlay_controller_ref = None
_hotkeys_paused = False


def load_hotkey_config():
    """Load hotkey configuration from file."""
    config_file = "hotkey_config.json"
    default_config = {
        # Each action can have multiple bindings.
        "toggle_visibility": ["f1"],
        "mirror_vertical": ["f3"],
        "mirror_horizontal": ["f4"],
        "switch_image": ["f2"],
        # Optional: if set, this key must be held while dragging an element.
        # Dragging itself is implemented by the Art Manager / overlay layer.
        "hold_to_drag": [],
    }

    def _normalize(value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip().lower() for v in value if str(v).strip()]
        s = str(value).strip().lower()
        return [s] if s else []
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                raw = json.load(f)
                if not isinstance(raw, dict):
                    return default_config
                merged = default_config.copy()
                for k in default_config.keys():
                    if k in raw:
                        merged[k] = _normalize(raw.get(k))
                return merged
        except:
            pass
    
    return default_config


def reload_hotkeys():
    """Reload all hotkeys with new configuration."""
    if _label_ref is None:
        return

    if _hotkeys_paused:
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

    def _register_many(hotkeys, callback):
        if hotkeys is None:
            return
        if isinstance(hotkeys, str):
            _register(hotkeys, callback)
            return
        if isinstance(hotkeys, list):
            for hk in hotkeys:
                _register(hk, callback)
    
    # Setup toggle visibility
    def toggle_visibility():
        if _label_ref.isVisible():
            _label_ref.hide()
        else:
            _label_ref.show()

        try:
            if _overlay_controller_ref is not None:
                _overlay_controller_ref.set_all_visible(bool(_label_ref.isVisible()))
        except Exception:
            pass
    
    _register_many(config.get('toggle_visibility', ['f1']), toggle_visibility)
    
    # Setup mirror vertical
    _register_many(
        config.get('mirror_vertical', ['f3']),
        lambda: mirror_vertical(_label_ref, _label_ref.pixmap()),
    )
    
    # Setup mirror horizontal
    _register_many(
        config.get('mirror_horizontal', ['f4']),
        lambda: mirror_horizontal(_label_ref, _label_ref.pixmap()),
    )
    
    # Setup switch image
    index = [0]  # Use list to make it mutable in closure
    
    def switch():
        arts = get_art_list()

        # Read combos from app_settings.json.
        combos = []
        try:
            with open("app_settings.json", "r", encoding="utf-8") as fh:
                data = json.load(fh)
                raw = data.get("art_combos") if isinstance(data, dict) else None
                if isinstance(raw, list):
                    for c in raw:
                        if not isinstance(c, dict):
                            continue
                        name = str(c.get("name") or "").strip()
                        keys = c.get("keys")
                        if not name or not isinstance(keys, list) or not keys:
                            continue
                        combos.append({"type": "combo", "name": name, "keys": [str(k) for k in keys if str(k).strip()]})
        except Exception:
            combos = []

        entries = ([{"type": "file", "path": p} for p in arts] + combos)
        if not entries:
            return

        index[0] = (index[0] + 1) % len(entries)
        entry = entries[index[0]]

        if entry.get("type") == "combo":
            keys = entry.get("keys") or []
            try:
                if _overlay_controller_ref is not None:
                    _overlay_controller_ref.set_selection_keys(keys)
                    if _label_ref.isVisible():
                        _overlay_controller_ref.render_selected_from_folder("display_images")
                        _overlay_controller_ref.set_all_visible(True)
                    # Keep base label transparent.
                    try:
                        pm = QPixmap(_label_ref.width(), _label_ref.height())
                        pm.fill(0)
                        _label_ref.setPixmap(pm)
                    except Exception:
                        pass
            except Exception:
                pass
            return

        # File: clear selection and set single art.
        try:
            if _overlay_controller_ref is not None:
                _overlay_controller_ref.clear_selection()
                _overlay_controller_ref.set_all_visible(False)
        except Exception:
            pass

        path = str(entry.get("path") or "").strip()
        if not path:
            return

            def _key_for_path(p: str) -> str:
                try:
                    root = os.path.dirname(os.path.abspath(__file__))
                    return os.path.relpath(os.path.abspath(p), root).replace("\\", "/")
                except Exception:
                    return os.path.abspath(p).replace("\\", "/")

            # Prefer overlay pipeline so single-file display is editable like combos.
            try:
                if _overlay_controller_ref is not None:
                    key = _key_for_path(path)
                    try:
                        _overlay_controller_ref.clear_selection()
                    except Exception:
                        pass
                    try:
                        _overlay_controller_ref.set_selection_keys([key])
                        if _label_ref.isVisible():
                            _overlay_controller_ref.render_selected_from_folder("display_images")
                            _overlay_controller_ref.set_all_visible(True)
                        # Make base label transparent to avoid duplicate rendering.
                        try:
                            pm = QPixmap(_label_ref.width(), _label_ref.height())
                            pm.fill(0)
                            _label_ref.setPixmap(pm)
                        except Exception:
                            pass
                        return
                    except Exception:
                        pass
            except Exception:
                pass

            # Fallback to legacy rendering into the base label.
            try:
                set_label_art_from_path(_label_ref, path)
            except Exception:
                try:
                    pix = QPixmap(path)
                    _label_ref.setPixmap(pix)
                except Exception:
                    pass

        def _key_for_path(p: str) -> str:
            try:
                root = os.path.dirname(os.path.abspath(__file__))
                return os.path.relpath(os.path.abspath(p), root).replace("\\", "/")
            except Exception:
                return os.path.abspath(p).replace("\\", "/")

        # If an overlay controller is present, prefer rendering the single
        # file as an overlay element (same pipeline as combos). This makes
        # the asset editable/movable via the Art Manager and avoids having
        # two different rendering paths for the same file.
        try:
            if _overlay_controller_ref is not None:
                key = _key_for_path(path)
                try:
                    _overlay_controller_ref.clear_selection()
                except Exception:
                    pass
                try:
                    _overlay_controller_ref.set_selection_keys([key])
                    if _label_ref.isVisible():
                        _overlay_controller_ref.render_selected_from_folder("display_images")
                        _overlay_controller_ref.set_all_visible(True)
                    # Make base label transparent to avoid duplicate rendering.
                    try:
                        pm = QPixmap(_label_ref.width(), _label_ref.height())
                        pm.fill(0)
                        _label_ref.setPixmap(pm)
                    except Exception:
                        pass
                    return
                except Exception:
                    # Fall-through to legacy behavior on error.
                    pass
        except Exception:
            pass

        # Legacy fallback: render directly into the base label.
        try:
            set_label_art_from_path(_label_ref, path)
        except Exception:
            try:
                pix = QPixmap(path)
                _label_ref.setPixmap(pix)
            except Exception:
                pass
    
    _register_many(config.get('switch_image', ['f2']), switch)


def setup_hotkeys(label, *, overlay_controller=None):
    """Initialize all hotkeys."""
    global _label_ref
    global _overlay_controller_ref
    _label_ref = label
    _overlay_controller_ref = overlay_controller
    reload_hotkeys()


def pause_hotkeys() -> None:
    """Temporarily disable global hotkeys (useful while editing bindings)."""
    global _hotkeys_paused
    _hotkeys_paused = True
    try:
        kb.unhook_all()
    except Exception:
        pass


def resume_hotkeys() -> None:
    """Re-enable global hotkeys after a pause."""
    global _hotkeys_paused
    _hotkeys_paused = False
    reload_hotkeys()


def get_current_hotkeys():
    """Get current hotkey configuration as a readable string."""
    config = load_hotkey_config()

    def _first(action: str, default: str) -> str:
        v = config.get(action)
        if isinstance(v, list) and v:
            return str(v[0]).upper()
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
        return default.upper()

    return (
        f"Toggle = {_first('toggle_visibility', 'f1')} | "
        f"MirrorV = {_first('mirror_vertical', 'f3')} | "
        f"MirrorH = {_first('mirror_horizontal', 'f4')} | "
        f"Switch = {_first('switch_image', 'f2')}"
    )
