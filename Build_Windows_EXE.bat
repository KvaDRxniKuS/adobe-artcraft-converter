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

py -3 -m pip install --upgrade -r "config\requirements.txt" PyInstaller
if errorlevel 1 goto :failed

rem Include the repository root for imports from app, converters and craft_converter.
rem Keep the EXE and generated spec in ignored build folders, never in the root.
py -3 -m PyInstaller --clean --noconfirm --onefile --windowed --name FilmCraftConverter --paths "." --specpath "build" --add-data "resources\shortcuts\Premiere_Shortcuts_Template.kys;resources\shortcuts" --add-data "resources\shortcuts\FilmCraft_Shortcuts_Template.json;resources\shortcuts" "app\desktop_app.py"
if errorlevel 1 goto :failed
if not exist "dist\FilmCraftConverter.exe" goto :failed

echo.
echo Done: dist\FilmCraftConverter.exe
echo Double-click the EXE in dist to launch the native desktop app.
pause
exit /b 0

:failed
echo.
echo Build failed. Check the error above.
pause
exit /b 1
