@echo off
setlocal
cd /d "%~dp0"
if exist "dist\GTAV-PS5-Converter.exe" (
 start "" "dist\GTAV-PS5-Converter.exe"
 exit /b 0
)
if not exist ".venv-build\Scripts\python.exe" (
 where py >nul 2>&1
 if not errorlevel 1 (py -3 -m venv .venv-build) else (python -m venv .venv-build)
 if errorlevel 1 goto FAIL
)
".venv-build\Scripts\python.exe" -c "import numpy; from PIL import Image, ImageTk" >nul 2>&1
if errorlevel 1 (
 ".venv-build\Scripts\python.exe" -m pip install --disable-pip-version-check "numpy>=2,<3" "pillow>=11,<13"
 if errorlevel 1 goto FAIL
)
".venv-build\Scripts\python.exe" launch.py
if errorlevel 1 goto FAIL
exit /b 0
:FAIL
echo ERROR: Python or its dependencies failed to start.
pause
exit /b 1
