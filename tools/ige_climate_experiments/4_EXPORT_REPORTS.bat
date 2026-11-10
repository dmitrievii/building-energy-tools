@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv_full\Scripts\python.exe" (echo Run 1_PREPARE_FULL_DATA.bat first.& pause & exit /b 2)
".venv_full\Scripts\python.exe" ige_full_experiments.py export --config config_full_cpu.json
set "IGE_CODE=%ERRORLEVEL%"
echo Exit code: %IGE_CODE%. Send full_cpu_results\FULL_CPU_REPORTS.zip
pause
exit /b %IGE_CODE%
