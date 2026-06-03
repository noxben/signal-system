-- ============================================================
-- schema_market_data.sql
-- Addendum to schema.sql — raw market snapshots from yfinance
-- Run after schema.sql
-- ============================================================

CREATE TABLE market_data (
    id              bigserial       PRIMARY KEY,
    ticker          varchar(10)     NOT NULL,
    price           numeric(12,4)   NOT NULL,
    volume          bigint          NOT NULL,
    avg_volume_20d  bigint          NOT NULL,
    pct_change      numeric(8,4)    NOT NULL,
    ingested_at     timestamptz     NOT NULL DEFAULT now()
);

-- Signal engine queries latest snapshot per ticker
CREATE INDEX idx_market_data_ticker_time ON market_data (ticker, ingested_at DESC);

-- Retention: keep only last 7 days of raw snapshots (§18 — no backtesting needed)
-- Run via a daily cron or outcome_worker cleanup step:
-- DELETE FROM market_data WHERE ingested_at < now() - interval '7 days';
