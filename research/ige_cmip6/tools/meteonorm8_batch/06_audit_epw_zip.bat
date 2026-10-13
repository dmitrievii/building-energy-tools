@echo off
setlocal
cd /d "%~dp0"
echo IGE P8 - private EPW ZIP audit (does not upload data)
echo Drag and drop epw_new.zip on this .bat, or enter the full path below.
set "ZIPPATH=%~1"
if not defined ZIPPATH set /p "ZIPPATH=Path to ZIP [epw_new.zip]: "
if not defined ZIPPATH set "ZIPPATH=epw_new.zip"
py -3 mn8_benchmark_zip_audit.py "%ZIPPATH%" --out "ige_p8_epw_zip_audit.json"
echo.
echo Send only ige_p8_epw_zip_audit.json to ChatGPT.
pause
