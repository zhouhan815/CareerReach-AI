param(
    [ValidateSet("fixture", "boss")]
    [string]$Backend = "fixture"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $Root "src"

python -m careerreach_ai `
    --backend $Backend `
    --input (Join-Path $Root "examples\mock_opportunity.json") `
    --output (Join-Path $Root "examples\mock_agent_output.json") `
    --pretty
