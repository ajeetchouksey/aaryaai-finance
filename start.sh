#!/usr/bin/env sh
# aaryaai finance - macOS/Linux starter. First run creates a private Python environment in .venv
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Setting up for the first time, this takes a minute..."
  python3 -m venv .venv || { echo "Python 3.10+ is needed"; exit 1; }
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -e ".[market]"
fi
exec .venv/bin/aaryaai-finance "$@"
