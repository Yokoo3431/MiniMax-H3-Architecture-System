@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Architect Video Studio - One-click Start

rem PATCH2.8-I2-R2B0 public entry.  Setup GUI never depends on Native ComfyUI.
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "H3_WINDOWS_SAFE_LOAD=pread"
set "H3_PROJECT_ROOT=%ROOT%"
set "NATIVE_ROOT="

if defined H3_NATIVE_ROOT set "NATIVE_ROOT=%H3_NATIVE_ROOT%"
if not defined NATIVE_ROOT if exist "%ROOT%\native_env.path" set /p NATIVE_ROOT=<"%ROOT%\native_env.path"
if defined NATIVE_ROOT set "H3_NATIVE_ROOT=%NATIVE_ROOT%"

rem Prefer project-managed/validated Python; system Python is development fallback only.
set "PY="
if defined H3_BOOTSTRAP_PYTHON if exist "%H3_BOOTSTRAP_PYTHON%" set "PY=%H3_BOOTSTRAP_PYTHON%"
if not defined PY if exist "%ROOT%\runtime\bootstrap\python.exe" set "PY=%ROOT%\runtime\bootstrap\python.exe"
if not defined PY if exist "%ROOT%\userdata\cache\runtime\comfyui_runtime\python_embeded\python.exe" set "PY=%ROOT%\userdata\cache\runtime\comfyui_runtime\python_embeded\python.exe"
if not defined PY if defined NATIVE_ROOT if exist "%NATIVE_ROOT%\python_embeded\python.exe" set "PY=%NATIVE_ROOT%\python_embeded\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"

if not defined PY goto :bootstrap_error
set "H3_BOOTSTRAP_PYTHON=%PY%"
set "H3_BASELINE=%ROOT%\configs\native_production_baseline.json"
if not defined H3_ENV_REPORT set "H3_ENV_REPORT=%ROOT%\userdata\system\env_report.json"
if not defined H3_STUDIO_DATA set "H3_STUDIO_DATA=%ROOT%\userdata\studio"
set "MODELS_ROOT="
if exist "%ROOT%\models_env.path" set /p MODELS_ROOT=<"%ROOT%\models_env.path"
if defined MODELS_ROOT set "H3_MODELS_ROOT=%MODELS_ROOT%"
if not defined H3_MODELS_ROOT if defined NATIVE_ROOT if exist "%NATIVE_ROOT%\ComfyUI\models" set "H3_MODELS_ROOT=%NATIVE_ROOT%\ComfyUI\models"
if defined NATIVE_ROOT set "H3_COMFY_INPUT=%NATIVE_ROOT%\ComfyUI\input"
if defined NATIVE_ROOT set "H3_COMFY_OUTPUT=%NATIVE_ROOT%\ComfyUI\output"

rem Normal users get the desktop control center with a taskbar/notification icon.
rem The browser remains an explicit backup surface from that GUI.
if exist "%ROOT%\launcher\ArchitectVideoStudioDesktop.exe" (
  start "Architect Video Studio" "%ROOT%\launcher\ArchitectVideoStudioDesktop.exe"
  endlocal & exit /b 0
)

echo ============================================================
echo   Architect Video Studio
echo   Setup GUI starts before Native Runtime checks.
echo   Bootstrap: %PY%
echo ============================================================
"%PY%" "%ROOT%\launcher\launcher.py" start
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Architect Video Studio could not start.
  echo.
  echo Reason: launcher exited with code %EXIT_CODE%.
  echo Log: %ROOT%\Logs\launcher.log
  echo.
  echo Press any key to close.
  pause >nul
)
endlocal & exit /b %EXIT_CODE%

:bootstrap_error
echo.
echo Architect Video Studio could not start.
echo.
echo Reason: no project-managed or available bootstrap Python was found.
echo The Setup GUI cannot start until a Python runtime is supplied.
echo Log: %ROOT%\Logs\launcher.log
echo.
echo Press any key to close.
pause >nul
endlocal & exit /b 1
