# Stops the worker + API processes started by dev-up.ps1 (tracked via PID
# files in .dev-pids/, since dev-up.ps1 uses Start-Process, not Start-Job)
# and brings down the docker services.
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/dev-down.ps1

$root = Split-Path -Parent $PSScriptRoot
$pidDir = Join-Path $root ".dev-pids"

foreach ($name in @("worker", "api")) {
    $pidFile = Join-Path $pidDir "$name.pid"
    if (Test-Path $pidFile) {
        $procId = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($procId) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped $name (PID $procId)."
        }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
}

Push-Location $root
docker compose down
Pop-Location
Write-Host "Stopped worker + api processes and docker compose services (pgdata volume preserved)."
