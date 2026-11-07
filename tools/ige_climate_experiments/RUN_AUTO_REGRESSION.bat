@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist ".venv_regression\Scripts\python.exe" (
  python -m venv .venv_regression
  if errorlevel 1 goto fail
)
".venv_regression\Scripts\python.exe" -m pip install -r requirements_regression.txt
if errorlevel 1 goto fail
".venv_regression\Scripts\python.exe" ige_regression.py run --config config_auto_regression.json
set "RUN_CODE=%ERRORLEVEL%"
echo.
echo Finished. Exit code %RUN_CODE%. See regression_results for reports.
pause
exit /b %RUN_CODE%
:fail
echo Python or dependency installation failed. See message above.
pause
exit /b 2
