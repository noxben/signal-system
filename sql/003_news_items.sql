-- ============================================================
-- 003_news_items.sql
-- News headlines from RSS feeds
-- ============================================================

CREATE TABLE news_items (
    id              bigserial       PRIMARY KEY,
    source          varchar(30)     NOT NULL,
    headline        text            NOT NULL,
    url             text            UNIQUE NOT NULL,
    published_at    timestamptz     NOT NULL,
    ingested_at     timestamptz     NOT NULL DEFAULT now(),
    tagged_tickers  jsonb           NOT NULL DEFAULT '[]',
    category        varchar(20),

    CONSTRAINT chk_news_category CHECK (
        category IN ('defense', 'AI', 'pharma', 'energy', 'macro') OR category IS NULL
    )
);

CREATE INDEX idx_news_published_at    ON news_items (published_at DESC);
CREATE INDEX idx_news_tagged_tickers  ON news_items USING gin (tagged_tickers);
CREATE INDEX idx_news_category        ON news_items (category);
