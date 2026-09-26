# Status — Automated EDA, Cleaning & Visualization Platform

> Log every session here, newest at top. This is the first thing to read
> after `context.md` when resuming work.

## [2026-09-25] Phase 0 confirmed fully green on Yash's actual machine
**Current phase:** Phase 0 is done against its `docs/phases.md` criteria,
with three honest gaps still open (below) — this was a multi-round
debugging session against Yash's real Windows setup, not just a code
review. Full root-cause/fix/verification trail for every issue is in
`docs/debug.md`'s five 2026-09-25 entries; summary of what was actually
wrong, in the order hit:
1. `PGPORT` defaulted to 5432 in code while `docker-compose.yml` publishes
   Postgres on 5433 (real repo bug — fixed).
2. `scripts/dev-up.ps1` used `Start-Job`, which doesn't reliably inherit
   PATH on Windows and never verified the API actually started listening
   (real script bug — rewritten around `Start-Process` + an explicit
   port-liveness check, with log files instead of a job buffer).
3. `requirements.txt` never included `pytest`/`requests`, so the documented
   test command couldn't run from a fresh install (real repo bug — added
   `requirements-dev.txt`).
4. `.env`'s `PGPASSWORD` didn't match what the already-initialized Docker
   volume was actually created with (Yash's hand-edited `.env`, not a repo
   bug — but the API now prints resolved host/port/`server_version` at boot
   specifically so this class of mismatch is obvious immediately).
5. A worker process left running from before `.env` was switched to Redis
   Cloud kept talking to the old Redis while a freshly-restarted API used
   the new one — classic stale-process-vs-new-config, not a repo bug, but
   both the worker and API now print their resolved Redis target at startup
   specifically to catch this.
6. The Docker containers (`postgres`, `redis`) had simply stopped running
   at some point in the session — not a bug, just needed `docker compose up -d`.
**Verified:** final run on Yash's actual machine —
`4 passed, 1 skipped, 1 warning in 9.88s`. `test_0_4_live_gemini_call`
still correctly skips (`GEMINI_API_KEY_EDA_CLEAN` not populated, despite
other keys being present in `.env` — worth Yash double-checking if he
wants that path exercised for real).
**Open items / honest gaps carried forward (unchanged by this session):**
- No OpenTelemetry tracing yet.
- `GeminiProvider` still untested against the real live API.
- No CI — the now-passing test suite still only runs when someone
  remembers to run it locally.
- Root folder path still not set on Yash's actual disk / repo location.
- Auth for the API gateway, and performance targets, still unspecified.
**Next:** either close Phase 0's remaining gaps above, or proceed to
Phase 1 (Ingestion & Dataset Discovery) with them tracked — your call. If
picking Phase 1 up next session, start with `docker ps` before assuming any
new failure is a code bug — half of this session's issues were "something
wasn't running," not logic errors.

## [2026-09-24] Phase 0 built and manually tested
**Current phase:** Phase 0 sub-phases 0.1–0.4 built and passing manual tests
(see `docs/debug.md`). Phase 0 is **not** marked fully closed — see caveats below.
**What changed:**
- Repo scaffolded: `services/api` (Node/TS API gateway + BullMQ producer),
  `services/agent-worker` (Python BullMQ consumer), `db/migrations` (Postgres
  schema), `docker-compose.yml`, `.env.example`.
- Resolved two previously-open items and logged them: queue tech is BullMQ
  (D-012, chosen because its maintained Python client lets one Redis queue
  serve both languages of the mixed stack); Python↔Node boundary is HTTP for
  request/response + shared BullMQ/Redis for job dispatch (D-011).
- Verified end-to-end: API→queue→worker round trip (0.1); Postgres schema +
  FK enforcement (0.2); approval pause/resume with zero worker held during
  `awaiting_approval` (0.3); provider-agnostic LLM interface contract via a
  fake provider, since no real Gemini key exists in this environment (0.4).
- Found and fixed one real bug: a `uuid[]` cast mismatch in the
  `pending_approvals` insert (psycopg2 was sending `text[]`).
**Open items / honest gaps carried forward:**
- No OpenTelemetry tracing yet — 0.1's original passing criteria wanted trace
  visibility; only job-ID/log-based verification exists.
- `GeminiProvider` untested against the real API (no key in this environment).
- No automated test suite — all Phase 0 testing was manual, one-off. Should
  become repeatable scripts/tests before Phase 1 builds on this skeleton.
- Root folder path still not set on the user's actual disk — this build lives
  at `/home/claude/automated-eda-platform` in the sandbox and is delivered as
  a zip; update `context.md`'s root-folder line once it has a real home.
- Auth for the API gateway, and performance targets, still unspecified.
**Next:** either close Phase 0's remaining gaps (tracing, automated tests,
real Gemini smoke test) or proceed to Phase 1 (Ingestion & Dataset Discovery)
with those gaps tracked — user's call.

## [2026-09-24] Documentation scaffolded
**Current phase:** Not started — Phase 0.1 (Repo & service boundary) is next.
**What changed:** Full documentation set created (`context.md` +
`docs/prd.md`, `trd.md`, `architecture.md`, `phases.md`, `decisions.md`,
`debug.md`, `code_logic.md`, `appflow.md`, `workflow.md`, `readme.md`,
`status.md`), based on the existing architecture/design plan. Stack decision
logged (Python for agents/data, Node/TS for API+frontend — D-010). No code exists yet.
**Open items carried forward:**
- Root folder path not set (placeholder in `context.md`).
- Exact Python↔Node service boundary (REST/gRPC/queue-only) — Phase 0.1.
- BullMQ vs. Celery choice — Phase 0.3.
- Auth approach for API gateway — not yet specified.
- Performance targets (dataset size / latency ceilings) — not yet specified.
- Monorepo vs. separate repos — `docs/workflow.md`.
**Next:** Begin Phase 0.1 — scaffold the Node/TS and Python service
skeletons and decide the call boundary between them.

---
**Next:** Return to [`context.md`](../context.md).
