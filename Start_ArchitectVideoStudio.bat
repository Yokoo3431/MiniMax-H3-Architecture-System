@echo off
setlocal
title Architect Video Studio - One-click Start

rem ============================================================
rem  Architect Video Studio - Public one-click entry (PATCH2.8-I0)
rem  Double-click to start: env check -> Native ComfyUI -> Studio
rem  -> browser opens automatically at http://127.0.0.1:8788
rem ============================================================

rem Locate repository root (this file must stay at the repo root)
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

rem Windows mmap mitigation (frozen safe-load shim)
set "H3_WINDOWS_SAFE_LOAD=pread"

rem --- Resolve the Native runtime root (no hardcoded dev paths) ---
set "NATIVE_ROOT="
if defined H3_NATIVE_ROOT set "NATIVE_ROOT=%H3_NATIVE_ROOT%"
if not defined NATIVE_ROOT if exist "%ROOT%\native_env.path" (
  set /p NATIVE_ROOT=<"%ROOT%\native_env.path"
)
if not defined NATIVE_ROOT (
  echo.
  echo  [ERROR] NATIVE RUNTIME NOT CONFIGURED
  echo  请设置环境变量 H3_NATIVE_ROOT，或在本目录创建 native_env.path
  echo  （第一行为 Native ComfyUI 根目录，例如 D:\ComfyUI_H3_NATIVE_TEST）。
  echo.
  echo  示例模板见 native_env.path.example
  pause
  exit /b 1
)

set "PY=%NATIVE_ROOT%\python_embeded\python.exe"
if not exist "%PY%" (
  echo.
  echo  [ERROR] NATIVE RUNTIME MISSING
  echo  未找到 Python: %PY%
  echo  请检查 native_env.path 是否指向正确的 Native ComfyUI 根目录。
  echo.
  pause
  exit /b 1
)

rem Export the derived paths for the launcher/studio modules
set "H3_NATIVE_ROOT=%NATIVE_ROOT%"
set "H3_MODELS_ROOT=%NATIVE_ROOT%\..\ComfyUI_windows_portable\ComfyUI\models"
set "H3_COMFY_INPUT=%NATIVE_ROOT%\ComfyUI\input"
set "H3_COMFY_OUTPUT=%NATIVE_ROOT%\ComfyUI\output"
set "H3_BASELINE=%ROOT%\configs\native_production_baseline.json"
set "H3_ENV_REPORT=%ROOT%\env_report.json"
set "H3_STUDIO_DATA=%ROOT%\userdata\studio"

echo ============================================================
echo   Architect Video Studio
echo   Native root : %NATIVE_ROOT%
echo   Safe load   : %H3_WINDOWS_SAFE_LOAD%
echo ============================================================

"%PY%" "%ROOT%\launcher\launcher.py" start

if errorlevel 1 (
  echo.
  echo  [ERROR] 启动失败。
  echo  常见原因：
  echo    MODEL MISSING           - 模型缺失或 SHA-256 不匹配
  echo    CUDA NOT AVAILABLE      - 无可用 CUDA GPU
  echo    FREE COMMIT TOO LOW     - 系统提交内存不足（需 >=30GB）
  echo    PORT 8189 OCCUPIED      - ComfyUI 端口被占用
  echo  详细日志：%ROOT%\logs\launcher.log
  echo.
  pause
  exit /b 1
)

endlocal
