"""
System tray icon management for the crosshair application.
"""
import json
from PyQt6.QtWidgets import (
    QSystemTrayIcon,
    QMenu,
    QApplication,
    QMessageBox,
)
from PyQt6.QtGui import QIcon, QAction


def create_tray_icon(app, label, control_panel, controller=None, icon_path="astra_yao_tray.png"):
    # КРИТИЧНО: приложение не должно закрываться при закрытии всех окон
    QApplication.setQuitOnLastWindowClosed(False)

    tray_icon = QSystemTrayIcon(QIcon(icon_path), parent=app)
    tray_icon.setToolTip("Crosshair App")

    # Левый / двойной клик по иконке
    def on_tray_activated(reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            control_panel.toggle_panel()

    tray_icon.activated.connect(on_tray_activated)

    tray_menu = _create_tray_menu(label, control_panel, controller, app, tray_icon)
    tray_icon.setContextMenu(tray_menu)

    tray_icon.show()
    return tray_icon


def _create_tray_menu(label, control_panel, controller, app, tray_icon):
    tray_menu = QMenu()

    try:
        from utils import APP_SETTINGS_PATH
    except ImportError:
        APP_SETTINGS_PATH = "app_settings.json"

    # ---------- settings helpers ----------

    def load_settings():
        try:
            with open(APP_SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_settings(data):
        try:
            with open(APP_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    settings = load_settings()

    # ---------- UI visibility control ----------

    def apply_autostart_state(enabled: bool):
        if enabled:
            label.hide()
            if hasattr(control_panel, "crosshair_label"):
                control_panel.crosshair_label.hide()
            control_panel.hide()
        else:
            label.show()
            if hasattr(control_panel, "crosshair_label"):
                control_panel.crosshair_label.show()

        # Keep control panel toggle buttons in sync with actual visibility.
        try:
            if hasattr(control_panel, "_update_image_toggle_text"):
                control_panel._update_image_toggle_text()
            if hasattr(control_panel, "_update_crosshair_toggle_text"):
                control_panel._update_crosshair_toggle_text()
            if hasattr(control_panel, "_sync_action_bar_state"):
                control_panel._sync_action_bar_state()
        except Exception:
            pass

    # 🔥 КЛЮЧЕВО: применяем состояние СРАЗУ при создании tray
    apply_autostart_state(settings.get("autostart_enabled", False))

    # ---------- Open Settings ----------

    open_settings_action = QAction("Open Settings", tray_menu)
    open_settings_action.triggered.connect(control_panel.toggle_panel)
    tray_menu.addAction(open_settings_action)

    # ---------- Autostart ----------

    autostart_action = QAction("Start on System Launch", tray_menu)
    autostart_action.setCheckable(True)
    autostart_action.setChecked(settings.get("autostart_enabled", False))

    def on_autostart_toggled(checked):
        s = load_settings()
        s["autostart_enabled"] = checked
        save_settings(s)
        apply_autostart_state(checked)

    autostart_action.toggled.connect(on_autostart_toggled)
    tray_menu.addAction(autostart_action)

    # ---------- Hotkeys ----------

    hotkeys_action = QAction("Enable Hotkeys", tray_menu)
    hotkeys_action.setCheckable(True)
    hotkeys_action.setChecked(settings.get("hotkeys_enabled", True))

    def on_hotkeys_toggled(checked):
        s = load_settings()
        s["hotkeys_enabled"] = checked
        save_settings(s)
        try:
            from hotkeys import pause_hotkeys, resume_hotkeys
            if checked:
                resume_hotkeys()
            else:
                pause_hotkeys()
        except Exception:
            pass

    hotkeys_action.toggled.connect(on_hotkeys_toggled)
    tray_menu.addAction(hotkeys_action)

    # ---------- Hide / Show UI ----------

    hide_ui_action = QAction(tray_menu)

    def is_ui_visible():
        return (
            label.isVisible()
            or (hasattr(control_panel, "crosshair_label") and control_panel.crosshair_label.isVisible())
            or control_panel.isVisible()
        )

    def update_hide_ui_text():
        hide_ui_action.setText("Hide UI" if is_ui_visible() else "Show UI")

    def toggle_ui():
        if is_ui_visible():
            label.hide()
            if hasattr(control_panel, "crosshair_label"):
                control_panel.crosshair_label.hide()
            control_panel.hide()
        else:
            label.show()
            if hasattr(control_panel, "crosshair_label"):
                control_panel.crosshair_label.show()
            control_panel.show()
        update_hide_ui_text()

    update_hide_ui_text()
    hide_ui_action.triggered.connect(toggle_ui)
    tray_menu.addAction(hide_ui_action)

    # ---------- Quick Toggle ----------

    if controller is not None and hasattr(controller, "toggle_app_enabled"):
        quick_toggle_action = QAction(tray_menu)

        def update_quick_toggle_text():
            enabled = getattr(controller, "app_enabled", True)
            quick_toggle_action.setText("Disable App" if enabled else "Enable App")

        def quick_toggle():
            controller.toggle_app_enabled()
            update_quick_toggle_text()

        update_quick_toggle_text()
        quick_toggle_action.triggered.connect(quick_toggle)
        tray_menu.addAction(quick_toggle_action)

    tray_menu.addSeparator()

    # ---------- Restart ----------

    if controller is not None and hasattr(controller, "restart_app"):
        restart_action = QAction("Restart App", tray_menu)
        restart_action.triggered.connect(controller.restart_app)
        tray_menu.addAction(restart_action)

    # ---------- Exit ----------

    def exit_app():
        busy = False
        if controller is not None:
            busy = getattr(controller, "current_state", None) == "active"

        if busy:
            reply = QMessageBox.question(
                None,
                "Exit App",
                "The app is currently active. Exit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        app.quit()

    exit_action = QAction("Exit App", tray_menu)
    exit_action.triggered.connect(exit_app)
    tray_menu.addAction(exit_action)

    return tray_menu
