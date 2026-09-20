@echo off
chcp 65001 >nul 2>&1
setlocal
title UOM Airspace Viewer

rem ============================================================
rem  UOM Airspace Viewer - desktop launcher
rem
rem  Prefers the packaged exe (no Python needed). Falls back to a
rem  Python local server when the exe is absent.
rem
rem  Why a local HTTP server is required instead of opening
rem  index.html directly: PMTiles reads bytes via HTTP Range
rem  requests, and browsers do not send Range over file://.
rem ============================================================

set "PROJ=%~dp0"
cd /d "%PROJ%"

if not exist "%PROJ%index.html" (
  echo [ERROR] Project folder not found:
  echo   %PROJ%
  echo Edit the PROJ variable in this file if you moved it.
  pause
  exit /b 1
)

echo ============================================
echo   UOM Airspace Viewer
echo ============================================
echo.

if exist "%PROJ%\release\UOM-Viewer-Windows-x64.exe" (
  echo Starting packaged app...
  start "" "%PROJ%\release\UOM-Viewer-Windows-x64.exe"
  exit /b 0
)

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No packaged exe found and Python is not installed.
  echo.
  echo   Option 1: download UOM-Viewer-Windows-x64.exe from Releases
  echo   Option 2: install Python 3.x and run this script again
  echo.
  pause
  exit /b 1
)

echo Starting local server on http://127.0.0.1:8080
echo Your browser will open automatically.
echo Close this window to stop the server.
echo.
start "" "http://127.0.0.1:8080/index.html"
python "%PROJ%\serve.py" 8080

pause
