# Copilot Instructions for Zenless Zone Zero Crosshair

## Architecture Overview

This PyQt6 overlay application renders customizable game crosshairs with two rendering pipelines:

- **Image-based**: User-supplied PNG overlays from `display_images/` (switched via F2)
- **Generated**: Procedural crosshair built from lines, circles, polygons, and curves (configured in [standard_crosshair.py](standard_crosshair.py))

The app maintains a **system tray icon** for background operation and uses **global keyboard hotkeys** (via `keyboard` library, not Qt) to toggle visibility, mirror, and switch images without focus.

## Key Data Flows

### Settings & Presets (standard_crosshair.py)
- **Load**: `load_settings_from_disk()` → `CONFIG_PATH` = `standard_crosshair_settings.json`
- **Presets**: Bundled templates ("Default", "Dot", "Small Plus", "Circle + Dot") seeded on first run
- **Import**: External presets from `crosshair_profiles.json` merged on startup with collision-safe renaming
- **Persistence**: `save_settings_to_disk()` serializes `StandardCrosshairSettings` dataclass to JSON
- **Rendering**: `render_crosshair_on_label()` paints to transparent pixmap using `QPainter`; fan rotation uses `QTimer`

### Hotkeys (hotkeys.py + hotkey_manager.py)
- **Config file**: `hotkey_config.json` (JSON dict mapping action name → list of key strings)
- **Action names**: `toggle_visibility`, `mirror_vertical`, `mirror_horizontal`, `switch_image`
- **Key format**: Lower-case, `+`-separated (e.g., `ctrl+alt+f1`, `f2`) parsed by `keyboard.add_hotkey()`
- **Pause/resume**: Used by hotkey manager dialog to avoid conflicts during remapping

### Control Panel (control_panel.py)
- **Stacked widget** with two pages: main menu (image/preset/opacity controls) + standard crosshair editor
- **Collapsible mode** persists user-resized widths per page (`_main_size`, `_crosshair_size`)
- **Frameless + WindowStaysOnTop** flags; custom resize detection on edge hover

### Image Management (image_manager.py)
- **Folder**: `display_images/` (auto-created if missing)
- **Formats**: PNG, JPG, JPEG, WEBP
- **File operations**: Copy to `display_images/`, delete from folder (no trash)

## Developer Workflows

### Run
```bash
python main.py  # or run_app.bat on Windows
```

### Install Dependencies
```bash
pip install -r requirements.txt  # PyQt6, keyboard
```

### Build Executable (PyInstaller)
```bash
pyinstaller "Zenless Zone Zero Crosshair.spec"
```
- Bundles `display_images/`, `hotkey_config.json`, `readme.media/` into executable
- Icon: `astra_yao_tray.ico` (referenced in .spec)

### Installer (Inno Setup)
- Script: `ZenlessZoneZeroCrosshair.iss`
- Builds `.exe` installer for end-users

## Project-Specific Conventions

1. **Color storage**: RGBA channels stored as separate `int` fields (red, green, blue, alpha) in settings, not hex strings
2. **Geometry**: Line components (left/right/top/bottom) mapped via `STYLE_ANGLES` and `ATTR_TO_LINE_KEY` dicts
3. **Settings migration**: On load, component types "polygon" → "triangle"; old presets with missing fields are sanitized
4. **Layer system**: Procedural crosshair supports "line layers" (custom-drawn groups of components with independent rotation)
5. **UI theme**: Shared dark purple palette in `utils.py` (`UI_THEME` dict) applied via `setStyleSheet()`
6. **Windows-only global hotkeys**: Uses `keyboard` library (non-blocking event loop), not Qt key events

## Important Caveats

- **Global hotkeys** require `keyboard` library, which uses OS-level listeners; may require admin on some Windows builds
- **Frameless windows** (control panel, dialogs) use custom title bars and manual resize edge detection
- **Transparency**: Label uses `WA_TranslucentBackground` + `WindowTransparentForInput` flags; pixmap fill must be transparent for overlay to work
- **Preset name collisions**: Resolved automatically with `_unique_preset_name()` function (e.g., "Copy (2)", "Copy (3)")
