@echo off
rem Sites that turn programs away with an "are you a person?" check (RBNZ, MBIE, UN, WTO,
rem CrisisWatch): opens each page in your own Edge (or Chrome) window. Complete any check
rem yourself; each page or file is saved into var\manual and loaded, then the app is rebuilt.
rem   .\verify.bat                 every such site
rem   .\verify.bat rbnz crisiswatch   only these
cd /d "%~dp0"
echo Verify: starting in %CD%
if /i "%CONDA_DEFAULT_ENV%"=="worldmodel" (
  echo Using the worldmodel environment already active.
) else (
  echo Finding conda...
  call "%~dp0scripts\find-conda.bat" || (echo Could not find conda; run this from an Anaconda Prompt. & exit /b 1)
  echo Activating the worldmodel environment...
  call "%CONDA_BAT%" activate worldmodel || (echo Could not activate the worldmodel environment; run setup.bat first. & exit /b 1)
)
where worldmodel-data >nul 2>nul || (echo worldmodel-data is not installed in this environment; run update.bat first. & exit /b 1)
worldmodel-data verify %*
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="1" (
  echo.
  echo Nothing was saved; see above. The app keeps what it had.
  exit /b 1
)
echo.
echo Building the warehouse...
worldmodel-data build
if errorlevel 1 (
  echo.
  echo The build did not pass its checks; see above and the Data status page. The app keeps the last good build.
  exit /b 1
)
echo.
if "%RESULT%"=="3" (echo Done, but some files did not load; see above.) else (echo Done. Reload the app to see it.)
exit /b 0
