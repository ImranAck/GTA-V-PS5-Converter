@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-build\Scripts\python.exe" (
 where py >nul 2>&1
 if not errorlevel 1 (py -3 -m venv .venv-build) else (python -m venv .venv-build)
 if errorlevel 1 goto FAIL
)
".venv-build\Scripts\python.exe" -m pip install --disable-pip-version-check "numpy>=2,<3" "pillow>=11,<13"
if errorlevel 1 goto FAIL
".venv-build\Scripts\python.exe" -c "import numpy; from PIL import Image, ImageTk"
if errorlevel 1 goto FAIL
echo Dependencias verificadas.
pause
exit /b 0
:FAIL
echo ERROR: revisa la salida anterior.
pause
exit /b 1
