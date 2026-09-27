-- Phase 1.1: columns needed for the upload -> object storage -> async
-- ingestion pipeline. `status` tracks the dataset through
-- 'ingesting' -> 'ready' | 'failed' while Agent-adjacent metadata (size,
-- row/column counts, checksum) is computed off the request thread by the
-- 'ingest_dataset' queue job, not synchronously in the upload handler.

ALTER TABLE datasets
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ready',
    -- 'ready' default keeps this backward-compatible with any row inserted
    -- before this migration existed; every new upload sets it explicitly.
    ADD COLUMN IF NOT EXISTS original_filename TEXT,
    ADD COLUMN IF NOT EXISTS mime_type TEXT,
    ADD COLUMN IF NOT EXISTS size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS row_count BIGINT,
    ADD COLUMN IF NOT EXISTS column_count INT,
    ADD COLUMN IF NOT EXISTS checksum_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Constrain status to the known state machine (ingesting -> ready|failed)
-- rather than leaving it a free-text field open to typos.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'datasets_status_check'
    ) THEN
        ALTER TABLE datasets
            ADD CONSTRAINT datasets_status_check
            CHECK (status IN ('ingesting', 'ready', 'failed'));
    END IF;
END $$;
