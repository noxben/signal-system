-- ============================================================
-- 004_political_events.sql
-- Congressional trades, gov contracts, lobbying from Quiver
-- Run after 001, 002, 003
-- ============================================================

CREATE TABLE political_events (
    id             bigserial       PRIMARY KEY,
    ticker         varchar(10)     NOT NULL,
    sector         varchar(30),
    event_type     varchar(20)     NOT NULL,    -- 'congress' | 'contracts' | 'lobbying'
    size_value     numeric(16,2),               -- dollar amount where available
    reported_date  date,                        -- date from Quiver (may lag up to 45 days)
    raw_json       jsonb           NOT NULL,    -- full Quiver row for debugging
    ingested_at    timestamptz     NOT NULL DEFAULT now(),

    CONSTRAINT chk_political_event_type CHECK (
        event_type IN ('congress', 'contracts', 'lobbying')
    )
);

-- Signal engine queries: "any political event for sector X in last 24 hours?"
CREATE INDEX idx_political_ticker      ON political_events (ticker);
CREATE INDEX idx_political_sector      ON political_events (sector);
CREATE INDEX idx_political_ingested_at ON political_events (ingested_at DESC);
CREATE INDEX idx_political_event_type  ON political_events (event_type);

-- Composite: sector alignment query (§6 Signal B)
CREATE INDEX idx_political_sector_time ON political_events (sector, ingested_at DESC);

-- Retention: 90 days (congressional lag means older data still has signal value)
-- DELETE FROM political_events WHERE ingested_at < now() - interval '90 days';
