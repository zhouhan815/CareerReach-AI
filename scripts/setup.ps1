$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) {
  py -3 -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".\third_party\boss-agent-cli[rag,communication]"
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

New-Item -ItemType Directory -Force -Path ".data" | Out-Null

Write-Host "CareerReach AI is ready."
Write-Host "Activate: .\.venv\Scripts\Activate.ps1"
Write-Host "Demo: careerreach-ai --backend fixture --input examples\mock_opportunity.json --pretty"
