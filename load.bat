@echo off
rem Load a file you downloaded yourself into a source, then build and check a new
rem warehouse. For sources that cannot be downloaded for you, such as EM-DAT
rem (it needs a free sign-in). Run from this folder, for example in PowerShell:
rem   .\load.bat emdat "D:\Downloads\public_emdat_custom_request_2025-06-01.xlsx"
rem Loading the same file twice changes nothing.
cd /d "%~dp0"
if "%~2"=="" (
  echo Usage: load.bat SOURCE FILE   ^(for example: load.bat emdat D:\Downloads\emdat.xlsx^)
  exit /b 1
)
call "%~dp0scripts\find-conda.bat" || exit /b 1
call "%CONDA_BAT%" activate worldmodel || (echo Run setup.bat first. & exit /b 1)
worldmodel-data fetch %1 --from "%~f2" || exit /b 1
worldmodel-data build
if errorlevel 1 (
  echo.
  echo The build did not pass its checks; see above and the Data status page. The app keeps the last good build.
  exit /b 1
)
echo.
echo Loaded. Reload the app to see it.
exit /b 0
