@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-NoraStudio.ps1"
if errorlevel 1 (
  echo.
  echo Installation failed. Review the error above.
) else (
  echo.
  echo Installation completed. Use the Nora Studio desktop shortcut.
)
pause
