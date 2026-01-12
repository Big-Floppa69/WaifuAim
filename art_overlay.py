"""Separate art overlay elements (images/videos) with per-element transforms.

This replaces the old "composition" workflow and does NOT introduce a separate
"media elements" UI; instead, elements are toggled via checkboxes in the Art
Manager.

Persistence lives in app_settings.json under the key "art_overlays".
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QLabel

from utils import APP_SETTINGS_PATH, set_label_art_from_path


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

        # Monotonic counter to cancel stale deferred renders.
        self._render_generation = 0

        # Drag context is enabled while the Art Manager is open.
        self._drag_context_enabled = False
        self._selected_key: Optional[str] = None
        # Optional hold chord, e.g. "alt" or "ctrl+shift". Empty => no hold.
        self._hold_to_drag: list[str] = []

        # Whether the UI currently expects art overlays to be visible.
        # Used so checkbox toggles can render immediately when "Show Art" is on.
        self._visible_requested = False

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
        data = self._read_settings()
        raw = data.get("art_overlays")
        overlays = raw if isinstance(raw, dict) else {}
        for k, v in list(overlays.items()):
            if isinstance(v, dict):
                v["enabled"] = False
                overlays[k] = v
        data["art_overlays"] = overlays
        self._write_settings(data)
        for _k, lbl in list(self._labels.items()):
            try:
                lbl.hide()
            except Exception:
                pass
        self._sync_interactivity()

    def set_selection_keys(self, keys: list[str]) -> None:
        """Set checkmarks to exactly `keys` (others become unchecked)."""
        wanted = {str(k) for k in (keys or []) if str(k).strip()}
        data = self._read_settings()
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
        self._write_settings(data)
        self._sync_interactivity()

    def render_selected_from_folder(self, folder: str = "display_images") -> None:
        """Render all checked items (selection) into overlay labels.

        This does not change selection; it just applies the current transform
        state to the on-screen overlays.
        """
        folder = str(folder or "").strip() or "display_images"
        abs_folder = os.path.abspath(folder)
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
        abs_folder = os.path.abspath(folder)
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
            if APP_SETTINGS_PATH.exists():
                raw = json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
                return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}
        return {}

    def _write_settings(self, data: dict) -> None:
        try:
            if not isinstance(data, dict):
                return
            APP_SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
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
        data = self._read_settings()
        overlays = data.get("art_overlays")
        if not isinstance(overlays, dict):
            overlays = {}
        overlays[key] = {
            "enabled": bool(state.enabled),
            "opacity": float(state.opacity),
            "transform": dict(state.transform or {}),
        }
        data["art_overlays"] = overlays
        self._write_settings(data)

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
        if not self._selected_key or self._selected_key != key:
            return False

        # If a hold chord is configured, require it.
        if self._hold_to_drag:
            try:
                import keyboard as kb  # type: ignore
            except Exception:
                return False

            # Accept if ANY configured chord is held.
            for chord in self._hold_to_drag:
                parts = [p.strip() for p in str(chord).split("+") if p.strip()]
                if not parts:
                    continue
                try:
                    if all(kb.is_pressed(p) for p in parts):
                        return True
                except Exception:
                    continue
            return False

        # Default: no key required while Art Manager is open.
        return True

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

        set_label_art_from_path(lbl, path, canvas_size=self._canvas_size, transform=dict(st.transform or {}))

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
            desired_interactive = bool(self._drag_context_enabled and self._selected_key == key)
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
