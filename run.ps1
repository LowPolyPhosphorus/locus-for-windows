# run.ps1 — Windows replacement for run.sh
# Starts the Locus daemon and tray UI for development
#
# Usage:
#   .\run.ps1

Set-StrictMode -Version Latest
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

# Launch daemon in background (no console window)
Write-Host "[Locus] Starting daemon..." -ForegroundColor Cyan
$daemon = Start-Process pythonw -ArgumentList "locusd_entry.py" -PassThru

# Small delay so the daemon can write its lock file before the UI checks it
Start-Sleep -Milliseconds 800

# Launch tray UI (foreground — this is what the user interacts with)
Write-Host "[Locus] Starting tray UI..." -ForegroundColor Cyan
python tray_app.py

# When tray UI exits, clean up the daemon
if ($daemon -and -not $daemon.HasExited) {
    Write-Host "[Locus] Stopping daemon (pid $($daemon.Id))..." -ForegroundColor Yellow
    Stop-Process -Id $daemon.Id -Force -ErrorAction SilentlyContinue
}
