@echo off
setlocal
title Architect Video Studio - Production Launcher
cd /d "%~dp0.."

REM PREAD safe-load shim requirement (Windows mmap mitigation)
set "H3_WINDOWS_SAFE_LOAD=pread"

set "PY=D:\ProgramFilesNormal\ComfyUI\ComfyUI_H3_NATIVE_TEST\python_embeded\python.exe"
if not exist "%PY%" (
  echo [BLOCK] Python runtime not found: %PY%
  echo Please verify the Native ComfyUI environment path.
  pause
  exit /b 1
)

echo ============================================================
echo   Architect Video Studio - Production Launcher
echo   Env: %H3_WINDOWS_SAFE_LOAD%
echo ============================================================
"%PY%" "%~dp0launcher.py" start %*
if errorlevel 1 (
  echo.
  echo Launcher exited with code %errorlevel%. See Logs\launcher.log
  pause
)
endlocal
