# Debug Log — Automated EDA, Cleaning & Visualization Platform

> Append-only. Newest entries at top. Log every coding session here, even
> "no issues found" — this is the record of what was actually tested, not
> just what was built.

## [2026-09-25] Postgres auth failure with correct PGPORT=5433 — likely a native PG17 collision
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
