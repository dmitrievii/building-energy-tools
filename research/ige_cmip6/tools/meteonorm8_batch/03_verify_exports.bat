@echo off
setlocal
cd /d "%~dp0"
py -3 mn8_batch_controller.py verify --project "%~dp0mn8_project"
echo.
echo Verification saved to mn8_project\verification_report.json
pause
