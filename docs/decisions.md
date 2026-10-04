# Decisions — Automated EDA, Cleaning & Visualization Platform

> Append-only log. Newest entries at top. Never edit or delete past entries —
> if a decision is reversed, log a new entry that supersedes it and reference
> the old ID.

## D-018 — Phase 1.3 PII pre-scan: one-pass scan, heuristic confidence, strict guard — 2026-10-04
**Decision:**
1. The scan runs inside the existing ingest pass (`probe_dataset` feeds each
   parsed row to `PiiScanner`) — no second read of the file. The dataset's
   `status='ready'`, its `pii_status`, and its `pii_findings` rows are written
   in ONE transaction, so a dataset is never ready with its scan missing.
2. D-007 scope, regex only: emails; phones (international `+`, US/NANP
   formatted, Indian mobile); national IDs: Aadhaar (Verhoeff checksum), PAN
   (holder-type letter), US SSN (invalid ranges excluded). Aadhaar/PAN/SSN
   were my choice of "national ID patterns" (D-007 didn't name countries).
3. Findings are per (column, detector): counts, match rate, confidence,
   header-hint flag. Raw values are NEVER stored or returned.
4. Confidence is a documented HEURISTIC (see scanner.py docstring), not a
   calibrated probability. Flag at >= 0.40 (D-003). Collision-prone detectors
   (bare 10-digit phones, bare 12-digit Aadhaar) also need a minimum match
   rate unless the column header hints at the type.
5. `pii_status` is explicit: `pending` -> `scanned` | `skipped_unsupported`
   (non-CSV) | `legacy_unscanned` (rows from before 1.3). "Not scanned" is
   never presented as "clean".
6. `require_pii_scanned(conn, dataset_id)` guard: only `scanned` passes. Phase
   2 code must call it before building any LLM context from a dataset.
7. Rows beyond `PII_MAX_ROWS` (default 500k) are counted but not scanned;
   `pii_truncated` records it.
8. Any exception during the pass fails the whole ingestion (status 'failed'
   with reason) rather than letting a dataset through with an unknown scan.
**Why:** one pass keeps large-file ingestion cheap; the atomic write and the
guard make "scan before LLM" structural instead of a convention; explicit
states avoid the worst failure mode of a scanner, silently reporting "clean".
**Known gaps (NOT resolved):**
- Detection only. Nothing is masked: raw data stays unmasked in object
  storage regardless of findings. Masking/thresholds are Phase 3.2.
- Names and free-text PII are not detected (D-007, v2). Only emails are
  searched inside free text; every other detector needs the whole cell to match.
- Not covered: payment card numbers, other countries' national IDs (UK NINO,
  etc.), addresses, dates of birth. Card numbers arguably belong in v1 — say
  if you want them added.
- PII beyond row `PII_MAX_ROWS` is missed (flagged via `pii_truncated`, not fixed).
- Confidence numbers are uncalibrated; Phase 8.2 must validate on real data.
- The "scan before any LLM call, verified in trace ordering" criterion is met
  structurally (ready only after scan; guard) plus span attributes
  (`eda.pii.*`) — no code sends dataset-derived data to an LLM yet, so the
  guard has no callers until Phase 2.
**Affects:** Phase 1.3, `db/migrations/004_pii.sql`,
`services/agent-worker/agent_worker/{pii/scanner.py,storage.py,worker.py}`,
`services/api/src/index.ts` (`GET /api/datasets/:id/pii`), `.env.example`.

## D-017 — Phase 1.2 Kaggle discovery: queue split, file-level import, shared token — 2026-10-03
**Decision:**
1. Agent 1 gets its own BullMQ queue `agent.discovery` (cap via
   `DISCOVERY_CONCURRENCY`). Search/list-files are awaited by the API
   (D-011); import is NOT — it returns 202 and reuses the `ingesting ->
   ready|failed` status flow from upload (1.1).
2. Import is per FILE, chosen explicitly by the client from
   `/api/discovery/files`; v1 accepts only `.csv`/`.tsv`, validated against
   Kaggle's own listing, capped by `KAGGLE_MAX_IMPORT_MB` (default 1024).
   Imported files go through the same `ingest_dataset` job as uploads.
3. Search = original query + at most 2 LLM-suggested alternatives (Gemini,
   `discovery` key), fused with reciprocal-rank fusion, cached in Postgres
   (`kaggle_search_cache`, 24h; 1h when LLM expansion fell back). The LLM
   step can never fail a search (fallback to original query).
4. Re-importing the same ref+file returns the existing dataset (unique
   partial index), including under double-click races.
5. Kaggle SDK (`kaggle>=2`) authenticates via `KAGGLE_API_TOKEN`.
**Why:** keeps long downloads off HTTP requests; per-agent concurrency per
the design doc; explicit file choice avoids guessing which file in a
multi-file dataset the user meant; tabular-only matches what Phase 2 can
profile.
**Risks accepted / flagged (NOT resolved):**
- ONE server-wide Kaggle account serves every user. Kaggle may rate-limit
  it, and a shared account fronting a multi-user product may sit badly with
  Kaggle's terms. Fine for development; needs a deliberate answer (per-user
  tokens, or confirming terms) before real multi-user launch.
- Dataset licenses vary per dataset. We copy the file into our own storage
  and later put derived data in reports/exports. License is shown in search
  results but is NOT yet persisted on the imported dataset. Recommend adding
  a `source_license` column + showing it in the report before 1.2 is
  considered production-ready.
- Kaggle data can contain PII; 1.3's scan must cover this path (it does if
  hooked into `ingest_dataset`, which both paths share).
- Discovery handlers run in a thread (`asyncio.to_thread`) so long
  downloads don't stall BullMQ lock renewal. The existing `agent.eda_clean`
  `process()` still runs handlers (incl. `ingest_dataset` on large files)
  directly on the event loop — a latent stall risk for multi-GB files.
  Not changed here; recommend the same treatment.
**Affects:** Phase 1.2, `db/migrations/003_discovery.sql`, `.env.example`,
`services/agent-worker/agent_worker/discovery/`, `worker.py`,
`services/api/src/{queue,index}.ts`.

## D-016 — Production object storage: self-hosted SeaweedFS, replacing Cloudflare R2 — 2026-09-27
**Decision:** Supersedes D-015. Use self-hosted SeaweedFS (same software as
dev, D-014) in production instead of Cloudflare R2. No code change: same
`S3_*` env vars, `S3_FORCE_PATH_STYLE=true`.
**Why:** user's call — wants an open-source, free option rather than a
managed vendor. SeaweedFS is Apache 2.0 with production use since ~2015 and
is already the dev backend, so there is one storage system to learn.
Garage (AGPL-3.0) was the main alternative; RustFS (Apache 2.0) was ruled out
for now because its production-readiness status was unclear.
**Trade-offs accepted (flagged, not resolved):**
- Durability and backups become our responsibility. R2 handled this; here
  nothing replicates or backs up data unless we configure it. This matters
  because the product promises reproducible, auditable dataset versions.
- Dev mode runs the S3 gateway with no identities. Production must load an
  S3 identity config and sit behind TLS, unexposed to the public internet.
- Hosting cost is now a VPS plus disk instead of R2's free tier.
- Download-heavy traffic is bounded by our host's bandwidth, not free egress.
**Affects:** `.env.example` (production block), `docs/architecture.md`,
`docs/trd.md`, future deploy runbook (not yet written).

## D-015 — Production object storage: Cloudflare R2, not AWS S3 — 2026-09-27
**Superseded by D-016 the same day** — historical only; kept per the
append-only convention.
**Decision:** Use Cloudflare R2 as the production object storage backend,
via the same `S3_*` env vars / provider-agnostic storage layer as dev
(`S3_ENDPOINT` pointed at the account's R2 endpoint, `S3_FORCE_PATH_STYLE=false`,
`S3_REGION=auto`). AWS S3 was the original assumption in `docs/trd.md` but
was never formally decided.
**Why:** R2 has a genuine free tier (10GB storage, 10M Class A + 1M Class B
ops/month) backed by a vendor whose core business is storage — a different
risk profile than MinIO's free-tier retreat (D-013/014), since Cloudflare's
incentive runs the opposite direction. More importantly for this product's
actual usage shape: R2 charges **zero egress fees**, while AWS S3 egress is
usually the line item that surprises people. This product's traffic is
download-heavy (report/notebook/dataset downloads) relative to upload
volume, so egress cost — not storage cost — is the number that would
actually move on AWS. Considered and rejected: Backblaze B2 (comparable free
tier and a longer track record, but R2's egress model and tighter edge
integration won out for a product serving user-facing downloads); Oracle
Cloud "Always Free" (real free tier, weaker API/dev-experience reputation,
not worth it when R2 fits better anyway).
**Affects:** `.env.example` (production block), eventual deploy docs/runbook
(not yet written — flag when deployment is actually set up that the R2 API
token should be scoped to Object Read & Write on the one bucket, not
account-wide, matching the per-agent-key blast-radius reasoning already used
for Gemini keys).

## D-014 — Dev/self-hosted object storage: SeaweedFS, replacing MinIO — 2026-09-27
**Decision:** Supersedes D-013. Drop MinIO entirely (both `minio/minio` and
its `quay.io/minio/minio` mirror) and use SeaweedFS's built-in S3 gateway
(`chrislusf/seaweedfs:latest`, run as `server -dir=/data -s3`) as the dev
object storage backend instead. Also drop the separate `mc`-based
bucket-creation container — the API gateway and agent worker each attempt an
idempotent `HeadBucket`/`CreateBucket` at their own startup instead (whoever
starts first wins, the other's attempt is a harmless no-op).
**Why:** D-013 treated "which S3-compatible image to run" as a low-risk
implementation detail. It wasn't — MinIO's open-source project was archived
by its own maintainers in April 2026 (pushing users toward a paid "AIStor"
product), and by September 2026 both Docker Hub and quay.io were returning
hard 401s/access-denied on every tag of `minio/minio` **and** `minio/mc`,
not a specific broken tag. That's not a pinning problem to work around, it's
the vendor deliberately shutting off free public distribution — repointing
to another registry only bought a few days before quay.io closed the same
door (confirmed via multiple independent, contemporaneous reports of the
identical failure across unrelated projects). SeaweedFS is maintained by a
different org, unaffected by MinIO's business decisions, and its S3 gateway
is a drop-in replacement for what this project actually needs (one bucket,
one node, S3-compatible PUT/GET). Removing the `mc` sidecar at the same time
removes a second dependency on an image from the same now-unreliable source.
**Affects:** Phase 1.1, `docker-compose.yml`, `.env.example`,
`docs/architecture.md`, `services/api/src/storage.ts`,
`services/agent-worker/agent_worker/storage.py`.

## D-013 — Dev/self-hosted object storage: MinIO (S3-compatible) — 2026-09-27
**Superseded by D-014 the same day** — see above. Left here per the
append-only/never-edit convention; do not use MinIO per this entry, it's
historical only.
**Decision:** Use MinIO as the local/dev object storage backend, accessed
through `@aws-sdk/client-s3` (Node) and `boto3` (Python) against its
S3-compatible API. Both sides read the same `S3_*` env vars
(`S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION`,
`S3_FORCE_PATH_STYLE`).
**Why:** `docs/trd.md` already specified "object storage (S3-compatible)"
but never named a concrete provider to develop against — needed one to build
Phase 1.1. MinIO is genuinely S3-API-compatible (not a lookalike), runs as a
single docker-compose service with no external account/credentials, and the
switch to real AWS S3 in production is a config change only (drop
`S3_ENDPOINT`, set `S3_FORCE_PATH_STYLE=false`) — no code path forks on which
backend is in use.
**Affects:** Phase 1.1, `docker-compose.yml`, `.env.example`,
`docs/architecture.md`, `docs/trd.md`.

## D-012 — Queue tech: BullMQ (not Celery), shared over one Redis instance — 2026-09-24
**Decision:** Use BullMQ as the job queue, with the Node API as producer and
the Python agent worker as consumer via the maintained `bullmq` Python client
(taskforcesh), both against the same Redis instance.
**Why:** Celery is Python-native and would need a translation layer (or a
Node Celery client of uncertain quality) for the Node side to produce jobs;
BullMQ's official Python port lets one queue implementation serve both
languages of the mixed stack (D-010) with no bridge code. Verified working in
Phase 0.1/0.3 testing.
**Affects:** `docs/trd.md` (resolves the open BullMQ-vs-Celery item),
Phase 0.3, all future agent job definitions.

## D-011 — Python↔Node service boundary: HTTP for request/response, shared BullMQ/Redis for job dispatch — 2026-09-24
**Decision:** The Node API gateway does not call Python agents directly over
HTTP for work dispatch; it enqueues BullMQ jobs and awaits completion via
`waitUntilFinished`/QueueEvents. Synchronous admin/read endpoints (e.g.
fetching a pending approval) go straight to Postgres from Node.
**Why:** matches the design doc's job-queue-first architecture (§4) and the
pending_approvals pause/resume pattern (§6) — a direct HTTP call from Node to
a Python agent would need its own timeout/retry/pause handling that the queue
already provides for free.
**Affects:** `docs/trd.md` (resolves the open Python↔Node boundary item),
`docs/architecture.md`, Phase 0.1, Phase 0.3.

## D-010 — Backend split: Python for agents/data, Node/TS for API+frontend — 2026-09-23
**Decision:** Agents and all data/ML work (pandas/polars/DuckDB, playbook
engine, RAG) are implemented in Python; the API gateway and frontend are
Node.js/TypeScript.
**Why:** matches the user's confirmed stack preference. Requires a clear
service boundary between the two languages (queue messages or REST/gRPC) —
left as an open item for Phase 0.1, not decided here.
**Affects:** `docs/trd.md`, `docs/architecture.md`, Phase 0.

## D-009 — Job orchestration: stay on BullMQ/Celery — 2026-09-23
**Decision:** Do not adopt Temporal/Prefect preemptively. Stay on BullMQ/
Celery until a concrete pain signal appears (hand-rolled `pending_approvals`
retry/resume logic becomes hard to maintain, or multi-day paused runs with
reminders are needed).
**Why:** avoids premature infrastructure complexity for a v1 product; the
hand-rolled `pending_approvals` pattern is deliberately simple and sufficient
for known v1 needs.
**Affects:** Phase 0.3, Phase 8.3.

## D-008 — Code/notebook export format: Jupyter notebook, not flat script — 2026-09-23
**Decision:** Export the audit trail as a Jupyter notebook (one cell per
applied playbook step, using actual chosen parameters) rather than a flat script.
**Why:** reuses data already captured for the audit trail (low incremental
cost) and gives technical users an artifact they can keep iterating on.
**Affects:** Phase 5.3.

## D-007 — PII scan v1 scope: emails, phones, national ID patterns only — 2026-09-23
**Decision:** v1 PII scanner is narrow and deterministic (regex-detectable
patterns only). Names and free-text-embedded PII (needing NER) deferred to v2.
**Why:** a narrow, reliable v1 scanner beats a broad, noisy one for first
release — false positives cost user trust and clicks.
**Affects:** Phase 1.3, Phase 3.2, `docs/prd.md` non-goals.

## D-006 — Domain playbook pack ship order: e-commerce → finance → survey — 2026-09-23
**Decision:** Ship e-commerce first, finance second, survey third (or defer).
**Why:** e-commerce has the most standardized schema patterns and the largest
supply of public Kaggle datasets to validate against; survey data (Likert
scales, skip logic) is the most idiosyncratic and best deferred until the
playbook engine is proven.
**Affects:** Phase 6.

## D-005 — Chat intent-classifier logic: rule-based first pass, LLM only for ambiguous cases — 2026-09-23
**Decision:** Column-name + aggregate-verb match → structured lookup; no
match + dataset-referential phrasing → RAG; column match + open-ended
phrasing → both; only genuinely ambiguous questions escalate to an
LLM-based classifier call.
**Why:** keeps the common case cheap and keeps hallucinated stats structurally
impossible for the exact-lookup case.
**Affects:** Phase 4.3.

## D-004 — Stale-handling default: flag stale, manual rerun — 2026-09-23
**Decision:** Default policy when an approved decision is edited and
downstream artifacts go stale is "flag stale, let user trigger rerun
manually" — not auto-rerun, not block-export. Configurable per project.
**Why:** auto-rerun burns cost on every micro-edit mid-iteration; blocking is
too rigid for exploratory use; matches the "proposals, not silent actions" principle.
**Affects:** Phase 2.4.

## D-003 — Confidence thresholds per category, not a single global number — 2026-09-23
**Decision:** Cleaning actions 0.80; viz/chart-type selection 0.60; PII
flagging asymmetric (~0.40 to flag, ~0.90 to auto-mask).
**Why:** risk tolerance varies by reversibility and blast radius — a wrong
silent cleaning choice corrupts downstream stats (kept conservative); a
mediocre chart suggestion is cheap to swap out; a missed real PII column is
worse than a benign false-positive flag.
**Affects:** Phase 2.2, Phase 3.2, Phase 5.2, Phase 8.2.

## D-002 — Constrained-choice model (Jev) treated as v2 optimization, not v1 dependency — 2026-09-23
**Decision:** Use Gemini as the sole LLM for v1. Evaluate Jev (TypeSafe AI)
against Gemini on 2–3 existing choice points before adopting pipeline-wide.
**Why:** Jev is early access (released mid-Sept 2026) with no production
track record; vendor-quoted cost/latency figures are unverified claims, not benchmarks.
**Affects:** Phase 8.1, `docs/trd.md`.

## D-001 — Automation model: proposal + human approval, never silent modification — 2026-09-23
**Decision:** Every cleaning/imputation decision is shown as a diff (before/
after, reasoning, confidence) before being applied, with full rollback. Agent
2 always works on a copy.
**Why:** core trust/differentiation story vs. competitors that auto-clean
silently; also the safety mechanism that makes the whole automated pipeline
acceptable to run unsupervised on real data.
**Affects:** entire product; enforced across Phase 2.

---
**Next:** Return to [`context.md`](../context.md).
