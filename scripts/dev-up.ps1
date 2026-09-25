# Brings up the whole Phase 0 stack and leaves the worker + API running in
# the background, so you can't forget a step (this is exactly what caused
# the 504 timeout on test_0_1_round_trip: redis + postgres + api were up,
# but nothing was consuming the queue).
#
# Uses Start-Process (not Start-Job) for the worker/API: Start-Job spawns a
# child PowerShell process that does not reliably inherit the same `node`/
# `python` PATH resolution as your interactive shell (this bit a real run --
# the job "started" but the process never actually bound port 4000, and the
# script had no check to catch that). Start-Process here uses the *exact*
# resolved exe path via Get-Command, redirects output to log files instead
# of the job buffer, and the script verifies port 4000 is actually accepting
# connections before declaring success -- if it isn't, it prints the log
# tail immediately instead of a false "should be up".
#
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/dev-up.ps1
#
# Stop everything with scripts/dev-down.ps1.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pidDir = Join-Path $root ".dev-pids"
New-Item -ItemType Directory -Force -Path $pidDir | Out-Null

Write-Host "[1/6] docker compose up -d (redis + postgres)..."
Push-Location $root
docker compose up -d
Pop-Location

Write-Host "[2/6] Waiting for Postgres to accept connections on 5433..."
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    docker exec $(docker compose -f "$root/docker-compose.yml" ps -q postgres) pg_isready -U postgres 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Write-Warning "Postgres did not report ready after 30s -- continuing anyway, but the next steps may fail."
}

Write-Host "[3/6] Ensuring .env exists (copied from .env.example if missing)..."
if (-not (Test-Path "$root\.env")) {
    Copy-Item "$root\.env.example" "$root\.env"
    Write-Host "    Created .env from .env.example (PGPORT=5433, LLM_PROVIDER=fake)."
}

Write-Host "[4/6] Stopping any leftover worker/API processes from a previous run..."
foreach ($name in @("worker", "api")) {
    $pidFile = Join-Path $pidDir "$name.pid"
    if (Test-Path $pidFile) {
        $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
        if ($oldPid) {
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $pidFile -ErrorAction SilentlyContinue
    }
}

Write-Host "[5/6] Setting up and starting the Python agent worker..."
$workerDir = Join-Path $root "services\agent-worker"
if (-not (Test-Path "$workerDir\venv")) {
    Write-Host "    No venv found -- creating one (first run only)..."
    python -m venv "$workerDir\venv"
}
# Always (re)install, not just on first venv creation -- cheap/no-op when
# already satisfied, but guarantees requirements-dev.txt (pytest, requests)
# is present even if the venv was created by an older version of this script
# or a manual `pip install -r requirements.txt` only.
& "$workerDir\venv\Scripts\pip.exe" install -q -r "$workerDir\requirements.txt" -r "$workerDir\requirements-dev.txt"

$workerLog = Join-Path $root "worker.log"
$workerExe = (Resolve-Path "$workerDir\venv\Scripts\python.exe").Path
$workerProc = Start-Process -FilePath $workerExe -ArgumentList "-m", "agent_worker.worker" `
    -WorkingDirectory $workerDir -RedirectStandardOutput $workerLog -RedirectStandardError "$workerLog.err" `
    -WindowStyle Hidden -PassThru
$workerProc.Id | Out-File (Join-Path $pidDir "worker.pid")
Write-Host "    Worker started (PID $($workerProc.Id)). Logs: $workerLog"

Write-Host "[6/6] Building and starting the API gateway..."
$apiDir = Join-Path $root "services\api"
Push-Location $apiDir
if (-not (Test-Path "$apiDir\node_modules")) { npm install }
npm run build
Pop-Location

$apiLog = Join-Path $root "api.log"
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    Write-Error "node is not on PATH in this PowerShell session -- install Node.js or open a new terminal where 'node --version' works, then re-run this script."
    exit 1
}
$apiProc = Start-Process -FilePath $nodeCmd.Source -ArgumentList "dist\index.js" `
    -WorkingDirectory $apiDir -RedirectStandardOutput $apiLog -RedirectStandardError "$apiLog.err" `
    -WindowStyle Hidden -PassThru
$apiProc.Id | Out-File (Join-Path $pidDir "api.pid")
Write-Host "    API process started (PID $($apiProc.Id)). Logs: $apiLog"

Write-Host "`nWaiting for the API to actually accept connections on :4000..."
$apiUp = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if ($apiProc.HasExited) { break }
    $test = Test-NetConnection -ComputerName "127.0.0.1" -Port 4000 -WarningAction SilentlyContinue -InformationLevel Quiet
    if ($test) { $apiUp = $true; break }
}

if (-not $apiUp -or $apiProc.HasExited) {
    Write-Host ""
    Write-Error "The API did not come up on :4000. It likely crashed on startup. Last log output:"
    if (Test-Path $apiLog) { Get-Content $apiLog -Tail 20 }
    if (Test-Path "$apiLog.err") { Get-Content "$apiLog.err" -Tail 20 }
    Write-Host "`nCommon causes: node not resolvable, a stale process already bound to :4000 (check with 'netstat -ano | findstr :4000'), or an unhandled startup exception (a Postgres error is logged but shouldn't crash the process -- anything else in api.log.err is the real cause)."
    exit 1
}

Write-Host "`nStack is up and verified: redis + postgres (docker), worker (PID $($workerProc.Id)), api (PID $($apiProc.Id), listening on :4000)."
Write-Host "Smoke test: cd services\agent-worker && .\venv\Scripts\python.exe -m pytest tests\test_phase0_smoke.py -v"
