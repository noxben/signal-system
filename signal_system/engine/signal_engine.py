# signal_system/engine/signal_engine.py
"""
Signal engine — §6, §7, §8, §9.
Runs every 5 minutes via scheduler.

Flow per ticker:
  1. Read latest market snapshot from DB
  2. Check volume spike condition (Signal A)
  3. Apply hard filters — reject before scoring
  4. Score remaining candidates
  5. Apply duplicate suppression (24h cooldown)
  6. Write signal rows — all of them, regardless of score or outcome
  7. Surface signals >= PASS_THRESHOLD to dashboard (approved = null)

Key rules:
  - Reads DB snapshot only — no shared memory with workers
  - Missing/stale market data is skipped, not treated as zero
  - Degraded sources zero out their factor contribution
  - Every signal row gets factors_json + sources_healthy_json
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import yfinance as yf
from sqlalchemy import text

from ..db import get_db
from ..health import get_source_statuses
from ..config.watchlist import ALL_TICKERS, TICKER_SECTOR
from . import filters, scorer

logger = logging.getLogger(__name__)

VOLUME_MULTIPLIER    = float(os.getenv("VOLUME_SPIKE_MULTIPLIER", 2.5))
PASS_THRESHOLD       = int(os.getenv("SCORE_PASS_THRESHOLD", 5))
COOLDOWN_HOURS       = int(os.getenv("DUPLICATE_COOLDOWN_HOURS", 24))
COOLDOWN_SCORE_DELTA = int(os.getenv("DUPLICATE_SCORE_EXCEPTION", 2))
STALE_MINUTES        = 10   # market data older than this is skipped


def _latest_market_data() -> dict[str, dict]:
    """
    Read the most recent market_data row per ticker.
    Skip rows older than STALE_MINUTES — stale data must not propagate. §5
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)

    with get_db() as db:
        rows = db.execute(
            text("""
                SELECT DISTINCT ON (ticker)
                    ticker, price, volume, avg_volume_20d, pct_change, ingested_at
                FROM market_data
                WHERE ingested_at >= :cutoff
                ORDER BY ticker, ingested_at DESC
            """),
            {"cutoff": cutoff},
        ).fetchall()

    return {r.ticker: dict(r._mapping) for r in rows}


def _get_market_cap(ticker: str) -> int:
    """Fetch market cap. Returns 0 on failure — scorer will penalise."""
    try:
        info = yf.Ticker(ticker).info
        return int(info.get("marketCap") or 0)
    except Exception:
        return 0


def _in_cooldown(ticker: str) -> tuple[bool, int | None]:
    """
    §9: 24h cooldown per ticker after any signal.
    Returns (in_cooldown, last_score).
    Exception: surface if new score >= last_score + COOLDOWN_SCORE_DELTA.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
    with get_db() as db:
        row = db.execute(
            text("""
                SELECT score FROM signals
                WHERE ticker = :ticker
                  AND created_at >= :cutoff
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"ticker": ticker, "cutoff": cutoff},
        ).fetchone()
    if row:
        return True, row.score
    return False, None


def _write_signal(
    ticker: str,
    trigger_type: str,
    score: int,
    factors: dict,
    sources: dict,
    status: str = "pending",
) -> None:
    """
    Write one signal row. All signals written regardless of score. §16
    data_quality = 'partial' if any source was degraded at signal time. §5.2
    """
    data_quality = "partial" if any(v == "degraded" for v in sources.values()) else "full"

    with get_db() as db:
        db.execute(
            text("""
                INSERT INTO signals
                    (ticker, sector, trigger_type, score, factors_json,
                     sources_healthy_json, data_quality, status)
                VALUES
                    (:ticker, :sector, :trigger_type, :score, :factors_json,
                     :sources_healthy_json, :data_quality, :status)
            """),
            {
                "ticker":              ticker,
                "sector":              TICKER_SECTOR.get(ticker),
                "trigger_type":        trigger_type,
                "score":               score,
                "factors_json":        json.dumps(factors),
                "sources_healthy_json": json.dumps(sources),
                "data_quality":        data_quality,
                "status":              status,
            },
        )


def _should_suppress(
    ticker: str,
    new_score: int,
    last_signal_time,
    last_signal_score,
) -> bool:
    """
    §9 duplicate suppression logic — extracted for testability.
    Returns True if signal should be suppressed.
    """
    if last_signal_time is None:
        return False

    now = datetime.now(timezone.utc)
    hours_since = (now - last_signal_time).total_seconds() / 3600

    if hours_since >= COOLDOWN_HOURS:
        return False  # outside cooldown window

    # Inside cooldown — check score jump exception
    if last_signal_score is not None and new_score >= last_signal_score + COOLDOWN_SCORE_DELTA:
        return False  # score jumped enough to override

    return True


def run() -> None:
    """
    Main signal engine loop.
    Called every 5 minutes by scheduler during market hours.
    """
    logger.info("signal_engine starting run")

    # Snapshot source health once for this run — shared across all tickers
    sources = get_source_statuses()

    # If market data source itself is degraded, abort — nothing to process
    if sources.get("market") == "degraded":
        logger.warning("signal_engine aborted — market source degraded")
        return

    market = _latest_market_data()

    if not market:
        logger.warning("signal_engine — no fresh market data, skipping run")
        return

    signals_written = 0

    for ticker in ALL_TICKERS:
        row = market.get(ticker)

        # No fresh data for this ticker — skip, do not treat as zero §5
        if not row:
            logger.debug("ticker=%s no fresh market data — skipped", ticker)
            continue

        volume       = row["volume"]
        avg_vol      = row["avg_volume_20d"]
        pct_change   = float(row["pct_change"])
        sector       = TICKER_SECTOR.get(ticker, "unknown")

        # Signal A: volume spike is the entry condition for all further processing
        if avg_vol <= 0 or (volume / avg_vol) < VOLUME_MULTIPLIER:
            continue
        if abs(pct_change) >= 2.0:
            continue

        logger.info("ticker=%s volume spike detected (%.1fx)", ticker, volume / avg_vol)

        # Hard filters — §8
        passed, reject_reason = filters.apply(ticker, pct_change, avg_vol)
        if not passed:
            logger.info("ticker=%s hard filter rejected: %s", ticker, reject_reason)
            # Still write to DB for calibration — stored with low score
            _write_signal(
                ticker=ticker,
                trigger_type="volume_spike",
                score=0,
                factors={"hard_filter_reject": reject_reason},
                sources=sources,
                status="suppressed",
            )
            signals_written += 1
            continue

        # Gather inputs for scorer
        market_cap   = _get_market_cap(ticker)
        earns_soon   = filters.earnings_soon(ticker)

        # Score — §7
        # If news source is degraded, no_news factor zeroed per §5.1
        effective_sources = dict(sources)
        score, factors = scorer.compute(
            ticker=ticker,
            sector=sector,
            volume=volume,
            avg_volume_20d=avg_vol,
            pct_change=pct_change,
            market_cap=market_cap,
            earnings_soon=earns_soon,
        )

        # If political source degraded, zero out sector_aligned contribution §5.1
        if sources.get("political") == "degraded" and factors.get("sector_aligned"):
            score -= scorer.SCORE_SECTOR_POLICY
            factors["sector_aligned"] = False
            factors["sector_aligned_zeroed"] = "political_source_degraded"

        # If news source degraded, zero out no_news contribution §5.1
        if sources.get("news") == "degraded" and factors.get("no_recent_news"):
            score -= scorer.SCORE_NO_NEWS
            factors["no_recent_news"] = False
            factors["no_news_zeroed"] = "news_source_degraded"

        trigger_type = factors.get("trigger_type", "volume_spike")

        # Duplicate suppression — §9
        in_cd, last_score = _in_cooldown(ticker)
        if in_cd:
            if last_score is not None and score >= last_score + COOLDOWN_SCORE_DELTA:
                logger.info(
                    "ticker=%s cooldown exception — score %d >= last %d + %d",
                    ticker, score, last_score, COOLDOWN_SCORE_DELTA,
                )
                # Allow through — fall to write below
            else:
                logger.debug("ticker=%s in cooldown, suppressing", ticker)
                _write_signal(
                    ticker=ticker,
                    trigger_type=trigger_type,
                    score=score,
                    factors=factors,
                    sources=sources,
                    status="suppressed",
                )
                signals_written += 1
                continue

        # Write signal — pending if score >= threshold, suppressed if below
        status = "pending" if score >= PASS_THRESHOLD else "suppressed"
        _write_signal(
            ticker=ticker,
            trigger_type=trigger_type,
            score=score,
            factors=factors,
            sources=sources,
            status=status,
        )
        signals_written += 1

        if status == "pending":
            logger.info(
                "ticker=%s signal surfaced score=%d trigger=%s quality=%s",
                ticker, score, trigger_type,
                "partial" if any(v == "degraded" for v in sources.values()) else "full",
            )

    logger.info("signal_engine complete — %d signals written", signals_written)
