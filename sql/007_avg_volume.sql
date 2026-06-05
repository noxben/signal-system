-- ============================================================
-- 007_avg_volume.sql
-- True 20-day average volume per ticker, updated daily.
-- Signal engine reads from here for volume spike detection.
-- ============================================================

CREATE TABLE avg_volume (
    ticker          varchar(10)   PRIMARY KEY,
    avg_volume_20d  bigint        NOT NULL,
    computed_at     timestamptz   NOT NULL DEFAULT now()
);

-- Seed with zeros so signal engine doesn't fail on first run.
-- avg_volume_worker will populate correct values at 09:35 ET on first market day.
