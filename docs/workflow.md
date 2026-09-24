# Dev Workflow — Automated EDA, Cleaning & Visualization Platform

> How work moves across tools (Claude, Obsidian, opencode, VS Code) so
> everyone/everything reads from the same ground truth. This file describes
> the *process*, not the product.

## Ground truth
`context.md` + the files in `docs/` are the single source of truth for
project state, decisions, and history — not any single tool's memory or
chat history. Any agent (Claude, opencode, etc.) starting a session reads
`context.md` first, then `docs/status.md` for current state, before writing code.

## Session start checklist (for any coding agent)
1. Read `context.md`.
2. Read `docs/status.md` — what phase, what happened last session.
3. Read the relevant sub-phase in `docs/phases.md` for what's next.
4. Skim `docs/decisions.md` for anything relevant to the task at hand — don't
   re-litigate a resolved decision without flagging it explicitly.
5. Do the work.
6. Log to `docs/debug.md` (testing/results) and `docs/decisions.md` (if any
   new decision was made) before ending the session.
7. Update `docs/status.md`.
8. If a full phase completed, update `docs/readme.md`.

## Tool roles
- **Claude (this session / claude.ai project):** primary design, planning,
  cross-cutting review, and doc maintenance. Also used for implementation
  when working directly in chat/artifacts.
- **opencode / VS Code / JetBrains (Claude Code or similar):** primary
  implementation environment for actual source files once scaffolding exists.
- **Obsidian:** human-facing view onto the same `docs/` folder — no separate
  copy, same files, so edits made by any agent are immediately visible.

## Conventions
- Never edit `docs/decisions.md` or `docs/debug.md` entries after the fact —
  append a new entry that supersedes/corrects, and reference the old one.
- `docs/phases.md` checkboxes only get checked after the stated **Testing**
  step actually ran and **Passing criteria** were met.
- Keep `docs/architecture.md`'s file tree in sync with `src/` as things are
  scaffolded — it's a living document, not a one-time snapshot.
- Cross-language boundary (Python agents / Node API+frontend) changes always
  get a `docs/decisions.md` entry — this is the seam most likely to grow
  inconsistent conventions on each side if undocumented.

## Open process items
- Root folder path not yet set — update `context.md` and this file's tool
  paths once decided.
- Repo layout: monorepo vs. separate repos for the Node and Python services —
  `(open — confirm with user)`, log as a decision once resolved (affects the
  workflow checklist above).

---
**Next:** Return to [`context.md`](../context.md).
