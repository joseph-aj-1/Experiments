# Sets up the Configured MBOM Builder on this PC and prints the Claude Desktop entry.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python 3.10 or newer is required: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python environment..."
    python -m venv .venv
}
Write-Host "Installing packages..."
.\.venv\Scripts\python -m pip install --quiet --upgrade pip
.\.venv\Scripts\python -m pip install --quiet -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "Created .env - open it and fill in your 3DEXPERIENCE details before first use." -ForegroundColor Yellow
}
New-Item -ItemType Directory -Force -Path runs | Out-Null

$pyexe = (Resolve-Path ".\.venv\Scripts\python.exe").Path -replace '\\', '\\'
$srv = (Resolve-Path ".\server.py").Path -replace '\\', '\\'
Write-Host ""
Write-Host 'Add this inside "mcpServers" in %APPDATA%\Claude\claude_desktop_config.json, then fully restart Claude Desktop:' -ForegroundColor Cyan
Write-Host ""
Write-Host "    `"configured-mbom-builder`": {"
Write-Host "      `"command`": `"$pyexe`","
Write-Host "      `"args`": [`"$srv`"]"
Write-Host "    }"
Write-Host ""
Write-Host "Offline self-test (no tenant needed):  .\.venv\Scripts\python tests\test_builder.py"
