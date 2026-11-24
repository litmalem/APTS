@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 atau lebih baru diperlukan.
  pause
  exit /b 1
)
python server.py %*
if errorlevel 1 pause
