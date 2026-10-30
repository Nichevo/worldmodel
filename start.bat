@echo off
rem Start the API and the web app, each in its own window, then open the browser.
rem Run from this folder (PowerShell: .\start.bat). Close the two windows to stop.
cd /d "%~dp0"
call "%~dp0scripts\find-conda.bat" || exit /b 1
call "%CONDA_BAT%" activate worldmodel || (echo Run setup.bat first. & exit /b 1)
start "worldmodel API" cmd /k worldmodel-api
start "worldmodel web" /d "%~dp0app\web" cmd /k npm run dev
echo Waiting for the app to start...
timeout /t 10 /nobreak >nul
start "" http://localhost:3030
