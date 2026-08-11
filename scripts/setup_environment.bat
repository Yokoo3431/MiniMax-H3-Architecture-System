@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System V0.2 - Environment Recovery Script

echo =====================================================================
echo    MiniMax H3 Architecture System V0.2 - Environment Restoration      
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe
set COMFY_ROOT=%COMFY_PORTABLE%\ComfyUI

echo [1/8] Checking ComfyUI Portable Root Directory...
if exist "%COMFY_PORTABLE%" (
    echo       [OK] ComfyUI Portable detected at: %COMFY_PORTABLE%
) else (
    echo       [WARNING] ComfyUI Portable not found at %COMFY_PORTABLE%
    echo       Please verify drive letter in configs/extra_model_paths.yaml
)

echo.
echo [2/8] Checking Embedded Python Executable...
if exist "%PYTHON_EXE%" (
    echo       [OK] Embedded Python detected.
) else (
    set PYTHON_EXE=python
    echo       [NOTICE] Using system Python command.
)

echo.
echo [3/8] Running Hardware Abstraction Layer (HAL) GPU Auto-Detection...
"%PYTHON_EXE%" "%SYSTEM_ROOT%\hardware\detect_gpu.py"
if %ERRORLEVEL% equ 0 (
    echo       [OK] GPU detection & machine profile matching complete.
) else (
    echo       [WARNING] GPU detection returned non-zero code.
)

echo.
echo [4/8] Running Custom Node Manifest Audit...
"%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\check_nodes.py"
if %ERRORLEVEL% equ 0 (
    echo       [OK] Custom Node manifest audit completed.
) else (
    echo       [WARNING] Custom Node audit found missing dependencies.
)

echo.
echo [5/8] Running Model Weight Manifest Audit...
"%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\check_models.py"
if %ERRORLEVEL% equ 0 (
    echo       [OK] Model manifest audit completed.
) else (
    echo       [WARNING] Model manifest audit found missing weights.
)

echo.
echo [6/8] Repairing & Linking extra_model_paths.yaml into ComfyUI...
if exist "%COMFY_ROOT%" (
    copy /Y "%SYSTEM_ROOT%\configs\extra_model_paths.yaml" "%COMFY_ROOT%\extra_model_paths.yaml" >nul
    echo       [OK] extra_model_paths.yaml linked to ComfyUI.
)

echo.
echo [7/8] Synchronizing Workflows into ComfyUI User Directory...
set USER_WORKFLOWS=%COMFY_ROOT%\user\default\workflows
if exist "%COMFY_ROOT%" (
    if not exist "%USER_WORKFLOWS%" mkdir "%USER_WORKFLOWS%"
    xcopy /Y /Q "%SYSTEM_ROOT%\workflows\*.json" "%USER_WORKFLOWS%\" >nul
    echo       [OK] Infrastructure workflows synchronized.
)

echo.
echo [8/8] Finalizing Environment Recovery Status...
echo =====================================================================
echo        MINIMAX H3 ENVIRONMENT RESTORATION READY FOR PRODUCTION       
echo =====================================================================
echo.
pause
exit /b 0
