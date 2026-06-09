# signal_system/engine/filters.py
"""
Hard filters — §8.
Applied before scoring. Cannot be overridden by score or manual action.
Returns (passed: bool, reason: str | None)
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from ..db import get_db
from ..config.watchlist import TICKER_SECTOR

logger = logging.getLogger(__name__)

EARNINGS_BUFFER_DAYS  = int(os.getenv("EARNINGS_BUFFER_DAYS", 7))
MIN_MARKET_CAP        = int(os.getenv("MIN_MARKET_CAP", 2_000_000_000))
MIN_AVG_VOLUME        = int(os.getenv("MIN_AVG_DAILY_VOLUME", 500_000))
LATE_ENTRY_PCT        = float(os.getenv("LATE_ENTRY_PCT", 5.0))
PRIOR_SIGNAL_DAYS     = 5   # §8: single isolated spike — no prior signal in 5 days


def _avg_volume_ok(avg_volume_20d: int) -> bool:
    """True if avg daily volume >= MIN_AVG_VOLUME. §8"""
    return avg_volume_20d >= MIN_AVG_VOLUME


def _price_not_late(pct_change: float) -> bool:
    """True if price hasn't already moved > LATE_ENTRY_PCT. §8"""
    return abs(pct_change) <= LATE_ENTRY_PCT


def _market_cap_ok(ticker: str) -> bool:
    """
    All 37 watchlist tickers are large-cap by definition (NVDA, MSFT, LMT etc).
    No API call needed — the watchlist itself is the market cap filter.
    Returns False only for tickers not on the watchlist (should never happen).
    """
    return ticker in TICKER_SECTOR


def _earnings_soon(ticker: str) -> bool:
    """
    Earnings check via DB — looks for news tagged 'earnings' for this ticker
    within EARNINGS_BUFFER_DAYS. Conservative: returns False (not soon) on
    any data error so we don't silently block signals.

    Note: yfinance earnings calendar is blocked on Railway cloud IPs.
    Using news-based proxy until a reliable free API is available.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        end    = datetime.now(timezone.utc) + timedelta(days=EARNINGS_BUFFER_DAYS)
        with get_db() as db:
            count = db.execute(
                text("""
                    SELECT COUNT(*) FROM news_items
                    WHERE :ticker = ANY(tagged_tickers)
                      AND category = 'earnings'
                      AND published_at BETWEEN :cutoff AND :end
                """),
                {"ticker": ticker, "cutoff": cutoff, "end": end},
            ).scalar()
        return (count or 0) > 0
    except Exception as e:
        logger.warning("ticker=%s earnings check failed: %s", ticker, e)
        return False  # don't block on error


def _has_prior_signal_or_new_ticker(ticker: str) -> tuple[bool, bool]:
    """
    Returns (passes_filter, is_cold_start).

    §8 intent: reject single isolated spikes — i.e. a ticker that spiked once
    but has no pattern of activity. The filter protects against noise on
    known-active tickers.

    Cold start exception: if a ticker has NEVER had a signal, this is its
    first legitimate chance. Allow it through — the scorer will apply its
    own discipline (+2 for repeat spike, etc). After the first signal is
    written, subsequent runs will require a prior signal within 5 days.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=PRIOR_SIGNAL_DAYS)
    with get_db() as db:
        # Check for recent signals (last 5 days)
        recent = db.execute(
            text("""
                SELECT COUNT(*) FROM signals
                WHERE ticker = :ticker
                  AND created_at >= :cutoff
            """),
            {"ticker": ticker, "cutoff": cutoff},
        ).scalar()

        if recent > 0:
            return True, False  # has prior signal — passes normally

        # Check if ticker has ever had a signal at all
        ever = db.execute(
            text("SELECT COUNT(*) FROM signals WHERE ticker = :ticker"),
            {"ticker": ticker},
        ).scalar()

        if ever == 0:
            # Cold start — first ever signal for this ticker. Allow through.
            logger.debug("ticker=%s cold start — allowing first signal", ticker)
            return True, True

        # Has had signals before but not in last 5 days — isolated spike, reject
        return False, False


def apply(
    ticker: str,
    pct_change: float,
    avg_volume_20d: int,
) -> tuple[bool, str | None]:
    """
    Run all hard filters in order. Returns (passed, reject_reason).
    Cheapest checks first.
    """

    # 1. Price already moved — cheapest, no DB/API call
    if not _price_not_late(pct_change):
        return False, f"price_moved_{abs(pct_change):.1f}pct"

    # 2. Low liquidity — already in memory, no call
    if not _avg_volume_ok(avg_volume_20d):
        return False, f"low_liquidity_avg_vol_{avg_volume_20d}"

    # 3. Market cap — watchlist check, no API call
    if not _market_cap_ok(ticker):
        return False, f"ticker_not_on_watchlist"

    # 4. Prior signal / cold start check — one DB query
    passes, is_cold_start = _has_prior_signal_or_new_ticker(ticker)
    if not passes:
        return False, "isolated_spike_no_prior_5d"
    if is_cold_start:
        logger.info("ticker=%s cold start — first signal allowed through filters", ticker)

    # 5. Earnings — DB query (news-based proxy)
    if _earnings_soon(ticker):
        return False, f"earnings_within_{EARNINGS_BUFFER_DAYS}d"

    return True, None


def earnings_soon(ticker: str) -> bool:
    """Public wrapper."""
    return _earnings_soon(ticker)


# -- Public aliases for testing --
def passes_liquidity(row: dict) -> bool:
    return _avg_volume_ok(row.get("avg_volume_20d", 0))

def passes_market_cap(row: dict) -> bool:
    return _market_cap_ok(row.get("ticker", ""))

def passes_late_entry(row: dict) -> bool:
    return _price_not_late(row.get("pct_change", 0))
