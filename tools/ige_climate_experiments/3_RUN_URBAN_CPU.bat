@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv_full\Scripts\python.exe" (echo Run 1_PREPARE_FULL_DATA.bat first.& pause & exit /b 2)
".venv_full\Scripts\python.exe" ige_full_experiments.py urban --config config_full_cpu.json
if errorlevel 1 goto end
".venv_full\Scripts\python.exe" ige_full_experiments.py run --config config_full_cpu.json --suite urban
:end
set "IGE_CODE=%ERRORLEVEL%"
echo Exit code: %IGE_CODE%. Results: full_cpu_results
pause
exit /b %IGE_CODE%
