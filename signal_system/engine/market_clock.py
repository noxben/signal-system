# signal_system/engine/market_clock.py
"""
Market session clock helper.
Converts a UTC timestamp into minutes-since-open (ET), or None if outside
market hours (weekend or before/after session). Used by the time-of-day
volume baseline in signal_engine.py.

Note: does not account for market holidays — a holiday will be treated as
a normal weekday. Low priority since market_data won't have fresh rows on
holidays anyway (no trades to ingest), so the stale-data check upstream
should naturally prevent false signals on those days.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)
ET = ZoneInfo("America/New_York")


def minutes_since_open(now_utc: datetime) -> float | None:
    """
    Returns minutes since market open (ET) for the given UTC timestamp,
    or None if outside market hours (weekend, pre-open, or post-close).
    """
    now_et = now_utc.astimezone(ET)
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return None
    open_dt  = now_et.replace(hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0)
    close_dt = now_et.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute, second=0, microsecond=0)
    if now_et < open_dt or now_et > close_dt:
        return None
    return (now_et - open_dt).total_seconds() / 60
