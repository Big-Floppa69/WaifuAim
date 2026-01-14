"""
Image Manager Dialog for adding and managing crosshair images.
"""
import os
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QListWidget, QListWidgetItem, QFileDialog, 
                             QLabel, QFrame, QGraphicsDropShadowEffect, 
                             QMessageBox, QApplication, QInputDialog, QAbstractItemView, QStyledItemDelegate,
                             QDialog, QLineEdit)
from PyQt6.QtGui import QPixmap, QColor, QIcon, QPainter, QPen
from PyQt6.QtCore import Qt, QSize, QUrl, QPoint, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
import json
from utils import UI_THEME, ART_EXTS, IMAGE_EXTS, is_video_path, tr_lit
from image_editor import ImageEditorDialog


class _ArtListWidget(QListWidget):
    orderChanged = pyqtSignal()
    comboArrowClicked = pyqtSignal(str)

    # Right-side affordances layout (must match delegate painting).
    _RIGHT_PAD = 6
    _HANDLE_W = 12
    _ARROW_W = 18

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.setDropIndicatorShown(True)
            self.setDragDropOverwriteMode(False)
        except Exception:
            pass

    def dropEvent(self, event):  # type: ignore[override]
        super().dropEvent(event)
        try:
            self.orderChanged.emit()
        except Exception:
            pass

    def mousePressEvent(self, event):  # type: ignore[override]
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint()
                it = self.itemAt(pos)
                if it is not None:
                    meta = it.data(Qt.ItemDataRole.UserRole)
                    if isinstance(meta, dict) and meta.get("type") == "combo":
                        r = self.visualItemRect(it)
                        arrow_right = r.right() - self._RIGHT_PAD - self._HANDLE_W - 4
                        arrow_left = arrow_right - self._ARROW_W
                        if arrow_left <= pos.x() <= arrow_right:
                            name = str(meta.get("name") or "").strip()
                            if name:
                                self.comboArrowClicked.emit(name)
                                event.accept()
                                return
        except Exception:
            pass

        return super().mousePressEvent(event)


class _DragHandleDelegate(QStyledItemDelegate):
    """Paints a small 3-line drag handle on the right side of each row."""

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        super().paint(painter, option, index)

        try:
            r = option.rect
            x = r.right() - 12
            y_mid = r.center().y()
            color = QColor(UI_THEME.get("accent", "#7C5CFF"))
            try:
                h, s, v, a = color.getHsv()
                v = max(0, min(255, int(v * 0.65)))
                s = max(0, min(255, int(s * 0.85)))
                color.setHsv(h, s, v, a)
            except Exception:
                pass
            color.setAlpha(150)
            pen = QPen(color, 2)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(pen)
            for dy in (-4, 0, 4):
                painter.drawLine(x, y_mid + dy, x + 8, y_mid + dy)

            # Draw combo expand arrow (clickable region handled in _ArtListWidget).
            try:
                meta = index.data(Qt.ItemDataRole.UserRole)
                if isinstance(meta, dict) and meta.get("type") == "combo":
                    expanded = bool(index.data(Qt.ItemDataRole.UserRole + 2))
                    arrow = "▼" if expanded else "▶"
                    arrow_color = QColor(UI_THEME.get("text", "#EDE7FF"))
                    arrow_color.setAlpha(220)
                    painter.setPen(QPen(arrow_color))
                    arrow_right = r.right() - _ArtListWidget._RIGHT_PAD - _ArtListWidget._HANDLE_W - 4
                    arrow_left = arrow_right - _ArtListWidget._ARROW_W
                    painter.drawText(
                        arrow_left,
                        r.top(),
                        _ArtListWidget._ARROW_W,
                        r.height(),
                        Qt.AlignmentFlag.AlignCenter,
                        arrow,
                    )
            except Exception:
                pass
            painter.restore()
        except Exception:
            try:
                painter.restore()
            except Exception:
                pass


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
        self._combo_expanded: set[str] = set()
        self.init_ui()
        self.load_images()

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        # Refresh hold-to-drag chord while the Art Manager is open.
        try:
            if self.overlay_controller is not None:
                cfg = _read_hotkey_config()
                hold = cfg.get("hold_to_drag", [])
                self.overlay_controller.set_hold_to_drag(hold)
                self.overlay_controller.set_selected_key(self._current_selected_key())
        except Exception:
            pass

    def closeEvent(self, event):  # type: ignore[override]
        try:
            if self.overlay_controller is not None:
                # Do not disable dragging globally; just clear selection hint.
                self.overlay_controller.set_selected_key(None)
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
        title = QLabel(tr_lit("🎨 Art Manager"))
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
        info_label = QLabel(tr_lit("Manage your crosshair art (images + videos)"))
        info_label.setStyleSheet(
            "QLabel { color: "
            + UI_THEME["muted"]
            + "; font-size: 12px; padding: 5px; background: transparent; }"
        )
        content_layout.addWidget(info_label)
        
        # Image list
        self.image_list = _ArtListWidget()
        self.image_list.setStyleSheet(
            "QListWidget { background-color: "
            + UI_THEME["surface"]
            + "; border: 1px solid "
            + UI_THEME["border"]
            + "; border-radius: 10px; color: "
            + UI_THEME["text"]
            + "; padding: 6px; font-size: 13px; outline: none; }"
            "QListWidget::item { padding: 8px; border-radius: 8px; margin: 2px; }"
            "QListWidget::item:selected { background-color: "
            + UI_THEME["accent"]
            + "; color: "
            + UI_THEME["bg"]
            + "; outline: none; }"
            "QListWidget::item:focus { outline: none; }"
            "QListWidget::item:hover { background-color: "
            + UI_THEME["surface2"]
            + "; }"
        )
        self.image_list.setIconSize(QSize(48, 48))
        try:
            self.image_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass
        try:
            self.image_list.setItemDelegate(_DragHandleDelegate(self.image_list))
        except Exception:
            pass

        self.image_list.itemChanged.connect(self._on_item_check_changed)
        self.image_list.currentItemChanged.connect(self._on_selection_changed)
        try:
            self.image_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        except Exception:
            pass
        try:
            self.image_list.comboArrowClicked.connect(self._toggle_combo_expanded)
        except Exception:
            pass
        try:
            # Persist sequence after drag reorder.
            self.image_list.orderChanged.connect(self._save_cycle_from_list)
        except Exception:
            pass
        content_layout.addWidget(self.image_list)
        
        # Button container
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        add_btn = self._create_button("➕", role="neutral")
        add_btn.setToolTip(tr_lit("Add Art"))
        add_btn.clicked.connect(self.add_image)
        button_layout.addWidget(add_btn)
        remove_btn = self._create_button("🗑️", role="danger")
        remove_btn.setToolTip(tr_lit("Remove"))
        remove_btn.clicked.connect(self.remove_image)
        button_layout.addWidget(remove_btn)

        edit_btn = self._create_button("✏️", role="neutral")
        edit_btn.setToolTip(tr_lit("Edit selected"))
        edit_btn.setEnabled(False)
        edit_btn.clicked.connect(self.edit_selected)
        self._edit_btn = edit_btn
        button_layout.addWidget(edit_btn)

        show_btn = self._create_button("👁", role="primary")
        show_btn.setCheckable(True)
        show_btn.setChecked(False)
        show_btn.setToolTip(tr_lit("Show/Hide marked"))
        show_btn.clicked.connect(lambda: self._toggle_show_marked(show_btn.isChecked()))
        button_layout.addWidget(show_btn)

        combo_btn = self._create_button("💾", role="neutral")
        combo_btn.setToolTip(tr_lit("Save marked as combo"))
        combo_btn.clicked.connect(self.save_marked_as_combo)
        button_layout.addWidget(combo_btn)
        content_layout.addLayout(button_layout)
        
        # Refresh button
        refresh_btn = self._create_button(tr_lit("🔄 Refresh List"), role="primary")
        refresh_btn.clicked.connect(self.load_images)
        content_layout.addWidget(refresh_btn)
        
        # Info text
        info_text = QLabel(tr_lit("Supported formats: PNG, JPG, JPEG, WEBP, GIF, BMP, MP4, AVI, MOV, WEBM, MKV, M4V"))
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
        try:
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
                    from PyQt6.QtGui import QPolygon

                    poly = QPolygon([QPoint(x, y) for x, y in pts])
                    p.drawPolygon(poly)
                except Exception:
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

            # Collect current assets.
            assets: dict[str, dict] = {}
            try:
                for filename in os.listdir(self.images_folder):
                    if not filename.lower().endswith(ART_EXTS):
                        continue
                    file_path = os.path.join(self.images_folder, filename)
                    key = _key_for_path(file_path)
                    if not key:
                        continue
                    cid = f"file:{key}"
                    assets[cid] = {
                        "filename": filename,
                        "path": os.path.abspath(file_path),
                        "key": key,
                    }
            except Exception:
                assets = {}

            # Collect combos.
            combos_by_id: dict[str, dict] = {}
            try:
                data = self._read_app_settings()
                combos = data.get("art_combos")
                if isinstance(combos, list) and combos:
                    for c in combos:
                        if not isinstance(c, dict):
                            continue
                        name = str(c.get("name") or "").strip()
                        keys = c.get("keys")
                        if not name or not isinstance(keys, list) or not keys:
                            continue
                        cid = f"combo:{name}"
                        combos_by_id[cid] = {
                            "name": name,
                            "keys": [str(k) for k in keys if str(k).strip()],
                        }
            except Exception:
                combos_by_id = {}

            # Load saved sequence (order for switching).
            ordered_ids: list[str] = []
            try:
                data = self._read_app_settings()
                seq = data.get("art_cycle_sequence")
                if isinstance(seq, list):
                    for e in seq:
                        if not isinstance(e, dict):
                            continue
                        t = str(e.get("type") or "").strip().lower()
                        if t == "file":
                            k = str(e.get("key") or "").strip()
                            cid = f"file:{k}" if k else ""
                        elif t == "combo":
                            n = str(e.get("name") or "").strip()
                            cid = f"combo:{n}" if n else ""
                        else:
                            cid = ""
                        if not cid:
                            continue
                        if cid in assets or cid in combos_by_id:
                            ordered_ids.append(cid)
            except Exception:
                ordered_ids = []

            # Append any newly discovered entries.
            seen = set(ordered_ids)
            for cid, meta in sorted(assets.items(), key=lambda kv: str(kv[1].get("filename") or "").lower()):
                if cid not in seen:
                    ordered_ids.append(cid)
                    seen.add(cid)
            for cid, meta in sorted(combos_by_id.items(), key=lambda kv: str(kv[1].get("name") or "").lower()):
                if cid not in seen:
                    ordered_ids.append(cid)
                    seen.add(cid)

            # Populate list in the selected order.
            any_combo_expanded = False
            for cid in ordered_ids:
                if cid.startswith("file:"):
                    meta = assets.get(cid)
                    if not meta:
                        continue
                    filename = str(meta.get("filename") or "")
                    file_path = str(meta.get("path") or "")
                    key = str(meta.get("key") or "")
                    if not filename or not file_path or not key:
                        continue

                    item = QListWidgetItem(filename)
                    try:
                        item.setFlags(
                            item.flags()
                            | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsDragEnabled
                        )
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
                            self._thumb_queue.append((item, file_path))
                    except Exception:
                        pass

                    self.image_list.addItem(item)
                    continue

                if cid.startswith("combo:"):
                    meta = combos_by_id.get(cid)
                    if not meta:
                        continue
                    name = str(meta.get("name") or "").strip()
                    keys = meta.get("keys")
                    if not name or not isinstance(keys, list) or not keys:
                        continue
                    expanded = name in self._combo_expanded
                    any_combo_expanded = any_combo_expanded or expanded
                    item = QListWidgetItem(f"Combo: {name}")
                    try:
                        item.setFlags(
                            item.flags()
                            | Qt.ItemFlag.ItemIsSelectable
                            | Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsDragEnabled
                            | Qt.ItemFlag.ItemIsUserCheckable
                        )
                        item.setData(
                            Qt.ItemDataRole.UserRole,
                            {"type": "combo", "name": name, "keys": [str(k) for k in keys]},
                        )
                        item.setData(Qt.ItemDataRole.UserRole + 2, bool(expanded))
                        item.setIcon(vid_icon)

                        # Tri-state: checked if all children enabled, unchecked if none.
                        enabled_states: list[bool] = []
                        if self.overlay_controller is not None:
                            for k in [str(v) for v in keys if str(v).strip()]:
                                enabled_states.append(bool(self.overlay_controller.is_enabled(k)))
                        if enabled_states:
                            if all(enabled_states):
                                item.setCheckState(Qt.CheckState.Checked)
                            elif not any(enabled_states):
                                item.setCheckState(Qt.CheckState.Unchecked)
                            else:
                                item.setCheckState(Qt.CheckState.PartiallyChecked)
                        else:
                            item.setCheckState(Qt.CheckState.Unchecked)
                    except Exception:
                        pass
                    self.image_list.addItem(item)

                    if expanded:
                        for k in [str(v) for v in keys if str(v).strip()]:
                            child = QListWidgetItem(f"    {os.path.basename(k)}")
                            try:
                                child.setFlags(
                                    child.flags()
                                    | Qt.ItemFlag.ItemIsUserCheckable
                                    | Qt.ItemFlag.ItemIsSelectable
                                    | Qt.ItemFlag.ItemIsEnabled
                                )
                                child.setData(Qt.ItemDataRole.UserRole, k)
                                p = ""
                                try:
                                    meta_file = assets.get(f"file:{k}")
                                    if isinstance(meta_file, dict):
                                        p = str(meta_file.get("path") or "")
                                except Exception:
                                    p = ""
                                if p:
                                    child.setData(Qt.ItemDataRole.UserRole + 1, os.path.abspath(p))
                                enabled = False
                                if self.overlay_controller is not None:
                                    enabled = bool(self.overlay_controller.is_enabled(k))
                                child.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                                child.setData(
                                    Qt.ItemDataRole.UserRole + 3,
                                    {"type": "combo_child", "name": name, "key": k},
                                )
                                child.setSizeHint(QSize(0, 28))
                            except Exception:
                                pass
                            self.image_list.addItem(child)

                    continue

            # Disable drag reorder while any combo accordions are open.
            try:
                self.image_list.setDragEnabled(not any_combo_expanded)
            except Exception:
                pass

            self._start_thumbnailer()

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

            # Persist a canonical sequence if none existed (keeps switch order stable).
            try:
                data = self._read_app_settings()
                seq = data.get("art_cycle_sequence")
                if not isinstance(seq, list) or not seq:
                    self._save_cycle_from_list()
            except Exception:
                pass
        finally:
            self._updating_checks = False

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
                try:
                    self._delete_combo(str(item_meta.get("name") or "").strip())
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
            meta = it.data(Qt.ItemDataRole.UserRole)
            # Combos are not draggable overlay elements.
            if isinstance(meta, dict) and meta.get("type") == "combo":
                return None
            key = str(meta) if meta else ""
            return key if key.strip() else None
        except Exception:
            return None

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Double-click toggles the checkmark (overlay enabled/disabled)."""
        try:
            if item is None:
                return
            if not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                return
            item.setCheckState(
                Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
            )
        except Exception:
            pass

    def _toggle_combo_expanded(self, name: str) -> None:
        name = str(name or "").strip()
        if not name:
            return

        try:
            sb = self.image_list.verticalScrollBar()
            scroll_val = sb.value() if sb is not None else 0
        except Exception:
            scroll_val = 0

        if name in self._combo_expanded:
            self._combo_expanded.discard(name)
        else:
            self._combo_expanded.add(name)

        self.load_images()

        try:
            for i in range(self.image_list.count()):
                it = self.image_list.item(i)
                if it is None:
                    continue
                meta = it.data(Qt.ItemDataRole.UserRole)
                if isinstance(meta, dict) and meta.get("type") == "combo" and str(meta.get("name") or "") == name:
                    self.image_list.setCurrentItem(it)
                    break
        except Exception:
            pass

        try:
            sb = self.image_list.verticalScrollBar()
            if sb is not None:
                sb.setValue(scroll_val)
        except Exception:
            pass

    def _save_cycle_from_list(self) -> None:
        if self._updating_checks:
            return
        seq: list[dict] = []
        try:
            for i in range(self.image_list.count()):
                it = self.image_list.item(i)
                if it is None:
                    continue
                meta = it.data(Qt.ItemDataRole.UserRole)
                if isinstance(meta, dict) and meta.get("type") == "combo":
                    name = str(meta.get("name") or "").strip()
                    if name:
                        seq.append({"type": "combo", "name": name})
                    continue
                if isinstance(meta, dict) and str(meta.get("type") or "").startswith("combo_"):
                    continue
                # File entry: stored as stable key in UserRole.
                key = str(meta or "").strip()
                if key:
                    seq.append({"type": "file", "key": key})
        except Exception:
            return

        try:
            data = self._read_app_settings()
            data["art_cycle_sequence"] = seq
            self._write_app_settings(data)
        except Exception:
            pass

    def _delete_combo(self, name: str) -> None:
        name = str(name or "").strip()
        if not name:
            return

        reply = QMessageBox.question(
            self,
            "Delete Combo",
            f"Delete combo '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        data = self._read_app_settings()
        combos = data.get("art_combos")
        if isinstance(combos, list):
            combos = [c for c in combos if not (isinstance(c, dict) and str(c.get("name") or "") == name)]
        else:
            combos = []
        data["art_combos"] = combos

        seq = data.get("art_cycle_sequence")
        if isinstance(seq, list):
            data["art_cycle_sequence"] = [
                e
                for e in seq
                if not (
                    isinstance(e, dict)
                    and str(e.get("type") or "").strip().lower() == "combo"
                    and str(e.get("name") or "") == name
                )
            ]

        self._write_app_settings(data)
        self._combo_expanded.discard(name)
        self.load_images()

    def _edit_combo(self, name: str) -> None:
        name = str(name or "").strip()
        if not name:
            return

        data = self._read_app_settings()
        combos = data.get("art_combos")
        if not isinstance(combos, list):
            combos = []

        combo = None
        for c in combos:
            if isinstance(c, dict) and str(c.get("name") or "") == name:
                combo = c
                break
        if not isinstance(combo, dict):
            QMessageBox.warning(self, tr_lit("Edit Combo"), tr_lit("Combo not found."))
            return

        # Available file keys from current list items.
        avail: list[tuple[str, str]] = []
        try:
            for i in range(self.image_list.count()):
                it = self.image_list.item(i)
                if it is None:
                    continue
                meta = it.data(Qt.ItemDataRole.UserRole)
                if isinstance(meta, dict):
                    continue
                key = str(meta or "").strip()
                path = str(it.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
                if key and path:
                    avail.append((os.path.basename(path), key))
        except Exception:
            avail = []
        avail.sort(key=lambda t: t[0].lower())

        current_keys = combo.get("keys")
        if not isinstance(current_keys, list):
            current_keys = []
        current_set = {str(k) for k in current_keys if str(k).strip()}

        dlg = QDialog(self)
        dlg.setWindowTitle(tr_lit("Edit Combo"))
        dlg.setModal(True)
        dlg.setStyleSheet(f"QDialog {{ background-color: {UI_THEME['bg']}; color: {UI_THEME['text']}; }}")
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr_lit("Name:")))
        name_edit = QLineEdit(name)
        name_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {UI_THEME['surface']}; border: 1px solid {UI_THEME['border']}; border-radius: 8px; padding: 6px; color: {UI_THEME['text']}; }}"
        )
        name_row.addWidget(name_edit, 1)
        outer.addLayout(name_row)

        listw = QListWidget()
        listw.setStyleSheet(
            f"QListWidget {{ background-color: {UI_THEME['surface']}; border: 1px solid {UI_THEME['border']}; border-radius: 10px; }}"
        )
        for disp, key in avail:
            it = QListWidgetItem(disp)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setCheckState(Qt.CheckState.Checked if key in current_set else Qt.CheckState.Unchecked)
            listw.addItem(it)
        outer.addWidget(listw, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton(tr_lit("Cancel"))
        ok = QPushButton(tr_lit("Save"))
        for b in (cancel, ok):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background-color: {UI_THEME['surface2']}; border: 1px solid {UI_THEME['border']}; border-radius: 10px; padding: 8px 14px; color: {UI_THEME['text']}; font-weight: 700; }}"
            )
        ok.setStyleSheet(
            f"QPushButton {{ background-color: {UI_THEME['accent']}; border: 1px solid {UI_THEME['accent']}; border-radius: 10px; padding: 8px 14px; color: {UI_THEME['bg']}; font-weight: 800; }}"
        )
        cancel.clicked.connect(dlg.reject)
        ok.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        outer.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = str(name_edit.text() or "").strip() or name
        new_keys: list[str] = []
        for i in range(listw.count()):
            it = listw.item(i)
            if it is None:
                continue
            if it.checkState() != Qt.CheckState.Checked:
                continue
            k = str(it.data(Qt.ItemDataRole.UserRole) or "").strip()
            if k:
                new_keys.append(k)
        if not new_keys:
            QMessageBox.warning(self, tr_lit("Edit Combo"), tr_lit("Combo must include at least one item."))
            return

        existing = {str(c.get("name") or "") for c in combos if isinstance(c, dict) and c.get("name")}
        if new_name != name and new_name in existing:
            n = 2
            base = new_name
            while f"{base} ({n})" in existing:
                n += 1
            new_name = f"{base} ({n})"

        combo["name"] = new_name
        combo["keys"] = new_keys
        data["art_combos"] = combos

        if new_name != name:
            seq = data.get("art_cycle_sequence")
            if isinstance(seq, list):
                for e in seq:
                    if not isinstance(e, dict):
                        continue
                    if str(e.get("type") or "").strip().lower() == "combo" and str(e.get("name") or "") == name:
                        e["name"] = new_name
            self._combo_expanded.discard(name)
            self._combo_expanded.add(new_name)

        self._write_app_settings(data)
        self.load_images()

    def _on_selection_changed(self, current, _prev):
        try:
            if self.overlay_controller is not None:
                self.overlay_controller.set_selected_key(self._current_selected_key())
        except Exception:
            pass
        try:
            if self._edit_btn is not None:
                editable = False
                if current is not None:
                    meta = current.data(Qt.ItemDataRole.UserRole)
                    if isinstance(meta, dict) and meta.get("type") == "combo":
                        editable = True
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
        meta = it.data(Qt.ItemDataRole.UserRole)
        if isinstance(meta, dict) and meta.get("type") == "combo":
            name = str(meta.get("name") or "").strip()
            if name:
                self._edit_combo(name)
            return

        key = str(meta or "").strip()
        path = str(it.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
        if not path:
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, tr_lit("Edit"), tr_lit("Selected file no longer exists."))
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
            QMessageBox.warning(self, tr_lit("Edit"), f"{tr_lit('Failed to open editor:')} {e}")

    def _on_item_check_changed(self, item: QListWidgetItem):
        if self._updating_checks:
            return
        if self.overlay_controller is None:
            return
        try:
            meta = item.data(Qt.ItemDataRole.UserRole)

            def _abs_path_for_key(k: str) -> str:
                k = str(k or "").strip()
                if not k:
                    return ""
                if os.path.isabs(k):
                    return os.path.abspath(k)

                # Keys are stored as workspace-relative paths like "display_images/foo.png".
                root = os.path.dirname(os.path.abspath(__file__))
                cand1 = os.path.abspath(os.path.join(root, k.replace("/", os.sep)))

                # Back-compat: some older configs may have stored just the filename.
                cand2 = os.path.abspath(os.path.join(self.images_folder, os.path.basename(k)))
                cand3 = os.path.abspath(os.path.join(self.images_folder, k))

                for cand in (cand1, cand3, cand2):
                    try:
                        if cand and os.path.exists(cand):
                            return cand
                    except Exception:
                        continue
                return cand1

            # Combo parent toggles all children.
            if isinstance(meta, dict) and meta.get("type") == "combo":
                name = str(meta.get("name") or "").strip()
                keys = meta.get("keys")
                if not name or not isinstance(keys, list) or not keys:
                    return

                enabled = item.checkState() != Qt.CheckState.Unchecked
                for k in [str(v) for v in keys if str(v).strip()]:
                    p = _abs_path_for_key(k)
                    if not p:
                        continue
                    self.overlay_controller.enable(k, path=p, enabled=enabled)

                # Sync any visible child rows in the list.
                self._updating_checks = True
                try:
                    for i in range(self.image_list.count()):
                        it = self.image_list.item(i)
                        if it is None:
                            continue
                        child_meta = it.data(Qt.ItemDataRole.UserRole + 3)
                        if not isinstance(child_meta, dict) or child_meta.get("type") != "combo_child":
                            continue
                        if str(child_meta.get("name") or "") != name:
                            continue
                        it.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                finally:
                    self._updating_checks = False
                return

            key = str(meta or "")
            path = str(item.data(Qt.ItemDataRole.UserRole + 1) or "")
            if not key or not path:
                return
            enabled = (item.checkState() == Qt.CheckState.Checked)
            self.overlay_controller.enable(key, path=path, enabled=enabled)

            # Sync all other rows that represent the same key (e.g. combo child vs standalone).
            self._updating_checks = True
            try:
                for i in range(self.image_list.count()):
                    it = self.image_list.item(i)
                    if it is None or it is item:
                        continue
                    m = it.data(Qt.ItemDataRole.UserRole)
                    if isinstance(m, dict):
                        continue
                    if str(m or "") != key:
                        continue
                    it.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            finally:
                self._updating_checks = False

            # Refresh combo parent state for any combo that contains this key.
            try:
                for i in range(self.image_list.count()):
                    it = self.image_list.item(i)
                    if it is None:
                        continue
                    parent_meta = it.data(Qt.ItemDataRole.UserRole)
                    if not isinstance(parent_meta, dict) or parent_meta.get("type") != "combo":
                        continue
                    keys = parent_meta.get("keys")
                    if not isinstance(keys, list) or not keys:
                        continue
                    if key in {str(k) for k in keys if str(k).strip()}:
                        name = str(parent_meta.get("name") or "").strip()
                        if name:
                            self._refresh_combo_parent_checkstate(name)
            except Exception:
                pass

            # If this is a combo child, update the parent tri-state.
            child_meta = item.data(Qt.ItemDataRole.UserRole + 3)
            if isinstance(child_meta, dict) and child_meta.get("type") == "combo_child":
                name = str(child_meta.get("name") or "").strip()
                if name:
                    self._refresh_combo_parent_checkstate(name)
        except Exception:
            pass

    def _refresh_combo_parent_checkstate(self, name: str) -> None:
        if self.overlay_controller is None:
            return
        name = str(name or "").strip()
        if not name:
            return
        try:
            for i in range(self.image_list.count()):
                it = self.image_list.item(i)
                if it is None:
                    continue
                meta = it.data(Qt.ItemDataRole.UserRole)
                if not isinstance(meta, dict) or meta.get("type") != "combo":
                    continue
                if str(meta.get("name") or "").strip() != name:
                    continue
                keys = meta.get("keys")
                if not isinstance(keys, list) or not keys:
                    return
                enabled_states = [bool(self.overlay_controller.is_enabled(str(k))) for k in keys if str(k).strip()]
                if not enabled_states:
                    return
                self._updating_checks = True
                try:
                    if all(enabled_states):
                        it.setCheckState(Qt.CheckState.Checked)
                    elif not any(enabled_states):
                        it.setCheckState(Qt.CheckState.Unchecked)
                    else:
                        it.setCheckState(Qt.CheckState.PartiallyChecked)
                finally:
                    self._updating_checks = False
                return
        except Exception:
            pass

    def _toggle_show_marked(self, show: bool) -> None:
        if self.overlay_controller is None:
            return
        try:
            if show:
                self.overlay_controller.request_render_selected_atomic("display_images", visible=True)
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
                meta = it.data(Qt.ItemDataRole.UserRole)
                if isinstance(meta, dict):
                    continue
                k = str(meta or "").strip()
                if k:
                    keys.append(k)
        except Exception:
            keys = []

        if not keys:
            QMessageBox.information(self, tr_lit("Save Combo"), tr_lit("No marked items to save."))
            return

        name, ok = QInputDialog.getText(self, tr_lit("Save Combo"), tr_lit("Combo name:"), text=tr_lit("Combo"))
        if not ok:
            return
        name = str(name or "").strip() or tr_lit("Combo")

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
        QMessageBox.information(self, tr_lit("Save Combo"), f"{tr_lit('Saved combo:')} {name}")
    
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
