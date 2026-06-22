@echo off
REM PLI-HazardTrack — Envia origin/main ao GitHub (se necessario) e atualiza a VM.
REM Commit pelo Controle de Codigo; este script faz push + deploy remoto.
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

call :banner "Verificando repositorio local"
for /f "delims=" %%H in ('git rev-parse --short HEAD 2^>nul') do set "LOCAL_SHA=%%H"
for /f "delims=" %%B in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%B"
echo   Branch: !BRANCH!
echo   HEAD local: !LOCAL_SHA!
git status -sb 2>nul
echo.

set "DIRTY=0"
for /f %%C in ('git status --porcelain 2^>nul ^| find /c /v ""') do set "DIRTY=%%C"
if !DIRTY! GTR 0 (
    echo [ERRO] Ha !DIRTY! alteracao local ainda nao commitada.
    echo        A VM so recebe o que esta no GitHub - origin/!BRANCH!
    echo        No Controle de Codigo: revise, faca Commit e rode o deploy de novo.
    echo.
    git status --short 2>nul
    exit /b 1
)

set "AHEAD=0"
for /f %%A in ('git rev-list --count origin/!BRANCH!..HEAD 2^>nul') do set "AHEAD=%%A"
if not defined AHEAD set "AHEAD=0"

if !AHEAD! GTR 0 (
    call :banner "Enviando !AHEAD! commit(s) para o GitHub"
    git push origin !BRANCH!
    if errorlevel 1 (
        echo.
        echo [ERRO] git push falhou. A VM nao sera atualizada.
        exit /b 1
    )
    for /f "delims=" %%H in ('git rev-parse --short HEAD 2^>nul') do set "LOCAL_SHA=%%H"
    echo   Push concluido. HEAD: !LOCAL_SHA!
) else (
    echo   Nenhum commit pendente de push — GitHub ja esta em !LOCAL_SHA!.
)

call :banner "Atualizando VM"
echo   Host: %VM%
echo   A VM executa git fetch + reset --hard origin/!BRANCH! e reinicia o container.
echo.

set "REMOTE=cd /opt/pli-hazardtrack && sed -i 's/\r$//' .deploy/update_vm.sh && bash .deploy/update_vm.sh"
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
