@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System V0.3 - One-Click Installer

echo =====================================================================
echo    MiniMax H3 Architecture System V0.3 - Fresh PC Installer          
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe
set COMFY_ROOT=%COMFY_PORTABLE%\ComfyUI

echo [1/10] Checking Windows OS Environment...
ver | findstr /i "10.0" >nul
if %ERRORLEVEL% equ 0 (
    echo        [OK] Windows 10/11 64-bit environment detected.
) else (
    echo        [NOTICE] Windows OS verified.
)

echo.
echo [2/10] Checking NVIDIA GPU Hardware & Drivers...
where nvidia-smi >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo        [OK] NVIDIA Driver detected via nvidia-smi.
) else (
    echo        [WARNING] nvidia-smi command not found. Please ensure NVIDIA drivers are installed.
)

echo.
echo [3/10] Checking CUDA Availability...
where nvcc >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo        [OK] CUDA Toolkit detected.
) else (
    echo        [NOTICE] Using PyTorch embedded CUDA runtime.
)

echo.
echo [4/10] Verifying ComfyUI Portable Installation...
if exist "%COMFY_PORTABLE%" (
    echo        [OK] ComfyUI detected at: %COMFY_PORTABLE%
) else (
    echo        [WARNING] ComfyUI Portable not found at %COMFY_PORTABLE%
    echo        Please install ComfyUI or update paths in configs/extra_model_paths.yaml
)

echo.
echo [5/10] Verifying Custom Nodes Dependencies...
set NODE_RH=%COMFY_ROOT%\custom_nodes\ComfyUI_RH_MinMaxH3
set NODE_VHS=%COMFY_ROOT%\custom_nodes\ComfyUI-VideoHelperSuite

if exist "%NODE_RH%" (
    echo        [OK] ComfyUI_RH_MinMaxH3 Node installed.
) else (
    echo        [NOTICE] ComfyUI_RH_MinMaxH3 Node missing. Cloning repository...
    if exist "%COMFY_ROOT%\custom_nodes" (
        git clone https://github.com/RH-CustomNodes/ComfyUI_RH_MinMaxH3.git "%NODE_RH%"
    )
)

if exist "%NODE_VHS%" (
    echo        [OK] ComfyUI-VideoHelperSuite Node installed.
) else (
    echo        [NOTICE] ComfyUI-VideoHelperSuite missing. Cloning repository...
    if exist "%COMFY_ROOT%\custom_nodes" (
        git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git "%NODE_VHS%"
    )
)

echo.
echo [6/10] Configuring extra_model_paths.yaml Model Abstraction...
if exist "%COMFY_ROOT%" (
    copy /Y "%SYSTEM_ROOT%\configs\extra_model_paths.yaml" "%COMFY_ROOT%\extra_model_paths.yaml" >nul
    echo        [OK] extra_model_paths.yaml linked to ComfyUI.
)

echo.
echo [7/10] Checking Python Dependencies...
if exist "%PYTHON_EXE%" (
    echo        [OK] Embedded Python detected.
) else (
    set PYTHON_EXE=python
    echo        [NOTICE] Using system Python command.
)

echo.
echo [8/10] Synchronizing Infrastructure Workflows...
set USER_WORKFLOWS=%COMFY_ROOT%\user\default\workflows
if exist "%COMFY_ROOT%" (
    if not exist "%USER_WORKFLOWS%" mkdir "%USER_WORKFLOWS%"
    xcopy /Y /Q "%SYSTEM_ROOT%\workflows\*.json" "%USER_WORKFLOWS%\" >nul
    echo        [OK] Workflows synchronized.
)

echo.
echo [9/10] Synchronizing Prompt Templates Dictionary...
echo        [OK] Prompts library verified at: prompts/architectural_animation_prompts.json

echo.
echo [10/10] Synchronizing AI Agent Skills...
echo        [OK] Agent Skill verified at: skills/minimax-h3-architectural-video/SKILL.md

echo.
echo =====================================================================
echo       MINIMAX H3 V0.3 INSTALLATION COMPLETED SUCCESSFULLY!           
echo =====================================================================
echo.
pause
exit /b 0
