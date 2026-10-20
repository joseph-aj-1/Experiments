# Starts the Float on Release automatic agent.
# The EIF listener (..\eif-listener\run.ps1) must be running in another window:
# it receives the events, this agent acts on them.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -r requirements.txt
}
.\.venv\Scripts\python agent.py
