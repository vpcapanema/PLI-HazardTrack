param(
    [string]$Root = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [int]$Port = 5050
)

if (-not (Get-Command Write-DevStage -ErrorAction SilentlyContinue)) {
    . (Join-Path $Root "dev-console.ps1")
}

$HealthUrl = "http://localhost:$Port/api/health"
$AppUrl = "http://localhost:$Port"
$MaxAttempts = 90

Write-DevGap
Write-DevSub "healthcheck: $HealthUrl"

for ($i = 1; $i -le $MaxAttempts; $i++) {
    $ok = $false
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
        $ok = ($r.StatusCode -eq 200)
    } catch {
        $null = curl.exe -fsS $HealthUrl 2>$null
        $ok = ($LASTEXITCODE -eq 0)
    }
    if ($ok) {
        Write-DevStage -Step 4 -Total 4 -Title "Servidor pronto"
        Write-DevOk "Health OK na tentativa $i" -Major
        Write-DevOk "Abrindo $AppUrl no navegador" -Major
        Start-Process $AppUrl
        return
    }
    if ($i -le 3) {
        Write-DevSub "aguardando boot... $i/$MaxAttempts"
    } elseif ($i -eq 10) {
        Write-DevWarn "ainda carregando MERGE e UAs... $i/$MaxAttempts"
    } elseif ($i -eq 30) {
        Write-DevWarn "ingest MERGE em andamento... $i/$MaxAttempts"
    }
    Start-Sleep -Seconds 2
}

Write-DevStage -Step 4 -Total 4 -Title "Servidor (health nao confirmado)"
Write-DevWarn "Health nao respondeu em $MaxAttempts tentativas" -Major
Write-DevWarn "Abrindo $AppUrl mesmo assim" -Major
Start-Process $AppUrl
