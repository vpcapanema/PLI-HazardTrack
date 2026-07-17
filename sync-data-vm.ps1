$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Plink = "C:\Program Files\PuTTY\plink.exe"
$Pscp = "C:\Program Files\PuTTY\pscp.exe"
$Ppk = Join-Path $Root "SRV-SISTEMA-30001480.ppk"
$Vm = "ubuntu@56.125.163.194"
$RemoteZip = "/tmp/pli-hazardtrack-heavy-data.zip"
$AppDir = "/opt/pli-hazardtrack"
$Container = "pli_hazardtrack_app"
$AppUrl = "https://56.125.163.194/pli-hazardtrack"
$Zip = Join-Path $env:TEMP "pli-hazardtrack-heavy-data.zip"
$Stage = Join-Path $env:TEMP "pli-hazardtrack-heavy-data"

function Write-Banner([string]$Title) {
    Write-Host ""
    Write-Host "========================================================================"
    Write-Host " $Title"
    Write-Host "========================================================================"
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Comando falhou ($LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

if (!(Test-Path $Plink)) { throw "PuTTY plink.exe nao encontrado em $Plink" }
if (!(Test-Path $Pscp)) { throw "PuTTY pscp.exe nao encontrado em $Pscp" }
if (!(Test-Path $Ppk)) { throw "Chave PuTTY nao encontrada: $Ppk" }

Set-Location $Root

Write-Banner "Empacotando dados pesados locais"
Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $Zip -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $Stage | Out-Null

$Items = @(
    "data/queimadas/base/trechos_der_sp.gpkg",
    "data/queimadas/base/limite_sp.gpkg",
    "data/queimadas/base/limite_sp_ibge.geojson",
    "data/queimadas/processed/risco_trechos_der.gpkg",
    "static/data/queimadas/risco_trechos_der_latest.geojson",
    "static/data/queimadas/risco_trechos_der_latest.json",
    "static/data/queimadas/risco_trechos_der_stats.json"
)

$Items += Get-ChildItem "static/data/queimadas" -Filter "risco_trechos_der_*.geojson" |
    ForEach-Object { ($_.FullName.Substring($Root.Length + 1) -replace "\\", "/") }
$Items = $Items | Sort-Object -Unique

foreach ($Rel in $Items) {
    $Src = Join-Path $Root $Rel
    if (!(Test-Path $Src)) { throw "Arquivo necessario ausente: $Rel" }
    $Dst = Join-Path $Stage $Rel
    New-Item -ItemType Directory -Path (Split-Path $Dst -Parent) -Force | Out-Null
    Copy-Item $Src $Dst -Force
    $SizeMb = (Get-Item $Src).Length / 1MB
    Write-Host ("  {0} {1:n1} MB" -f $Rel, $SizeMb)
}

Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Zip -Force
Write-Host ("ZIP: {0} {1:n1} MB" -f $Zip, ((Get-Item $Zip).Length / 1MB))

Write-Banner "Enviando ZIP para a VM"
Invoke-Checked $Pscp @("-i", $Ppk, "-batch", $Zip, "${Vm}:${RemoteZip}")

Write-Banner "Aplicando dados no host e no container"
$RemoteApply = @"
python3 -m zipfile -e $RemoteZip $AppDir &&
docker exec $Container mkdir -p /app/data/queimadas/base /app/data/queimadas/processed /app/static/data/queimadas &&
docker cp $AppDir/data/queimadas/base/. $Container`:/app/data/queimadas/base &&
docker cp $AppDir/data/queimadas/processed/. $Container`:/app/data/queimadas/processed &&
docker cp $AppDir/static/data/queimadas/. $Container`:/app/static/data/queimadas &&
rm -f $RemoteZip
"@ -replace "`r?`n", " "
Invoke-Checked $Plink @("-ssh", $Vm, "-i", $Ppk, "-batch", $RemoteApply)

Write-Banner "Validando dados no container"
$RemoteCheck = @"
docker exec $Container python -m json.tool /app/static/data/queimadas/risco_trechos_der_latest.geojson >/dev/null &&
docker exec $Container test -s /app/data/queimadas/processed/risco_trechos_der.gpkg &&
docker exec $Container ls -lh /app/static/data/queimadas/risco_trechos_der_latest.geojson /app/data/queimadas/processed/risco_trechos_der.gpkg
"@ -replace "`r?`n", " "
Invoke-Checked $Plink @("-ssh", $Vm, "-i", $Ppk, "-batch", $RemoteCheck)

Write-Banner "Healthcheck publico"
curl.exe -fsS "$AppUrl/api/health" | Out-Null
Write-Host "  OK - aplicacao saudavel."
Write-Host "  $AppUrl"
