@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "HUMIDITY_PARENT_RUN=%~1"
if not defined HUMIDITY_PARENT_RUN set "HUMIDITY_PARENT_RUN=humidity_results\20261108T191838_341211Z_5ea72a0b"
if not exist ".venv_regression\Scripts\python.exe" (
  echo Existing .venv_regression was not found. Extract this update next to ige_regression.py.
  pause
  exit /b 2
)
".venv_regression\Scripts\python.exe" ige_humidity.py recover --run "%HUMIDITY_PARENT_RUN%"
set "HUMIDITY_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Exit code %HUMIDITY_EXIT_CODE%. Results are in the new child run printed above.
echo The source run and downloaded data were preserved. C was not opened.
pause
exit /b %HUMIDITY_EXIT_CODE%
