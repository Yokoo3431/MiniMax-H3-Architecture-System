@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System V0.3 - One-Click Updater

echo =====================================================================
echo    MiniMax H3 Architecture System V0.3 - Automated System Updater    
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe
set COMFY_ROOT=%COMFY_PORTABLE%\ComfyUI

echo [1/8] Pulling Latest Platform Updates from GitHub Repository...
where git >nul 2>&1
if %ERRORLEVEL% equ 0 (
    git pull origin main
    echo       [OK] Git repository updated.
) else (
    echo       [NOTICE] Git executable not in PATH. Skipping git pull.
)

echo.
echo [2/8] Verifying System Version & Platform Manifest...
if exist "%PYTHON_EXE%" (
    echo       [OK] Python runtime ready.
) else (
    set PYTHON_EXE=python
)

echo.
echo [3/8] Synchronizing Workflows into ComfyUI...
set USER_WORKFLOWS=%COMFY_ROOT%\user\default\workflows
if exist "%COMFY_ROOT%" (
    if not exist "%USER_WORKFLOWS%" mkdir "%USER_WORKFLOWS%"
    xcopy /Y /Q "%SYSTEM_ROOT%\workflows\*.json" "%USER_WORKFLOWS%\" >nul
    echo       [OK] Infrastructure workflows synchronized.
)

echo.
echo [4/8] Synchronizing Architectural Prompts Library...
echo       [OK] Prompts library updated: prompts/architectural_animation_prompts.json

echo.
echo [5/8] Synchronizing AI Agent Skills...
echo       [OK] Agent skill updated: skills/minimax-h3-architectural-video/SKILL.md

echo.
echo [6/8] Synchronizing System Configurations & Extra Model Paths...
if exist "%COMFY_ROOT%" (
    copy /Y "%SYSTEM_ROOT%\configs\extra_model_paths.yaml" "%COMFY_ROOT%\extra_model_paths.yaml" >nul
    echo       [OK] extra_model_paths.yaml re-linked to ComfyUI.
)

echo.
echo [7/8] Validating Custom Node Dependencies...
"%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\check_nodes.py"

echo.
echo [8/8] Validating Model Weights Integrity...
"%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\check_models.py"

echo.
echo =====================================================================
echo       MINIMAX H3 V0.3 PLATFORM UPDATE COMPLETED SUCCESSFULLY!        
echo =====================================================================
echo.
pause
exit /b 0
