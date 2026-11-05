@echo off
rem Fetch World Prison Brief's figures for every country (one page per year, a few seconds
rem apart; the first run goes back to 2000, later runs fetch only the latest), then build.
rem   .\prisons.bat             latest figures (and the years not fetched yet)
rem   .\prisons.bat 1995        go back to 1995 instead of 2000
cd /d "%~dp0"
call "%~dp0scripts\find-conda.bat" || exit /b 1
call "%CONDA_BAT%" activate worldmodel || (echo Run setup.bat first. & exit /b 1)
if "%~1"=="" (
  worldmodel-data prisons
) else (
  worldmodel-data prisons --since %1
)
if errorlevel 1 exit /b 1
worldmodel-data build
if errorlevel 1 (
  echo.
  echo The build did not pass its checks; see above and the Data status page. The app keeps the last good build.
  exit /b 1
)
echo.
echo Done. Reload the app to see it.
