@echo off
echo Installing WaifuAim dependencies...
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH!
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install dependencies
echo Installing dependencies from requirements.txt...
python -m pip install -r requirements.txt

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