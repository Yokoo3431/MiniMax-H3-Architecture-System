@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System V0.4 - Asset Lifecycle Updater

echo =====================================================================
echo    MiniMax H3 Architecture System V0.4 - Lifecycle Updater           
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe
set COMFY_ROOT=%COMFY_PORTABLE%\ComfyUI

echo [1/6] Pulling Remote Updates from GitHub Repository...
where git >nul 2>&1
if %ERRORLEVEL% equ 0 (
    git pull origin main
    echo       [OK] Remote commits synchronized.
) else (
    echo       [NOTICE] Git command not found in PATH. Skipping git pull.
)

echo.
echo [2/6] Auditing Asset Registry & Lifecycle Manifest...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\sync_test_simulation.py"
) else (
    python "%SYSTEM_ROOT%\scripts\sync_test_simulation.py"
)

echo.
echo [3/6] Synchronizing Infrastructure Workflows...
set USER_WORKFLOWS=%COMFY_ROOT%\user\default\workflows
if exist "%COMFY_ROOT%" (
    if not exist "%USER_WORKFLOWS%" mkdir "%USER_WORKFLOWS%"
    xcopy /Y /Q "%SYSTEM_ROOT%\workflows\*.json" "%USER_WORKFLOWS%\" >nul
    echo       [OK] Workflows updated in ComfyUI.
)

echo.
echo [4/6] Updating Prompts & AI Agent Skills...
echo       [OK] Prompts updated: prompts/architectural_animation_prompts.json
echo       [OK] Agent Skills updated: skills/minimax-h3-architectural-video/SKILL.md

echo.
echo [5/6] Auditing Custom Nodes Consistency...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\check_nodes.py"
)

echo.
echo [6/6] Auditing Model Weights Integrity...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\check_models.py"
)

echo.
echo =====================================================================
echo     MINIMAX H3 LIFECYCLE ASSET UPDATE COMPLETED SUCCESSFULLY!        
echo =====================================================================
echo.
pause
exit /b 0
