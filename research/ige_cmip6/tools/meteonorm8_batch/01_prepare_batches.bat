@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.9 or later.
  pause
  exit /b 1
)
py -3 mn8_batch_controller.py init --project "%~dp0mn8_project"
echo.
echo STEP 2: Open Meteonorm 8 and import batch_input\locations_format22.csv
echo Complete the single-site pilot before generating all scenarios.
pause
