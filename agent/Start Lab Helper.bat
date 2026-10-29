@echo off
rem Double-click this file to start the Local AI Lab (Windows).
rem Keep this window open while you use the lab; close it to stop.
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up the lab's own Python environment in this folder, one time...
  %PY% -m venv .venv || goto fail
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto fail
)

".venv\Scripts\python.exe" -m telemetry_agent.helper
goto :eof

:fail
if exist ".venv" rmdir /s /q ".venv"
echo Setup failed. Install Python from python.org (tick "Add python.exe to PATH"), then double-click this file again.
pause
