@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.10 or newer with Tcl/Tk and the Python launcher enabled.
  echo If Python is already installed without py, run: python launch_editor.py
  echo See docs\HOST_LAUNCHER.md for setup help.
  pause
  exit /b 1
)
py -3 launch_editor.py
if errorlevel 1 pause
