@echo off
REM ==============================================================================
REM run_online.bat - Multi-Job Online Pipeline Runner
REM ==============================================================================

echo.
echo ========================================
echo   Online Pipeline - Multi-Job Mode
echo ========================================
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo WARNING: Virtual environment not found!
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

REM Run the online pipeline
python online_pipeline.py %JOB_IDS%

REM Capture exit code
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% EQU 0 (
    echo ========================================
    echo   Pipeline completed successfully!
    echo ========================================
) else (
    echo ========================================
    echo   Pipeline failed with exit code %EXIT_CODE%
    echo ========================================
)
echo.

REM Deactivate virtual environment
call .venv\Scripts\deactivate.bat 2>nul

echo.
pause

exit /b %EXIT_CODE%
