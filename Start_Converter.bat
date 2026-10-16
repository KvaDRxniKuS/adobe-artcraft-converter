@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0FilmCraftConverter.exe" (
  start "" "%~dp0FilmCraftConverter.exe"
  goto :end
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(sys.version_info < (3,10))" >nul 2>nul
  if errorlevel 1 goto :need_build
  py -3 -c "import PySide6" >nul 2>nul
  if errorlevel 1 goto :need_build
  py -3 desktop_app.py
  goto :check
)

where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(sys.version_info < (3,10))" >nul 2>nul
  if errorlevel 1 goto :need_build
  python -c "import PySide6" >nul 2>nul
  if errorlevel 1 goto :need_build
  python desktop_app.py
  goto :check
)

echo Python 3.10+ is needed. Or run Build_Windows_EXE.bat once to create the standalone EXE.
pause
goto :end

:need_build
echo Desktop dependencies are not installed. Run Build_Windows_EXE.bat to build the standalone app.
pause
goto :end

:check
if errorlevel 1 pause
:end
endlocal
