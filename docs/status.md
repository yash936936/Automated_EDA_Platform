# Status — Automated EDA, Cleaning & Visualization Platform

> Log every session here, newest at top. This is the first thing to read
> after `context.md` when resuming work.

## [2026-09-25] Phase 0 test failures debugged and fixed (Yash's local run)
**Current phase:** still Phase 0, now genuinely closer to closed — the two
test failures reported (`test_0_1_round_trip` 504 timeout,
`test_0_3_pause_and_resume` `KeyError: 'pending'`) were both config/workflow
bugs, not logic bugs, and are now fixed and verified. Full root-cause and
fix details in `docs/debug.md`'s 2026-09-25 entry — summary:
- `PGPORT` defaulted to 5432 everywhere in code while `docker-compose.yml`
  publishes Postgres on 5433; fixed defaults + `.env.example` to agree on
  5433, and made the API check Postgres connectivity loudly at boot.
- The Python worker simply wasn't running in the failing session — added
  `scripts/dev-up.{ps1,sh}` so bringing up the whole stack (docker services,
  `.env`, worker, API, in the right order) is one command instead of a
  multi-step manual sequence that's easy to get half right.
- Also fixed along the way: `README.md`'s `psql "$DATABASE_URL"` referenced
  an env var that's never defined anywhere in this repo (real bug, would
  have confused the next person too); `requirements.txt` never included
  `pytest`/`requests`, so the documented smoke-test command couldn't have
  run from a fresh install either (added `requirements-dev.txt`); the Redis
  "eviction policy is volatile-lru" warning is defended against now (app
  enforces `noeviction` on its own connection at startup) even though the
  likely cause is an environment-level second Redis instance, not this repo.
- **Verified for real, not just reviewed:** stood up Postgres 16 + Redis
  natively (no Docker available in the verification environment), matched
  the port topology to `docker-compose.yml` exactly, ran the actual worker
  and built API from a fresh `.env`, and ran
  `pytest tests/test_phase0_smoke.py -v` — 4 passed, 1 correctly skipped.
**Open items / honest gaps carried forward (unchanged by this session):**
- No OpenTelemetry tracing yet.
- `GeminiProvider` still untested against the real API (no key available).
- No CI — the now-passing test suite still only runs when someone
  remembers to run it locally.
- Root folder path still not set on Yash's actual disk / repo location.
- Auth for the API gateway, and performance targets, still unspecified.
**Next:** either close Phase 0's three remaining gaps above, or proceed to
Phase 1 (Ingestion & Dataset Discovery) with them tracked — your call.

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
