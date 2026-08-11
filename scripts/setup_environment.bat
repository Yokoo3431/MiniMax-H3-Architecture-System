@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System - Environment Recovery Script

echo =====================================================================
echo    MiniMax H3 Architecture Infrastructure - Environment Restoration  
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe
set COMFY_ROOT=%COMFY_PORTABLE%\ComfyUI

echo [1/5] Checking ComfyUI Portable Root Directory...
if exist "%COMFY_PORTABLE%" (
    echo       [OK] ComfyUI Portable detected at: %COMFY_PORTABLE%
) else (
    echo       [ERROR] ComfyUI Portable not found at %COMFY_PORTABLE%!
    echo       Please check drive letter or update configs/extra_model_paths.yaml
    goto FAIL
)

echo.
echo [2/5] Checking Python Embedded Environment...
if exist "%PYTHON_EXE%" (
    echo       [OK] Embedded Python detected.
) else (
    echo       [ERROR] Embedded Python executable missing!
    goto FAIL
)

echo.
echo [3/5] Checking Custom Nodes Dependencies...
set NODE_RH=%COMFY_ROOT%\custom_nodes\ComfyUI_RH_MinMaxH3
set NODE_VHS=%COMFY_ROOT%\custom_nodes\ComfyUI-VideoHelperSuite
set NODE_MGR=%COMFY_ROOT%\custom_nodes\ComfyUI-Manager

if exist "%NODE_RH%" (
    echo       [OK] ComfyUI_RH_MinMaxH3 Node is installed.
) else (
    echo       [WARNING] ComfyUI_RH_MinMaxH3 Node is missing!
)

if exist "%NODE_VHS%" (
    echo       [OK] ComfyUI-VideoHelperSuite Node is installed.
) else (
    echo       [WARNING] ComfyUI-VideoHelperSuite Node is missing!
)

echo.
echo [4/5] Restoring extra_model_paths.yaml into ComfyUI...
copy /Y "%SYSTEM_ROOT%\configs\extra_model_paths.yaml" "%COMFY_ROOT%\extra_model_paths.yaml" >nul
if %ERRORLEVEL% equ 0 (
    echo       [OK] extra_model_paths.yaml successfully linked to ComfyUI.
) else (
    echo       [WARNING] Failed to copy extra_model_paths.yaml
)

echo.
echo [5/5] Syncing Infrastructure Workflows into ComfyUI User Workflows...
set USER_WORKFLOWS=%COMFY_ROOT%\user\default\workflows
if not exist "%USER_WORKFLOWS%" mkdir "%USER_WORKFLOWS%"
xcopy /Y /Q "%SYSTEM_ROOT%\workflows\*.json" "%USER_WORKFLOWS%\" >nul
echo       [OK] Workflows synchronized to ComfyUI.

echo.
echo =====================================================================
echo            ENVIRONMENT RESTORATION COMPLETED SUCCESSFULLY!           
echo =====================================================================
echo.
pause
exit /b 0

:FAIL
echo.
echo [ERROR] Environment Restoration Failed. Please check the logs above.
echo.
pause
exit /b 1
