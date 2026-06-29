# signal_system/engine/scorer.py
"""
Scoring model — §7.
Computes score from factors. Returns score + factors_json.
Weights are initial estimates — do NOT tune until 60+ signals logged.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from .market_clock import minutes_since_open
from ..config.intraday_curve import expected_volume_fraction

from sqlalchemy import text

from ..db import get_db

logger = logging.getLogger(__name__)

# §7 scoring table — locked until calibration
SCORE_VOLUME_SPIKE   =  2
SCORE_SECTOR_POLICY  =  2
SCORE_NO_NEWS        =  2
SCORE_REPEAT_SPIKE   =  2
SCORE_OPTIONS_PROXY  =  1
PENALTY_EARNINGS     = -3
PENALTY_LATE_ENTRY   = -2
PENALTY_SMALL_CAP    = -1
PENALTY_BELOW_50_SMA = -2  # price below 50-day SMA — trend is against the trade
                           # POST-MVP NOTE: when shorting is added, this penalty
                           # should flip to a positive for short signals.
                           # Revisit after 60 signals logged with outcome data.

PASS_THRESHOLD       = int(os.getenv("SCORE_PASS_THRESHOLD", 5))
VOLUME_MULTIPLIER    = float(os.getenv("VOLUME_SPIKE_MULTIPLIER", 2.5))
NO_NEWS_HOURS        = int(os.getenv("NO_NEWS_WINDOW_HOURS", 4))
SECTOR_ALIGN_MINUTES = int(os.getenv("SECTOR_ALIGN_WINDOW_MINUTES", 60))
REPEAT_HOURS         = int(os.getenv("REPEAT_SPIKE_WINDOW_HOURS", 48))
MIN_MARKET_CAP       = int(os.getenv("MIN_MARKET_CAP", 2_000_000_000))
LATE_ENTRY_PCT       = float(os.getenv("LATE_ENTRY_PCT", 5.0))
EARNINGS_BUFFER_DAYS = int(os.getenv("EARNINGS_BUFFER_DAYS", 7))


def _has_recent_news(ticker: str) -> bool:
    """True if any news tagged this ticker in the last NO_NEWS_HOURS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NO_NEWS_HOURS)
    with get_db() as db:
        count = db.execute(
            text("""
                SELECT COUNT(*) FROM news_items
                WHERE tagged_tickers @> :ticker_json
                  AND published_at >= :cutoff
            """),
            {"ticker_json": f'["{ticker}"]', "cutoff": cutoff},
        ).scalar()
    return count > 0


def _sector_aligned(ticker: str, sector: str) -> bool:
    """
    Signal B: 2+ tickers in same sector spiked within SECTOR_ALIGN_MINUTES
    AND a political event exists for that sector in last 24h. §6
    """
    now              = datetime.now(timezone.utc)
    cutoff_align     = now - timedelta(minutes=SECTOR_ALIGN_MINUTES)
    cutoff_political = now - timedelta(hours=24)

    with get_db() as db:
        spike_count = db.execute(
            text("""
                SELECT COUNT(DISTINCT ticker) FROM signals
                WHERE sector = :sector
                  AND ticker != :ticker
                  AND trigger_type = 'volume_spike'
                  AND created_at >= :cutoff
            """),
            {"sector": sector, "ticker": ticker, "cutoff": cutoff_align},
        ).scalar()

        if spike_count < 1:
            return False

        pol_count = db.execute(
            text("""
                SELECT COUNT(*) FROM political_events
                WHERE sector = :sector
                  AND ingested_at >= :cutoff
            """),
            {"sector": sector, "cutoff": cutoff_political},
        ).scalar()

    return pol_count > 0


def _is_repeat_spike(ticker: str) -> bool:
    """Signal D: same ticker had 2+ spikes in last REPEAT_HOURS. §6"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=REPEAT_HOURS)
    with get_db() as db:
        count = db.execute(
            text("""
                SELECT COUNT(*) FROM signals
                WHERE ticker = :ticker
                  AND trigger_type = 'volume_spike'
                  AND created_at >= :cutoff
            """),
            {"ticker": ticker, "cutoff": cutoff},
        ).scalar()
    return count >= 2


def _get_sma_50d(ticker: str) -> float | None:
    """
    Read the 50-day SMA from avg_volume table.
    Computed daily by avg_volume_worker.
    Returns None if not yet populated — penalty is skipped, not applied.
    """
    with get_db() as db:
        row = db.execute(
            text("SELECT sma_50d FROM avg_volume WHERE ticker = :ticker"),
            {"ticker": ticker},
        ).fetchone()
    if row and row.sma_50d is not None:
        return float(row.sma_50d)
    return None


def compute(
    ticker: str,
    sector: str,
    volume: int,
    avg_volume_20d: int,
    pct_change: float,
    market_cap: int,
    earnings_soon: bool,
    current_price: float,
) -> tuple[int, dict]:
    """
    Compute score and return (score, factors_json).
    factors_json records every factor value for calibration (§16).

    current_price added to support the 50-day SMA trend filter.
    Signal engine must pass this — it already has price from market_data.
    """
    factors = {}
    score   = 0

    # --- Positive factors ---

    # Volume spike baseline, time-of-day adjusted
    now_utc = datetime.now(timezone.utc)
    mins = minutes_since_open(now_utc)
    if mins is not None and avg_volume_20d > 0:
        expected_fraction = expected_volume_fraction(mins)
        expected_volume   = avg_volume_20d * expected_fraction
        volume_ratio      = volume / expected_volume if expected_volume > 0 else 0
    else:
        volume_ratio = 0

    is_spike = volume_ratio >= VOLUME_MULTIPLIER and abs(pct_change) < LATE_ENTRY_PCT
    if is_spike:
        score += SCORE_VOLUME_SPIKE
    factors["volume_spike"] = is_spike
    factors["volume_ratio"] = round(volume_ratio, 2)

    # Sector alignment + political event
    aligned = _sector_aligned(ticker, sector)
    if aligned:
        score += SCORE_SECTOR_POLICY
    factors["sector_aligned"] = aligned

    # No news in window (pre-news signal)
    has_news = _has_recent_news(ticker)
    no_news  = not has_news
    if no_news:
        score += SCORE_NO_NEWS
    factors["no_recent_news"] = no_news

    # Repeat spike
    repeat = _is_repeat_spike(ticker)
    if repeat:
        score += SCORE_REPEAT_SPIKE
    factors["repeat_spike"] = repeat

    # Options proxy — placeholder, implemented Week 4
    factors["options_proxy"] = False

    # --- Penalties ---

    if earnings_soon:
        score += PENALTY_EARNINGS
    factors["earnings_soon"] = earnings_soon

    if abs(pct_change) > LATE_ENTRY_PCT:
        score += PENALTY_LATE_ENTRY
    factors["late_entry"] = abs(pct_change) > LATE_ENTRY_PCT

    if market_cap < MIN_MARKET_CAP:
        score += PENALTY_SMALL_CAP
    factors["small_cap"] = market_cap < MIN_MARKET_CAP

    # 50-day SMA trend filter
    # If sma_50d is None (not yet computed), skip penalty — do not penalise
    # a ticker just because the worker hasn't run yet.
    sma_50d = _get_sma_50d(ticker)
    if sma_50d is not None:
        below_50_sma = current_price < sma_50d
        if below_50_sma:
            score += PENALTY_BELOW_50_SMA
        factors["below_50_sma"] = below_50_sma
        factors["sma_50d"]      = sma_50d
    else:
        factors["below_50_sma"] = None  # None = data not yet available
        factors["sma_50d"]      = None

    # Determine primary trigger type
    if no_news and is_spike:
        trigger_type = "pre_news"
    elif repeat:
        trigger_type = "repeat"
    elif aligned:
        trigger_type = "sector_align"
    else:
        trigger_type = "volume_spike"

    factors["trigger_type"] = trigger_type
    factors["final_score"]  = score

    return score, factors


# -- Public interface for testing --
def compute_score(factors: dict, source_statuses: dict) -> tuple[int, dict]:
    """
    Testable interface: takes pre-built factors dict + source statuses.
    Returns (score, breakdown_dict).
    """
    score     = 0
    breakdown = dict(factors)

    vol_contrib = 2 if factors.get("volume_spike") else 0
    breakdown["volume_spike_contribution"] = vol_contrib
    score += vol_contrib

    sector_contrib = 2 if (
        factors.get("sector_aligned") and
        source_statuses.get("political") == "healthy"
    ) else 0
    breakdown["sector_aligned_contribution"] = sector_contrib
    score += sector_contrib

    news_contrib = 2 if (
        factors.get("no_recent_news") and
        source_statuses.get("news") == "healthy"
    ) else 0
    breakdown["no_recent_news_contribution"] = news_contrib
    score += news_contrib

    repeat_contrib = 2 if factors.get("repeat_spike") else 0
    breakdown["repeat_spike_contribution"] = repeat_contrib
    score += repeat_contrib

    options_contrib = 1 if (
        factors.get("options_proxy") and
        source_statuses.get("options_proxy") == "healthy"
    ) else 0
    breakdown["options_proxy_contribution"] = options_contrib
    score += options_contrib

    # Penalties
    if factors.get("earnings_soon"):
        score -= 3
    if factors.get("late_entry"):
        score -= 2
    if factors.get("small_cap"):
        score -= 1
    if factors.get("below_50_sma"):
        score -= 2

    return score, breakdown