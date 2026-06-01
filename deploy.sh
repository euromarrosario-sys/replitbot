#!/usr/bin/env bash
# deploy.sh — set up and start the trading bot on a fresh VPS
# Usage: bash deploy.sh
set -euo pipefail

echo "=== Trading Bot Deploy ==="

# 1. Install Docker if missing
if ! command -v docker &>/dev/null; then
    echo "[1/4] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Log out and back in if permissions fail."
else
    echo "[1/4] Docker already installed."
fi

# 2. Install Docker Compose plugin if missing
if ! docker compose version &>/dev/null 2>&1; then
    echo "[2/4] Installing Docker Compose..."
    sudo apt-get install -y docker-compose-plugin
else
    echo "[2/4] Docker Compose already installed."
fi

# 3. Create .env if missing
if [ ! -f .env ]; then
    echo "[3/4] Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "  !! Edit .env and add your Binance API keys before continuing !!"
    echo "     nano .env"
    echo ""
    exit 1
else
    echo "[3/4] .env found."
fi

# 4. Build and start
echo "[4/4] Building and starting bot..."
docker compose up -d --build

echo ""
echo "=== Bot running ==="
echo "Logs:    docker compose logs -f"
echo "Stop:    docker compose down"
echo "Restart: docker compose restart"
