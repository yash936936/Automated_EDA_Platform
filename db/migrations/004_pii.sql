-- Phase 1.3: PII pre-scan results (D-007: emails, phones, national IDs; regex only).
-- NEVER stores raw PII values -- only where it was found and how sure we are.

-- Existing rows (ingested before this scan existed) get 'legacy_unscanned'
-- via the column default at ADD time; new rows then default to 'pending'.
ALTER TABLE datasets
    ADD COLUMN IF NOT EXISTS pii_status TEXT NOT NULL DEFAULT 'legacy_unscanned',
    ADD COLUMN IF NOT EXISTS pii_scanned_rows BIGINT,
    ADD COLUMN IF NOT EXISTS pii_truncated BOOLEAN;
ALTER TABLE datasets ALTER COLUMN pii_status SET DEFAULT 'pending';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'datasets_pii_status_check') THEN
        ALTER TABLE datasets ADD CONSTRAINT datasets_pii_status_check
            CHECK (pii_status IN ('pending', 'scanned', 'skipped_unsupported', 'legacy_unscanned'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS pii_findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    column_index INT NOT NULL,
    column_name TEXT NOT NULL,
    detector TEXT NOT NULL,          -- e.g. email, phone_formatted, aadhaar, pan, ssn
    pii_type TEXT NOT NULL,          -- email | phone | national_id
    match_count BIGINT NOT NULL,
    scanned_values BIGINT NOT NULL,  -- non-empty cells in the column that were examined
    match_rate DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    header_hint BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pii_findings_dataset_idx ON pii_findings (dataset_id);
