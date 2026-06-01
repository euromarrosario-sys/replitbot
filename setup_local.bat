@echo off
REM setup_local.bat — instala y arranca el bot en Windows
REM Uso: doble click o ejecutar desde CMD

echo ======================================
echo   Trading Bot — Setup Local (Windows)
echo ======================================

REM 1. Verificar Python
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo X Python no encontrado. Instálalo desde https://python.org
    pause
    exit /b 1
)
echo OK Python encontrado

REM 2. Crear entorno virtual
IF NOT EXIST ".venv" (
    echo Creando entorno virtual...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
echo OK Entorno virtual activo

REM 3. Instalar dependencias
echo Instalando dependencias...
pip install --quiet --upgrade pip
pip install --quiet ^
    "python-binance>=1.0.36" ^
    "numpy>=2.0" ^
    "pandas>=2.0" ^
    "cryptography>=42.0"
echo OK Dependencias instaladas

REM 4. Crear .env si no existe
IF NOT EXIST ".env" (
    copy .env.example .env
    echo.
    echo   AVISO: Edita .env con tus API keys:
    echo   notepad .env
    echo.
    echo   Keys sin restriccion de IP en:
    echo   https://testnet.binancefuture.com  ^(PAPER^)
    echo   https://binance.com/en/my/settings/api-management  ^(REAL^)
    echo.
    notepad .env
    pause
    exit /b 0
)
echo OK .env encontrado

REM 5. Cargar variables y arrancar
echo.
echo ======================================
echo   Arrancando bot...
echo ======================================
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
)
python -u main.py
pause
