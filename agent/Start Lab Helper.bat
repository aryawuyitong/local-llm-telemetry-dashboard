@echo off
setlocal
rem Double-click to start the lab. On the first run it sets up a private Python environment in
rem this folder. If this PC has no Python 3.11 or newer, it shows what it would download and
rem waits for your OK before putting a private copy of Python in this folder.
rem It never installs system software, needs no administrator rights and changes no settings.
cd /d "%~dp0"
set "LAB_PYTHON=%~dp0.venv\Scripts\python.exe"

rem The private copy of Python, if one is needed: the official CPython build packaged by Astral
rem (python-build-standalone), pinned to one release and checked against its published SHA-256.
set "PY_VERSION=3.12.16"
set "PY_BUILD=20261026"
set "PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/%PY_BUILD%"
set "PY_SHA_X64=590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5"
set "PY_SHA_ARM64=ad585318bfe47980cbaa90be12a65319c5b4eec7472655428528068e710a6c9a"

if exist "%LAB_PYTHON%" goto check

rem A Python 3.11+ this PC already has, or the private copy from an earlier run.
set "BASE="
if exist ".python\python\python.exe" (
  ".python\python\python.exe" -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
  if not errorlevel 1 set "BASE=.python\python\python.exe"
)
if defined BASE goto venv
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
  if not errorlevel 1 set "BASE=py -3"
)
if defined BASE goto venv
python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
if not errorlevel 1 set "BASE=python"
if defined BASE goto venv

rem No Python: offer the private copy.
set "ARCH=x86_64"
set "SHA=%PY_SHA_X64%"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
  set "ARCH=aarch64"
  set "SHA=%PY_SHA_ARM64%"
)
set "FILE=cpython-%PY_VERSION%+%PY_BUILD%-%ARCH%-pc-windows-msvc-install_only.tar.gz"
echo This PC doesn't have Python 3.11 or newer, which the lab needs.
echo.
echo The lab can download a private copy of Python %PY_VERSION% (about 45 MB) into this folder:
echo   from: %PY_URL%/%FILE%
echo   to:   %~dp0.python
echo It is the official CPython build packaged by Astral (python-build-standalone). The lab checks
echo the download against its published SHA-256 before using it. It installs nothing anywhere else
echo and needs no administrator rights. To undo it later, delete the .python folder.
echo.
echo Press any key to download it, or close this window to stop.
pause >nul
if exist .python rmdir /s /q .python
mkdir .python || goto setup
echo Downloading Python %PY_VERSION%...
curl.exe -fL --progress-bar -o ".python\%FILE%" "%PY_URL%/%FILE%"
if errorlevel 1 (
  rmdir /s /q .python
  echo The download failed. Check your internet connection, then double-click Start Lab Helper again.
  pause
  exit /b 1
)
set "ACTUAL="
for /f "skip=1 tokens=1" %%h in ('certutil -hashfile ".python\%FILE%" SHA256') do if not defined ACTUAL set "ACTUAL=%%h"
if /i not "%ACTUAL%"=="%SHA%" (
  rmdir /s /q .python
  echo The downloaded file didn't match its published checksum, so the lab deleted it. Try again later, or tell the team.
  pause
  exit /b 1
)
echo Checksum matches. Unpacking...
tar.exe -xzf ".python\%FILE%" -C .python || goto setup
del ".python\%FILE%"
".python\python\python.exe" -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul || goto setup
set "BASE=.python\python\python.exe"
echo Python %PY_VERSION% is ready in %~dp0.python.

:venv
echo First run: creating the lab's private Python environment in this folder.
echo This only adds a .venv folder here. Delete the folder to undo it.
%BASE% -m venv .venv
if errorlevel 1 goto setup
"%LAB_PYTHON%" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto setup

:check
"%LAB_PYTHON%" -c "import sys, psutil; assert sys.version_info >= (3, 11)" >nul 2>nul
if errorlevel 1 goto setup
"%LAB_PYTHON%" -m telemetry_agent.helper
if errorlevel 1 goto failed
exit /b 0

:setup
echo Setup failed. Delete the .venv folder (and .python, if it exists), then double-click Start Lab Helper again.
echo If it fails again, send the text in this window to the team.
pause
exit /b 1

:failed
echo The helper stopped. Read the error above and contact the project team.
pause
exit /b 1
