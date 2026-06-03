-- ============================================================
-- 003_news_items.sql
-- News headlines from Reuters + Benzinga RSS
-- Run after 001 and 002
-- ============================================================

CREATE TABLE news_items (
    id              bigserial       PRIMARY KEY,
    source          varchar(20)     NOT NULL,           -- 'reuters' | 'benzinga'
    headline        text            NOT NULL,
    url             text            UNIQUE NOT NULL,    -- dedup key
    published_at    timestamptz     NOT NULL,
    ingested_at     timestamptz     NOT NULL DEFAULT now(),
    tagged_tickers  jsonb           NOT NULL DEFAULT '[]',  -- ["NVDA", "AMD"]
    category        varchar(20),                        -- 'defense' | 'AI' | 'pharma' | 'energy' | 'macro'

    CONSTRAINT chk_news_source   CHECK (source IN ('reuters', 'benzinga')),
    CONSTRAINT chk_news_category CHECK (category IN ('defense', 'AI', 'pharma', 'energy', 'macro') OR category IS NULL)
);

-- Signal engine queries: "any news for ticker X in last N hours?"
CREATE INDEX idx_news_published_at    ON news_items (published_at DESC);
CREATE INDEX idx_news_tagged_tickers  ON news_items USING gin (tagged_tickers);
CREATE INDEX idx_news_category        ON news_items (category);

-- Retention: 30 days of headlines is plenty
-- Run via outcome_worker cleanup:
-- DELETE FROM news_items WHERE ingested_at < now() - interval '30 days';
