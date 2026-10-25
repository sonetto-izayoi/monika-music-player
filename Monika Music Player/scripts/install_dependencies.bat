@echo off
setlocal
chcp 65001 >nul
echo ==============================================
echo  Monika Music Player - dependency setup
echo ==============================================
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher (py.exe) was not found.
  echo Install Python 3.11 or newer from python.org, then reopen this file.
  echo Make sure to tick the option to install the Python Launcher.
  pause
  exit /b 1
)
echo Installing PySide6 for Python 3...
py -3 -m pip install --upgrade pip
py -3 -m pip install --upgrade PySide6
if errorlevel 1 (
  echo.
  echo The install did not finish. Check the error above and try again.
  pause
  exit /b 1
)
echo.
echo Done. Restart MAS and select Music Player again.
pause
