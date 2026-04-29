# build_daemon.ps1 — Windows replacement for build_daemon.sh
# Builds locusd.exe and the tray app using PyInstaller
#
# Usage:
#   .\build_daemon.ps1
#
# Requirements:
#   pip install pyinstaller
#   All deps in requirements.txt installed

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

Write-Host "[Locus] Installing dependencies..." -ForegroundColor Cyan
pip install -r requirements.txt --quiet

Write-Host "[Locus] Building daemon (locusd.exe)..." -ForegroundColor Cyan
pyinstaller `
    --onefile `
    --noconsole `
    --name locusd `
    --add-data "config.example.json;." `
    locusd_entry.py

Write-Host "[Locus] Building tray UI (Locus.exe)..." -ForegroundColor Cyan
pyinstaller `
    --onefile `
    --noconsole `
    --name Locus `
    --icon assets\icon.ico `
    tray_app.py

Write-Host "[Locus] Build complete." -ForegroundColor Green
Write-Host "  Daemon : dist\locusd.exe"
Write-Host "  Tray UI: dist\Locus.exe"
