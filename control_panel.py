"""
Control panel widget for managing crosshair settings.
"""
import json
import traceback
import time
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QSlider,
    QFrame,
    QGraphicsDropShadowEffect,
    QComboBox,
    QSizeGrip,
    QSizePolicy,
    QToolButton,
    QScrollBar,
    QAbstractItemView,
)
from PyQt6.QtGui import QPixmap, QColor, QIcon, QFont, QPainter
from PyQt6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, QRectF
from utils import (
    mirror_vertical,
    mirror_horizontal,
    get_art_list,
    set_label_art_from_path,
    clear_label_art,
    refresh_label_pixmap_for_colorblind_mode,
    transparent,
    UI_THEME,
    get_art_cycle_entries,
    get_app_language_from_disk,
    set_app_language_on_disk,
    SUPPORTED_LANGUAGES,
    tr,
    tr_lit,
    apply_language_to_object_tree,
)
from image_manager import ImageManagerDialog
from hotkey_manager import HotkeyManagerDialog
from standard_crosshair import (
    StandardCrosshairDialog,
    load_settings_from_disk,
    render_crosshair_on_label,
    save_crosshair_visibility,
    save_settings_to_disk,
    _apply_preset_dict_to_settings,
    _bind_settings_to_label,
    _sync_fan_timer_state,
)


class DarkControlPanel(QWidget):
    """A dark-themed control panel for managing crosshair settings."""

    APP_SETTINGS_PATH = Path(__file__).resolve().with_name("app_settings.json")
    
    def __init__(self, image_label, crosshair_label, parent=None, *, art_overlay_controller=None):
        super().__init__(parent)
        self.image_label = image_label
        self.crosshair_label = crosshair_label
        self.art_overlay_controller = art_overlay_controller
        self.is_visible = False
        self.drag_position = None
        self.current_image_index = 0
        self.image_list = get_art_list()
        self.opacity_actions = {}
        self.image_manager = None
        self.hotkey_manager = None
        self.crosshair_dialog = None
        self.crosshair_preset_combo = None

        # Side panel behavior
        self._collapsed = False
        self._expanded_width = 320
        self._collapsed_width = 76
        self._crosshair_width = 560
        # Account for the internal title bar so the main menu doesn't get vertically cramped.
        self._main_size = QSize(320, 960)
        self._crosshair_size = QSize(560, 760)
        self._collapse_btn = None
        self._back_btn = None
        self._title_label = None
        self._title_bar = None
        self._collapsible_buttons: list[QPushButton] = []
        self._preset_container = None
        self._mirror_container = None
        self._opacity_container = None
        self._separator = None
        self._hotkey_info_label = None

        # Sidebar preset icon (collapsed mode)
        self._drawer_preset_icon_btn = None

        # Single-view layout (no stacked pages).
        self._content = None

        # Compact mode: when panel is resized to the minimum size, hide all UI
        # below the main action buttons row.
        self._below_action_container = None
        self._is_compact_mode = False

        # Track last panel position to avoid "teleporting" when reopening.
        self._last_panel_pos = None

        # Opacity accordion header (to show current colorblind mode in title).
        self._opacity_accordion_header = None

        # Action bar buttons
        self._btn_toggle_image = None
        self._btn_toggle_crosshair = None
        self._btn_next_image = None
        self._btn_manage_images = None
        self._btn_hotkeys = None
        self._btn_mirror_v = None
        self._btn_mirror_h = None

        # App window opacity
        self.window_opacity_slider = None
        self.window_opacity_value = None

        # Accessibility: colorblindness mode (persisted, currently UI-only)
        self.colorblind_mode_combo = None

        # Track programmatic resizing so we can persist user-resized sizes per page.
        self._programmatic_resize = False

        # Resizing (frameless)
        self._resize_margin = 7
        self._resizing = False
        self._resize_edges: set[str] = set()
        self._resize_start_pos = None
        self._resize_start_geom = None
        self._size_grip = None
        self.init_ui()

        # Apply initial language across the whole panel.
        try:
            apply_language_to_object_tree(self)
        except Exception:
            pass
        # Dragging helpers
        self._maybe_drag = False
        self._press_pos = None
        self._drag_offset = None
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Allow manual resizing.
        self.setMinimumSize(450, 150)
        
        # Main container with dark background and rounded edges
        main_frame = self._create_main_frame()
        
        # Layout
        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Title bar with buttons
        title_bar = self._create_title_bar()
        self._title_bar = title_bar
        layout.addWidget(title_bar)

        # Content container (single primary view)
        self._content = self._create_primary_settings_view()
        layout.addWidget(self._content)

        # Resize handle for the frameless panel.
        self._size_grip = QSizeGrip(main_frame)
        self._size_grip.setFixedSize(16, 16)
        self._size_grip.setStyleSheet("QSizeGrip { background: transparent; }")
        
        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_frame)

        # Apply persisted window opacity (app-level setting).
        try:
            self._apply_window_opacity_from_disk()
        except Exception:
            pass

        # Default size for the Standard Crosshair primary view.
        self.resize(self._crosshair_size)
        self._set_title_mode("crosshair")

    # Instrumentation: override move/setGeometry to capture callers when the
    # control panel is unexpectedly moved. Writes timestamped stack traces to
    # move_debug.log in the project root so we can identify the caller.
    def move(self, *args, **kwargs):
        try:
            try:
                log_path = Path(__file__).resolve().with_name("move_debug.log")
            except Exception:
                log_path = Path("move_debug.log")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- MOVE called at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                fh.write("Args: %r, Kwargs: %r\n" % (args, kwargs))
                for line in traceback.format_stack():
                    fh.write(line)
                fh.write("--- END STACK ---\n")
        except Exception:
            pass
        return super().move(*args, **kwargs)

    def setGeometry(self, *args, **kwargs):
        try:
            try:
                log_path = Path(__file__).resolve().with_name("move_debug.log")
            except Exception:
                log_path = Path("move_debug.log")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- setGeometry called at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                fh.write("Args: %r, Kwargs: %r\n" % (args, kwargs))
                for line in traceback.format_stack():
                    fh.write(line)
                fh.write("--- END STACK ---\n")
        except Exception:
            pass
        return super().setGeometry(*args, **kwargs)

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        try:
            if self._size_grip is not None:
                margin = 8
                self._size_grip.move(
                    self.width() - self._size_grip.width() - margin,
                    self.height() - self._size_grip.height() - margin,
                )
                self._size_grip.raise_()
        except Exception:
            pass

        # Enter compact mode only when hitting the minimum size.
        try:
            self._update_compact_mode()
        except Exception:
            pass

    def _update_compact_mode(self) -> None:
        container = getattr(self, "_below_action_container", None)
        if container is None:
            return

        # The panel already has a minimum size (450x150). When the user shrinks
        # the window to that minimum, only the top icon row should remain.
        w = int(self.width())
        h = int(self.height())
        min_w = int(self.minimumWidth())
        min_h = int(self.minimumHeight())

        # Use a small epsilon because Qt may report off-by-1 sizes depending on
        # platform/window frame rounding.
        eps = 2
        compact = (w <= (min_w + eps)) and (h <= (min_h + eps))

        if compact == bool(getattr(self, "_is_compact_mode", False)):
            return
        self._is_compact_mode = bool(compact)
        container.setVisible(not compact)

    def _hit_test_edges(self, pos) -> set[str]:
        """Return a set of edges (left/right/top/bottom) if pos is near them."""
        m = int(self._resize_margin)
        edges: set[str] = set()
        x = int(pos.x())
        y = int(pos.y())
        if x <= m:
            edges.add("left")
        if x >= self.width() - m:
            edges.add("right")
        if y <= m:
            edges.add("top")
        if y >= self.height() - m:
            edges.add("bottom")
        return edges

    def _cursor_for_edges(self, edges: set[str]):
        if not edges:
            return Qt.CursorShape.ArrowCursor
        if edges == {"left"} or edges == {"right"}:
            return Qt.CursorShape.SizeHorCursor
        if edges == {"top"} or edges == {"bottom"}:
            return Qt.CursorShape.SizeVerCursor
        if ("left" in edges and "top" in edges) or ("right" in edges and "bottom" in edges):
            return Qt.CursorShape.SizeFDiagCursor
        return Qt.CursorShape.SizeBDiagCursor
    
    def _create_main_frame(self):
        """Create the main frame with styling and shadow effect."""
        main_frame = QFrame(self)
        main_frame.setObjectName("mainFrame")
        main_frame.setStyleSheet("""
            QFrame#mainFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0F0B1E, stop:1 #130F2A);
                border-radius: 15px;
                border: 1px solid rgba(230, 225, 255, 40);
            }
        """)
        
        # Add shadow effect
        # shadow = QGraphicsDropShadowEffect(self)
        # shadow.setBlurRadius(30)
        # shadow.setColor(QColor(0, 0, 0, 180))
        # shadow.setOffset(0, 5)
        # main_frame.setGraphicsEffect(shadow)
        
        return main_frame
    
    def _create_title_bar(self):
        """Create the title bar with minimize and close buttons."""
        title_bar = QFrame()
        title_bar.setStyleSheet(
            f"""
            QFrame {{
                background-color: {UI_THEME['surface']};
                border-top-left-radius: 15px;
                border-top-right-radius: 15px;
                border-bottom: 1px solid {UI_THEME['border']};
            }}
            """
        )

        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(15, 8, 8, 8)
        title_bar_layout.setSpacing(6)

        # Back button (only visible on sub-pages)
        self._back_btn = self._create_window_button("←", self._show_main_menu)
        self._back_btn.setVisible(False)
        title_bar_layout.addWidget(self._back_btn)

        self._title_label = QLabel(tr_lit("Crosshair Control"))
        self._title_label.setStyleSheet(
            f"""
            QLabel {{
                color: {UI_THEME['text']};
                font-size: 14px;
                font-weight: 800;
                background: transparent;
            }}
            """
        )
        title_bar_layout.addWidget(self._title_label)
        title_bar_layout.addStretch()

        # (Removed) Collapse/expand button
        self._collapse_btn = None

        minimize_btn = self._create_window_button("−", self.hide)
        title_bar_layout.addWidget(minimize_btn)

        close_btn = self._create_window_button("×", QApplication.quit, is_close=True)
        title_bar_layout.addWidget(close_btn)

        return title_bar

    def _set_title_mode(self, mode: str) -> None:
        """Update title bar widgets depending on current page."""
        mode = (mode or "main").lower()
        # Single-view redesign: treat everything as the crosshair/settings page.
        is_main = False
        try:
            if self._back_btn is not None:
                self._back_btn.setVisible(False)
            if self._title_label is not None:
                self._title_label.setText("WaifuAim")
                self._title_label.setVisible(True)
        except Exception:
            pass

    def _read_app_settings(self) -> dict:
        try:
            if self.APP_SETTINGS_PATH.exists():
                raw = json.loads(self.APP_SETTINGS_PATH.read_text(encoding="utf-8"))
                return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}
        return {}

    def _write_app_settings(self, data: dict) -> None:
        try:
            if not isinstance(data, dict):
                return
            self.APP_SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            return

    def _apply_window_opacity_from_disk(self) -> None:
        data = self._read_app_settings()
        value = int(data.get("window_opacity", 100))
        value = max(30, min(100, value))
        self.setWindowOpacity(value / 100.0)
        if self.window_opacity_slider is not None:
            self.window_opacity_slider.blockSignals(True)
            self.window_opacity_slider.setValue(value)
            self.window_opacity_slider.blockSignals(False)
        if self.window_opacity_value is not None:
            self.window_opacity_value.setText(f"{value}%")

    def _persist_window_opacity(self, value: int) -> None:
        value = int(value)
        value = max(30, min(100, value))
        data = self._read_app_settings()
        data["window_opacity"] = value
        self._write_app_settings(data)

    def _persist_colorblind_mode(self, mode: str) -> None:
        mode = str(mode or "default").strip().lower() or "default"
        data = self._read_app_settings()
        data["colorblind_mode"] = mode
        self._write_app_settings(data)

        try:
            self._update_opacity_accordion_title()
        except Exception:
            pass

        # Apply immediately to the currently displayed image overlay.
        try:
            refresh_label_pixmap_for_colorblind_mode(self.image_label)
        except Exception:
            pass

    def _format_colorblind_mode_label(self, mode: str) -> str:
        mode = str(mode or "default").strip().lower() or "default"
        lang = get_app_language_from_disk("en")
        if lang == "ru":
            mapping = {
                "default": "По умолчанию",
                "protanopia": "Протанопия",
                "deuteranopia": "Дейтеранопия",
                "tritanopia": "Тританопия",
                "achromatopsia": "Ахроматопсия",
            }
        else:
            mapping = {
                "default": "Default",
                "protanopia": "Protanopia",
                "deuteranopia": "Deuteranopia",
                "tritanopia": "Tritanopia",
                "achromatopsia": "Achromatopsia",
            }
        return mapping.get(mode, mode.capitalize())

    def _update_opacity_accordion_title(self) -> None:
        header = getattr(self, "_opacity_accordion_header", None)
        if header is None:
            return
        data = self._read_app_settings()
        mode = str(data.get("colorblind_mode", "default") or "default").strip().lower()
        title = tr("opacity_language_title")
        prefix = tr("colorblind_prefix")
        header.setText(f"{title} ({prefix}: {self._format_colorblind_mode_label(mode)})")

    def _apply_language_from_disk(self) -> None:
        combo = getattr(self, "language_combo", None)
        if combo is None:
            return
        lang = get_app_language_from_disk("en")
        idx = combo.findData(lang)
        if idx < 0:
            idx = combo.findData("en")
        combo.blockSignals(True)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _on_language_changed(self, _index: int) -> None:
        combo = getattr(self, "language_combo", None)
        if combo is None:
            return
        lang = str(combo.currentData() or "en").strip().lower() or "en"
        set_app_language_on_disk(lang)
        self._update_opacity_accordion_texts()
        self._update_opacity_accordion_title()

        # Preserve actual crosshair visibility while we rebuild UI.
        try:
            was_visible = bool(self.crosshair_label.isVisible())
        except Exception:
            was_visible = None

        # Rebuild embedded crosshair settings so its UI strings update.
        try:
            self._rebuild_embedded_crosshair_dialog()
        except Exception:
            pass

        # Restore visibility (language switching must not force-show/hide).
        try:
            if was_visible is not None:
                self.crosshair_label.setVisible(bool(was_visible))
                if self.crosshair_label.isVisible():
                    self.crosshair_label.raise_()
        except Exception:
            pass

        # Refresh control panel titles/tooltips.
        try:
            self._apply_language_to_control_panel()
        except Exception:
            pass

        # Apply the language to all currently open windows/dialogs.
        try:
            from PyQt6.QtWidgets import QApplication

            for w in QApplication.topLevelWidgets():
                apply_language_to_object_tree(w)
        except Exception:
            pass

    def _rebuild_embedded_crosshair_dialog(self) -> None:
        below = getattr(self, "_below_layout", None)
        if below is None:
            return
        old = getattr(self, "crosshair_dialog", None)
        if old is None:
            return

        try:
            below.removeWidget(old)
        except Exception:
            pass
        try:
            old.setParent(None)
            old.deleteLater()
        except Exception:
            pass

        self.crosshair_dialog = StandardCrosshairDialog(
            self.crosshair_label,
            self,
            embedded=True,
            on_request_close=None,
        )
        self.crosshair_dialog.visibility_changed.connect(self._on_crosshair_dialog_visibility)
        if hasattr(self.crosshair_dialog, "presets_changed"):
            self.crosshair_dialog.presets_changed.connect(self._refresh_crosshair_presets_ui)

        below.addWidget(self.crosshair_dialog, 1)

    def _apply_language_to_control_panel(self) -> None:
        # Main title (top-left)
        lbl = getattr(self, "_title_label", None)
        if lbl is not None:
            # The title changes depending on tab; keep it simple here.
            cur = str(lbl.text() or "")
            if cur in ("Crosshair Control", tr_lit("Crosshair Control")):
                lbl.setText(tr_lit("Crosshair Control"))
            elif cur in ("WaifuAim", tr_lit("WaifuAim")):
                lbl.setText("WaifuAim")

        # Tooltips/state labels.
        self._sync_action_bar_state()

        # Best-effort: translate any remaining literal strings in the widget tree.
        try:
            apply_language_to_object_tree(self)
        except Exception:
            pass

    def _update_opacity_accordion_texts(self) -> None:
        # Update the visible strings inside the opacity/language accordion.
        lbl = getattr(self, "_opacity_crosshair_label", None)
        if lbl is not None:
            lbl.setText(tr("crosshair_opacity"))
        lbl = getattr(self, "_opacity_window_label", None)
        if lbl is not None:
            lbl.setText(tr("window_opacity"))
        lbl = getattr(self, "_opacity_mode_label", None)
        if lbl is not None:
            lbl.setText(tr("colorblind_mode"))
        lbl = getattr(self, "_opacity_language_label", None)
        if lbl is not None:
            lbl.setText(tr("language"))

        # Update language combo texts.
        combo = getattr(self, "language_combo", None)
        if combo is not None:
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("english"), "en")
            combo.addItem(tr("russian"), "ru")
            idx = combo.findData(cur)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        # Update colorblind option labels.
        cb = getattr(self, "colorblind_mode_combo", None)
        if cb is not None:
            cur = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            cb.addItem(self._format_colorblind_mode_label("default"), "default")
            cb.addItem(self._format_colorblind_mode_label("protanopia"), "protanopia")
            cb.addItem(self._format_colorblind_mode_label("deuteranopia"), "deuteranopia")
            cb.addItem(self._format_colorblind_mode_label("tritanopia"), "tritanopia")
            cb.addItem(self._format_colorblind_mode_label("achromatopsia"), "achromatopsia")
            idx = cb.findData(cur)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.blockSignals(False)

    def _apply_colorblind_mode_from_disk(self) -> None:
        combo = getattr(self, "colorblind_mode_combo", None)
        if combo is None:
            return
        data = self._read_app_settings()
        mode = str(data.get("colorblind_mode", "default") or "default").strip().lower()
        idx = combo.findData(mode)
        if idx < 0:
            idx = combo.findData("default")
        combo.blockSignals(True)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _set_window_opacity(self, value: int) -> None:
        value = int(value)
        value = max(30, min(100, value))
        try:
            self.setWindowOpacity(value / 100.0)
        except Exception:
            return
        if self.window_opacity_value is not None:
            self.window_opacity_value.setText(f"{value}%")
        self._persist_window_opacity(value)

    def _create_primary_settings_view(self) -> QWidget:
        """Primary settings view: top actions + opacity accordion + standard crosshair settings."""
        page = QWidget()
        page.setStyleSheet("QWidget { background: transparent; }")
        root = QVBoxLayout(page)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        root.addWidget(self._create_top_action_bar())

        # Everything below the main action bar is grouped into a single container
        # so we can hide it when the window is shrunk to its minimum size.
        self._below_action_container = QWidget()
        self._below_action_container.setStyleSheet("QWidget { background: transparent; }")
        below = QVBoxLayout(self._below_action_container)
        below.setContentsMargins(0, 0, 0, 0)
        below.setSpacing(10)
        self._below_layout = below

        below.addWidget(self._create_opacity_accordion())

        # Embedded Standard Crosshair settings.
        self.crosshair_dialog = StandardCrosshairDialog(
            self.crosshair_label,
            self,
            embedded=True,
            on_request_close=None,
        )
        self.crosshair_dialog.visibility_changed.connect(self._on_crosshair_dialog_visibility)
        if hasattr(self.crosshair_dialog, "presets_changed"):
            self.crosshair_dialog.presets_changed.connect(self._refresh_crosshair_presets_ui)
        below.addWidget(self.crosshair_dialog, 1)

        root.addWidget(self._below_action_container, 1)

        # Sync action button tooltips/state.
        self._sync_action_bar_state()

        # Apply compact-mode visibility for the initial geometry.
        try:
            self._update_compact_mode()
        except Exception:
            pass
        return page

    def _square_icon_btn_style(self) -> str:
        return (
            f"QPushButton {{"
            f" background-color: {UI_THEME['surface2']};"
            f" color: {UI_THEME['text']};"
            f" border: 1px solid {UI_THEME['border']};"
            f" border-radius: 14px;"
            f" font-size: 18px;"
            f" font-weight: 800;"
            f" padding: 0px;"
            f" }}"
            f"QPushButton:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}"
            f"QPushButton:pressed {{ background-color: {UI_THEME['surface']}; }}"
            f"QPushButton:checked {{ background-color: {UI_THEME['accent']}; border: 1px solid {UI_THEME['accent']}; color: {UI_THEME['bg']}; }}"
        )

    def _rotated_text_icon(self, text: str, angle: float, size: int = 36, font_size: int = 20) -> QIcon:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        font = QFont()
        font.setPointSize(font_size)
        painter = QPainter(pix)
        painter.setFont(font)
        painter.setPen(QColor(UI_THEME['text']))
        painter.translate(size / 2, size / 2)
        painter.rotate(angle)
        painter.drawText(QRectF(-size / 2, -size / 2, size, size), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return QIcon(pix)

    def _create_icon_button(self, icon_text: str, tooltip: str, callback, *, checkable: bool = False) -> QPushButton:
        btn = QPushButton(icon_text)
        btn.setFixedSize(44, 44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setCheckable(bool(checkable))
        btn.setStyleSheet(self._square_icon_btn_style())
        if callback is not None:
            btn.clicked.connect(callback)
        return btn

    def _create_mirror_split_control(self) -> QFrame:
        """Two halves that read as a single control (mirror vertical/horizontal)."""
        wrapper = QFrame()
        wrapper.setStyleSheet("QFrame { background: transparent; }")
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        def seg_style(position: str) -> str:
            left_radius = "14px" if position == "left" else "0px"
            right_radius = "14px" if position == "right" else "0px"
            extra_border = "border-left: none;" if position == "right" else ""
            return (
                f"QPushButton {{"
                f" background-color: {UI_THEME['surface2']};"
                f" color: {UI_THEME['text']};"
                f" border: 1px solid {UI_THEME['border']};"
                f" {extra_border}"
                f" border-top-left-radius: {left_radius};"
                f" border-bottom-left-radius: {left_radius};"
                f" border-top-right-radius: {right_radius};"
                f" border-bottom-right-radius: {right_radius};"
                f" font-size: 18px;"
                f" font-weight: 800;"
                f" padding: 0px;"
                f" min-width: 40px;"
                f" min-height: 35px;"
                f" }}"
                f"QPushButton:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}"
                f"QPushButton:pressed {{ background-color: {UI_THEME['surface']}; }}"
            )

        self._btn_mirror_v = QPushButton()
        self._btn_mirror_v.setFixedSize(44, 44)
        self._btn_mirror_v.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mirror_v.setToolTip("Mirror Vertical")
        self._btn_mirror_v.setStyleSheet(seg_style("left"))
        # Render a rotated arrow icon (90°) for vertical mirror
        try:
            self._btn_mirror_v.setText("")
            self._btn_mirror_v.setIcon(self._rotated_text_icon("↔️", 90, size=44, font_size=14))
            self._btn_mirror_v.setIconSize(QSize(44, 44))
        except Exception:
            self._btn_mirror_v.setText("↔️")
        self._btn_mirror_v.clicked.connect(lambda: mirror_vertical(self.image_label, self.image_label.pixmap()))

        self._btn_mirror_h = QPushButton("↔️")
        self._btn_mirror_h.setFixedSize(44, 44)
        self._btn_mirror_h.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mirror_h.setToolTip("Mirror Horizontal")
        self._btn_mirror_h.setStyleSheet(seg_style("right"))
        self._btn_mirror_h.clicked.connect(lambda: mirror_horizontal(self.image_label, self.image_label.pixmap()))

        layout.addWidget(self._btn_mirror_v)
        layout.addWidget(self._btn_mirror_h)
        return wrapper

    def _create_top_action_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background-color: {UI_THEME['surface']}; border-radius: 14px; border: 1px solid {UI_THEME['border']}; }}"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 10, 10, 10)
        row.setSpacing(10)

        # Keep the top action bar a fixed height so its background doesn't
        # expand when the rest of the UI is hidden (compact mode).
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bar.setFixedHeight(64)

        self._btn_toggle_image = self._create_icon_button("🖼️", tr_lit("Show/Hide Image"), self.toggle_image_visibility, checkable=True)
        self._btn_toggle_crosshair = self._create_icon_button("🎯", tr_lit("Show/Hide Crosshair"), self.toggle_crosshair_visibility, checkable=True)
        self._btn_next_image = self._create_icon_button("⏭️", "Next Image", self.switch_image)
        self._btn_manage_images = self._create_icon_button("🎨", "Art Manager", self.open_image_manager)
        self._btn_hotkeys = self._create_icon_button("⌨️", "Customize Hotkeys", self.open_hotkey_manager)
        mirror = self._create_mirror_split_control()

        row.addWidget(self._btn_toggle_image)
        row.addWidget(self._btn_toggle_crosshair)
        row.addWidget(mirror)
        row.addStretch(1)
        row.addWidget(self._btn_next_image)
        row.addWidget(self._btn_manage_images)
        row.addWidget(self._btn_hotkeys)
        return bar

    def _create_accordion(self, title: str, content: QWidget, *, expanded: bool = False) -> QFrame:
        wrapper = QFrame()
        wrapper.setStyleSheet(
            f"QFrame {{ background-color: {UI_THEME['surface']}; border-radius: 14px; border: 1px solid {UI_THEME['border']}; }}"
        )
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        header = QToolButton()
        header.setText(title)
        header.setCheckable(True)
        header.setChecked(bool(expanded))
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none; color: {UI_THEME['text']}; font-weight: 800; font-size: 12px; padding: 4px 2px; }}"
            f"QToolButton:hover {{ color: {UI_THEME['text']}; }}"
        )

        content.setVisible(bool(expanded))

        def on_toggle(checked: bool) -> None:
            content.setVisible(bool(checked))
            header.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

        header.toggled.connect(on_toggle)
        layout.addWidget(header)
        layout.addWidget(content)

        # Expose header for callers that want to update the title.
        try:
            setattr(wrapper, "_header_btn", header)
        except Exception:
            pass
        return wrapper

    def _create_opacity_accordion(self) -> QFrame:
        content = QFrame()
        content.setStyleSheet("QFrame { background: transparent; border: none; }")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Crosshair opacity (existing behavior): controls overlay labels.
        crosshair_row = QFrame()
        crosshair_row.setStyleSheet(
            f"QFrame {{ background-color: {UI_THEME['surface2']}; border-radius: 12px; border: 1px solid {UI_THEME['border']}; }}"
        )
        crosshair_layout = QHBoxLayout(crosshair_row)
        crosshair_layout.setContentsMargins(12, 10, 12, 10)
        crosshair_layout.setSpacing(10)
        crosshair_label = QLabel(tr("crosshair_opacity"))
        crosshair_label.setStyleSheet(f"color: {UI_THEME['muted']}; font-size: 11px; font-weight: 700;")
        crosshair_layout.addWidget(crosshair_label)
        try:
            self._opacity_crosshair_label = crosshair_label
        except Exception:
            pass

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setFixedHeight(18)
        self.opacity_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.opacity_slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{ border: none; height: 6px; background: rgba(230, 225, 255, 35); border-radius: 3px; }}
            QSlider::sub-page:horizontal {{ background: {UI_THEME['accent']}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ background: {UI_THEME['accent']}; border: none; width: 16px; margin: -5px 0; border-radius: 8px; }}
            QSlider::handle:horizontal:hover {{ background: {UI_THEME.get('accent2', UI_THEME['accent'])}; }}
            """
        )
        self.opacity_slider.valueChanged.connect(self.change_opacity)

        self.opacity_value = QLabel("100%")
        self.opacity_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.opacity_value.setFixedHeight(26)
        self.opacity_value.setMinimumWidth(62)
        self.opacity_value.setStyleSheet(
            f"QLabel {{ color: {UI_THEME['text']}; font-size: 11px; font-weight: 800; background-color: {UI_THEME['surface']}; border: 1px solid {UI_THEME['border']}; border-radius: 10px; padding: 0px 10px; }}"
        )
        crosshair_layout.addWidget(self.opacity_slider, 1)
        crosshair_layout.addWidget(self.opacity_value)
        layout.addWidget(crosshair_row)

        # Window opacity (new app-level setting): controls the control panel window.
        window_row = QFrame()
        window_row.setStyleSheet(
            f"QFrame {{ background-color: {UI_THEME['surface2']}; border-radius: 12px; border: 1px solid {UI_THEME['border']}; }}"
        )
        window_layout = QHBoxLayout(window_row)
        window_layout.setContentsMargins(12, 10, 12, 10)
        window_layout.setSpacing(10)
        window_label = QLabel(tr("window_opacity"))
        window_label.setStyleSheet(f"color: {UI_THEME['muted']}; font-size: 11px; font-weight: 700;")
        window_layout.addWidget(window_label)
        try:
            self._opacity_window_label = window_label
        except Exception:
            pass

        self.window_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.window_opacity_slider.setMinimum(30)
        self.window_opacity_slider.setMaximum(100)
        self.window_opacity_slider.setValue(100)
        self.window_opacity_slider.setFixedHeight(18)
        self.window_opacity_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.window_opacity_slider.setStyleSheet(self.opacity_slider.styleSheet())
        self.window_opacity_slider.valueChanged.connect(self._set_window_opacity)

        self.window_opacity_value = QLabel("100%")
        self.window_opacity_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window_opacity_value.setFixedHeight(26)
        self.window_opacity_value.setMinimumWidth(62)
        self.window_opacity_value.setStyleSheet(self.opacity_value.styleSheet())
        window_layout.addWidget(self.window_opacity_slider, 1)
        window_layout.addWidget(self.window_opacity_value)
        layout.addWidget(window_row)

        # Colorblindness mode (UI selector; persisted for future use).
        mode_row = QFrame()
        mode_row.setStyleSheet(
            f"QFrame {{ background-color: {UI_THEME['surface2']}; border-radius: 12px; border: 1px solid {UI_THEME['border']}; }}"
        )
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(12, 10, 12, 10)
        mode_layout.setSpacing(10)
        mode_label = QLabel(tr("colorblind_mode"))
        mode_label.setStyleSheet(f"color: {UI_THEME['muted']}; font-size: 11px; font-weight: 700;")
        mode_layout.addWidget(mode_label)
        try:
            self._opacity_mode_label = mode_label
        except Exception:
            pass

        self.colorblind_mode_combo = QComboBox()
        self.colorblind_mode_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.colorblind_mode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.colorblind_mode_combo.setStyleSheet(
            f"QComboBox {{ background-color: {UI_THEME['surface']}; color: {UI_THEME['text']}; border: 1px solid {UI_THEME['border']}; border-radius: 10px; padding: 6px 10px; font-size: 11px; font-weight: 800; }}"
            f"QComboBox:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background-color: {UI_THEME['surface']}; color: {UI_THEME['text']}; border: 1px solid {UI_THEME['border']}; selection-background-color: {UI_THEME['accent']}; }}"
        )
        self.colorblind_mode_combo.addItem(self._format_colorblind_mode_label("default"), "default")
        self.colorblind_mode_combo.addItem(self._format_colorblind_mode_label("protanopia"), "protanopia")
        self.colorblind_mode_combo.addItem(self._format_colorblind_mode_label("deuteranopia"), "deuteranopia")
        self.colorblind_mode_combo.addItem(self._format_colorblind_mode_label("tritanopia"), "tritanopia")
        self.colorblind_mode_combo.addItem(self._format_colorblind_mode_label("achromatopsia"), "achromatopsia")
        self.colorblind_mode_combo.currentIndexChanged.connect(
            lambda _: self._persist_colorblind_mode(self.colorblind_mode_combo.currentData())
        )
        mode_layout.addWidget(self.colorblind_mode_combo, 1)
        layout.addWidget(mode_row)

        # Language
        lang_row = QFrame()
        lang_row.setStyleSheet(
            f"QFrame {{ background-color: {UI_THEME['surface2']}; border-radius: 12px; border: 1px solid {UI_THEME['border']}; }}"
        )
        lang_layout = QHBoxLayout(lang_row)
        lang_layout.setContentsMargins(12, 10, 12, 10)
        lang_layout.setSpacing(10)
        lang_label = QLabel(tr("language"))
        lang_label.setStyleSheet(f"color: {UI_THEME['muted']}; font-size: 11px; font-weight: 700;")
        lang_layout.addWidget(lang_label)
        try:
            self._opacity_language_label = lang_label
        except Exception:
            pass

        self.language_combo = QComboBox()
        self.language_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.language_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.language_combo.setStyleSheet(self.colorblind_mode_combo.styleSheet())
        self.language_combo.addItem(tr("english"), "en")
        self.language_combo.addItem(tr("russian"), "ru")
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self.language_combo, 1)
        layout.addWidget(lang_row)

        # Apply persisted window opacity now that controls exist.
        try:
            self._apply_window_opacity_from_disk()
        except Exception:
            pass

        # Apply persisted colorblind mode now that the combo exists.
        try:
            self._apply_colorblind_mode_from_disk()
        except Exception:
            pass

        # Apply persisted language now that the combo exists.
        try:
            self._apply_language_from_disk()
        except Exception:
            pass

        wrapper = self._create_accordion(tr("opacity_language_title"), content, expanded=False)
        try:
            self._opacity_accordion_header = getattr(wrapper, "_header_btn", None)
            self._update_opacity_accordion_title()
        except Exception:
            pass
        return wrapper

    def _sync_action_bar_state(self) -> None:
        try:
            if self._btn_toggle_image is not None:
                self._btn_toggle_image.blockSignals(True)
                self._btn_toggle_image.setChecked(bool(self.image_label.isVisible()))
                self._btn_toggle_image.blockSignals(False)
                self._btn_toggle_image.setToolTip(tr_lit("Hide Image") if self.image_label.isVisible() else tr_lit("Show Image"))
            if self._btn_toggle_crosshair is not None:
                self._btn_toggle_crosshair.blockSignals(True)
                self._btn_toggle_crosshair.setChecked(bool(self.crosshair_label.isVisible()))
                self._btn_toggle_crosshair.blockSignals(False)
                self._btn_toggle_crosshair.setToolTip(tr_lit("Hide Crosshair") if self.crosshair_label.isVisible() else tr_lit("Show Crosshair"))
        except Exception:
            return

    def _register_collapsible_button(self, btn: QPushButton, full_text: str) -> None:
        """Track a button so it can collapse to an icon-only variant."""
        if btn is None:
            return
        full_text = str(full_text or btn.text())
        btn.setProperty("fullText", full_text)
        icon = str(full_text).strip().split(" ", 1)[0] if str(full_text).strip() else ""
        btn.setProperty("iconText", icon)
        btn.setToolTip(full_text)
        self._collapsible_buttons.append(btn)

        # If currently collapsed, immediately apply icon-only label.
        try:
            if getattr(self, "_collapsed", False):
                btn.setText(icon if icon else full_text)
            else:
                btn.setText(full_text)
        except Exception:
            pass

    def set_collapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed

        # Collapsing only applies to the main menu page.
        if self._stack is not None and self._page_crosshair is not None and self._stack.currentWidget() == self._page_crosshair:
            return

        # Persist user-resized size per page.
        try:
            if not getattr(self, "_programmatic_resize", False) and self._stack is not None:
                cur = self._stack.currentWidget()
                if cur is not None and cur == self._page_main:
                    self._main_size = self.size()
                elif cur is not None and cur == self._page_crosshair:
                    self._crosshair_size = self.size()
        except Exception:
            pass
        self.setFixedWidth(self._collapsed_width if collapsed else self._expanded_width)
        if self._collapse_btn is not None:
            self._collapse_btn.setText("❯" if collapsed else "❮")

        # Hide text-heavy widgets in collapsed mode.
        for w in (self._preset_container, self._opacity_container, self._separator, self._hotkey_info_label):
            try:
                if w is not None:
                    w.setVisible(not collapsed)
            except Exception:
                pass
        # Keep legacy behavior but avoid locking width permanently.
        target_w = self._collapsed_width if collapsed else self._expanded_width
        try:
            self.resize(QSize(target_w, self.height()))
        except Exception:
            pass
        # Update button labels.
        for btn in self._collapsible_buttons:
            try:
                full_text = btn.property("fullText") or btn.text()
                icon_text = btn.property("iconText") or ""
                if collapsed:
                    btn.setText(str(icon_text))
                else:
                    btn.setText(str(full_text))
            except Exception:
                pass

        # Hide title when collapsed (keep window controls).
        if self._title_label is not None:
            self._title_label.setVisible(not collapsed)

        self.adjustSize()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)
    
    def _create_window_button(self, text, callback, is_close=False):
        """Create a minimize or close button for the title bar."""
        btn = QPushButton(text)
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        hover_color = UI_THEME["danger"] if is_close else UI_THEME["surface2"]
        font_size = "20px" if is_close else "18px"
        
        btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {UI_THEME['surface2']};
                color: {UI_THEME['text']};
                border: none;
                border-radius: 8px;
                font-size: {font_size};
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {UI_THEME['surface']};
            }}
            """
        )
        btn.clicked.connect(callback)
        return btn
    
    # NOTE: The previous stacked main-menu + drawer UI has been removed in favor of a
    # single Standard Crosshair primary view.

    def _create_main_menu_page(self) -> QFrame:
        """Create the main menu page."""
        content_frame = QFrame()
        content_frame.setStyleSheet("QFrame { background: transparent; }")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(20, 15, 20, 20)
        # Match the original compact spacing.
        content_layout.setSpacing(22)

        # Crosshair settings button (moved to top)
        standard_btn = self.create_button("⚙️ Crosshair Settings", role="primary")
        standard_btn.clicked.connect(self.open_standard_crosshair_dialog)
        self._register_collapsible_button(standard_btn, "⚙️ Crosshair Settings")
        content_layout.addWidget(standard_btn)
        
        # Visibility toggle buttons
        self.image_toggle_btn = self.create_button(tr_lit("🖼️ Hide Image"), role="neutral")
        self.image_toggle_btn.clicked.connect(self.toggle_image_visibility)
        self._register_collapsible_button(self.image_toggle_btn, tr_lit("🖼️ Hide Image"))
        content_layout.addWidget(self.image_toggle_btn)

        self.crosshair_toggle_btn = self.create_button(tr_lit("🎯 Show Crosshair"), role="neutral")
        self.crosshair_toggle_btn.clicked.connect(self.toggle_crosshair_visibility)
        self._register_collapsible_button(self.crosshair_toggle_btn, tr_lit("🎯 Show Crosshair"))
        content_layout.addWidget(self.crosshair_toggle_btn)
        self._update_image_toggle_text()
        self._update_crosshair_toggle_text()

        # Standard crosshair preset/profile picker
        self._preset_container = QFrame()
        self._preset_container.setStyleSheet(
            f"""
            QFrame {{
                background-color: {UI_THEME['surface']};
                border-radius: 14px;
                border: 1px solid {UI_THEME['border']};
            }}
            """
        )
        preset_layout = QHBoxLayout(self._preset_container)
        preset_layout.setContentsMargins(14, 14, 14, 14)
        preset_layout.setSpacing(12)

        preset_label = QLabel(tr_lit("Preset"))
        preset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preset_label.setFixedHeight(38)
        preset_label.setStyleSheet(
            f"""
            QLabel {{
                color: {UI_THEME['muted']};
                font-size: 12px;
                background-color: {UI_THEME['surface2']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 12px;
                padding-top: 0px;
                padding-bottom: 0px;
                padding-left: 12px;
                padding-right: 12px;
                min-width: 72px;
            }}
            """
        )

        self.crosshair_preset_combo = QComboBox()
        self.crosshair_preset_combo.setFixedHeight(38)
        self.crosshair_preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.crosshair_preset_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.crosshair_preset_combo.setStyleSheet(
            f"""
            QComboBox {{
                background-color: {UI_THEME['surface2']};
                color: {UI_THEME['text']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 12px;
                padding-top: 0px;
                padding-bottom: 0px;
                padding-left: 12px;
                padding-right: 12px;
                font-size: 12px;
            }}
            QComboBox:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background-color: {UI_THEME['surface']};
                color: {UI_THEME['text']};
                selection-background-color: {UI_THEME['accent']};
                selection-color: white;
                border: 1px solid {UI_THEME['border']};
                outline: none;
            }}
            """
        )
        self.crosshair_preset_combo.currentTextChanged.connect(self._on_crosshair_preset_selected)

        # Instrument combo popup to log show/hide events for debugging teleport
        try:
            orig_show = self.crosshair_preset_combo.showPopup
            def _logged_show():
                try:
                    log_path = Path(__file__).resolve().with_name("move_debug.log")
                except Exception:
                    log_path = Path("move_debug.log")
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"\n--- Combo showPopup at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    for line in traceback.format_stack():
                        fh.write(line)
                    fh.write("--- END ---\n")
                return orig_show()
            self.crosshair_preset_combo.showPopup = _logged_show
        except Exception:
            pass

        preset_layout.setAlignment(preset_label, Qt.AlignmentFlag.AlignVCenter)
        preset_layout.setAlignment(self.crosshair_preset_combo, Qt.AlignmentFlag.AlignVCenter)

        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self.crosshair_preset_combo, 1)
        content_layout.addWidget(self._preset_container)

        # Mirror segmented control (two-half button)
        self._mirror_container = QFrame()
        self._mirror_container.setStyleSheet("QFrame { background: transparent; }")
        mirror_layout = QHBoxLayout(self._mirror_container)
        mirror_layout.setContentsMargins(0, 0, 0, 0)
        mirror_layout.setSpacing(0)

        mirror_v_btn = self._create_segment_button("🔄 Vertical", position="left", role="neutral")
        mirror_v_btn.clicked.connect(
            lambda: mirror_vertical(self.image_label, self.image_label.pixmap())
        )
        mirror_h_btn = self._create_segment_button("Horizontal ↔️", position="right", role="neutral")
        mirror_h_btn.clicked.connect(
            lambda: mirror_horizontal(self.image_label, self.image_label.pixmap())
        )

        mirror_v_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mirror_h_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mirror_layout.addWidget(mirror_v_btn, 1)
        mirror_layout.addWidget(mirror_h_btn, 1)
        self._register_collapsible_button(mirror_v_btn, "🔄 Vertical")
        self._register_collapsible_button(mirror_h_btn, "Horizontal ↔️")
        content_layout.addWidget(self._mirror_container)
        
        # Switch image button
        switch_btn = self.create_button("🖼️ Next Image", role="neutral")
        switch_btn.clicked.connect(self.switch_image)
        self._register_collapsible_button(switch_btn, "🖼️ Next Image")
        content_layout.addWidget(switch_btn)
        
        # Art manager button
        manage_btn = self.create_button("🎨 Art Manager", role="neutral")
        manage_btn.clicked.connect(self.open_image_manager)
        self._register_collapsible_button(manage_btn, "🎨 Art Manager")
        content_layout.addWidget(manage_btn)
        
        # Hotkey manager button
        hotkey_btn = self.create_button("⌨️ Customize Hotkeys", role="neutral")
        hotkey_btn.clicked.connect(self.open_hotkey_manager)
        self._register_collapsible_button(hotkey_btn, "⌨️ Customize Hotkeys")
        content_layout.addWidget(hotkey_btn)
        
        # Opacity section
        self._opacity_container = self._add_opacity_controls(content_layout)
        
        # Separator
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.Shape.HLine)
        self._separator.setStyleSheet(f"background-color: {UI_THEME['border']};")
        self._separator.setMaximumHeight(1)
        content_layout.addWidget(self._separator)
        
        # Hotkey info
        from hotkeys import get_current_hotkeys
        hotkey_text = get_current_hotkeys()
        self._hotkey_info_label = QLabel(f"{hotkey_text}")
        self._hotkey_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hotkey_info_label.setStyleSheet("""
            QLabel {
                color: #BDB6E6;
                font-size: 10px;
                padding: 5px;
                background: transparent;
            }
        """)
        content_layout.addWidget(self._hotkey_info_label)

        self._refresh_crosshair_presets_ui()
        
        return content_frame

    def _create_crosshair_page(self) -> QWidget:
        """Create the embedded Standard Crosshair settings page."""
        page = QWidget()
        page.setStyleSheet("QWidget { background: transparent; }")
        layout = QHBoxLayout(page)
        # Give the settings page some air from the panel borders.
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Collapsible sidebar (hamburger + icon-only buttons when collapsed)
        self._sidebar = QFrame()
        self._sidebar.setObjectName("CrosshairSidebar")
        self._sidebar.setStyleSheet(
            f"""
            QFrame#CrosshairSidebar {{
                background-color: {UI_THEME['surface']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 14px;
            }}
            """
        )

        self._sidebar_collapsed_width = 56
        self._sidebar_expanded_width = 280
        self._sidebar_open = False
        self._sidebar.setMaximumWidth(self._sidebar_collapsed_width)
        self._sidebar.setMinimumWidth(self._sidebar_collapsed_width)

        self._sidebar_anim = QPropertyAnimation(self._sidebar, b"maximumWidth")
        self._sidebar_anim.setDuration(170)
        self._sidebar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(10)

        self._sidebar_menu_btn = QPushButton("≡")
        self._sidebar_menu_btn.setFixedSize(34, 34)
        self._sidebar_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sidebar_menu_btn.setToolTip("Menu")
        self._sidebar_menu_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {UI_THEME['surface2']};
                color: {UI_THEME['text']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 12px;
                font-size: 18px;
                font-weight: 800;
            }}
            QPushButton:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}
            QPushButton:pressed {{ background-color: {UI_THEME['surface']}; }}
            """
        )
        self._sidebar_menu_btn.clicked.connect(self._toggle_drawer)
        sidebar_layout.addWidget(self._sidebar_menu_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._sidebar_buttons: list[QPushButton] = []

        def _apply_sidebar_button_style(btn: QPushButton, icon_only: bool) -> None:
            if btn is None:
                return
            if icon_only:
                btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {UI_THEME['surface2']};
                        color: {UI_THEME['text']};
                        border: 1px solid {UI_THEME['border']};
                        border-radius: 14px;
                        padding: 0px;
                        min-height: 44px;
                        font-size: 18px;
                        font-weight: 800;
                        text-align: center;
                    }}
                    QPushButton:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}
                    QPushButton:pressed {{ background-color: {UI_THEME['surface']}; }}
                    """
                )
            else:
                # Fall back to standard button styling.
                btn.setStyleSheet(self.create_button("tmp").styleSheet())
                btn.setText(btn.property("fullText") or btn.text())

        def _mk_sidebar_btn(text: str, callback) -> QPushButton:
            btn = self.create_button(text, role="neutral")
            btn.clicked.connect(callback)
            # reuse same icon-text behavior as main menu collapse
            self._register_collapsible_button(btn, text)
            self._sidebar_buttons.append(btn)
            return btn

        # Preset/profile icon button shown only when collapsed.
        self._drawer_preset_icon_btn = QPushButton("👤")
        self._drawer_preset_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_preset_icon_btn.setToolTip(tr_lit("Preset"))
        self._drawer_preset_icon_btn.clicked.connect(self._toggle_drawer)
        _apply_sidebar_button_style(self._drawer_preset_icon_btn, True)
        sidebar_layout.addWidget(self._drawer_preset_icon_btn)

        self._drawer_image_toggle_btn = _mk_sidebar_btn(tr_lit("🖼️ Hide Image"), self.toggle_image_visibility)
        self._drawer_crosshair_toggle_btn = _mk_sidebar_btn(tr_lit("🎯 Show Crosshair"), self.toggle_crosshair_visibility)

        self._sidebar_preset_frame = QFrame()
        self._sidebar_preset_frame.setStyleSheet(
            f"""
            QFrame {{
                background-color: {UI_THEME['surface2']};
                border-radius: 12px;
                border: 1px solid {UI_THEME['border']};
            }}
            """
        )
        preset_layout = QHBoxLayout(self._sidebar_preset_frame)
        preset_layout.setContentsMargins(10, 8, 10, 8)
        preset_layout.setSpacing(8)

        preset_label = QLabel(tr_lit("Preset"))
        preset_label.setStyleSheet(f"color: {UI_THEME['muted']}; font-size: 12px; background: transparent; min-width: 46px;")
        self._drawer_preset_combo = QComboBox()
        self._drawer_preset_combo.setFixedHeight(28)
        self._drawer_preset_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_preset_combo.setStyleSheet(
            f"""
            QComboBox {{
                background-color: {UI_THEME['surface']};
                color: {UI_THEME['text']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 10px;
                padding: 3px 8px;
                font-size: 12px;
            }}
            QComboBox:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background-color: {UI_THEME['surface']};
                color: {UI_THEME['text']};
                selection-background-color: {UI_THEME['accent']};
                selection-color: white;
                border: 1px solid {UI_THEME['border']};
                outline: none;
            }}
            """
        )
        self._drawer_preset_combo.currentTextChanged.connect(self._on_crosshair_preset_selected)
        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self._drawer_preset_combo, 1)
        sidebar_layout.addWidget(self._sidebar_preset_frame)

        # Mirror controls (available from the sidebar; opacity is intentionally omitted here).
        # When the drawer is collapsed, the segmented control becomes too narrow to show text,
        # so we also provide two icon-only buttons for the collapsed state.
        self._drawer_mirror_frame = QFrame()
        self._drawer_mirror_frame.setStyleSheet("QFrame { background: transparent; }")
        mirror_layout = QHBoxLayout(self._drawer_mirror_frame)
        mirror_layout.setContentsMargins(0, 0, 0, 0)
        mirror_layout.setSpacing(0)

        drawer_mirror_v = self._create_segment_button("🔄 Vertical", position="left", role="neutral")
        drawer_mirror_h = self._create_segment_button("↔️ Horizontal", position="right", role="neutral")
        drawer_mirror_v.clicked.connect(lambda: mirror_vertical(self.image_label, self.image_label.pixmap()))
        drawer_mirror_h.clicked.connect(lambda: mirror_horizontal(self.image_label, self.image_label.pixmap()))
        drawer_mirror_v.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        drawer_mirror_h.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mirror_layout.addWidget(drawer_mirror_v, 1)
        mirror_layout.addWidget(drawer_mirror_h, 1)
        self._register_collapsible_button(drawer_mirror_v, "🔄 Vertical")
        self._register_collapsible_button(drawer_mirror_h, "↔️ Horizontal")
        sidebar_layout.addWidget(self._drawer_mirror_frame)

        self._drawer_mirror_icon_v = QPushButton("🔄")
        self._drawer_mirror_icon_h = QPushButton("↔️")
        for btn, tip, cb in (
            (self._drawer_mirror_icon_v, "Mirror Vertical", lambda: mirror_vertical(self.image_label, self.image_label.pixmap())),
            (self._drawer_mirror_icon_h, "Mirror Horizontal", lambda: mirror_horizontal(self.image_label, self.image_label.pixmap())),
        ):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.clicked.connect(cb)
            _apply_sidebar_button_style(btn, True)
            sidebar_layout.addWidget(btn)

        sidebar_layout.addWidget(_mk_sidebar_btn("🖼️ Next Image", self.switch_image))
        sidebar_layout.addWidget(_mk_sidebar_btn("🎨 Art Manager", self.open_image_manager))
        sidebar_layout.addWidget(_mk_sidebar_btn("⌨️ Customize Hotkeys", self.open_hotkey_manager))
        sidebar_layout.addStretch(1)

        self.crosshair_dialog = StandardCrosshairDialog(
            self.crosshair_label,
            self,
            embedded=True,
            on_request_close=self._show_main_menu,
        )
        self.crosshair_dialog.visibility_changed.connect(self._on_crosshair_dialog_visibility)
        if hasattr(self.crosshair_dialog, "presets_changed"):
            self.crosshair_dialog.presets_changed.connect(self._refresh_crosshair_presets_ui)

        # Start sidebar collapsed (icons only).
        try:
            self._sidebar_open = False
            self._sidebar_preset_frame.setVisible(False)
            if self._drawer_preset_icon_btn is not None:
                self._drawer_preset_icon_btn.setVisible(True)

            # Collapsed drawer: show icon-only mirror buttons and hide the segmented control.
            if getattr(self, "_drawer_mirror_frame", None) is not None:
                self._drawer_mirror_frame.setVisible(False)
            if getattr(self, "_drawer_mirror_icon_v", None) is not None:
                self._drawer_mirror_icon_v.setVisible(True)
            if getattr(self, "_drawer_mirror_icon_h", None) is not None:
                self._drawer_mirror_icon_h.setVisible(True)

            for btn in self._sidebar_buttons:
                full_text = btn.property("fullText") or btn.text()
                icon_text = btn.property("iconText") or ""
                btn.setText(str(icon_text) if icon_text else str(full_text))
                _apply_sidebar_button_style(btn, True)
        except Exception:
            pass

        layout.addWidget(self._sidebar)
        layout.addWidget(self.crosshair_dialog, 1)
        return page

    def _toggle_drawer(self) -> None:
        if getattr(self, "_sidebar", None) is None:
            return

        # Sync sidebar controls with current state.
        self._update_image_toggle_text()
        self._update_crosshair_toggle_text()
        try:
            self._refresh_crosshair_presets_ui()
        except Exception:
            pass

        self._sidebar_open = not bool(getattr(self, "_sidebar_open", False))
        target = int(self._sidebar_expanded_width if self._sidebar_open else self._sidebar_collapsed_width)
        try:
            if getattr(self, "_sidebar_preset_frame", None) is not None:
                self._sidebar_preset_frame.setVisible(bool(self._sidebar_open))
            if getattr(self, "_drawer_preset_icon_btn", None) is not None:
                self._drawer_preset_icon_btn.setVisible(not bool(self._sidebar_open))

            # Mirror controls: segmented when expanded, icon-only when collapsed.
            if getattr(self, "_drawer_mirror_frame", None) is not None:
                self._drawer_mirror_frame.setVisible(bool(self._sidebar_open))
            if getattr(self, "_drawer_mirror_icon_v", None) is not None:
                self._drawer_mirror_icon_v.setVisible(not bool(self._sidebar_open))
            if getattr(self, "_drawer_mirror_icon_h", None) is not None:
                self._drawer_mirror_icon_h.setVisible(not bool(self._sidebar_open))
        except Exception:
            pass

        # Update button text (icons only when collapsed).
        try:
            for btn in getattr(self, "_sidebar_buttons", []) or []:
                full_text = btn.property("fullText") or btn.text()
                icon_text = btn.property("iconText") or ""
                btn.setText(str(full_text) if self._sidebar_open else (str(icon_text) if icon_text else str(full_text)))
                if self._sidebar_open:
                    # Restore normal styling
                    btn.setStyleSheet(self.create_button("tmp").styleSheet())
                else:
                    btn.setStyleSheet(
                        f"""
                        QPushButton {{
                            background-color: {UI_THEME['surface2']};
                            color: {UI_THEME['text']};
                            border: 1px solid {UI_THEME['border']};
                            border-radius: 14px;
                            padding: 0px;
                            min-height: 44px;
                            font-size: 18px;
                            font-weight: 800;
                            text-align: center;
                        }}
                        QPushButton:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}
                        QPushButton:pressed {{ background-color: {UI_THEME['surface']}; }}
                        """
                    )
        except Exception:
            pass

        try:
            self._sidebar_anim.stop()
            self._sidebar_anim.setStartValue(self._sidebar.maximumWidth())
            self._sidebar_anim.setEndValue(target)
            self._sidebar_anim.start()
        except Exception:
            self._sidebar.setMaximumWidth(target)

    def _show_main_menu(self) -> None:
        if self._stack is not None and self._page_main is not None:
            self._stack.setCurrentWidget(self._page_main)
        # If we came from another page, keep behavior consistent.
        self.set_collapsed(False)
        self._set_title_mode("main")
        try:
            self._programmatic_resize = True
            self.resize(self._main_size)
        except Exception:
            pass
        finally:
            self._programmatic_resize = False

    def _show_crosshair_settings(self) -> None:
        # Ensure crosshair page uses the larger window size.
        self._collapsed = False
        if self.crosshair_dialog is not None:
            self.crosshair_dialog.sync_with_label()
        if self._stack is not None and self._page_crosshair is not None:
            self._stack.setCurrentWidget(self._page_crosshair)
        self._set_title_mode("crosshair")
        try:
            self._programmatic_resize = True
            self.resize(self._crosshair_size)
        except Exception:
            pass
        finally:
            self._programmatic_resize = False

        try:
            if getattr(self, "_sidebar", None) is not None:
                self._sidebar_open = False
                self._sidebar.setMaximumWidth(getattr(self, "_sidebar_collapsed_width", 56))
            if getattr(self, "_sidebar_preset_frame", None) is not None:
                self._sidebar_preset_frame.setVisible(False)
            if getattr(self, "_drawer_preset_icon_btn", None) is not None:
                self._drawer_preset_icon_btn.setVisible(True)
            for btn in getattr(self, "_sidebar_buttons", []) or []:
                full_text = btn.property("fullText") or btn.text()
                icon_text = btn.property("iconText") or ""
                btn.setText(str(icon_text) if icon_text else str(full_text))
                btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background-color: {UI_THEME['surface2']};
                        color: {UI_THEME['text']};
                        border: 1px solid {UI_THEME['border']};
                        border-radius: 14px;
                        padding: 0px;
                        min-height: 44px;
                        font-size: 18px;
                        font-weight: 800;
                        text-align: center;
                    }}
                    QPushButton:hover {{ border: 1px solid {UI_THEME['border_strong']}; }}
                    QPushButton:pressed {{ background-color: {UI_THEME['surface']}; }}
                    """
                )
        except Exception:
            pass

    def _refresh_crosshair_presets_ui(self):
        """Refresh the preset/profile dropdown from persisted settings."""
        try:
            try:
                log_path = Path(__file__).resolve().with_name("move_debug.log")
            except Exception:
                log_path = Path("move_debug.log")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- Refreshing presets at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        except Exception:
            pass
            # Preserve panel position to avoid visual jumps when repopulating
            # combo contents (some platforms may adjust window stacking/geometry).
            try:
                _preserve_pos = self.pos()
            except Exception:
                _preserve_pos = None
            settings = load_settings_from_disk()
            presets = getattr(settings, "presets", {})
            names = list(presets.keys()) if isinstance(presets, dict) else []
            if not names:
                names = ["Default"]

            active = getattr(settings, "active_preset", "Default")
            if active not in names:
                active = names[0]

            combos = []
            if self.crosshair_preset_combo is not None:
                combos.append(self.crosshair_preset_combo)
            if hasattr(self, "_drawer_preset_combo") and self._drawer_preset_combo is not None:
                combos.append(self._drawer_preset_combo)

            for combo in combos:
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(names)
                idx = combo.findText(active)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                combo.blockSignals(False)
            try:
                if _preserve_pos is not None:
                    self.move(_preserve_pos)
            except Exception:
                pass
        except Exception:
            try:
                if self.crosshair_preset_combo is not None:
                    self.crosshair_preset_combo.blockSignals(False)
                if hasattr(self, "_drawer_preset_combo") and self._drawer_preset_combo is not None:
                    self._drawer_preset_combo.blockSignals(False)
            except Exception:
                pass

    def _on_crosshair_preset_selected(self, preset_name: str):
        """Apply the selected preset immediately."""
        preset_name = (preset_name or "").strip()
        if not preset_name:
            return
        try:
            try:
                log_path = Path(__file__).resolve().with_name("move_debug.log")
            except Exception:
                log_path = Path("move_debug.log")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- Preset selected: {preset_name} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        except Exception:
            pass
        try:
            try:
                _preserve_pos = self.pos()
            except Exception:
                _preserve_pos = None
            settings = load_settings_from_disk()
            presets = getattr(settings, "presets", {})
            if not isinstance(presets, dict) or preset_name not in presets:
                return

            settings.active_preset = preset_name
            _apply_preset_dict_to_settings(settings, presets.get(preset_name, {}))
            save_settings_to_disk(settings)

            _bind_settings_to_label(self.crosshair_label, settings)
            _sync_fan_timer_state(self.crosshair_label, settings)
            render_crosshair_on_label(self.crosshair_label, settings)

            self.crosshair_label.setVisible(bool(getattr(settings, "visible", True)))
            if self.crosshair_label.isVisible():
                self.crosshair_label.raise_()
            self._update_crosshair_toggle_text()

            if self.crosshair_dialog is not None:
                self.crosshair_dialog.settings = settings
                self.crosshair_dialog.sync_with_label()
            try:
                if _preserve_pos is not None:
                    self.move(_preserve_pos)
            except Exception:
                pass
        except Exception:
            try:
                if _preserve_pos is not None:
                    self.move(_preserve_pos)
            except Exception:
                pass
            return
    
    def _add_opacity_controls(self, layout):
        """Add opacity slider and label to the layout."""
        wrapper = QFrame()
        wrapper.setStyleSheet("QFrame { background: transparent; }")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        # Keep the label close to the card (global layout spacing is larger).
        wrapper_layout.setSpacing(8)

        # Opacity label
        opacity_label = QLabel(tr_lit("Opacity"))
        opacity_label.setStyleSheet(
            f"""
            QLabel {{
                color: {UI_THEME['muted']};
                font-size: 12px;
                padding: 0px 0;
                background: transparent;
            }}
            """
        )
        wrapper_layout.addWidget(opacity_label)
        
        # Opacity slider container
        opacity_container = QFrame()
        opacity_container.setStyleSheet(
            f"""
            QFrame {{
                background-color: {UI_THEME['surface']};
                border-radius: 14px;
                border: 1px solid {UI_THEME['border']};
            }}
            """
        )
        opacity_layout = QHBoxLayout(opacity_container)
        opacity_layout.setContentsMargins(18, 18, 18, 18)
        opacity_layout.setSpacing(12)

        # Ensure the background card comfortably contains the slider + value pill.
        opacity_container.setMinimumHeight(86)
        
        # Slider
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(0)
        self.opacity_slider.setMaximum(100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setFixedHeight(18)
        self.opacity_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.opacity_slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                border: none;
                height: 6px;
                background: rgba(230, 225, 255, 35);
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {UI_THEME['accent']};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {UI_THEME['accent']};
                border: none;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {UI_THEME.get('accent2', UI_THEME['accent'])};
            }}
            """
        )
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        
        # Value label
        self.opacity_value = QLabel("100%")
        self.opacity_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.opacity_value.setFixedHeight(50)
        self.opacity_value.setMinimumWidth(94)
        self.opacity_value.setStyleSheet(
            f"""
            QLabel {{
                color: {UI_THEME['text']};
                font-size: 13px;
                font-weight: 800;
                background-color: {UI_THEME['surface2']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 16px;
                padding: 0px 16px;
            }}
            """
        )
        
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_value)
        opacity_layout.setAlignment(self.opacity_slider, Qt.AlignmentFlag.AlignVCenter)
        opacity_layout.setAlignment(self.opacity_value, Qt.AlignmentFlag.AlignVCenter)

        wrapper_layout.addWidget(opacity_container)
        layout.addWidget(wrapper)
        return wrapper
    
    def create_button(self, text, role="neutral"):
        """Create a styled button with consistent dark-purple theme."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        role = (role or "neutral").lower()
        if role == "primary":
            bg = UI_THEME["accent"]
            fg = "white"
            border = "none"
        elif role == "danger":
            bg = UI_THEME["danger"]
            fg = "white"
            border = "none"
        else:
            bg = UI_THEME["surface2"]
            fg = UI_THEME["text"]
            border = f"1px solid {UI_THEME['border']}"

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: {border};
                border-radius: 16px;
                padding: 10px 14px;
                font-size: 13px;
                font-weight: 700;
                min-height: 44px;
            }}
            QPushButton:hover {{
                background-color: {self.adjust_color_brightness(bg, 1.08)};
            }}
            QPushButton:pressed {{
                background-color: {self.adjust_color_brightness(bg, 0.92)};
            }}
        """)
        return btn

    def _create_segment_button(self, text: str, position: str, role: str = "neutral") -> QPushButton:
        """Create one segment of a two-part (left/right) control."""
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        role = (role or "neutral").lower()
        if role == "primary":
            bg = UI_THEME["accent"]
            fg = "white"
            border = "none"
        elif role == "danger":
            bg = UI_THEME["danger"]
            fg = "white"
            border = "none"
        else:
            bg = UI_THEME["surface2"]
            fg = UI_THEME["text"]
            border = f"1px solid {UI_THEME['border']}"

        left_radius = "16px" if position == "left" else "0px"
        right_radius = "16px" if position == "right" else "0px"

        # Keep a single 1px divider in the middle.
        extra_border = "border-left: none;" if position == "right" and border != "none" else ""

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: {border};
                {extra_border}
                border-top-left-radius: {left_radius};
                border-bottom-left-radius: {left_radius};
                border-top-right-radius: {right_radius};
                border-bottom-right-radius: {right_radius};
                padding-left: 10px;
                padding-right: 10px;
                padding-top: 1px;
                padding-bottom: 8px;
                font-size: 13px;
                font-weight: 700;
                min-height: 46px;
                min-width: 0px;
            }}
            QPushButton:hover {{
                background-color: {self.adjust_color_brightness(bg, 1.08)};
            }}
            QPushButton:pressed {{
                background-color: {self.adjust_color_brightness(bg, 0.92)};
            }}
        """)
        return btn
    
    def adjust_color_brightness(self, hex_color, factor):
        """Adjust color brightness by a factor."""
        color = QColor(hex_color)
        h, s, v, a = color.getHsv()
        v = min(255, int(v * factor))
        color.setHsv(h, s, v, a)
        return color.name()
    
    def _update_image_toggle_text(self):
        text = tr_lit("🖼️ Hide Image") if self.image_label.isVisible() else tr_lit("🖼️ Show Image")
        if hasattr(self, "image_toggle_btn"):
            try:
                self.image_toggle_btn.setProperty("fullText", text)
                icon = str(text).strip().split(" ", 1)[0] if str(text).strip() else ""
                self.image_toggle_btn.setProperty("iconText", icon)
                self.image_toggle_btn.setText(icon if self._collapsed else text)
            except Exception:
                self.image_toggle_btn.setText(text)
        if hasattr(self, "_drawer_image_toggle_btn") and self._drawer_image_toggle_btn is not None:
            try:
                self._drawer_image_toggle_btn.setProperty("fullText", text)
                icon = str(text).strip().split(" ", 1)[0] if str(text).strip() else ""
                self._drawer_image_toggle_btn.setProperty("iconText", icon)
                # Respect sidebar open/collapsed state.
                if bool(getattr(self, "_sidebar_open", False)):
                    self._drawer_image_toggle_btn.setText(text)
                else:
                    self._drawer_image_toggle_btn.setText(icon if icon else text)
            except Exception:
                pass

    def _update_crosshair_toggle_text(self):
        text = tr_lit("🎯 Hide Crosshair") if self.crosshair_label.isVisible() else tr_lit("🎯 Show Crosshair")
        if hasattr(self, "crosshair_toggle_btn"):
            try:
                self.crosshair_toggle_btn.setProperty("fullText", text)
                icon = str(text).strip().split(" ", 1)[0] if str(text).strip() else ""
                self.crosshair_toggle_btn.setProperty("iconText", icon)
                self.crosshair_toggle_btn.setText(icon if self._collapsed else text)
            except Exception:
                self.crosshair_toggle_btn.setText(text)
        if hasattr(self, "_drawer_crosshair_toggle_btn") and self._drawer_crosshair_toggle_btn is not None:
            try:
                self._drawer_crosshair_toggle_btn.setProperty("fullText", text)
                icon = str(text).strip().split(" ", 1)[0] if str(text).strip() else ""
                self._drawer_crosshair_toggle_btn.setProperty("iconText", icon)
                if bool(getattr(self, "_sidebar_open", False)):
                    self._drawer_crosshair_toggle_btn.setText(text)
                else:
                    self._drawer_crosshair_toggle_btn.setText(icon if icon else text)
            except Exception:
                pass

    def toggle_image_visibility(self):
        """Toggle imported image visibility."""
        # If there are checked items (selection), Show/Hide controls all of them.
        selected = []
        try:
            if self.art_overlay_controller is not None:
                selected = self.art_overlay_controller.enabled_keys()
        except Exception:
            selected = []

        if self.image_label.isVisible():
            # Hide everything.
            try:
                self.image_label.hide()
            except Exception:
                pass
            try:
                if self.art_overlay_controller is not None:
                    self.art_overlay_controller.set_all_visible(False)
            except Exception:
                pass
        else:
            # Show selection overlays if any. If nothing is selected, keep the
            # base label transparent (do NOT auto-select a file), otherwise the
            # user's unchecked state gets overridden when toggling visibility.
            try:
                self.image_label.show()
            except Exception:
                pass

            # Always clear base label when using the overlay pipeline.
            try:
                clear_label_art(self.image_label)
            except Exception:
                pass

            if self.art_overlay_controller is not None:
                # Render whatever is currently checked (may be empty).
                try:
                    self.art_overlay_controller.request_render_selected_atomic(
                        "display_images",
                        visible=True,
                    )
                except Exception:
                    pass
            else:
                # Legacy mode (no overlay controller): keep the old behavior.
                if not selected:
                    try:
                        arts = get_art_list()
                        if arts:
                            if self.current_image_index < 0 or self.current_image_index >= len(arts):
                                self.current_image_index = 0
                            path = arts[self.current_image_index]
                            try:
                                set_label_art_from_path(self.image_label, path)
                            except Exception:
                                try:
                                    pix = QPixmap(path)
                                    self.image_label.setPixmap(pix)
                                except Exception:
                                    pass
                    except Exception:
                        pass

        self._update_image_toggle_text()
        self._sync_action_bar_state()
    
    def toggle_crosshair_visibility(self):
        """Toggle generated crosshair visibility."""
        currently_visible = self.crosshair_label.isVisible()
        if currently_visible:
            self.crosshair_label.hide()
        else:
            self.crosshair_label.show()
            self.crosshair_label.raise_()
        self._update_crosshair_toggle_text()
        save_crosshair_visibility(self.crosshair_label.isVisible())
        if self.crosshair_dialog is not None:
            self.crosshair_dialog.sync_with_label()
        self._sync_action_bar_state()

    def change_opacity(self, value):
        """Change the opacity of the crosshair."""
        opacity = value / 100.0
        transparent(self.image_label, opacity)
        transparent(self.crosshair_label, opacity)
        try:
            if self.art_overlay_controller is not None:
                self.art_overlay_controller.set_global_opacity(opacity)
        except Exception:
            pass
        self.opacity_value.setText(f"{value}%")
        
        # Update check marks in tray menu
        if self.opacity_actions:
            for opacity_val, action in self.opacity_actions.items():
                action.setChecked(value == opacity_val)
    
    def set_opacity(self, value):
        """Set opacity from external source (e.g., tray menu)."""
        self.opacity_slider.setValue(value)
    
    def switch_image(self):
        """Switch to the next crosshair image."""
        # Build cycle list: user-defined order (Art Manager), including combos.
        entries = get_art_cycle_entries("display_images")
        if not entries:
            return

        # Find next entry.
        self.current_image_index = (self.current_image_index + 1) % len(entries)
        entry = entries[self.current_image_index]

        if entry.get("type") == "combo":
            keys = entry.get("keys") or []
            try:
                if self.art_overlay_controller is not None:
                    # Clear base label BEFORE any overlay render/show.
                    clear_label_art(self.image_label)
                    self.art_overlay_controller.set_selection_keys(keys)
                    self.art_overlay_controller.request_render_selected_atomic(
                        "display_images",
                        visible=bool(self.image_label.isVisible()),
                    )
            except Exception:
                pass
            return

        path = str(entry.get("path") or "").strip()
        if not path:
            return
        def _key_for_path(p: str) -> str:
            try:
                root = os.path.dirname(os.path.abspath(__file__))
                return os.path.relpath(os.path.abspath(p), root).replace("\\", "/")
            except Exception:
                return os.path.abspath(p).replace("\\", "/")

        # Prefer overlay pipeline so single-file display is editable like combos.
        if self.art_overlay_controller is not None:
            key = _key_for_path(path)
            try:
                clear_label_art(self.image_label)
                self.art_overlay_controller.set_selection_keys([key])

                def _fallback(_e=None):
                    try:
                        self.art_overlay_controller.clear_selection()
                        self.art_overlay_controller.set_all_visible(False)
                    except Exception:
                        pass
                    try:
                        set_label_art_from_path(self.image_label, path)
                    except Exception:
                        try:
                            pix = QPixmap(path)
                            self.image_label.setPixmap(pix)
                        except Exception:
                            pass

                self.art_overlay_controller.request_render_selected_atomic(
                    "display_images",
                    visible=bool(self.image_label.isVisible()),
                    on_error=_fallback,
                )
                return
            except Exception:
                # Fall through to legacy rendering.
                pass

        # Fallback to legacy rendering into the base label.
        try:
            # Ensure overlay selection doesn't remain visible over the base label.
            if self.art_overlay_controller is not None:
                try:
                    self.art_overlay_controller.clear_selection()
                    self.art_overlay_controller.set_all_visible(False)
                except Exception:
                    pass
            set_label_art_from_path(self.image_label, path)
        except Exception:
            try:
                pix = QPixmap(path)
                self.image_label.setPixmap(pix)
            except Exception:
                pass
    
    def open_image_manager(self):
        """Open the image manager dialog."""
        if self.image_manager is None:
            self.image_manager = ImageManagerDialog(self, overlay_controller=self.art_overlay_controller)
        self.image_manager.show()
        self.image_manager.raise_()
        self.image_manager.activateWindow()
    
    def open_hotkey_manager(self):
        """Open the hotkey manager dialog."""
        if self.hotkey_manager is None:
            self.hotkey_manager = HotkeyManagerDialog(self)
            # Connect signal to refresh control panel when hotkeys are updated
            self.hotkey_manager.hotkeys_updated.connect(self._refresh_hotkey_display)
        self.hotkey_manager.show()
        self.hotkey_manager.raise_()
        self.hotkey_manager.activateWindow()

    def open_standard_crosshair_dialog(self):
        """Open the standard crosshair configuration dialog."""
        # Single-view redesign: already on Standard Crosshair.
        try:
            if self.crosshair_dialog is not None:
                self.crosshair_dialog.sync_with_label()
                self.crosshair_dialog.raise_()
        except Exception:
            pass

    def _on_crosshair_dialog_destroyed(self, *args):
        self.crosshair_dialog = None
        self._refresh_crosshair_presets_ui()

    def _on_crosshair_dialog_visibility(self, visible):
        """Keep control panel toggle text in sync with dialog."""
        self.crosshair_label.setVisible(visible)
        if visible:
            self.crosshair_label.raise_()
        self._update_crosshair_toggle_text()
        save_crosshair_visibility(self.crosshair_label.isVisible())
        self._sync_action_bar_state()
    
    def _refresh_hotkey_display(self, hotkeys):
        """Refresh the hotkey info display after changes."""
        try:
            from hotkeys import get_current_hotkeys
            if self._hotkey_info_label is not None:
                self._hotkey_info_label.setText(get_current_hotkeys())
        except Exception:
            return
    
    def toggle_panel(self):
        """Toggle the control panel visibility."""
        try:
            try:
                log_path = Path(__file__).resolve().with_name("move_debug.log")
            except Exception:
                log_path = Path("move_debug.log")
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- toggle_panel called at {time.strftime('%Y-%m-%d %H:%M:%S')} (is_visible={self.is_visible}) ---\n")
        except Exception:
            pass
        if self.is_visible:
            try:
                self._last_panel_pos = self.pos()
            except Exception:
                pass
            self.hide()
            self.is_visible = False
        else:
            # Preserve last position to avoid shifting when reopening.
            try:
                if self._last_panel_pos is not None:
                    self.move(self._last_panel_pos)
                else:
                    screen = QApplication.primaryScreen().geometry()
                    self.move(screen.width() - self.width() - 20, 20)
            except Exception:
                pass
            self.show()
            self.is_visible = True
    
    def mousePressEvent(self, event):
        """Handle mouse press events for dragging."""
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._hit_test_edges(event.position())
            if edges:
                self._resizing = True
                self._resize_edges = edges
                self._resize_start_pos = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
                event.accept()
                return

            # Drag only from the title bar (prevents accidental moves while
            # interacting with sliders/combos which can feel like "teleporting").
            try:
                if self._title_bar is None:
                    return
                local = event.position().toPoint()
                # Allow dragging from any non-interactive area. If the clicked
                # widget (or any of its parents) is an interactive control
                # (buttons, sliders, combo boxes, scrollbars, list views,
                # size grips), do not start a drag — otherwise allow it.
                child = self.childAt(local)
                if child is not None:
                    widget = child
                    while widget is not None:
                        if isinstance(widget, (QPushButton, QToolButton, QSlider, QComboBox, QSizeGrip, QScrollBar, QAbstractItemView)):
                            return
                        widget = widget.parent()
            except Exception:
                return

            # Defer starting a drag until the mouse has moved beyond the
            # platform's drag threshold to avoid immediate 'teleport' caused
            # by spurious move events on press.
            try:
                self._maybe_drag = True
                self._press_pos = event.globalPosition().toPoint()
                self._drag_offset = None
            except Exception:
                self._maybe_drag = False
                self._press_pos = None
                self._drag_offset = None
            event.accept()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move events for dragging."""
        if self._resizing and self._resize_start_pos is not None and self._resize_start_geom is not None:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geom = self._resize_start_geom
            x = geom.x()
            y = geom.y()
            w = geom.width()
            h = geom.height()

            if "left" in self._resize_edges:
                x = geom.x() + delta.x()
                w = geom.width() - delta.x()
            if "right" in self._resize_edges:
                w = geom.width() + delta.x()
            if "top" in self._resize_edges:
                y = geom.y() + delta.y()
                h = geom.height() - delta.y()
            if "bottom" in self._resize_edges:
                h = geom.height() + delta.y()

            w = max(self.minimumWidth(), w)
            h = max(self.minimumHeight(), h)
            self.setGeometry(x, y, w, h)
            event.accept()
            return

        # Update cursor when hovering near edges.
        if event.buttons() == Qt.MouseButton.NoButton:
            edges = self._hit_test_edges(event.position())
            self.setCursor(self._cursor_for_edges(edges))

        if event.buttons() == Qt.MouseButton.LeftButton:
            # Only begin moving after the user has moved past the drag start
            # threshold. This prevents accidental instant-reposition on clicks.
            try:
                if self._maybe_drag and self._drag_offset is None and self._press_pos is not None:
                    dist = event.globalPosition().toPoint() - self._press_pos
                    thresh = QApplication.startDragDistance()
                    if abs(dist.x()) >= thresh or abs(dist.y()) >= thresh:
                        self._drag_offset = self._press_pos - self.frameGeometry().topLeft()
                        self.drag_position = self._drag_offset
                if self.drag_position is not None:
                    self.move(event.globalPosition().toPoint() - self.drag_position)
                    event.accept()
            except Exception:
                pass

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            self._resize_edges = set()
            self._resize_start_pos = None
            self._resize_start_geom = None
            try:
                self._last_panel_pos = self.pos()
            except Exception:
                pass
            # Clear deferred-drag state
            self._maybe_drag = False
            self._press_pos = None
            self._drag_offset = None
            self.drag_position = None
        super().mouseReleaseEvent(event)
