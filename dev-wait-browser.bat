@echo off
setlocal
set HEALTH_URL=http://localhost:5050/api/health
set APP_URL=http://localhost:5050
set MAX_ATTEMPTS=90

for /L %%i in (1,1,%MAX_ATTEMPTS%) do (
    curl -fsS "%HEALTH_URL%" >nul 2>&1
    if not errorlevel 1 (
        echo.
        echo [4/4] Servidor saudavel (tentativa %%i) - abrindo %APP_URL%
        start "" "%APP_URL%"
        exit /b 0
    )
    if %%i LEQ 3 (
        echo    aguardando boot... %%i/%MAX_ATTEMPTS%
    ) else if %%i==10 (
        echo    ainda carregando MERGE/UAs... %%i/%MAX_ATTEMPTS%
    ) else if %%i==30 (
        echo    ingest em andamento... %%i/%MAX_ATTEMPTS%
    )
    timeout /t 2 /nobreak >nul
)

echo.
echo [4/4] AVISO: health nao confirmou em %MAX_ATTEMPTS% tentativas - abrindo mesmo assim.
start "" "%APP_URL%"
endlocal
