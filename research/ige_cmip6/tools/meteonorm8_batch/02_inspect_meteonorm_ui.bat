@echo off
setlocal
cd /d "%~dp0"
if not exist "mn8_project" mkdir "mn8_project"
echo Start Meteonorm 8 and open the view you want to inspect.
set /p "VIEW=View name [main/future/advanced]: "
if "%VIEW%"=="" set "VIEW=main"
py -3 mn8_batch_controller.py inspect-ui --out "mn8_project\ui_%VIEW%.json"
echo.
echo Attach the resulting mn8_project\ui_*.json files for precise UI automation.
pause
