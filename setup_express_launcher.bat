@echo off
rem MSL Tools setup: double-click to install the desktop hub.
rem
rem 1. finds Python 3.10+ on this machine,
rem 2. prepares the msl_tools Python environment (PySide6) in %LOCALAPPDATA%\MSL\runtime,
rem 3. opens the setup window (pick a folder, Install, Launch).
rem
rem Nothing is installed into Maya: the hub's Maya Gate takes care of Maya itself.

setlocal
title MSL Tools setup
set "ROOT=%~dp0"
set "PYTHON="

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"
if defined PYTHON goto :run

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PYTHON=python"
if defined PYTHON goto :run

echo.
echo  MSL Tools needs Python 3.10 or newer, and none was found on this computer.
echo.
echo  Install it from https://www.python.org/downloads/  (the default options are fine),
echo  then run this file again.
echo.
pause
exit /b 1

:run
echo  Preparing MSL Tools...
%PYTHON% "%ROOT%msl\core\installer\runtime_bootstrap.py" --run "%ROOT%msl\run_installer.py"
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo  Setup could not be completed - see the messages above.
echo.
pause
exit /b 1
