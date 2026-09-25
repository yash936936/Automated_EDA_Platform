#!/usr/bin/env bash
# Bash equivalent of dev-up.ps1 -- see that file's header for what/why.
# Run from the repo root: bash scripts/dev-up.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/5] docker compose up -d (redis + postgres)..."
(cd "$ROOT" && docker compose up -d)

echo "[2/5] Waiting for Postgres to accept connections on 5433..."
for i in $(seq 1 30); do
  if docker exec "$(cd "$ROOT" && docker compose ps -q postgres)" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[3/5] Ensuring .env exists (copied from .env.example if missing)..."
if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "    Created .env from .env.example (PGPORT=5433, LLM_PROVIDER=fake)."
fi

WORKER_DIR="$ROOT/services/agent-worker"
echo "[4/5] Starting Python agent worker in the background..."
if [ ! -d "$WORKER_DIR/venv" ]; then
  echo "    No venv found -- creating one (first run only)..."
  python3 -m venv "$WORKER_DIR/venv"
fi
# Always (re)install -- cheap/no-op when already satisfied, but guarantees
# requirements-dev.txt (pytest, requests) is present even on a venv created
# by an older version of this script.
"$WORKER_DIR/venv/bin/pip" install -q -r "$WORKER_DIR/requirements.txt" -r "$WORKER_DIR/requirements-dev.txt"
(cd "$WORKER_DIR" && nohup "$WORKER_DIR/venv/bin/python" -m agent_worker.worker > "$ROOT/worker.log" 2>&1 &)
echo "    Worker started in background. Logs: tail -f $ROOT/worker.log"

API_DIR="$ROOT/services/api"
echo "[5/5] Building and starting the API gateway in the background..."
(cd "$API_DIR" && [ -d node_modules ] || npm install)
(cd "$API_DIR" && npm run build)
(cd "$API_DIR" && nohup node dist/index.js > "$ROOT/api.log" 2>&1 &)
echo "    API started in background. Logs: tail -f $ROOT/api.log"

echo ""
echo "Waiting for the API to actually accept connections on :4000..."
up=false
for i in $(seq 1 20); do
  sleep 0.5
  if (exec 3<>/dev/tcp/127.0.0.1/4000) 2>/dev/null; then
    exec 3<&- 3>&-
    up=true
    break
  fi
done

if [ "$up" != "true" ]; then
  echo ""
  echo "ERROR: the API did not come up on :4000. It likely crashed on startup. Last log output:" >&2
  tail -n 20 "$ROOT/api.log" >&2 2>/dev/null || true
  echo "" >&2
  echo "Common causes: a stale process already bound to :4000 (check with 'lsof -i :4000'), or an unhandled startup exception (a Postgres error is logged but shouldn't crash the process -- anything else here is the real cause)." >&2
  exit 1
fi

echo ""
echo "Stack is up and verified: redis + postgres (docker), worker, api (listening on :4000)."
echo "Smoke test: cd services/agent-worker && ./venv/bin/python -m pytest tests/test_phase0_smoke.py -v"
