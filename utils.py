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

        rgba = img.convertToFormat(QImage.Format.Format_RGBA8888)
        # Work on a copy to avoid mutating any shared QImage memory the
        # caller might still be using elsewhere (in-place numpy views can
        # unexpectedly alter other components). This prevents accidental
        # transparency applied to unrelated UI images.
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

        # RGBA order.
        r = arr[:, :, 0]
        g = arr[:, :, 1]
        b = arr[:, :, 2]
        # Only key-out fully opaque pixels (avoid touching already-transparent
        # areas). This reduces accidental alpha changes for layered artwork.
        a = arr[:, :, 3]
        opaque = (a == 255)
        near_black = (r <= threshold) & (g <= threshold) & (b <= threshold)
        candidates = near_black & opaque

        # Require a majority of the 3x3 neighborhood to also be near-black
        # before treating the pixel as background. This avoids removing
        # small black details in artwork (like shading on clothing).
        try:
            if np.any(candidates):
                total = int(w) * int(h)
                # Minimum connected component area to consider background.
                min_area = max(500, int(total * 0.001))

                # Prefer OpenCV for efficient connected-component analysis if available.
                if cv2 is not None:
                    try:
                        comp = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), connectivity=8)
                        nlabels = int(comp[0])
                        labels = comp[1]
                        stats = comp[2]
                        # feather width in pixels for soft edges
                        feather_px = max(3, int(min(w, h) * 0.005))
                        for lbl in range(1, nlabels):
                            area = int(stats[lbl, cv2.CC_STAT_AREA])
                            if area >= min_area:
                                # Create mask for this component
                                comp_mask = (labels == lbl)
                                # distance transform requires 8-bit mask with foreground >0
                                mask8 = (comp_mask.astype(np.uint8) * 255)
                                try:
                                    # Use a blurred mask to create a soft/feathered alpha.
                                    k = max(1, int(feather_px) * 2 + 1)
                                    # Gaussian blur the 8-bit mask to produce soft edges
                                    blur = cv2.GaussianBlur(mask8, (k, k), 0)
                                    soft = blur.astype(np.float32) / 255.0
                                except Exception:
                                    # Fallback: treat whole component as hard-transparent
                                    arr[comp_mask, 3] = 0
                                    continue

                                # Apply softness only to candidate pixels inside this component
                                idx = comp_mask & candidates & (soft > 0)
                                if np.any(idx):
                                    orig = arr[idx, 3].astype(np.float32) / 255.0
                                    new_alpha = orig * (1.0 - soft[idx])
                                    arr[idx, 3] = (np.clip(new_alpha, 0.0, 1.0) * 255.0).astype(np.uint8)
                    except Exception:
                        # If OpenCV call fails, fall back to neighborhood rule below.
                        raise
                else:
                    # No OpenCV: use a stricter neighborhood rule (8/9 majority)
                    pad = np.pad(candidates.astype(np.uint8), ((1, 1), (1, 1)), mode="constant")
                    neigh = (
                        pad[:-2, :-2]
                        + pad[:-2, 1:-1]
                        + pad[:-2, 2:]
                        + pad[1:-1, :-2]
                        + pad[1:-1, 1:-1]
                        + pad[1:-1, 2:]
                        + pad[2:, :-2]
                        + pad[2:, 1:-1]
                        + pad[2:, 2:]
                    )
                    bg_mask = (neigh >= 8) & candidates
                    arr[bg_mask, 3] = 0
        except Exception:
            # Conservative fallback: only key pixels where the immediate
            # neighborhood is entirely near-black.
            pad = np.pad(candidates.astype(np.uint8), ((1, 1), (1, 1)), mode="constant")
            neigh = (
                pad[:-2, :-2]
                + pad[:-2, 1:-1]
                + pad[:-2, 2:]
                + pad[1:-1, :-2]
                + pad[1:-1, 1:-1]
                + pad[1:-1, 2:]
                + pad[2:, :-2]
                + pad[2:, 1:-1]
                + pad[2:, 2:]
            )
            bg_mask = (neigh >= 9) & candidates
            arr[bg_mask, 3] = 0
        return rgba
    except Exception:
        return img


def _get_project_root() -> Path:
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path(".")


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
        zoom = float(self._transform.get("zoom", 1.0) or 1.0)
        rotation = float(self._transform.get("rotation", 0.0) or 0.0)
        pos_x = float(self._transform.get("x", (self._canvas_w - img.width()) / 2.0) or 0.0)
        pos_y = float(self._transform.get("y", (self._canvas_h - img.height()) / 2.0) or 0.0)

        canvas = QImage(self._canvas_w, self._canvas_h, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        pm = QPixmap.fromImage(img)
        if zoom != 1.0:
            target_w = max(1, int(pm.width() * zoom))
            target_h = max(1, int(pm.height() * zoom))
            pm = pm.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        # Draw rotated about its center.
        painter.save()
        painter.translate(pos_x + pm.width() / 2.0, pos_y + pm.height() / 2.0)
        painter.rotate(rotation)
        painter.translate(-pm.width() / 2.0, -pm.height() / 2.0)
        painter.drawPixmap(0, 0, pm)
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


def set_label_art_from_path(label: QLabel, path: str) -> None:
    """Set the overlay label content from either an image or a video path."""
    path = str(path or "").strip()
    if not path:
        return

    _stop_label_video_if_any(label)

    if not is_video_path(path):
        set_label_image_from_path(label, path)
        return

    # Clear any stored image source so image-only operations don't interfere.
    try:
        _set_attr(label, _LABEL_SOURCE_IMAGE_PROP, None)
        _set_attr(label, "_zzz_cvd_cache", {})
    except Exception:
        pass

    # Videos: render frames into label pixmap (looping) and apply saved transform.
    transforms = load_art_transforms()
    key = _normalize_art_key(path)
    transform = transforms.get(key) if isinstance(transforms, dict) else None

    # If this video is a saved composite (has a sidecar project), treat near-black
    # pixels as transparent during playback.
    base, _ext = os.path.splitext(os.path.abspath(path))
    sidecar = base + ".zzc.json"
    key_black = os.path.exists(sidecar)

    player = _LabelVideoPlayer(
        label,
        path,
        canvas_size=(1920, 1080),
        transform=transform,
        key_black=key_black,
        key_threshold=12,
    )
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
