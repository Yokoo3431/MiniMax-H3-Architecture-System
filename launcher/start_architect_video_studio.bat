@echo off
setlocal
rem Backward-compatible developer wrapper. The root BAT is the only public entry.
call "%~dp0..\Start_ArchitectVideoStudio.bat" %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
