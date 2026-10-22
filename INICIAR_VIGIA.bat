@echo off
setlocal
chcp 65001 >nul
title Sistema Vigia KGB - camera USB + disparo Wi-Fi
cls

rem ==============================================================
rem  Roda o sistema completo: le a ESP32-CAM pela USB, roda o
rem  YOLO11 do Lucas, e dispara no ESP32-S3 por Wi-Fi.
rem
rem  TROCA O IP ABAIXO pelo IP que o S3 imprime na serial ao ligar.
rem ==============================================================

set IP_S3=192.168.0.17

set PROJ=C:\projetos\deteccao-fogo
set PY=%PROJ%\venv\Scripts\python.exe

echo ======================================================================
echo    SISTEMA VIGIA KGB
echo    Camera pela USB, disparo pelo Wi-Fi em %IP_S3%
echo ======================================================================
echo.

if not exist "%PY%" (
  echo Nao encontrei o Python do venv em:
  echo   %PY%
  goto erro
)

if not exist "%PROJ%\sistema_vigia.py" (
  echo Nao encontrei o sistema_vigia.py em %PROJ%
  goto erro
)

echo Conferindo bibliotecas...
"%PY%" -m pip install --quiet --disable-pip-version-check --upgrade "ultralytics>=8.3.0"
"%PY%" -m pip install --quiet --disable-pip-version-check opencv-python pyserial numpy

echo.
echo Abrindo. Na janela de video:
echo    q sai   f dispara manual   r gira   + e - mudam o limiar
echo.

cd /d "%PROJ%"
"%PY%" sistema_vigia.py --ip %IP_S3% --salvar

echo.
pause
exit /b 0

:erro
echo.
echo *** Tira print desta janela e manda. ***
pause
exit /b 1
