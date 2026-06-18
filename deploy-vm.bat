@echo off
REM PLI-HazardTrack — Deploy: commit + push + VM + health + browser
setlocal EnableDelayedExpansion
chcp 65001 > nul

set "ROOT=%~dp0"
set "PLINK=C:\Program Files\PuTTY\plink.exe"
set "PPK=%ROOT%SRV-SISTEMA-30001480.ppk"
set "VM=ubuntu@56.125.163.194"
set "APP_URL=http://pli-hazardtrack.56-125-163-194.sslip.io"
set "BRANCH=main"

set "MSG=%*"
if "%MSG%"=="" set "MSG=deploy: atualizacao %date% %time%"

if not exist "%PLINK%" (
    echo.
    echo [ERRO] PuTTY plink.exe nao encontrado em "%PLINK%"
    exit /b 2
)
if not exist "%PPK%" (
    echo.
    echo [ERRO] Chave PuTTY nao encontrada: "%PPK%"
    exit /b 2
)

cd /d "%ROOT%"

call :banner "ETAPA 1/6 — Alteracoes no controle de codigo"
git status --short
if errorlevel 1 goto :fail

git diff --quiet
set "DIRTY=!errorlevel!"
git diff --cached --quiet
set "STAGED=!errorlevel!"

if !DIRTY! equ 0 if !STAGED! equ 0 (
    echo.
    echo   Nada para commitar — seguindo para push e VM.
    goto :step_push
)

call :banner "ETAPA 2/6 — Commit local"
echo   Mensagem: %MSG%
echo.

REM Stage alteracoes (exclui segredos e arquivos locais)
git add -A -- . ":!*.session.sql" ":!*.ppk" ":!.env" ":!.env.*"
if errorlevel 1 goto :fail

git diff --cached --quiet
if not errorlevel 1 (
    echo.
    echo   Nenhum arquivo elegivel para commit apos filtros de seguranca.
    goto :step_push
)

git commit -m "%MSG%"
if errorlevel 1 goto :fail
echo.
echo   Commit criado.

:step_push
call :banner "ETAPA 3/6 — Push para GitHub (origin/%BRANCH%)"
git push origin %BRANCH%
if errorlevel 1 goto :fail
for /f "delims=" %%H in ('git rev-parse --short HEAD') do set "LOCAL_SHA=%%H"
echo.
echo   Push OK — commit %%LOCAL_SHA%% no GitHub.

call :banner "ETAPA 4/6 — Atualizando a VM"
echo   Host: %VM%
echo   A VM vai baixar origin/main e reiniciar o container.
echo.

set "REMOTE=cd /opt/pli-hazardtrack && bash .deploy/update_vm.sh"

"%PLINK%" -ssh %VM% -i "%PPK%" -batch "%REMOTE%"
if errorlevel 1 goto :fail

call :banner "ETAPA 5/6 — Healthcheck publico"
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
    echo           O MERGE pode estar no primeiro ciclo — abrindo o site mesmo assim.
) else (
    echo.
    echo   Aplicacao saudavel.
)

call :banner "ETAPA 6/6 — Abrindo no navegador"
echo   %APP_URL%
start "" "%APP_URL%"

echo.
echo ========================================================================
echo   DEPLOY CONCLUIDO
echo ========================================================================
echo   Site: %APP_URL%
echo   Ops:  %APP_URL%/ops/login
echo ========================================================================
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
echo  DEPLOY INTERROMPIDO — corrija o erro acima e rode a task de novo.
echo ========================================================================
exit /b 1
