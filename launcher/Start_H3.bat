@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System V0.4 - Runtime Launcher

echo =====================================================================
echo    MiniMax H3 Architecture System V0.4 - Runtime WebUI Launcher      
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe

echo [1/3] Running Hardware HAL Profile Check...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\hardware\detect_gpu.py"
)

echo.
echo [2/3] Launching ComfyUI Server Backend (Port 8188)...
echo       Starting daemon in background...
cd /d "%COMFY_PORTABLE%"
start "ComfyUI MiniMax H3 Server" "%PYTHON_EXE%" ComfyUI\main.py --lowvram --use-split-cross-attention --port 8188 --disable-auto-launch

echo.
echo [3/3] Opening WebUI in Browser...
timeout /t 3 >nul
start http://127.0.0.1:8188

echo.
echo =====================================================================
echo    MiniMax H3 WebUI Server is Running at http://127.0.0.1:8188      
echo =====================================================================
echo.
pause
