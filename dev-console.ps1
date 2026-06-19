# Estilo visual do terminal dev (cores, etapas, destaques).
$ErrorActionPreference = "SilentlyContinue"

function Enable-DevConsoleAnsi {
    if (-not [Console]::IsOutputRedirected) {
        $null = [Console]::OutputEncoding
    }
    if ($PSVersionTable.PSEdition -eq "Desktop") {
        $sig = @"
using System;
using System.Runtime.InteropServices;
public class DevConsoleVT {
    [DllImport("kernel32.dll")]
    private static extern bool GetConsoleMode(IntPtr h, out uint m);
    [DllImport("kernel32.dll")]
    public static extern bool SetConsoleMode(IntPtr h, uint m);
    [DllImport("kernel32.dll")]
    public static extern IntPtr GetStdHandle(int n);
    public static void Enable() {
        var h = GetStdHandle(-11);
        if (h == IntPtr.Zero) { return; }
        uint mode;
        if (!GetConsoleMode(h, out mode)) { return; }
        SetConsoleMode(h, mode | 4u);
    }
}
"@
        try {
            Add-Type -TypeDefinition $sig -ErrorAction Stop
            [DevConsoleVT]::Enable()
        } catch { }
    }
}

function Write-DevGap {
    param([int]$Lines = 1)
    for ($i = 0; $i -lt $Lines; $i++) { Write-Host "" }
}

function Write-DevBanner {
    param([string]$Title)
    Write-DevGap
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-Host "  $Title" -ForegroundColor White
    Write-Host "================================================================" -ForegroundColor Magenta
    Write-DevGap
}

function Write-DevStage {
    param(
        [int]$Step,
        [int]$Total,
        [string]$Title
    )
    Write-DevGap
    Write-Host "[$Step/$Total] $Title" -ForegroundColor Cyan
}

function Write-DevSub {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Write-DevOk {
    param(
        [string]$Message,
        [switch]$Major
    )
    if ($Major) {
        Write-DevGap
        Write-Host "  >> $Message" -ForegroundColor Green
        Write-DevGap
    } else {
        Write-Host "    [ok] $Message" -ForegroundColor Green
    }
}

function Write-DevWarn {
    param(
        [string]$Message,
        [switch]$Major
    )
    if ($Major) {
        Write-DevGap
        Write-Host "  !! $Message" -ForegroundColor Yellow
        Write-DevGap
    } else {
        Write-Host "    [!] $Message" -ForegroundColor Yellow
    }
}

function Write-DevFail {
    param(
        [string]$Message,
        [switch]$Major
    )
    if ($Major) {
        Write-DevGap
        Write-Host "  XX $Message" -ForegroundColor Red
        Write-DevGap
    } else {
        Write-Host "    [x] $Message" -ForegroundColor Red
    }
}

function Write-DevInfo {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor Gray
}

function Write-DevDivider {
    Write-Host "----------------------------------------------------------------" -ForegroundColor DarkGray
}

function Write-DevSectionEnd {
    param([string]$Label = "")
    if ($Label) {
        Write-Host "    --- fim: $Label ---" -ForegroundColor DarkGray
    }
    Write-DevGap
}

function Start-DevHealthMonitor {
    param(
        [string]$Root,
        [int]$Port = 5050
    )
    $waitScript = Join-Path $Root "dev-wait-browser.ps1"
    $null = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $waitScript,
            "-Root", $Root,
            "-Port", "$Port"
        ) `
        -WindowStyle Hidden
}

Enable-DevConsoleAnsi
