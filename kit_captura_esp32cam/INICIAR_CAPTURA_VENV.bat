@echo off
setlocal
chcp 65001 >nul
title ESP32-CAM - Kit de Captura (usando o venv do projeto)
cls

rem ==============================================================
rem  Roda o app de captura do Lucas usando o Python do venv do
rem  projeto, que ja tem opencv e companhia instalados.
rem  Substitui o INICIAR_CAPTURA.bat original, que nao achava o
rem  Python do sistema.
rem ==============================================================

set PROJ=C:\projetos\deteccao-fogo
set PY=%PROJ%\venv\Scripts\python.exe
set APP=%PROJ%\kit_captura_esp32cam\app.py

echo ======================================================================
echo    KIT DE CAPTURA ESP32-CAM
echo ======================================================================
echo.

if not exist "%PY%" (
  echo Nao encontrei o Python do venv em:
  echo   %PY%
  echo.
  goto erro
)

if not exist "%APP%" (
  echo Nao encontrei o app em:
  echo   %APP%
  echo.
  goto erro
)

echo Conferindo bibliotecas, pode demorar na primeira vez...
"%PY%" -m pip install --quiet --disable-pip-version-check opencv-python flask pyserial requests numpy pillow
if errorlevel 1 (
  echo.
  echo Falhou ao instalar alguma biblioteca.
  goto erro
)

echo.
echo ======================================================================
echo  Abrindo em http://localhost:5005
echo.
echo  Na tela: aba "Cabo USB", porta COM13, botao Conectar.
echo  NAO feche esta janela enquanto estiver gravando.
echo ======================================================================
echo.

"%PY%" "%APP%"

echo.
echo O aplicativo encerrou.
pause
exit /b 0

:erro
echo *** Tira print desta janela inteira e manda. ***
pause
exit /b 1
