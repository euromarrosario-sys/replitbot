#!/usr/bin/env bash
# setup_local.sh — instala y arranca el bot en Mac / Linux
# Uso: bash setup_local.sh
set -euo pipefail

echo "======================================"
echo "  Trading Bot — Setup Local (Mac/Linux)"
echo "======================================"

# 1. Verificar Python 3.11+
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 no encontrado. Instálalo desde https://python.org"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ Python $PY_VER encontrado"

# 2. Crear entorno virtual
if [ ! -d ".venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv .venv
fi
source .venv/bin/activate
echo "✓ Entorno virtual activo"

# 3. Instalar dependencias
echo "Instalando dependencias..."
pip install --quiet --upgrade pip
pip install --quiet \
    "python-binance>=1.0.36" \
    "numpy>=2.0" \
    "pandas>=2.0" \
    "cryptography>=42.0"
echo "✓ Dependencias instaladas"

# 4. Crear .env si no existe
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "  ⚠️  Edita .env con tus API keys antes de continuar:"
    echo "     nano .env"
    echo ""
    echo "  Obtén keys sin restricción de IP en:"
    echo "  https://testnet.binancefuture.com  (PAPER)"
    echo "  https://binance.com/en/my/settings/api-management  (REAL)"
    echo ""
    exit 0
fi
echo "✓ .env encontrado"

# 5. Exportar variables y arrancar
echo ""
echo "======================================"
echo "  Arrancando bot..."
echo "======================================"
export $(grep -v '^#' .env | xargs)
python3 -u main.py
