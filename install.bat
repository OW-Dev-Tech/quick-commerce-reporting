@echo off
cd /d %~dp0
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\playwright install chromium
echo Installed. Double-click start.bat
pause
