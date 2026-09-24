# Automated EDA, Cleaning & Visualization Platform

A web platform that automates exploratory data analysis, data cleaning,
visualization, and reporting on user-uploaded or imported datasets — with a
strict **automation proposes, the user approves** design: nothing touches
your data without an explicit, logged approval, and every decision is
reversible and auditable.

> **Status: pre-build.** Architecture and phased build plan are finalized
> (see `docs/`); no code has been written yet. This README will be updated as
> phases complete to reflect real, working capabilities — not aspirational ones.

## What it does (once built)
- Upload a file or search/import a dataset from Kaggle.
- Get automated, deterministic EDA (types, missingness, distributions,
  correlations) with no LLM guesswork on the numbers.
- Review every proposed cleaning action as a diff — approve, edit, or reject,
  in batch or step-by-step — before anything is applied.
- Chat with your dataset in natural language, with exact-value answers always
  backed by a direct lookup, never an LLM-recalled number.
- Get a compiled report (docx/pdf/markdown) and a reproducible Jupyter
  notebook of the exact cleaning run.
- Every version of your cleaned dataset and every downstream artifact is
  tracked, so you always know what a report is "based on."

## Stack
Python (pandas/polars/DuckDB) for the data/agent layer; Node.js/TypeScript
for the API gateway and frontend; Postgres; BullMQ/Celery for job
orchestration; Gemini as the v1 LLM behind a provider-agnostic interface.

## Docs
See `context.md` for the full documentation map (PRD, TRD, architecture,
phased build plan, decisions log, and more).

---
*Updated automatically at the end of each completed phase — see
`docs/phases.md` for current progress.*
