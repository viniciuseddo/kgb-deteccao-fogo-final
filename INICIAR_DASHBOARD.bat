@echo off
setlocal
chcp 65001 >nul
title Vigia KGB - Dashboard de Alertas
cls

rem ==============================================================
rem  Sobe o painel de alertas. Le o SQLite que o sistema_vigia.py
rem  alimenta e abre no navegador em http://localhost:8060
rem  Pode rodar junto com o INICIAR_VIGIA.bat.
rem ==============================================================

set PROJ=%~dp0
if "%PROJ:~-1%"=="\" set PROJ=%PROJ:~0,-1%
if not exist "%PROJ%\venv\Scripts\python.exe" set PROJ=C:\projetos\deteccao-fogo
set PY=%PROJ%\venv\Scripts\python.exe

echo ======================================================================
echo    DASHBOARD DE ALERTAS - VIGIA KGB
echo    http://localhost:8060
echo ======================================================================
echo.

if not exist "%PY%" (
  echo Nao encontrei o Python do venv em:
  echo   %PY%
  goto erro
)

cd /d "%PROJ%"
"%PY%" dashboard.py --porta 8060

echo.
pause
exit /b 0

:erro
echo.
echo *** Tira print desta janela e manda. ***
pause
exit /b 1
