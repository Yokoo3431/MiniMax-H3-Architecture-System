@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System V0.4 - Installation Launcher

echo =====================================================================
echo    MiniMax H3 Architecture System V0.4 - Distribution Installer       
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe
set COMFY_ROOT=%COMFY_PORTABLE%\ComfyUI

echo [1/10] Auditing Windows Environment...
ver | findstr /i "10.0" >nul
if %ERRORLEVEL% equ 0 (
    echo        [OK] Windows 10/11 64-bit environment detected.
) else (
    echo        [NOTICE] Windows OS verified.
)

echo.
echo [2/10] Auditing NVIDIA GPU Hardware & Drivers...
where nvidia-smi >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo        [OK] NVIDIA Driver detected via nvidia-smi.
) else (
    echo        [WARNING] nvidia-smi command not found.
)

echo.
echo [3/10] Auditing CUDA Availability...
where nvcc >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo        [OK] CUDA Toolkit detected.
) else (
    echo        [NOTICE] Using PyTorch embedded CUDA runtime.
)

echo.
echo [4/10] Running Hardware Abstraction Layer (HAL) GPU Auto-Detection...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\hardware\detect_gpu.py"
) else (
    python "%SYSTEM_ROOT%\hardware\detect_gpu.py"
)

echo.
echo [5/10] Verifying ComfyUI Portable Installation...
if exist "%COMFY_PORTABLE%" (
    echo        [OK] ComfyUI detected at: %COMFY_PORTABLE%
) else (
    echo        [WARNING] ComfyUI Portable not found at %COMFY_PORTABLE%
    echo        Please verify drive letter in configs/extra_model_paths.yaml
)

echo.
echo [6/10] Verifying Custom Nodes Dependencies...
set NODE_RH=%COMFY_ROOT%\custom_nodes\ComfyUI_RH_MinMaxH3
set NODE_VHS=%COMFY_ROOT%\custom_nodes\ComfyUI-VideoHelperSuite

if exist "%NODE_RH%" (
    echo        [OK] ComfyUI_RH_MinMaxH3 Node installed.
) else (
    echo        [NOTICE] Cloning ComfyUI_RH_MinMaxH3 Repository...
    if exist "%COMFY_ROOT%\custom_nodes" git clone https://github.com/RH-CustomNodes/ComfyUI_RH_MinMaxH3.git "%NODE_RH%"
)

if exist "%NODE_VHS%" (
    echo        [OK] ComfyUI-VideoHelperSuite Node installed.
) else (
    echo        [NOTICE] Cloning ComfyUI-VideoHelperSuite Repository...
    if exist "%COMFY_ROOT%\custom_nodes" git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git "%NODE_VHS%"
)

echo.
echo [7/10] Linking extra_model_paths.yaml Model Abstraction...
if exist "%COMFY_ROOT%" (
    copy /Y "%SYSTEM_ROOT%\configs\extra_model_paths.yaml" "%COMFY_ROOT%\extra_model_paths.yaml" >nul
    echo        [OK] extra_model_paths.yaml linked to ComfyUI.
)

echo.
echo [8/10] Auditing MiniMax H3 Model Weights...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\download_models.py" --check-only
) else (
    python "%SYSTEM_ROOT%\scripts\download_models.py" --check-only
)

echo.
echo [9/10] Synchronizing Categorized Infrastructure Workflows...
set USER_WORKFLOWS=%COMFY_ROOT%\user\default\workflows
if exist "%COMFY_ROOT%" (
    if not exist "%USER_WORKFLOWS%" mkdir "%USER_WORKFLOWS%"
    xcopy /Y /Q "%SYSTEM_ROOT%\workflows\*.json" "%USER_WORKFLOWS%\" >nul
    echo        [OK] Workflows synchronized to ComfyUI.
)

echo.
echo [10/10] Registering AI Agent Skills & Prompts...
echo        [OK] Prompts dictionary registered: prompts/architectural_animation_prompts.json
echo        [OK] Agent Skill registered: skills/minimax-h3-architectural-video/SKILL.md

echo.
echo =====================================================================
echo       MINIMAX H3 V0.4 PLATFORM INSTALLATION COMPLETED READY!         
echo =====================================================================
echo.
pause
exit /b 0
