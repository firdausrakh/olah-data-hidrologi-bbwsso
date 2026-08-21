@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Olah Data Hidrologi BBWS SO

echo ============================================================
echo   OLAH DATA HIDROLOGI BBWS SERAYU OPAK
echo ============================================================
echo.

REM ============================================================
REM Cari Python
REM ============================================================

set "PYEXE="

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYEXE=%~dp0.venv\Scripts\python.exe"
)

if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    where py >nul 2>nul
    if not errorlevel 1 set "PYEXE=py"
)

if not defined PYEXE (
    echo [ERROR] Python tidak ditemukan.
    echo.
    echo Install Python 3.11 atau lebih baru.
    echo Pastikan "Add Python to PATH" dicentang.
    echo.
    pause
    exit /b 1
)

echo Python: %PYEXE%
echo.

REM ============================================================
REM Load .env
REM ============================================================

if exist ".env" (
    echo [ENV] Memuat konfigurasi .env...

    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "LINE=%%A"
        if not "%%A"=="" (
            if not "%%A:~0,1%%"=="#" (
                set "%%A=%%B"
            )
        )
    )
) else (
    echo [WARNING] File .env tidak ditemukan.
)

echo.

REM ============================================================
REM Pastikan pip
REM ============================================================

echo [1/3] Memeriksa pip...

%PYEXE% -m pip --version >nul 2>nul

if errorlevel 1 (
    echo Mengaktifkan pip...
    %PYEXE% -m ensurepip --upgrade

    if errorlevel 1 (
        echo.
        echo [ERROR] Gagal menyediakan pip.
        pause
        exit /b 1
    )
)

REM ============================================================
REM Install requirements
REM ============================================================

echo [2/3] Memeriksa dependency...

%PYEXE% -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [ERROR] Instalasi dependency gagal.
    echo Pastikan koneksi internet aktif.
    echo.
    pause
    exit /b 1
)

REM ============================================================
REM Run Flask
REM ============================================================

echo.
echo [3/3] Menjalankan server...
echo.
echo ============================================================
echo   SERVER AKTIF
echo.
echo   http://127.0.0.1:5050
echo ============================================================
echo.

%PYEXE% api/app.py

echo.
echo Server berhenti.
pause