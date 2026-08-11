@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System V0.4 - System Diagnostic Audit

echo =====================================================================
echo    MiniMax H3 Architecture System V0.4 - System Diagnostics Audit     
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe

echo [1/3] Running Hardware HAL Inspection...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\hardware\detect_gpu.py"
) else (
    python "%SYSTEM_ROOT%\hardware\detect_gpu.py"
)

echo.
echo [2/3] Generating System Diagnostic Audit Report (docs/diagnostic_report.md)...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\generate_diagnostics.py"
) else (
    python "%SYSTEM_ROOT%\scripts\generate_diagnostics.py"
)

echo.
echo [3/3] Diagnostic Report Created at docs/diagnostic_report.md
echo =====================================================================
echo           DIAGNOSTIC INSPECTION COMPLETED SUCCESSFULLY!              
echo =====================================================================
echo.
pause
exit /b 0
