# TRD — Automated EDA, Cleaning & Visualization Platform

## Stack
- **Agents/data layer (Python):** pandas/polars/DuckDB for deterministic
  profiling and cleaning execution; Presidio-style regex+NER for PII scan
  (v1 scope: emails, phone numbers, national ID patterns only); Jinja2/Pandoc
  or python-docx for report templating; embeddings + BM25/tsvector for hybrid
  RAG; OpenTelemetry for tracing.
- **API/frontend (Node.js/TypeScript):** API gateway (auth, routing, user-level
  rate limiting); frontend app (upload/drag-drop, Kaggle search UI, chat UI,
  report viewer, approval/review UI, data quality dashboard).
- **Job queue:** BullMQ (Node) or Celery (Python) — async, DAG-aware, with
  per-agent concurrency caps and a `pending_approvals` table for pause/resume
  on human review. Exact choice (BullMQ vs Celery) is `(open — confirm with
  user)`; given the mixed stack, BullMQ on the Node side calling into Python
  agent services (or Celery with a Node-facing API) both work — pick based on
  which side owns the queue definitions. Log the final choice as a decision.
- **Database:** Postgres (dataset versions, cleaning action log, dependency
  graph for `built_from` staleness, pending_approvals, playbook definitions).
- **LLM backend:** Gemini (v1), behind a provider-agnostic interface. Jev
  (TypeSafe AI) evaluated for constrained-choice (`llm_choice`) steps only.
  LiteLLM proxy recommended as the swap point between providers.
- **Storage:** object storage (S3-compatible) for uploaded datasets and
  generated reports.

## System requirements
- Runs as a web service (not a desktop app) — browser-based frontend, backend
  services deployable as containers.
- Async job execution is mandatory: cleaning/report runs must not block a
  request thread, and must be resumable after arbitrary pause (human
  approval can take hours/days).
- No hard offline requirement — this is a hosted/cloud product.
- Performance target: `(open — confirm with user)` — no explicit p95 latency
  or dataset-size ceiling has been set yet. Recommend setting an initial
  target (e.g. "profile a 1M-row CSV in under 60s") once profiling code
  exists, rather than guessing now.

## Integration points
- **Kaggle API** — dataset discovery/import (metadata search; LLM only for
  query understanding/keyword expansion).
- **Gemini API** — narrative generation, `llm_choice` decision points.
- **Jev API (TypeSafe AI)** — evaluation only, not yet integrated pipeline-wide.
  Early access, released mid-Sept 2026, no production track record — treat
  vendor cost/latency claims as unverified until benchmarked in-house.
- **Connectors:** Google Sheets, S3, Postgres (ingestion); PowerBI, Tableau,
  Looker Studio (export).
- **Auth:** `(open — confirm with user)` — not yet specified (e.g. email/pass,
  OAuth, SSO for team accounts). Matters for the API gateway design in Phase 0.

## Non-functional requirements
- **Security:** PII scan (regex+NER) runs before any data reaches an LLM.
  `context_fields` whitelist in every playbook step is the enforced privacy
  boundary — only named fields, never raw rows, go to an LLM call. Multiple
  API keys per agent for blast-radius containment if one key leaks/is abused.
- **Reliability:** every `llm_choice` step has a deterministic `fallback` —
  the pipeline never hard-fails on an LLM/API hiccup. Runs can sit in
  `awaiting_approval` indefinitely at zero worker cost.
- **Observability/logging:** structured logging/tracing (OpenTelemetry) +
  schema validation on all agent outputs. No dedicated "monitoring agent" —
  LLM-as-judge is used selectively/sampled for report-quality QA only. Ties
  directly into `docs/debug.md`/`docs/status.md` logging conventions.
- **Reproducibility:** every cleaning run is content-addressed (`dataset_v{n}`)
  and exportable as a Jupyter notebook built from the actual approved action
  log (chosen parameters, not LLM reasoning text).

## Known technical constraints
- Kaggle-imported data may contain improperly anonymized PII — this is the
  primary reason the PII scanner ships in v1 rather than being deferred.
- Jev is a Sept-2026 early-access product — no SLA guarantees, budget for it
  to be dropped if benchmarks against Gemini don't hold up.
- Separate API keys do not, by themselves, provide throughput isolation (all
  keys can share the same backend quota) — real isolation is job-queue
  concurrency limits, not key count. Don't conflate the two when designing
  rate limiting.
- Mixed Python/Node stack means the agent layer and API/frontend layer need a
  clear service boundary (REST/gRPC/queue messages) decided in Phase 0 —
  don't let Python agent code and Node API code share a process/import graph.

---
**Next:** Return to [`context.md`](../context.md).
