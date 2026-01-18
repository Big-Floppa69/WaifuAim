"""Hotkey management for the crosshair application.

Important:
- Global hotkeys are handled by the `keyboard` library (non-Qt thread).
- Any Qt widget manipulation must be marshaled onto the Qt UI thread.
"""

from __future__ import annotations

import json
import os
import sys
import time
import ctypes
import threading

import keyboard as kb  # type: ignore
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from utils import (
    clear_label_art,
    get_art_list,
    get_art_cycle_entries,
    get_app_config_path,
    mirror_horizontal,
    mirror_vertical,
    set_label_art_from_path,
)

from standard_crosshair import randomize_standard_crosshair


_label_ref = None
_overlay_controller_ref = None
_crosshair_label_ref = None
_control_panel_ref = None
_hotkeys_paused = False

_win32_hotkey_lock = threading.Lock()
_win32_hotkey_bindings: list[dict] = []
_win32_hotkey_thread: threading.Thread | None = None
_win32_hotkey_stop = threading.Event()


class _UiInvoker(QObject):
    run = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.run.connect(self._run)

    def _run(self, fn) -> None:
        try:
            if callable(fn):
                fn()
        except Exception:
            pass


_ui_invoker: _UiInvoker | None = None


def _ensure_ui_invoker() -> _UiInvoker | None:
    global _ui_invoker
    if _ui_invoker is not None:
        return _ui_invoker
    app = QApplication.instance()
    if app is None:
        return None
    inv = _UiInvoker()
    try:
        inv.moveToThread(app.thread())
    except Exception:
        pass
    _ui_invoker = inv
    return _ui_invoker


def _on_ui_thread(fn) -> None:
    inv = _ensure_ui_invoker()
    if inv is None:
        try:
            fn()
        except Exception:
            pass
        return
    try:
        inv.run.emit(fn)
    except Exception:
        try:
            fn()
        except Exception:
            pass


def load_hotkey_config() -> dict:
    """Load hotkey configuration from file."""
    config_file = get_app_config_path("hotkey_config.json")
    default_config = {
        "toggle_visibility": ["f1"],
        "mirror_vertical": ["f3"],
        "mirror_horizontal": ["f4"],
        "switch_image": ["f2"],
        # Randomize generated crosshair (optional).
        "randomize_crosshair": [],
        "hold_to_drag": [],
    }

    def _normalize_key_name(s: str) -> str:
        s = str(s or "").strip().lower()
        if not s:
            return ""
        # keyboard library tends to prefer key names like "grave".
        aliases = {
            "`": "grave",
            "~": "grave",
            "mouse4": "mouse_x1",
            "mouse5": "mouse_x2",
            "mouse_4": "mouse_x1",
            "mouse_5": "mouse_x2",
            "x1": "mouse_x1",
            "x2": "mouse_x2",
            "mb4": "mouse_x1",
            "mb5": "mouse_x2",
        }
        return aliases.get(s, s)

    def _normalize_chord(chord: str) -> str:
        parts = [p.strip() for p in str(chord or "").split("+") if p.strip()]
        parts = [_normalize_key_name(p) for p in parts]
        parts = [p for p in parts if p]
        return "+".join(parts)

    def _normalize(value):
        if value is None:
            return []
        if isinstance(value, list):
            out = []
            for v in value:
                s = _normalize_chord(v)
                if s:
                    out.append(s)
            return out
        s = _normalize_chord(value)
        return [s] if s else []

    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if not isinstance(raw, dict):
                    return default_config
                merged = default_config.copy()
                for k in default_config.keys():
                    if k in raw:
                        merged[k] = _normalize(raw.get(k))
                return merged
        except Exception:
            pass

    return default_config


def reload_hotkeys() -> None:
    """Reload all hotkeys with new configuration."""
    if _label_ref is None:
        return
    if _hotkeys_paused:
        return

    try:
        kb.unhook_all()
    except Exception:
        pass

    with _win32_hotkey_lock:
        _win32_hotkey_bindings.clear()

    config = load_hotkey_config()

    # Keep overlay controller in sync with hold-to-drag chord.
    try:
        if _overlay_controller_ref is not None:
            _overlay_controller_ref.set_hold_to_drag(config.get("hold_to_drag", []))
    except Exception:
        pass

    def _register(hotkey: str, callback) -> None:
        hotkey = str(hotkey or "").strip().lower()
        if not hotkey:
            return

        parts = [p.strip() for p in hotkey.split("+") if p.strip()]
        if not parts:
            return

        def _vk_from_key_name(name: str) -> int | None:
            name = str(name or "").strip().lower()
            if not name:
                return None
            mapping = {
                "mouse_left": 0x01,
                "mouse_right": 0x02,
                "mouse_middle": 0x04,
                "mouse_x1": 0x05,
                "mouse_x2": 0x06,
                "shift": 0x10,
                "ctrl": 0x11,
                "control": 0x11,
                "alt": 0x12,
                "windows": 0x5B,
                "win": 0x5B,
                "space": 0x20,
                "tab": 0x09,
                "esc": 0x1B,
                "escape": 0x1B,
                "enter": 0x0D,
                "return": 0x0D,
                "backspace": 0x08,
                "capslock": 0x14,
                "grave": 0xC0,
            }
            if name.startswith("f") and name[1:].isdigit():
                try:
                    n = int(name[1:])
                    if 1 <= n <= 24:
                        return 0x70 + (n - 1)
                except Exception:
                    return None
            arrows = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
            if name in arrows:
                return arrows[name]
            if name in mapping:
                return mapping[name]
            if len(name) == 1:
                ch = name
                if "a" <= ch <= "z":
                    return ord(ch.upper())
                if "0" <= ch <= "9":
                    return ord(ch)
            return None

        def _is_pressed_win32(key_name: str) -> bool:
            vk = _vk_from_key_name(key_name)
            if vk is None:
                return False
            try:
                state = ctypes.windll.user32.GetAsyncKeyState(int(vk))
                return bool(state & 0x8000)
            except Exception:
                return False

        def _any_mouse(parts_: list[str]) -> bool:
            return any(p.startswith("mouse_") for p in parts_)

        def _all_modifiers(parts_: list[str]) -> bool:
            if not parts_:
                return False
            mods = {"ctrl", "control", "alt", "shift", "windows", "win"}
            return all(str(p or "").strip().lower() in mods for p in parts_)

        state = {"armed": True, "last": 0.0}

        # Windows installed/frozen builds frequently cannot rely on low-level
        # keyboard hooks (the `keyboard` lib may require elevation or be blocked).
        # Use Win32 polling for reliability.
        try:
            is_windows = (os.name == "nt")
        except Exception:
            is_windows = False

        if is_windows:
            # If all parts are recognized, handle via Win32 polling.
            if any(_vk_from_key_name(p) is None for p in parts):
                return
            with _win32_hotkey_lock:
                _win32_hotkey_bindings.append({"parts": parts, "state": state, "callback": callback})
            _ensure_win32_hotkey_thread()
            return

        def maybe_fire(_=None):
            now = time.monotonic()
            if not state["armed"]:
                return
            try:
                if all(kb.is_pressed(p) for p in parts):
                    if now - state["last"] < 0.15:
                        return
                    state["last"] = now
                    state["armed"] = False
                    callback()
            except Exception:
                return

        def rearm(_=None):
            try:
                if not all(kb.is_pressed(p) for p in parts):
                    state["armed"] = True
            except Exception:
                state["armed"] = True

        for p in parts:
            kb.on_press_key(p, maybe_fire)
            kb.on_release_key(p, rearm)

    def _register_many(hotkeys, callback) -> None:
        if hotkeys is None:
            return
        if isinstance(hotkeys, str):
            _register(hotkeys, callback)
            return
        if isinstance(hotkeys, list):
            for hk in hotkeys:
                _register(hk, callback)

    def toggle_visibility() -> None:
        def _do():
            if _label_ref is None:
                return
            if _label_ref.isVisible():
                _label_ref.hide()
            else:
                _label_ref.show()
            try:
                if _overlay_controller_ref is not None:
                    _overlay_controller_ref.set_all_visible(bool(_label_ref.isVisible()))
            except Exception:
                pass

        _on_ui_thread(_do)

    def mirror_v() -> None:
        def _do():
            # Prefer mirroring selected art overlays (new pipeline).
            try:
                if _overlay_controller_ref is not None:
                    fn = getattr(_overlay_controller_ref, "toggle_mirror_vertical", None)
                    if callable(fn):
                        fn()
                        return
            except Exception:
                pass

            # Fallback: mirror the legacy base image label.
            if _label_ref is None:
                return
            mirror_vertical(_label_ref, _label_ref.pixmap())

        _on_ui_thread(_do)

    def mirror_h() -> None:
        def _do():
            # Prefer mirroring selected art overlays (new pipeline).
            try:
                if _overlay_controller_ref is not None:
                    fn = getattr(_overlay_controller_ref, "toggle_mirror_horizontal", None)
                    if callable(fn):
                        fn()
                        return
            except Exception:
                pass

            # Fallback: mirror the legacy base image label.
            if _label_ref is None:
                return
            mirror_horizontal(_label_ref, _label_ref.pixmap())

        _on_ui_thread(_do)

    index = [0]

    def _sync_image_manager_checkmarks() -> None:
        """If the Art Manager window is open, refresh its checkmarks."""
        try:
            cp = _control_panel_ref
            if cp is None:
                return
            mgr = getattr(cp, "image_manager", None)
            if mgr is None:
                return
            fn = getattr(mgr, "sync_checkmarks_from_controller", None)
            if callable(fn):
                fn()
        except Exception:
            return

    def switch_image() -> None:
        def _do():
            if _label_ref is None:
                return

            # Prefer using the main UI's switching logic so the order/index is
            # consistent across the Next Image button and the hotkey.
            try:
                cp = _control_panel_ref
                fn = getattr(cp, "switch_image", None) if cp is not None else None
                if callable(fn):
                    fn()
                    return
            except Exception:
                pass

            # Switching images via hotkey should always advance *and* show the
            # newly selected art. If the base label is hidden, the previous
            # selection can appear to "turn off" because rendering is requested
            # with visible=False.
            try:
                if not _label_ref.isVisible():
                    _label_ref.show()
            except Exception:
                pass

            entries = get_art_cycle_entries("display_images")
            if not entries:
                return

            index[0] = (index[0] + 1) % len(entries)
            entry = entries[index[0]]

            def _key_for_path(p: str) -> str:
                try:
                    root = os.path.dirname(os.path.abspath(__file__))
                    return os.path.relpath(os.path.abspath(p), root).replace("\\", "/")
                except Exception:
                    return os.path.abspath(p).replace("\\", "/")

            if entry.get("type") == "combo":
                if _overlay_controller_ref is None:
                    return
                keys = entry.get("keys") or []
                clear_label_art(_label_ref)
                try:
                    _overlay_controller_ref.set_selection_keys(keys)
                    _sync_image_manager_checkmarks()
                    _overlay_controller_ref.request_render_selected_atomic(
                        "display_images",
                        visible=True,
                    )
                except Exception:
                    pass
                return

            path = str(entry.get("path") or "").strip()
            if not path:
                return

            if _overlay_controller_ref is not None:
                key = _key_for_path(path)
                clear_label_art(_label_ref)

                def _fallback(_e=None):
                    try:
                        _overlay_controller_ref.clear_selection()
                        _overlay_controller_ref.set_all_visible(False)
                    except Exception:
                        pass
                    try:
                        set_label_art_from_path(_label_ref, path)
                    except Exception:
                        try:
                            pix = QPixmap(path)
                            _label_ref.setPixmap(pix)
                        except Exception:
                            pass

                try:
                    _overlay_controller_ref.set_selection_keys([key])
                    _sync_image_manager_checkmarks()
                    _overlay_controller_ref.request_render_selected_atomic(
                        "display_images",
                        visible=True,
                        on_error=_fallback,
                    )
                except Exception:
                    _fallback(None)
                return

            try:
                set_label_art_from_path(_label_ref, path)
            except Exception:
                try:
                    pix = QPixmap(path)
                    _label_ref.setPixmap(pix)
                except Exception:
                    pass

        _on_ui_thread(_do)

    def randomize_crosshair() -> None:
        def _do():
            if _crosshair_label_ref is None:
                return
            try:
                randomize_standard_crosshair(_crosshair_label_ref)
            except Exception:
                pass

        _on_ui_thread(_do)

    _register_many(config.get("toggle_visibility", ["f1"]), toggle_visibility)
    _register_many(config.get("mirror_vertical", ["f3"]), mirror_v)
    _register_many(config.get("mirror_horizontal", ["f4"]), mirror_h)
    _register_many(config.get("switch_image", ["f2"]), switch_image)
    _register_many(config.get("randomize_crosshair", []), randomize_crosshair)


def _ensure_win32_hotkey_thread() -> None:
    global _win32_hotkey_thread
    if _win32_hotkey_thread is not None and _win32_hotkey_thread.is_alive():
        return

    _win32_hotkey_stop.clear()

    def _poll_loop() -> None:
        while not _win32_hotkey_stop.is_set():
            if _hotkeys_paused:
                time.sleep(0.05)
                continue

            with _win32_hotkey_lock:
                bindings = list(_win32_hotkey_bindings)

            for b in bindings:
                parts = b.get("parts") or []
                state = b.get("state") or {"armed": True, "last": 0.0}
                cb = b.get("callback")
                if not callable(cb) or not isinstance(parts, list) or not parts:
                    continue

                now = time.monotonic()
                if not state.get("armed", True):
                    # Rearm when released.
                    try:
                        if not all(_is_pressed_win32(p) for p in parts):
                            state["armed"] = True
                    except Exception:
                        state["armed"] = True
                    continue

                try:
                    if all(_is_pressed_win32(p) for p in parts):
                        if now - float(state.get("last", 0.0)) < 0.15:
                            continue
                        state["last"] = now
                        state["armed"] = False
                        cb()
                except Exception:
                    continue

            time.sleep(0.01)

    _win32_hotkey_thread = threading.Thread(target=_poll_loop, name="WaifuAimWin32Hotkeys", daemon=True)
    _win32_hotkey_thread.start()


def _is_pressed_win32(key_name: str) -> bool:
    # Helper for Win32 polling thread.
    key_name = str(key_name or "").strip().lower()
    if not key_name:
        return False

    mapping = {
        "mouse_left": 0x01,
        "mouse_right": 0x02,
        "mouse_middle": 0x04,
        "mouse_x1": 0x05,
        "mouse_x2": 0x06,
        "shift": 0x10,
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "windows": 0x5B,
        "win": 0x5B,
        "space": 0x20,
        "tab": 0x09,
        "esc": 0x1B,
        "escape": 0x1B,
        "enter": 0x0D,
        "return": 0x0D,
        "backspace": 0x08,
        "capslock": 0x14,
        "grave": 0xC0,
    }
    if key_name.startswith("f") and key_name[1:].isdigit():
        try:
            n = int(key_name[1:])
            if 1 <= n <= 24:
                vk = 0x70 + (n - 1)
            else:
                return False
        except Exception:
            return False
    elif key_name in ("left", "up", "right", "down"):
        vk = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}[key_name]
    elif key_name in mapping:
        vk = mapping[key_name]
    elif len(key_name) == 1:
        ch = key_name
        if "a" <= ch <= "z":
            vk = ord(ch.upper())
        elif "0" <= ch <= "9":
            vk = ord(ch)
        else:
            return False
    else:
        return False

    try:
        state = ctypes.windll.user32.GetAsyncKeyState(int(vk))
        return bool(state & 0x8000)
    except Exception:
        return False


def setup_hotkeys(label, *, crosshair_label=None, overlay_controller=None, control_panel=None) -> None:
    """Initialize all hotkeys."""
    global _label_ref
    global _overlay_controller_ref
    global _crosshair_label_ref
    global _control_panel_ref
    _label_ref = label
    _overlay_controller_ref = overlay_controller
    _crosshair_label_ref = crosshair_label
    _control_panel_ref = control_panel
    _ensure_ui_invoker()
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


def get_current_hotkeys() -> str:
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
        f"Switch = {_first('switch_image', 'f2')} | "
        f"Randomize = {_first('randomize_crosshair', '')}"
    )
