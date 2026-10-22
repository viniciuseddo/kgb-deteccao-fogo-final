@echo off
setlocal
chcp 65001 >nul
title Detector de Chamas YOLO11 + ESP32-CAM
cls

rem ==============================================================
rem  Roda o teste ao vivo do modelo do Lucas usando o Python do
rem  venv do projeto. Substitui o INICIAR_TESTE_AO_VIVO.bat, que
rem  nao achava o Python do sistema.
rem ==============================================================

set PROJ=C:\projetos\deteccao-fogo
set PY=%PROJ%\venv\Scripts\python.exe
set KIT=%PROJ%\kit_teste_esp32cam

echo ======================================================================
echo    DETECTOR DE CHAMAS EM TEMPO REAL - YOLO11 + ESP32-CAM
echo ======================================================================
echo.

if not exist "%PY%" (
  echo Nao encontrei o Python do venv em:
  echo   %PY%
  goto erro
)

if not exist "%KIT%\testar_esp32_usb.py" (
  echo Nao encontrei o script em:
  echo   %KIT%\testar_esp32_usb.py
  goto erro
)

echo Conferindo bibliotecas. O modelo e YOLO11, entao o ultralytics
echo precisa ser 8.3 ou mais novo. Pode demorar na primeira vez...
echo.
"%PY%" -m pip install --quiet --disable-pip-version-check --upgrade "ultralytics>=8.3.0"
"%PY%" -m pip install --quiet --disable-pip-version-check opencv-python pyserial numpy onnx onnxruntime
if errorlevel 1 (
  echo.
  echo Falhou ao instalar alguma biblioteca.
  goto erro
)

echo.
echo ======================================================================
echo  Abrindo a janela de video. Atalhos dentro dela:
echo    R = rotaciona     + / - = ajusta o limiar de certeza
echo    L = LED flash     S = salva print     Q ou ESC = sai
echo ======================================================================
echo.

cd /d "%KIT%"
"%PY%" testar_esp32_usb.py

echo.
echo O teste encerrou.
pause
exit /b 0

:erro
echo.
echo *** Tira print desta janela inteira e manda. ***
pause
exit /b 1
