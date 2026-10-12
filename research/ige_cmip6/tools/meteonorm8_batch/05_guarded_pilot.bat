@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
if not exist "mn8_project" mkdir "mn8_project"
echo IGE P8 Meteonorm 8.2 - guarded pilot
echo Meteonorm must be running. First import/select 5 IGE locations.
echo inspect: read only; configure: change RCP/year/seed only
echo prepare: additionally select EPW and navigate to Save
echo save: explicitly invoke Save All once (file dialog may require manual handling)
set /p "MODE=Mode [inspect/configure/prepare/save]: "
if "%MODE%"=="" set "MODE=inspect"
if /I "%MODE%"=="save" (
  echo WARNING: save invokes Meteonorm Save All button once.
  set /p "CONFIRM=Type YES to authorize Save All: "
  if /I NOT "!CONFIRM!"=="YES" exit /b 2
)
set /p "SCENARIO=Scenario [contemporary/rcp45_2050/rcp85_2050/rcp85_2100]: "
if "%SCENARIO%"=="" set "SCENARIO=rcp45_2050"
set /p "SEED=Seed 1..10 [1]: "
if "%SEED%"=="" set "SEED=1"
py -3 mn8_uia_pilot_driver.py --mode "%MODE%" --scenario "%SCENARIO%" --seed "%SEED%" --expected-locations 5 --report "mn8_project\uia_pilot_v03.json"
echo Please send mn8_project\uia_pilot_v03.json, or copy the printed ERROR.
pause
