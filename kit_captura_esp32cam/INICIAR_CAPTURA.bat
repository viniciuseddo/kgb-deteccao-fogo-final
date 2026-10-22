@echo off
title ESP32-CAM - Kit de Captura de Video e Fotos
chcp 65001 > nul
cls

echo ======================================================================
echo       🔥 KIT DE CAPTURA ESP32-CAM (VIDEOS E FOTOS) 🔥
echo ======================================================================
echo.
echo Iniciando o servidor de captura...
echo O navegador abrira automaticamente em: http://localhost:5005
echo.
echo DICA: Se for a primeira vez que roda neste computador, execute antes
echo o arquivo "1_INSTALAR_DEPENDENCIAS.bat".
echo.
echo Nao feche esta janela enquanto estiver gravando!
echo ======================================================================
echo.

python app.py

if %errorlevel% neq 0 (
    echo.
    echo [AVISO] O aplicativo encerrou com erro.
    echo Se faltar alguma biblioteca, execute "1_INSTALAR_DEPENDENCIAS.bat".
    pause
)
