@echo off
setlocal
chcp 65001 >nul
title Gravar firmware universal na ESP32-CAM (sem Arduino IDE)

rem ==============================================================
rem  Compila e grava o firmware universal do Lucas na ESP32-CAM
rem  usando arduino-cli pelo terminal. Nao abre a Arduino IDE.
rem
rem  Precisa: ESP32-CAM na base MB, plugada no USB, aparecendo
rem  como COM13. Se for outra porta, troca a linha PORTA abaixo.
rem ==============================================================

set PORTA=COM13
set PROJ=C:\projetos\deteccao-fogo
set SKETCH=%PROJ%\arduino\esp32cam_coleta_universal
set CLI_DIR=%PROJ%\ferramentas\arduino-cli
set CLI=%CLI_DIR%\arduino-cli.exe
set URL_INDEX=https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json

if not exist "%SKETCH%\esp32cam_coleta_universal.ino" (
  echo.
  echo Nao achei o sketch em:
  echo   %SKETCH%
  echo Copia a pasta esp32cam_coleta_universal do kit do Lucas pra dentro de %PROJ%\arduino\
  goto erro
)

echo.
echo ===== 1/4  arduino-cli =====
if exist "%CLI%" goto temcli
mkdir "%CLI_DIR%" 2>nul
echo Baixando arduino-cli (uns 30 MB)...
curl -L -o "%CLI_DIR%\acli.zip" https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Windows_64bit.zip
if errorlevel 1 goto erro
tar -xf "%CLI_DIR%\acli.zip" -C "%CLI_DIR%"
if not exist "%CLI%" goto erro
:temcli
"%CLI%" version

echo.
echo ===== 2/4  core ESP32 =====
"%CLI%" core list 2>nul | findstr /i "esp32:esp32" >nul
if not errorlevel 1 (
  echo Core ESP32 ja instalado pela Arduino IDE, reaproveitando.
  goto temcore
)
echo Core ESP32 nao encontrado. Instalando, e um download grande, so na primeira vez...
"%CLI%" core update-index --additional-urls %URL_INDEX%
"%CLI%" core install esp32:esp32 --additional-urls %URL_INDEX%
if errorlevel 1 goto erro
:temcore

echo.
echo ===== 3/4  compilando (1 a 3 minutos) =====
"%CLI%" compile --fqbn esp32:esp32:esp32cam "%SKETCH%"
if errorlevel 1 goto erro

echo.
echo ===== 4/4  gravando na %PORTA% =====
echo Se ficar parado em "Connecting......", segura o botao IO0 da base,
echo aperta e solta o RST, e so entao solta o IO0.
"%CLI%" upload -p %PORTA% --fqbn esp32:esp32:esp32cam "%SKETCH%"
if errorlevel 1 goto erro

echo.
echo ==========================================================
echo   GRAVADO. Aperta o RST na base uma vez.
echo.
echo   Agora roda o INICIAR_CAPTURA.bat do kit do Lucas,
echo   aba "Cabo USB", porta %PORTA%, clica em Conectar.
echo   A imagem aparece ali. Sem Wi-Fi, sem hotspot.
echo ==========================================================
pause
exit /b 0

:erro
echo.
echo *** DEU ERRO. Tira print desta janela inteira e manda. ***
pause
exit /b 1
