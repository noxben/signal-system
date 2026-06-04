-- ============================================================
-- 006_add_outcome_source.sql
-- Adds 'outcome' as a tracked source in source_health.
-- Run in Supabase SQL editor.
-- ============================================================

-- Drop and recreate the check constraint to include 'outcome'
ALTER TABLE source_health
    DROP CONSTRAINT IF EXISTS chk_source_name;

ALTER TABLE source_health
    ADD CONSTRAINT chk_source_name CHECK (
        source IN ('market', 'news', 'political', 'options_proxy', 'outcome')
    );

-- Seed the outcome row
INSERT INTO source_health (source, status, consecutive_failures)
VALUES ('outcome', 'healthy', 0)
ON CONFLICT (source) DO NOTHING;
