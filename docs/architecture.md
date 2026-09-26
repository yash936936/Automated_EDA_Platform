# Architecture — Automated EDA, Cleaning & Visualization Platform

## System overview
A Node.js/TypeScript **frontend + API gateway** sits in front of a **job queue**
(BullMQ/Celery — exact boundary an open decision, see `docs/trd.md`) that
dispatches work to five Python-based **agents**, each with its own API key(s)
for cost attribution and rate-limit tuning. Deterministic work (profiling,
cleaning execution, quality scoring) runs in-process in pandas/polars/DuckDB;
LLM calls happen only at named judgment points inside playbook steps or for
narrative generation. Every cleaning action is `proposed` before it is
`approved`/`rejected`, via a `pending_approvals` table the frontend polls or
subscribes to — no worker sits blocked waiting on a human. Cross-cutting
concerns (PII scan, data quality score, connectors, observability) are not
agents themselves — they're shared services/passes invoked by the agents.

## Components

### API Gateway (Node/TypeScript)
- **Responsibility:** auth, routing, user-level rate limiting, exposing REST/
  websocket endpoints for upload, Kaggle search, approvals, chat, report
  download.
- **Location:** `src/api/`
- **Depends on:** Job Queue, Postgres, all five agents (via queue messages,
  not direct calls).
- **Key files:** `(open — confirm with user; to be filled in once scaffolded)`.

### Frontend (Node/TypeScript)
- **Responsibility:** upload/drag-drop, Kaggle search UI, approval/review UI
  (batch + step-by-step modes), data quality dashboard, chat interface,
  report viewer.
- **Location:** `src/frontend/`
- **Depends on:** API Gateway.
- **Key files:** `(open — confirm with user)`.

### Job Queue + pending_approvals
- **Responsibility:** async, DAG-aware dispatch with per-agent concurrency
  caps; pause/resume orchestration for human review steps.
- **Location:** `src/shared/queue/`
- **Depends on:** Postgres (for `pending_approvals`, run state).
- **Key files:** playbook step executor, approval-gate middleware.

### Agent 1 — Dataset Discovery
- **Responsibility:** Kaggle API metadata search (no LLM for search itself);
  LLM only for query understanding/keyword expansion; result caching.
- **Location:** `src/agents/discovery/`
- **Depends on:** Kaggle API, Gemini (query expansion only).

### Agent 2 — EDA + Cleaning
- **Responsibility:** deterministic profiling (types, missingness,
  distributions, correlations) via pandas/polars/DuckDB; executes playbook
  steps; calls LLM/Jev only at defined `llm_choice` branches (e.g. imputation
  strategy); logs every action with reasoning; works on a copy, nothing
  applied until approved.
- **Location:** `src/agents/eda_clean/`
- **Depends on:** Playbook engine (`src/shared/playbooks/`), Gemini/Jev,
  Postgres (audit log, versioning).

### Agent 3 — Summary + RAG
- **Responsibility:** structured summary generation at ingestion; chunking at
  dataset/column/relationship level; embedding for hybrid retrieval; also
  writes structured stats directly to Postgres for exact-value lookups
  (bypassing RAG for numeric questions).
- **Location:** `src/agents/summary_rag/`
- **Depends on:** Agent 2's cleaning output, embedding store, Postgres,
  BM25/tsvector index.

### Agent 4 — Report Compilation
- **Responsibility:** templating-driven report generation (Jinja2/Pandoc or
  python-docx) combining Agent 2's cleaning log + Agent 3's summary/insights +
  chart specs; one LLM call for an executive-summary paragraph, not per-section.
- **Location:** `src/agents/report_gen/`
- **Depends on:** Agent 2, Agent 3, chart/visualization module.

### Agent 5 — Extras
- **Responsibility:** domain playbook pack selection, drift-detection
  narrative, data-quality-score explanation. Mostly rule-based with narrative
  LLM glue.
- **Location:** `src/agents/extras/`
- **Depends on:** playbook engine, data quality scorer, drift detector.

### Cross-cutting shared services (not agents)
- **PII/masking:** regex + NER pass (`src/shared/pii/`), runs before any data
  reaches an LLM. v1 scope: emails, phones, national ID patterns.
- **Data quality score:** pure computation (`src/shared/quality_score/`), no LLM.
- **Connectors:** standard ETL adapters (`src/shared/connectors/`) — S3, Google
  Sheets, Postgres (ingestion); PowerBI/Tableau/Looker Studio (export).
- **Observability:** OpenTelemetry tracing across the API gateway and the
  EDA/Clean worker, wired up as of Phase 0.4 (`services/api/src/tracing.ts`,
  `services/agent-worker/agent_worker/tracing.py`). Manual spans, not
  auto-instrumentation -- the API runs as pure ESM, where OTel's Node
  auto-instrumentation needs a `--experimental-loader` hook this repo
  doesn't wire in, so route handlers and the worker's job processor create
  spans explicitly instead. Trace context crosses the Redis/BullMQ boundary
  via a W3C `traceparent` injected into the job payload itself
  (`_traceCarrier`) since the two processes share no memory -- this is what
  makes one API request and the worker's handling of its job show up as a
  single linked trace rather than two disconnected ones. Exports as OTLP/HTTP
  to the `jaeger` service in `docker-compose.yml` (UI on :16687, not
  Jaeger's usual :16686, in case another Jaeger instance is already running
  locally) — not an LLM watching other LLMs.

## Data flow
1. User uploads a file or searches/imports via Kaggle (Agent 1) → dataset
   lands in object storage, metadata in Postgres.
2. PII scan runs before anything reaches an LLM → flags surfaced to user.
3. Agent 2 runs deterministic profiling, then executes the matched playbook
   (see `docs/code_logic.md` for the playbook engine's decision logic) →
   proposed actions written to `pending_approvals`.
4. User reviews (batch or step-by-step) via the frontend → approve/edit/reject
   → API records decision → job re-enqueued from that step.
5. On completion, a stamped `dataset_v{n}` is produced, tied to the exact
   approved/overridden action IDs.
6. Agent 3 chunks + embeds the cleaned dataset's summary (dataset/column/
   relationship level), recording `built_from: dataset_v{n}`.
7. Agent 4 compiles the report from Agent 2's log + Agent 3's summary + chart
   specs, also recording its `built_from` version.
8. Agent 5 runs domain playbook narrative, drift detection (on re-upload of
   the same source), and quality-score explanation.
9. If a user later edits an approved decision, a new version (`v{n+1}`) is
   produced; downstream stages whose `built_from` points at the old version
   are marked `stale` per the per-project stale-handling policy (default:
   flag stale, manual rerun — see `docs/decisions.md`).
10. Chat queries route through the intent classifier (rule-based first pass):
    structured lookup, RAG retrieval, or both, before hitting the LLM.

## File tree (living document — keep in sync with src/)
```
src/
├── api/                — Node/TS API gateway (not yet scaffolded)
├── frontend/            — Node/TS frontend (not yet scaffolded)
├── agents/
│   ├── discovery/        — Agent 1
│   ├── eda_clean/         — Agent 2
│   ├── summary_rag/       — Agent 3
│   ├── report_gen/        — Agent 4
│   └── extras/            — Agent 5
└── shared/
    ├── queue/             — job queue + pending_approvals orchestration
    ├── playbooks/         — playbook schema + engine (YAML/JSON defs)
    ├── pii/                — PII scan/mask
    ├── quality_score/      — data quality scoring
    ├── connectors/         — S3, Google Sheets, Postgres, BI export adapters
    └── llm/                — provider-agnostic Gemini/Jev interface
```

## External dependencies
- **Kaggle API** — dataset discovery.
- **Gemini API** — v1 LLM, chosen for prototype speed; swappable via
  provider-agnostic interface.
- **Jev (TypeSafe AI)** — evaluated for constrained-choice steps; not adopted
  pipeline-wide (see `docs/decisions.md`).
- **pandas/polars/DuckDB** — deterministic profiling/cleaning; chosen to keep
  cost/latency predictable and keep LLM usage bounded to genuine judgment calls.
- **BullMQ/Celery** — job orchestration; staying put until a concrete pain
  signal appears (see `docs/decisions.md`).
- **Postgres** — audit log, versioning/dependency graph, pending approvals,
  playbook definitions, structured stats for chat lookup.
- **Presidio-style regex+NER** — PII scan (v1: regex-only scope).
- **Jinja2/Pandoc/python-docx** — report templating.
- **OpenTelemetry** — observability.

---
**Next:** Return to [`context.md`](../context.md).
