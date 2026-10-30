@echo off
rem Sets CONDA_BAT to conda's batch entry point, so setup.bat, update.bat and
rem start.bat also work from PowerShell or a plain Command Prompt, not only from
rem an Anaconda Prompt. Called by those scripts; not meant to be run directly.
set "CONDA_BAT="
for /f "delims=" %%p in ('where conda.bat 2^>nul') do if not defined CONDA_BAT set "CONDA_BAT=%%p"
if defined CONDA_BAT exit /b 0
if defined CONDA_EXE for %%d in ("%CONDA_EXE%\..\..") do if exist "%%~fd\condabin\conda.bat" set "CONDA_BAT=%%~fd\condabin\conda.bat"
if defined CONDA_BAT exit /b 0
set "ROOTS="%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%USERPROFILE%\miniforge3" "%LOCALAPPDATA%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3" "C:\anaconda3" "C:\miniconda3" "D:\anaconda3" "D:\miniconda3""
for %%r in (%ROOTS%) do if not defined CONDA_BAT if exist "%%~r\condabin\conda.bat" set "CONDA_BAT=%%~r\condabin\conda.bat"
set "ROOTS="
if defined CONDA_BAT exit /b 0
echo Conda not found. Install Miniconda or Anaconda, or run this from an Anaconda Prompt.
exit /b 1
