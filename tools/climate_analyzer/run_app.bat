@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    py -3.12 -m venv .venv
)

call .venv\Scripts\activate.bat

if not exist ".venv\.deps_installed" (
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo installed > .venv\.deps_installed
) else (
    echo Dependencies already installed. Delete .venv\.deps_installed to force reinstall.
)

streamlit run app.py --server.port 8501 --client.toolbarMode viewer --browser.gatherUsageStats false --server.fileWatcherType none

pause
