@echo off
setlocal EnableExtensions
chcp 65001 >nul
rem Python must decode UTF-8 sources consistently on Spanish/French/English Windows.
rem This environment setting is inherited by unittest and subprocess workers.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title GTA V PS5 Converter - standalone EXE

echo =====================================================
echo  GTA V PS5 Converter 1.0.2c - Single Windows EXE
 echo =====================================================
echo.
where py >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 goto MISSING_PYTHON
    set "PY=python"
)

if not exist "vendor\7zip" mkdir "vendor\7zip"
set "SEVENZIP=%ProgramFiles%\7-Zip"
if not exist "%SEVENZIP%\7z.exe" set "SEVENZIP=%ProgramFiles(x86)%\7-Zip"
if not exist "%SEVENZIP%\7z.exe" (
    echo ERROR: Install 7-Zip on this build computer to create the full EXE.
    echo Official website: https://www.7-zip.org/
    echo The EXE bundles 7-Zip; recipients should not need it separately.
    goto FAIL
)
for %%F in (7z.exe 7z.dll License.txt) do (
    if not exist "%SEVENZIP%\%%F" (
        echo ERROR: Missing %%F in "%SEVENZIP%".
        goto FAIL
    )
    copy /y "%SEVENZIP%\%%F" "vendor\7zip\%%F" >nul
    if errorlevel 1 goto FAIL
)

%PY% -m venv .venv-build
if errorlevel 1 goto MISSING_PYTHON
call ".venv-build\Scripts\activate.bat"
if errorlevel 1 goto FAIL
python -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto FAIL
python -m pip install --disable-pip-version-check -r requirements-build.txt
if errorlevel 1 goto FAIL

echo [1/4] Running automated tests...
python -m unittest discover -s tests -p "test_*.py" -q
if errorlevel 1 goto FAIL

echo [2/4] Checking converter module imports...
python build_imports.py > "ANALISIS-MODULOS.txt"
if errorlevel 1 goto FAIL
findstr /C:"xml.dom.minidom" "ANALISIS-MODULOS.txt" >nul
if errorlevel 1 goto FAIL

echo [3/4] Building a single EXE with Python, tools and 7-Zip...
python -m PyInstaller --noconfirm --clean "GTAV-PS5-Converter.spec"
if errorlevel 1 goto FAIL
if not exist "dist\GTAV-PS5-Converter.exe" goto FAIL

echo [4/4] Testing EXE and internal workers...
if exist "PRUEBA-EXE-RESULTADO.txt" del /q "PRUEBA-EXE-RESULTADO.txt"
"dist\GTAV-PS5-Converter.exe" --self-test --report "%CD%\PRUEBA-EXE-RESULTADO.txt"
if errorlevel 1 goto FAIL
if not exist "PRUEBA-EXE-RESULTADO.txt" goto FAIL
findstr /C:"V4_FROZEN_WORKER_TEST=PASS" "PRUEBA-EXE-RESULTADO.txt" >nul
if errorlevel 1 goto FAIL

powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 'dist\GTAV-PS5-Converter.exe').Hash | Set-Content 'dist\SHA256-EXE.txt'"
echo.
echo BUILD COMPLETE. The executable is:
echo   dist\GTAV-PS5-Converter.exe
echo Only the EXE needs to be copied; no _internal directory.
echo Each user must supply original game resources separately.
echo.
echo IMPORTANT: EXE portability is NOT verified; test on a clean Windows computer.
pause
exit /b 0
:MISSING_PYTHON
echo ERROR: A compatible Python version (preferably 3.12 x64) is required to build.
echo Descarga desde https://www.python.org/downloads/
:FAIL
echo.
echo No portable EXE was validated. Review the preceding error.
if exist "PRUEBA-EXE-RESULTADO.txt" type "PRUEBA-EXE-RESULTADO.txt"
pause
exit /b 1
