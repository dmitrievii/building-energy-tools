@echo off
setlocal
cd /d "%~dp0"
if not exist "mn8_project" mkdir "mn8_project"
echo Meteonorm 8.2 should be open on the view to inspect.
echo This script only reads UI labels and control identifiers.
echo It does not click, type, or collect editable field values.
set /p "VIEW=View [future/advanced/format/output]: "
if /I "%VIEW%"=="" set "VIEW=future"
if /I NOT "%VIEW%"=="future" if /I NOT "%VIEW%"=="advanced" if /I NOT "%VIEW%"=="format" if /I NOT "%VIEW%"=="output" (
  echo Invalid view. Use future, advanced, format, output.
  pause
  exit /b 2
)
py -3 mn8_uia_deep_probe.py --view "%VIEW%" --max-depth 7 --out "mn8_project\ui_deep_%VIEW%.json"
if errorlevel 1 (
  echo UI inspection could not find the requested Meteonorm panel.
  echo Open that panel in Meteonorm and try again.
  pause
  exit /b 2
)
echo Please attach mn8_project\ui_deep_%VIEW%.json.
pause
