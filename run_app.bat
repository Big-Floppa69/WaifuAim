@echo off
title Zenless Zone Zero Crosshair
echo Starting Zenless Zone Zero Crosshair...
echo.

REM Change to the directory where this batch file is located
cd /d "%~dp0"

REM Check if dependencies are installed
python -c "import PyQt6, keyboard" >nul 2>&1
if %errorlevel% neq 0 (
    echo Dependencies not found! Running installer...
    call install_dependencies.bat
    if %errorlevel% neq 0 (
        echo Failed to install dependencies. Please install manually.
        pause
        exit /b 1
    )
)

REM Run the application
echo Launching application...
python main.py

REM If the application exits, pause to show any error messages
if %errorlevel% neq 0 (
    echo.
    echo Application exited with error code %errorlevel%
    echo.
    pause
)