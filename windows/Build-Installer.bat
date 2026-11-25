@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
echo ============================================
echo   Nora Studio - Windows Setup Wizard Build
echo ============================================
echo.
call "windows\Build-Standalone-EXE.bat" --no-pause
if errorlevel 1 goto fail

set "NORA_ISCC="
where ISCC.exe >nul 2>nul
if not errorlevel 1 set "NORA_ISCC=ISCC.exe"
if not defined NORA_ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "NORA_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined NORA_ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "NORA_ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined NORA_ISCC (
  echo Inno Setup 6 is required to create the installer wizard.
  echo Install it from https://jrsoftware.org/isinfo.php
  goto fail
)

echo.
echo Building installer with Inno Setup...
"%NORA_ISCC%" "windows\NoraStudio.iss"
if errorlevel 1 goto fail
echo.
echo SUCCESS: installer-output\NoraStudio-Setup-0.4.0.exe
if /I not "%~1"=="--no-pause" pause
exit /b 0

:fail
echo.
echo Installer build failed. Check the error above.
if /I not "%~1"=="--no-pause" pause
exit /b 1
