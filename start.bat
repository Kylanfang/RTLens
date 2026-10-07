@echo off
REM ============================================================
REM  RTLens v5.0.0 Quickstart Launcher for Windows
REM  1) Extract the WHOLE zip first (do not run from inside the zip)
REM  2) Double-click this file
REM  Browser will open automatically at http://127.0.0.1:8765
REM ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"
title RTLens v5.0.0

echo ============================================
echo   RTLens v5.0.0 - Verilog LSP Quickstart
echo ============================================
echo.

REM --- 1. check rtlens package exists next to this script ---
if not exist "%~dp0rtlens\__main__.py" (
    echo [ERROR] rtlens package not found next to start.bat
    echo         Please EXTRACT the whole zip first, then run start.bat
    echo         Do NOT run directly from inside the zip file.
    echo.
    pause
    exit /b 1
)

REM --- 2. find a working Python (py launcher > python > python3) ---
set "PY="
for %%C in ("py -3" "python" "python3") do (
    if not defined PY (
        %%~C --version >nul 2>&1
        if not errorlevel 1 set "PY=%%~C"
    )
)
if not defined PY goto :nopython

for /f "tokens=*" %%v in ('!PY! --version 2^>^&1') do echo [OK] Found %%v
echo.
echo [..] Starting Web UI, browser will open automatically...
echo [..] Keep this window open while using RTLens.
echo [..] Press Ctrl+C to stop.
echo.

REM --- 3. run quickstart (browser opens automatically) ---
!PY! -m rtlens quickstart
set RC=%errorlevel%
echo.
if !RC! neq 0 (
    echo [ERROR] quickstart exited with code !RC!
    echo         If port 8765 is in use, try: !PY! -m rtlens quickstart --port 8766
)
echo.
echo [..] Press any key to close this window.
pause >nul
exit /b !RC!

:nopython
echo [ERROR] Python 3.8+ not found on PATH.
echo         Please install from https://www.python.org/downloads/
echo         IMPORTANT: check "Add python.exe to PATH" during install!
echo.
echo         Opening download page...
start "" "https://www.python.org/downloads/"
echo.
pause
exit /b 1

