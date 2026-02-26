@echo off
REM =============================================================================
REM Recruitment Pipeline - One-Time Setup
REM =============================================================================
REM Run this script ONCE to set up Python virtual environment and dependencies.
REM After setup, use run_pipeline.bat to run the pipeline.
REM =============================================================================

echo.
echo ========================================
echo   Recruitment Pipeline Setup
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH!
    echo.
    echo Please install Python 3.10 or higher from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo Found Python:
python --version
echo.

REM Check if virtual environment already exists
if exist ".venv" (
    echo Virtual environment already exists.
    echo.
    choice /C YN /M "Do you want to recreate it"
    if errorlevel 2 goto :skip_venv
    if errorlevel 1 (
        echo Removing old virtual environment...
        rmdir /s /q .venv
    )
)

echo Creating virtual environment...
python -m venv .venv
if %errorlevel% neq 0 (
    echo ERROR: Failed to create virtual environment!
    pause
    exit /b 1
)

:skip_venv

REM Activate virtual environment
echo.
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Upgrade pip
echo.
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install dependencies
echo.
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   Setup completed successfully!
    echo ========================================
    echo.
    echo You can now:
    echo   1. Edit pipeline_config.txt with your job settings
    echo   2. Double-click run_pipeline.bat to run the pipeline
    echo.
) else (
    echo.
    echo ========================================
    echo   Setup failed!
    echo ========================================
    echo.
    echo Please check the error messages above.
    echo.
)

call .venv\Scripts\deactivate.bat 2>nul

echo.
pause
