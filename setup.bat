@echo off
rem First-time setup on Windows. Run from this folder (PowerShell: .\setup.bat).
rem Creates the "worldmodel" conda environment (Python, Node, Git), keeps your
rem data in this folder's var\, then installs everything via update.bat.
setlocal
cd /d "%~dp0"
call "%~dp0scripts\find-conda.bat" || exit /b 1
call "%CONDA_BAT%" env list | findstr /b /c:"worldmodel " >nul
if errorlevel 1 (
  echo Creating the worldmodel conda environment...
  call "%CONDA_BAT%" env create -f environment.yml || goto :fail
) else (
  echo Updating the worldmodel conda environment...
  call "%CONDA_BAT%" env update -n worldmodel -f environment.yml || goto :fail
)
call "%CONDA_BAT%" env config vars set -n worldmodel WORLDMODEL_HOME=%~dp0var >nul || goto :fail
call "%~dp0update.bat" || goto :fail
echo.
echo Setup done. Data will be kept in %~dp0var
echo Start the app with: start.bat
exit /b 0

:fail
echo.
echo Setup stopped; see the message above.
exit /b 1
