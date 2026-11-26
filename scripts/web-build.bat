@echo off
rem Build the web app (app\web\.next) for start.bat's fast mode, unless Settings > How the web app
rem runs > Development mode is on, or it is already built from this exact code. Called by
rem update.bat, setup.bat and start.bat with the worldmodel environment active.
rem   scripts\web-build.bat          build when needed
rem   scripts\web-build.bat --check  only say: "prod" (ready), "build" (needs one) or "dev"
setlocal
cd /d "%~dp0.."
for /f "usebackq" %%m in (`python -c "from worldmodel_contract import local; print('dev' if local.load_settings().get('web_dev_mode') else 'prod')" 2^>nul`) do set MODE=%%m
if not defined MODE set MODE=prod
if "%MODE%"=="dev" (
  if "%~1"=="--check" echo dev
  exit /b 0
)
for /f %%i in ('git rev-parse HEAD 2^>nul') do set HEAD=%%i
set BUILT=
if exist "app\web\.next\BUILD_ID" if exist "app\web\.next\worldmodel-built-from.txt" set /p BUILT=<"app\web\.next\worldmodel-built-from.txt"
if "%~1"=="--check" (
  if "%BUILT%"=="%HEAD%" (echo prod) else (echo build)
  exit /b 0
)
if "%BUILT%"=="%HEAD%" exit /b 0
echo Building the web app (about a minute; once after each update)...
pushd app\web
set NEXT_TELEMETRY_DISABLED=1
call npm run build >"%TEMP%\worldmodel-web-build.log" 2>&1
if errorlevel 1 (
  popd
  echo The web app could not be built; start.bat will use development mode. Details: %TEMP%\worldmodel-web-build.log
  exit /b 1
)
popd
>"app\web\.next\worldmodel-built-from.txt" echo %HEAD%
echo Web app built.
exit /b 0
