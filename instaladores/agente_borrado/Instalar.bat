@echo off
rem Instalador del agente de borrado - Clinica de Imagenes
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" %*
echo.
pause
