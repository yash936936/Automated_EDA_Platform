# Debug Log — Automated EDA, Cleaning & Visualization Platform

> Append-only. Newest entries at top. Log every coding session here, even
> "no issues found" — this is the record of what was actually tested, not
> just what was built.

## [2026-09-27] Phase 1.1 re-run after fixes — all green on Yash's machine
**Tested:** after rebuilding the API (BIGINT fix) and installing
`requests-toolbelt`, ran `pytest tests/test_phase1_1_upload.py -v` twice.
**Found:** run 1: 3 passed in 47.9s; run 2 (`-k large`): 1 passed in 56.7s.
Note run 1 also executed the 500MB test because `RUN_LARGE_UPLOAD_TEST=1`
was still set in that PowerShell session from the earlier attempt — so the
large test has passed twice, not once.
**Fixed:** nothing new; both earlier bugs (string BIGINTs, generator upload
in the test client) confirmed fixed.
**Still open:** manual drag-and-drop via `http://localhost:4000/upload.html`
not yet tried; checksum correctness is covered by the moto test, not
asserted against a known hash in the live tests; production hardening of
SeaweedFS (S3 identity config, TLS, backups — D-016) is untouched.

## [2026-09-27] Phase 1.1 first live run on Yash's machine — real stack works, 3 test/API bugs found
**Tested:** Yash ran the full stack (docker compose with SeaweedFS, worker,
API) and `pytest tests/test_phase0_smoke.py` + `test_phase1_1_upload.py`.
Phase 0: 5/5 passed (including live Gemini). Phase 1.1: uploads reached
SeaweedFS, the BullMQ `ingest_dataset` job ran, datasets reached
`status='ready'` — i.e. the real wiring (Busboy -> lib-storage -> SeaweedFS
-> queue -> boto3 -> Postgres) works, which the moto-only testing could not
show.
**Found:**
- API returned `row_count`/`size_bytes` as strings (`'3'`): node-postgres
  returns BIGINT as string by default. A real API bug, not just a test issue.
- The 500MB test failed in the test client: `requests` cannot take a
  generator in `files=` (`TypeError: bytes-like object is required`). The
  500MB / non-blocking criterion has therefore NOT been exercised yet.
**Fixed:** `types.setTypeParser(20, Number)` in `services/api/src/index.ts`;
large test rewritten to write a temp file and stream it with
`requests-toolbelt`'s `MultipartEncoder` (added to requirements-dev.txt).
Not yet re-run after the fixes.
**Still open:** re-run both Phase 1.1 test files and the large test
(`RUN_LARGE_UPLOAD_TEST=1`); 1.1 stays unchecked in `phases.md` until the
large test passes.

## [2026-09-27] MinIO image pull denied from Docker Hub — switched to quay.io mirror
**Tested:** Yash ran `docker compose up -d` on his own machine (first real
run of the new minio/createbuckets services from Phase 1.1) and hit
`Error response from daemon: pull access denied for minio/minio, repository
does not exist or may require 'docker login'`.
**Found:** not a local auth/login problem — Docker Hub started denying
anonymous pulls of `minio/minio` and `minio/mc` outright as of this month
(2026-09), independent of this project; confirmed via web search that
multiple unrelated repos hit the identical error the same week. MinIO
continues to mirror the same images under the same tags to `quay.io`.
**Fixed:** `docker-compose.yml`'s `minio` and `createbuckets` services now
pull `quay.io/minio/minio:latest` and `quay.io/minio/mc:latest` instead of
the Docker Hub `minio/*` names. No other config (env vars, ports, the `mc
alias set`/`mc mb` bucket-creation command) changes — same images, same
tags, different registry only. Not yet re-verified on Yash's machine after
the swap (this fix was made in the sandbox, which still has no Docker) —
next session should confirm `docker compose up -d` succeeds end to end with
this change before trusting it further.

## [2026-09-27] Phase 1.1 — File upload path
**Tested:**
- Wrote `probe_dataset` (services/agent-worker/agent_worker/storage.py) and
  verified it directly against a **moto-mocked S3 bucket** (no real
  MinIO/Postgres/Redis available in this sandbox): (1) a small CSV — asserted
  row_count, column_count, size_bytes, and sha256 checksum all matched
  ground truth computed independently; (2) a non-CSV binary blob — asserted
  size/checksum still computed and row/column counts correctly left `None`;
  (3) the same CSV again with the chunk size forced down to 7 bytes
  (deliberately smaller than one row) to exercise the line-split-across-
  chunk-boundary logic — same correct result, so the streaming parser
  doesn't corrupt rows that straddle a chunk boundary.
- Type-checked the API gateway (`npx tsc --noEmit`) after adding the
  `POST /api/datasets/upload` route, `storage.ts`, and the two dataset-read
  routes — clean, no errors.
- Syntax/import-checked the Python worker changes (`ast.parse`, plus
  actually importing `agent_worker.worker` and confirming `ingest_dataset`
  is registered in `HANDLERS` alongside the Phase 0 handlers).
- Wrote `tests/test_phase1_1_upload.py` (small-CSV round trip, non-CSV round
  trip, and an opt-in `RUN_LARGE_UPLOAD_TEST=1` 500MB concurrency test) —
  collects cleanly under pytest but **was not run against live services**,
  see "Still open."

**Found:** none in the logic that could be exercised standalone (moto mock).

**Fixed:** n/a — new code, not a fix.

**Still open (do not mark 1.1 fully closed until these are addressed):**
- **No real end-to-end run.** This sandbox has no `docker` binary, so
  `docker compose up` (redis + postgres + the **new** minio/createbuckets
  services) was never started, migration `002_dataset_ingestion.sql` was
  never applied to a real Postgres, and neither
  `POST /api/datasets/upload` nor the `ingest_dataset` BullMQ job has been
  exercised end-to-end. Everything above verifies the *logic* in isolation
  (mocked S3) — not the *wiring* (real S3 client config against real MinIO,
  a real BullMQ round trip, real Postgres writes, the actual multipart
  stream through Busboy + `@aws-sdk/lib-storage`'s `Upload`). Same root
  cause as the PGDATABASE-override gap below (sandbox has no Docker), same
  remedy: run `pytest tests/test_phase1_1_upload.py -v` against the real
  stack before treating 1.1 as passing.
- **500MB stress test never run.** `test_1_1_large_file_does_not_block_event_loop`
  is gated behind `RUN_LARGE_UPLOAD_TEST=1` precisely because it wasn't run
  here; it's the test that actually exercises Phase 1.1's stated passing
  criterion ("large file doesn't block the request thread"), so it matters
  more than the two tests that only got collection-checked.
- `docs/architecture.md`'s "File tree" diagram still shows a `src/`-rooted
  layout that doesn't match the real `services/api/` + `services/agent-worker/`
  layout Phase 0 actually scaffolded — pre-existing drift, not introduced by
  this session, but worth a cleanup pass since `docs/workflow.md` calls that
  section a "living document."

## [2026-09-26] CI's first real run on GitHub Actions — passed
**Tested:** pushed the tracing/CI/test-fix work to `main` (commit `4e95fe7`).
This triggered `Phase 0 CI`'s actual first execution on GitHub's own
runners -- the one thing the local dry-run in the entry below couldn't
prove, since it's a different environment (network egress rules, base image
package versions, contended shared hardware) than any local shell.
**Result:** green. `Phase 0 CI #1` completed in 1m 1s against commit
`4e95fe7` on `main`. No environment-specific surprises -- the local dry-run
turned out to be an accurate predictor of the real run.
**Status:** every honest gap this session tracked for Phase 0 is now
closed with real evidence, not just code review: tracing (verified via a
real Jaeger binary, twice independently), live Gemini (verified on Yash's
machine, real key, real pass), and CI (verified on real GitHub Actions,
real green run). Phase 0 is done.

## [2026-09-26] CI wired up (closes the third and last of Phase 0's tracked gaps)
**Work:** added `.github/workflows/ci.yml` -- runs the real
`tests/test_phase0_smoke.py` suite on every push/PR to `main`, against real
Postgres 16 and Redis 7 service containers (not mocks), a real built API,
and a real worker process. Matches the local dev topology deliberately:
Postgres published on the same **5433** host port used everywhere else in
this repo, so nothing has to special-case "the port is different in CI" --
one less thing to drift out of sync between environments. `LLM_PROVIDER=fake`
and no `GEMINI_API_KEY_*` are set on purpose: `test_0_4_live_gemini_call` is
meant to skip in CI, since a shared CI environment is the wrong place to
spend real API quota or depend on an external service's uptime on every
push (contrast with the 2026-09-26 entry above this one, where that same
test skipping *locally* despite a real key being set was a bug -- here,
skipping is the correct, intentional behavior).
**Verified for real, not just written:** could not run actual GitHub
Actions in this environment, so did the closest possible thing --
reproduced the exact workflow step-by-step, in order, in a real shell: `npm
ci` (not `npm install`, to catch a lockfile drifted out of sync with
`package.json`, which real CI would fail on and local `npm install` would
silently paper over -- confirmed clean), build, install worker deps, apply
both migrations against a freshly-dropped-and-recreated database, start
worker, start API, wait-for-ready via the same "verify, don't just sleep"
pattern used in `scripts/dev-up.sh`/`.ps1`, then the actual test run:
`4 passed, 1 skipped` -- the skip being the intended one, since no `.env`
existed in that shell at all.
**Still open (at the time this entry was written):** the workflow had not
yet executed on GitHub's actual runners -- see the entry above this one
(newer) for that confirmation, which came back green on the very first
real push. This closes out all three gaps `docs/status.md`'s 2026-09-25
entry originally tracked for Phase 0 (tracing, live Gemini, CI) -- Phase 0
is now done against every criterion in `docs/phases.md`, not just the ones
verifiable without a live key or a real CI run.

## [2026-09-26] test_0_4_live_gemini_call kept skipping despite a real key being set
**Tested:** Yash set `GEMINI_API_KEY_EDA_CLEAN` in `.env` to a real key,
still got `SKIPPED (no real Gemini key set for eda_clean)`. Replaced the key
with a different one, same result -- ruled out the key value itself as the
cause.
**Found:** `tests/test_phase0_smoke.py`'s `@pytest.mark.skipif(not
os.environ.get("GEMINI_API_KEY_EDA_CLEAN"), ...)` decorator is evaluated at
**collection time** -- the instant pytest imports the test module, before
any test function body runs. The file never calls `load_dotenv()` itself;
`.env` only gets loaded by `gemini_provider.py`/`db.py`/`worker.py`, and
this test file only imports `agent_worker.llm.factory` (which pulls in
`gemini_provider.py`) *inside* `test_0_4_llm_interface_contract`'s function
body -- which runs during the test phase, after collection already
evaluated (and permanently fixed) the skip decision for the test after it.
So the skip check always read a raw, unloaded `os.environ` and always
evaluated to "skip", regardless of what `.env` actually contained. This
wasn't specific to Yash's key at all -- it would have skipped for anyone,
with any key, every time.
**Fixed:** added `from dotenv import load_dotenv; load_dotenv()` at the top
of `tests/test_phase0_smoke.py`, before the `@pytest.mark.skipif` line.
**Verified:** reconstructed the old (buggy) file and the fixed file
side-by-side, ran both against the identical `.env` containing a (fake,
since no real key is available in this environment) `GEMINI_API_KEY_EDA_CLEAN`
-- old version: `SKIPPED`; fixed version: actually attempted the call and
failed only on `google.genai` rejecting the placeholder key value, which is
the expected/correct behavior for a fake key. On Yash's machine with his
real key, this should now genuinely execute and pass rather than skip.
**Still open:** Yash to confirm `test_0_4_live_gemini_call` actually
**passes** (not just runs) with his real key -- this fix only proves the
test now executes; it doesn't by itself confirm the real Gemini API call
succeeds. CI is still the next and final Phase 0 gap after that.

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
**Confirmed on Yash's actual machine, not just this sandbox:** after
`npm install` picked up the new `@opentelemetry/*` packages (`package.json`
already listed them from this session's work; his `node_modules` just
predated the install), `docker compose up -d` brought up `jaeger` alongside
redis/postgres with both ports mapped correctly (`4318`, `16687->16686`).
Queried Jaeger's own API directly (`GET /api/traces?service=eda-api`) and
got back the same structure verified in this sandbox: one trace
(`249008a9c6ad7352a8489a943a8edaa8`) with `POST /api/ping-agent`
(`eda-api`, root) and `worker.process echo` (`eda-clean-worker`) correctly
linked via `CHILD_OF`, with `bullmq.job_id`/`bullmq.job_name` attributes on
the worker span. Tracing is genuinely closed, verified twice independently
(this sandbox + Yash's real Windows/Docker setup).
**Still open:** `GeminiProvider` still not confirmed against the real live
API as of this entry -- `test_0_4_live_gemini_call` was still skipping on
Yash's machine even after setting `GEMINI_API_KEY_EDA_CLEAN`, a separate,
new issue investigated in the entry above (newer, since this file is
newest-first). No CI yet either (the step after that, per Yash's stated
plan).

## [2026-09-25] Phase 0 fully green on Yash's machine — session closed out
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

## [2026-09-25] Postgres fixed, then test_0_1/0_3 failed again — stale worker on a different Redis than the API
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
