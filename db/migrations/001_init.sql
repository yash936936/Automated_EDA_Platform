-- Phase 0.2: core schema for datasets, versioning, cleaning audit log,
-- pending approvals, and playbook definitions.

CREATE TABLE IF NOT EXISTS datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    source TEXT NOT NULL,             -- 'upload' | 'kaggle' | 'gsheets' | 's3' | 'postgres'
    storage_path TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS playbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    playbook_id TEXT NOT NULL,        -- e.g. 'cleaning.missing_values.v1'
    domain TEXT NOT NULL DEFAULT 'generic',
    version INT NOT NULL,
    definition JSONB NOT NULL,        -- full YAML/JSON playbook, parsed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (playbook_id, version)
);

-- One row per completed/attempted cleaning run.
CREATE TABLE IF NOT EXISTS cleaning_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES datasets(id),
    playbook_id UUID NOT NULL REFERENCES playbooks(id),
    review_mode TEXT NOT NULL DEFAULT 'batch',  -- 'batch' | 'step_by_step'
    status TEXT NOT NULL DEFAULT 'running',     -- running | awaiting_approval | completed | failed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Content-addressed dataset versions: each is tied to an exact set of
-- approved/overridden action IDs (see cleaning_actions.action_id).
CREATE TABLE IF NOT EXISTS dataset_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES datasets(id),
    version_number INT NOT NULL,
    cleaning_run_id UUID NOT NULL REFERENCES cleaning_runs(id),
    action_ids UUID[] NOT NULL,        -- exact set that produced this version
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, version_number)
);

-- Every proposed cleaning/imputation action. State machine:
-- proposed -> approved | rejected | auto_approved.
-- Nothing here mutates the dataset by itself -- Agent 2 always works on a
-- copy, and only approved/auto_approved actions are ever applied.
CREATE TABLE IF NOT EXISTS cleaning_actions (
    action_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cleaning_run_id UUID NOT NULL REFERENCES cleaning_runs(id),
    step_id TEXT NOT NULL,             -- playbook step_id, e.g. 'select_imputation_strategy'
    column_name TEXT,
    action_type TEXT NOT NULL,         -- e.g. 'impute_median', 'drop_column'
    before_sample JSONB,
    after_sample JSONB,
    reasoning TEXT,
    confidence NUMERIC(4,3),
    status TEXT NOT NULL DEFAULT 'proposed',  -- proposed|approved|rejected|auto_approved
    overridden_to TEXT,                -- if user picked a different valid choice
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pause/resume mechanics for human review (Phase 0.3). A row here means a
-- job has exited and is waiting -- no worker is held open.
CREATE TABLE IF NOT EXISTS pending_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cleaning_run_id UUID NOT NULL REFERENCES cleaning_runs(id),
    step_id TEXT NOT NULL,
    action_ids UUID[] NOT NULL,        -- actions awaiting a decision at this gate
    status TEXT NOT NULL DEFAULT 'awaiting_approval', -- awaiting_approval|resolved
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- Dependency graph for downstream staleness (summary/report built_from a
-- specific dataset_version). Phase 2.4 uses this; created now so the schema
-- is stable from Phase 0.
CREATE TABLE IF NOT EXISTS downstream_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_type TEXT NOT NULL,       -- 'summary' | 'report' | 'notebook'
    dataset_version_id UUID NOT NULL REFERENCES dataset_versions(id),
    status TEXT NOT NULL DEFAULT 'current', -- current | stale
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE EXTENSION IF NOT EXISTS pgcrypto; -- for gen_random_uuid()
