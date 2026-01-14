"""Utility functions for the crosshair application."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QImage, QPixmap, QPainter
from PyQt6.QtCore import QObject, QThread, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None
try:
    import cv2  # type: ignore
except Exception:
    cv2 = None


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
    """Mirror the image vertically.

    Applies mirroring to the *stored source image* (unfiltered), then re-renders
    according to the current persisted colorblind mode.
    """
    source = _get_label_source_image(label)
    if source is None:
        if pixmap is None:
            return
        try:
            source = pixmap.toImage()
        except Exception:
            return
    mirrored = source.mirrored(False, True)
    _set_label_source_image(label, mirrored)
    refresh_label_pixmap_for_colorblind_mode(label)


def mirror_horizontal(label, pixmap):
    """Mirror the image horizontally.

    Applies mirroring to the *stored source image* (unfiltered), then re-renders
    according to the current persisted colorblind mode.
    """
    source = _get_label_source_image(label)
    if source is None:
        if pixmap is None:
            return
        try:
            source = pixmap.toImage()
        except Exception:
            return
    mirrored = source.mirrored(True, False)
    _set_label_source_image(label, mirrored)
    refresh_label_pixmap_for_colorblind_mode(label)


def get_art_list(folder="display_images"):
    """Get list of art files (images + videos) in the display_images folder."""

    exts = ART_EXTS
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


def _art_key_for_path(path: str) -> str:
    """Return stable key for an art asset.

    Uses project-root-relative paths (same scheme as ArtOverlayController).
    """
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        return os.path.relpath(os.path.abspath(path), root).replace("\\", "/")
    except Exception:
        return os.path.abspath(path).replace("\\", "/")


def get_art_cycle_entries(folder: str = "display_images") -> list[dict]:
    """Return the art switching sequence (files + combos) in user-defined order.

    Reads app_settings.json keys:
    - art_cycle_sequence: list[dict] of {type: file/combo, key/name, enabled}
    - art_combos: list[dict] of {name, keys}

    Falls back to legacy ordering if no saved sequence exists.
    """
    folder = str(folder or "").strip() or "display_images"

    # Build file lookup by stable key.
    file_paths = [p for p in get_art_list(folder) if str(p).strip()]
    key_to_path: dict[str, str] = {}
    for p in file_paths:
        key = _art_key_for_path(p)
        if key:
            key_to_path[key] = p

    data = read_app_settings()

    # Build combo lookup by name.
    combos_raw = data.get("art_combos")
    combo_name_to_keys: dict[str, list[str]] = {}
    if isinstance(combos_raw, list):
        for c in combos_raw:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            keys = c.get("keys")
            if not name or not isinstance(keys, list) or not keys:
                continue
            combo_name_to_keys[name] = [str(k) for k in keys if str(k).strip()]

    def _default_entries() -> list[dict]:
        out: list[dict] = []
        for p in sorted(file_paths, key=lambda s: os.path.basename(str(s)).lower()):
            out.append({"type": "file", "path": p})
        for name, keys in sorted(combo_name_to_keys.items(), key=lambda kv: kv[0].lower()):
            out.append({"type": "combo", "name": name, "keys": keys})
        return out

    seq = data.get("art_cycle_sequence")
    if not isinstance(seq, list) or not seq:
        return _default_entries()

    out: list[dict] = []
    for entry in seq:
        if not isinstance(entry, dict):
            continue
        if not bool(entry.get("enabled", True)):
            continue
        t = str(entry.get("type") or "").strip().lower()
        if t == "file":
            key = str(entry.get("key") or "").strip()
            path = key_to_path.get(key)
            if path:
                out.append({"type": "file", "path": path})
        elif t == "combo":
            name = str(entry.get("name") or "").strip()
            keys = combo_name_to_keys.get(name)
            if name and keys:
                out.append({"type": "combo", "name": name, "keys": keys})

    # If everything got filtered out (e.g., deleted files), fall back.
    return out if out else _default_entries()


# --- Art file types -----------------------------------------------------------------

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
VIDEO_EXTS = (".mp4", ".avi", ".mov", ".webm", ".mkv", ".m4v")
ART_EXTS = tuple(sorted(set(IMAGE_EXTS + VIDEO_EXTS)))


def is_video_path(path: str) -> bool:
    p = str(path or "").strip().lower()
    return any(p.endswith(ext) for ext in VIDEO_EXTS)


def _key_out_near_black(img: QImage, *, threshold: int = 12) -> QImage:
    """Turn near-black pixels transparent.

    Used to emulate transparency for MP4 composites (which have no alpha).
    Threshold is in 0..255; smaller means less aggressive.
    """
    try:
        if np is None:
            return img
        if img is None or getattr(img, "isNull", lambda: True)():
            return img

        # Fast-ish soft key: compute a gradual alpha ramp near the threshold.
        # To avoid making dark subjects disappear, prefer removing only near-
        # black pixels connected to the frame border (typical "black background"
        # composites). This keeps interior dark details.
        t0 = int(max(0, min(255, threshold)))
        # Feather band width (in brightness levels). Keep modest.
        t1 = int(max(t0 + 1, min(255, t0 + 12)))

        rgba = img.convertToFormat(QImage.Format.Format_RGBA8888)
        try:
            rgba = rgba.copy()
        except Exception:
            pass

        w = rgba.width()
        h = rgba.height()
        ptr = rgba.bits()
        ptr.setsize(h * rgba.bytesPerLine())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, rgba.bytesPerLine() // 4, 4))
        arr = arr[:, :w, :]

        rgb_max = np.maximum.reduce([arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]]).astype(np.int16)
        a = arr[:, :, 3].astype(np.float32)

        denom = float(max(1, (t1 - t0)))
        scale = (rgb_max.astype(np.float32) - float(t0)) / denom
        np.clip(scale, 0.0, 1.0, out=scale)

        # Determine which pixels we are allowed to key.
        # Candidates are near-black within the feather band.
        candidates = (rgb_max <= t1)
        bg_mask = candidates

        # If OpenCV is available, restrict keying to near-black regions connected
        # to the border, computed on a downscaled mask for speed.
        if cv2 is not None:
            try:
                # Downscale mask to reduce connected-components cost.
                scale_div = 4
                small_w = max(1, int(w) // scale_div)
                small_h = max(1, int(h) // scale_div)
                cand8 = (candidates.astype(np.uint8) * 255)
                cand_small = cv2.resize(cand8, (small_w, small_h), interpolation=cv2.INTER_NEAREST)
                comp = cv2.connectedComponentsWithStats((cand_small > 0).astype(np.uint8), connectivity=8)
                labels = comp[1]
                # Labels touching border are treated as background.
                border = np.concatenate(
                    [
                        labels[0, :],
                        labels[-1, :],
                        labels[:, 0],
                        labels[:, -1],
                    ]
                )
                border_labels = np.unique(border)
                border_labels = border_labels[border_labels != 0]
                if border_labels.size > 0:
                    bg_small = np.isin(labels, border_labels)
                    bg8 = (bg_small.astype(np.uint8) * 255)
                    bg_up = cv2.resize(bg8, (int(w), int(h)), interpolation=cv2.INTER_NEAREST)
                    bg_mask = (bg_up > 0) & candidates
                else:
                    bg_mask = candidates
            except Exception:
                bg_mask = candidates

        # Apply alpha scaling only for background-ish pixels.
        if np.any(bg_mask):
            a[bg_mask] *= scale[bg_mask]

        # Optional tiny blur of the alpha edge to reduce blocky MP4 artifacts.
        if cv2 is not None:
            try:
                if np.any((a > 0.0) & (a < 255.0)):
                    alpha8 = a.astype(np.uint8)
                    alpha8 = cv2.GaussianBlur(alpha8, (3, 3), 0)
                    a = alpha8.astype(np.float32)
            except Exception:
                pass

        arr[:, :, 3] = np.clip(a, 0.0, 255.0).astype(np.uint8)

        # Use premultiplied alpha for smoother Qt compositing.
        try:
            return rgba.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        except Exception:
            return rgba
    except Exception:
        return img


def _get_project_root() -> Path:
    """Return the repository root directory.

    Used for storing/reading per-asset transforms with stable relative keys.
    """
    return Path(__file__).resolve().parent


def _art_transform_path() -> Path:
    return _get_project_root() / "art_transforms.json"


def load_art_transforms() -> dict:
    """Load persisted transforms for video assets."""
    path = _art_transform_path()
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
    return {}


def save_art_transforms(data: dict) -> None:
    path = _art_transform_path()
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _normalize_art_key(path: str) -> str:
    """Normalize art path for transform storage.

    Prefers a stable key relative to the project root when possible.
    """
    p = str(path or "").strip()
    if not p:
        return ""
    try:
        root = _get_project_root()
        return os.path.relpath(p, str(root)).replace("\\", "/")
    except Exception:
        return p.replace("\\", "/")


class _LabelVideoPlayer(QObject):
    """Plays a video into a QLabel by rendering frames to a pixmap.

    This avoids needing a QVideoWidget and keeps compatibility with the existing
    QLabel overlay pipeline.
    """

    def __init__(
        self,
        label: QLabel,
        source_path: str,
        canvas_size=(1920, 1080),
        transform: Optional[dict] = None,
        *,
        key_black: bool = False,
        key_threshold: int = 12,
    ):
        super().__init__(label)
        self._label = label
        self._source_path = str(source_path)
        self._canvas_w = int(canvas_size[0])
        self._canvas_h = int(canvas_size[1])
        self._transform = transform or {}
        self._key_black = bool(key_black)
        self._key_threshold = int(key_threshold)

        self._latest_frame = None
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_display)
        self._update_timer.start(1000 // 30)  # 30 fps

        self._audio = QAudioOutput()
        try:
            self._audio.setVolume(0.0)
        except Exception:
            pass

        self._sink = QVideoSink()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._sink)

        self._sink.videoFrameChanged.connect(self._on_frame)
        self._player.mediaStatusChanged.connect(self._on_status)

    def set_transform(self, transform: Optional[dict]) -> None:
        self._transform = transform or {}

    def start(self) -> None:
        try:
            self._player.setSource(QUrl.fromLocalFile(os.path.abspath(self._source_path)))
            self._player.play()
            self._update_timer.start(1000 // 30)
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self._player.stop()
        except Exception:
            pass
        try:
            self._sink.videoFrameChanged.disconnect(self._on_frame)
        except Exception:
            pass
        try:
            self._player.mediaStatusChanged.disconnect(self._on_status)
        except Exception:
            pass
        try:
            self._update_timer.stop()
        except Exception:
            pass

    def _on_status(self, status) -> None:
        # Loop forever.
        try:
            if status == QMediaPlayer.MediaStatus.EndOfMedia:
                self._player.setPosition(0)
                self._player.play()
        except Exception:
            pass

    def _on_frame(self, frame) -> None:
        try:
            img = frame.toImage()
        except Exception:
            img = None
        if img is None or getattr(img, "isNull", lambda: True)():
            return

        self._latest_frame = img

    def _update_display(self) -> None:
        if self._latest_frame is None:
            return

        img = self._latest_frame

        if self._key_black:
            img = _key_out_near_black(img, threshold=self._key_threshold)

        # Transform defaults.
        # If zoom is not specified, fit the frame into the canvas.
        try:
            zoom_raw = self._transform.get("zoom", None)
        except Exception:
            zoom_raw = None

        if zoom_raw is None:
            try:
                zw = float(self._canvas_w) / float(max(1, img.width()))
                zh = float(self._canvas_h) / float(max(1, img.height()))
                zoom = min(zw, zh)
            except Exception:
                zoom = 1.0
        else:
            try:
                zoom = float(zoom_raw or 1.0)
            except Exception:
                zoom = 1.0
        try:
            rotation = float(self._transform.get("rotation", 0.0) or 0.0)
        except Exception:
            rotation = 0.0
        try:
            pos_x = float(self._transform.get("x", (self._canvas_w - img.width()) / 2.0) or 0.0)
        except Exception:
            pos_x = (self._canvas_w - img.width()) / 2.0
        try:
            pos_y = float(self._transform.get("y", (self._canvas_h - img.height()) / 2.0) or 0.0)
        except Exception:
            pos_y = (self._canvas_h - img.height()) / 2.0

        # Sanity clamps: bad persisted transforms can push video fully off-screen,
        # making it appear "invisible".
        if not (zoom > 0):
            zoom = 1.0
        zoom = max(0.05, min(10.0, zoom))
        try:
            # keep rotation in a reasonable range
            rotation = float(rotation) % 360.0
        except Exception:
            rotation = 0.0

        canvas = QImage(self._canvas_w, self._canvas_h, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Draw rotated & scaled about its center. Use painter transforms instead
        # of allocating/scaling a QPixmap each frame (less CPU + less GC churn).
        try:
            img2 = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        except Exception:
            img2 = img
        w = float(img2.width())
        h = float(img2.height())

        # If the transformed image is completely outside the canvas, recenter.
        try:
            tw = w * zoom
            th = h * zoom
            off = (pos_x + tw < 1) or (pos_x > self._canvas_w - 1) or (pos_y + th < 1) or (pos_y > self._canvas_h - 1)
            if off:
                pos_x = (self._canvas_w - w) / 2.0
                pos_y = (self._canvas_h - h) / 2.0
        except Exception:
            pass

        painter.save()
        painter.translate(pos_x + (w * zoom) / 2.0, pos_y + (h * zoom) / 2.0)
        painter.rotate(rotation)
        if zoom != 1.0:
            painter.scale(zoom, zoom)
        painter.translate(-w / 2.0, -h / 2.0)
        painter.drawImage(0, 0, img2)
        painter.restore()
        painter.end()

        try:
            self._label.setPixmap(QPixmap.fromImage(canvas))
        except Exception:
            pass


def _stop_label_video_if_any(label: QLabel) -> None:
    player = _get_attr(label, "_zzz_video_player", None)
    if player is None:
        return
    try:
        player.stop()
    except Exception:
        pass
    _set_attr(label, "_zzz_video_player", None)


def clear_label_art(label: QLabel) -> None:
    """Stop any label video and clear to a fully transparent pixmap."""
    try:
        _stop_label_video_if_any(label)
    except Exception:
        pass

    try:
        w = max(1, int(label.width()))
        h = max(1, int(label.height()))
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        label.setPixmap(pm)
    except Exception:
        pass

    # Clear image-related caches/state so later transforms/mirroring don't reuse old content.
    try:
        _set_attr(label, _LABEL_SOURCE_IMAGE_PROP, None)
        _set_attr(label, "_zzz_cvd_cache", {})
    except Exception:
        pass


def set_label_art_from_path(
    label: QLabel,
    path: str,
    *,
    canvas_size: Optional[tuple[int, int]] = None,
    transform: Optional[dict] = None,
) -> None:
    """Set the overlay label content from either an image or a video path.

    Backwards compatible behavior (existing calls):
    - images render directly via `set_label_image_from_path` (supports mirroring + CVD).
    - videos render via a QVideoSink player into the label.

    New behavior (used by "media elements"):
    - optional `canvas_size` and `transform` allow rendering the asset into a
      full-screen transparent canvas (x/y/zoom/rotation), so multiple elements
      can be layered as independent overlay labels.
    """
    path = str(path or "").strip()
    if not path:
        return

    _stop_label_video_if_any(label)

    # Determine canvas size (for sprite-style rendering).
    if canvas_size is None:
        try:
            w = int(label.width())
            h = int(label.height())
            if w > 0 and h > 0:
                canvas_size = (w, h)
        except Exception:
            canvas_size = None

    if not is_video_path(path):
        # Default (legacy) behavior: image fills label pixmap directly.
        if transform is None and canvas_size is None:
            set_label_image_from_path(label, path)
            return

        # Sprite-style image rendering onto a transparent canvas.
        try:
            img = QImage(path)
            if img.isNull():
                return
        except Exception:
            return

        cw, ch = (1920, 1080)
        try:
            if canvas_size is not None:
                cw, ch = int(canvas_size[0]), int(canvas_size[1])
        except Exception:
            cw, ch = (1920, 1080)

        t = dict(transform or {})
        try:
            zoom = float(t.get("zoom", 1.0) or 1.0)
        except Exception:
            zoom = 1.0
        try:
            rotation = float(t.get("rotation", 0.0) or 0.0)
        except Exception:
            rotation = 0.0
        try:
            pos_x = float(t.get("x", (cw - img.width()) / 2.0) or 0.0)
        except Exception:
            pos_x = (cw - img.width()) / 2.0
        try:
            pos_y = float(t.get("y", (ch - img.height()) / 2.0) or 0.0)
        except Exception:
            pos_y = (ch - img.height()) / 2.0

        if not (zoom > 0):
            zoom = 1.0
        zoom = max(0.05, min(10.0, zoom))
        try:
            rotation = float(rotation) % 360.0
        except Exception:
            rotation = 0.0

        canvas = QImage(cw, ch, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        try:
            img2 = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        except Exception:
            img2 = img
        w = float(img2.width())
        h = float(img2.height())

        painter.save()
        painter.translate(pos_x + (w * zoom) / 2.0, pos_y + (h * zoom) / 2.0)
        painter.rotate(rotation)
        if zoom != 1.0:
            painter.scale(zoom, zoom)
        painter.translate(-w / 2.0, -h / 2.0)
        painter.drawImage(0, 0, img2)
        painter.restore()
        painter.end()

        try:
            label.setPixmap(QPixmap.fromImage(canvas))
        except Exception:
            pass
        return

    # If this label is already playing the same video, just update transform.
    try:
        existing_src = _get_attr(label, "_zzz_video_source", None)
        existing_player = _get_attr(label, "_zzz_video_player", None)
        if isinstance(existing_src, str) and os.path.abspath(existing_src) == os.path.abspath(path) and existing_player is not None:
            try:
                existing_player.set_transform(dict(transform or {}))
                return
            except Exception:
                pass
    except Exception:
        pass

    # Clear any stored image source so image-only operations don't interfere.
    try:
        _set_attr(label, _LABEL_SOURCE_IMAGE_PROP, None)
        _set_attr(label, "_zzz_cvd_cache", {})
    except Exception:
        pass

    # Videos: render frames into label pixmap (looping) and apply transform.
    t = dict(transform or {})

    cw, ch = (1920, 1080)
    try:
        if canvas_size is not None:
            cw, ch = int(canvas_size[0]), int(canvas_size[1])
    except Exception:
        cw, ch = (1920, 1080)

    player = _LabelVideoPlayer(
        label,
        path,
        canvas_size=(cw, ch),
        transform=t,
        key_black=False,
        key_threshold=12,
    )
    _set_attr(label, "_zzz_video_source", path)
    _set_attr(label, "_zzz_video_player", player)
    player.start()


def transparent(label, percent):
    """Set the opacity of the label."""
    label.setWindowOpacity(percent)


# --- Colorblindness (image filtering) -------------------------------------------------

APP_SETTINGS_PATH = Path(__file__).resolve().with_name("app_settings.json")

_LABEL_SOURCE_IMAGE_PROP = "_zzz_source_image"


class _CvdWorker(QObject):
    finished = pyqtSignal(object)  # QImage

    def __init__(self, source: QImage, mode: str):
        super().__init__()
        self._source = source
        self._mode = mode

    def run(self) -> None:
        try:
            out = apply_colorblind_mode_to_qimage(self._source, self._mode)
        except Exception:
            out = self._source
        self.finished.emit(out)


def _get_attr(obj, name: str, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _set_attr(obj, name: str, value) -> None:
    try:
        setattr(obj, name, value)
    except Exception:
        pass


def read_app_settings() -> dict:
    try:
        if APP_SETTINGS_PATH.exists():
            raw = json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
    return {}


def write_app_settings(data: dict) -> None:
    try:
        if not isinstance(data, dict):
            return
        APP_SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "ru": "Русский",
}


_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "opacity_language_title": "Opacity, Language",
        "crosshair_opacity": "Crosshair Opacity",
        "window_opacity": "Window Opacity",
        "colorblind_mode": "Colorblind Mode",
        "language": "Language",
        "english": "English",
        "russian": "Russian",
        "colorblind_prefix": "Colorblind",
    },
    "ru": {
        "opacity_language_title": "Прозрачность, Язык",
        "crosshair_opacity": "Прозрачность прицела",
        "window_opacity": "Прозрачность окна",
        "colorblind_mode": "Режим дальтонизма",
        "language": "Язык",
        "english": "Английский",
        "russian": "Русский",
        "colorblind_prefix": "Дальтонизм",
    },
}


def get_app_language_from_disk(default: str = "en") -> str:
    default = str(default or "en").strip().lower() or "en"
    if default not in SUPPORTED_LANGUAGES:
        default = "en"
    data = read_app_settings()
    lang = str(data.get("language", default) or default).strip().lower()
    return lang if lang in SUPPORTED_LANGUAGES else default


def set_app_language_on_disk(lang: str) -> str:
    lang = str(lang or "en").strip().lower() or "en"
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"
    data = read_app_settings()
    data["language"] = lang
    write_app_settings(data)
    return lang


def tr(key: str, *, lang: str | None = None, default: str | None = None) -> str:
    key = str(key or "").strip()
    if not key:
        return default or ""
    if lang is None:
        lang = get_app_language_from_disk("en")
    lang = str(lang or "en").strip().lower() or "en"
    table = _TRANSLATIONS.get(lang) or _TRANSLATIONS.get("en", {})
    if key in table:
        return str(table[key])
    fallback = _TRANSLATIONS.get("en", {})
    if key in fallback:
        return str(fallback[key])
    return default or key


_LIT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        "Crosshair Control": "Управление прицелом",
        "Standard Crosshair": "WaifuAim",
        "\N{BULLSEYE} Standard Crosshair": "\N{BULLSEYE} WaifuAim",
        "Choose or edit a preset for generated crosshairs.": "Выберите или отредактируйте профиль для сгенерированного прицела.",
        "Preset": "Профиль",
        "Save": "Сохранить",
        "Save As": "Сохранить как",
        "Delete": "Удалить",
        "Reset": "Сбросить",
        "Apply": "Применить",
        "Cancel": "Отмена",
        "Edit": "Редактировать",
        "Error": "Ошибка",
        "Open Line Builder": "Открыть конструктор линий",
        "Hide Crosshair": "Скрыть прицел",
        "Show Crosshair": "Показать прицел",
        "Hide Image": "Скрыть изображение",
        "Show Image": "Показать изображение",
        "Show/Hide Image": "Показать/скрыть изображение",
        "Hide UI": "Скрыть интерфейс",
        "Show UI": "Показать интерфейс",
            "Show/Hide Crosshair": "Показать/скрыть прицел",
            "🖼️ Hide Image": "🖼️ Скрыть изображение",
            "🖼️ Show Image": "🖼️ Показать изображение",
            "🎯 Hide Crosshair": "🎯 Скрыть прицел",
            "🎯 Show Crosshair": "🎯 Показать прицел",
            "👁️ Hide Crosshair": "👁️ Скрыть прицел",
            "↺ Reset": "↺ Сбросить",
        "Disable App": "Отключить приложение",
        "Enable App": "Включить приложение",
        "Crosshair App": "Приложение прицела",
        "Enable Hotkeys": "Включить хоткеи",
        "Restart App": "Перезапустить приложение",
        "Exit App": "Выйти",
        "The app is currently active. Exit anyway?": "Приложение сейчас активно. Всё равно выйти?",
        "\N{ARTIST PALETTE} Palette": "\N{ARTIST PALETTE} Палитра",
        "Pick Crosshair Color": "Выбор цвета прицела",
        "Advanced Line Builder": "Расширенный конструктор линий",
        "\N{LEFTWARDS ARROW} Back": "\N{LEFTWARDS ARROW} Назад",
        "Shape stacked lines, drag their order, and preview the result instantly.": "Создавайте составные линии, перетаскивайте их порядок и сразу смотрите результат.",
        "Standard lines still respect the toggles above; builder layers optional geometry on top.": "Стандартные линии всё ещё зависят от переключателей выше; конструктор добавляет дополнительную геометрию поверх.",
        "Drag custom lines to reorder draw priority or stack multiple spokes at once.": "Перетаскивайте пользовательские линии, чтобы менять порядок отрисовки или накладывать несколько элементов.",
        "Select an object to edit it.": "Выберите объект, чтобы редактировать его.",
        "Live Preview": "Предпросмотр",
        "Metadata": "Метаданные",
        "Selected Object": "Выбранный объект",
        "Layer name": "Название слоя",
        "Label": "Название",
        "Angle": "Угол",
        "Offset": "Смещение",
        "Tip": "Наконечник",
        "Duplicate selected object": "Дублировать выбранный объект",
        "Delete selected object": "Удалить выбранный объект",
        "Click-drag on the canvas to draw a new object": "Зажмите и тяните на холсте, чтобы нарисовать новый объект",
        "Select an object on the canvas (or in the left list) to edit its properties in Metadata.": "Выберите объект на холсте (или в левом списке), чтобы редактировать его свойства в Метаданных.",
        "＋ Line": "＋ Линия",
        "＋ Circle": "＋ Круг",
        "＋ Square": "＋ Квадрат",
        "＋ Triangle": "＋ Треугольник",
        "✎ Draw": "✎ Рисовать",
        "Grid Size": "Размер сетки",
        "Basic": "Основное",
        "Transform": "Трансформация",
        "Dot": "Точка",
        "Color": "Цвет",
        "Size": "Размер",
        "Length": "Длина",
        "Thickness": "Толщина",
        "Gap": "Зазор",
        "Outline": "Обводка",
        "Rotation": "Поворот",
        "Horizontal Offset": "Смещение по горизонтали",
        "Vertical Offset": "Смещение по вертикали",
        "Line Corner Radius": "Скругление углов",
        "Crosshair Style": "Стиль прицела",
        "Enable Fan Animation": "Включить анимацию вращения",
        "Fan Speed": "Скорость вращения",
        "Randomize": "Случайно",
        "From Presets": "Из профилей",
        "Presets": "Профили",
        "Preset": "Профиль",
        "Fully Random": "Полностью случайно",
        "Normal Random": "Нормальный рандом",
        "Chaos Random": "Хаотичный рандом",
        "Absolute Random": "Абсолютный рандом",
        "Enable randomize hotkey": "Включить хоткей рандома",
        "Click, then press a key or mouse button": "Нажмите, затем нажмите клавишу или кнопку мыши",
        "Press a key… (Esc to cancel)": "Нажмите клавишу… (Esc для отмены)",
        "Fade while holding": "Скрывать при удержании",
        "\N{ARTIST PALETTE} Art Manager": "\N{ARTIST PALETTE} Менеджер Артов",
        "Art Manager": "Менеджер Артов",
        "🎨 Art Manager": "🎨 Менеджер Артов",
        "Manage your crosshair art (images + videos)": "Управляйте артом для прицела (изображения + видео)",
        "Supported formats: PNG, JPG, JPEG, WEBP, GIF, BMP, MP4, AVI, MOV, WEBM, MKV, M4V": "Поддерживаемые форматы: PNG, JPG, JPEG, WEBP, GIF, BMP, MP4, AVI, MOV, WEBM, MKV, M4V",
        "Add Art": "Добавить арт",
        "Remove": "Удалить",
        "Edit selected": "Редактировать выбранное",
        "Show/Hide marked": "Показать/скрыть отмеченное",
        "Save marked as combo": "Сохранить отмеченное как комбо",
        "🔄 Refresh List": "🔄 Обновить список",
        "Edit Combo": "Редактировать комбо",
        "Combo not found.": "Комбо не найдено.",
        "Name:": "Имя:",
        "Combo must include at least one item.": "Комбо должно содержать хотя бы один элемент.",
        "Save Combo": "Сохранить комбо",
        "No marked items to save.": "Нет отмеченных элементов для сохранения.",
        "Combo name:": "Название комбо:",
        "Combo": "Комбо",
        "Saved combo:": "Сохранено комбо:",
        "\N{KEYBOARD} Hotkey Manager": "\N{KEYBOARD} Менеджер горячих клавиш",
        "⌨️ Hotkey Manager": "⌨️ Менеджер горячих клавиш",
            "Save Hotkeys": "Сохранить горячие клавиши",
            "Reset to Defaults": "Сбросить по умолчанию",
            "Toggle Visibility": "Показать/скрыть",
            "Mirror Vertical": "Отразить по вертикали",
            "Mirror Horizontal": "Отразить по горизонтали",
            "Switch Image": "Переключить изображение",
            "Randomize Crosshair": "Рандом прицела",
            "Hold to Drag Element": "Удерживать для перетаскивания",
            "Standard Lines": "Стандартные линии",
            "Custom Lines": "Пользовательские линии",
            "Objects": "Объекты",
        "Press a key or ESC to cancel...": "Нажмите клавишу или ESC для отмены...",
        "Click and press a key...": "Нажмите и затем нажмите клавиши...",
        "Add another hotkey": "Добавить еще одну комбинацию",
        "Click on a field and press a key combination to set a hotkey.\nPress ESC to cancel while editing.": "Нажмите на поле и затем комбинацию клавиш, чтобы назначить хоткей.\nНажмите ESC для отмены во время редактирования.",
        "Opacity": "Прозрачность",

        "Add Center Dot": "Добавить центральную точку",
        "Visible": "Видимый",
        "Draggable": "Перетаскиваемый",
        "⚲ Snap": "⚲ Привязка",

        # Image editor / file dialogs / message boxes
        "Art Files (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.mp4 *.avi *.mov *.webm *.mkv *.m4v)": "Файлы арта (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.mp4 *.avi *.mov *.webm *.mkv *.m4v)",
        "No Content": "Нет содержимого",
        "Add images/videos first.": "Сначала добавьте изображения/видео.",
        "Saved": "Сохранено",
        "Saved position for this element.": "Сохранена позиция для этого элемента.",
        "Saved to:": "Сохранено в:",
        "Missing Dependency": "Не хватает зависимости",
        "MP4 export requires opencv-python (and numpy). Install it and restart the app.": "Экспорт MP4 требует opencv-python (и numpy). Установите их и перезапустите приложение.",
        "Save Video": "Сохранить видео",
        "Save Image": "Сохранить изображение",
        "MP4 Video (*.mp4)": "Видео MP4 (*.mp4)",
        "PNG Image (*.png)": "Изображение PNG (*.png)",
        "Failed to add image:": "Не удалось добавить изображение:",
        "Failed to add video:": "Не удалось добавить видео:",
        "Failed to save position:": "Не удалось сохранить позицию:",
        "Failed to save:": "Не удалось сохранить:",
        "Project": "Проект",
        "Failed to load project:": "Не удалось загрузить проект:",
        "No Selection": "Нет выбора",
        "Select an element to rename.": "Выберите элемент, чтобы переименовать.",
        "Rename": "Переименовать",
        "New file name:": "Новое имя файла:",
        "A file with that name already exists.": "Файл с таким именем уже существует.",
        "Failed to rename:": "Не удалось переименовать:",
        "Select element(s) to delete.": "Выберите элемент(ы) для удаления.",
        "Remove Element": "Удалить элемент",
        "Remove selected element(s) from the editor? (Files will NOT be deleted)": "Удалить выбранный(е) элемент(ы) из редактора? (Файлы НЕ будут удалены)",
        "File Exists": "Файл уже существует",
        "already exists in display_images. Overwrite?": "уже существует в display_images. Перезаписать?",

        # Art manager editor
        "Selected file no longer exists.": "Выбранный файл больше не существует.",
        "Failed to open editor:": "Не удалось открыть редактор:",

        # Hotkey manager
        "Duplicate Hotkeys": "Дубликаты горячих клавиш",
        "You have assigned the same hotkey to multiple actions. Please use unique hotkeys.": "Одна и та же комбинация назначена нескольким действиям. Используйте уникальные комбинации.",
        "Hotkeys Saved": "Горячие клавиши сохранены",
        "Hotkeys have been saved and applied successfully!": "Горячие клавиши успешно сохранены и применены!",
        "Save Error": "Ошибка сохранения",
        "Failed to save hotkeys:": "Не удалось сохранить горячие клавиши:",
    },
    "en": {},
}


def tr_lit(text: str, *, lang: str | None = None) -> str:
    """Translate a literal UI string.

    Use when retrofitting i18n across a codebase that already has lots of
    hard-coded English strings.
    """
    s = str(text or "")
    if lang is None:
        lang = get_app_language_from_disk("en")
    lang = str(lang or "en").strip().lower() or "en"
    mapping = _LIT_TRANSLATIONS.get(lang) or {}
    return mapping.get(s, s)


def apply_language_to_object_tree(root: QObject, *, lang: str | None = None) -> None:
    """Apply `tr_lit()` to common text-bearing Qt objects under `root`.

    Safe by design: only exact known strings are translated; unknown strings are
    left untouched.
    """
    if root is None:
        return
    if lang is None:
        lang = get_app_language_from_disk("en")

    def _maybe_translate_attr(obj: object, getter: str, setter: str) -> None:
        try:
            get_fn = getattr(obj, getter, None)
            set_fn = getattr(obj, setter, None)
            if not callable(get_fn) or not callable(set_fn):
                return
            old = get_fn()
            if not isinstance(old, str) or not old:
                return
            new = tr_lit(old, lang=lang)
            if new != old:
                set_fn(new)
        except Exception:
            return

    def _apply(obj: QObject) -> None:
        _maybe_translate_attr(obj, "text", "setText")
        _maybe_translate_attr(obj, "windowTitle", "setWindowTitle")
        _maybe_translate_attr(obj, "toolTip", "setToolTip")
        _maybe_translate_attr(obj, "statusTip", "setStatusTip")
        _maybe_translate_attr(obj, "whatsThis", "setWhatsThis")
        _maybe_translate_attr(obj, "placeholderText", "setPlaceholderText")
        _maybe_translate_attr(obj, "title", "setTitle")

        try:
            from PyQt6.QtWidgets import QComboBox
        except Exception:
            QComboBox = None
        if QComboBox is not None and isinstance(obj, QComboBox):
            try:
                for i in range(int(obj.count())):
                    t = obj.itemText(i)
                    if isinstance(t, str) and t:
                        obj.setItemText(i, tr_lit(t, lang=lang))
            except Exception:
                pass

        try:
            from PyQt6.QtWidgets import QTabWidget
        except Exception:
            QTabWidget = None
        if QTabWidget is not None and isinstance(obj, QTabWidget):
            try:
                for i in range(int(obj.count())):
                    t = obj.tabText(i)
                    if isinstance(t, str) and t:
                        obj.setTabText(i, tr_lit(t, lang=lang))
            except Exception:
                pass

    try:
        _apply(root)
        for child in root.findChildren(QObject):
            _apply(child)
    except Exception:
        return


def get_colorblind_mode_from_disk(default: str = "default") -> str:
    data = read_app_settings()
    mode = str(data.get("colorblind_mode", default) or default).strip().lower()
    return mode or default


def set_label_image_from_path(label: QLabel, image_path: str) -> None:
    """Load an image file as the label source, then render with current mode."""
    image_path = str(image_path or "").strip()
    if not image_path:
        return
    img = QImage(image_path)
    if img.isNull():
        return
    _set_label_source_image(label, img)
    refresh_label_pixmap_for_colorblind_mode(label)


def refresh_label_pixmap_for_colorblind_mode(label: QLabel) -> None:
    """Re-render the label's pixmap from its stored source image.

    Uses caching and a background worker to avoid UI freezes on large images.
    """
    source = _get_label_source_image(label)
    if source is None:
        return

    mode = get_colorblind_mode_from_disk("default")
    _set_attr(label, "_zzz_cvd_desired_mode", mode)

    cache = _get_attr(label, "_zzz_cvd_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        _set_attr(label, "_zzz_cvd_cache", cache)

    cached = cache.get(mode)
    if isinstance(cached, QPixmap):
        try:
            label.setPixmap(cached)
        except Exception:
            pass
        return

    # Default mode is fast; do it inline and cache.
    if mode == "default":
        try:
            pm = QPixmap.fromImage(source)
            cache[mode] = pm
            label.setPixmap(pm)
        except Exception:
            pass
        return

    # Debounce expensive processing so rapid switching doesn't spawn work.
    timer = _get_attr(label, "_zzz_cvd_timer", None)
    if timer is None:
        timer = QTimer(label)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: _start_colorblind_render(label))
        _set_attr(label, "_zzz_cvd_timer", timer)
    try:
        timer.start(40)
    except Exception:
        _start_colorblind_render(label)


def _start_colorblind_render(label: QLabel) -> None:
    source = _get_label_source_image(label)
    if source is None:
        return

    mode = str(_get_attr(label, "_zzz_cvd_desired_mode", "default") or "default").strip().lower()
    if mode == "default":
        # Hand back to the normal path.
        refresh_label_pixmap_for_colorblind_mode(label)
        return

    cache = _get_attr(label, "_zzz_cvd_cache", None)
    if isinstance(cache, dict):
        cached = cache.get(mode)
        if isinstance(cached, QPixmap):
            try:
                label.setPixmap(cached)
            except Exception:
                pass
            return

    # Only one render in-flight at a time per label.
    thread = _get_attr(label, "_zzz_cvd_thread", None)
    if isinstance(thread, QThread) and thread.isRunning():
        return

    # Copy source so the worker isn't affected by later mutations.
    src_copy = source.copy()

    worker = _CvdWorker(src_copy, mode)
    thread = QThread(label)
    worker.moveToThread(thread)

    def _cleanup() -> None:
        try:
            thread.quit()
            thread.wait(250)
        except Exception:
            pass
        try:
            worker.deleteLater()
        except Exception:
            pass
        try:
            thread.deleteLater()
        except Exception:
            pass
        _set_attr(label, "_zzz_cvd_thread", None)
        _set_attr(label, "_zzz_cvd_worker", None)

    def _on_done(out_img: QImage) -> None:
        try:
            desired = str(_get_attr(label, "_zzz_cvd_desired_mode", "default") or "default").strip().lower()
        except Exception:
            desired = "default"

        try:
            cache2 = _get_attr(label, "_zzz_cvd_cache", None)
            if not isinstance(cache2, dict):
                cache2 = {}
                _set_attr(label, "_zzz_cvd_cache", cache2)
            pm = QPixmap.fromImage(out_img)
            cache2[mode] = pm

            # Only apply if still desired; otherwise just cache.
            if desired == mode:
                label.setPixmap(pm)
        except Exception:
            pass
        finally:
            _cleanup()
            # If the user switched mode during processing, render the latest.
            if desired != mode:
                refresh_label_pixmap_for_colorblind_mode(label)

    thread.started.connect(worker.run)
    worker.finished.connect(_on_done)
    thread.finished.connect(_cleanup)

    _set_attr(label, "_zzz_cvd_thread", thread)
    _set_attr(label, "_zzz_cvd_worker", worker)
    thread.start()


def apply_colorblind_mode_to_qimage(image: QImage, mode: str) -> QImage:
    """Return a transformed copy of `image` according to the given mode.

    Modes match the UI combo values:
    - default
    - protanopia
    - deuteranopia
    - tritanopia
    - achromatopsia
    """
    mode = str(mode or "default").strip().lower() or "default"
    if mode == "default":
        return image

    # Work in ARGB32 for predictable channel layout.
    img = image.convertToFormat(QImage.Format.Format_ARGB32)
    w = img.width()
    h = img.height()

    # Choose matrix in linear RGB space.
    m = _CVD_MATRICES_LINEAR.get(mode)
    if m is None:
        return img

    out = QImage(w, h, QImage.Format.Format_ARGB32)

    for y in range(h):
        for x in range(w):
            px = img.pixel(x, y)
            a = (px >> 24) & 0xFF
            r = (px >> 16) & 0xFF
            g = (px >> 8) & 0xFF
            b = px & 0xFF

            # Premultiply not used; keep alpha as-is.
            lr = _srgb8_to_linear01(r)
            lg = _srgb8_to_linear01(g)
            lb = _srgb8_to_linear01(b)

            rr = m[0][0] * lr + m[0][1] * lg + m[0][2] * lb
            gg = m[1][0] * lr + m[1][1] * lg + m[1][2] * lb
            bb = m[2][0] * lr + m[2][1] * lg + m[2][2] * lb

            rr8 = _linear01_to_srgb8(rr)
            gg8 = _linear01_to_srgb8(gg)
            bb8 = _linear01_to_srgb8(bb)

            out.setPixel(x, y, (a << 24) | (rr8 << 16) | (gg8 << 8) | bb8)

    return out


def _get_label_source_image(label: QLabel) -> Optional[QImage]:
    try:
        v = label.property(_LABEL_SOURCE_IMAGE_PROP)
        return v if isinstance(v, QImage) else None
    except Exception:
        return None


def _set_label_source_image(label: QLabel, image: QImage) -> None:
    try:
        label.setProperty(_LABEL_SOURCE_IMAGE_PROP, image)
    except Exception:
        return

    # New source image invalidates cached renders.
    _set_attr(label, "_zzz_cvd_cache", {})


def _srgb8_to_linear01(v: int) -> float:
    c = max(0.0, min(1.0, float(v) / 255.0))
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear01_to_srgb8(v: float) -> int:
    c = max(0.0, min(1.0, float(v)))
    if c <= 0.0031308:
        s = 12.92 * c
    else:
        s = 1.055 * (c ** (1.0 / 2.4)) - 0.055
    return int(max(0, min(255, round(s * 255.0))))


def _mat_mul_3x3(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [
        [
            a[0][0] * b[0][0] + a[0][1] * b[1][0] + a[0][2] * b[2][0],
            a[0][0] * b[0][1] + a[0][1] * b[1][1] + a[0][2] * b[2][1],
            a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2] * b[2][2],
        ],
        [
            a[1][0] * b[0][0] + a[1][1] * b[1][0] + a[1][2] * b[2][0],
            a[1][0] * b[0][1] + a[1][1] * b[1][1] + a[1][2] * b[2][1],
            a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2] * b[2][2],
        ],
        [
            a[2][0] * b[0][0] + a[2][1] * b[1][0] + a[2][2] * b[2][0],
            a[2][0] * b[0][1] + a[2][1] * b[1][1] + a[2][2] * b[2][1],
            a[2][0] * b[0][2] + a[2][1] * b[1][2] + a[2][2] * b[2][2],
        ],
    ]


# Linear RGB <-> LMS (Hunt-Pointer-Estevez) matrices + deficiency simulation matrices.
# Values are from ixora.io's "Color Blindness Simulation Research".
_T = [
    [0.31399022, 0.15537241, 0.01775239],
    [0.63951294, 0.75789446, 0.10944209],
    [0.04649755, 0.08670142, 0.87256922],
]

_T_INV = [
    [5.47221206, -1.1252419, 0.02980165],
    [-4.6419601, 2.29317094, -0.19318073],
    [0.16963708, -0.1678952, 1.16364789],
]

_S_PROTANOPIA = [
    [0.0, 0.0, 0.0],
    [1.05118294, 1.0, 0.0],
    [-0.05116099, 0.0, 1.0],
]

_S_DEUTERANOPIA = [
    [1.0, 0.9513092, 0.0],
    [0.0, 0.0, 0.0],
    [0.0, 0.04866992, 1.0],
]

_S_TRITANOPIA = [
    [1.0, 0.0, -0.86744736],
    [0.0, 1.0, 1.86727089],
    [0.0, 0.0, 0.0],
]


def _combine_deficiency(sim: list[list[float]]) -> list[list[float]]:
    # LinearRGB' = T^-1 * S * T * LinearRGB
    return _mat_mul_3x3(_T_INV, _mat_mul_3x3(sim, _T))


_M_PROT = _combine_deficiency(_S_PROTANOPIA)
_M_DEUT = _combine_deficiency(_S_DEUTERANOPIA)
_M_TRIT = _combine_deficiency(_S_TRITANOPIA)

# Achromatopsia (rod monochromacy) approximation as luminance.
_M_ACHROM = [
    [0.212656, 0.715158, 0.072186],
    [0.212656, 0.715158, 0.072186],
    [0.212656, 0.715158, 0.072186],
]

_CVD_MATRICES_LINEAR = {
    "protanopia": _M_PROT,
    "deuteranopia": _M_DEUT,
    "tritanopia": _M_TRIT,
    "achromatopsia": _M_ACHROM,
}
