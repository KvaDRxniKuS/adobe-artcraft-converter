@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"

rem Source-only updates need Python 3.10+. Prefer an interpreter with PySide6.
set "PYTHON_CMD="
set "DOWNLOAD_PY="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 set "DOWNLOAD_PY=py -3"
  py -3 -c "import sys; import PySide6.QtWidgets; raise SystemExit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if defined PYTHON_CMD goto :run_update

where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 if not defined DOWNLOAD_PY set "DOWNLOAD_PY=python"
  python -c "import sys; import PySide6.QtWidgets; raise SystemExit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if defined PYTHON_CMD goto :run_update
if defined DOWNLOAD_PY set "PYTHON_CMD=%DOWNLOAD_PY%"
if defined PYTHON_CMD goto :run_update

echo Python 3.10+ is not available, so source updates cannot be checked.
goto :fallback_exe

:run_update
if not exist "%~dp0update_converter.py" goto :local_source
%PYTHON_CMD% "%~dp0update_converter.py" --source-dir "%~dp0"
if "%errorlevel%"=="42" goto :no_pyside
if errorlevel 1 goto :failed
goto :end

:local_source
echo Source updater is missing. Launching local files without an update check.
%PYTHON_CMD% -c "import PySide6.QtWidgets" >nul 2>nul
if errorlevel 1 goto :no_pyside
%PYTHON_CMD% "%~dp0desktop_app.py"
if errorlevel 1 goto :failed
goto :end

:no_pyside
echo Source updates need PySide6. Install dependencies with: %PYTHON_CMD% -m pip install -r "%~dp0requirements.txt"
goto :fallback_exe

:fallback_exe
if not exist "%~dp0FilmCraftConverter.exe" goto :need_build
echo Starting the existing EXE. It is NOT updated by source-only updates.
start "" "%~dp0FilmCraftConverter.exe"
goto :end

:need_build
echo No usable EXE found. Install Python 3.10+ and PySide6, or build the EXE with Build_Windows_EXE.bat.
pause
goto :end

:failed
echo FilmCraft Converter exited with an error. Check the message above.
pause

:end
endlocal
