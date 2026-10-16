@echo off
setlocal
cd /d "%~dp0"

echo Build FilmCraftConverter.exe - native Windows desktop application
echo Python 3.10+ and an internet connection are needed for the one-time dependency install.
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher ^(py^) not found. Install Python 3.10 or later from python.org.
  pause
  exit /b 1
)

py -3 -c "import sys; raise SystemExit(sys.version_info < (3,10))"
if errorlevel 1 (
  echo Python 3.10 or later is required.
  pause
  exit /b 1
)

py -3 -m pip install --upgrade -r requirements.txt PyInstaller
if errorlevel 1 goto :failed

py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --name FilmCraftConverter --add-data "Premiere_Shortcuts_Template.kys;." --add-data "FilmCraft_Shortcuts_Template.json;." desktop_app.py
if errorlevel 1 goto :failed

copy /y "dist\FilmCraftConverter.exe" "%~dp0FilmCraftConverter.exe" >nul
if errorlevel 1 goto :failed

echo.
echo Done: FilmCraftConverter.exe
echo Double-click the EXE to launch the native desktop app.
pause
exit /b 0

:failed
echo.
echo Build failed. Check the error above.
pause
exit /b 1
