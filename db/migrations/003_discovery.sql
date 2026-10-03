-- Phase 1.2: Kaggle discovery + import.
-- source_ref holds the Kaggle dataset ref ("owner/slug") for source='kaggle'.
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_ref TEXT;

-- Idempotent import: one live (non-failed) dataset per Kaggle ref+file.
-- Also closes the double-click race -- the second concurrent INSERT hits a
-- unique violation instead of creating a duplicate dataset.
CREATE UNIQUE INDEX IF NOT EXISTS datasets_kaggle_ref_file_uniq
    ON datasets (source_ref, original_filename)
    WHERE source = 'kaggle' AND status <> 'failed';

-- Search cache (Agent 1): normalized query -> fused results. TTL is enforced
-- in code (per-row ttlHours inside payload), not by a DB job.
CREATE TABLE IF NOT EXISTS kaggle_search_cache (
    query_key TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
