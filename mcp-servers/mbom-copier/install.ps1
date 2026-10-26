<#
  MBOM Copier service - install, update, show pairing details, or uninstall (current user, no admin rights).

    powershell -ExecutionPolicy Bypass -File .\install.ps1              install or update, start at sign-in, start now
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Info        show the address and pairing token again
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall   stop it and remove the auto-start (keeps your files)

  Uses mbom-copier-service.exe when it sits in this folder (no Python needed), otherwise Python 3.10+ in .venv.
  Settings (target.env), the pairing token (service.json) and run records (runs\) stay in this folder.
#>
param([switch]$Info, [switch]$Uninstall, [switch]$NoAutoStart)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$TaskName = "MBOM Copier service"
$Here = $PSScriptRoot
$Exe = Join-Path $Here "mbom-copier-service.exe"
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupLink = if ($StartupDir) { Join-Path $StartupDir "MBOM Copier service.lnk" } else { $null }

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }

function Stop-Service-Process {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -eq "mbom-copier-service.exe" -and $_.ExecutablePath -eq $Exe) -or
        (($_.Name -in @("python.exe", "pythonw.exe")) -and $_.CommandLine -like "*$Here*mbom_service.py*")
    }
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    if ($procs) { Start-Sleep -Seconds 1 }
}

function Remove-AutoStart {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    if ($StartupLink -and (Test-Path $StartupLink)) { Remove-Item $StartupLink -Force }
}

function Show-Pairing {
    if (-not (Test-Path "service.json")) { Say "Not installed yet: run .\install.ps1" Yellow; return }
    $cfg = Get-Content "service.json" -Raw | ConvertFrom-Json
    $address = "http://127.0.0.1:$($cfg.port)"
    $tenant = ""
    if (Test-Path "target.env") {
        $line = Select-String -Path "target.env" -Pattern "^TDX_TENANT=(.*)$" | Select-Object -First 1
        if ($line) { $tenant = $line.Matches[0].Groups[1].Value.Trim("'`"") }
    }
    Say ""
    Say "In the MBOM Copier widget, open Settings and enter:" Cyan
    Say "    Address        $address" White
    Say "    Pairing token  $($cfg.token)" White
    try { Set-Clipboard -Value $cfg.token; Say "    (the token is on your clipboard)" DarkGray } catch { }
    if ($tenant) { Say "Target tenant: $tenant" } else { Say "Then fill in the target tenant in Settings and press Test connection." }
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "$address/status" -Headers @{ "X-MBC-Token" = $cfg.token }
        Say "Service is running ($address)." Green
    } catch {
        Say "Service is not answering at $address yet - see service.log in this folder if it stays that way." Yellow
    }
}

if ($Info) { Show-Pairing; exit 0 }

if ($Uninstall) {
    Stop-Service-Process
    Remove-AutoStart
    Say "MBOM Copier service stopped; it no longer starts at sign-in. Your files in $Here are kept." Green
    exit 0
}

# ------------------------------------------------------------------ runtime
if (Test-Path $Exe) {
    Say "Using mbom-copier-service.exe"
    $Run = $Exe; $RunArgs = ""
    $CliExe = $Exe; $CliArgs = @()
} else {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Say "Python 3.10 or newer is needed (python.org, 'Install for me only', tick 'Add python.exe to PATH')," Yellow
        Say "or put mbom-copier-service.exe in this folder and run this script again." Yellow
        exit 1
    }
    $ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ([version]$ver -lt [version]"3.10") { Say "Python $ver found; 3.10 or newer is needed." Yellow; exit 1 }
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        Say "Creating the Python environment (.venv)..."
        & python -m venv .venv
    }
    Say "Installing packages..."
    & .\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Say "Retrying with the Windows certificate store (company network)..." Yellow
        & .\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check --use-feature=truststore -r requirements.txt
        if ($LASTEXITCODE -ne 0) { Say "Package install failed. Ask IT for the pip proxy setting, then run this script again." Red; exit 1 }
    }
    $Run = (Resolve-Path ".venv\Scripts\pythonw.exe").Path
    $RunArgs = "`"$Here\mbom_service.py`""
    $CliExe = (Resolve-Path ".venv\Scripts\python.exe").Path; $CliArgs = @("`"$Here\mbom_service.py`"")
}
New-Item -ItemType Directory -Force -Path "runs" | Out-Null

# ------------------------------------------------------------------ port + token
Stop-Service-Process                 # an older copy may hold the port
# writes service.json (free port, pairing token); waits, also for the window-less .exe
Start-Process -FilePath $CliExe -ArgumentList ($CliArgs + "--pick-port") -WorkingDirectory $Here -WindowStyle Hidden -Wait
if (-not (Test-Path "service.json")) { Say "Could not create service.json - see service.log." Red; exit 1 }

# ------------------------------------------------------------------ start at sign-in
if (-not $NoAutoStart) {
    Remove-AutoStart
    try {
        $me = "$env:USERDOMAIN\$env:USERNAME"
        $action = if ($RunArgs) { New-ScheduledTaskAction -Execute $Run -Argument $RunArgs -WorkingDirectory $Here }
                  else { New-ScheduledTaskAction -Execute $Run -WorkingDirectory $Here }
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $me
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
        $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
                               -Description "Local service for the MBOM Copier 3DDashboard widget (127.0.0.1 only)." -Force | Out-Null
        Say "Starts automatically when you sign in (Task Scheduler: '$TaskName')." Green
        Start-ScheduledTask -TaskName $TaskName
    } catch {
        # some company PCs don't allow scheduled tasks: use the Startup folder instead
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut($StartupLink)
        $lnk.TargetPath = $Run; $lnk.Arguments = $RunArgs; $lnk.WorkingDirectory = $Here; $lnk.WindowStyle = 7
        $lnk.Description = "MBOM Copier service"; $lnk.Save()
        Say "Starts automatically when you sign in (Startup folder shortcut)." Green
        if ($RunArgs) { Start-Process -FilePath $Run -ArgumentList $RunArgs -WorkingDirectory $Here -WindowStyle Hidden }
        else { Start-Process -FilePath $Run -WorkingDirectory $Here -WindowStyle Hidden }
    }
} else {
    if ($RunArgs) { Start-Process -FilePath $Run -ArgumentList $RunArgs -WorkingDirectory $Here -WindowStyle Hidden }
    else { Start-Process -FilePath $Run -WorkingDirectory $Here -WindowStyle Hidden }
}

Start-Sleep -Seconds 2
Show-Pairing
Say ""
Say "Widget for your dashboard (Run Your App):  https://joseph-aj-1.github.io/Experiments/mbom-copier/index.html" Cyan
