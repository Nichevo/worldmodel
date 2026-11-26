@echo off
rem Start the API and the web app, each in its own window, then open the browser.
rem Run from this folder (PowerShell: .\start.bat). Close the two windows to stop;
rem running it again while the app is up restarts it.
cd /d "%~dp0"
call "%~dp0scripts\find-conda.bat" || exit /b 1
call "%CONDA_BAT%" activate worldmodel || (echo Run setup.bat first. & exit /b 1)
call :free 3030 || exit /b 1
call :free 8000 || exit /b 1
start "worldmodel API" cmd /k worldmodel-api
rem Windows' own timeout.exe and curl.exe by full path: a conda env or Git can put Unix ones first on PATH.
set "WAIT=%SystemRoot%\System32\timeout.exe"
set "CURL=%SystemRoot%\System32\curl.exe"
rem The built web app (fast) unless Settings > How the web app runs > Development mode is on;
rem built first when the code changed since the last build, and development mode if that fails.
set "WEB=dev"
for /f %%m in ('call "%~dp0scripts\web-build.bat" --check') do set "WEB=%%m"
if "%WEB%"=="build" (
  call "%~dp0scripts\web-build.bat" && set "WEB=prod" || set "WEB=dev"
)
rem The web app passes every /api call on to the API, so it starts once the API answers
rem (the API can take a while to start after a reboot); otherwise its first pages fail.
echo Waiting for the API to start...
for /l %%n in (1,1,120) do (
  "%CURL%" -s -o nul http://127.0.0.1:8000/health 2>nul && goto apiready
  "%WAIT%" /t 1 /nobreak >nul
)
echo The API has not answered after two minutes. Look in the "worldmodel API" window for an error;
echo the web app starts anyway and its pages work once the API is up.
:apiready
if "%WEB%"=="prod" (
  start "worldmodel web" /d "%~dp0app\web" cmd /k npm run start
) else (
  start "worldmodel web" /d "%~dp0app\web" cmd /k npm run dev
)
echo Waiting for the web app to start...
for /l %%n in (1,1,90) do (
  "%CURL%" -s -o nul http://localhost:3030 2>nul && goto ready
  "%WAIT%" /t 1 /nobreak >nul
)
echo The web app has not answered yet; it may still be starting. Check the "worldmodel web" window.
:ready
echo From other PCs on your network: http://%COMPUTERNAME%:3030
start "" http://localhost:3030
exit /b 0

rem Free a port held by a copy of this app still running from last time (node or
rem python only); anything else on the port is reported instead of stopped.
:free
for /f "tokens=5" %%i in ('netstat -ano ^| findstr /r /c:":%1  *[^ ]*  *LISTENING"') do (
  tasklist /fi "pid eq %%i" /nh 2>nul | findstr /i "node.exe python.exe worldmodel-api.exe" >nul
  if not errorlevel 1 (
    echo Stopping the copy still running on port %1...
    taskkill /pid %%i /t /f >nul 2>nul
    "%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
  ) else (
    tasklist /fi "pid eq %%i" /nh 2>nul | findstr /c:" %%i " >nul
    if not errorlevel 1 (
      echo Port %1 is used by another program ^(process %%i^). Close it, then run start.bat again.
      exit /b 1
    )
  )
)
exit /b 0
