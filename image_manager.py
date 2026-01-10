"""
Image Manager Dialog for adding and managing crosshair images.
"""
import os
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QListWidget, QListWidgetItem, QFileDialog, 
                             QLabel, QFrame, QGraphicsDropShadowEffect, 
                             QMessageBox, QApplication, QInputDialog)
from PyQt6.QtGui import QPixmap, QColor, QIcon, QPainter, QPen
from PyQt6.QtCore import Qt, QSize, QUrl, QPoint
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
import json
from utils import UI_THEME, ART_EXTS, IMAGE_EXTS, is_video_path
from image_editor import ImageEditorDialog


def _read_hotkey_config() -> dict:
    try:
        with open("hotkey_config.json", "r", encoding="utf-8") as fh:
            raw = json.load(fh)
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


class ImageManagerDialog(QWidget):
    """Dialog for managing crosshair images."""
    
    def __init__(self, parent=None, images_folder="display_images", *, overlay_controller=None):
        super().__init__(parent)
        # Use absolute path to ensure we have proper path handling
        self.images_folder = os.path.abspath(images_folder)
        self.drag_position = None
        self.overlay_controller = overlay_controller
        self._updating_checks = False
        # Compositions / layer editor removed; this dialog manages assets only.
        self.image_editor = None
        self._edit_btn = None
        self._thumb_player = None
        self._thumb_sink = None
        self._thumb_audio = None
        self._thumb_queue = []  # list[tuple[QListWidgetItem,str]]
        self._thumb_current = None
        self._thumb_timer = None
        self.init_ui()
        self.load_images()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        # Enable drag context while the Art Manager is open.
        try:
            if self.overlay_controller is not None:
                cfg = _read_hotkey_config()
                hold = cfg.get("hold_to_drag", [])
                self.overlay_controller.set_hold_to_drag(hold)
                self.overlay_controller.set_drag_context(True, selected_key=self._current_selected_key())
        except Exception:
            pass

    def closeEvent(self, event):  # type: ignore[override]
        try:
            if self.overlay_controller is not None:
                self.overlay_controller.set_drag_context(False, selected_key=None)
        except Exception:
            pass
        try:
            self._stop_thumbnailer()
        except Exception:
            pass
        return super().closeEvent(event)
    
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
        
        self.setFixedSize(500, 600)
        self.center_on_screen()
    
    def _create_main_frame(self):
        """Create the main frame with styling and shadow effect."""
        main_frame = QFrame(self)
        main_frame.setObjectName("mainFrame")
        main_frame.setStyleSheet(
            "QFrame#mainFrame {"
            "background-color: "
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
        title = QLabel("🎨 Art Manager")
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
        content_layout.setContentsMargins(20, 15, 20, 20)
        
        # Info label
        info_label = QLabel("Manage your crosshair art (images + videos)")
        info_label.setStyleSheet(
            "QLabel { color: "
            + UI_THEME["muted"]
            + "; font-size: 12px; padding: 5px; background: transparent; }"
        )
        content_layout.addWidget(info_label)
        
        # Image list
        self.image_list = QListWidget()
        self.image_list.setStyleSheet(
            "QListWidget { background-color: "
            + UI_THEME["surface"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 10px; color: "
            + UI_THEME["text"]
            + "; padding: 6px; font-size: 13px; }"
            "QListWidget::item { padding: 8px; border-radius: 8px; margin: 2px; }"
            "QListWidget::item:selected { background-color: "
            + UI_THEME["accent"]
            + "; color: "
            + UI_THEME["bg"]
            + "; }"
            "QListWidget::item:hover { background-color: "
            + UI_THEME["surface2"]
            + "; }"
        )
        self.image_list.setIconSize(QSize(48, 48))
        self.image_list.itemChanged.connect(self._on_item_check_changed)
        self.image_list.currentItemChanged.connect(self._on_selection_changed)
        content_layout.addWidget(self.image_list)
        
        # Button container
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        add_btn = self._create_button("➕", role="neutral")
        add_btn.setToolTip("Add Art")
        add_btn.clicked.connect(self.add_image)
        button_layout.addWidget(add_btn)
        remove_btn = self._create_button("🗑️", role="danger")
        remove_btn.setToolTip("Remove")
        remove_btn.clicked.connect(self.remove_image)
        button_layout.addWidget(remove_btn)

        edit_btn = self._create_button("✏️", role="neutral")
        edit_btn.setToolTip("Edit selected")
        edit_btn.setEnabled(False)
        edit_btn.clicked.connect(self.edit_selected)
        self._edit_btn = edit_btn
        button_layout.addWidget(edit_btn)

        show_btn = self._create_button("👁", role="primary")
        show_btn.setCheckable(True)
        show_btn.setChecked(False)
        show_btn.setToolTip("Show/Hide marked")
        show_btn.clicked.connect(lambda: self._toggle_show_marked(show_btn.isChecked()))
        button_layout.addWidget(show_btn)

        combo_btn = self._create_button("💾", role="neutral")
        combo_btn.setToolTip("Save marked as combo")
        combo_btn.clicked.connect(self.save_marked_as_combo)
        button_layout.addWidget(combo_btn)
        content_layout.addLayout(button_layout)
        
        # Refresh button
        refresh_btn = self._create_button("🔄 Refresh List", role="primary")
        refresh_btn.clicked.connect(self.load_images)
        content_layout.addWidget(refresh_btn)
        
        # Info text
        info_text = QLabel("Supported formats: PNG, JPG, JPEG, WEBP, GIF, BMP, MP4, AVI, MOV, WEBM, MKV, M4V")
        info_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_text.setStyleSheet("""
            QLabel {
                color: rgba(200, 200, 200, 120);
                font-size: 10px;
                padding: 5px;
                background: transparent;
            }
        """)
        content_layout.addWidget(info_text)
        
        return content_frame
    
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
            + "; border-radius: 10px; padding: 12px 20px; font-size: 13px; font-weight: 700; }"
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
    
    def load_images(self):
        """Load and display art from the display_images folder."""
        self._updating_checks = True
        self.image_list.clear()
        
        # Ensure folder exists
        abs_folder_path = os.path.abspath(self.images_folder)
        if not os.path.exists(abs_folder_path):
            os.makedirs(abs_folder_path)
            return
        
        def _video_icon() -> QIcon:
            pm = QPixmap(48, 48)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(UI_THEME["border_strong"]), 2))
            p.drawRoundedRect(4, 8, 40, 30, 6, 6)
            p.setBrush(QColor(UI_THEME["accent"]))
            pts = [
                (20, 16),
                (20, 32),
                (34, 24),
            ]
            try:
                from PyQt6.QtCore import QPoint
                from PyQt6.QtGui import QPolygon
                poly = QPolygon([QPoint(x, y) for x, y in pts])
                p.drawPolygon(poly)
            except Exception:
                # Fallback triangle.
                p.drawPolygon(
                    QPoint(20, 16),
                    QPoint(20, 32),
                    QPoint(34, 24),
                )
            p.end()
            return QIcon(pm)

        vid_icon = _video_icon()

        # Stop any in-flight thumbnail generation.
        self._stop_thumbnailer()
        self._thumb_queue = []
        self._thumb_current = None

        def _key_for_path(p: str) -> str:
            try:
                root = os.path.dirname(os.path.abspath(__file__))
                return os.path.relpath(os.path.abspath(p), root).replace("\\", "/")
            except Exception:
                return os.path.abspath(p).replace("\\", "/")

        for filename in sorted(os.listdir(self.images_folder)):
            if not filename.lower().endswith(ART_EXTS):
                continue
            file_path = os.path.join(self.images_folder, filename)
            key = _key_for_path(file_path)
            item = QListWidgetItem(filename)

            # Checkbox enables/disables this file as a separate overlay element.
            try:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setData(Qt.ItemDataRole.UserRole + 1, os.path.abspath(file_path))
                enabled = False
                if self.overlay_controller is not None:
                    enabled = bool(self.overlay_controller.is_enabled(key))
                item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            except Exception:
                pass

            try:
                if filename.lower().endswith(IMAGE_EXTS):
                    pixmap = QPixmap(file_path)
                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(
                            48,
                            48,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        item.setIcon(QIcon(scaled_pixmap))
                else:
                    item.setIcon(vid_icon)
                    # Queue for async first-frame thumbnail extraction.
                    self._thumb_queue.append((item, file_path))
            except Exception:
                pass

            self.image_list.addItem(item)

            # Do not render overlays here; checkmarks are selection only.

        # Kick off thumbnail generation after list is populated.
        self._start_thumbnailer()

        self._updating_checks = False

        # Keep selection consistent and update drag target.
        try:
            if self.image_list.count() > 0 and self.image_list.currentRow() < 0:
                self.image_list.setCurrentRow(0)
        except Exception:
            pass
        try:
            if self.overlay_controller is not None:
                self.overlay_controller.set_selected_key(self._current_selected_key())
        except Exception:
            pass

        # Append saved combos (from app_settings.json) into the list so users
        # can see and delete combos from the Art Manager.
        try:
            data = self._read_app_settings()
            combos = data.get("art_combos")
            if isinstance(combos, list) and combos:
                for c in combos:
                    try:
                        if not isinstance(c, dict):
                            continue
                        name = str(c.get("name") or "").strip()
                        keys = c.get("keys")
                        if not name or not isinstance(keys, list):
                            continue
                        display_text = f"Combo: {name}"
                        item = QListWidgetItem(display_text)
                        # mark as combo type
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                        item.setData(Qt.ItemDataRole.UserRole, {"type": "combo", "name": name, "keys": [str(k) for k in keys]})
                        # Use same icon as video for visibility (simple choice)
                        try:
                            item.setIcon(vid_icon)
                        except Exception:
                            pass
                        self.image_list.addItem(item)
                    except Exception:
                        pass
        except Exception:
            pass

    def _start_thumbnailer(self) -> None:
        if not self._thumb_queue:
            return

        try:
            if self._thumb_timer is None:
                from PyQt6.QtCore import QTimer
                self._thumb_timer = QTimer(self)
                self._thumb_timer.setSingleShot(True)
                self._thumb_timer.timeout.connect(self._process_next_thumbnail)
            self._thumb_timer.start(10)
        except Exception:
            self._process_next_thumbnail()

    def _stop_thumbnailer(self) -> None:
        try:
            if self._thumb_timer is not None:
                self._thumb_timer.stop()
        except Exception:
            pass

        try:
            if self._thumb_sink is not None:
                try:
                    self._thumb_sink.videoFrameChanged.disconnect(self._on_thumb_frame)
                except Exception:
                    pass
            if self._thumb_player is not None:
                try:
                    self._thumb_player.mediaStatusChanged.disconnect(self._on_thumb_status)
                except Exception:
                    pass
                try:
                    self._thumb_player.stop()
                except Exception:
                    pass
        except Exception:
            pass

        self._thumb_player = None
        self._thumb_sink = None
        self._thumb_audio = None

    def _process_next_thumbnail(self) -> None:
        if not self._thumb_queue:
            self._thumb_current = None
            self._stop_thumbnailer()
            return

        item, file_path = self._thumb_queue.pop(0)
        self._thumb_current = (item, file_path)

        try:
            # Lazily create player/sink once.
            if self._thumb_audio is None:
                self._thumb_audio = QAudioOutput()
                try:
                    self._thumb_audio.setVolume(0.0)
                except Exception:
                    pass
            if self._thumb_sink is None:
                self._thumb_sink = QVideoSink()
            if self._thumb_player is None:
                self._thumb_player = QMediaPlayer()
                self._thumb_player.setAudioOutput(self._thumb_audio)
                self._thumb_player.setVideoOutput(self._thumb_sink)
                self._thumb_sink.videoFrameChanged.connect(self._on_thumb_frame)
                self._thumb_player.mediaStatusChanged.connect(self._on_thumb_status)

            self._thumb_player.stop()
            self._thumb_player.setSource(QUrl.fromLocalFile(os.path.abspath(file_path)))
            # Play briefly to force frame delivery; we stop on first frame.
            self._thumb_player.play()
        except Exception:
            self._thumb_current = None
            self._start_thumbnailer()

    def _on_thumb_status(self, status) -> None:
        # If media is invalid or already ended without a frame, advance.
        try:
            if status in (
                QMediaPlayer.MediaStatus.InvalidMedia,
                QMediaPlayer.MediaStatus.NoMedia,
            ):
                self._thumb_current = None
                self._start_thumbnailer()
        except Exception:
            pass

    def _on_thumb_frame(self, frame) -> None:
        cur = self._thumb_current
        if not cur:
            return

        item, _file_path = cur
        try:
            img = frame.toImage()
        except Exception:
            img = None
        if img is None or getattr(img, "isNull", lambda: True)():
            return

        try:
            pm = QPixmap.fromImage(img)
            pm = pm.scaled(
                48,
                48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            item.setIcon(QIcon(pm))
        except Exception:
            pass

        # Stop quickly and move on.
        try:
            if self._thumb_player is not None:
                self._thumb_player.stop()
        except Exception:
            pass

        self._thumb_current = None
        self._start_thumbnailer()
    
    def add_image(self):
        """Open file dialog to add a new image."""
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter("Art Files (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.mp4 *.avi *.mov *.webm *.mkv *.m4v)")
        
        if file_dialog.exec():
            files = file_dialog.selectedFiles()
            
            # Ensure folder exists
            if not os.path.exists(self.images_folder):
                os.makedirs(self.images_folder)
            
            for file_path in files:
                try:
                    filename = os.path.basename(file_path)
                    # Normalize the path to ensure it's correct
                    dest_path = os.path.normpath(os.path.join(self.images_folder, filename))
                    
                    # Ensure folder exists
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    
                    # Check if file already exists
                    if os.path.exists(dest_path):
                        reply = QMessageBox.question(
                            self, 
                            'File Exists',
                            f'{filename} already exists. Overwrite?',
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )
                        if reply == QMessageBox.StandardButton.No:
                            continue
                    
                    # Copy file with error handling
                    try:
                        shutil.copy2(file_path, dest_path)
                    except PermissionError:
                        # If permission error, try to fix by ensuring directory exists
                        os.makedirs(self.images_folder, exist_ok=True)
                        # Try again with normalized path
                        shutil.copy2(file_path, dest_path)
                    
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        'Error',
                        f'Failed to add {os.path.basename(file_path)}: {str(e)}'
                    )
            
            # Refresh list
            self.load_images()
            
            # No editor prompt; assets are immediately available in the folder.
    
    # Composition editor removed.
    
    def remove_image(self):
        """Remove the selected image."""
        current_item = self.image_list.currentItem()
        if not current_item:
            QMessageBox.information(
                self,
                'No Selection',
                'Please select an item to remove.'
            )
            return
        
        # Determine whether this is a regular asset or a combo entry.
        item_meta = current_item.data(Qt.ItemDataRole.UserRole)
        is_combo = isinstance(item_meta, dict) and item_meta.get("type") == "combo"
        filename = current_item.text()
        
        # Confirm deletion
        reply = QMessageBox.question(
            self,
            'Confirm Deletion',
            f'Are you sure you want to delete {filename}?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if is_combo:
                # Remove combo from app_settings.json
                try:
                    data = self._read_app_settings()
                    combos = data.get("art_combos")
                    if isinstance(combos, list):
                        new_combos = [c for c in combos if not (isinstance(c, dict) and str(c.get("name") or "") == item_meta.get("name"))]
                        data["art_combos"] = new_combos
                        self._write_app_settings(data)
                    self.load_images()
                except Exception as e:
                    QMessageBox.warning(self, 'Error', f'Failed to delete combo {filename}: {e}')
                return

            try:
                file_path = os.path.join(self.images_folder, filename)
                # Disable overlay before deleting the file.
                try:
                    if self.overlay_controller is not None:
                        root = os.path.dirname(os.path.abspath(__file__))
                        key = os.path.relpath(os.path.abspath(file_path), root).replace("\\", "/")
                        self.overlay_controller.enable(key, path=os.path.abspath(file_path), enabled=False)
                except Exception:
                    pass
                os.remove(file_path)
                self.load_images()
            except Exception as e:
                QMessageBox.warning(
                    self,
                    'Error',
                    f'Failed to delete {filename}: {str(e)}'
                )

    def _current_selected_key(self):
        try:
            it = self.image_list.currentItem()
            if it is None:
                return None
            key = it.data(Qt.ItemDataRole.UserRole)
            return str(key) if key else None
        except Exception:
            return None

    def _on_selection_changed(self, current, _prev):
        try:
            if self.overlay_controller is not None:
                self.overlay_controller.set_selected_key(self._current_selected_key())
        except Exception:
            pass
        try:
            if self._edit_btn is not None:
                # Disable edit for combo items (they are not file assets).
                editable = False
                if current is not None:
                    meta = current.data(Qt.ItemDataRole.UserRole)
                    if isinstance(meta, dict) and meta.get("type") == "combo":
                        editable = False
                    else:
                        # Require a backing path for editing.
                        p = current.data(Qt.ItemDataRole.UserRole + 1)
                        editable = bool(p)
                self._edit_btn.setEnabled(editable)
        except Exception:
            pass

    def edit_selected(self) -> None:
        it = self.image_list.currentItem()
        if it is None:
            return
        key = str(it.data(Qt.ItemDataRole.UserRole) or "").strip()
        path = str(it.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
        if not path:
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "Edit", "Selected file no longer exists.")
            try:
                self.load_images()
            except Exception:
                pass
            return

        try:
            if self.image_editor is not None:
                try:
                    self.image_editor.close()
                except Exception:
                    pass
                self.image_editor = None
        except Exception:
            pass

        try:
            self.image_editor = ImageEditorDialog(
                image_path=path,
                parent=None,
                overlay_controller=self.overlay_controller,
                asset_key=key or None,
            )
            self.image_editor.image_saved.connect(lambda _p: self.load_images())
            self.image_editor.asset_renamed.connect(lambda _o, _n: self.load_images())
            self.image_editor.asset_deleted.connect(lambda _p: self.load_images())
            self.image_editor.show()
        except Exception as e:
            QMessageBox.warning(self, "Edit", f"Failed to open editor: {e}")

    def _on_item_check_changed(self, item: QListWidgetItem):
        if self._updating_checks:
            return
        if self.overlay_controller is None:
            return
        try:
            key = str(item.data(Qt.ItemDataRole.UserRole) or "")
            path = str(item.data(Qt.ItemDataRole.UserRole + 1) or "")
            if not key or not path:
                return
            enabled = (item.checkState() == Qt.CheckState.Checked)
            self.overlay_controller.enable(key, path=path, enabled=enabled)
        except Exception:
            pass

    def _toggle_show_marked(self, show: bool) -> None:
        if self.overlay_controller is None:
            return
        try:
            if show:
                self.overlay_controller.render_selected_from_folder("display_images")
                self.overlay_controller.set_all_visible(True)
            else:
                self.overlay_controller.set_all_visible(False)
        except Exception:
            pass

    def _read_app_settings(self) -> dict:
        try:
            here = Path(__file__).resolve().with_name("app_settings.json")
            if here.exists():
                raw = json.loads(here.read_text(encoding="utf-8"))
                return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}
        return {}

    def _write_app_settings(self, data: dict) -> None:
        try:
            if not isinstance(data, dict):
                return
            here = Path(__file__).resolve().with_name("app_settings.json")
            here.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def save_marked_as_combo(self) -> None:
        # Gather checked keys.
        keys: list[str] = []
        try:
            for i in range(self.image_list.count()):
                it = self.image_list.item(i)
                if it is None:
                    continue
                if it.checkState() != Qt.CheckState.Checked:
                    continue
                k = str(it.data(Qt.ItemDataRole.UserRole) or "").strip()
                if k:
                    keys.append(k)
        except Exception:
            keys = []

        if not keys:
            QMessageBox.information(self, "Save Combo", "No marked items to save.")
            return

        name, ok = QInputDialog.getText(self, "Save Combo", "Combo name:", text="Combo")
        if not ok:
            return
        name = str(name or "").strip() or "Combo"

        data = self._read_app_settings()
        combos = data.get("art_combos")
        if not isinstance(combos, list):
            combos = []

        existing = {str(c.get("name")) for c in combos if isinstance(c, dict) and c.get("name")}
        base = name
        if base in existing:
            n = 2
            while f"{base} ({n})" in existing:
                n += 1
            name = f"{base} ({n})"

        combos.append({"name": name, "keys": keys})
        data["art_combos"] = combos
        self._write_app_settings(data)
        QMessageBox.information(self, "Save Combo", f"Saved combo: {name}")
    
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
