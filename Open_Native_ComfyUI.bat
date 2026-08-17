@echo off
setlocal
title Native ComfyUI (Advanced / Developer only)

rem ============================================================
rem  Open Native ComfyUI directly (port 8189).
rem  ADVANCED / DEVELOPER ONLY - normal users do not need this.
rem  Does NOT open Architect Video Studio.
rem ============================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "H3_WINDOWS_SAFE_LOAD=pread"

set "NATIVE_ROOT="
if defined H3_NATIVE_ROOT set "NATIVE_ROOT=%H3_NATIVE_ROOT%"
if not defined NATIVE_ROOT if exist "%ROOT%\native_env.path" (
  set /p NATIVE_ROOT=<"%ROOT%\native_env.path"
)
if not defined NATIVE_ROOT (
  echo.
  echo  [ERROR] NATIVE RUNTIME NOT CONFIGURED
  echo  请设置 H3_NATIVE_ROOT 或创建 native_env.path（见 native_env.path.example）。
  echo.
  pause
  exit /b 1
)

set "PY=%NATIVE_ROOT%\python_embeded\python.exe"
if not exist "%PY%" (
  echo  [ERROR] Python not found: %PY%
  pause
  exit /b 1
)

echo Starting Native ComfyUI on port 8189 (Advanced / Developer only)...
"%PY%" -s "%NATIVE_ROOT%\ComfyUI\main.py" --windows-standalone-build --port 8189 --disable-dynamic-vram --disable-pinned-memory

if errorlevel 1 (
  echo.
  echo  [ERROR] ComfyUI exited abnormally. See %ROOT%\logs\launcher.log
  pause
)
endlocal
