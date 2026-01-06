"""
Image Editor Dialog with positioning tools.
"""
from __future__ import annotations

import os
from typing import Any
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFrame, QGraphicsDropShadowEffect, 
                             QMessageBox, QApplication, QSlider, QFileDialog,
                             QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QProgressDialog)
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter, QPen
from PyQt6.QtCore import Qt, QRectF, QUrl, pyqtSignal, QTimer
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from utils import UI_THEME
from utils import (
    ART_EXTS,
    is_video_path,
)


def _screen_size() -> tuple[int, int]:
    try:
        geo = QApplication.primaryScreen().geometry()
        w = int(geo.width())
        h = int(geo.height())
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None


@dataclass
class _Layer:
    item: QGraphicsPixmapItem
    source_path: str
    is_video: bool
    player: Optional[QMediaPlayer] = None
    sink: Optional[QVideoSink] = None
    audio: Optional[QAudioOutput] = None
    pending_center: Optional[tuple[float, float]] = None


class ImageCanvas(QGraphicsView):
    """Custom canvas with centered guides and draggable image."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # Canvas settings
        self.setStyleSheet(
            "QGraphicsView { background-color: "
            + UI_THEME["surface2"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 12px; }"
        )
        try:
            self.setBackgroundBrush(QColor(0, 0, 0, 0))
        except Exception:
            pass
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.show_guides = True
        
        # Canvas size (1920x1080 for crosshair preview)
        self.canvas_width = 1920
        self.canvas_height = 1080
        self.setSceneRect(0, 0, self.canvas_width, self.canvas_height)

        # Let the canvas expand to fill the dialog; we scale to fit on resize.
        self.setMinimumSize(720, 405)
        self._fit_scene()

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._fit_scene()

    def _fit_scene(self) -> None:
        try:
            self.resetTransform()
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        except Exception:
            pass
        
    def drawBackground(self, painter, rect):
        """Draw background with center guides."""
        super().drawBackground(painter, rect)

        if not bool(getattr(self, "show_guides", True)):
            return
        
        # Draw center lines
        painter.setPen(QPen(QColor(UI_THEME["muted"]), 2, Qt.PenStyle.DashLine))
        
        # Vertical center line
        center_x = self.canvas_width / 2
        painter.drawLine(int(center_x), 0, int(center_x), self.canvas_height)
        
        # Horizontal center line
        center_y = self.canvas_height / 2
        painter.drawLine(0, int(center_y), self.canvas_width, int(center_y))
        
        # Draw center crosshair
        painter.setPen(QPen(QColor(UI_THEME["accent"]), 1))
        crosshair_size = 20
        painter.drawLine(int(center_x - crosshair_size), int(center_y), 
                        int(center_x + crosshair_size), int(center_y))
        painter.drawLine(int(center_x), int(center_y - crosshair_size), 
                        int(center_x), int(center_y + crosshair_size))
    
    def add_layer_pixmap(self, pixmap: QPixmap) -> QGraphicsPixmapItem:
        item = QGraphicsPixmapItem(pixmap)
        item.setFlags(
            QGraphicsPixmapItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsPixmapItem.GraphicsItemFlag.ItemIsSelectable
        )
        try:
            item.setTransformOriginPoint(pixmap.width() / 2, pixmap.height() / 2)
        except Exception:
            pass

        center_x = self.canvas_width / 2 - pixmap.width() / 2
        center_y = self.canvas_height / 2 - pixmap.height() / 2
        item.setPos(center_x, center_y)

        self.scene.addItem(item)
        return item

    def render_final_pixmap(self, *, include_guides: bool = False) -> QPixmap:
        prev_guides = bool(getattr(self, "show_guides", True))
        selected = []
        try:
            # Important: QGraphicsScene renders selection highlights (the dashed
            # outline) into the output. Clear selection while exporting so the
            # UI-only outline is never baked into saved PNG/MP4 frames.
            try:
                selected = list(self.scene.selectedItems())
                if selected:
                    self.scene.clearSelection()
            except Exception:
                selected = []

            self.show_guides = bool(include_guides)
            out = QPixmap(self.canvas_width, self.canvas_height)
            out.fill(Qt.GlobalColor.transparent)
            painter = QPainter(out)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            self.scene.render(
                painter,
                QRectF(0, 0, self.canvas_width, self.canvas_height),
                QRectF(0, 0, self.canvas_width, self.canvas_height),
            )
            painter.end()
            return out
        finally:
            self.show_guides = prev_guides
            try:
                # Restore selection after export.
                if selected:
                    for it in selected:
                        try:
                            it.setSelected(True)
                        except Exception:
                            pass
            except Exception:
                pass


class ImageEditorDialog(QWidget):
    """Dialog for editing images with positioning tools."""
    
    image_saved = pyqtSignal(str)  # emitted when a new composite is saved
    asset_renamed = pyqtSignal(str, str)  # old_path, new_path (source file)
    asset_deleted = pyqtSignal(str)  # selected element removed (source path)
    
    def __init__(self, image_path=None, parent=None, *, overlay_controller: Any = None, asset_key: Optional[str] = None):
        super().__init__(parent)
        self.image_path = None
        self.drag_position = None
        self._layers: list[_Layer] = []
        self._updating_controls = False

        # Optional: when opened from Art Manager, save only transform/opacity
        # to app_settings.json instead of exporting a new PNG/MP4.
        self._overlay_controller = overlay_controller
        self._asset_key = str(asset_key) if asset_key else None
        
        self.init_ui()
        
        if image_path and os.path.exists(image_path):
            # If this looks like a previously saved composite, load its project
            # so the user can keep editing layers (not a single fused MP4/PNG).
            project_path = self._project_path_for_output(str(image_path))
            if project_path and os.path.exists(project_path):
                self._load_project(project_path)
            else:
                self.add_art(image_path)

            # If this editor is opened for a single overlay element, apply its
            # saved transform/opacity for preview.
            try:
                self._apply_overlay_state_to_single_layer()
            except Exception:
                pass
    
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Main container with dark background and rounded edges
        main_frame = self._create_main_frame()
        
        # Layout
        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Title bar
        title_bar = self._create_title_bar()
        layout.addWidget(title_bar)
        
        # Content frame
        content_frame = self._create_content_frame()
        layout.addWidget(content_frame)
        
        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_frame)
        
        self.setFixedSize(900, 740)
        self.center_on_screen()
    
    def _create_main_frame(self):
        """Create the main frame with styling and shadow effect."""
        main_frame = QFrame(self)
        main_frame.setObjectName("mainFrame")
        main_frame.setStyleSheet(
            "QFrame#mainFrame { background-color: "
            + UI_THEME["bg"]
            + "; border-radius: 15px; border: 1px solid "
            + UI_THEME["border"]
            + "; }"
        )
        
        # Add shadow effect
        # shadow = QGraphicsDropShadowEffect(self)
        # shadow.setBlurRadius(30)
        # shadow.setColor(QColor(0, 0, 0, 180))
        # shadow.setOffset(0, 5)
        # main_frame.setGraphicsEffect(shadow)
        
        return main_frame
    
    def _create_title_bar(self):
        """Create the title bar with close button."""
        title_bar = QFrame()
        title_bar.setStyleSheet(
            "QFrame { background-color: "
            + UI_THEME["surface"]
            + "; border-top-left-radius: 15px; border-top-right-radius: 15px;"
            + " border-bottom: 1px solid "
            + UI_THEME["border"]
            + "; }"
        )
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(15, 8, 8, 8)
        title_bar_layout.setSpacing(5)
        
        # Title
        title = QLabel("✂️ Art Editor")
        title.setStyleSheet(
            "QLabel { color: "
            + UI_THEME["text"]
            + "; font-size: 14px; font-weight: 800; background: transparent; }"
        )
        title_bar_layout.addWidget(title)
        title_bar_layout.addStretch()
        
        # Close button
        close_btn = self._create_window_button("×", self.close)
        title_bar_layout.addWidget(close_btn)
        
        return title_bar
    
    def _create_window_button(self, text, callback):
        """Create a close button for the title bar."""
        btn = QPushButton(text)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background-color: "
            + UI_THEME["surface2"]
            + "; color: "
            + UI_THEME["text"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 6px; font-size: 20px; font-weight: 900; }"
            "QPushButton:hover { background-color: "
            + UI_THEME["danger"]
            + "; border: 1px solid "
            + UI_THEME["danger"]
            + "; }"
            "QPushButton:pressed { background-color: "
            + UI_THEME["surface"]
            + "; }"
        )
        btn.clicked.connect(callback)
        return btn
    
    def _create_content_frame(self):
        """Create the content frame with all controls."""
        content_frame = QFrame()
        content_frame.setStyleSheet("QFrame { background: transparent; }")
        content_layout = QVBoxLayout(content_frame)
        # Tighter layout so the canvas nearly reaches the edges.
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)
        
        # Canvas
        self.canvas = ImageCanvas()
        # The overlay system uses screen coordinates; keep preview mapping consistent.
        try:
            sw, sh = _screen_size()
            self.canvas.canvas_width = int(sw)
            self.canvas.canvas_height = int(sh)
            self.canvas.setSceneRect(0, 0, self.canvas.canvas_width, self.canvas.canvas_height)
            self.canvas._fit_scene()
        except Exception:
            pass
        try:
            self.canvas.scene.selectionChanged.connect(self._sync_controls_from_selection)
        except Exception:
            pass
        content_layout.addWidget(self.canvas)
        
        # Controls section
        controls_frame = self._create_controls_section()
        content_layout.addWidget(controls_frame)
        
        # Action buttons
        buttons_layout = self._create_action_buttons()
        content_layout.addLayout(buttons_layout)
        
        return content_frame
    
    def _create_controls_section(self):
        """Create the controls section with sliders."""
        controls_frame = QFrame()
        controls_frame.setStyleSheet(
            "QFrame { background-color: "
            + UI_THEME["surface"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 12px; padding: 10px; }"
        )
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setSpacing(10)
        
        # Zoom control
        zoom_layout = QHBoxLayout()
        zoom_label = QLabel("Zoom:")
        zoom_label.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 12px;")
        zoom_layout.addWidget(zoom_label)
        
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(10)
        self.zoom_slider.setMaximum(1000)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedHeight(16)
        self.zoom_slider.setStyleSheet(self._get_slider_style())
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        zoom_layout.addWidget(self.zoom_slider)
        
        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setStyleSheet(
            "color: " + UI_THEME["text"] + "; font-size: 12px; min-width: 45px;"
        )
        zoom_layout.addWidget(self.zoom_value_label)
        
        controls_layout.addLayout(zoom_layout)
        
        # Rotation control
        rotation_layout = QHBoxLayout()
        rotation_label = QLabel("Rotation:")
        rotation_label.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 12px;")
        rotation_layout.addWidget(rotation_label)
        
        self.rotation_slider = QSlider(Qt.Orientation.Horizontal)
        self.rotation_slider.setMinimum(0)
        self.rotation_slider.setMaximum(360)
        self.rotation_slider.setValue(0)
        self.rotation_slider.setFixedHeight(16)
        self.rotation_slider.setStyleSheet(self._get_slider_style())
        self.rotation_slider.valueChanged.connect(self.on_rotation_changed)
        rotation_layout.addWidget(self.rotation_slider)
        
        self.rotation_value_label = QLabel("0°")
        self.rotation_value_label.setStyleSheet(
            "color: " + UI_THEME["text"] + "; font-size: 12px; min-width: 45px;"
        )
        rotation_layout.addWidget(self.rotation_value_label)
        
        controls_layout.addLayout(rotation_layout)

        # Opacity control
        opacity_layout = QHBoxLayout()
        opacity_label = QLabel("Opacity:")
        opacity_label.setStyleSheet("color: " + UI_THEME["muted"] + "; font-size: 12px;")
        opacity_layout.addWidget(opacity_label)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setFixedHeight(16)
        self.opacity_slider.setStyleSheet(self._get_slider_style())
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.opacity_slider)

        self.opacity_value_label = QLabel("100%")
        self.opacity_value_label.setStyleSheet(
            "color: " + UI_THEME["text"] + "; font-size: 12px; min-width: 45px;"
        )
        opacity_layout.addWidget(self.opacity_value_label)

        controls_layout.addLayout(opacity_layout)
        
        return controls_frame
    
    def _get_slider_style(self):
        """Get slider stylesheet."""
        return (
            "QSlider::groove:horizontal { border: none; height: 6px; background: "
            + UI_THEME["surface2"]
            + "; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: "
            + UI_THEME["accent"]
            + "; border-radius: 3px; }"
            "QSlider::handle:horizontal { background: "
            + UI_THEME["accent"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; width: 16px; margin: -5px 0; border-radius: 8px; }"
            "QSlider::handle:horizontal:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
        )
    
    def _create_action_buttons(self):
        """Create action buttons layout."""
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        # Load art button
        load_btn = self._create_button("📁 Load Art", role="neutral")
        load_btn.clicked.connect(self.load_art_dialog)
        buttons_layout.addWidget(load_btn)

        # Rename button
        rename_btn = self._create_button("✏️ Rename", role="neutral")
        rename_btn.clicked.connect(self.rename_asset)
        buttons_layout.addWidget(rename_btn)

        # Delete button
        delete_btn = self._create_button("🗑️ Delete", role="danger")
        delete_btn.clicked.connect(self.delete_asset)
        buttons_layout.addWidget(delete_btn)
        
        # Reset button
        reset_btn = self._create_button("🔄 Reset", role="neutral")
        reset_btn.clicked.connect(self.reset_image)
        buttons_layout.addWidget(reset_btn)
        
        # Save button
        save_btn = self._create_button("💾 Save", role="primary")
        save_btn.clicked.connect(self.save_current)
        buttons_layout.addWidget(save_btn)
        
        return buttons_layout
    
    def _create_button(self, text: str, role: str = "neutral"):
        """Create a themed button."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        if role == "primary":
            bg = UI_THEME["accent"]
            fg = UI_THEME["bg"]
            border = UI_THEME["accent"]
        elif role == "danger":
            bg = UI_THEME["danger"]
            fg = UI_THEME["text"]
            border = UI_THEME["danger"]
        else:
            bg = UI_THEME["surface2"]
            fg = UI_THEME["text"]
            border = UI_THEME["border"]

        btn.setStyleSheet(
            "QPushButton { background-color: "
            + bg
            + "; color: "
            + fg
            + "; border: 1px solid "
            + border
            + "; border-radius: 10px; padding: 8px 12px; font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { border: 1px solid "
            + UI_THEME["border_strong"]
            + "; }"
            "QPushButton:pressed { background-color: "
            + UI_THEME["surface"]
            + "; }"
            "QPushButton:disabled { background-color: rgba(120,120,140,60); color: rgba(255,255,255,120); border: 1px solid rgba(230,225,255,30); }"
        )
        return btn
    
    def _adjust_color_brightness(self, hex_color, factor):
        """Adjust color brightness by a factor."""
        color = QColor(hex_color)
        h, s, v, a = color.getHsv()
        v = min(255, int(v * factor))
        color.setHsv(h, s, v, a)
        return color.name()
    
    def center_on_screen(self):
        """Center the dialog on the screen."""
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
    
    def load_art_dialog(self):
        """Import one or more art files into display_images and add them as layers."""

        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter(
            "Art Files (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.mp4 *.avi *.mov *.webm *.mkv *.m4v)"
        )

        if not file_dialog.exec():
            return

        files = file_dialog.selectedFiles() or []
        if not files:
            return

        imported = self._import_art_files(files)
        for p in imported:
            self.add_art(p)

    def add_art(self, file_path: str) -> None:
        file_path = str(file_path or "").strip()
        if not file_path or not os.path.exists(file_path):
            return
        if is_video_path(file_path):
            self._add_video_layer(file_path)
        else:
            self._add_image_layer(file_path)

        # Select the newest layer.
        try:
            if self._layers:
                self.canvas.scene.clearSelection()
                self._layers[-1].item.setSelected(True)
        except Exception:
            pass
    
    def _add_image_layer(self, file_path: str) -> None:
        try:
            pm = QPixmap(file_path)
            if pm.isNull():
                raise ValueError("Failed to load image")
            item = self.canvas.add_layer_pixmap(pm)
            self._layers.append(_Layer(item=item, source_path=file_path, is_video=False))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to add image: {str(e)}")

    def _add_video_layer(self, file_path: str) -> None:
        try:
            # Placeholder pixmap until the first frame arrives.
            pm = QPixmap(4, 4)
            pm.fill(Qt.GlobalColor.transparent)
            item = self.canvas.add_layer_pixmap(pm)

            audio = QAudioOutput()
            try:
                audio.setVolume(0.0)
            except Exception:
                pass
            sink = QVideoSink()
            player = QMediaPlayer()
            player.setAudioOutput(audio)
            player.setVideoOutput(sink)

            layer = _Layer(item=item, source_path=file_path, is_video=True, player=player, sink=sink, audio=audio)
            self._layers.append(layer)

            def on_status(status) -> None:
                try:
                    if status == QMediaPlayer.MediaStatus.EndOfMedia and layer.player is not None:
                        layer.player.setPosition(0)
                        layer.player.play()
                except Exception:
                    pass

            def on_frame(frame) -> None:
                try:
                    img = frame.toImage()
                except Exception:
                    img = None
                if img is None or getattr(img, "isNull", lambda: True)():
                    return
                try:
                    pm2 = QPixmap.fromImage(img)
                    layer.item.setPixmap(pm2)
                    layer.item.setTransformOriginPoint(pm2.width() / 2, pm2.height() / 2)

                    # If we have a pending center (from project load), apply once
                    # now that we know the real frame size.
                    if layer.pending_center is not None:
                        try:
                            cx, cy = layer.pending_center
                            layer.item.setPos(float(cx) - pm2.width() / 2, float(cy) - pm2.height() / 2)
                        except Exception:
                            pass
                        layer.pending_center = None
                except Exception:
                    pass

            sink.videoFrameChanged.connect(on_frame)
            player.mediaStatusChanged.connect(on_status)

            player.setSource(QUrl.fromLocalFile(os.path.abspath(file_path)))
            player.play()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to add video: {str(e)}")
    
    def reset_image(self):
        """Reset selected layers (or all layers if none selected)."""
        items = list(self.canvas.scene.selectedItems())
        targets = set(items) if items else set(l.item for l in self._layers)
        if not targets:
            return

        cx = self.canvas.canvas_width / 2
        cy = self.canvas.canvas_height / 2
        for it in targets:
            try:
                it.setScale(1.0)
                it.setRotation(0.0)
                it.setOpacity(1.0)
                pm = it.pixmap()
                w = pm.width() if pm is not None else 0
                h = pm.height() if pm is not None else 0
                it.setPos(cx - w / 2, cy - h / 2)
            except Exception:
                pass

        self._sync_controls_from_selection()
    
    def save_current(self):
        """Export a new composite file.

        - If only images: saves PNG.
        - If any videos: saves MP4.
        """

        if not self._layers:
            QMessageBox.information(self, "No Content", "Add images/videos first.")
            return

        # Single element editing mode (from Art Manager): persist transform instead
        # of exporting, to avoid black background MP4 canvases.
        if self._overlay_controller is not None and self._asset_key and len(self._layers) == 1:
            try:
                layer = self._layers[0]
                it = layer.item
                pos = it.pos()
                zoom = float(it.scale() or 1.0)
                rot = float(it.rotation() or 0.0)
                op = float(it.opacity() if it.opacity() is not None else 1.0)

                # Coordinates are already in screen space because we set the
                # editor canvas to the primary screen size.
                x = float(pos.x())
                y = float(pos.y())

                try:
                    self._overlay_controller.set_transform(self._asset_key, {"x": x, "y": y, "zoom": zoom, "rotation": rot})
                except Exception:
                    pass
                try:
                    self._overlay_controller.set_opacity(self._asset_key, op)
                except Exception:
                    pass

                QMessageBox.information(self, "Saved", "Saved position for this element.")
                try:
                    self.close()
                except Exception:
                    pass
                return
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save position: {e}")
                return

        has_video = any(l.is_video for l in self._layers)
        if has_video and (cv2 is None or np is None):
            QMessageBox.warning(
                self,
                "Missing Dependency",
                "MP4 export requires opencv-python (and numpy). Install it and restart the app."
            )
            return

        if has_video:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Video",
                "display_images/edited_composite.mp4",
                "MP4 Video (*.mp4)",
            )
        else:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Image",
                "display_images/edited_composite.png",
                "PNG Image (*.png)",
            )

        if not file_path:
            return

        try:
            if has_video:
                self._start_export_mp4(file_path)
            else:
                pm = self.canvas.render_final_pixmap(include_guides=False)
                pm.save(file_path, "PNG")

            # Persist a sidecar project so reopening stays editable.
            try:
                project_path = self._project_path_for_output(file_path)
                if project_path:
                    self._save_project(project_path, output_path=file_path)
            except Exception:
                pass

            if not has_video:
                QMessageBox.information(self, "Saved", f"Saved to:\n{file_path}")
                self.image_saved.emit(file_path)
                try:
                    self.close()
                except Exception:
                    pass
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to save: {str(e)}")

    def _apply_overlay_state_to_single_layer(self) -> None:
        if self._overlay_controller is None or not self._asset_key:
            return
        if len(self._layers) != 1:
            return
        it = self._layers[0].item

        try:
            t = self._overlay_controller.get_transform(self._asset_key)
        except Exception:
            t = {}

        try:
            x = float(t.get("x", it.pos().x()) or 0.0)
        except Exception:
            x = float(it.pos().x())
        try:
            y = float(t.get("y", it.pos().y()) or 0.0)
        except Exception:
            y = float(it.pos().y())
        try:
            zoom = float(t.get("zoom", it.scale()) or 1.0)
        except Exception:
            zoom = float(it.scale() or 1.0)
        try:
            rot = float(t.get("rotation", it.rotation()) or 0.0)
        except Exception:
            rot = float(it.rotation() or 0.0)

        # Opacity is stored separately in overlay settings.
        try:
            st = getattr(self._overlay_controller, "_get_state", None)
            if callable(st):
                op = float(st(self._asset_key).opacity)
            else:
                op = 1.0
        except Exception:
            op = 1.0

        try:
            it.setPos(float(x), float(y))
        except Exception:
            pass
        try:
            if zoom > 0:
                it.setScale(float(zoom))
        except Exception:
            pass
        try:
            it.setRotation(float(rot))
        except Exception:
            pass
        try:
            it.setOpacity(max(0.0, min(1.0, float(op))))
        except Exception:
            pass

        try:
            self._sync_controls_from_selection()
        except Exception:
            pass

    def _start_export_mp4(self, output_path: str) -> None:
        # Use OpenCV to step frames for each source video; render the Qt scene
        # to a frame image so rotations/scales are applied correctly.
        assert cv2 is not None and np is not None

        video_layers = [l for l in self._layers if l.is_video]
        # Stop Qt playback to avoid Windows file locks and racing updates.
        for l in video_layers:
            try:
                self._stop_layer_video(l)
            except Exception:
                pass

        captures = []
        for l in video_layers:
            cap = cv2.VideoCapture(l.source_path)
            captures.append(cap)

        def _cap_fps(cap) -> float:
            try:
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
                return fps if fps > 0 else 0.0
            except Exception:
                return 0.0

        def _cap_frames(cap) -> int:
            try:
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                return n if n > 0 else 0
            except Exception:
                return 0

        out_fps = 0.0
        out_frames = 0
        for cap in captures:
            out_fps = max(out_fps, _cap_fps(cap))
            out_frames = max(out_frames, _cap_frames(cap))

        if out_fps <= 0:
            out_fps = 30.0
        if out_frames <= 0:
            out_frames = int(out_fps * 5)

        w = int(self.canvas.canvas_width)
        h = int(self.canvas.canvas_height)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, float(out_fps), (w, h))

        self._export_state = {
            'captures': captures,
            'writer': writer,
            'video_layers': video_layers,
            'out_frames': out_frames,
            'current_frame': 0,
            'output_path': output_path
        }

        self._progress = QProgressDialog("Exporting video...", "Cancel", 0, out_frames, self)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.canceled.connect(self._cancel_export)
        self._progress.show()

        self._export_timer = QTimer(self)
        self._export_timer.timeout.connect(self._process_next_frame)
        self._export_timer.start(0)

    def _process_next_frame(self) -> None:
        # Export can be canceled/finished and cleaned up while the timer still
        # has a queued timeout. Bail out safely if state is already gone.
        if not hasattr(self, "_export_state") or not hasattr(self, "_progress"):
            return
        if self._progress.wasCanceled():
            self._finish_export(canceled=True)
            return

        state = self._export_state
        i = state['current_frame']
        if i >= state['out_frames']:
            self._finish_export()
            return

        # Update each video layer pixmap.
        for layer, cap in zip(state['video_layers'], state['captures']):
            ok, frame = cap.read()
            if not ok or frame is None:
                try:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                except Exception:
                    pass
                ok, frame = cap.read()
            if not ok or frame is None:
                continue

            # OpenCV gives BGR.
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
                pm = QPixmap.fromImage(qimg)
                layer.item.setPixmap(pm)
                layer.item.setTransformOriginPoint(pm.width() / 2, pm.height() / 2)
            except Exception:
                pass

        # Render without guides.
        pm = self.canvas.render_final_pixmap(include_guides=False)
        img = pm.toImage().convertToFormat(QImage.Format.Format_RGB888)
        ptr = img.bits()
        ptr.setsize(img.height() * img.bytesPerLine())
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((img.height(), img.bytesPerLine() // 3, 3))
        arr = arr[:, : img.width(), :]
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        state['writer'].write(bgr)

        state['current_frame'] += 1
        self._progress.setValue(i + 1)

    def _cancel_export(self) -> None:
        self._finish_export(canceled=True)

    def _finish_export(self, canceled: bool = False) -> None:
        # Make this idempotent (can be called via timer + cancel + internal
        # finish conditions).
        if getattr(self, "_export_finishing", False):
            return
        state = getattr(self, "_export_state", None)
        if state is None:
            return

        self._export_finishing = True
        try:
            try:
                state['writer'].release()
            except Exception:
                pass
            for cap in state.get('captures', []):
                try:
                    cap.release()
                except Exception:
                    pass

            # Restart preview playback (best-effort).
            for l in state.get('video_layers', []):
                try:
                    self._restart_layer_video(l)
                except Exception:
                    pass

            try:
                self._progress.close()
            except Exception:
                pass

            if not canceled:
                # Save project
                try:
                    project_path = self._project_path_for_output(state['output_path'])
                    if project_path:
                        self._save_project(project_path, output_path=state['output_path'])
                except Exception:
                    pass

                try:
                    QMessageBox.information(self, "Saved", f"Saved to:\n{state['output_path']}")
                except Exception:
                    pass
                try:
                    self.image_saved.emit(state['output_path'])
                except Exception:
                    pass
                try:
                    self.close()
                except Exception:
                    pass
        finally:
            # Clean up
            try:
                if hasattr(self, '_export_timer'):
                    self._export_timer.stop()
                    del self._export_timer
            except Exception:
                pass
            try:
                if hasattr(self, '_export_state'):
                    del self._export_state
            except Exception:
                pass
            try:
                if hasattr(self, '_progress'):
                    del self._progress
            except Exception:
                pass
            self._export_finishing = False

    def _project_path_for_output(self, output_path: str) -> str:
        base, _ext = os.path.splitext(str(output_path))
        return base + ".zzc.json"

    def _save_project(self, project_path: str, *, output_path: Optional[str] = None) -> None:
        import json

        base_dir = os.path.dirname(os.path.abspath(project_path))
        layers_payload = []
        for z, layer in enumerate(self._layers):
            try:
                pm = layer.item.pixmap()
                w = pm.width() if pm is not None else 0
                h = pm.height() if pm is not None else 0
                pos = layer.item.pos()
                cx = float(pos.x()) + (w / 2.0)
                cy = float(pos.y()) + (h / 2.0)
            except Exception:
                cx, cy = 0.0, 0.0

            try:
                rel = os.path.relpath(os.path.abspath(layer.source_path), base_dir)
            except Exception:
                rel = layer.source_path

            layers_payload.append(
                {
                    "path": rel.replace("\\", "/"),
                    "is_video": bool(layer.is_video),
                    "center": [cx, cy],
                    "scale": float(getattr(layer.item, "scale", lambda: 1.0)()),
                    "rotation": float(getattr(layer.item, "rotation", lambda: 0.0)()),
                    "opacity": float(getattr(layer.item, "opacity", lambda: 1.0)()),
                    "z": float(getattr(layer.item, "zValue", lambda: float(z))()),
                }
            )

        payload = {
            "version": 1,
            "canvas": {"width": int(self.canvas.canvas_width), "height": int(self.canvas.canvas_height)},
            "output": os.path.basename(output_path) if output_path else None,
            "layers": layers_payload,
        }

        with open(project_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _load_project(self, project_path: str) -> None:
        import json

        # Clear existing.
        try:
            self.canvas.scene.clear()
        except Exception:
            pass
        for l in list(self._layers):
            if l.is_video:
                try:
                    self._stop_layer_video(l)
                except Exception:
                    pass
        self._layers = []

        base_dir = os.path.dirname(os.path.abspath(project_path))
        try:
            with open(project_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Project", f"Failed to load project: {str(e)}")
            return

        layers = data.get("layers") if isinstance(data, dict) else None
        if not isinstance(layers, list):
            return

        # Load in z-order.
        def _z(v):
            try:
                return float(v.get("z", 0.0))
            except Exception:
                return 0.0

        for entry in sorted([e for e in layers if isinstance(e, dict)], key=_z):
            rel = str(entry.get("path", "")).strip()
            if not rel:
                continue
            abs_path = os.path.abspath(os.path.join(base_dir, rel))
            if not os.path.exists(abs_path):
                continue

            is_vid = bool(entry.get("is_video", is_video_path(abs_path)))
            center = entry.get("center")
            try:
                cx, cy = float(center[0]), float(center[1])
            except Exception:
                cx, cy = self.canvas.canvas_width / 2.0, self.canvas.canvas_height / 2.0
            try:
                scale = float(entry.get("scale", 1.0))
            except Exception:
                scale = 1.0
            try:
                rot = float(entry.get("rotation", 0.0))
            except Exception:
                rot = 0.0
            try:
                opacity = float(entry.get("opacity", 1.0))
            except Exception:
                opacity = 1.0
            try:
                zval = float(entry.get("z", 0.0))
            except Exception:
                zval = 0.0

            if is_vid:
                # Create video layer; position will be applied once first frame arrives.
                before = len(self._layers)
                self._add_video_layer(abs_path)
                if len(self._layers) > before:
                    layer = self._layers[-1]
                    layer.pending_center = (cx, cy)
                    try:
                        layer.item.setScale(scale)
                        layer.item.setRotation(rot)
                        layer.item.setOpacity(opacity)
                        layer.item.setZValue(zval)
                    except Exception:
                        pass
            else:
                pm = QPixmap(abs_path)
                if pm.isNull():
                    continue
                item = self.canvas.add_layer_pixmap(pm)
                try:
                    item.setPos(cx - pm.width() / 2, cy - pm.height() / 2)
                    item.setScale(scale)
                    item.setRotation(rot)
                    item.setOpacity(opacity)
                    item.setZValue(zval)
                except Exception:
                    pass
                self._layers.append(_Layer(item=item, source_path=abs_path, is_video=False))

        # Select topmost for immediate editing.
        try:
            if self._layers:
                self.canvas.scene.clearSelection()
                self._layers[-1].item.setSelected(True)
        except Exception:
            pass
        self._sync_controls_from_selection()
    
    def on_zoom_changed(self, value):
        """Handle zoom slider change."""
        if self._updating_controls:
            return
        zoom = value / 100.0
        for it in self.canvas.scene.selectedItems():
            try:
                it.setScale(float(zoom))
            except Exception:
                pass
        self.zoom_value_label.setText(f"{value}%")
    
    def on_rotation_changed(self, value):
        """Handle rotation slider change."""
        if self._updating_controls:
            return
        for it in self.canvas.scene.selectedItems():
            try:
                it.setRotation(float(value))
            except Exception:
                pass
        self.rotation_value_label.setText(f"{value}°")

    def on_opacity_changed(self, value):
        """Handle opacity slider change."""
        if self._updating_controls:
            return
        op = max(0.0, min(1.0, float(value) / 100.0))
        for it in self.canvas.scene.selectedItems():
            try:
                it.setOpacity(op)
            except Exception:
                pass
        try:
            self.opacity_value_label.setText(f"{int(value)}%")
        except Exception:
            pass

    def rename_asset(self) -> None:
        layer = self._selected_layer()
        if layer is None or not layer.source_path or not os.path.exists(layer.source_path):
            QMessageBox.information(self, "No Selection", "Select an element to rename.")
            return

        # Stop that layer's video playback so Windows doesn't lock the file.
        if layer.is_video:
            self._stop_layer_video(layer)

        # Lazy import to keep the top imports stable.
        try:
            from PyQt6.QtWidgets import QInputDialog
        except Exception:
            QInputDialog = None
        if QInputDialog is None:
            return

        folder = os.path.dirname(layer.source_path)
        old_name = os.path.basename(layer.source_path)
        root, ext = os.path.splitext(old_name)

        # Let the user edit the full filename (without forcing extension), but
        # keep the old extension if they omit one.
        new_name, ok = QInputDialog.getText(self, "Rename", "New file name:", text=old_name)
        if not ok:
            return
        new_name = str(new_name or "").strip()
        if not new_name:
            return

        # Preserve extension if user didn't type it.
        if os.path.splitext(new_name)[1] == "":
            new_name = new_name + ext

        new_path = os.path.join(folder, new_name)
        if os.path.abspath(new_path) == os.path.abspath(layer.source_path):
            return
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Rename", "A file with that name already exists.")
            return

        old_path = layer.source_path
        try:
            os.rename(old_path, new_path)
        except Exception as e:
            QMessageBox.warning(self, "Rename", f"Failed to rename: {str(e)}")
            return

        layer.source_path = new_path
        self.asset_renamed.emit(old_path, new_path)

        # Restart playback if needed.
        if layer.is_video:
            self._restart_layer_video(layer)

    def delete_asset(self) -> None:
        selected = list(self.canvas.scene.selectedItems())
        if not selected:
            QMessageBox.information(self, "No Selection", "Select element(s) to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Remove Element",
            "Remove selected element(s) from the editor? (Files will NOT be deleted)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        removed_paths: list[str] = []
        for it in selected:
            layer = self._layer_for_item(it)
            if layer is None:
                try:
                    self.canvas.scene.removeItem(it)
                except Exception:
                    pass
                continue

            if layer.is_video:
                self._stop_layer_video(layer)
            try:
                self.canvas.scene.removeItem(layer.item)
            except Exception:
                pass
            removed_paths.append(layer.source_path)
            try:
                self._layers.remove(layer)
            except Exception:
                pass

        for p in removed_paths:
            try:
                self.asset_deleted.emit(p)
            except Exception:
                pass

        self._sync_controls_from_selection(force_defaults=(not bool(self._layers)))

    def _import_art_files(self, files: list[str]) -> list[str]:
        """Copy selected files into display_images and return destination paths."""
        out: list[str] = []
        try:
            dest_folder = os.path.abspath("display_images")
            os.makedirs(dest_folder, exist_ok=True)
        except Exception:
            dest_folder = os.path.abspath("display_images")

        for src in files:
            try:
                if not src:
                    continue
                src = os.path.abspath(str(src))
                if not os.path.exists(src):
                    continue

                # Only accept supported extensions.
                if not str(src).lower().endswith(ART_EXTS):
                    continue

                name = os.path.basename(src)
                dst = os.path.join(dest_folder, name)
                if os.path.exists(dst):
                    reply = QMessageBox.question(
                        self,
                        "File Exists",
                        f"{name} already exists in display_images. Overwrite?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        # Still allow loading the existing one.
                        out.append(dst)
                        continue

                import shutil
                shutil.copy2(src, dst)
                out.append(dst)
            except Exception:
                continue

        return out

    def _layer_for_item(self, it) -> Optional[_Layer]:
        for l in self._layers:
            if l.item is it:
                return l
        return None

    def _selected_layer(self) -> Optional[_Layer]:
        items = list(self.canvas.scene.selectedItems())
        if not items:
            return None
        # Prefer the last selected in Qt's ordering (top-most), but any is fine.
        return self._layer_for_item(items[-1])

    def _stop_layer_video(self, layer: _Layer) -> None:
        try:
            if layer.player is not None:
                layer.player.stop()
        except Exception:
            pass
        # Disconnecting is optional; on close the QObject tree is destroyed.
        layer.player = None
        layer.sink = None
        layer.audio = None

    def _restart_layer_video(self, layer: _Layer) -> None:
        # Easiest is to re-add it as a new layer; but we want to keep transforms.
        # So we create a new player/sink and keep the same item.
        try:
            audio = QAudioOutput()
            try:
                audio.setVolume(0.0)
            except Exception:
                pass
            sink = QVideoSink()
            player = QMediaPlayer()
            player.setAudioOutput(audio)
            player.setVideoOutput(sink)

            def on_status(status) -> None:
                try:
                    if status == QMediaPlayer.MediaStatus.EndOfMedia and player is not None:
                        player.setPosition(0)
                        player.play()
                except Exception:
                    pass

            def on_frame(frame) -> None:
                try:
                    img = frame.toImage()
                except Exception:
                    img = None
                if img is None or getattr(img, "isNull", lambda: True)():
                    return
                try:
                    pm2 = QPixmap.fromImage(img)
                    layer.item.setPixmap(pm2)
                    layer.item.setTransformOriginPoint(pm2.width() / 2, pm2.height() / 2)
                except Exception:
                    pass

            sink.videoFrameChanged.connect(on_frame)
            player.mediaStatusChanged.connect(on_status)
            player.setSource(QUrl.fromLocalFile(os.path.abspath(layer.source_path)))
            player.play()

            layer.player = player
            layer.sink = sink
            layer.audio = audio
        except Exception:
            pass

    def _sync_controls_from_selection(self, *, force_defaults: bool = False) -> None:
        if self._updating_controls:
            return
        self._updating_controls = True
        try:
            if force_defaults:
                self.zoom_slider.setValue(100)
                self.rotation_slider.setValue(0)
                try:
                    self.opacity_slider.setValue(100)
                    self.opacity_value_label.setText("100%")
                except Exception:
                    pass
                self.zoom_value_label.setText("100%")
                self.rotation_value_label.setText("0°")
                return

            items = list(self.canvas.scene.selectedItems())
            if not items:
                return
            it = items[-1]
            try:
                zv = int(round(float(it.scale()) * 100))
                zv = max(self.zoom_slider.minimum(), min(self.zoom_slider.maximum(), zv))
                self.zoom_slider.setValue(zv)
                self.zoom_value_label.setText(f"{zv}%")
            except Exception:
                pass
            try:
                rv = int(round(float(it.rotation())))
                rv = max(self.rotation_slider.minimum(), min(self.rotation_slider.maximum(), rv))
                self.rotation_slider.setValue(rv)
                self.rotation_value_label.setText(f"{rv}°")
            except Exception:
                pass

            try:
                ov = int(round(float(it.opacity()) * 100))
                ov = max(self.opacity_slider.minimum(), min(self.opacity_slider.maximum(), ov))
                self.opacity_slider.setValue(ov)
                self.opacity_value_label.setText(f"{ov}%")
            except Exception:
                pass
        finally:
            self._updating_controls = False

    def closeEvent(self, event):  # type: ignore[override]
        try:
            for l in list(self._layers):
                if l.is_video:
                    self._stop_layer_video(l)
        except Exception:
            pass
        return super().closeEvent(event)
    
    def mousePressEvent(self, event):
        """Handle mouse press events for dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move events for dragging."""
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
