@echo off
title Lunar Web
rem Paths are derived from this script's own folder, so Lunar works wherever
rem the project is cloned and nothing here depends on a specific user account.
cd /d "%~dp0"

echo ================================================
echo    LUNAR WEB  -  local voice assistant in your browser
echo.
echo    Keep this window OPEN while using Lunar.
echo    Press Ctrl+C or use Exit in the page to stop.
echo ================================================
echo.

rem -- Stop any Lunar assistant that is already running --
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill-server.ps1" >nul 2>&1
timeout /t 2 /nobreak >nul

rem -- Pick a Python: the py launcher, or the project venv --
set "PYEXE=py"
where py >nul 2>&1 || set "PYEXE=%~dp0.venv\Scripts\python.exe"

rem -- Run the web app in this window (blocking) --
"%PYEXE%" web.py