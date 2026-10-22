@echo off
setlocal
chcp 65001 >nul
title Vigia KGB - quais gravacoes tem chama
cls

rem ==============================================================
rem  Varre as gravacoes da pasta tomadas e diz quantos quadros de
rem  cada uma tem chama. Nao dispara nada e nao grava nada.
rem  Use para escolher qual gravacao usar no video.
rem ==============================================================

set PROJ=C:\projetos\deteccao-fogo
set PY=%PROJ%\venv\Scripts\python.exe

echo ======================================================================
echo    VARREDURA DAS GRAVACOES
echo    So analisa. Nao aciona o hardware e nao grava no banco.
echo ======================================================================
echo.

if not exist "%PY%" (
  echo Nao encontrei o Python do venv em:
  echo   %PY%
  goto erro
)

cd /d "%PROJ%"
"%PY%" reprocessar.py --listar

echo.
pause
exit /b 0

:erro
echo.
echo *** Tira print desta janela e manda. ***
pause
exit /b 1
