# signal_system/engine/filters.py
"""
Hard filters — §8.
Applied before scoring. Cannot be overridden by score or manual action.
Returns (passed: bool, reason: str | None)
"""

import logging
import os
from datetime import datetime, timezone, timedelta

import yfinance as yf
from sqlalchemy import text

from ..db import get_db

logger = logging.getLogger(__name__)

EARNINGS_BUFFER_DAYS  = int(os.getenv("EARNINGS_BUFFER_DAYS", 7))
MIN_MARKET_CAP        = int(os.getenv("MIN_MARKET_CAP", 2_000_000_000))
MIN_AVG_VOLUME        = int(os.getenv("MIN_AVG_DAILY_VOLUME", 500_000))
LATE_ENTRY_PCT        = float(os.getenv("LATE_ENTRY_PCT", 5.0))
PRIOR_SIGNAL_DAYS     = 5   # §8: single isolated spike — no prior signal in 5 days


def _earnings_soon(ticker: str) -> bool:
    """True if earnings within EARNINGS_BUFFER_DAYS."""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return False

        # calendar may be a DataFrame or plain dict depending on yfinance version
        import pandas as pd
        if isinstance(cal, pd.DataFrame):
            if cal.empty:
                return False
            if "Earnings Date" in cal.columns:
                dates = cal["Earnings Date"].dropna().tolist()
            elif "Earnings Date" in cal.index:
                dates = [cal.loc["Earnings Date"]]
            else:
                return False
        elif isinstance(cal, dict):
            raw = cal.get("Earnings Date", [])
            dates = raw if isinstance(raw, list) else [raw]
        else:
            return False

        now = datetime.now(timezone.utc).date()
        for d in dates:
            try:
                ed = d.date() if hasattr(d, "date") else d
                if 0 <= (ed - now).days <= EARNINGS_BUFFER_DAYS:
                    return True
            except Exception:
                continue
    except Exception as e:
        logger.warning("ticker=%s earnings check failed: %s", ticker, e)
    return False


def _market_cap_ok(ticker: str) -> bool:
    """True if market cap >= MIN_MARKET_CAP."""
    try:
        info = yf.Ticker(ticker).info
        cap  = info.get("marketCap") or 0
        return cap >= MIN_MARKET_CAP
    except Exception as e:
        logger.warning("ticker=%s market cap check failed: %s", ticker, e)
        return True  # don't reject on data error — let scorer penalise


def _avg_volume_ok(avg_volume_20d: int) -> bool:
    """True if avg daily volume >= MIN_AVG_VOLUME. §8"""
    return avg_volume_20d >= MIN_AVG_VOLUME


def _price_not_late(pct_change: float) -> bool:
    """True if price hasn't already moved > LATE_ENTRY_PCT. §8"""
    return abs(pct_change) <= LATE_ENTRY_PCT


def _has_prior_signal(ticker: str) -> bool:
    """
    True if ticker had any signal in the last PRIOR_SIGNAL_DAYS.
    §8: reject single isolated spikes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=PRIOR_SIGNAL_DAYS)
    with get_db() as db:
        count = db.execute(
            text("""
                SELECT COUNT(*) FROM signals
                WHERE ticker = :ticker
                  AND created_at >= :cutoff
            """),
            {"ticker": ticker, "cutoff": cutoff},
        ).scalar()
    return count > 0


def apply(
    ticker: str,
    pct_change: float,
    avg_volume_20d: int,
) -> tuple[bool, str | None]:
    """
    Run all hard filters in order. Returns (passed, reject_reason).
    Cheapest checks first to avoid unnecessary API calls.
    """

    # 1. Price already moved — cheapest, no API call
    if not _price_not_late(pct_change):
        return False, f"price_moved_{abs(pct_change):.1f}pct"

    # 2. Low liquidity — already in DB, no API call
    if not _avg_volume_ok(avg_volume_20d):
        return False, f"low_liquidity_avg_vol_{avg_volume_20d}"

    # 3. Single isolated spike — DB query
    if not _has_prior_signal(ticker):
        return False, "isolated_spike_no_prior_5d"

    # 4. Market cap — yfinance call (cached by yfinance internally)
    if not _market_cap_ok(ticker):
        return False, f"market_cap_below_{MIN_MARKET_CAP}"

    # 5. Earnings — yfinance call (most expensive, last)
    if _earnings_soon(ticker):
        return False, f"earnings_within_{EARNINGS_BUFFER_DAYS}d"

    return True, None


def earnings_soon(ticker: str) -> bool:
    """Public wrapper — use this instead of _earnings_soon directly."""
    return _earnings_soon(ticker)


# -- Public aliases for testing and external use --
def passes_liquidity(row: dict) -> bool:
    return _avg_volume_ok(row.get("avg_volume_20d", 0))

def passes_market_cap(row: dict) -> bool:
    cap = row.get("market_cap")
    if cap is None:
        return False
    return _market_cap_ok_value(cap)

def passes_late_entry(row: dict) -> bool:
    return _price_not_late(row.get("pct_change", 0))

def _market_cap_ok_value(cap: float) -> bool:
    """Value-based market cap check — used by passes_market_cap."""
    return cap >= MIN_MARKET_CAP
