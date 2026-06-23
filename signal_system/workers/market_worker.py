# signal_system/workers/market_worker.py
"""
market_worker — runs every 5 minutes during market hours.

Uses Alpaca Market Data API (free with paper account):
  - /v2/stocks/snapshots — batch snapshot for all watchlist tickers
    Returns: latest trade price, daily volume, prev close

Real-time IEX data, no IP blocking, generous rate limits.
Same API key used for paper trading execution later.
"""

import logging
import os
from datetime import datetime, timezone

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
        "Accept":              "application/json",
    }


def _fetch_snapshots() -> list[dict]:
    """
    Fetch current snapshot for all watchlist tickers in one call.
    Alpaca snapshots include: latest trade, latest quote, daily bar, prev daily bar.
    """
    url = f"{ALPACA_DATA_URL}/v2/stocks/snapshots"

    resp = requests.get(
        url,
        headers=_headers(),
        params={
            "symbols": ",".join(ALL_TICKERS),
            "feed":    "sip",  # free tier — IEX feed
        },
        timeout=15,
    )

    if resp.status_code == 401:
        raise ValueError("Alpaca API key invalid — check ALPACA_API_KEY and ALPACA_API_SECRET")
    if resp.status_code == 429:
        raise ValueError("Alpaca rate limit hit")
    resp.raise_for_status()

    data = resp.json()
    now  = datetime.now(timezone.utc)
    records = []

    for ticker, snap in data.items():
        if ticker not in set(ALL_TICKERS):
            continue

        # Latest trade price
        latest_trade = snap.get("latestTrade", {})
        price = latest_trade.get("p")  # price field

        # Daily bar for volume
        daily_bar = snap.get("dailyBar", {})
        volume    = daily_bar.get("v", 0)

        # Previous daily bar for avg volume proxy and pct change baseline
        prev_bar   = snap.get("prevDailyBar", {})
        prev_close = prev_bar.get("c", 0)
        prev_vol   = prev_bar.get("v", 0)

        # redacted for new volume trend schedule
        # Use prev day volume as avg_volume_20d proxy (best available on free tier)
        # avg_volume_20d = prev_vol or volume or 1

        # Pct change vs previous close
        if price and prev_close and prev_close > 0:
            pct_change = round((price - prev_close) / prev_close * 100, 4)
        else:
            pct_change = 0.0

        if not price:
            logger.warning("ticker=%s no price in snapshot", ticker)
            continue

        records.append({
            "ticker":         ticker,
            "price":          float(price),
            "volume":         int(volume),
            # avg_volume_20d intentionally omitted — signal_engine reads the
            # real 20-day average from the avg_volume table. Do not write a
            # fabricated proxy here; it previously masked avg_volume_worker
            # failures and was being compared against partial-day cumulative
            # volume incorrectly.
            "pct_change":     pct_change,
            "ingested_at":    now,
        })

    logger.info("alpaca snapshot returned %d tickers", len(records))
    return records


def _write_to_db(records: list[dict]) -> None:
    if not records:
        logger.warning("market_worker — nothing to write")
        return
    with get_db() as db:
        db.execute(
            text("""
                INSERT INTO market_data
					(ticker, price, volume, pct_change, ingested_at)
				VALUES
					(:ticker, :price, :volume, :pct_change, :ingested_at)
            """),
            records,
        )
    logger.info("market_worker wrote %d rows", len(records))


def run() -> None:
    logger.info("market_worker starting run")

    if not ALPACA_API_KEY or not ALPACA_API_SECRET:
        logger.warning("Alpaca credentials not set — market_worker skipped")
        mark_failure(SOURCE, "ALPACA_API_KEY or ALPACA_API_SECRET not configured")
        return

    try:
        records = _fetch_snapshots()
        if records:
            _write_to_db(records)
            mark_success(SOURCE)
            logger.info("market_worker completed — %d tickers written", len(records))
        else:
            logger.warning("market_worker — snapshot returned no data (market may be closed)")
            mark_success(SOURCE)  # not a failure — just no data outside hours
    except Exception as e:
        logger.error("market_worker failed: %s", e)
        mark_failure(SOURCE, str(e))
