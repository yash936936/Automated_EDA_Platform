# Debug Log — Automated EDA, Cleaning & Visualization Platform

> Append-only. Newest entries at top. Log every coding session here, even
> "no issues found" — this is the record of what was actually tested, not
> just what was built.

## Log

## [2026-09-24] Phase 0.1–0.4 — Foundation & Infra skeleton
**Tested:**
- 0.1: `POST /api/ping-agent` — Node API enqueues a BullMQ job, Python worker
  (separate process, same Redis) processes it and returns a result over a
  real network hop. Confirmed via job ID + response payload.
- 0.2: ran `000_extensions.sql` + `001_init.sql` against a fresh Postgres DB;
  inserted a valid dataset → playbook → cleaning_run → cleaning_action →
  dataset_version chain; separately attempted an invalid `dataset_versions`
  insert referencing a non-existent `cleaning_run_id`.
- 0.3: started a simulated playbook run; confirmed it wrote a
  `pending_approvals` row and the job exited (worker process idle, not
  blocked); confirmed `GET .../pending-approval` reflects it; posted an
  approval decision and confirmed the run correctly resumed to `completed`
  and the underlying `cleaning_actions` row updated to `approved`.
- 0.4: called `get_provider()` for two different agent keys via the `fake`
  provider (interface contract, since no real Gemini API key exists in this
  environment); switched `LLM_PROVIDER` to `gemini` via env var only (no
  call-site change) and confirmed it correctly raises when no per-agent key
  is configured; confirmed an unknown agent key is rejected.

**Found:**
- 0.3: `psycopg2.errors.DatatypeMismatch` — inserting into `pending_approvals.action_ids`
  (`uuid[]`) with a plain Python list produced a `text[]` literal, and
  Postgres refused the implicit cast.

**Fixed:**
- Cast the parameterized array explicitly with `%s::uuid[]` in the insert
  statement (`agent_worker/worker.py`, `handle_playbook_run`). Re-ran the
  0.3 test after the fix — passed.

**Still open (do not mark Phase 0 fully closed until these are addressed):**
- OpenTelemetry tracing is not wired up. Phase 0.1's original passing
  criteria specified trace visibility; this pass only verified the round
  trip via job IDs/logs, which is a materially weaker guarantee. Add real
  tracing before treating 0.1 as done to its original spec.
- `GeminiProvider` has never made a real API call — only its interface
  contract (per-agent key lookup, config-only provider swap, clean failure
  on missing key) was tested. Needs a live smoke test once a Gemini API key
  exists.
- No automated test suite — everything above was verified by hand, once,
  in this session. Before Phase 1 builds on this skeleton, these should
  become repeatable tests (e.g. a small integration test script), not
  one-off manual curl commands.

**Entry format to use going forward:**
```
## [YYYY-MM-DD] Phase X.Y — <short description>
**Tested:** what was run/exercised
**Found:** bugs/issues discovered (or "none")
**Fixed:** what changed, and why
**Still open:** anything deferred, with a reason
```

---
**Next:** Return to [`context.md`](../context.md).
