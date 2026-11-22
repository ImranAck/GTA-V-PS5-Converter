@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "LOGDIR=%LOCALAPPDATA%\GTAV-CarMods-PS5\logs"
if not defined LOCALAPPDATA set "LOGDIR=%TEMP%\GTAV-CarMods-PS5-logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1
set "LOGFILE=%LOGDIR%\inicio-python.log"
>"%LOGFILE%" echo GTA V PS5 Converter - Python runtime startup
>>"%LOGFILE%" echo Folder: %CD%
>>"%LOGFILE%" echo Date: %DATE% %TIME%
echo GTA V PS5 Converter - launching with Python

echo [1/3] Checking Python...
if exist ".venv-runtime\Scripts\python.exe" goto HAVE_VENV
where py >nul 2>&1
if errorlevel 1 goto USE_PYTHON
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if errorlevel 1 goto USE_PYTHON
set "PY=py -3"
goto CREATE_VENV
:USE_PYTHON
where python >nul 2>&1
if errorlevel 1 goto NO_PYTHON
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if errorlevel 1 goto NO_PYTHON
set "PY=python"
:CREATE_VENV
echo Creating local Python environment (first run only)...
%PY% -m venv ".venv-runtime" >>"%LOGFILE%" 2>&1
if errorlevel 1 goto CREATE_ERROR
:HAVE_VENV
set "RUNPY=%CD%\.venv-runtime\Scripts\python.exe"
if not exist "%RUNPY%" goto CREATE_ERROR
"%RUNPY%" -c "import sys; import tkinter; assert sys.version_info >= (3,11)" >>"%LOGFILE%" 2>&1
if errorlevel 1 goto CREATE_ERROR

echo [2/3] Checking libraries...
"%RUNPY%" -c "import numpy; from PIL import Image,ImageTk; import xml.dom.minidom" >>"%LOGFILE%" 2>&1
if not errorlevel 1 goto READY
 echo Installing numpy and Pillow for this application...
"%RUNPY%" -m pip install --disable-pip-version-check "numpy>=2,<3" "pillow>=11,<13" >>"%LOGFILE%" 2>&1
if errorlevel 1 goto DEPS_ERROR
"%RUNPY%" -c "import numpy; from PIL import Image,ImageTk; import xml.dom.minidom" >>"%LOGFILE%" 2>&1
if errorlevel 1 goto DEPS_ERROR
:READY
echo [3/3] Starting application...
if /I "%~1"=="--self-test" goto SELFTEST
"%RUNPY%" -u "launch.py" >>"%LOGFILE%" 2>&1
if errorlevel 1 goto LAUNCH_ERROR
exit /b 0
:SELFTEST
"%RUNPY%" -u "launch.py" --self-test --report "%LOGDIR%\autoprueba-python.txt" >>"%LOGFILE%" 2>&1
if errorlevel 1 goto LAUNCH_ERROR
findstr /C:"V4_FROZEN_WORKER_TEST=PASS" "%LOGDIR%\autoprueba-python.txt" >nul 2>&1
if errorlevel 1 goto LAUNCH_ERROR
echo SELF-TEST PASSED.
echo Report: "%LOGDIR%\autoprueba-python.txt"
type "%LOGDIR%\autoprueba-python.txt"
pause
exit /b 0
:NO_PYTHON
echo ERROR: Install Python 3.11 or newer (64-bit) from https://www.python.org/downloads/windows/
echo Enable Add python.exe to PATH during installation if available.
>>"%LOGFILE%" echo ERROR: Python 3.11 or newer was not found.
goto FAIL
:CREATE_ERROR
echo ERROR: Could not create the Python environment. Check the log.
goto FAIL
:DEPS_ERROR
echo ERROR: Could not install libraries. Check your internet connection.
goto FAIL
:LAUNCH_ERROR
echo ERROR: The application did not start correctly.
goto FAIL
:FAIL
echo.
echo Error log: "%LOGFILE%"
type "%LOGFILE%"
pause
exit /b 1
