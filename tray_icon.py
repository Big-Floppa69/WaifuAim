"""
System tray icon management for the crosshair application.
"""
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QAction
from utils import mirror_vertical, mirror_horizontal


def create_tray_icon(app, label, control_panel, icon_path="astra_yao_tray.png"):
    """Create and configure the system tray icon with menu."""
    tray_icon = QSystemTrayIcon(QIcon(icon_path), parent=app)
    
    # Single click on tray icon to toggle control panel
    tray_icon.activated.connect(
        lambda reason: control_panel.toggle_panel() 
        if reason == QSystemTrayIcon.ActivationReason.Trigger 
        else None
    )
    
    # Create context menu
    tray_menu = _create_tray_menu(label, control_panel)
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()
    
    return tray_icon


def _create_tray_menu(label, control_panel):
    """Create the context menu for the tray icon."""
    tray_menu = QMenu()
    
    # Exit action
    exit_action = QAction("Exit")
    exit_action.triggered.connect(QApplication.quit)
    
    # Hide action
    hide_action = QAction('Hide')
    hide_action.triggered.connect(label.hide)
    
    # Show action
    show_action = QAction('Show')
    show_action.triggered.connect(label.show)
    
    # Mirror Vertical action
    mirror_v_action = QAction('Mirror Vertical')
    mirror_v_action.triggered.connect(lambda: mirror_vertical(label, label.pixmap()))
    
    # Mirror Horizontal action
    mirror_h_action = QAction('Mirror Horizontal')
    mirror_h_action.triggered.connect(lambda: mirror_horizontal(label, label.pixmap()))
    
    # Transparent submenu
    transparent_action = _create_transparency_menu(control_panel)
    
    # Add actions to menu
    tray_menu.addAction(hide_action)
    tray_menu.addAction(show_action)
    tray_menu.addAction(mirror_v_action)
    tray_menu.addAction(mirror_h_action)
    tray_menu.addMenu(transparent_action)
    tray_menu.addAction(exit_action)
    
    return tray_menu


def _create_transparency_menu(control_panel):
    """Create the transparency submenu with checkable options."""
    transparent_action = QMenu('Transparent')
    
    # Create opacity actions
    opacity_levels = [100, 75, 50, 25]
    
    for opacity in opacity_levels:
        action = QAction(f'{opacity}%')
        action.setCheckable(True)
        action.setChecked(opacity == 100)  # Default to 100%
        action.triggered.connect(lambda checked, o=opacity: control_panel.set_opacity(o))
        transparent_action.addAction(action)
        
        # Store reference in control panel for synchronization
        control_panel.opacity_actions[opacity] = action
    
    return transparent_action
