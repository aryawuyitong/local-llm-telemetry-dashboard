@echo off
rem Start here on Windows: double-click this file. It only opens the lab's real launcher,
rem in the agent folder next to this file. It is plain text, so you can read both files first.
if not exist "%~dp0agent\Start Lab Helper.bat" (
  echo The agent folder is missing. Download the lab again.
  pause
  exit /b 1
)
call "%~dp0agent\Start Lab Helper.bat"
