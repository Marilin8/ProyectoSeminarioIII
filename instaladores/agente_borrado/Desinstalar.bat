@echo off
rem Desinstalador del agente de borrado - Clinica de Imagenes
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0desinstalar.ps1" %*
echo.
pause
