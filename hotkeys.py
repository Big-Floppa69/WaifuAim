"""Hotkey management for the crosshair application.

Important:
- Global hotkeys are handled by the `keyboard` library (non-Qt thread).
- Any Qt widget manipulation must be marshaled onto the Qt UI thread.
"""

from __future__ import annotations

import json
import os
import time

import keyboard as kb  # type: ignore
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from utils import (
    clear_label_art,
    get_art_list,
    get_art_cycle_entries,
    mirror_horizontal,
    mirror_vertical,
    set_label_art_from_path,
)


_label_ref = None
_overlay_controller_ref = None
_hotkeys_paused = False


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
    config_file = "hotkey_config.json"
    default_config = {
        "toggle_visibility": ["f1"],
        "mirror_vertical": ["f3"],
        "mirror_horizontal": ["f4"],
        "switch_image": ["f2"],
        "hold_to_drag": [],
    }

    def _normalize_key_name(s: str) -> str:
        s = str(s or "").strip().lower()
        if not s:
            return ""
        # keyboard library tends to prefer key names like "grave".
        return {"`": "grave", "~": "grave"}.get(s, s)

    def _normalize(value):
        if value is None:
            return []
        if isinstance(value, list):
            out = []
            for v in value:
                s = _normalize_key_name(v)
                if s:
                    out.append(s)
            return out
        s = _normalize_key_name(value)
        return [s] if s else []

    if os.path.exists(config_file):
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

        state = {"armed": True, "last": 0.0}

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
            if _label_ref is None:
                return
            mirror_vertical(_label_ref, _label_ref.pixmap())

        _on_ui_thread(_do)

    def mirror_h() -> None:
        def _do():
            if _label_ref is None:
                return
            mirror_horizontal(_label_ref, _label_ref.pixmap())

        _on_ui_thread(_do)

    index = [0]

    def switch_image() -> None:
        def _do():
            if _label_ref is None:
                return

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
                    _overlay_controller_ref.request_render_selected_atomic(
                        "display_images",
                        visible=bool(_label_ref.isVisible()),
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
                    _overlay_controller_ref.request_render_selected_atomic(
                        "display_images",
                        visible=bool(_label_ref.isVisible()),
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

    _register_many(config.get("toggle_visibility", ["f1"]), toggle_visibility)
    _register_many(config.get("mirror_vertical", ["f3"]), mirror_v)
    _register_many(config.get("mirror_horizontal", ["f4"]), mirror_h)
    _register_many(config.get("switch_image", ["f2"]), switch_image)


def setup_hotkeys(label, *, overlay_controller=None) -> None:
    """Initialize all hotkeys."""
    global _label_ref
    global _overlay_controller_ref
    _label_ref = label
    _overlay_controller_ref = overlay_controller
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
        f"Switch = {_first('switch_image', 'f2')}"
    )
