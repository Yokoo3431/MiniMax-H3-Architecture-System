@echo off
title MiniMax H3 Architect One-Click Launcher V0.8.0-RC2
color 0A

echo =======================================================================
echo         MiniMax H3 Architecture System Architect One-Click Launcher
echo                     Version V0.8.0-RC2 Daily Usage Package
echo =======================================================================
echo.

echo [1/3] Initializing Architect Personal Workspace...
"D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\python_embeded\python.exe" "%~dp0..\runtime\prompt_bridge\workspace_manager.py"
echo.

echo [2/3] Checking ComfyUI Server Health on http://127.0.0.1:8188...
powershell -Command "try { $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2; Write-Host '[PASS] ComfyUI Server is active on http://127.0.0.1:8188' } catch { Write-Host '[NOTE] Starting local ComfyUI instance...'; Start-Process -FilePath 'D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable\run_nvidia_gpu.bat' -WorkingDirectory 'D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable' }"

echo.
echo [3/3] Opening Architect ComfyUI Studio in default browser...
timeout /t 2 >nul
start http://127.0.0.1:8188

echo.
echo =======================================================================
echo   Architect Environment Ready! Please select one of 5 frozen workflows:
echo   1. 01_Exterior_Hero.json
echo   2. 02_Day_Night_Transition.json
echo   3. 03_Material_Detail.json
echo   4. 04_Drone_Aerial.json
echo   5. 05_Slow_Walkthrough.json
echo =======================================================================
echo.
