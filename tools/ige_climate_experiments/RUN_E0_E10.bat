@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 "%~dp0ige_experiments.py" run --config "%~dp0config_E0_E10.json"
) else (
  python "%~dp0ige_experiments.py" run --config "%~dp0config_E0_E10.json"
)
set IGE_EXIT_CODE=%errorlevel%
echo.
echo IGE exit code: %IGE_EXIT_CODE%
echo Reports are in the results folder next to this BAT file.
pause
exit /b %IGE_EXIT_CODE%
