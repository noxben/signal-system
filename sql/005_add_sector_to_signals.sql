-- ============================================================
-- 005_add_sector_to_signals.sql
-- Safe to run multiple times (IF NOT EXISTS guard).
-- Run in Supabase SQL editor if you applied 001 before this.
-- ============================================================

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS sector varchar(30);

-- Backfill is not needed — all future rows will have it set by the engine.
