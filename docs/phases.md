# Phases — Automated EDA, Cleaning & Visualization Platform

> Work through phases in order. Each phase is broken into sub-phases; mark a
> sub-phase done only when its **Testing** step has actually been run and its
> **Passing criteria** are met — not on "looks right." Update `docs/status.md`
> after each sub-phase, and `docs/readme.md` when a full phase completes.

---

## Phase 0 — Foundation & Infra
**Status: sub-phases 0.1–0.4 built and passing for real, confirmed on
Yash's own machine 2026-09-25 (`4 passed, 1 skipped` — see `docs/debug.md`'s
2026-09-25 entries for the full multi-round debugging trail; this was no
longer just manual one-off verification by 0.4's original criterion, since
`tests/test_phase0_smoke.py` now exists and is repeatable, just not yet
wired into CI). Not marked fully closed: real OpenTelemetry tracing (0.1's
original criterion) is still missing, `GeminiProvider` has only been tested
at the interface-contract level (real key present but that specific agent's
key wasn't populated, so `test_0_4_live_gemini_call` still skips), and there
is still no CI running this suite automatically.**

**Goal:** a running skeleton — repo structure, DB schema, job queue, API
gateway shell, and the provider-agnostic LLM interface — with nothing
"smart" in it yet.

### 0.1 — Repo & service boundary
**Files touched:** repo root, `src/api/`, `src/agents/`, `src/shared/`
**Work:** scaffold the Node/TS API+frontend project and the Python agents
project as separate services; decide and document the exact call boundary
between them (REST vs gRPC vs queue-only messages) — currently `(open —
confirm with user)`.
**Testing:** a trivial round-trip request from frontend → API gateway →
one Python agent stub → response, logged end-to-end.
**Passing criteria:** the round-trip completes with a real network hop (not
mocked in-process) and is visible in OpenTelemetry traces.

### 0.2 — Postgres schema
**Files touched:** `src/shared/db/` (migrations)
**Work:** tables for datasets, dataset versions, cleaning action log,
`pending_approvals`, playbook definitions, dependency graph (`built_from`).
**Testing:** migration runs clean on an empty DB; a manual insert/read of one
row per table succeeds.
**Passing criteria:** all tables from `docs/architecture.md` §Data flow exist
with foreign keys enforcing the version/dependency relationships (a
downstream row cannot reference a non-existent `dataset_v{n}`).

### 0.3 — Job queue + pending_approvals mechanics
**Files touched:** `src/shared/queue/`
**Work:** implement the queue (BullMQ or Celery, per the decision logged in
`docs/decisions.md`), per-agent concurrency caps, and the pause/resume pattern:
job hits an approval-required step → writes `pending_approvals` row → exits →
re-enqueues on decision.
**Testing:** simulate a job that pauses for approval, sits idle, then resumes
after a manual DB update to `pending_approvals` (no worker held open in between).
**Passing criteria:** no worker process is occupied while a run sits in
`awaiting_approval`; resuming correctly picks up from the paused step, not
from the start.

### 0.4 — Provider-agnostic LLM interface
**Files touched:** `src/shared/llm/`
**Work:** thin interface wrapping Gemini (v1), with hooks for Jev, keyed per
agent (separate API keys for Discovery/EDA-Clean/RAG-Summary/ReportGen/Extras).
**Testing:** call the interface from two different agent stubs with two
different keys; confirm each call is attributable to its own key/agent in logs.
**Passing criteria:** swapping the underlying provider requires a config
change only, no call-site changes; per-agent key attribution is visible in logs.

**Phase 0 done when:** 0.1–0.4 all pass, and a "hello world" run can go
upload stub → queue → agent stub → approval pause → resume → completion,
fully traced.

---

## Phase 1 — Ingestion & Dataset Discovery (Agent 1)
**Goal:** users can get a dataset into the system, via upload or Kaggle search.

### 1.1 — File upload path
**Files touched:** `src/api/upload/`, `src/frontend/upload/`
**Work:** drag-and-drop upload → object storage → dataset metadata row in Postgres.
**Testing:** upload a real CSV (small + a ~500MB stress file) through the UI.
**Passing criteria:** both files land in storage with correct metadata; the
large file doesn't block the request thread (goes through the job queue).

### 1.2 — Kaggle search & import (Agent 1)
**Files touched:** `src/agents/discovery/`
**Work:** Kaggle API metadata search; LLM-based query understanding/keyword
expansion only (not the search itself); result caching.
**Testing:** run 10 varied natural-language queries (e.g. "housing prices
india", "customer churn telecom") and inspect returned candidates.
**Passing criteria:** relevant datasets appear in the top results for at least
8/10 queries; repeat queries hit cache (verified via reduced latency/logged
cache hit) instead of re-calling Kaggle+LLM.

### 1.3 — PII pre-scan on ingestion
**Files touched:** `src/shared/pii/`
**Work:** regex-based scan (emails, phone numbers, national ID patterns) runs
on any newly ingested dataset before it's exposed to any LLM call.
**Testing:** run against a synthetic dataset with known planted PII values of
each type, and a clean dataset with none.
**Passing criteria:** all planted PII instances are flagged; the clean
dataset produces zero false flags; scan completes before any LLM call is made
on that dataset (verified in trace ordering).

**Phase 1 done when:** 1.1–1.3 pass and a user can go from "search Kaggle" or
"upload a file" to a dataset row that Phase 2 can pick up, with PII already scanned.

---

## Phase 2 — EDA + Cleaning Engine (Agent 2)
**Goal:** deterministic profiling, the playbook engine, and the human-approval
flow — the core trust mechanism of the product.

### 2.1 — Deterministic profiling
**Files touched:** `src/agents/eda_clean/profiling/`
**Work:** types, missingness pattern (MCAR/MAR/MNAR), distributions,
correlations — pure pandas/polars/DuckDB, no LLM.
**Testing:** run against 5 varied public datasets (different sizes, dtypes,
missingness patterns) and manually verify a sample of the computed stats
against a notebook ground-truth.
**Passing criteria:** computed stats match ground-truth within floating-point
tolerance on all 5 datasets; profiling of a 1M-row dataset completes without
timing out the job (target latency `(open — confirm with user)`).

### 2.2 — Playbook engine + generic playbook
**Files touched:** `src/shared/playbooks/`, `playbooks/generic/`
**Work:** implement the playbook schema (per `docs/architecture.md` /
original design doc §5) — `deterministic`, `llm_choice`, `llm_freeform` step
types; `context_fields` whitelist enforcement; `confidence_threshold` +
deterministic `fallback`.
**Testing:** run the generic missing-values playbook against a dataset with
deliberately induced missingness of each pattern (MCAR/MAR/MNAR, varying %);
force one LLM call to fail and confirm fallback triggers.
**Passing criteria:** each `llm_choice` step only ever sees the whitelisted
`context_fields` (verified by inspecting the actual API payload sent); a
forced provider failure results in the deterministic fallback being applied
and logged, not a pipeline crash.

### 2.3 — Approval flow (batch + step-by-step)
**Files touched:** `src/api/approvals/`, `src/frontend/approvals/`
**Work:** diff-style batch review UI; step-by-step pause-and-ask for risky
actions (drop_column, drop_rows, low-confidence choices); one-click override
to any other valid choice from the same `choices` list.
**Testing:** run one full playbook pass in batch mode, approve some/reject
some/override one action; run a second pass in step-by-step mode and let it
pause on a risky action.
**Passing criteria:** rejected actions never touch the working copy of the
data; overridden actions apply the overridden choice, not the original
suggestion; step-by-step mode genuinely pauses (job exits, no worker held) on
every risky action and only those.

### 2.4 — Versioning & downstream staleness
**Files touched:** `src/shared/versioning/`
**Work:** stamp `dataset_v{n}` per completed run tied to exact approved/
overridden action IDs; mark downstream stages `stale` when their `built_from`
points at a superseded version; implement the "flag stale, manual rerun"
default policy (see `docs/decisions.md`) with per-project override.
**Testing:** approve a cleaning run, let Agent 3/4 run downstream, then edit
one approved decision to force `v3` → `v4`; check that downstream stages flag stale.
**Passing criteria:** the old version is never mutated in place; the UI
correctly shows "based on cleaning v3 — N changes made since"; a project with
the stale policy overridden to "block export" actually blocks the report download.

**Phase 2 done when:** 2.1–2.4 pass and a full upload → profile → clean →
approve → versioned-output cycle works end to end for at least the generic playbook.

---

## Phase 3 — Data Quality Score & PII Masking Depth
**Goal:** the deterministic quality score and the asymmetric-threshold PII
masking behavior are correct and match the resolved design decisions.

### 3.1 — Data quality score
**Files touched:** `src/shared/quality_score/`
**Work:** composite score (completeness, validity, uniqueness, consistency),
pure computation, no LLM.
**Testing:** compute the score on a known-clean dataset (expect high score)
and a deliberately corrupted copy of the same dataset (expect materially lower score).
**Passing criteria:** the corrupted copy scores lower on every sub-component
that was actually corrupted, and the score is reproducible (same input →
same output, no LLM non-determinism involved).

### 3.2 — PII flag/mask thresholds
**Files touched:** `src/shared/pii/`
**Work:** apply the resolved asymmetric thresholds — flag at confidence
~0.40, auto-mask only above ~0.90.
**Testing:** run against a dataset with PII instances spanning a range of
detector confidence scores (borderline and clear-cut cases).
**Passing criteria:** borderline instances (confidence between 0.40 and 0.90)
are flagged for human review but never auto-masked; only high-confidence
(>0.90) instances are auto-masked; nothing below 0.40 is flagged (verify false
positive rate stays low on clean text).

**Phase 3 done when:** 3.1–3.2 pass and both scores/flags surface correctly in
the frontend dashboard.

---

## Phase 4 — Summary + Hybrid RAG & Chat (Agent 3)
**Goal:** chunking, embedding, structured-lookup bypass, and the chat
interface that never hallucinates a computable number.

### 4.1 — Chunking & embedding
**Files touched:** `src/agents/summary_rag/chunking/`
**Work:** dataset-level, column-level, relationship-level chunks per the
three-tier scheme; embed for dense retrieval; BM25/tsvector index for sparse.
**Testing:** ingest a cleaned dataset and inspect the generated chunks
manually for a handful of columns and relationships.
**Passing criteria:** every column has exactly one self-contained chunk
containing its cleaning actions and flagged issues; relationship chunks only
include correlations above the configured threshold, not every pair.

### 4.2 — Retrieval fusion (RRF)
**Files touched:** `src/agents/summary_rag/retrieval/`
**Work:** reciprocal rank fusion across sparse + dense retrieval.
**Testing:** run a mixed query set — exact column-name queries, numeric
literal queries, and paraphrased semantic queries — and inspect top-k results.
**Passing criteria:** exact-name/numeric queries are dominated by sparse
results, paraphrased queries by dense, and RRF surfaces a sensible blend
without a hand-tuned weight per query type.

### 4.3 — Intent classifier + structured-lookup bypass
**Files touched:** `src/agents/summary_rag/intent/`
**Work:** rule-based first pass (column-name + aggregate-verb match → lookup;
no match + dataset-referential phrasing → RAG; both → hybrid), LLM escalation
only for genuinely ambiguous cases.
**Testing:** run the four resolved-decision test cases from the original plan
(exact aggregate question, general dataset question, "why/trend" question,
and a genuinely ambiguous one) and confirm routing.
**Passing criteria:** "what's the mean of column X" never goes through the
LLM for the number itself — the LLM only phrases an answer already fetched
from Postgres; genuinely ambiguous cases are the only ones triggering an
LLM-based classifier call.

### 4.4 — Chat interface (frontend + API)
**Files touched:** `src/frontend/chat/`, `src/api/chat/`
**Work:** wire the intent classifier + retrieval + Gemini into a chat UI.
**Testing:** manual QA session asking 20+ real questions against a real
cleaned dataset, spot-checking every numeric answer against ground truth.
**Passing criteria:** zero incorrect numeric answers across the QA session;
every answer sourced from lookup/RAG is traceable back to its source chunk or
DB value in logs.

**Phase 4 done when:** 4.1–4.4 pass and a user can chat naturally about a
cleaned dataset with grounded, verifiable answers.

---

## Phase 5 — Report Generation & Notebook Export (Agent 4)
**Goal:** a complete, professional report and a reproducible notebook from
any completed run.

### 5.1 — Report templating
**Files touched:** `src/agents/report_gen/`
**Work:** Jinja2/Pandoc or python-docx templates combining cleaning log +
summary/insights + chart specs; one LLM call for the executive summary only.
**Testing:** generate docx/pdf/markdown reports for 3 different datasets of
varying size/domain.
**Passing criteria:** all three formats render without broken sections;
exactly one LLM call is made per report (verified in trace/cost logs), not
one per section; the report displays its `built_from` dataset/playbook version.

### 5.2 — Chart specs / visualization engine
**Files touched:** `src/agents/report_gen/charts/` (or shared viz module)
**Work:** rule-based chart-type selection + LLM judgment for final picks, per
the 0.60 confidence threshold for viz decisions.
**Testing:** run against columns of each dtype/shape (categorical, skewed
numeric, time series, high-cardinality) and inspect chosen chart types.
**Passing criteria:** chart-type choices are sensible for at least 9/10 test
columns; low-confidence picks are still applied (viz mistakes are cheap per
the resolved threshold) without blocking report generation.

### 5.3 — Jupyter notebook export
**Files touched:** `src/agents/report_gen/notebook_export/`
**Work:** generate one cell per applied playbook step from the approved
action log, using actual chosen parameters — not the LLM's reasoning text.
**Testing:** export a notebook from a completed run and actually execute it
top-to-bottom against the original raw dataset.
**Passing criteria:** executing the notebook reproduces the same cleaned
dataset (byte-for-byte or statistically identical) that the approval flow produced.

**Phase 5 done when:** 5.1–5.3 pass and a user can download a report and a
working notebook from any completed, approved run.

---

## Phase 6 — Extras: Domain Playbooks, Drift, Quality Narrative (Agent 5)
**Goal:** the monetizable domain-pack layer and drift detection.

### 6.1 — E-commerce domain playbook pack
**Files touched:** `playbooks/ecommerce/`
**Work:** extend/override generic playbooks for e-commerce schema patterns
(orders, SKUs, pricing, returns), per the resolved ship order (e-commerce first).
**Testing:** run against 3+ public Kaggle e-commerce datasets.
**Passing criteria:** the e-commerce pack produces materially different (and
more appropriate) cleaning suggestions than the generic pack on at least one
column type per dataset (e.g. SKU-aware dedup logic vs generic dedup).

### 6.2 — Finance domain playbook pack
**Files touched:** `playbooks/finance/`
**Work:** currency/unit edge-case handling, per the resolved ship order
(finance second).
**Testing:** run against datasets with mixed currencies/units.
**Passing criteria:** currency/unit mismatches are correctly flagged and
handled per playbook rules, not silently averaged/summed across units.

### 6.3 — Drift detection
**Files touched:** `src/agents/extras/drift/`
**Work:** detect structural/statistical change on re-upload of the same source.
**Testing:** upload a dataset, then re-upload a deliberately modified version
(added column, shifted distribution) as the "same source."
**Passing criteria:** both the structural change (added column) and the
statistical drift (shifted distribution) are correctly detected and narrated.

### 6.4 — Survey domain playbook pack (deferred candidate)
**Files touched:** `playbooks/survey/`
**Work:** Likert scales, skip logic — only start once 6.1–6.3 are proven, per
the resolved decision to defer survey until the engine is validated on
simpler domains.
**Testing:** run against a public survey dataset with skip-logic columns.
**Passing criteria:** skip-logic-induced "missingness" is correctly
distinguished from genuine missing data (not treated identically by the
imputation playbook).

**Phase 6 done when:** at minimum 6.1–6.3 pass; 6.4 can slip to a later
release without blocking the rest of the product.

---

## Phase 7 — Connectors, BI Export & Frontend Polish
**Goal:** round out ingestion/export beyond file upload and finish the
dashboard experience.

### 7.1 — Ingestion connectors
**Files touched:** `src/shared/connectors/`
**Work:** Google Sheets, S3, Postgres ingestion adapters.
**Testing:** ingest a real dataset through each of the three connectors.
**Passing criteria:** each connector produces a dataset row identical in
shape/behavior to a file-upload-ingested dataset (same downstream pipeline
handles it with no special-casing).

### 7.2 — BI export
**Files touched:** `src/shared/connectors/export/`
**Work:** PowerBI/Tableau/Looker Studio handoff.
**Testing:** export a cleaned dataset + report artifacts to each target and
open the result in the actual BI tool.
**Passing criteria:** exported data opens correctly in all three tools with
no manual reformatting required.

### 7.3 — Data quality dashboard & UX polish
**Files touched:** `src/frontend/dashboard/`
**Work:** finish the data quality dashboard, approval UI polish, report
viewer polish.
**Testing:** full manual walkthrough of the entire user journey (search/
upload → clean → approve → chat → report → export) by someone who hasn't
built the feature.
**Passing criteria:** the walkthrough completes with no dead ends, unclear
states, or silent failures; every async/long-running step has visible
progress or status.

**Phase 7 done when:** 7.1–7.3 pass and the product is usable end-to-end by a
new user without developer assistance.

---

## Phase 8 — Jev Evaluation, Hardening & Observability
**Goal:** validate the Jev evaluation, close out observability gaps, and
harden for real usage before wider release.

### 8.1 — Jev benchmark vs Gemini
**Files touched:** `src/shared/llm/`, `playbooks/generic/`
**Work:** prototype Jev against 2–3 existing `llm_choice` points (start with
imputation strategy selection); compare choices/confidence against Gemini on
identical inputs.
**Testing:** run both providers on an identical batch of `llm_choice`
decisions across multiple datasets; log agreement rate, confidence
calibration, latency, and actual (not vendor-quoted) cost.
**Passing criteria:** a documented comparison exists in `docs/decisions.md`
with real numbers (not vendor claims) before any decision to adopt Jev more
broadly is made.

### 8.2 — Confidence threshold validation
**Files touched:** `src/shared/playbooks/`
**Work:** validate the resolved thresholds (cleaning 0.80, viz 0.60, PII flag
0.40/mask 0.90) against real usage data once enough runs exist.
**Testing:** review a sample of low-confidence-routed-to-human decisions and
a sample of auto-approved decisions for correctness.
**Passing criteria:** auto-approved decisions show a materially lower error
rate than the pre-threshold baseline; thresholds are adjusted (and the change
logged in `docs/decisions.md`) if data suggests they're miscalibrated.

### 8.3 — Observability & job-queue pain check
**Files touched:** `src/shared/queue/`, tracing config
**Work:** confirm OpenTelemetry coverage across all agents; assess whether
hand-rolled `pending_approvals` retry/resume logic is showing real pain
(per the resolved "migrate to Temporal/Prefect only on concrete pain signal" policy).
**Testing:** review traces for gaps; review incident/debug log for recurring
`pending_approvals` issues.
**Passing criteria:** every agent call and approval-gate transition is
traceable end-to-end; a documented go/no-go decision on Temporal/Prefect
migration exists in `docs/decisions.md`, not left implicit.

**Phase 8 done when:** 8.1–8.3 pass. This closes the initial build; further
phases are additive (v2 PII/NER, more domain packs, etc.) and should be
appended below rather than inserted.

---
**Next:** Return to [`context.md`](../context.md).
