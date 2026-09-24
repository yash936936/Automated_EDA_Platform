# Code Logic — Automated EDA, Cleaning & Visualization Platform

> Explains non-obvious logic and algorithms. Not a restatement of
> `docs/architecture.md` — this is for the *why does this specific piece of
> code work this way* questions. Fill in each section as the corresponding
> phase is built; this file starts as scaffolding based on the design doc.

## Playbook engine step execution (Phase 2.2)
Each playbook step declares a `type` up front (`deterministic` / `llm_choice`
/ `llm_freeform`), which makes cost/latency predictable per run *before*
execution starts — the engine can sum expected LLM calls across a playbook
without running it. `llm_choice` steps carry `choices`, `choice_criteria` (a
plain-language description of when each choice applies, handed to the LLM/Jev
as context), `confidence_threshold`, and a deterministic `fallback`. The
engine's contract: **the pipeline never hard-fails on an LLM/API hiccup** —
if the provider call errors or times out, the `fallback` value is applied and
logged as a fallback (not as a normal LLM decision), so audit trails can
distinguish "LLM chose X" from "LLM failed, fallback applied X."
`(To be expanded once the actual executor code exists — this is the intended
contract, not yet verified against an implementation.)`

## Context field whitelisting (privacy boundary)
`context_fields` in a playbook step is not just documentation — it's meant to
be enforced as the literal, sole set of fields serialized into the LLM
request payload for that step. Raw rows are never sent, only the named
per-column/per-dataset statistics. This is the actual privacy boundary
between the dataset and any LLM provider, not the PII scanner (the PII
scanner catches problems in what's whitelisted; the whitelist itself is what
keeps raw data server-side). `(Implementation note: enforce this at the LLM
interface layer — `src/shared/llm/` — so a bug in a playbook definition can't
accidentally widen what's sent; don't rely on playbook authors getting it
right by convention.)`

## Content-addressed versioning (`dataset_v{n}`)
A version is defined by the exact set of approved/overridden action IDs that
produced it — not by a timestamp or a diff against the previous version. This
means two runs that happen to approve the identical set of actions would (in
principle) be content-identical, which is why diffing `v3` vs `v4` at the
column level is cheap: it's a set difference on action IDs, not a full
data-level diff, and only the columns touched by the differing actions need
re-embedding/re-summarizing downstream.

## Structured-lookup bypass for chat
The intent classifier is a rule-based first pass specifically so that the
*common* case (an exact aggregate question against a known column) never
touches an LLM for the numeric value itself — only for phrasing the answer
around a value already read from Postgres. This is described in the design
doc as "the single biggest lever against hallucinated stats," which means the
implementation detail that matters most here isn't the classifier's
sophistication — it's that the numeric answer path structurally cannot
originate from the LLM, even if the classifier misfires and the LLM is
consulted anyway (the value it's given should always come pre-computed).

## Hybrid retrieval fusion (RRF)
Reciprocal rank fusion was chosen over a hand-tuned weighted blend of sparse/
dense scores specifically to avoid needing a per-query-type weight that would
require ongoing tuning. `(To be expanded with the actual RRF constant/
implementation once Phase 4.2 is built — note here if empirical tuning ends
up needed despite the initial rationale, and log that as a decision if so.)`

---
**Next:** Return to [`context.md`](../context.md).
