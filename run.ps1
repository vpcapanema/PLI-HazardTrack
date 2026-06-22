# Executa qualquer comando Python dentro do venv do projeto.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Error @"
.venv nao encontrado em $Root
Crie e instale as dependencias:
  py -3.12 -m venv .venv
  .\.venv\Scripts\pip install -r requirements.txt
"@
    exit 1
}

Set-Location $Root
& $PythonExe @Args
exit $LASTEXITCODE
