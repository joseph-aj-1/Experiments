# Starts the EIF event capture. Prompts for the MCPAgent API key if it is not already set;
# the key is kept in memory for this run only and is never written to disk.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Host "The .NET SDK was not found. Install it with:" -ForegroundColor Yellow
    Write-Host "    winget install Microsoft.DotNet.SDK.8"
    Write-Host "then open a new PowerShell window and run .\run.ps1 again."
    exit 1
}

if (-not $env:EIF_AGENT_SECRET -and -not (Test-Path "agent.secret")) {
    $secure = Read-Host "Paste the MCPAgent API key" -AsSecureString
    $env:EIF_AGENT_SECRET = [System.Net.NetworkCredential]::new("", $secure).Password
}

dotnet run --project EifListener.csproj
