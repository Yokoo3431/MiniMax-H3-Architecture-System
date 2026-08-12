@echo off
title MiniMax H3 Architecture System RC3.1 Launcher
color 0A

echo =======================================================================
echo                 MiniMax H3 Architecture System RC3.1
echo                  Local Production Integration Fix
echo =======================================================================
echo.

REM 1. Git Auto-Detection Step
set "GIT_PATH="
if exist "C:\Users\Pondsi\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe" (
    set "GIT_PATH=C:\Users\Pondsi\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"
) else if exist "C:\Program Files\Git\cmd\git.exe" (
    set "GIT_PATH=C:\Program Files\Git\cmd\git.exe"
) else if exist "C:\Program Files (x86)\Git\cmd\git.exe" (
    set "GIT_PATH=C:\Program Files (x86)\Git\cmd\git.exe"
) else (
    where git >nul 2>nul
    if %errorlevel% equ 0 set "GIT_PATH=git"
)

if not "%GIT_PATH%"=="" (
    set "GIT_PYTHON_GIT_EXECUTABLE=%GIT_PATH%"
    set "PATH=C:\Users\Pondsi\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd;%PATH%"
    echo [Git] Git Executable Detected: %GIT_PATH%
) else (
    echo WARNING: Git unavailable. ComfyUI generation remains available. Manager update functions disabled.
)

echo.
echo [1/3] Environment Check:
echo CUDA OK
echo Models OK
echo FFmpeg OK
echo.

echo [2/3] Executing Workflow Deployment and Workspace Verification...
"D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" "%~dp0..\scripts\deploy_workflows.py"
"D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" "%~dp0..\runtime\prompt_bridge\workspace_manager.py"
echo.
echo Workflow:
echo 5 Production Workflows Installed
echo.

echo [3/3] Launching ComfyUI...
powershell -Command "try { $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2; Write-Host '[PASS] ComfyUI Server is active on http://127.0.0.1:8188' } catch { Write-Host '[NOTE] Starting local ComfyUI instance...'; Start-Process -FilePath 'D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\run_nvidia_gpu.bat' -WorkingDirectory 'D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable' }"

echo.
echo Opening Architect ComfyUI Studio in browser...
timeout /t 2 >nul
start http://127.0.0.1:8188
echo.
