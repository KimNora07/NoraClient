@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Building standalone Windows EXE for Nora Studio...
py -3.12 --version >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 not found. Install Python 3.12 alongside your current Python first.
  if /I not "%~1"=="--no-pause" pause
  exit /b 1
)
py -3.12 -m venv .build-venv
if errorlevel 1 goto fail
".build-venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller pillow PySide6 PySide6-Addons
if errorlevel 1 goto fail
".build-venv\Scripts\python.exe" windows\Generate-App-Icon.py
if errorlevel 1 goto fail
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name NoraStudio --icon "assets\NoraStudio.ico" --add-data "static;static" --collect-all uvicorn --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets --collect-submodules keyring.backends --hidden-import uvicorn.logging desktop.py
if errorlevel 1 goto fail
echo.
echo SUCCESS: dist\NoraStudio\NoraStudio.exe
echo The EXE and _internal folder must remain together.
if /I not "%~1"=="--no-pause" pause
exit /b 0
:fail
echo.
echo EXE build failed. Review the error messages above.
if /I not "%~1"=="--no-pause" pause
exit /b 1
