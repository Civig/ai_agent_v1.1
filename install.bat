@echo off
REM Corporate AI Assistant - Windows Installation Script
REM Автоматическая установка для Windows

setlocal enabledelayedexpansion

echo ========================================
echo Corporate AI Assistant - Installation
echo ========================================
echo.

REM Проверка Python
echo [*] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python %PYTHON_VERSION% found

REM Проверка pip
echo [*] Checking pip...
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] pip not found!
    echo Installing pip...
    python -m ensurepip --upgrade
)
echo [OK] pip found

REM Создание виртуального окружения
echo.
echo [*] Creating virtual environment...
if exist venv (
    echo [WARNING] Virtual environment already exists
    set /p RECREATE="Recreate? (y/n): "
    if /i "!RECREATE!"=="y" (
        rmdir /s /q venv
        python -m venv venv
        echo [OK] Virtual environment recreated
    )
) else (
    python -m venv venv
    echo [OK] Virtual environment created
)

REM Активация виртуального окружения
echo [*] Activating virtual environment...
call venv\Scripts\activate.bat

REM Обновление pip
echo [*] Upgrading pip...
python -m pip install --upgrade pip

REM Установка зависимостей
echo.
echo [*] Installing dependencies...
if exist requirements.txt (
    pip install -r requirements.txt
    echo [OK] Dependencies installed
) else (
    echo [ERROR] requirements.txt not found!
    pause
    exit /b 1
)

REM Создание директорий
echo.
echo [*] Creating directories...
if not exist static\css mkdir static\css
if not exist static\js mkdir static\js
if not exist models mkdir models
if not exist templates mkdir templates
echo [OK] Directories created

REM Создание .env файла
echo.
echo [*] Setting up environment variables...
if exist .env (
    echo [WARNING] .env file already exists
    set /p OVERWRITE="Overwrite? (y/n): "
    if /i "!OVERWRITE!"=="y" (
        copy /y .env.example .env
        echo [OK] .env file created from .env.example
    )
) else (
    if exist .env.example (
        copy .env.example .env
        echo [OK] .env file created from .env.example
        echo [WARNING] IMPORTANT: Edit .env file with your settings!
    ) else (
        echo [ERROR] .env.example not found!
    )
)

REM Проверка Ollama
echo.
echo [*] Checking Ollama...
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Ollama not found
    echo Please install Ollama from https://ollama.ai/download
) else (
    echo [OK] Ollama found
    
    REM Проверка, запущен ли Ollama
    curl -s http://localhost:11434/api/tags >nul 2>&1
    if %errorlevel% neq 0 (
        echo [WARNING] Ollama is not running
        echo Start Ollama with: ollama serve
    ) else (
        echo [OK] Ollama is running
    )
)

REM Тест импорта модулей
echo.
echo [*] Testing module imports...
python -c "import fastapi, uvicorn, ldap3, jose, markdown" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Module import failed
    echo Try reinstalling dependencies
) else (
    echo [OK] All modules import correctly
)

REM Финальные инструкции
echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo [OK] Project successfully installed and configured
echo.
echo Next steps:
echo.
echo 1. Edit .env file with your AD/LDAP settings:
echo    notepad .env
echo.
echo 2. Make sure Ollama is running:
echo    ollama serve
echo.
echo 3. Activate virtual environment:
echo    venv\Scripts\activate.bat
echo.
echo 4. Start the application:
echo    python app.py
echo.
echo 5. Open browser:
echo    http://localhost:8000
echo.
echo [WARNING] IMPORTANT: Change settings in .env before running!
echo.
pause
