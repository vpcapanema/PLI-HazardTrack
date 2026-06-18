@echo off
REM ============================================================================
REM PLI-HazardTrack — Deploy completo (Windows)
REM   1) git add + commit (alteracoes visiveis no controle de codigo)
REM   2) git push origin main
REM   3) VM: git pull + rebuild condicional + restart
REM   4) healthcheck externo + abrir navegador
REM
REM Uso:
REM   deploy-vm.bat "feat: descricao do commit"
REM   (ou via Task do VS Code/Cursor: Deploy commit push VM)
REM ============================================================================

setlocal EnableDelayedExpansion
chcp 65001 > nul

set "ROOT=%~dp0"
set "PLINK=C:\Program Files\PuTTY\plink.exe"
set "PPK=%ROOT%SRV-SISTEMA-30001480.ppk"
set "VM=ubuntu@56.125.163.194"
set "REMOTE_CMD=cd /opt/pli-hazardtrack && git pull --ff-only origin main && bash .deploy/update_vm.sh"
set "APP_URL=http://pli-hazardtrack.56-125-163-194.sslip.io"
set "BRANCH=main"

set "MSG=%*"
if "%MSG%"=="" set "MSG=deploy: atualizacao %date% %time%"

if not exist "%PLINK%" (
    echo.
    echo [ERRO] PuTTY plink.exe nao encontrado.
    echo        Instale o PuTTY ou ajuste PLINK neste script.
    exit /b 2
)

if not exist "%PPK%" (
    echo.
    echo [ERRO] Chave nao encontrada: %PPK%
    exit /b 2
)

cd /d "%ROOT%"

call :banner "ETAPA 1/6 — O que vai para o GitHub"
git status --short
if errorlevel 1 goto :fail

git diff --quiet
set "HAS_UNSTAGED=!errorlevel!"
git diff --cached --quiet
set "HAS_STAGED=!errorlevel!"

if !HAS_UNSTAGED! equ 0 if !HAS_STAGED! equ 0 (
    echo.
    echo   Nenhuma alteracao local — seguindo para push e VM.
    goto :step_push
)

call :banner "ETAPA 2/6 — Commit local"
echo   Mensagem: %MSG%
echo.

git add -A
if errorlevel 1 goto :fail

git commit -m "%MSG%"
if errorlevel 1 goto :fail
echo.
echo   Commit criado com sucesso.

:step_push
call :banner "ETAPA 3/6 — Enviando para o GitHub (origin/%BRANCH%)"
git push origin %BRANCH%
if errorlevel 1 goto :fail
echo.
echo   Push concluido — GitHub sincronizado.

call :banner "ETAPA 4/6 — Atualizando a VM (pull + container)"
echo   Conectando em %VM% ...
echo.

"%PLINK%" -ssh %VM% -i "%PPK%" -batch %REMOTE_CMD%
if errorlevel 1 goto :fail

call :banner "ETAPA 5/6 — Confirmando saude da aplicacao"
echo   Testando %APP_URL%/api/health ...
echo.

set "HEALTH_OK=0"
for /L %%i in (1,1,12) do (
    curl -fsS "%APP_URL%/api/health" >nul 2>&1
    if not errorlevel 1 (
        set "HEALTH_OK=1"
        echo   Aplicacao respondeu OK na tentativa %%i.
        goto :health_done
    )
    echo   Aguardando container... (%%i/12^)
    timeout /t 5 /nobreak >nul
)

:health_done
if "!HEALTH_OK!"=="0" (
    echo.
    echo   [AVISO] Healthcheck externo nao confirmou 200 ainda.
    echo           A VM pode estar finalizando o boot do MERGE.
    echo           Abrindo o site mesmo assim.
) else (
    echo.
    echo   Healthcheck externo OK.
)

call :banner "ETAPA 6/6 — Abrindo no navegador"
echo   %APP_URL%
start "" "%APP_URL%"

echo.
echo ========================================================================
echo   DEPLOY CONCLUIDO
echo ========================================================================
echo   Site:  %APP_URL%
echo   Ops:   %APP_URL%/ops/login
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
echo  DEPLOY INTERROMPIDO — veja a mensagem acima e corrija.
echo ========================================================================
exit /b 1
