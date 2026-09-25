# Automated EDA, Cleaning & Visualization Platform — code

Phase 0 skeleton. See `/docs` (or the project's doc set) for the full plan.

## Services
- `services/api` — Node/TypeScript API gateway + BullMQ producer.
- `services/agent-worker` — Python BullMQ consumer (stands in for Agent 2 in Phase 0).
- `db/migrations` — SQL schema (run in order: `000_extensions.sql`, `001_init.sql`).

## Run locally

**Quickest path (recommended):** the fixes below are now automated —
```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts/dev-up.ps1
```
```bash
# macOS/Linux/WSL
bash scripts/dev-up.sh
```
This brings up Redis + Postgres, creates `.env` from `.env.example` if
missing, applies migrations (via docker-compose's init mount, on a fresh
volume), and starts the worker + API in the background in the right order.
Tear down with `scripts/dev-down.ps1` / re-run `docker compose down` + kill
the processes on bash. See `docs/debug.md`'s 2026-09-25 entry for exactly
what these scripts fix and why (a Postgres port mismatch and a
worker-never-started gap that both looked like app bugs but were config/
workflow gaps).

**Manual path**, if you want to see each step (or the scripts don't fit your
setup):
```bash
docker compose up -d          # redis + postgres (postgres on host port 5433)
cp .env.example .env          # PGPORT=5433 must match docker-compose.yml

# only needed if the postgres volume already existed before this docker-compose
# (a *fresh* volume auto-runs these via docker-entrypoint-initdb.d):
psql -h 127.0.0.1 -p 5433 -U postgres -d eda_platform -f db/migrations/000_extensions.sql
psql -h 127.0.0.1 -p 5433 -U postgres -d eda_platform -f db/migrations/001_init.sql

cd services/agent-worker
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt -r requirements-dev.txt
./venv/bin/python -m agent_worker.worker &   # <-- do not skip this; nothing
                                              #     consumes queued jobs without it

cd ../api
npm install && npm run build && npm start
```
`services/api/src/index.ts` now checks Postgres connectivity at boot and
prints exactly which host/port/database it resolved — if that log line
doesn't say `5433`/`eda_platform`, fix `.env` before going further.

## Phase 0 smoke test
```bash
cd services/agent-worker
./venv/bin/python -m pytest tests/test_phase0_smoke.py -v
```
Expect 4 passed, 1 skipped (`test_0_4_live_gemini_call` skips without a real
`GEMINI_API_KEY_*`). Requires the worker and API to already be running (see
above) — the suite talks to both over real network/Postgres, it doesn't
mock them.

Or, for a single manual check instead of the full suite:
```bash
curl -X POST http://127.0.0.1:4000/api/ping-agent
```
Expect `{"ok":true, "jobId": "...", "result": {...}}` — confirms frontend →
API gateway → Python agent worker → response, over a real Redis hop.

Approval-gate pause/resume:
```bash
curl -X POST http://127.0.0.1:4000/api/runs/<runId>/start
curl http://127.0.0.1:4000/api/runs/<runId>/pending-approval
curl -X POST http://127.0.0.1:4000/api/approvals/<pendingId>/resolve -d '{"decision":"approved"}' -H 'Content-Type: application/json'
```

## Known gaps (honest, not swept under the rug)
- OpenTelemetry tracing is **not** wired up yet — Phase 0.1's passing
  criteria asked for trace visibility; this skeleton only proves the
  round trip via job IDs and logs. Add real tracing before calling Phase 0 closed.
- `GeminiProvider.complete()` is untestable in this environment (no API key)
  — verified only at the interface-contract level (per-agent key lookup,
  swap-via-config, clear failure when a key is missing). Needs a real
  smoke test against the live Gemini API before Phase 1 depends on it.
- Service boundary is HTTP (Node) + shared Redis/BullMQ queue (Node↔Python).
  This resolves the "open" item from `docs/trd.md` — logged in `docs/decisions.md`.
- BullMQ (not Celery) was chosen specifically because it has a maintained
  Python client, letting one Redis queue serve both languages without a
  translation layer — logged as a decision.
