@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "OPENBLAS_NUM_THREADS=1"
set "OMP_NUM_THREADS=1"
set "MKL_NUM_THREADS=1"
set "IGE_PYTHON=python"
if exist ".venv_regression\Scripts\python.exe" set "IGE_PYTHON=.venv_regression\Scripts\python.exe"
"%IGE_PYTHON%" ige_next_experiments.py run --config config_interpolation_v030.json
set "IGE_EXIT=%ERRORLEVEL%"
echo.
echo Exit code %IGE_EXIT%. Reports are in the new interpolation_experiments run.
echo To resume, use: python ige_next_experiments.py resume --run "interpolation_experiments\RUN_NAME"
echo C was not evaluated by this program.
pause
exit /b %IGE_EXIT%
