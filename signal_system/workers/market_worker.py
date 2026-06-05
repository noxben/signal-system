# signal_system/workers/market_worker.py
"""
market_worker — runs every 5 minutes during market hours.

Fetches price + volume for all 37 watchlist tickers via yfinance.
Uses individual ticker calls with delay to avoid rate limiting on cloud IPs.
Writes raw snapshot to market_data table.
"""

import logging
import os
import time
from datetime import datetime, timezone

import yfinance as yf
from sqlalchemy import text

from ..db import get_db
from ..health import mark_success, mark_failure
from ..config.watchlist import ALL_TICKERS

logger = logging.getLogger(__name__)
SOURCE = "market"

# Delay between individual ticker calls — avoids Yahoo rate limiting
INTER_TICKER_DELAY = float(os.getenv("TICKER_FETCH_DELAY", "0.5"))


def _fetch_ticker(ticker: str, now: datetime) -> dict | None:
    """Fetch single ticker. Returns data dict or None on failure."""
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="1mo", interval="1d")

        if hist.empty or len(hist) < 2:
            logger.warning("ticker=%s insufficient history", ticker)
            return None

        latest   = hist.iloc[-1]
        prev     = hist.iloc[-2]
        price    = float(latest["Close"])
        volume   = int(latest["Volume"])

        avg_vol_20d = int(hist["Volume"].tail(20).mean()) if len(hist) >= 5 else volume

        pct_change = 0.0
        if prev["Close"] > 0:
            pct_change = round((price - float(prev["Close"])) / float(prev["Close"]) * 100, 4)

        return {
            "ticker":         ticker,
            "price":          price,
            "volume":         volume,
            "avg_volume_20d": avg_vol_20d,
            "pct_change":     pct_change,
            "ingested_at":    now,
        }
    except Exception as e:
        logger.warning("ticker=%s fetch error: %s", ticker, e)
        return None


def _write_to_db(records: list[dict]) -> None:
    if not records:
        logger.warning("Nothing to write — empty records list")
        return
    with get_db() as db:
        db.execute(
            text("""
                INSERT INTO market_data
                    (ticker, price, volume, avg_volume_20d, pct_change, ingested_at)
                VALUES
                    (:ticker, :price, :volume, :avg_volume_20d, :pct_change, :ingested_at)
            """),
            records,
        )
    logger.info("market_worker wrote %d rows", len(records))


def run() -> None:
    logger.info("market_worker starting run")
    now     = datetime.now(timezone.utc)
    records = []
    errors  = []

    for ticker in ALL_TICKERS:
        row = _fetch_ticker(ticker, now)
        if row:
            records.append(row)
        else:
            errors.append(ticker)
        time.sleep(INTER_TICKER_DELAY)

    if records:
        try:
            _write_to_db(records)
        except Exception as e:
            logger.error("market_worker DB write failed: %s", e)
            mark_failure(SOURCE, str(e))
            return

    logger.info(
        "market_worker done — %d fetched, %d failed: %s",
        len(records), len(errors), errors if errors else "none"
    )

    # Only mark degraded if ALL tickers failed
    if len(records) == 0:
        mark_failure(SOURCE, f"All {len(errors)} tickers failed")
    else:
        mark_success(SOURCE)
