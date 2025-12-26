"""Utility functions for the crosshair application."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal


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
