#!/bin/bash
# Double-click this file on a Mac (or run: ./run_mac.command)
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Get it from https://www.python.org/downloads/ then run this again."
  read -n 1 -s -r -p "Press any key to close"; exit 1
fi

echo "Installing requirements (first run takes a minute)..."
python3 -m pip install -q -r requirements.txt || { echo "Install failed."; read -n 1 -s -r -p "Press any key to close"; exit 1; }

if [ ! -f .env ] && [ ! -f .env.txt ]; then
  python3 tools/set_key.py
fi

python3 app.py
