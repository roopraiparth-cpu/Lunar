@echo off
title Lunar Server
cd /d C:\Users\Parth\Lunar

echo ================================================
echo    LUNAR  -  local voice assistant
echo.
echo    Keep this window OPEN while using Lunar.
echo    Closing this window stops the server.
echo ================================================
echo.

rem -- Stop any Lunar server that is already running --
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Parth\Lunar\kill-server.ps1" >nul 2>&1
timeout /t 2 /nobreak >nul

rem -- Pick a Python: the py launcher, or the project venv --
set "PYEXE=py"
where py >nul 2>&1 || set "PYEXE=C:\Users\Parth\Lunar\.venv\Scripts\python.exe"

rem -- Open the Lunar UI in the browser as soon as the server answers --
start "Lunar UI opener" /min powershell.exe -NoProfile -Command "$u='http://127.0.0.1:8765'; for($i=0; $i -lt 40; $i++){ try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -eq 200) { Start-Process $u; break } } catch {}; Start-Sleep -Milliseconds 500 }"

rem -- Run the server in this window (blocking) --
"%PYEXE%" main.py
