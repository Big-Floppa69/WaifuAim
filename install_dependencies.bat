@echo off
echo Installing WaifuAim dependencies...
echo.

set "PY_CMD="

REM Prefer the Windows Python Launcher if available
py -3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py -3"
) else (
    REM Fall back to python on PATH
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=python"
    )
)

REM Check if Python is installed
if "%PY_CMD%"=="" (
    echo Python is not installed or not in PATH!
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Upgrade pip
echo Upgrading pip...
%PY_CMD% -m pip install --upgrade pip

REM Install dependencies
echo Installing dependencies from requirements.txt...
%PY_CMD% -m pip install -r requirements.txt

if %errorlevel% equ 0 (
    echo.
    echo Dependencies installed successfully!
    echo You can now run the application using run_app.bat
) else (
    echo.
    echo Error installing dependencies. Please check your Python installation.
)

echo.
pause