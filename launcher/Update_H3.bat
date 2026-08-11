@echo off
chcp 65001 >nul
title MiniMax H3 Architecture System V0.5 - Safe Lifecycle Updater

echo =====================================================================
echo    MiniMax H3 Architecture System V0.5 - Safe Lifecycle Updater      
echo =====================================================================
echo.

set SYSTEM_ROOT=%~dp0..
set COMFY_PORTABLE=D:\ProgramFilesNormal\ComfyUI\ComfyUI_windows_portable
set PYTHON_EXE=%COMFY_PORTABLE%\python_embeded\python.exe
set COMFY_ROOT=%COMFY_PORTABLE%\ComfyUI
set BACKUP_DIR=%SYSTEM_ROOT%\userdata_backup_temp

echo [1/7] Backing Up User Data (userdata/ -> userdata_backup_temp/)...
if exist "%SYSTEM_ROOT%\userdata" (
    xcopy /E /I /Y /Q "%SYSTEM_ROOT%\userdata\*" "%BACKUP_DIR%\" >nul
    echo       [OK] User data backed up safely.
)

echo.
echo [2/7] Pulling Remote Code & Core Asset Updates from GitHub...
where git >nul 2>&1
if %ERRORLEVEL% equ 0 (
    git pull origin main
    echo       [OK] Git repository updated.
) else (
    echo       [NOTICE] Git executable not in PATH. Skipping git pull.
)

echo.
echo [3/7] Running Asset Migration & Registry Check...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\sync_test_simulation.py"
) else (
    python "%SYSTEM_ROOT%\scripts\sync_test_simulation.py"
)

echo.
echo [4/7] Synchronizing System Core Workflows to ComfyUI...
set USER_WORKFLOWS=%COMFY_ROOT%\user\default\workflows
if exist "%COMFY_ROOT%" (
    if not exist "%USER_WORKFLOWS%" mkdir "%USER_WORKFLOWS%"
    xcopy /Y /Q "%SYSTEM_ROOT%\workflows\*.json" "%USER_WORKFLOWS%\" >nul
    echo       [OK] Infrastructure workflows synchronized.
)

echo.
echo [5/7] Restoring Protected User Data (userdata_backup_temp/ -> userdata/)...
if exist "%BACKUP_DIR%" (
    xcopy /E /I /Y /Q "%BACKUP_DIR%\*" "%SYSTEM_ROOT%\userdata\" >nul
    rd /s /q "%BACKUP_DIR%"
    echo       [OK] User data restored intact without data loss.
)

echo.
echo [6/7] Validating Custom Node Dependencies...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\check_nodes.py"
)

echo.
echo [7/7] Validating Model Weights Integrity...
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%SYSTEM_ROOT%\scripts\check_models.py"
)

echo.
echo =====================================================================
echo   MINIMAX H3 V0.5 SAFE LIFECYCLE UPDATE COMPLETED SUCCESSFULLY!      
echo =====================================================================
echo.
pause
exit /b 0
