@echo off
setlocal
cd /d "%~dp0"
echo This command will not execute or extract the installer.
set /p "ZIPPATH=Absolute path to Meteonorm installer ZIP: "
if "%ZIPPATH%"=="" exit /b 1
py -3 archive_probe.py "%ZIPPATH%" --out meteonorm8_installer_inventory.json
echo.
echo Send meteonorm8_installer_inventory.json (not licence files).
pause
