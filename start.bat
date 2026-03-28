@echo off
REM Corporate AI Assistant - Windows Start Script
REM Быстрый запуск приложения

setlocal

echo ========================================
echo Corporate AI Assistant
echo ========================================
echo.

REM Проверка виртуального окружения
if not exist venv (
    echo [ERROR] Virtual environment not found
    echo Please run install.bat first
    pause
    exit /b 1
)

REM Активация виртуального окружения
echo [*] Activating virtual environment...
call venv\Scripts\activate.bat

REM Проверка .env файла
if not exist .env (
    echo [ERROR] .env file not found
    echo Please create .env file from .env.example
    pause
    exit /b 1
)

REM Проверка Ollama
echo [*] Checking Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Ollama is not running
    echo Please start Ollama in another terminal: ollama serve
    pause
    exit /b 1
)

echo [OK] Ollama is running
echo.

REM Запуск приложения
echo [OK] Starting application...
echo ========================================
echo.

python app.py
