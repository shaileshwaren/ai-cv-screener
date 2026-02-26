@echo off
REM =============================================================================
REM Offline Pipeline - Multi-Job Runner
REM =============================================================================

echo.
echo ========================================
echo   Offline Pipeline - Multi-Job Mode
echo ========================================
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo.
    echo Please run setup.bat first to install dependencies.
    echo.
    pause
    exit /b 1
)

REM Always prompt for job IDs
echo Enter Job ID(s) to process:
echo   - Single job: 3419430
echo   - Multiple jobs: 3419430, 3261113
echo.
set /p JOB_IDS=Job IDs: 

REM Check if job IDs were provided
if "%JOB_IDS%"=="" (
    echo.
    echo ERROR: No job IDs specified!
    echo.
    pause
    exit /b 1
)

echo.
echo Processing job(s): %JOB_IDS%
echo.

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Run offline pipeline with specified job IDs
python offline_pipeline.py "%JOB_IDS%"

REM Check exit code
if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   All jobs completed successfully!
    echo ========================================
) else (
    echo.
    echo ========================================
    echo   Some jobs failed - check output above
    echo ========================================
)

REM Deactivate virtual environment
call .venv\Scripts\deactivate.bat 2>nul

echo.
pause
