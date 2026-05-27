# Baixa Leaflet 1.9.4 + leaflet.heat 0.2.0 para static/vendor/leaflet
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dst  = Join-Path $root 'static\vendor\leaflet'
$img  = Join-Path $dst 'images'
New-Item -ItemType Directory -Force -Path $img | Out-Null

$base = 'https://unpkg.com/leaflet@1.9.4/dist'
Invoke-WebRequest -UseBasicParsing -Uri "$base/leaflet.css" -OutFile (Join-Path $dst 'leaflet.css')
Invoke-WebRequest -UseBasicParsing -Uri "$base/leaflet.js"  -OutFile (Join-Path $dst 'leaflet.js')
Invoke-WebRequest -UseBasicParsing -Uri 'https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js' `
                  -OutFile (Join-Path $dst 'leaflet-heat.js')

$files = @('layers.png','layers-2x.png','marker-icon.png','marker-icon-2x.png','marker-shadow.png')
foreach ($f in $files) {
    Invoke-WebRequest -UseBasicParsing -Uri "$base/images/$f" -OutFile (Join-Path $img $f)
}

Get-ChildItem -Recurse $dst | Select-Object FullName, Length | Format-Table -AutoSize
