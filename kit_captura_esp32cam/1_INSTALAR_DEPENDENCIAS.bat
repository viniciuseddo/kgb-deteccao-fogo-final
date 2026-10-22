@echo off
title Instalador de Dependencias - Kit Captura ESP32-CAM
chcp 65001 > nul
cls

echo ======================================================================
echo    INSTALADOR DE DEPENDENCIAS - KIT DE CAPTURA ESP32-CAM
echo ======================================================================
echo.
echo Verificando instalacao do Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python nao foi encontrado no seu computador!
    echo Por favor, instale o Python 3.10 ou superior pelo site oficial (python.org)
    echo IMPORTANTE: Na instalacao do Python, marque a caixinha:
    echo "Add python.exe to PATH"
    echo.
    pause
    exit /b 1
)

echo Python detectado com sucesso!
echo Instalando pacotes necessarios (opencv, flask, pyserial, requests, numpy)...
echo Isso pode levar alguns instantes...
echo.

python -m pip install --upgrade pip
python -m pip install opencv-python flask pyserial requests numpy pillow

echo.
echo ======================================================================
echo    TUDO PRONTO! DEPENDENCIAS INSTALADAS COM SUCESSO!
echo ======================================================================
echo Agora voce ja pode dar 2 cliques em "INICIAR_CAPTURA.bat" para abrir.
echo.
pause
