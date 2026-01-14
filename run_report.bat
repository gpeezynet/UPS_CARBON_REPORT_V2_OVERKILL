@echo off
REM ============================================================
REM UPS Carbon Report Generator - Windows Runner
REM ============================================================
REM
REM Usage:
REM   1. Set CSV_PATH to your UPS shipping report CSV
REM   2. Set ORIGIN_ZIP to your default origin ZIP (optional)
REM   3. Set OUTPUT_DIR to desired output folder (optional)
REM   4. Run this batch file
REM
REM ============================================================

REM === CONFIGURATION - EDIT THESE ===

REM Path to your UPS CSV file (required)
set CSV_PATH=your_ups_report.csv

REM Default origin ZIP code (optional - leave blank if in data)
set ORIGIN_ZIP=35761

REM Output directory (optional - defaults to CSV location)
set OUTPUT_DIR=carbon_output

REM ============================================================
REM === DO NOT EDIT BELOW THIS LINE ===
REM ============================================================

echo.
echo ============================================================
echo UPS Carbon Report Generator
echo ============================================================
echo.

REM Check if CSV file exists
if not exist "%CSV_PATH%" (
    echo ERROR: CSV file not found: %CSV_PATH%
    echo.
    echo Please edit this batch file and set CSV_PATH to your UPS report CSV.
    echo.
    pause
    exit /b 1
)

echo Input CSV: %CSV_PATH%
echo Origin ZIP: %ORIGIN_ZIP%
echo Output Dir: %OUTPUT_DIR%
echo.

REM Build command
set CMD=python -m ups_carbon "%CSV_PATH%"

if not "%OUTPUT_DIR%"=="" (
    set CMD=%CMD% --out-dir "%OUTPUT_DIR%"
)

if not "%ORIGIN_ZIP%"=="" (
    set CMD=%CMD% --origin-zip %ORIGIN_ZIP%
)

echo Running: %CMD%
echo.

%CMD%

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Report generation failed!
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Report generation complete!
echo Check the output directory for results.
echo ============================================================
echo.

pause
