@echo off
REM PLI-HazardTrack — Sincroniza a VM com origin/main (sem commit/push).
REM Faca commit e push pelo painel Controle de Codigo do Cursor/VS Code.
setlocal EnableDelayedExpansion
chcp 65001 > nul

set "ROOT=%~dp0"
set "PLINK=C:\Program Files\PuTTY\plink.exe"
set "PPK=%ROOT%SRV-SISTEMA-30001480.ppk"
set "VM=ubuntu@56.125.163.194"
set "APP_URL=http://pli-hazardtrack.56-125-163-194.sslip.io"

if not exist "%PLINK%" (
    echo [ERRO] PuTTY plink.exe nao encontrado em "%PLINK%"
    exit /b 2
)
if not exist "%PPK%" (
    echo [ERRO] Chave PuTTY nao encontrada: "%PPK%"
    exit /b 2
)

cd /d "%ROOT%"

call :banner "Commit local (use o painel Git se ainda nao fez push)"
for /f "delims=" %%H in ('git rev-parse --short HEAD 2^>nul') do set "LOCAL_SHA=%%H"
echo   HEAD local: !LOCAL_SHA!
git status -sb 2>nul

call :banner "Atualizando VM agora"
echo   Host: %VM%
echo   A VM baixa origin/main e reinicia o container se necessario.
echo.

set "REMOTE=cd /opt/pli-hazardtrack && bash .deploy/update_vm.sh"
"%PLINK%" -ssh %VM% -i "%PPK%" -batch "%REMOTE%"
if errorlevel 1 goto :fail

call :banner "Healthcheck publico"
echo   URL: %APP_URL%/api/health
echo.

set "HEALTH_OK=0"
for /L %%i in (1,1,15) do (
    curl -fsS "%APP_URL%/api/health" >nul 2>&1
    if not errorlevel 1 (
        set "HEALTH_OK=1"
        echo   OK — aplicacao respondeu na tentativa %%i.
        goto :health_done
    )
    echo   Aguardando... %%i/15
    timeout /t 5 /nobreak >nul
)

:health_done
if "!HEALTH_OK!"=="0" (
    echo.
    echo   [AVISO] Healthcheck ainda nao confirmou 200.
) else (
    echo.
    echo   Aplicacao saudavel.
)

call :banner "Site"
echo   %APP_URL%
start "" "%APP_URL%"
exit /b 0

:banner
echo.
echo ========================================================================
echo  %~1
echo ========================================================================
goto :eof

:fail
echo.
echo ========================================================================
echo  SYNC VM INTERROMPIDO
echo ========================================================================
exit /b 1
