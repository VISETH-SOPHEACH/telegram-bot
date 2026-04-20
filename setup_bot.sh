#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  if command -v python3 >/dev/null 2>&1; then
    BOOTSTRAP_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    BOOTSTRAP_BIN="python"
  else
    echo "Python 3 was not found. Install Python 3 and try again." >&2
    exit 1
  fi

  "$BOOTSTRAP_BIN" -m venv .venv
  PYTHON_BIN=".venv/bin/python"
fi

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt

echo
echo "Setup complete."
echo "The bot will use the .venv environment automatically."
echo "Start it with: sh ./run_bot.sh"
