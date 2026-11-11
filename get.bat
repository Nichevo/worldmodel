@echo off
rem Get every file that is due to be saved by hand, in one go: opens each source's download
rem page in your browser, one tab each, then watches var\inbox and your Downloads folder.
rem You click Download (and sign in where a site asks); each file is filed into its
rem source's folder and loaded as it arrives, and the app is rebuilt at the end.
rem   .\get.bat                 every file that is due (the To do page lists them)
rem   .\get.bat emdat rbnz      only these
cd /d "%~dp0"
call "%~dp0scripts\find-conda.bat" || exit /b 1
call "%CONDA_BAT%" activate worldmodel || (echo Run setup.bat first. & exit /b 1)
worldmodel-data get %*
if errorlevel 1 (
  echo.
  echo Some files did not load; see above. The app keeps what it had.
  exit /b 1
)
echo.
echo Done. Reload the app to see the new data.
exit /b 0
