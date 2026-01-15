<div align="center">
<img src="astra_yao_tray.png" width="200px" />
</div>

# <div align="center">WaifuAim</div>

WaifuAim is a lightweight, always-on-top crosshair overlay for Windows.

It supports two rendering modes:

- **Image-based**: show a PNG/JPG/WEBP crosshair from `display_images/`
- **Generated**: a procedural crosshair (lines/dots/circles/etc.) configured in the built-in editor

## Features

- Global hotkeys (work without focus)
- System tray icon + tray menu
- Presets/profiles for the generated crosshair
- Randomize button + Randomize hotkey

## Hotkeys

Hotkeys are configured in `hotkey_config.json` and can also be changed via the in-app Hotkey UI.

**Chord format** is lower-case keys joined with `+`, for example:

- `ctrl+alt+f2`
- `shift+mouse_x1`
- `windows+f3`

Note: modifier-only hotkeys like `alt` / `ctrl+alt` may not work reliably as global hotkeys on Windows. Prefer including a non-modifier key (for example `alt+f2`). But they still work pretty nice, personally, didn't have issues.

Note: while the **Hotkey Manager** window is open, global hotkeys are paused to prevent accidental triggers.

## Images

- Put your crosshair images into `display_images/`.
- Supported formats: PNG, JPG/JPEG, WEBP.
- Use the configured `switch_image` hotkey to cycle.

## Generated crosshair presets

The generated crosshair editor lets you save and switch presets. The Randomize button and Randomize hotkey both use the selected Randomize mode:

- **From Presets**: picks a preset (avoids re-picking the currently active preset when multiple exist)
- **Absolute Random**: randomizes parameters directly

## Installer (recommended)

If you have the installer, just run it and follow the steps. It includes everything needed to start the app (no Python setup required).

## 🚀 Installing (for development)

### 1. Create a virtual environment

```bash
python -m venv venv
```

### 2. Activate the virtual environment

On Windows:

```bash
venv\Scripts\activate
```

On Linux/MacOS:

```bash
source venv/bin/activate
```

### 3. Install dependencies

```
pip install -r requirements.txt
```

### 4. Run the project

```
python main.py
```

## Importing crosshair profiles (presets)

- Create a file named `crosshair_profiles.json` next to `standard_crosshair.py`.
- On app start (or whenever settings are loaded), presets from that file are merged into your saved preset list.
- If a name already exists, it will be imported as `Name (2)`, `Name (3)`, etc.

See `crosshair_profiles.example.json` for the file format.

## 🎉 That's it!

## Credits

- Creators: **Big-Floppa69** and **AmacioSlayer**
- Inspired by **Hitoshi144** (original tiny one-file version)

You can also improve the program by adding additional features.

If you liked this app at all, please give it a **star** rating (´ ω `♡). I would be very grateful.
