-- ============================================================
-- Event-Driven Trading Signal System
-- PostgreSQL Schema  |  v1.1
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ------------------------------------------------------------
-- Table: source_health
-- Updated by each worker on every run (success or failure)
-- ------------------------------------------------------------
CREATE TABLE source_health (
    source                varchar(30)  PRIMARY KEY,  -- 'market' | 'news' | 'political' | 'options_proxy'
    last_success_at       timestamptz,
    status                varchar(10)  NOT NULL DEFAULT 'healthy',  -- 'healthy' | 'degraded'
    consecutive_failures  smallint     NOT NULL DEFAULT 0,
    last_error            text,

    CONSTRAINT chk_source_status CHECK (status IN ('healthy', 'degraded')),
    CONSTRAINT chk_source_name   CHECK (source IN ('market', 'news', 'political', 'options_proxy'))
);

-- Seed the four sources so workers can UPDATE rather than UPSERT every run
INSERT INTO source_health (source, status, consecutive_failures)
VALUES
    ('market',        'healthy', 0),
    ('news',          'healthy', 0),
    ('political',     'healthy', 0),
    ('options_proxy', 'healthy', 0);


-- ------------------------------------------------------------
-- Table: signals
-- Written by signal_engine; read by dashboard and outcome_worker
-- ------------------------------------------------------------
CREATE TABLE signals (
    signal_id            uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at           timestamptz  NOT NULL DEFAULT now(),
    ticker               varchar(10)  NOT NULL,
    trigger_type         varchar(50)  NOT NULL,  -- 'volume_spike' | 'sector_align' | 'pre_news' | 'repeat'
    score                smallint     NOT NULL,
    factors_json         jsonb        NOT NULL,  -- all factor values used in scoring
    sources_healthy_json jsonb        NOT NULL,  -- source status snapshot at signal time
    data_quality         varchar(10)  NOT NULL DEFAULT 'full',  -- 'full' | 'partial'
    status               varchar(15)  NOT NULL DEFAULT 'pending',  -- 'pending' | 'suppressed'

    -- Human decision (null until acted on)
    approved             boolean,
    reject_reason        varchar(100),
    approval_timestamp   timestamptz,

    -- Pricing
    entry_price          numeric(12,4),  -- set at approval time

    -- Outcome fields — filled by outcome_worker
    price_1d             numeric(12,4),
    price_3d             numeric(12,4),
    price_5d             numeric(12,4),
    mfe_value            numeric(12,4),  -- max favorable excursion within 5d
    max_drawdown         numeric(12,4),  -- max adverse excursion within 5d
    outcome_label        varchar(10),    -- 'hit' | 'mfe' | 'fail' | null

    -- FK to paper_trades (null if not approved)
    paper_trade_id       uuid,

    CONSTRAINT chk_trigger_type   CHECK (trigger_type IN ('volume_spike', 'sector_align', 'pre_news', 'repeat')),
    CONSTRAINT chk_data_quality   CHECK (data_quality IN ('full', 'partial')),
    CONSTRAINT chk_signal_status  CHECK (status IN ('pending', 'suppressed')),
    CONSTRAINT chk_outcome_label  CHECK (outcome_label IN ('hit', 'mfe', 'fail') OR outcome_label IS NULL),
    -- reject_reason required when rejected
    CONSTRAINT chk_reject_reason  CHECK (
        (approved = false AND reject_reason IS NOT NULL) OR
        (approved IS DISTINCT FROM false)
    )
);

CREATE INDEX idx_signals_ticker      ON signals (ticker);
CREATE INDEX idx_signals_created_at  ON signals (created_at DESC);
CREATE INDEX idx_signals_score       ON signals (score);
CREATE INDEX idx_signals_status      ON signals (status);
CREATE INDEX idx_signals_approved    ON signals (approved);


-- ------------------------------------------------------------
-- Table: paper_trades
-- Created on signal approval; updated by outcome_worker on exit
-- ------------------------------------------------------------
CREATE TABLE paper_trades (
    trade_id           uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id          uuid          NOT NULL REFERENCES signals (signal_id),
    ticker             varchar(10)   NOT NULL,
    entry_price        numeric(12,4) NOT NULL,
    position_size_usd  numeric(10,2) NOT NULL DEFAULT 1000.00,
    entry_time         timestamptz   NOT NULL DEFAULT now(),

    -- Exit fields — null until closed
    exit_price         numeric(12,4),
    exit_time          timestamptz,
    exit_reason        varchar(30),   -- 'take_profit' | 'stop_loss' | 'time_exit'
    pnl_usd            numeric(10,2),
    pnl_pct            numeric(8,4),

    status             varchar(10)   NOT NULL DEFAULT 'open',  -- 'open' | 'closed'

    CONSTRAINT chk_exit_reason    CHECK (exit_reason IN ('take_profit', 'stop_loss', 'time_exit') OR exit_reason IS NULL),
    CONSTRAINT chk_trade_status   CHECK (status IN ('open', 'closed')),
    -- pnl required when closed
    CONSTRAINT chk_closed_fields  CHECK (
        (status = 'closed' AND exit_price IS NOT NULL AND exit_time IS NOT NULL AND exit_reason IS NOT NULL) OR
        (status = 'open')
    )
);

CREATE INDEX idx_paper_trades_signal_id  ON paper_trades (signal_id);
CREATE INDEX idx_paper_trades_ticker     ON paper_trades (ticker);
CREATE INDEX idx_paper_trades_status     ON paper_trades (status);

-- Back-link: once paper_trade is created, update signals.paper_trade_id
ALTER TABLE signals
    ADD CONSTRAINT fk_paper_trade
    FOREIGN KEY (paper_trade_id) REFERENCES paper_trades (trade_id)
    DEFERRABLE INITIALLY DEFERRED;


-- ------------------------------------------------------------
-- Useful views for calibration queries (§16)
-- ------------------------------------------------------------

-- Approved hit rate
CREATE VIEW v_hit_rate AS
SELECT
    COUNT(*)                                                         AS approved_total,
    COUNT(*) FILTER (WHERE outcome_label IN ('hit', 'mfe'))          AS hits,
    ROUND(
        COUNT(*) FILTER (WHERE outcome_label IN ('hit', 'mfe'))::numeric
        / NULLIF(COUNT(*) FILTER (WHERE outcome_label IS NOT NULL), 0) * 100,
    2)                                                               AS hit_rate_pct
FROM signals
WHERE approved = true;

-- Score bucket vs outcome
CREATE VIEW v_score_vs_outcome AS
SELECT
    CASE
        WHEN score BETWEEN 3 AND 4 THEN '3-4'
        WHEN score BETWEEN 5 AND 6 THEN '5-6'
        WHEN score >= 7             THEN '7+'
        ELSE '<3'
    END                                                              AS score_bucket,
    COUNT(*)                                                         AS total,
    COUNT(*) FILTER (WHERE outcome_label IN ('hit', 'mfe'))          AS hits,
    COUNT(*) FILTER (WHERE outcome_label = 'fail')                   AS fails
FROM signals
WHERE approved = true AND outcome_label IS NOT NULL
GROUP BY score_bucket
ORDER BY score_bucket;

-- Partial signal performance
CREATE VIEW v_partial_vs_full AS
SELECT
    data_quality,
    COUNT(*)                                                         AS total,
    COUNT(*) FILTER (WHERE outcome_label IN ('hit', 'mfe'))          AS hits,
    COUNT(*) FILTER (WHERE outcome_label = 'fail')                   AS fails
FROM signals
WHERE approved = true AND outcome_label IS NOT NULL
GROUP BY data_quality;

-- Reject reason distribution
CREATE VIEW v_reject_reasons AS
SELECT
    reject_reason,
    COUNT(*) AS count
FROM signals
WHERE approved = false
GROUP BY reject_reason
ORDER BY count DESC;
