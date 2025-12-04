# Zenless Zone Zero Crosshair - Inno Setup Installer

This directory contains the complete Inno Setup installer script and supporting files for the Zenless Zone Zero Crosshair application.

## Files Included

- `ZenlessZoneZeroCrosshair.iss` - Main Inno Setup installer script
- `install_dependencies.bat` - Batch script to install Python dependencies
- `run_app.bat` - Batch script to launch the application with dependency checks
- `python_check.py` - Python script to verify environment setup
- `LICENSE.txt` - MIT License file
- `INSTALLER_README.md` - This documentation file

## Prerequisites

1. **Inno Setup 6.x** - Download from: https://jrsoftware.org/isinfo.php
2. **Python 3.8+** - Required for running the application
3. **All source files** from the Zenless Zone Zero Crosshair project

## How to Build the Installer

1. **Install Inno Setup** on your Windows machine
2. **Copy all project files** to the directory containing the `.iss` script:
   - All `.py` files (main.py, control_panel.py, etc.)
   - `requirements.txt`
   - All image files (`.png`, `.ico`)
   - `display_images/` directory
   - `readme.media/` directory
   - Any other project files
3. **Open** `ZenlessZoneZeroCrosshair.iss` in Inno Setup
4. **Build** the installer:
   - Press `Ctrl+F9` or use Build → Compile
   - The installer will be created in the `Output/` directory

## Installer Features

### Multi-language Support
- English (default)
- Russian
- Ukrainian

### Installation Options
- Desktop icon creation
- Quick Launch icon (Windows 7 and earlier)
- Auto-start with Windows
- Python dependency verification and installation

### System Requirements
- Windows 10/11 (x64)
- Python 3.8+ (checked during installation)
- Administrator privileges (for dependency installation)

### Application Registration
- Registry entries for proper Windows integration
- Uninstall registry entries
- Start menu shortcuts

## Post-Installation Behavior

The installer will:

1. **Check Python installation** - Validates Python 3.8+ is installed and in PATH
2. **Install dependencies** - Automatically installs PyQt6 and keyboard packages
3. **Create shortcuts** - Desktop, Start Menu, and Quick Launch icons
4. **Optionally configure auto-start** - Adds to Windows startup (if selected)
5. **Launch application** - Option to run the app immediately after installation

## Uninstallation

The uninstaller will:

1. **Stop running instances** - Terminates any running Python processes
2. **Remove registry entries** - Cleans up Windows registry
3. **Delete application files** - Removes all installed files and directories
4. **Remove shortcuts** - Cleans desktop and start menu icons

## Customization

### Version Updates
Update these constants in the `.iss` file:
```pascal
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Your Publisher Name"
```

### Additional Files
To include more files in the installer, add entries to the `[Files]` section:
```pascal
Source: "your_file.py"; DestDir: "{app}"; Flags: ignoreversion
```

### Custom Installation Tasks
Add new tasks in the `[Tasks]` section:
```pascal
Name: "yourtask"; Description: "Your custom task description"; Flags: unchecked
```

## Troubleshooting

### Python Not Found
- Ensure Python 3.8+ is installed
- Add Python to system PATH
- Restart command prompt after PATH changes

### Dependency Installation Fails
- Run installer as Administrator
- Check internet connection for package downloads
- Manually run `install_dependencies.bat`

### Application Won't Start
- Run `python_check.py` to diagnose issues
- Check that all dependencies are installed: `pip list`
- Review application logs for specific errors

## Advanced Configuration

### Silent Installation
```batch
# Create silent installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /S /silent ZenlessZoneZeroCrosshair.iss

# Silent install with options
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /S /silent /tasks="desktopicon,startup" ZenlessZoneZeroCrosshair.iss
```

### Custom Installer Icon
Replace `astra_yao_tray.ico` with your own icon file and update the script.

### Different Installation Directory
Users can change the installation path during setup. The default is:
`C:\Program Files\Zenless Zone Zero Crosshair`

## Support

For issues with:
- **Inno Setup** - Visit: https://jrsoftware.org/ishelp/
- **Application** - Check the main project repository
- **Dependencies** - Review requirements.txt and package documentation

## License

This installer is provided under the MIT License. See LICENSE.txt for details.

---

**Created:** December 2025  
**Inno Setup Version:** 6.x compatible  
**Python Version:** 3.8+ required