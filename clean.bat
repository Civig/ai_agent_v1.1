@echo off
REM Corporate AI Assistant - Windows Clean Script
REM Очистка временных файлов и кэша

setlocal

echo ========================================
echo Cleaning project
echo ========================================
echo.

REM Python cache
echo [*] Removing __pycache__...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
echo [OK] Python cache cleaned

REM .pyc files
echo [*] Removing .pyc files...
del /s /q *.pyc >nul 2>&1
del /s /q *.pyo >nul 2>&1
echo [OK] .pyc files removed

REM Backup files
echo [*] Removing backup files...
del /q *.backup.* >nul 2>&1
echo [OK] Backup files removed

REM Logs
echo [*] Removing logs...
del /q *.log >nul 2>&1
echo [OK] Logs removed

REM Temporary files
echo [*] Removing temporary files...
del /s /q *.tmp >nul 2>&1
del /s /q *.temp >nul 2>&1
echo [OK] Temporary files removed

REM Virtual environment (optional)
if "%1"=="--full" (
    if exist venv (
        echo [*] Removing virtual environment...
        rmdir /s /q venv
        echo [OK] Virtual environment removed
    )
)

echo.
echo [OK] Cleaning complete!
echo.

if not "%1"=="--full" (
    echo For full cleanup (including venv): clean.bat --full
)

pause
