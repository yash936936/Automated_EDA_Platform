# Context — Automated EDA, Cleaning & Visualization Platform

> Entry point. Read this file first, every session, before touching code or
> any other doc. If you (the agent — Claude, opencode, etc.) jumped straight
> into another file, stop and come back here.

## What this project is
A web platform where users upload or import a dataset (via Kaggle search, file
upload, or connectors like Google Sheets/S3/Postgres) and the system automates
exploratory data analysis, data cleaning, visualization generation, a
natural-language chat interface over the dataset, and a downloadable report
(docx/pdf/markdown/Jupyter notebook). Core principle: **automation proposes,
the user approves** — no silent modification of data, every AI decision is
logged, versioned, and reversible. Current stage: pre-build, documentation and
architecture finalized, no code written yet.

Full product/architecture reasoning lives in `docs/prd.md`, `docs/trd.md`, and
`docs/architecture.md` — this file is only the router.

## Root folder
`(open — confirm with user)` — no disk path set yet. Update this line (and the
folder tree below, if it changes) the moment the project has a real home on
disk, so Obsidian/opencode/VS Code/Claude all point at the same root.

## Folder structure
```
<project-root>/
├── context.md          ← you are here
├── docs/                the files below
│   ├── prd.md            product requirements — what & why
│   ├── trd.md            technical requirements — how, constraints
│   ├── architecture.md   full system/file structure — the map
│   ├── phases.md         build order, phase by phase, with sub-phases +
│   │                     testing/passing criteria for each
│   ├── decisions.md      append-only log of decisions made
│   ├── debug.md          append-only log of bugs found & fixed
│   ├── code_logic.md     non-obvious logic/algorithms explained
│   ├── appflow.md        user-facing flow through the app
│   ├── workflow.md       dev workflow across Claude/Obsidian/opencode/VS Code
│   ├── readme.md         public-facing readme, updated as phases complete
│   └── status.md         current phase, last debug, last decisions — log every run
└── src/                  actual code (not yet created)
    ├── agents/           Discovery, EDA/Clean, RAG/Summary, Report Gen, Extras
    ├── api/               API gateway (Node/TypeScript)
    ├── frontend/          Node/TypeScript client
    └── shared/            playbook schema, provider-agnostic LLM interface, etc.
```

## Where to look, by task
| I need to...                                  | Read this first                     |
|------------------------------------------------|--------------------------------------|
| Understand the product                          | `docs/prd.md`                        |
| Understand technical constraints                | `docs/trd.md`                        |
| Understand the file/system layout               | `docs/architecture.md`               |
| Know what to build next                         | `docs/phases.md` + `docs/status.md`  |
| Understand a tricky piece of logic              | `docs/code_logic.md`                 |
| Understand how a user moves through it          | `docs/appflow.md`                    |
| Know the dev process/tooling loop               | `docs/workflow.md`                   |
| See past decisions before changing something    | `docs/decisions.md`                  |
| See what broke before and how it was fixed      | `docs/debug.md`                      |
| Know current state before starting work         | `docs/status.md`                     |

## Logging rules (every agent must follow these)
- Finished a coding task → append to `docs/debug.md` (what you tested, what
  broke, what you fixed) even if nothing broke ("no issues found").
- Made a design/implementation decision → append to `docs/decisions.md` with
  an ID (`D-00N`), what was decided, and why (alternatives considered if any).
- End of every work session/run → update `docs/status.md`: current phase,
  what changed, what's next.
- Completed a phase or sub-phase → check it off in `docs/phases.md` only
  after its stated **testing** step has actually been run and its **passing
  criteria** are met — not before. Update `docs/readme.md` when a full phase
  (not just a sub-phase) completes, to reflect current real capabilities.

## Standing constraints (do not re-litigate without explicit user request)
- LLM calls only at genuine judgment points (playbook `llm_choice` branches,
  narrative generation). Deterministic stats/profiling stay in pandas/polars/DuckDB.
- Separate API keys per agent for cost attribution and independent rate-limit
  tuning — not for parallelism. Job-queue concurrency limits handle isolation.
- Gemini is the v1 LLM. Jev (TypeSafe AI) is being evaluated for constrained-
  choice steps only, not adopted pipeline-wide.
- Every cleaning/imputation action is diffable, reversible, and logged. No
  silent data modification, ever.
- Stack: Python for agents/data/ML work (pandas/polars/DuckDB, playbook
  engine, RAG); Node.js/TypeScript for the API gateway and frontend.

## Next task
Start at **Phase 0 — Foundation & Infra**, sub-phase 0.1, in `docs/phases.md`.
Nothing has been built yet.
