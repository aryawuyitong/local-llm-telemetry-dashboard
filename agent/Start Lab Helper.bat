@echo off
setlocal
rem Launch only; never installs, deletes or changes execution policy.
cd /d "%~dp0"
set "LAB_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%LAB_PYTHON%" goto missing
"%LAB_PYTHON%" -c "import sys, psutil; assert sys.version_info >= (3, 9)" >nul 2>nul
if errorlevel 1 goto dependencies
echo Windows support awaits physical-device validation.
"%LAB_PYTHON%" -m telemetry_agent.helper
if errorlevel 1 goto failed
exit /b 0
:missing
echo Create the lab environment manually from this folder:
echo   py -3 -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
echo Then run this launcher again. Do not run as administrator.
pause
exit /b 1
:dependencies
echo Python 3.9+ and the listed dependencies are required.
echo Run: .venv\Scripts\python.exe -m pip install -r requirements.txt
echo If a step needs administrator access or a security bypass, stop and ask the team.
pause
exit /b 1
:failed
echo The helper stopped. Read the error above and contact the project team.
pause
exit /b 1
