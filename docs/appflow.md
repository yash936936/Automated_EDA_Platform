# App Flow — Automated EDA, Cleaning & Visualization Platform

> The user-facing journey through the app, screen by screen. Written from the
> design doc's product features; update as the frontend is actually built.

## 1. Get a dataset in
- **Upload:** drag-and-drop a file → progress indicator → dataset appears in
  the user's dataset list once ingestion + PII pre-scan complete.
- **Kaggle search:** type a natural-language query → candidate datasets shown
  with metadata → user picks one → same ingestion pipeline as upload.
- **Connector:** connect Google Sheets/S3/Postgres → pick a source → same
  ingestion pipeline.

## 2. Automatic profiling + PII flags
- On ingestion, the user lands on a dataset overview screen: deterministic
  profiling summary (types, missingness, distributions, correlations at a
  glance) and any PII flags surfaced prominently, before any cleaning starts.

## 3. Choose review mode
- User picks **batch review** or **step-by-step review** for this run
  (per-project default can be set, but is overridable per run).

## 4. Cleaning proposal review
- **Batch mode:** a diff-style list of every proposed action — column,
  action, before/after sample, confidence, reasoning. User can bulk-accept
  above a confidence threshold, or go action-by-action: approve / edit
  (override to another valid choice) / reject.
- **Step-by-step mode:** the run pauses live at each risky action
  (drop_column, drop_rows, low-confidence choices) and asks before continuing;
  everything else proceeds automatically.
- Every action shows: what will change, why, blast radius (rows/columns
  affected), and a one-click override.

## 5. Data quality dashboard
- Composite quality score (completeness, validity, uniqueness, consistency)
  updates as the cleaning run completes, with an explanation of what's
  driving the score (Agent 5 narrative).

## 6. Chat with the dataset
- Natural-language Q&A box grounded in the cleaned dataset. Exact-value
  questions get instant, DB-backed answers; open-ended questions get RAG-
  grounded answers with visible source chunks the user can inspect.

## 7. Report + notebook
- One-click generation of a docx/pdf/markdown report combining summary,
  charts, and narrative, always labeled with its `built_from` dataset/
  playbook version.
- One-click export of a Jupyter notebook reproducing the exact cleaning run.
- If the underlying cleaning decisions have since changed, the report/notebook
  view shows a "based on cleaning v3 — N changes made since" banner (per the
  project's stale-handling policy).

## 8. Export downstream
- Send the cleaned dataset/report to PowerBI, Tableau, or Looker Studio.

## 9. Domain playbook packs (monetization surface)
- User can select a domain pack (e-commerce, finance, survey once available)
  for a project, which swaps in specialized cleaning/viz rules on top of the
  generic playbook.

## Re-upload / drift flow
- Re-uploading a file recognized as "the same source" (per Agent 5's drift
  detection) surfaces a drift report instead of treating it as a brand-new,
  unrelated dataset — structural and statistical changes since the last
  version are narrated.

---
**Next:** Return to [`context.md`](../context.md).
