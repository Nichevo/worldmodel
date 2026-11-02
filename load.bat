@echo off
rem Load files you downloaded yourself (sites that block scripts, or need a sign-in),
rem then build and check a new warehouse. Save each file in its source's folder in
rem var\manual\ (each folder has a note on where to get the file), then in PowerShell:
rem   .\load.bat                 load every folder in var\manual that has a file
rem   .\load.bat rbnz            load one source's folder
rem   .\load.bat emdat "D:\Downloads\emdat.xlsx"   load a file from elsewhere; it is copied into var\manual\emdat
rem Loading the same file twice changes nothing.
cd /d "%~dp0"
call "%~dp0scripts\find-conda.bat" || exit /b 1
call "%CONDA_BAT%" activate worldmodel || (echo Run setup.bat first. & exit /b 1)
if "%~1"=="" (
  worldmodel-data load
) else if "%~2"=="" (
  worldmodel-data load %1
) else (
  worldmodel-data load %1 "%~f2"
)
if errorlevel 1 (
  echo.
  echo Some files did not load; see above. Building with what did.
)
worldmodel-data build
if errorlevel 1 (
  echo.
  echo The build did not pass its checks; see above and the Data status page. The app keeps the last good build.
  exit /b 1
)
echo.
echo Loaded. Reload the app to see it.
exit /b 0
