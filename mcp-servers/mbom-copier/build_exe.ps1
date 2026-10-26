<#
  Builds mbom-copier-service.exe: the MBOM Copier service as one Windows program, so colleagues
  don't need Python. Run once on a Windows PC that has Python 3.10+ (your own is fine):

    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

  Result: mbom-copier-service.exe in this folder (about 15-40 MB). It has no console window;
  it writes its messages to service.log next to itself. Ship it together with install.ps1
  (see "Share with colleagues" in README.md).
#>
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "Python 3.10+ is needed to build the .exe." -ForegroundColor Yellow; exit 1 }

# a separate build environment keeps PyInstaller out of the service's .venv
if (-not (Test-Path ".buildenv\Scripts\python.exe")) { & python -m venv .buildenv }
& .\.buildenv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) {
    & .\.buildenv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check --use-feature=truststore -r requirements.txt pyinstaller
}

& .\.buildenv\Scripts\python.exe -m PyInstaller --onefile --noconsole --clean --noconfirm `
    --name mbom-copier-service --collect-submodules app `
    --distpath . --workpath .build --specpath .build mbom_service.py
if ($LASTEXITCODE -ne 0) { Write-Host "Build failed." -ForegroundColor Red; exit 1 }

Remove-Item -Recurse -Force .build -ErrorAction SilentlyContinue
$size = [math]::Round((Get-Item .\mbom-copier-service.exe).Length / 1MB, 1)
Write-Host "Built mbom-copier-service.exe ($size MB)." -ForegroundColor Green
Write-Host "Some company PCs block unsigned programs; if a colleague's PC does, they can use the Python route instead (install.ps1 sets it up)."
