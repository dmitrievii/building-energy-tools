@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv_regression\Scripts\python.exe" (
  ".venv_regression\Scripts\python.exe" ige_regression.py check-config --config config_auto_regression.json
) else (
  python ige_regression.py check-config --config config_auto_regression.json
)
if errorlevel 1 goto config_fail
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
:config_fail
echo Configuration check failed. Correct config_auto_regression.json using the message above.
echo No calculation or dependency installation was started.
pause
exit /b 2
:fail
echo Python or dependency installation failed. See message above.
pause
exit /b 2
