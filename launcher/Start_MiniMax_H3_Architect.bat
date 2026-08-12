@echo off
title MiniMax H3 Architecture System RC3.2 Launcher
color 0A

echo =======================================================================
echo                 MiniMax H3 Architecture System RC3.2
echo                Native Runtime Reconstruction Launcher
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
echo [1/4] Auto-Configuring FFmpeg & FFprobe...
where ffmpeg >nul 2>nul
if %errorlevel% equ 0 (
    echo [FFmpeg] System FFmpeg & FFprobe Active
) else (
    echo [FFmpeg] Using ComfyUI Embedded Video Decoder
)

echo.
echo [2/4] Executing Native Workflow Deployment and Workspace Verification...
"D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" "%~dp0..\scripts\deploy_workflows.py"
"D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" "%~dp0..\runtime\prompt_bridge\workspace_manager.py"
echo.

echo [3/4] Checking Local ComfyUI Server Instance...
powershell -Command "$stats = try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2).StatusCode } catch { 0 }; if ($stats -ne 200) { Write-Host '[ComfyUI] Launching local ComfyUI GPU process...'; Start-Process -FilePath 'D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\run_nvidia_gpu.bat' -WorkingDirectory 'D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable' }"

echo.
echo [4/4] Polling ComfyUI API Health (http://127.0.0.1:8188/system_stats)...
:POLL_LOOP
powershell -Command "$resp = try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2).StatusCode } catch { 0 }; exit $resp"
if %errorlevel% equ 200 (
    echo [PASS] ComfyUI Server is READY!
    goto OPEN_BROWSER
)
echo [WAIT] Waiting for ComfyUI API initialization... (Polling /system_stats)
powershell -Command "Start-Sleep -Seconds 2"
goto POLL_LOOP

:OPEN_BROWSER
echo.
echo =======================================================================
echo   Opening Architect Studio in browser...
echo =======================================================================
start http://127.0.0.1:8188
echo.
