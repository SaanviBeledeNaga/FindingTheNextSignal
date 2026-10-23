$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m pharma_scope demo --tui
if ($LASTEXITCODE -ne 0) { Write-Host 'Setup instructions are in README.md' }
