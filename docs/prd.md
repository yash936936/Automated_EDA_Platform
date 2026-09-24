# PRD — Automated EDA, Cleaning & Visualization Platform

## Problem
Analysts, data scientists, and non-technical business users routinely spend
disproportionate time on the mechanical front-end of data work — profiling a
new dataset, spotting and fixing data quality issues, picking sensible charts,
and writing up findings — before they can get to actual insight. Existing
automated-EDA tools (ydata-profiling, Sweetviz) only profile; others
(PandasAI, Julius) chat over data but don't give a transparent, auditable
cleaning pipeline. Nobody in the space combines automated cleaning *with*
mandatory human approval and full reproducibility.

## Goals
- Let a user go from raw dataset (upload or Kaggle import) to a reviewed,
  cleaned dataset + full report in minutes, not hours.
- Make every automated decision (imputation, drop, mask) visible, explained,
  and reversible before it touches the data.
- Support a natural-language chat interface over the dataset that never
  hallucinates a number it could have looked up.
- Produce a shareable, professional report (docx/pdf/markdown) and a
  reproducible Jupyter notebook from every cleaning run.
- Build a foundation that supports paid domain playbook packs
  (e-commerce, finance, survey) as a monetization lever.

## Non-goals (v1)
- Not a full data-governance/compliance PII platform — PII handling is
  "detect and warn/mask" (emails, phones, national ID patterns only), not a
  broad NER-based compliance suite.
- Not a general BI/dashboarding tool — visualization is about the automated
  narrative and export, not an interactive dashboard builder to rival
  PowerBI/Tableau (those are export *targets*, not competitors to replicate).
- Not adopting Jev (constrained-decision model) pipeline-wide — it's a v1
  evaluation against Gemini on 2–3 choice points only.
- Not migrating off BullMQ/Celery to Temporal/Prefect preemptively.
- Names/free-text PII detection (needs NER) — deferred to v2.

## Users / use cases
- **Analyst/data scientist** uploading a messy CSV who wants a fast, trustworthy
  first pass at cleaning + EDA, with full control to override any decision.
- **Non-technical business user** who wants a plain-English report and chat
  interface over a dataset without writing code.
- **Technical user** who wants the audit trail as an executable Jupyter
  notebook they can keep iterating on.
- **Team lead** who wants a domain playbook pack (e.g. e-commerce) applied
  consistently across recurring dataset drops.

## Success criteria
- A user can go upload → cleaned dataset → report with zero required code.
- Zero cases of the dataset being modified without an explicit approve action
  logged against it (verifiable via the audit/versioning log).
- Chat answers to "what's the mean of column X"-style questions are always
  backed by a structured DB lookup, never an LLM-recalled number (spot-checkable
  in the response's grounding metadata).
- Every generated report links back to the exact playbook version and dataset
  version (`built_from`) that produced it.
- A rejected/overridden cleaning decision never silently breaks downstream
  report/summary — it's flagged `stale` per the versioning policy in
  `docs/architecture.md` §Versioning.

## Constraints
- v1 LLM provider: Gemini, via API key, behind a provider-agnostic interface.
- Multiple API keys, one per agent (Discovery, EDA/Clean, RAG/Summary, Report
  Gen, Extras) for cost attribution and rate-limit isolation.
- Stack: Python for agents/data (pandas/polars/DuckDB); Node.js/TypeScript for
  API gateway + frontend.
- Job orchestration stays on BullMQ/Celery until a concrete pain signal
  appears (see `docs/decisions.md`).
- Root folder path: `(open — confirm with user)`.

---
**Next:** Return to [`context.md`](../context.md).
