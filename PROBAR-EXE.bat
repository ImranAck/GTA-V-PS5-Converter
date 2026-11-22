@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "dist\GTAV-PS5-Converter.exe" (
    echo No se encontro el EXE. Ejecuta CREAR-EXE.bat.
    pause
    exit /b 1
)
"dist\GTAV-PS5-Converter.exe" --self-test --report "%CD%\PRUEBA-EXE-RESULTADO.txt"
if errorlevel 1 (
    echo PRUEBA FALLIDA.
    if exist "PRUEBA-EXE-RESULTADO.txt" notepad "PRUEBA-EXE-RESULTADO.txt"
    pause
    exit /b 1
)
findstr /C:"V4_FROZEN_WORKER_TEST=PASS" "PRUEBA-EXE-RESULTADO.txt" >nul
if errorlevel 1 (
    echo PRUEBA FALLIDA: no se encontro PASS.
    pause
    exit /b 1
)
echo Todas las pruebas internas terminadas correctamente.
notepad "PRUEBA-EXE-RESULTADO.txt"
pause
