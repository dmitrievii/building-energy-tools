@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
if exist ".venv_regression\Scripts\python.exe" (
  ".venv_regression\Scripts\python.exe" ige_humidity.py check-config --config config_humidity_comparison.json
) else (
  python ige_humidity.py check-config --config config_humidity_comparison.json
)
if errorlevel 1 goto config_fail
if not exist ".venv_regression\Scripts\python.exe" (
  python -m venv .venv_regression
  if errorlevel 1 goto fail
)
".venv_regression\Scripts\python.exe" -m pip install --timeout 60 --retries 5 -r requirements_regression.txt
if errorlevel 1 goto fail
".venv_regression\Scripts\python.exe" ige_humidity.py run --config config_humidity_comparison.json
set "HUMIDITY_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Exit code %HUMIDITY_EXIT_CODE%. See the new humidity_results run printed above.
echo C was not opened by this command.
pause
exit /b %HUMIDITY_EXIT_CODE%
:config_fail
echo Configuration check failed. See the message above.
pause
exit /b 2
:fail
echo Python or numerical dependency setup failed.
pause
exit /b 2
