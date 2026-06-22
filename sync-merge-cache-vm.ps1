# Envia o cache MERGE local (data/_cache/merge) para o volume Docker na VM.
# Para o container, repovoa o volume e sobe de novo.
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CacheDir = Join-Path $Root "data\_cache\merge"
$Plink = "C:\Program Files\PuTTY\plink.exe"
$Pscp = "C:\Program Files\PuTTY\pscp.exe"
$Ppk = Join-Path $Root "SRV-SISTEMA-30001480.ppk"
$Vm = "ubuntu@56.125.163.194"
$Vol = "pli_hazardtrack_merge_cache"
$RemoteTar = "/tmp/pli-merge-cache.tgz"
$AppDir = "/opt/pli-hazardtrack"

if (-not (Test-Path $CacheDir)) {
    Write-Error "Cache local ausente: $CacheDir"
}
$gribCount = @(
    Get-ChildItem -Path $CacheDir -Recurse -Filter "*.grib2" -ErrorAction SilentlyContinue
).Count
if ($gribCount -lt 1) {
    Write-Error "Nenhum GRIB em $CacheDir. Rode o backend local antes."
}

Write-Host "Cache local: $gribCount GRIB(s) em $CacheDir"
if ($DryRun) { exit 0 }

$LocalTar = Join-Path $env:TEMP "pli-merge-cache.tgz"
if (Test-Path $LocalTar) { Remove-Item $LocalTar -Force }
& tar -czf $LocalTar -C $CacheDir .
$sizeMb = [math]::Round((Get-Item $LocalTar).Length / 1MB, 1)
Write-Host "Enviando ${sizeMb} MB para a VM..."

& $Pscp -i $Ppk $LocalTar "${Vm}:${RemoteTar}"

$RemoteScript = @'
set -eu
VOL=pli_hazardtrack_merge_cache
TAR=/tmp/pli-merge-cache.tgz
APP=/opt/pli-hazardtrack
cd "$APP"
docker compose -f docker-compose.vm.yml stop app
docker run --rm -v "${VOL}:/cache" alpine:3.20 sh -c "rm -rf /cache/grib /cache/samples /cache/.ingest.lock"
docker run --rm -v "${VOL}:/cache" -v "${TAR}:${TAR}:ro" alpine:3.20 sh -c "cd /cache && tar xzf ${TAR} && rm -f ${TAR}"
echo "Arquivos no volume:"
docker run --rm -v "${VOL}:/cache" alpine:3.20 sh -c "find /cache -type f | wc -l; du -sh /cache"
docker compose -f docker-compose.vm.yml up -d app
'@

& $Plink -ssh $Vm -i $Ppk -batch $RemoteScript
Remove-Item $LocalTar -Force -ErrorAction SilentlyContinue
Write-Host "Cache MERGE repovoado no volume $Vol e container reiniciado."
