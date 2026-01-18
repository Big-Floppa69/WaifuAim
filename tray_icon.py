"""
System tray icon management for the crosshair application.
"""
from PyQt6.QtWidgets import (
    QSystemTrayIcon,
    QMenu,
    QApplication,
    QMessageBox,
)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QUrl, QTimer

import threading

from utils import APP_VERSION, get_app_config_dir, get_app_config_path, tr_lit, read_app_settings, update_app_settings, is_windows_autostart_enabled, set_windows_autostart

# GitHub repo used for update checks
_GITHUB_OWNER = "Big-Floppa69"
_GITHUB_REPO = "WaifuAim"


def create_tray_icon(app, label, control_panel, controller=None, icon_path="astra_yao_tray.png"):
    # КРИТИЧНО: приложение не должно закрываться при закрытии всех окон
    QApplication.setQuitOnLastWindowClosed(False)

    tray_icon = QSystemTrayIcon(QIcon(icon_path), parent=app)
    tray_icon.setToolTip(f"WaifuAim v{APP_VERSION}")

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

    # ---------- settings helpers (AppData) ----------

    def load_settings() -> dict:
        try:
            return read_app_settings() or {}
        except Exception:
            return {}

    def save_settings_patch(patch: dict) -> dict:
        try:
            return update_app_settings(patch)
        except Exception:
            return {}

    settings = load_settings()

    # Ensure defaults exist (so toggles always have a source of truth in JSON).
    # User request: autostart default ON.
    try:
        patch = {}
        if "autostart_enabled" not in settings:
            patch["autostart_enabled"] = True
            settings["autostart_enabled"] = True
        if "hotkeys_enabled" not in settings:
            patch["hotkeys_enabled"] = True
            settings["hotkeys_enabled"] = True
        if patch:
            save_settings_patch(patch)
    except Exception:
        pass

    # ---------- Open Settings ----------

    open_settings_action = QAction("Open Settings", tray_menu)
    open_settings_action.triggered.connect(control_panel.toggle_panel)
    tray_menu.addAction(open_settings_action)

    open_settings_file_action = QAction("Open Settings File", tray_menu)

    def _open_settings_file():
        try:
            from PyQt6.QtGui import QDesktopServices
            p = get_app_config_path("app_settings.json")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception:
            pass

    open_settings_file_action.triggered.connect(_open_settings_file)
    tray_menu.addAction(open_settings_file_action)

    open_config_folder_action = QAction("Open Config Folder", tray_menu)

    def _open_config_folder():
        try:
            from PyQt6.QtGui import QDesktopServices
            p = get_app_config_dir()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception:
            pass

    open_config_folder_action.triggered.connect(_open_config_folder)
    tray_menu.addAction(open_config_folder_action)

    # ---------- Updates ----------

    updates_action = QAction("Check for Updates", tray_menu)

    update_state = {
        "checked": False,
        "available": False,
        "latest_version": None,
        "latest_url": None,
        "asset_name": None,
        "asset_url": None,
        "error": None,
    }

    def _set_updates_action_label() -> None:
        base = "Check for Updates"
        if bool(update_state.get("available")):
            base = f"{base}  ↑"
        try:
            updates_action.setText(base)
        except Exception:
            pass

    def _run_update_check(*, interactive: bool) -> None:
        def worker():
            try:
                from updates import get_latest_github_release, is_newer_version

                rel = get_latest_github_release(_GITHUB_OWNER, _GITHUB_REPO)
                update_state["checked"] = True
                if rel is None:
                    update_state["available"] = False
                    update_state["error"] = "No release info"
                else:
                    update_state["latest_version"] = rel.version
                    update_state["latest_url"] = rel.html_url
                    update_state["asset_name"] = rel.asset_name
                    update_state["asset_url"] = rel.asset_url
                    update_state["available"] = bool(is_newer_version(rel.version, str(APP_VERSION)))
                    update_state["error"] = None
            except Exception as e:
                update_state["checked"] = True
                update_state["available"] = False
                update_state["error"] = str(e)

            def on_done():
                _set_updates_action_label()

                if not interactive:
                    return

                if not update_state.get("checked"):
                    return

                if update_state.get("available"):
                    latest = str(update_state.get("latest_version") or "").strip() or "?"
                    url = str(update_state.get("latest_url") or "").strip()
                    asset_url = str(update_state.get("asset_url") or "").strip()
                    asset_name = str(update_state.get("asset_name") or "").strip()

                    text = (
                        f"A new version is available.\n\n"
                        f"Current: {APP_VERSION}\n"
                        f"Latest:  {latest}\n\n"
                        f"Update now?"
                    )

                    box = QMessageBox(tray_menu)
                    box.setWindowTitle("WaifuAim")
                    box.setText(text)
                    btn_download = None
                    if asset_url and asset_name.lower().endswith(".exe"):
                        btn_download = box.addButton("Download && Install", QMessageBox.ButtonRole.AcceptRole)
                    btn_open = box.addButton("Open GitHub", QMessageBox.ButtonRole.ActionRole)
                    btn_later = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
                    box.setDefaultButton(btn_later)
                    box.exec()
                    clicked = box.clickedButton()

                    if clicked == btn_open and url:
                        try:
                            from PyQt6.QtGui import QDesktopServices
                            QDesktopServices.openUrl(QUrl(url))
                        except Exception:
                            pass

                    if btn_download is not None and clicked == btn_download and asset_url:
                        try:
                            from updates import download_file, launch_installer

                            QMessageBox.information(
                                tray_menu,
                                "WaifuAim",
                                "Downloading the installer...\n\n"
                                "Your browser may also prompt you depending on Windows security settings.",
                            )
                            path = download_file(asset_url, filename=asset_name)
                            ok = launch_installer(path)
                            if not ok:
                                QMessageBox.warning(
                                    tray_menu,
                                    "WaifuAim",
                                    "Download completed, but the installer could not be launched automatically.\n"
                                    f"File: {path}",
                                )
                        except Exception as e:
                            QMessageBox.warning(
                                tray_menu,
                                "WaifuAim",
                                f"Update failed: {e}",
                            )
                else:
                    # Up to date or error
                    err = str(update_state.get("error") or "").strip()
                    if err:
                        QMessageBox.information(
                            tray_menu,
                            "WaifuAim",
                            "Could not check for updates right now.\n\n"
                            f"Reason: {err}",
                        )
                    else:
                        QMessageBox.information(
                            tray_menu,
                            "WaifuAim",
                            f"You're up to date.\n\nCurrent version: {APP_VERSION}",
                        )

            try:
                QTimer.singleShot(0, on_done)
            except Exception:
                pass

        try:
            t = threading.Thread(target=worker, daemon=True)
            t.start()
        except Exception:
            if interactive:
                QMessageBox.information(tray_menu, "WaifuAim", "Could not start update check thread.")

    def on_updates_clicked():
        _run_update_check(interactive=True)

    updates_action.triggered.connect(on_updates_clicked)
    tray_menu.addAction(updates_action)

    # Automatic update check on every app start (non-blocking)
    _run_update_check(interactive=False)

    about_action = QAction(f"About v{APP_VERSION}", tray_menu)

    def _show_about():
        try:
            cfg = str(get_app_config_dir())
            s = str(get_app_config_path("app_settings.json"))
            hk = str(get_app_config_path("hotkey_config.json"))
            QMessageBox.information(
                tray_menu,
                "WaifuAim",
                f"Version: {APP_VERSION}\n\nConfig dir:\n{cfg}\n\nSettings:\n{s}\n\nHotkeys:\n{hk}\n\nTray state (loaded):\n"
                f"autostart_enabled={bool(settings.get('autostart_enabled', False))}\n"
                f"hotkeys_enabled={bool(settings.get('hotkeys_enabled', True))}",
            )
        except Exception:
            pass

    about_action.triggered.connect(_show_about)
    tray_menu.addAction(about_action)

    # ---------- Autostart ----------

    autostart_action = QAction("Start on System Launch", tray_menu)
    autostart_action.setCheckable(True)
    autostart_action.setChecked(bool(settings.get("autostart_enabled", False)))

    def on_autostart_toggled(checked):
        checked = bool(checked)

        # Best effort: try to apply the requested state to the registry.
        try:
            set_windows_autostart(checked)
        except Exception:
            pass

        # Persist the *actual* state after the attempt.
        actual = checked
        try:
            actual = bool(is_windows_autostart_enabled())
        except Exception:
            actual = checked

        save_settings_patch({"autostart_enabled": actual})

        # If registry didn't match the requested state, revert the checkmark.
        if actual != checked:
            try:
                autostart_action.blockSignals(True)
                autostart_action.setChecked(actual)
            finally:
                try:
                    autostart_action.blockSignals(False)
                except Exception:
                    pass

        # Verify persistence (installed builds can run under odd contexts).
        try:
            cur = bool((read_app_settings() or {}).get("autostart_enabled", False))
            if cur != actual:
                QMessageBox.warning(
                    tray_menu,
                    "WaifuAim",
                    "Failed to save 'Start on System Launch' setting.\n"
                    "This usually means the config folder is not writable or another instance overwrote settings.",
                )
        except Exception:
            pass

    autostart_action.toggled.connect(on_autostart_toggled)
    tray_menu.addAction(autostart_action)

    # ---------- Hotkeys ----------

    hotkeys_action = QAction(tr_lit("Enable Hotkeys"), tray_menu)
    hotkeys_action.setCheckable(True)
    hotkeys_action.setChecked(settings.get("hotkeys_enabled", True))

    def on_hotkeys_toggled(checked):
        desired = bool(checked)
        save_settings_patch({"hotkeys_enabled": desired})

        # Verify persistence.
        try:
            cur = bool((read_app_settings() or {}).get("hotkeys_enabled", True))
            if cur != desired:
                QMessageBox.warning(
                    tray_menu,
                    "WaifuAim",
                    "Failed to save 'Enable Hotkeys' setting.\n"
                    "This usually means the config folder is not writable or another instance overwrote settings.",
                )
        except Exception:
            pass
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
        hide_ui_action.setText(tr_lit("Hide UI") if is_ui_visible() else tr_lit("Show UI"))

    def toggle_ui():
        if is_ui_visible():
            label.hide()
            if hasattr(control_panel, "crosshair_label"):
                control_panel.crosshair_label.hide()
            try:
                if hasattr(control_panel, "art_overlay_controller") and control_panel.art_overlay_controller is not None:
                    control_panel.art_overlay_controller.set_all_visible(False)
            except Exception:
                pass
            control_panel.hide()
        else:
            label.show()
            if hasattr(control_panel, "crosshair_label"):
                control_panel.crosshair_label.show()
            try:
                if hasattr(control_panel, "art_overlay_controller") and control_panel.art_overlay_controller is not None:
                    control_panel.art_overlay_controller.set_all_visible(True)
            except Exception:
                pass
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
            quick_toggle_action.setText(tr_lit("Disable App") if enabled else tr_lit("Enable App"))

        def quick_toggle():
            controller.toggle_app_enabled()
            update_quick_toggle_text()

        update_quick_toggle_text()
        quick_toggle_action.triggered.connect(quick_toggle)
        tray_menu.addAction(quick_toggle_action)

    tray_menu.addSeparator()

    # ---------- Restart ----------

    if controller is not None and hasattr(controller, "restart_app"):
        restart_action = QAction(tr_lit("Restart App"), tray_menu)
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
                tr_lit("Exit App"),
                tr_lit("The app is currently active. Exit anyway?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        app.quit()

    exit_action = QAction(tr_lit("Exit App"), tray_menu)
    exit_action.triggered.connect(exit_app)
    tray_menu.addAction(exit_action)

    return tray_menu
