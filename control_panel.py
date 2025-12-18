"""
Control panel widget for managing crosshair settings.
"""
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
    QStackedWidget,
    QSizeGrip,
    QSizePolicy,
)
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve
from utils import mirror_vertical, mirror_horizontal, get_art_list, transparent, UI_THEME
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
    
    def __init__(self, image_label, crosshair_label, parent=None):
        super().__init__(parent)
        self.image_label = image_label
        self.crosshair_label = crosshair_label
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
        self._main_size = QSize(320, 820)
        self._crosshair_size = QSize(560, 760)
        self._collapse_btn = None
        self._back_btn = None
        self._title_label = None
        self._collapsible_buttons: list[QPushButton] = []
        self._preset_container = None
        self._mirror_container = None
        self._opacity_container = None
        self._separator = None
        self._hotkey_info_label = None

        # Sidebar preset icon (collapsed mode)
        self._drawer_preset_icon_btn = None

        # In-panel navigation
        self._stack = None
        self._page_main = None
        self._page_crosshair = None

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
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Allow manual resizing.
        self.setMinimumSize(280, 520)
        
        # Main container with dark background and rounded edges
        main_frame = self._create_main_frame()
        
        # Layout
        layout = QVBoxLayout(main_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Title bar with buttons
        title_bar = self._create_title_bar()
        layout.addWidget(title_bar)
        
        # Content container (stacked pages)
        self._stack = self._create_content_stack()
        layout.addWidget(self._stack)

        # Resize handle for the frameless panel.
        self._size_grip = QSizeGrip(main_frame)
        self._size_grip.setFixedSize(16, 16)
        self._size_grip.setStyleSheet("QSizeGrip { background: transparent; }")
        
        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(main_frame)

        self.resize(self._main_size)

        # Start on main menu title mode.
        self._set_title_mode("main")

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

        self._title_label = QLabel("Crosshair Control")
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
        is_main = mode == "main"
        try:
            if self._back_btn is not None:
                self._back_btn.setVisible(not is_main)
            if self._title_label is not None:
                self._title_label.setText("Crosshair Control" if is_main else "Standard Crosshair")
                self._title_label.setVisible(True)
        except Exception:
            pass

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
    
    def _create_content_stack(self) -> QStackedWidget:
        """Create stacked pages so navigation happens in one window."""
        stack = QStackedWidget()
        self._page_main = self._create_main_menu_page()
        stack.addWidget(self._page_main)

        self._page_crosshair = self._create_crosshair_page()
        stack.addWidget(self._page_crosshair)

        stack.setCurrentWidget(self._page_main)
        return stack

    def _create_main_menu_page(self) -> QFrame:
        """Create the main menu page."""
        content_frame = QFrame()
        content_frame.setStyleSheet("QFrame { background: transparent; }")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(20, 15, 20, 20)
        # Match the original compact spacing.
        content_layout.setSpacing(22)
        
        # Visibility toggle buttons
        self.image_toggle_btn = self.create_button("🖼️ Hide Image", role="neutral")
        self.image_toggle_btn.clicked.connect(self.toggle_image_visibility)
        self._register_collapsible_button(self.image_toggle_btn, "🖼️ Hide Image")
        content_layout.addWidget(self.image_toggle_btn)

        self.crosshair_toggle_btn = self.create_button("🎯 Show Crosshair", role="neutral")
        self.crosshair_toggle_btn.clicked.connect(self.toggle_crosshair_visibility)
        self._register_collapsible_button(self.crosshair_toggle_btn, "🎯 Show Crosshair")
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
        preset_layout.setContentsMargins(12, 12, 12, 12)
        preset_layout.setSpacing(12)

        preset_label = QLabel("Preset")
        preset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preset_label.setFixedHeight(34)
        preset_label.setStyleSheet(
            f"""
            QLabel {{
                color: {UI_THEME['muted']};
                font-size: 12px;
                background-color: {UI_THEME['surface2']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 12px;
                padding: 6px 10px;
                min-width: 66px;
            }}
            """
        )

        self.crosshair_preset_combo = QComboBox()
        self.crosshair_preset_combo.setFixedHeight(34)
        self.crosshair_preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.crosshair_preset_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.crosshair_preset_combo.setStyleSheet(
            f"""
            QComboBox {{
                background-color: {UI_THEME['surface2']};
                color: {UI_THEME['text']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 12px;
                padding: 4px 10px;
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

        preset_layout.setAlignment(preset_label, Qt.AlignmentFlag.AlignVCenter)
        preset_layout.setAlignment(self.crosshair_preset_combo, Qt.AlignmentFlag.AlignVCenter)

        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self.crosshair_preset_combo, 1)
        content_layout.addWidget(self._preset_container)

        # Standard crosshair button
        standard_btn = self.create_button("🎯 Standard Crosshair", role="primary")
        standard_btn.clicked.connect(self.open_standard_crosshair_dialog)
        self._register_collapsible_button(standard_btn, "🎯 Standard Crosshair")
        content_layout.addWidget(standard_btn)

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
        mirror_h_btn = self._create_segment_button("↔️ Horizontal", position="right", role="neutral")
        mirror_h_btn.clicked.connect(
            lambda: mirror_horizontal(self.image_label, self.image_label.pixmap())
        )

        mirror_v_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mirror_h_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        mirror_layout.addWidget(mirror_v_btn, 1)
        mirror_layout.addWidget(mirror_h_btn, 1)
        self._register_collapsible_button(mirror_v_btn, "🔄 Vertical")
        self._register_collapsible_button(mirror_h_btn, "↔️ Horizontal")
        content_layout.addWidget(self._mirror_container)
        
        # Switch image button
        switch_btn = self.create_button("🖼️ Next Image", role="neutral")
        switch_btn.clicked.connect(self.switch_image)
        self._register_collapsible_button(switch_btn, "🖼️ Next Image")
        content_layout.addWidget(switch_btn)
        
        # Manage images button
        manage_btn = self.create_button("📁 Manage Images", role="neutral")
        manage_btn.clicked.connect(self.open_image_manager)
        self._register_collapsible_button(manage_btn, "📁 Manage Images")
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
        self._drawer_preset_icon_btn.setToolTip("Preset")
        self._drawer_preset_icon_btn.clicked.connect(self._toggle_drawer)
        _apply_sidebar_button_style(self._drawer_preset_icon_btn, True)
        sidebar_layout.addWidget(self._drawer_preset_icon_btn)

        self._drawer_image_toggle_btn = _mk_sidebar_btn("🖼️ Hide Image", self.toggle_image_visibility)
        self._drawer_crosshair_toggle_btn = _mk_sidebar_btn("🎯 Show Crosshair", self.toggle_crosshair_visibility)

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

        preset_label = QLabel("Preset")
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
        mirror_frame = QFrame()
        mirror_frame.setStyleSheet("QFrame { background: transparent; }")
        mirror_layout = QHBoxLayout(mirror_frame)
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
        sidebar_layout.addWidget(mirror_frame)

        sidebar_layout.addWidget(_mk_sidebar_btn("🖼️ Next Image", self.switch_image))
        sidebar_layout.addWidget(_mk_sidebar_btn("📁 Manage Images", self.open_image_manager))
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
        except Exception:
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
        opacity_label = QLabel("Opacity")
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
        opacity_layout.setContentsMargins(14, 14, 14, 14)
        opacity_layout.setSpacing(12)
        
        # Slider
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setMinimum(25)
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
        self.opacity_value.setFixedHeight(44)
        self.opacity_value.setMinimumWidth(82)
        self.opacity_value.setStyleSheet(
            f"""
            QLabel {{
                color: {UI_THEME['text']};
                font-size: 13px;
                font-weight: 800;
                background-color: {UI_THEME['surface2']};
                border: 1px solid {UI_THEME['border']};
                border-radius: 16px;
                padding: 0px 14px;
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
                padding-top: 10px;
                padding-bottom: 14px;
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
        text = "🖼️ Hide Image" if self.image_label.isVisible() else "🖼️ Show Image"
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
        text = "🎯 Hide Crosshair" if self.crosshair_label.isVisible() else "🎯 Show Crosshair"
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
        if self.image_label.isVisible():
            self.image_label.hide()
        else:
            self.image_label.show()
        self._update_image_toggle_text()
    
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

    def change_opacity(self, value):
        """Change the opacity of the crosshair."""
        opacity = value / 100.0
        transparent(self.image_label, opacity)
        transparent(self.crosshair_label, opacity)
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
        # Refresh image list in case new images were added
        self.image_list = get_art_list()
        if not self.image_list:
            return
        self.current_image_index = (self.current_image_index + 1) % len(self.image_list)
        pix = QPixmap(self.image_list[self.current_image_index])
        self.image_label.setPixmap(pix)
    
    def open_image_manager(self):
        """Open the image manager dialog."""
        if self.image_manager is None:
            self.image_manager = ImageManagerDialog(self)
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
        # In-panel navigation: switch to embedded settings page.
        self._show_crosshair_settings()

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
        if self.is_visible:
            self.hide()
            self.is_visible = False
        else:
            # Position near top-right corner
            screen = QApplication.primaryScreen().geometry()
            self.move(screen.width() - self.width() - 20, 20)
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

            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
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

        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._resizing = False
            self._resize_edges = set()
            self._resize_start_pos = None
            self._resize_start_geom = None
        super().mouseReleaseEvent(event)
