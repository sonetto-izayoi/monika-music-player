@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher not found. Run scripts\install_dependencies.bat first.
  pause
  exit /b 1
)
py -3 player\music_player.py
