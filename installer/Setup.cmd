@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Architect Video Studio Setup
set "SETUP_ROOT=%~dp0"
if exist "%SETUP_ROOT%SetupLauncher.exe" (
  start "Architect Video Studio Setup" "%SETUP_ROOT%SetupLauncher.exe" %*
  endlocal & exit /b 0
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_ROOT%Setup.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Architect Video Studio setup failed with code %EXIT_CODE%.
  pause
)
endlocal & exit /b %EXIT_CODE%
