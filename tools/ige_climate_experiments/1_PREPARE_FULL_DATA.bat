@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv_full\Scripts\python.exe" python -m venv .venv_full
if errorlevel 1 goto end
".venv_full\Scripts\python.exe" -m pip install --timeout 120 --retries 5 -r requirements_full_cpu.txt
if errorlevel 1 goto end
".venv_full\Scripts\python.exe" ige_full_experiments.py prepare --config config_full_cpu.json
if errorlevel 1 goto end
".venv_full\Scripts\python.exe" ige_full_experiments.py preflight --config config_full_cpu.json
:end
set "IGE_CODE=%ERRORLEVEL%"
echo Exit code: %IGE_CODE%. Results: full_cpu_results
pause
exit /b %IGE_CODE%
