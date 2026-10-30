@echo off
rem Bring this copy up to date: the latest code from GitHub, then any new Python
rem and web packages. Your data in var\ is never touched. Run from an Anaconda
rem Prompt in this folder, with the app stopped.
setlocal
cd /d "%~dp0"
call conda activate worldmodel || (echo Run setup.bat first. & exit /b 1)
echo Fetching the latest code...
for /f %%i in ('git rev-parse HEAD') do set BEFORE=%%i
git checkout -q main || goto :fail
git pull --ff-only origin main || goto :fail
git diff --quiet %BEFORE% HEAD -- environment.yml || set ENVCHANGED=1
echo Installing Python packages...
python -m pip install -q -e contract -e "data[test]" -e "app/api[test]" || goto :fail
echo Installing web packages...
pushd app\web
call npm install --no-fund --no-audit || (popd & goto :fail)
popd
echo.
echo Up to date:
git log -1 --format="  %%h %%s (%%cr)"
if defined ENVCHANGED echo NOTE: environment.yml changed; run setup.bat once before starting.
echo Start the app with: start.bat
exit /b 0

:fail
echo.
echo Update stopped; see the message above. Nothing in var\ was changed.
exit /b 1
