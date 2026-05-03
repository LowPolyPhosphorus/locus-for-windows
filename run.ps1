# run.ps1 -- Start Locus
# The daemon now runs inside the tray app process.
# Just run this one command.

Set-StrictMode -Version Latest
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

Write-Host "[Locus] Starting..." -ForegroundColor Cyan
python tray_app.py
