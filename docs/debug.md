# Debug Log — Automated EDA, Cleaning & Visualization Platform

> Append-only. Newest entries at top. Log every coding session here, even
> "no issues found" — this is the record of what was actually tested, not
> just what was built.

## [2026-09-26] OpenTelemetry tracing wired up for real (closes Phase 0.1's original gap)
**Work:** `docs/status.md`'s 2026-09-25 entry flagged "no OpenTelemetry
tracing yet" as the first of three remaining Phase 0 gaps. Closed it:
- `services/api/src/tracing.ts` (new): sets up a `NodeTracerProvider` with an
  OTLP/HTTP exporter, `AsyncHooksContextManager` for context propagation
  across `await`s, and a `W3CTraceContextPropagator`. Manual spans, not
  auto-instrumentation -- decided against auto-instrumentation because this
  service runs as pure ESM (`"type": "module"`), and OTel's Node
  auto-instrumentation patches modules via a CommonJS require hook that
  needs `--experimental-loader` wired into how the process is launched; that
  adds real complexity for a Phase-0-scale codebase with four route
  handlers. Manual `tracer.startActiveSpan(...)` around each handler in
  `index.ts` gets the same visibility with no loader changes.
- `services/api/src/queue.ts`: new `addTracedJob()` helper that injects the
  active span's W3C `traceparent` into the BullMQ job payload
  (`_traceCarrier`) before enqueueing. Trace context does not cross the
  Redis boundary on its own -- the Node API and Python worker are separate
  processes with no shared memory, so without this, the worker's span would
  start a disconnected trace instead of continuing the one the API started.
- `services/agent-worker/agent_worker/tracing.py` (new): same shape on the
  Python side -- `TracerProvider` + `OTLPSpanExporter`, plus
  `extract_context()` which pulls `_traceCarrier` back out of the job data
  and returns it as a parent context for the worker's span.
- `services/agent-worker/agent_worker/worker.py`'s `process()` now wraps
  every job in `tracer.start_as_current_span(..., context=parent_ctx, ...)`,
  recording exceptions and setting `ERROR` status on failure so a failed job
  is visible as an error span, not just a log line.
- `docker-compose.yml`: added a `jaeger` service (`jaegertracing/all-in-one`)
  with `COLLECTOR_OTLP_ENABLED=true`, UI on host port **16687** (not
  Jaeger's usual 16686) specifically because Yash already has a separate
  Jaeger container running for something else on this machine (visible in
  an earlier Docker Desktop screenshot this session) -- reusing 16686 would
  have risked exactly the "something else is listening on the port I
  assumed was free" class of bug this whole debugging session kept hitting.
- `.env.example`: added `OTEL_EXPORTER_OTLP_ENDPOINT` (defaults to the
  `jaeger` service) and `OTEL_DEBUG` (prints every span to stdout too, for
  sanity-checking without opening the Jaeger UI).
**Found along the way:** `worker.py` printed its startup/status lines with
default Python stdout buffering, which is block-buffered (not line-buffered)
whenever stdout isn't a terminal -- i.e. every single time this repo's own
scripts (`dev-up.sh`/`dev-up.ps1`) or this debugging session redirected it
to a log file. `worker.log` could sit empty for a long stretch after actual
startup, which would have looked like "the worker didn't start" during any
future debugging session for a completely unrelated reason. Fixed with
`sys.stdout.reconfigure(line_buffering=True)` at worker startup.
**Verified for real, not just reviewed:** could not use Docker in the
verification environment (same limitation as every prior session), so
downloaded the actual `jaeger-all-in-one` v1.60.0 Linux binary from its
GitHub release and ran it directly with `COLLECTOR_OTLP_ENABLED=true`. Built
the real API, ran the real worker, fired a real `POST /api/ping-agent`, then
queried Jaeger's own HTTP query API (`/api/traces?service=eda-api`) and
confirmed **one trace ID containing two linked spans**: `POST
/api/ping-agent` (service `eda-api`, root span) with `worker.process echo`
(service `eda-clean-worker`) as its correctly-linked child -- i.e. the exact
thing Phase 0.1's original passing criterion asked for ("visible in
OpenTelemetry traces"), across a real process/language boundary, not
mocked. Re-ran the full `pytest tests/test_phase0_smoke.py -v` afterward:
still 4 passed, 1 skipped, confirming tracing didn't regress anything.
**Still open:** `GeminiProvider` untested against the real live API (Yash's
next step), and no CI (explicitly the step after that, per Yash's stated
plan). Tracing itself does not yet cover Postgres queries or BullMQ's
internal operations as spans -- only the API's own route handlers and the
worker's job processing are instrumented. That's enough to satisfy Phase
0.1's and 8.3's stated criteria (the round trip and every agent
call/approval-gate transition are traceable) but is worth knowing as a
boundary, not a gap, if deeper DB-level tracing is wanted later.


**Tested:** after the Postgres-password fix, the Redis-mismatch fix (stale
worker vs. Redis Cloud), and bringing the stopped Docker containers back up
(`docker compose up -d` -- they'd simply stopped at some point, not a config
bug), ran the full suite one more time.
**Result:** `4 passed, 1 skipped, 1 warning in 9.88s` -- `test_0_1_round_trip`,
`test_0_2_schema_and_fk`, `test_0_3_pause_and_resume`, and
`test_0_4_llm_interface_contract` all pass for real, against a real running
stack (Postgres 16 in Docker, Redis Cloud, the actual worker and API
processes). `test_0_4_live_gemini_call` still (correctly) skips --
`GEMINI_API_KEY_EDA_CLEAN` specifically isn't set/populated despite other
keys being visible in `.env`, worth Yash double-checking if he intends to
exercise the real Gemini path.
**Summary of everything actually wrong, across this whole debugging
session, for future reference:** (1) `PGPORT` defaulted to 5432 in code
while docker-compose publishes 5433 -- fixed; (2) `dev-up.ps1` used
`Start-Job`, which doesn't reliably inherit PATH on Windows and never
verified anything actually started -- rewritten around `Start-Process` with
an explicit port-liveness check; (3) `requirements.txt` never included
`pytest`/`requests` -- added `requirements-dev.txt`; (4) `.env`'s
`PGPASSWORD` didn't match what the already-initialized Docker volume was
actually created with -- a hand-edit mismatch, not a repo bug; (5) a stale
worker process kept talking to the pre-switch Redis after `.env` was
updated to Redis Cloud, while a freshly-restarted API used the new one --
added startup logging on both sides specifically to catch this class of
bug going forward; (6) the Docker containers had simply stopped running.
Only (1)-(3) were real repository bugs; (4)-(6) were environment/session
state, but (4) and (5) were made much faster to diagnose by the defensive
logging added while fixing (1).
**Still open (unchanged, honest gaps, not addressed this session):** no
OpenTelemetry tracing (0.1's original passing criterion), `GeminiProvider`
still never exercised against the real live API, no automated CI --
`pytest` only runs when someone remembers to run it locally.
**Next:** Phase 0 can now be considered genuinely done against its
`docs/phases.md` criteria *except* for the three items above -- either close
those out, or proceed to Phase 1 (Ingestion & Dataset Discovery) with them
explicitly tracked. Recommend restarting Postgres/Redis health checks with
`docker ps` at the start of any future session before assuming a fresh
failure is a new bug -- three of the six issues this session were
"something wasn't running," not code.


**Tested:** Yash fixed `PGPASSWORD` (confirmed: `Postgres OK
(127.0.0.1:5433/eda_platform)` with no warning). Re-ran the full suite and
got the exact same two failures as the very first report -- `test_0_1`
504 timeout, `test_0_3` no `pending_approvals` row -- despite Postgres now
being fine. Both point at the queue itself: jobs enqueue but nothing
consumes them.
**Found:** `.env`'s Redis now points at a Redis Cloud instance
(`redis-16314...redislabs.com`), switched from local Docker Redis at some
point in this troubleshooting session. `services/agent-worker/agent_worker/
worker.py` correctly reads `REDIS_HOST`/`PORT`/`PASSWORD` from `.env` via
`python-dotenv` -- not a code bug -- but `load_dotenv()` only runs once, at
process startup. A worker process left running from *before* the Redis
Cloud switch keeps talking to the old (local) Redis forever, while a
freshly-restarted API now enqueues to Redis Cloud. Producer and consumer end
up on two different queues: jobs "enqueue" successfully from the API's
point of view, nothing ever consumes them, and the symptom is
indistinguishable from "the worker isn't running at all" -- this is the
third time that exact symptom has appeared for a different underlying
reason (previously: worker literally not started; now: worker started
against stale config).
**Fixed:** both `services/agent-worker/agent_worker/worker.py` and
`services/api/src/queue.ts` now unconditionally print which Redis
host:port they resolved at startup (password redacted), so a mismatch
between the two is visible at a glance in their logs instead of only
surfacing as a downstream timeout with no obvious cause.
**Verified:** reproduced the exact failure on purpose -- started the worker
against one local Redis (port 6379) and the API against a second, separate
local Redis (port 6380) -- and got the identical `504`/timeout error Yash
saw. Confirmed the new log lines immediately show the mismatch
(`redis=...6379` vs `API Redis target: ...6380`). Then re-matched both to
the same Redis and re-ran the full suite clean: 4 passed, 1 skipped, no
regression.
**Still open:** unchanged from prior entries. General note worth stating
explicitly now that this has bitten three times in different forms: **any
time `.env` changes, both the worker and the API process must be fully
restarted** -- there is no live-reload of environment variables in either,
by design of `python-dotenv`/Node's process.env model.


**Tested:** Yash ran `node dist\index.js` directly (bypassing the scripts
entirely, correctly isolating the API), got `API gateway listening on :4000`
followed immediately by `password authentication failed for user "postgres"`
on `127.0.0.1:5433/eda_platform` -- this time with the *correct* port
already in place, ruling out the previous PGPORT-default bug.
**Found:** a pgAdmin screenshot from the same machine shows a native
PostgreSQL **17** server with three databases including one literally named
`eda_platform` (alongside `postgres` and an unrelated `sysdesign` db).
`docker-compose.yml` runs `postgres:16`. If that native PG17 instance is
also bound to port 5433 on this machine, `PGPORT=5433` walks straight into
it instead of the Docker container, with a different password -- same class
of bug as before (something else answering on the expected port) but a
different, machine-specific root cause this time, not fixable by picking a
different "safe" port in the repo since there's no way to know in advance
which port is actually free on a given developer's machine.
**Fixed (defensive, not yet root-cause-confirmed):** `services/api/src/
index.ts`'s startup check now runs `SHOW server_version` on success and
warns loudly if it doesn't start with `16` (the version docker-compose
runs), and on an auth failure specifically, prints a hint that this is
often a different-Postgres-on-the-same-port problem rather than an actually
wrong password, pointing at `docker ps` / `netstat -ano | findstr :<port>`
to identify the real owner of the port before assuming credentials are
wrong. **Root cause on Yash's machine is not yet confirmed** -- waiting on
`docker ps` / `netstat -ano | findstr :5433` / `.env` contents from his
actual machine before deciding whether the fix is "start the missing
container", "stop/reconfigure the native PG17", or "move docker-compose's
Postgres to a different host port entirely".
**Verified:** ran both the success path (real Postgres 16, confirms the new
version line reads `server_version=16.15 ...` with no warning) and the
auth-failure path (deliberately wrong password against the same real
Postgres 16, confirms the new hint text renders correctly) for real in this
session's environment. Have not yet reproduced the actual native-PG17
collision itself, since that's specific to Yash's machine.
**Still open:** unchanged from prior entries, plus: confirm actual cause of
the PG17/5433 collision once diagnostic output comes back.

## [2026-09-25] dev-up.ps1: Start-Job silently failed to start a listening API — fixed
**Tested:** ran `scripts/dev-up.ps1` on Yash's machine (real run) — script
reported the API "started as background job" and printed success, but the
immediately-following `pytest` run failed both HTTP-dependent tests with
`[WinError 10061] ... actively refused it` on port 4000, i.e. nothing was
ever listening.
**Found:** the script used `Start-Job` for both the worker and the API.
`Start-Job` spawns a **child PowerShell process**, and on Windows that child
does not reliably inherit the same `node`/`python` PATH resolution as the
interactive shell it was launched from (common with nvm-style installs, or
any PATH set via profile scripts rather than machine/user env vars). The
job object itself still reports as "started" even if the process it runs
immediately fails to resolve `node` and exits — the script had **no check**
that anything was actually listening on :4000 before declaring success, so
this failure mode was invisible until the test suite hit it downstream.
**Fixed:** rewrote `dev-up.ps1`/`dev-down.ps1` to use `Start-Process` instead
of `Start-Job`:
- Resolves `node`'s exact path via `Get-Command` before launching (fails
  fast with a clear message if `node` isn't on PATH at all, rather than a
  silent job failure).
- Redirects stdout/stderr to `worker.log`/`api.log` (+ `.err` variants)
  instead of the job output buffer, matching the bash script's approach.
- Tracks PIDs in `.dev-pids/` instead of named jobs, so `dev-down.ps1` can
  reliably stop the right processes and re-running `dev-up.ps1` cleans up
  any leftover process from a previous run first (named `Start-Job`s could
  also silently accumulate duplicates across runs, since PowerShell doesn't
  enforce unique job names).
- **Actually waits and checks** that the API is accepting connections on
  :4000 before declaring success; if it isn't (or the process already
  exited), prints the last 20 lines of both log files and exits non-zero
  instead of a false "should be up".
- Added the equivalent check to `dev-up.sh` for consistency (bash's `nohup`
  doesn't have the PATH-isolation bug, but the same "never verified, just
  claimed success" flaw existed there too).
**Verified:** could not run PowerShell directly in the verification
environment (no `pwsh` package available without a Microsoft repo this
sandbox's network policy doesn't allow), so verified by (a) careful manual
review for PowerShell syntax correctness (line-continuation backticks,
`Start-Process`/`Test-NetConnection` argument shapes), and (b) porting the
identical verification logic to `dev-up.sh` and running it for real: killed
the API mid-script, confirmed the new check catches it immediately rather
than hanging or reporting false success; with a real listener, confirmed
it detects "up" within ~1 second. Re-ran the full
`pytest tests/test_phase0_smoke.py -v` afterward -- still 4 passed, 1
skipped. The PowerShell-specific mechanics (`Start-Process` vs `Start-Job`,
`Get-Command`/`Test-NetConnection` behavior) are standard, well-documented
cmdlet behavior, but flagging that this specific script has not been
executed on Windows by Claude -- Yash's next run is the first real test of
the `.ps1` file itself, only the underlying logic has been verified.
**Still open:** unchanged from prior entries (tracing, live Gemini test, CI).


**Tested:** ran `scripts/dev-up.ps1` on Yash's machine (real run, not this
sandbox) — stack came up fine, but the immediately-following `pytest` command
failed with `No module named pytest`.
**Found:** `dev-up.ps1`/`dev-up.sh` only ran `pip install -r requirements.txt`
inside the "venv doesn't exist yet" branch, and only installed
`requirements.txt` — never `requirements-dev.txt` (added in the prior
session specifically to hold `pytest`/`requests`). So the one script whose
whole point is "get you to a runnable test suite" didn't actually install
the thing that runs the tests.
**Fixed:** both scripts now install `requirements.txt` **and**
`requirements-dev.txt` every run (not gated behind the venv-doesn't-exist
check), so it also self-heals a venv created by an older copy of the script
or a manual `pip install -r requirements.txt` that predates the dev-file
split.
**Still open:** unchanged from the prior entry (tracing, live Gemini test, CI).


**Tested:** reproduced the failure by standing up the exact stack (Postgres +
Redis, natively, port-matched to `docker-compose.yml`'s 5433 mapping) in a
clean environment and running `pytest tests/test_phase0_smoke.py -v`.
**Found:**
- `test_0_1_round_trip` timed out (504) and `test_0_3_pause_and_resume` threw
  `KeyError: 'pending'` on Yash's run. Root cause for 0.3: `docker-compose.yml`
  publishes Postgres on host port **5433** (`"5433:5432"`), deliberately
  non-default to avoid colliding with a native Postgres install — but
  `services/api/src/index.ts`, `services/agent-worker/agent_worker/db.py`,
  and `tests/test_phase0_smoke.py` all defaulted `PGPORT` to **5432** when
  unset, and `.env.example` never set `PGPORT` at all. With no complete
  `.env`, everything fell back to 5432 and hit Yash's native Postgres
  instead of the Docker one → `password authentication failed` → the API's
  error-path response had no `pending` key → `KeyError`. Root cause for 0.1:
  the Python worker (`python -m agent_worker.worker`) was never started in
  that shell — only Redis, Postgres and the API were — so the enqueued
  `echo` job had nothing to consume it and the 15s `waitUntilFinished` timed
  out. Separately, the "Eviction policy is volatile-lru" warning strongly
  suggests a *second* Redis (native/WSL) is also listening on 6379 on that
  machine, since `docker-compose.yml`'s `--maxmemory-policy noeviction`
  command should otherwise guarantee this.
**Fixed:**
- `PGPORT` default corrected to `5433` in `index.ts`, `db.py`, and the test
  file, and `.env.example` now sets `PGPORT=5433` explicitly with a comment
  explaining why it isn't 5432, so a fresh `.env` is correct by default.
- `docker-compose.yml`'s Postgres service now mounts `db/migrations` into
  `/docker-entrypoint-initdb.d`, so both migration files auto-apply on a
  fresh volume (manual `psql -f` instructions kept as the documented
  fallback for pre-existing volumes).
- `services/api/src/index.ts` now runs `SELECT 1` at boot and logs the
  resolved host/port/database, so a bad `PGPORT`/`PGPASSWORD` fails loudly
  at startup instead of surfacing later as a confusing `KeyError` in a
  client. The `/pending-approval` error path now always includes a `pending`
  key (`null` on error) so the response shape never breaks callers.
- `services/api/src/queue.ts` now issues `CONFIG SET maxmemory-policy
  noeviction` on its own Redis connection at startup (self-healing even if
  another Redis is being hit) and logs a pointer to check for a port
  conflict if it still can't be set.
- Added `scripts/dev-up.ps1` / `dev-down.ps1` (Windows, matching Yash's
  actual shell) and `scripts/dev-up.sh` (bash) that bring up
  docker-compose, wait for Postgres, create `.env` from `.env.example` if
  missing, and start the worker + API as background jobs/processes in the
  right order — so the "forgot to start the worker" failure mode can't
  recur. `services/agent-worker/requirements.txt` never included `pytest`/
  `requests`, so the documented `pytest` command could never have run from a
  fresh `pip install -r requirements.txt` either way — added
  `requirements-dev.txt` for that.
**Verified:** installed Postgres 16 + Redis natively in a clean environment
(no Docker available there), moved Postgres to port 5433 to mirror
`docker-compose.yml` exactly, applied both migrations, started the real
worker and the real built API from a fresh `.env` copied from the fixed
`.env.example`, and ran the actual `pytest tests/test_phase0_smoke.py -v` —
all 4 runnable tests pass (`test_0_4_live_gemini_call` still correctly
skips, no key present). This is a real, executed pass, not a static review.
**Still open:** same three gaps carried forward from the 2026-09-24 entry
(OpenTelemetry tracing, a real Gemini API smoke test, and turning this
pytest suite into CI rather than a manually-triggered local run) — none of
this session's fixes touch those.


**Tested:** noticed the same issue as the earlier Redis fix: `services/api/src/index.ts`
and `services/agent-worker/agent_worker/db.py` both had `127.0.0.1`/`postgres`/`postgres`/
`eda_platform` hardcoded, ignoring `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`
from `.env.example`. Also caught a real user-facing mismatch: their `.env`
had `PGDATABASE=EDA`, but the migrations create a database literally named
`eda_platform` — that would have silently pointed at a nonexistent database.
**Fixed:** both files now build their Postgres connection from env vars,
defaulting to the original hardcoded values when unset (zero-config sandbox
behavior preserved). Re-ran the Phase 0.1 round trip twice with no `.env`
present — passed both times, no regression.
**Still open:** attempted a third test — pointing `PGDATABASE` at a
freshly-created alternate database via `.env` to prove the env var actually
changes which database is used (not just that it's silently accepted) — this
was interrupted mid-run by the sandbox environment itself resetting (this has
now happened three times this session; it's an instability in this tool's
container, unrelated to the code). The fix follows the identical pattern
already proven end-to-end for Redis (`REDIS_HOST`/`PORT`/`PASSWORD`), so
confidence is high, but this specific PGDATABASE-override test should be
re-run (ideally on the user's own machine, which has been more stable) before
treating it as fully verified.

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
