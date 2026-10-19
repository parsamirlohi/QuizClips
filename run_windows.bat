@echo off
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org/downloads/ and tick "Add Python to PATH".
  pause
  exit /b 1
)

echo Installing requirements (first run takes a minute)...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Install failed.
  pause
  exit /b 1
)

if not exist .env if not exist .env.txt python tools\set_key.py

python app.py
pause
