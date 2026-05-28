@echo off
REM ============================================================================
REM PLI-HazardTrack - Deploy completo: commit -> push -> update na VM
REM
REM Acompanha todas as etapas no console:
REM   1) git status (mostra o que vai ser commitado)
REM   2) git add -A + git commit (com a mensagem passada via %*)
REM   3) git push origin main
REM   4) ssh ubuntu@56.125.163.194 -> bash .deploy/update_vm.sh
REM
REM Para a primeira falha. Se nao houver mudancas para commitar, pula direto
REM para o update da VM (util quando voce so quer reaplicar a imagem).
REM ============================================================================

setlocal EnableDelayedExpansion
chcp 65001 > nul

set "WORKSPACE=%~dp0.."
set "PLINK=C:\Program Files\PuTTY\plink.exe"
set "PPK=%WORKSPACE%\SRV-SISTEMA-30001480.ppk"
set "VM=ubuntu@56.125.163.194"
set "REMOTE_CMD=bash /opt/pli-hazardtrack/.deploy/update_vm.sh"

set "MSG=%*"
if "%MSG%"=="" (
    echo.
    echo [ERRO] Mensagem de commit nao informada.
    echo Uso: deploy-vm.bat "feat: descricao curta"
    exit /b 2
)

if not exist "%PLINK%" (
    echo.
    echo [ERRO] plink.exe nao encontrado em "%PLINK%"
    echo Instale o PuTTY ou ajuste o caminho neste script.
    exit /b 2
)

if not exist "%PPK%" (
    echo.
    echo [ERRO] Chave PuTTY nao encontrada em "%PPK%"
    exit /b 2
)

cd /d "%WORKSPACE%"

echo.
echo =====================================================================
echo  ETAPA 1/4 - Status do repositorio
echo =====================================================================
git status --short
if errorlevel 1 goto :fail

REM Verifica se ha algo para commitar
git diff --quiet && git diff --cached --quiet
if not errorlevel 1 (
    echo.
    echo [INFO] Nenhuma mudanca para commitar - pulando para push/update.
    goto :step_push
)

echo.
echo =====================================================================
echo  ETAPA 2/4 - Commit local
echo =====================================================================
echo Mensagem: %MSG%
echo.

git add -A
if errorlevel 1 goto :fail

git commit -m %MSG%
if errorlevel 1 goto :fail

:step_push
echo.
echo =====================================================================
echo  ETAPA 3/4 - Push para o GitHub (origin/main)
echo =====================================================================
git push origin main
if errorlevel 1 goto :fail

echo.
echo =====================================================================
echo  ETAPA 4/4 - Update da VM (pull + rebuild + restart)
echo =====================================================================
echo Conectando em %VM% e rodando %REMOTE_CMD%
echo.

"%PLINK%" -ssh %VM% -i "%PPK%" -batch %REMOTE_CMD%
if errorlevel 1 goto :fail

echo.
echo =====================================================================
echo  DEPLOY CONCLUIDO
echo =====================================================================
echo  URL publica: http://pli-hazardtrack.56-125-163-194.sslip.io
echo  /ops:        http://pli-hazardtrack.56-125-163-194.sslip.io/ops/login
echo =====================================================================
exit /b 0

:fail
echo.
echo =====================================================================
echo  [FALHA] - veja os logs acima e corrija antes de tentar de novo.
echo =====================================================================
exit /b 1
