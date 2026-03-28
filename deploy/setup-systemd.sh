#!/bin/bash

# Corporate AI Assistant - Systemd Setup Script
# Автоматическая настройка systemd сервисов

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🚀 Настройка Systemd сервисов${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Проверка прав root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Запустите скрипт с sudo${NC}"
    exit 1
fi

# Переменные (можно изменить)
APP_USER="${APP_USER:-aiassistant}"
APP_GROUP="${APP_GROUP:-aiassistant}"
APP_DIR="${APP_DIR:-/opt/corporate-ai-assistant}"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"

echo -e "${BLUE}Настройки:${NC}"
echo "  Пользователь: $APP_USER"
echo "  Группа: $APP_GROUP"
echo "  Директория: $APP_DIR"
echo "  Venv: $VENV_DIR"
echo ""

# Создание пользователя если не существует
if ! id "$APP_USER" &>/dev/null; then
    echo -e "${BLUE}Создание пользователя $APP_USER...${NC}"
    useradd -r -m -s /bin/bash "$APP_USER"
    echo -e "${GREEN}✓ Пользователь создан${NC}"
fi

# Создание группы ollama если не существует
if ! getent group ollama &>/dev/null; then
    echo -e "${BLUE}Создание группы ollama...${NC}"
    groupadd -r ollama
    echo -e "${GREEN}✓ Группа ollama создана${NC}"
fi

# Создание пользователя ollama если не существует
if ! id "ollama" &>/dev/null; then
    echo -e "${BLUE}Создание пользователя ollama...${NC}"
    useradd -r -g ollama -s /bin/false ollama
    echo -e "${GREEN}✓ Пользователь ollama создан${NC}"
fi

# Копирование systemd файлов
echo -e "${BLUE}Копирование systemd unit файлов...${NC}"

# AI Assistant service
cat > /etc/systemd/system/ai-assistant.service << EOF
[Unit]
Description=Corporate AI Assistant
After=network-online.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$VENV_DIR/bin/python $APP_DIR/app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}✓ ai-assistant.service создан${NC}"

# Ollama service
cat > /etc/systemd/system/ollama.service << EOF
[Unit]
Description=Ollama Service
After=network-online.target
Documentation=https://ollama.ai

[Service]
Type=simple
User=ollama
Group=ollama
ExecStart=/usr/local/bin/ollama serve
Restart=always
RestartSec=3
Environment="OLLAMA_HOST=127.0.0.1:11434"

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}✓ ollama.service создан${NC}"

# Перезагрузка systemd
echo -e "${BLUE}Перезагрузка systemd daemon...${NC}"
systemctl daemon-reload
echo -e "${GREEN}✓ Systemd daemon перезагружен${NC}"

# Включение автозапуска
echo -e "${BLUE}Включение автозапуска сервисов...${NC}"
systemctl enable ollama.service
systemctl enable ai-assistant.service
echo -e "${GREEN}✓ Автозапуск включен${NC}"

# Запуск сервисов
echo ""
read -p "Запустить сервисы сейчас? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Запуск Ollama...${NC}"
    systemctl start ollama.service
    sleep 2
    
    echo -e "${BLUE}Запуск AI Assistant...${NC}"
    systemctl start ai-assistant.service
    sleep 2
    
    echo ""
    echo -e "${GREEN}✓ Сервисы запущены${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Настройка завершена!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Полезные команды:${NC}"
echo ""
echo "  Статус сервисов:"
echo "    sudo systemctl status ai-assistant.service"
echo "    sudo systemctl status ollama.service"
echo ""
echo "  Управление:"
echo "    sudo systemctl start ai-assistant.service"
echo "    sudo systemctl stop ai-assistant.service"
echo "    sudo systemctl restart ai-assistant.service"
echo ""
echo "  Логи:"
echo "    sudo journalctl -u ai-assistant.service -f"
echo "    sudo journalctl -u ollama.service -f"
echo ""
echo "  Автозапуск:"
echo "    sudo systemctl enable ai-assistant.service"
echo "    sudo systemctl disable ai-assistant.service"
echo ""
