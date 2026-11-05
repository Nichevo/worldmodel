@echo off
rem Read the sources that come from web pages now (politely: long gaps between pages, and
rem each site stops at its first problem), then build. Each step says what it is doing.
rem   .\scrape.bat                    every scraping source, one site after another
rem   .\scrape.bat prisons            only World Prison Brief (first run goes back to 2000)
rem   .\scrape.bat prisons 1995       World Prison Brief back to 1995
rem   .\scrape.bat crisiswatch vetoes wto treaties corrections elections   any of these
cd /d "%~dp0"
echo Scrape: starting in %CD%
if /i "%CONDA_DEFAULT_ENV%"=="worldmodel" (
  echo Using the worldmodel environment already active.
) else (
  echo Finding conda...
  call "%~dp0scripts\find-conda.bat" || (echo Could not find conda; run this from an Anaconda Prompt. & exit /b 1)
  echo Activating the worldmodel environment...
  call "%CONDA_BAT%" activate worldmodel || (echo Could not activate the worldmodel environment; run setup.bat first. & exit /b 1)
)
where worldmodel-data >nul 2>nul || (echo worldmodel-data is not installed in this environment; run update.bat first. & exit /b 1)
set "SINCE="
if /i "%~1"=="prisons" if not "%~2"=="" set "SINCE=--since %~2"
if defined SINCE (
  worldmodel-data scrape prisons %SINCE%
) else (
  worldmodel-data scrape %*
)
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="2" exit /b 2
if "%RESULT%"=="1" (
  echo.
  echo Nothing could be read; see above. The app keeps what it had.
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
if "%RESULT%"=="3" (
  echo Done, but some sites stopped early; see above and Data status, Sources read from web pages.
) else (
  echo Done. Reload the app to see it.
)
exit /b 0
