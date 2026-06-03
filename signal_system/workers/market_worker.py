# signal_system/workers/market_worker.py
"""
market_worker — runs every 5 minutes during market hours.

Pulls price + volume for all 37 watchlist tickers via yfinance.
Writes raw snapshot to market_data table.
Updates source_health on every run (success or failure).

§4.1, §5, §14.1
"""

import logging
import os
from datetime import datetime, timezone

import yfinance as yf
import pandas as pd
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential

from ..db import get_db
from ..health import mark_success, mark_failure
from ..config.watchlist import ALL_TICKERS

logger = logging.getLogger(__name__)

SOURCE = "market"

# Retry: 3 attempts, backoff 1s → 4s → 16s  (§5.1)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    reraise=True,
)
def _fetch_yfinance(tickers: list[str]) -> pd.DataFrame:
    """
    Fetch latest price + volume for all tickers in one batch call.
    Returns DataFrame with columns: ticker, price, volume, avg_volume_20d, pct_change.
    """
    raw = yf.download(
        tickers=tickers,
        period="1mo",       # need 20d history for avg_volume_20d
        interval="5m",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    records = []
    now = datetime.now(timezone.utc)

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                df = raw
            else:
                df = raw[ticker]

            if df.empty:
                logger.warning("ticker=%s no data returned", ticker)
                continue

            # Latest bar
            latest = df.iloc[-1]
            price      = float(latest["Close"])
            volume     = int(latest["Volume"])

            # 20-day average volume using daily data
            daily = yf.Ticker(ticker).history(period="1mo", interval="1d")
            avg_vol_20d = int(daily["Volume"].tail(20).mean()) if len(daily) >= 5 else volume

            # Percent change vs previous close
            if len(df) >= 2:
                prev_close  = float(df.iloc[-2]["Close"])
                pct_change  = ((price - prev_close) / prev_close) * 100 if prev_close else 0.0
            else:
                pct_change  = 0.0

            records.append({
                "ticker":        ticker,
                "price":         price,
                "volume":        volume,
                "avg_volume_20d": avg_vol_20d,
                "pct_change":    round(pct_change, 4),
                "ingested_at":   now,
            })

        except Exception as e:
            logger.error("ticker=%s parse error: %s", ticker, e)

    return pd.DataFrame(records)


def _write_to_db(df: pd.DataFrame) -> None:
    """Insert raw snapshot rows. Each run is a new set of rows — no upsert."""
    if df.empty:
        logger.warning("Nothing to write — empty DataFrame")
        return

    rows = df.to_dict(orient="records")

    with get_db() as db:
        db.execute(
            text("""
                INSERT INTO market_data
                    (ticker, price, volume, avg_volume_20d, pct_change, ingested_at)
                VALUES
                    (:ticker, :price, :volume, :avg_volume_20d, :pct_change, :ingested_at)
            """),
            rows,
        )

    logger.info("market_worker wrote %d rows", len(rows))


def run() -> None:
    """
    Entry point called by Celery Beat every 5 minutes.
    §5: raw data stored before any processing.
    §5.1: on failure, mark degraded and continue — do NOT raise into the scheduler.
    """
    logger.info("market_worker starting run")
    try:
        df = _fetch_yfinance(ALL_TICKERS)
        _write_to_db(df)
        mark_success(SOURCE)
        logger.info("market_worker completed successfully")
    except Exception as e:
        mark_failure(SOURCE, str(e))
        logger.error("market_worker failed after retries: %s", e)
        # Do not re-raise — degraded state is recorded, pipeline continues
