@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM UOM airspace viewer launcher
REM Uses 127.0.0.1 (not localhost) to avoid IPv6 fallback delay on Windows.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  echo Please install Python 3.x and retry.
  pause
  exit /b 1
)

echo Starting UOM viewer at http://127.0.0.1:8080/index.html
start "" "http://127.0.0.1:8080/index.html"

python serve.py 8080

echo.
echo Server stopped.
pause
