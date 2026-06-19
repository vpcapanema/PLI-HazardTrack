# PLI-HazardTrack - Mata porta, sobe backend, healthcheck, abre navegador.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Root "dev-console.ps1")

$Port = 5050

Write-DevBanner "PLI-HazardTrack :: Dev Server"

# --- Etapa 1: liberar porta ---
Write-DevStage -Step 1 -Total 4 -Title "Liberando porta $Port"
$script:hadListener = $false
try {
    Get-NetTCPConnection -LocalPort $Port -ErrorAction Stop |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object {
            Write-DevSub "Encerrando PID $_"
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
            $script:hadListener = $true
        }
} catch {
    $lines = netstat -aon | Select-String ":$Port " | Select-String "LISTENING"
    foreach ($line in $lines) {
        $procId = ($line -split '\s+')[-1]
        if ($procId -and $procId -ne "0") {
            Write-DevSub "Encerrando PID $procId"
            taskkill /F /PID $procId 2>$null | Out-Null
            $script:hadListener = $true
        }
    }
}
if ($script:hadListener) {
    Write-DevOk "Porta $Port liberada"
} else {
    Write-DevInfo "Nenhum processo na porta $Port"
}
Start-Sleep -Seconds 1
Write-DevSectionEnd "porta $Port"

# --- Etapa 2: monitor de health ---
Write-DevStage -Step 2 -Total 4 -Title "Monitor de saude (abre navegador quando OK)"
Start-DevHealthMonitor -Root $Root -Port $Port
Write-DevOk "Monitor em segundo plano"
Write-DevSectionEnd "monitor"

# --- Etapa 3: backend ---
Write-DevStage -Step 3 -Total 4 -Title "Backend Flask - logs em tempo real (Ctrl+C para parar)"
Write-DevDivider
Write-DevInfo "Fontes: MERGE/INPE (CPTEC), previsao WRF, malha DER-SP"
Write-DevInfo "Login /admin: gestor SIGMA (SIGMA_POSTGRES_* no .env)"
Write-DevInfo "HTTP do frontend: linhas [http] (verde=OK, vermelho=erro)"
Write-DevDivider
Write-DevGap

$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
    Write-DevWarn "venv ausente; usando python do PATH"
}

$env:PORT = "$Port"
$env:PYTHONUNBUFFERED = "1"
$env:SAMAEG_DEV_LOG = "1"
$env:SAMAEG_DEV_COLOR = "1"
$env:SAMAEG_WORKERS = "12"
$env:SAMAEG_DECODE_WORKERS = "6"
$env:SAMAEG_INGEST_INTERVAL_S = "120"

Set-Location $Root
& $PythonExe -u (Join-Path $Root "app.py")
