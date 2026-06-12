@echo off
setlocal EnableDelayedExpansion

set "IMAGE=pli-hazardtrack"
set "TAG=prod"
set "ROOT=%~dp0"

echo ============================================================
echo   PLI-HazardTrack :: Build imagem Docker (producao)
echo ============================================================
echo.

cd /d "%ROOT%"

echo [1/3] Verificando Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo ERRO: Docker Desktop nao esta rodando.
    echo Abra o Docker Desktop e execute este script novamente.
    goto :fim_erro
)
echo    - Docker OK
echo.

echo [2/3] Build %IMAGE%:%TAG% ...
docker build -t %IMAGE%:%TAG% -t %IMAGE%:latest "%ROOT%"
if errorlevel 1 (
    echo ERRO: falha no docker build.
    goto :fim_erro
)
echo.

echo [3/3] Imagem pronta:
docker images %IMAGE% --format "   {{.Repository}}:{{.Tag}}  {{.Size}}"
echo.
echo Testar localmente:
echo   docker run --rm -p 5050:5050 -e PORT=5050 %IMAGE%:%TAG%
echo   curl http://localhost:5050/api/health
echo.
echo Publicar (exemplo Docker Hub):
echo   docker tag %IMAGE%:%TAG% SEU_USUARIO/%IMAGE%:%TAG%
echo   docker push SEU_USUARIO/%IMAGE%:%TAG%
echo.
echo Render: use render.yaml (runtime: docker) ou aponte para a imagem publicada.
echo.
echo ============================================================
echo   BUILD CONCLUIDO COM SUCESSO
echo ============================================================
goto :fim_ok

:fim_erro
echo.
echo ============================================================
echo   BUILD FALHOU — leia a mensagem acima
echo ============================================================

:fim_ok
echo.
pause
endlocal
