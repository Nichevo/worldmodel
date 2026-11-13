@echo off
rem Sites that turn programs away with an "are you a person?" check (RBNZ, MBIE, UN, WTO,
rem CrisisWatch): opens each page in your own Edge (or Chrome) window. Complete any check
rem yourself; each page or file is saved into var\manual and loaded, then the app is rebuilt.
rem   .\verify.bat                 every such site
rem   .\verify.bat rbnz crisiswatch   only these
rem   .\verify.bat crisiswatch_pdf   the CrisisWatch PDF archive since 2003, 40 PDFs a run
cd /d "%~dp0"
rem It always waits for a key at the end, so a window opened by a double-click stays open to be read.
echo Verify: starting in %CD%
if /i "%CONDA_DEFAULT_ENV%"=="worldmodel" (
  echo Using the worldmodel environment already active.
) else (
  echo Finding conda...
  call "%~dp0scripts\find-conda.bat" || (echo Could not find conda; run this from an Anaconda Prompt. & goto :fail)
  echo Activating the worldmodel environment...
  call "%CONDA_BAT%" activate worldmodel || (echo Could not activate the worldmodel environment; run setup.bat first. & goto :fail)
)
where worldmodel-data >nul 2>nul || (echo worldmodel-data is not installed in this environment; run update.bat first. & goto :fail)
worldmodel-data verify %*
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="1" (
  echo.
  echo Nothing was saved; see above. The app keeps what it had.
  goto :fail
)
echo.
echo Building the warehouse...
worldmodel-data build
if errorlevel 1 (
  echo.
  echo The build did not pass its checks; see above and the Data status page. The app keeps the last good build.
  goto :fail
)
echo.
if "%RESULT%"=="3" (echo Done, but some files did not load; see above.) else (echo Done. Reload the app to see it.)
goto :end

:fail
echo. & pause
exit /b 1

:end
echo. & pause
exit /b 0
