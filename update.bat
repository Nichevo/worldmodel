@echo off
rem Bring this copy up to date: the latest code from GitHub, then any new Python
rem and web packages. Downloaded data in var\ is never touched; if the new code
rem reads a newer warehouse format, the warehouse is rebuilt from that data (no
rem download). Run from this folder (PowerShell: .\update.bat), with the app stopped.
rem It waits for a key at the end so the messages stay on screen.
rem git pull may rewrite this file while cmd is still reading it, so run from a
rem copy in %TEMP% and keep the original untouched while it runs.
if not "%~1"=="--from-copy" (
  copy /y "%~f0" "%TEMP%\worldmodel-update.bat" >nul
  call "%TEMP%\worldmodel-update.bat" --from-copy "%~dp0."
  exit /b
)
setlocal
cd /d "%~f2"
call scripts\find-conda.bat || exit /b 1
call "%CONDA_BAT%" activate worldmodel || (echo Run setup.bat first. & exit /b 1)
echo Fetching the latest code...
for /f %%i in ('git rev-parse HEAD') do set BEFORE=%%i
rem npm rewrites the web lock file on some machines; it is generated, so drop that
rem change rather than let it block the pull.
git checkout -q -- app/web/package-lock.json 2>nul
rem .env.example is only a template (keys go in .env). If it was edited here, keep the
rem edited copy as .env.example.mine, and as .env when there is none yet, then take the new one.
git diff --quiet -- .env.example 2>nul || (
  copy /y .env.example .env.example.mine >nul
  if not exist .env copy /y .env.example .env >nul
  git checkout -q -- .env.example
  echo NOTE: your changes to .env.example are kept in .env.example.mine. The app reads keys from .env only.
)
git checkout -q main || goto :fail
git pull --ff-only origin main || goto :fail
git diff --quiet %BEFORE% HEAD -- environment.yml || set ENVCHANGED=1
echo Installing Python packages...
python -m pip install -q -e contract -e "data[test]" -e "app/api[test]" -e "client[mcp,test]" || goto :fail
echo Installing web packages...
pushd app\web
call npm install --no-fund --no-audit || (popd & goto :fail)
popd
git checkout -q -- app/web/package-lock.json 2>nul
echo Checking the warehouse format...
rem Back up your saved files, settings and keys first (Settings > Looking after the data; once a day at most).
worldmodel-data backup --auto || echo The backup did not finish; carrying on.
worldmodel-data upgrade || set UPGRADEFAILED=1
echo.
echo Up to date:
git log -1 --format="  %%h %%s (%%cr)"
if defined ENVCHANGED echo NOTE: environment.yml changed; run setup.bat once before starting.
if defined UPGRADEFAILED goto :notbuilt
echo Start the app with: start.bat
call :hold
exit /b 0

:notbuilt
echo.
echo The code is up to date, but the warehouse could not be rebuilt from the stored data
echo (the message above says why; a file ending -stopped.txt in var\warehouse\reports has the
echo details when the build stopped without a report). Copy the messages above when you ask for help.
echo The app keeps the last good build, but it may not open with the new code until a rebuild passes.
call :hold
exit /b 1

:fail
echo.
echo Update stopped; see the message above. Nothing in var\ was changed.
call :hold
exit /b 1

:hold
rem Keep the window open so the messages can be read (setup.bat sets WM_NO_PAUSE when it calls this).
if not defined WM_NO_PAUSE (echo. & pause)
exit /b 0
