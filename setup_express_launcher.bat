@echo off
rem MSL Tools setup: double-click to install the desktop hub.
rem
rem 1. finds Python 3.10 - 3.13 on this machine (the range the hub's Qt, PySide6 6.8, supports;
rem    the same range as runtime_bootstrap.py MINIMUM_PYTHON / NEWEST_PYTHON),
rem 2. prepares the msl_tools Python environment (PySide6) in %LOCALAPPDATA%\MSL\runtime,
rem 3. opens the setup window (pick a folder, Install, Launch).
rem
rem Nothing is installed into Maya: the hub's Maya Gate takes care of Maya itself.

setlocal
title MSL Tools setup
set "ROOT=%~dp0"
set "PYTHON="
set "CHECK=import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)"

rem The Python launcher can pick a version: the newest supported one first.
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PYTHON (
        py -%%V -c "%CHECK%" >nul 2>nul
        if not errorlevel 1 set "PYTHON=py -%%V"
    )
)
if defined PYTHON goto :run

python -c "%CHECK%" >nul 2>nul
if not errorlevel 1 set "PYTHON=python"
if defined PYTHON goto :run

echo.
echo  MSL Tools needs Python 3.10 to 3.13, and none was found on this computer.
py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] > (3, 13) else 1)" >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3 --version 2^>nul') do echo  ^(%%P is installed - it is too new for MSL Tools yet.^)
)
echo.
echo  Install Python 3.13 from https://www.python.org/downloads/  (the default options are fine;
echo  it can stay next to a newer Python), then run this file again.
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
