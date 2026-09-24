# Automated EDA, Cleaning & Visualization Platform — code

Phase 0 skeleton. See `/docs` (or the project's doc set) for the full plan.

## Services
- `services/api` — Node/TypeScript API gateway + BullMQ producer.
- `services/agent-worker` — Python BullMQ consumer (stands in for Agent 2 in Phase 0).
- `db/migrations` — SQL schema (run in order: `000_extensions.sql`, `001_init.sql`).

## Run locally
```bash
docker compose up -d          # redis + postgres
psql "$DATABASE_URL" -f db/migrations/000_extensions.sql
psql "$DATABASE_URL" -f db/migrations/001_init.sql

cd services/agent-worker
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python -m agent_worker.worker &

cd ../api
npm install && npm run build && npm start
```

## Phase 0 smoke test
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
