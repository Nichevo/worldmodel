@echo off
rem Fetch every data source, then build and check a new warehouse. Run from this
rem folder (PowerShell: .\refresh.bat). The app can stay running: it switches to
rem the new build once it passes its checks, and keeps the old one if not.
rem Each run is logged for the charts on the Data status page.
cd /d "%~dp0"
call "%~dp0scripts\find-conda.bat" || exit /b 1
call "%CONDA_BAT%" activate worldmodel || (echo Run setup.bat first. & exit /b 1)
worldmodel-data refresh %*
if errorlevel 1 (
  echo.
  echo Refresh did not finish cleanly; see the messages above. The app keeps showing the last good build.
  exit /b 1
)
echo.
echo Refresh done. Reload the app to see the new data; details are on the Data status page.
exit /b 0
