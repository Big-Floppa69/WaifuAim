"""Separate art overlay elements (images/videos) with per-element transforms.

This replaces the old "composition" workflow and does NOT introduce a separate
"media elements" UI; instead, elements are toggled via checkboxes in the Art
Manager.

Persistence lives in app_settings.json under the key "art_overlays".
"""

from __future__ import annotations

import json
import ctypes
import os
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QLabel

from utils import read_app_settings, update_app_settings, refresh_label_pixmap_for_colorblind_mode, resolve_art_folder, set_label_art_from_path


@dataclass
class ArtOverlayState:
    enabled: bool
    opacity: float
    transform: dict


class MovableOverlayLabel(QLabel):
    """Fullscreen label that can be dragged to update an element transform."""

    def __init__(self, controller: "ArtOverlayController", key: str):
        super().__init__()
        self._controller = controller
        self._key = key
        self._drag_active = False
        self._drag_start_global = None
        self._drag_start_xy = None

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._controller.can_drag(self._key):
            return
        self._drag_active = True
        self._drag_start_global = event.globalPosition().toPoint()
        t = self._controller.get_transform(self._key)
        x = float(t.get("x", 0) or 0)
        y = float(t.get("y", 0) or 0)
        self._drag_start_xy = (x, y)
        event.accept()

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if not self._drag_active or self._drag_start_global is None or self._drag_start_xy is None:
            return
        if not self._controller.can_drag(self._key):
            return
        cur = event.globalPosition().toPoint()
        dx = float(cur.x() - self._drag_start_global.x())
        dy = float(cur.y() - self._drag_start_global.y())
        x0, y0 = self._drag_start_xy
        self._controller.set_transform(self._key, {"x": x0 + dx, "y": y0 + dy})
        event.accept()

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._drag_start_global = None
            self._drag_start_xy = None
            try:
                self._controller.flush_transform(self._key)
            except Exception:
                pass
            event.accept()


class ArtOverlayController:
    def __init__(self, app: QApplication, *, crosshair_overlay: QLabel):
        self._app = app
        self._crosshair_overlay = crosshair_overlay

        screen = app.primaryScreen()
        geo = screen.geometry()
        self._canvas_size = (int(geo.width()), int(geo.height()))

        self._labels: dict[str, MovableOverlayLabel] = {}
        self._global_opacity = 1.0

        # Runtime-only visual transforms (never persisted).
        # Key -> {"flip_x": bool, "flip_y": bool}
        self._runtime_flips: dict[str, dict[str, bool]] = {}

        # Monotonic counter to cancel stale deferred renders.
        self._render_generation = 0

        # Drag context: overlays become interactive only while a configured
        # hold-to-drag chord is held. Default empty chord disables dragging.
        self._drag_context_enabled = True
        self._selected_key: Optional[str] = None
        # Optional hold chord, e.g. "alt" or "ctrl+shift". Empty => no hold.
        self._hold_to_drag: list[str] = []
        self._drag_hold_active = False

        # Poll hold-to-drag state so dragging can work globally.
        self._hold_poll = QTimer(self._app)
        self._hold_poll.setInterval(30)
        self._hold_poll.timeout.connect(self._update_hold_state)
        self._hold_poll.start()

        # Whether the UI currently expects art overlays to be visible.
        # Used so checkbox toggles can render immediately when "Show Art" is on.
        self._visible_requested = False

        # Coalesce repeated drag updates for smoother movement.
        self._pending_reapply: set[str] = set()
        self._reapply_timer = QTimer(self._app)
        self._reapply_timer.setSingleShot(True)
        self._reapply_timer.setInterval(16)
        self._reapply_timer.timeout.connect(self._process_pending_reapply)

    def enabled_keys(self) -> list[str]:
        data = self._read_settings()
        raw = data.get("art_overlays")
        overlays = raw if isinstance(raw, dict) else {}
        out: list[str] = []
        for k, v in overlays.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, dict) and bool(v.get("enabled", False)):
                out.append(k)
        return out

    def clear_selection(self) -> None:
        """Clear all checkmarks (selection) and hide any existing overlay labels."""
        def _upd(data: dict) -> dict:
            raw = data.get("art_overlays")
            overlays = raw if isinstance(raw, dict) else {}
            for k, v in list(overlays.items()):
                if isinstance(v, dict):
                    v["enabled"] = False
                    overlays[k] = v
            data["art_overlays"] = overlays
            return data

        try:
            update_app_settings(update_fn=_upd)
        except Exception:
            pass
        for _k, lbl in list(self._labels.items()):
            try:
                lbl.hide()
            except Exception:
                pass
        self._sync_interactivity()

    def set_selection_keys(self, keys: list[str]) -> None:
        """Set checkmarks to exactly `keys` (others become unchecked)."""
        wanted = {str(k) for k in (keys or []) if str(k).strip()}
        def _upd(data: dict) -> dict:
            raw = data.get("art_overlays")
            overlays = raw if isinstance(raw, dict) else {}

            # Flip existing entries.
            for k, v in list(overlays.items()):
                if not isinstance(v, dict):
                    v = {}
                v["enabled"] = (k in wanted)
                overlays[k] = v

            # Add missing entries.
            for k in wanted:
                v = overlays.get(k)
                if not isinstance(v, dict):
                    v = {}
                v["enabled"] = True
                if "opacity" not in v:
                    v["opacity"] = 1.0
                if "transform" not in v:
                    v["transform"] = {}
                overlays[k] = v

            data["art_overlays"] = overlays
            return data

        try:
            update_app_settings(update_fn=_upd)
        except Exception:
            pass
        self._sync_interactivity()

    def render_selected_from_folder(self, folder: str = "display_images") -> None:
        """Render all checked items (selection) into overlay labels.

        This does not change selection; it just applies the current transform
        state to the on-screen overlays.
        """
        folder = str(folder or "").strip() or "display_images"
        abs_folder = resolve_art_folder(folder)
        if not os.path.exists(abs_folder):
            return

        def _key_for_path(p: str) -> str:
            try:
                root = os.path.dirname(os.path.abspath(__file__))
                return os.path.relpath(os.path.abspath(p), root).replace("\\", "/")
            except Exception:
                return os.path.abspath(p).replace("\\", "/")

        enabled = set(self.enabled_keys())
        for name in sorted(os.listdir(abs_folder)):
            p = os.path.join(abs_folder, name)
            if not os.path.isfile(p):
                continue
            key = _key_for_path(p)
            if key not in enabled:
                continue
            self._ensure_label(key)
            self._apply_label(key, p)

    def refresh_colorblind_mode(self) -> None:
        """Re-render image overlays according to the current colorblind mode."""
        for _k, lbl in list(self._labels.items()):
            try:
                refresh_label_pixmap_for_colorblind_mode(lbl)
            except Exception:
                pass

    def request_render_selected_atomic(
        self,
        folder: str = "display_images",
        *,
        visible: bool,
        on_error=None,
    ) -> None:
        """Render selection without transient overlap.

        Steps:
        - Hide all existing overlay labels immediately.
        - Defer actual rendering to the next Qt tick.
        - Only show overlays (via set_all_visible) after a successful render.

        This avoids one-frame stacking when selection changes and also prevents
        the legacy fallback from double-rendering on partial overlay failures.
        """
        self._visible_requested = bool(visible)
        self._render_generation += 1
        gen = self._render_generation

        # Hide everything first (old selection may still be enabled in settings).
        for _k, lbl in list(self._labels.items()):
            try:
                lbl.hide()
            except Exception:
                pass

        def _do_render() -> None:
            if gen != self._render_generation:
                return
            try:
                self._render_selected_from_folder_hidden(folder)
            except Exception as e:
                # Keep overlays hidden on failure.
                if on_error is not None:
                    try:
                        on_error(e)
                    except Exception:
                        pass
                return
            self.set_all_visible(bool(visible))

        QTimer.singleShot(0, _do_render)

    def _render_selected_from_folder_hidden(self, folder: str = "display_images") -> None:
        """Like render_selected_from_folder(), but keeps overlays hidden until caller shows them."""
        folder = str(folder or "").strip() or "display_images"
        abs_folder = resolve_art_folder(folder)
        if not os.path.exists(abs_folder):
            return

        def _key_for_path(p: str) -> str:
            try:
                root = os.path.dirname(os.path.abspath(__file__))
                return os.path.relpath(os.path.abspath(p), root).replace("\\", "/")
            except Exception:
                return os.path.abspath(p).replace("\\", "/")

        enabled = set(self.enabled_keys())
        for name in sorted(os.listdir(abs_folder)):
            p = os.path.join(abs_folder, name)
            if not os.path.isfile(p):
                continue
            key = _key_for_path(p)
            if key not in enabled:
                continue
            self._ensure_label(key)
            self._apply_label(key, p, visible_override=False)

    # --- persistence -----------------------------------------------------------------

    def _read_settings(self) -> dict:
        try:
            return read_app_settings() or {}
        except Exception:
            return {}

    def _write_settings(self, data: dict) -> None:
        try:
            if not isinstance(data, dict):
                return
            update_app_settings(update_fn=lambda _old: dict(data))
        except Exception:
            pass

    def _get_state(self, key: str) -> ArtOverlayState:
        data = self._read_settings()
        raw = data.get("art_overlays")
        overlays = raw if isinstance(raw, dict) else {}
        v = overlays.get(key)
        if not isinstance(v, dict):
            return ArtOverlayState(enabled=False, opacity=1.0, transform={})

        enabled = bool(v.get("enabled", False))
        try:
            opacity = float(v.get("opacity", 1.0))
        except Exception:
            opacity = 1.0
        opacity = max(0.0, min(1.0, opacity))
        t = v.get("transform")
        if not isinstance(t, dict):
            t = {}
        return ArtOverlayState(enabled=enabled, opacity=opacity, transform=t)

    def _set_state(self, key: str, state: ArtOverlayState) -> None:
        def _upd(data: dict) -> dict:
            overlays = data.get("art_overlays")
            if not isinstance(overlays, dict):
                overlays = {}
            overlays[key] = {
                "enabled": bool(state.enabled),
                "opacity": float(state.opacity),
                "transform": dict(state.transform or {}),
            }
            data["art_overlays"] = overlays
            return data

        try:
            update_app_settings(update_fn=_upd)
        except Exception:
            pass

    # --- public API ------------------------------------------------------------------

    def set_hold_to_drag(self, hotkeys: list[str] | str | None) -> None:
        if hotkeys is None:
            self._hold_to_drag = []
            return
        if isinstance(hotkeys, str):
            hotkeys = [hotkeys]
        out: list[str] = []
        for hk in hotkeys:
            s = str(hk or "").strip().lower()
            if s:
                out.append(s)
        self._hold_to_drag = out
        self._update_hold_state()

    def set_drag_context(self, enabled: bool, *, selected_key: Optional[str] = None) -> None:
        self._drag_context_enabled = bool(enabled)
        self._selected_key = str(selected_key) if selected_key else None
        self._sync_interactivity()

    def set_selected_key(self, key: Optional[str]) -> None:
        self._selected_key = str(key) if key else None
        self._sync_interactivity()

    def is_enabled(self, key: str) -> bool:
        return bool(self._get_state(key).enabled)

    def enable(self, key: str, *, path: str, enabled: bool) -> None:
        st = self._get_state(key)
        st.enabled = bool(enabled)
        self._set_state(key, st)
        if not st.enabled:
            lbl = self._labels.get(key)
            if lbl is not None:
                try:
                    lbl.hide()
                except Exception:
                    pass
        else:
            try:
                self._ensure_label(key)
                if self._visible_requested:
                    self._apply_label(key, path, visible_override=True)
            except Exception:
                pass
        self._sync_interactivity()

    def set_global_opacity(self, opacity: float) -> None:
        try:
            opacity = float(opacity)
        except Exception:
            return
        self._global_opacity = max(0.0, min(1.0, opacity))
        for key, lbl in list(self._labels.items()):
            st = self._get_state(key)
            try:
                lbl.setWindowOpacity(self._global_opacity * float(st.opacity))
            except Exception:
                pass

    def set_all_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self._visible_requested = visible
        for key, lbl in list(self._labels.items()):
            st = self._get_state(key)
            try:
                lbl.setVisible(visible and bool(st.enabled))
            except Exception:
                pass

    def get_transform(self, key: str) -> dict:
        return dict(self._get_state(key).transform or {})

    def toggle_mirror_horizontal(self) -> None:
        """Mirror horizontally around the screen center (left-right).

        This mirrors the overlay *position* around the canvas center and also
        flips the rendered content.
        """
        self._toggle_runtime_flip_for_targets("flip_x")

    def toggle_mirror_vertical(self) -> None:
        """Mirror vertically around the screen center (top-bottom).

        This mirrors the overlay *position* around the canvas center and also
        flips the rendered content.
        """
        self._toggle_runtime_flip_for_targets("flip_y")

    def _toggle_runtime_flip_for_targets(self, flip_key: str) -> None:
        """Toggle runtime flip for selected or enabled overlays.

        This is intentionally NOT persisted; it resets on app restart.
        """
        flip_key = str(flip_key or "").strip()
        if flip_key not in ("flip_x", "flip_y"):
            return

        targets: list[str] = []
        try:
            if self._selected_key and self.is_enabled(self._selected_key):
                targets = [self._selected_key]
            else:
                targets = list(self.enabled_keys())
        except Exception:
            targets = []

        for key in targets:
            cur = False
            try:
                cur = bool(self._runtime_flips.get(key, {}).get(flip_key, False))
            except Exception:
                cur = False
            self._set_runtime_flip(key, flip_key, (not cur))

            # Re-apply immediately so the user sees the change.
            lbl = self._labels.get(key)
            path = getattr(lbl, "_zzz_source_path", None) if lbl is not None else None
            if isinstance(path, str) and path:
                try:
                    self._apply_label(key, path)
                except Exception:
                    pass

    def _set_runtime_flip(self, key: str, flip_key: str, value: bool) -> None:
        key = str(key or "").strip()
        if not key:
            return
        flip_key = str(flip_key or "").strip()
        if flip_key not in ("flip_x", "flip_y"):
            return
        try:
            d = self._runtime_flips.get(key)
            if not isinstance(d, dict):
                d = {}
            d[flip_key] = bool(value)
            self._runtime_flips[key] = d
        except Exception:
            pass

    def _get_runtime_flips(self, key: str) -> tuple[bool, bool]:
        try:
            d = self._runtime_flips.get(key)
            if not isinstance(d, dict):
                return (False, False)
            return (bool(d.get("flip_x", False)), bool(d.get("flip_y", False)))
        except Exception:
            return (False, False)

    def _effective_zoom(self, t: dict, cw: int, ch: int, src_w: int, src_h: int) -> float:
        """Match the runtime zoom behavior for mirror position calculations."""
        try:
            zoom_raw = t.get("zoom", 1.0)
        except Exception:
            zoom_raw = 1.0

        # For videos we support 'zoom: null' meaning "fit" (matches utils._LabelVideoPlayer).
        if zoom_raw is None:
            try:
                zw = float(cw) / float(max(1, src_w))
                zh = float(ch) / float(max(1, src_h))
                zoom = min(zw, zh)
            except Exception:
                zoom = 1.0
        else:
            try:
                zoom = float(zoom_raw or 1.0)
            except Exception:
                zoom = 1.0

        if not (zoom > 0):
            zoom = 1.0
        return max(0.05, min(10.0, float(zoom)))

    def _get_asset_size(self, key: str, path: Optional[str]) -> tuple[int, int]:
        """Best-effort media dimensions for mirroring math."""
        # 1) Try image dimensions directly.
        try:
            p = str(path or "").strip()
        except Exception:
            p = ""

        if p and os.path.exists(p):
            try:
                lower = p.lower()
            except Exception:
                lower = p

            if not lower.endswith((".mp4", ".avi", ".mov", ".webm", ".mkv", ".m4v")):
                try:
                    from PyQt6.QtGui import QImage

                    img = QImage(p)
                    if not img.isNull():
                        return int(img.width()), int(img.height())
                except Exception:
                    pass

        # 2) For videos, prefer the active player last-known frame size.
        try:
            lbl = self._labels.get(key)
            player = getattr(lbl, "_zzz_video_player", None) if lbl is not None else None
            if player is not None:
                fn = getattr(player, "get_source_size", None)
                if callable(fn):
                    sz = fn()
                    if isinstance(sz, tuple) and len(sz) == 2:
                        w, h = int(sz[0]), int(sz[1])
                        if w > 0 and h > 0:
                            return w, h
        except Exception:
            pass

        # 3) Fallback: probe with OpenCV if available.
        if p and os.path.exists(p):
            try:
                import cv2  # type: ignore

                cap = cv2.VideoCapture(p)
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                try:
                    cap.release()
                except Exception:
                    pass
                if w > 0 and h > 0:
                    return w, h
            except Exception:
                pass

        return (0, 0)

    def set_transform(self, key: str, update: dict) -> None:
        st = self._get_state(key)
        t = dict(st.transform or {})
        for k, v in (update or {}).items():
            t[k] = v
        st.transform = t
        self._set_state(key, st)
        # Caller will re-apply via Art Manager; we can re-render if path known.
        lbl = self._labels.get(key)
        if lbl is None:
            return
        # Defer re-apply to avoid re-rendering on every mousemove.
        try:
            self._pending_reapply.add(key)
            if not self._reapply_timer.isActive():
                self._reapply_timer.start()
        except Exception:
            path = getattr(lbl, "_zzz_source_path", None)
            if isinstance(path, str) and path:
                self._apply_label(key, path)

    def flush_transform(self, key: str) -> None:
        """Force-apply any pending transform for `key` immediately."""
        key = str(key or "").strip()
        if not key:
            return
        try:
            if key in self._pending_reapply:
                self._pending_reapply.discard(key)
        except Exception:
            pass
        lbl = self._labels.get(key)
        if lbl is None:
            return
        path = getattr(lbl, "_zzz_source_path", None)
        if isinstance(path, str) and path:
            self._apply_label(key, path)

    def _process_pending_reapply(self) -> None:
        keys = []
        try:
            keys = list(self._pending_reapply)
            self._pending_reapply.clear()
        except Exception:
            keys = []
        for key in keys:
            lbl = self._labels.get(key)
            if lbl is None:
                continue
            path = getattr(lbl, "_zzz_source_path", None)
            if isinstance(path, str) and path:
                self._apply_label(key, path)

    def set_opacity(self, key: str, opacity: float) -> None:
        st = self._get_state(key)
        try:
            st.opacity = float(opacity)
        except Exception:
            st.opacity = st.opacity
        st.opacity = max(0.0, min(1.0, st.opacity))
        self._set_state(key, st)
        lbl = self._labels.get(key)
        if lbl is not None:
            try:
                lbl.setWindowOpacity(self._global_opacity * float(st.opacity))
            except Exception:
                pass

    def apply_path(self, key: str, path: str) -> None:
        if not self.is_enabled(key):
            return
        self._ensure_label(key)
        self._apply_label(key, path)

    # --- dragging --------------------------------------------------------------------

    def can_drag(self, key: str) -> bool:
        if not self._drag_context_enabled:
            return False
        if not self._drag_hold_active:
            return False
        return bool(self.is_enabled(key))

    def _update_hold_state(self) -> None:
        """Update whether the hold-to-drag chord is currently active."""
        active = False

        def _vk_from_name(name: str) -> int | None:
            name = str(name or "").strip().lower()
            if not name:
                return None
            aliases = {
                "mouse4": "mouse_x1",
                "mouse5": "mouse_x2",
                "mouse_4": "mouse_x1",
                "mouse_5": "mouse_x2",
                "x1": "mouse_x1",
                "x2": "mouse_x2",
                "mb4": "mouse_x1",
                "mb5": "mouse_x2",
                "`": "grave",
                "~": "grave",
            }
            name = aliases.get(name, name)

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

        def _is_pressed_win32(name: str) -> bool:
            vk = _vk_from_name(name)
            if vk is None:
                return False
            try:
                state = ctypes.windll.user32.GetAsyncKeyState(int(vk))
                return bool(state & 0x8000)
            except Exception:
                return False

        # Empty by default => dragging disabled.
        if self._hold_to_drag:
            try:
                import keyboard as kb  # type: ignore
            except Exception:
                kb = None

            if kb is not None:
                for chord in self._hold_to_drag:
                    raw = str(chord or "").strip().lower()
                    if not raw:
                        continue

                    # Common alias normalization.
                    raw = {"`": "grave", "~": "grave", "mouse4": "mouse_x1", "mouse5": "mouse_x2"}.get(raw, raw)

                    # Mouse buttons aren't supported by the keyboard lib; use Win32 polling.
                    if "mouse_" in raw:
                        parts = [p.strip() for p in raw.split("+") if p.strip()]
                        if parts and all(_is_pressed_win32(p) for p in parts):
                            active = True
                            break
                        continue

                    try:
                        # keyboard.is_pressed can handle combos like "ctrl+shift" and
                        # special keys better than manual splitting.
                        if kb.is_pressed(raw):
                            active = True
                            break
                    except Exception:
                        # Fallback: try split form.
                        parts = [p.strip() for p in raw.split("+") if p.strip()]
                        if not parts:
                            continue
                        try:
                            if all(kb.is_pressed(p) for p in parts):
                                active = True
                                break
                        except Exception:
                            continue

        if active == self._drag_hold_active:
            return
        self._drag_hold_active = active
        self._sync_interactivity()

    # --- internals -------------------------------------------------------------------

    def _ensure_label(self, key: str) -> MovableOverlayLabel:
        lbl = self._labels.get(key)
        if lbl is not None:
            return lbl

        screen = self._app.primaryScreen()
        geo = screen.geometry()

        lbl = MovableOverlayLabel(self, key)
        pixmap = QPixmap(int(geo.width()), int(geo.height()))
        pixmap.fill(Qt.GlobalColor.transparent)
        lbl.setPixmap(pixmap)
        lbl.setFixedWidth(int(geo.width()))
        lbl.setFixedHeight(int(geo.height()))

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        lbl.setWindowFlags(flags)
        lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lbl.setScaledContents(False)

        # Keep hidden until explicitly shown (prevents transient stacking).
        try:
            lbl.hide()
        except Exception:
            pass

        # Ensure crosshair stays above.
        try:
            lbl.raise_()
        except Exception:
            pass
        try:
            self._crosshair_overlay.raise_()
        except Exception:
            pass

        self._labels[key] = lbl
        return lbl

    def _apply_label(self, key: str, path: str, *, visible_override: Optional[bool] = None) -> None:
        lbl = self._labels.get(key)
        if lbl is None:
            return

        path = str(path or "").strip()
        if not path or not os.path.exists(path):
            try:
                lbl.hide()
            except Exception:
                pass
            return

        st = self._get_state(key)

        try:
            setattr(lbl, "_zzz_source_path", path)
        except Exception:
            pass

        base_t = dict(st.transform or {})
        # Mirror is runtime-only; ignore any persisted flip keys from older builds.
        try:
            base_t.pop("flip_x", None)
            base_t.pop("flip_y", None)
        except Exception:
            pass

        fx, fy = self._get_runtime_flips(key)

        # Compute mirrored position around canvas center without modifying persisted x/y.
        cw, ch = (0, 0)
        try:
            cw, ch = int(self._canvas_size[0]), int(self._canvas_size[1])
        except Exception:
            cw, ch = (0, 0)

        eff_t = dict(base_t)
        if fx:
            eff_t["flip_x"] = True
        if fy:
            eff_t["flip_y"] = True

        try:
            pos_x = float(base_t.get("x", 0.0) or 0.0)
        except Exception:
            pos_x = 0.0
        try:
            pos_y = float(base_t.get("y", 0.0) or 0.0)
        except Exception:
            pos_y = 0.0

        # Only shift x/y if we can determine the asset size; otherwise just flip visually.
        try:
            src_w, src_h = self._get_asset_size(key, path)
        except Exception:
            src_w, src_h = (0, 0)

        if cw > 0 and ch > 0 and src_w > 0 and src_h > 0 and (fx or fy):
            try:
                zoom = self._effective_zoom(base_t, cw, ch, src_w, src_h)
            except Exception:
                zoom = 1.0

            w_scaled = float(src_w) * float(zoom)
            h_scaled = float(src_h) * float(zoom)

            if fx:
                eff_t["x"] = float(cw) - (pos_x + w_scaled)
            if fy:
                eff_t["y"] = float(ch) - (pos_y + h_scaled)

        set_label_art_from_path(lbl, path, canvas_size=self._canvas_size, transform=eff_t)

        try:
            target_visible = bool(st.enabled) if visible_override is None else bool(visible_override)
            lbl.setVisible(target_visible)
        except Exception:
            pass
        try:
            lbl.setWindowOpacity(self._global_opacity * float(st.opacity))
        except Exception:
            pass

        # Re-stack.
        try:
            lbl.raise_()
        except Exception:
            pass
        try:
            self._crosshair_overlay.raise_()
        except Exception:
            pass

    def _sync_interactivity(self) -> None:
        for key, lbl in list(self._labels.items()):
            desired_interactive = bool(self._drag_context_enabled and self._drag_hold_active and self.is_enabled(key))
            self._set_label_interactive(lbl, desired_interactive)

    def _set_label_interactive(self, lbl: QLabel, interactive: bool) -> None:
        interactive = bool(interactive)
        flags = lbl.windowFlags()
        try:
            was_visible = bool(lbl.isVisible())
        except Exception:
            was_visible = False
        if interactive:
            if flags & Qt.WindowType.WindowTransparentForInput:
                flags = flags & ~Qt.WindowType.WindowTransparentForInput
        else:
            if not (flags & Qt.WindowType.WindowTransparentForInput):
                flags = flags | Qt.WindowType.WindowTransparentForInput

        try:
            lbl.setWindowFlags(flags)
            if was_visible:
                lbl.show()
                lbl.raise_()
                self._crosshair_overlay.raise_()
            else:
                lbl.hide()
        except Exception:
            pass
