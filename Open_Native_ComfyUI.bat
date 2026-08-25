@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Native ComfyUI - Advanced Only

rem PATCH2.8-I2-R2B0 advanced entry. Normal users should use Start_ArchitectVideoStudio.bat.
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "H3_WINDOWS_SAFE_LOAD=pread"
set "H3_PROJECT_ROOT=%ROOT%"
set "NATIVE_ROOT="
if defined H3_NATIVE_ROOT set "NATIVE_ROOT=%H3_NATIVE_ROOT%"
if not defined NATIVE_ROOT if exist "%ROOT%\native_env.path" set /p NATIVE_ROOT=<"%ROOT%\native_env.path"
if not defined NATIVE_ROOT goto :not_configured
if not exist "%NATIVE_ROOT%\python_embeded\python.exe" goto :not_configured
if not exist "%NATIVE_ROOT%\ComfyUI\main.py" goto :not_configured
set "H3_NATIVE_ROOT=%NATIVE_ROOT%"
if exist "%NATIVE_ROOT%\ComfyUI\models" set "H3_MODELS_ROOT=%NATIVE_ROOT%\ComfyUI\models"
set "H3_BASELINE=%ROOT%\configs\native_production_baseline.json"
set "H3_ENV_REPORT=%ROOT%\userdata\system\env_report.json"

set "PY="
if defined H3_BOOTSTRAP_PYTHON if exist "%H3_BOOTSTRAP_PYTHON%" set "PY=%H3_BOOTSTRAP_PYTHON%"
if not defined PY if exist "%ROOT%\runtime\bootstrap\python.exe" set "PY=%ROOT%\runtime\bootstrap\python.exe"
if not defined PY if exist "%ROOT%\userdata\cache\runtime\comfyui_runtime\python_embeded\python.exe" set "PY=%ROOT%\userdata\cache\runtime\comfyui_runtime\python_embeded\python.exe"
if not defined PY if exist "%NATIVE_ROOT%\python_embeded\python.exe" set "PY=%NATIVE_ROOT%\python_embeded\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY set "PY=%%P"
if not defined PY goto :bootstrap_error
set "H3_BOOTSTRAP_PYTHON=%PY%"

echo Starting Native ComfyUI (Advanced / Developer only) on port 8189...
"%PY%" "%ROOT%\launcher\launcher.py" native
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Native ComfyUI could not start.
  echo Reason: launcher exited with code %EXIT_CODE%.
  echo Log: %ROOT%\Logs\launcher.log
  echo.
  echo Press any key to close.
  pause >nul
)
endlocal & exit /b %EXIT_CODE%

:not_configured
echo.
echo Native Runtime is not configured.
echo.
echo Please run:
echo Start_ArchitectVideoStudio.bat
echo and complete System Setup first.
echo.
echo Log: %ROOT%\Logs\launcher.log
echo Press any key to close.
pause >nul
endlocal & exit /b 1

:bootstrap_error
echo.
echo Native ComfyUI could not start.
echo Reason: no bootstrap Python was found.
echo Log: %ROOT%\Logs\launcher.log
echo Press any key to close.
pause >nul
endlocal & exit /b 1
