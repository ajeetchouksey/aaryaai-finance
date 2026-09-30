@echo off
rem aaryaai finance - double-click to start. First run creates a private Python environment in .venv
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Setting up for the first time, this takes a minute...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 ( echo Python 3.10+ is needed: https://www.python.org/downloads/ & pause & exit /b 1 )
  .venv\Scripts\python -m pip install --quiet --upgrade pip
  .venv\Scripts\python -m pip install --quiet -e ".[market]"
)
.venv\Scripts\aaryaai-finance %*
pause
