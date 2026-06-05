# signal_system/workers/avg_volume_worker.py
"""
avg_volume_worker — runs once daily at market open (09:35 ET).

Fetches 20 trading days of daily bars from Alpaca for all watchlist tickers.
Computes true avg_volume_20d and stores in avg_volume table.
Signal engine reads from here instead of using prev-day proxy.

§4.1: avg_volume_20d is a hard filter input — accuracy matters.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import text

from ..db import get_db
from ..health import mark_success, mark_failure
from ..config.watchlist import ALL_TICKERS

logger = logging.getLogger(__name__)
SOURCE = "market"

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET", "")
ALPACA_DATA_URL   = os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets")


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
    }


def _fetch_avg_volumes() -> dict[str, int]:
    """
    Fetch 25 calendar days of daily bars (gives ~20 trading days).
    Returns {ticker: avg_volume_20d}.
    """
    end   = datetime.now(timezone.utc).date()
    start = end - timedelta(days=35)  # buffer for weekends/holidays

    url = f"{ALPACA_DATA_URL}/v2/stocks/bars"
    resp = requests.get(
        url,
        headers=_headers(),
        params={
            "symbols":   ",".join(ALL_TICKERS),
            "timeframe": "1Day",
            "start":     start.isoformat(),
            "end":       end.isoformat(),
            "feed":      "iex",
            "limit":     1000,
        },
        timeout=20,
    )

    if resp.status_code == 401:
        raise ValueError("Alpaca API key invalid")
    resp.raise_for_status()

    bars_by_ticker = resp.json().get("bars", {})
    result = {}

    for ticker, bars in bars_by_ticker.items():
        if not bars:
            continue
        volumes = [b["v"] for b in bars[-20:]]  # last 20 trading days
        if volumes:
            result[ticker] = int(sum(volumes) / len(volumes))

    logger.info("avg_volume_worker computed avg for %d tickers", len(result))
    return result


def _write_to_db(avgs: dict[str, int]) -> None:
    now = datetime.now(timezone.utc)
    with get_db() as db:
        for ticker, avg_vol in avgs.items():
            db.execute(
                text("""
                    INSERT INTO avg_volume
                        (ticker, avg_volume_20d, computed_at)
                    VALUES
                        (:ticker, :avg_vol, :now)
                    ON CONFLICT (ticker) DO UPDATE SET
                        avg_volume_20d = EXCLUDED.avg_volume_20d,
                        computed_at    = EXCLUDED.computed_at
                """),
                {"ticker": ticker, "avg_vol": avg_vol, "now": now},
            )
    logger.info("avg_volume_worker wrote %d rows", len(avgs))


def run() -> None:
    logger.info("avg_volume_worker starting run")

    if not ALPACA_API_KEY or not ALPACA_API_SECRET:
        logger.warning("Alpaca credentials not set — avg_volume_worker skipped")
        return

    try:
        avgs = _fetch_avg_volumes()
        if avgs:
            _write_to_db(avgs)
            logger.info("avg_volume_worker completed successfully")
        else:
            logger.warning("avg_volume_worker — no data returned")
    except Exception as e:
        logger.error("avg_volume_worker failed: %s", e)
        mark_failure(SOURCE, str(e))
