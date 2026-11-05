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
start "worldmodel web" /d "%~dp0app\web" cmd /k npm run dev
rem Windows' own timeout.exe by full path: a conda env or Git can put a Unix "timeout" first on PATH.
set "WAIT=%SystemRoot%\System32\timeout.exe"
echo Waiting for the app to start...
for /l %%n in (1,1,90) do (
  "%SystemRoot%\System32\curl.exe" -s -o nul http://localhost:3030 2>nul && goto ready
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
