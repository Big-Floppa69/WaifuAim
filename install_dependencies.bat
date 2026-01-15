@echo off
echo Installing WaifuAim dependencies...
echo.

set "PY_CMD="

REM Prefer the Windows Python Launcher if available
py --version >nul 2>&1
if %errorlevel% equ 0 (
    REM Prefer a stable Python that has prebuilt wheels for numpy/opencv.
    py -3.12 --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=py -3.12"
    ) else (
        py -3.11 --version >nul 2>&1
        if %errorlevel% equ 0 (
            set "PY_CMD=py -3.11"
        ) else (
            py -3.10 --version >nul 2>&1
            if %errorlevel% equ 0 (
                set "PY_CMD=py -3.10"
            ) else (
                set "PY_CMD=py -3"
            )
        )
    )
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

REM Detect unsupported too-new Python versions (e.g. 3.14) that often lack wheels.
set "PY_VER_CODE="
for /f "usebackq delims=" %%v in (`%PY_CMD% -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])"`) do set "PY_VER_CODE=%%v"
if not "%PY_VER_CODE%"=="" (
    if %PY_VER_CODE% GEQ 314 (
        echo.
        echo Detected Python %PY_CMD% with version 3.%PY_VER_CODE:~1%.
        echo Python 3.14+ often has no prebuilt wheels for NumPy/OpenCV yet,
        echo so pip tries to compile them and fails without Visual C++ build tools.
        echo.
        echo Recommended fix: install Python 3.12 x64 from https://python.org
        echo Then rerun this installer step.
        echo.
        echo Alternative: install "Visual Studio Build Tools" with "Desktop development with C++".
        pause
        exit /b 1
    )
)

REM Upgrade pip
echo Upgrading pip...
%PY_CMD% -m pip install --upgrade pip

REM Install dependencies
echo Installing dependencies from requirements.txt...
%PY_CMD% -m pip install --only-binary=:all: -r requirements.txt

if %errorlevel% equ 0 (
    echo.
    echo Dependencies installed successfully!
    echo You can now run the application using run_app.bat
) else (
    echo.
    echo Error installing dependencies.
    echo If you are using Python 3.14+, install Python 3.12 x64 instead.
    echo If you must stay on a new Python, install Visual C++ build tools.
)

echo.
pause