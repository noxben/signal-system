# signal_system/workers/avg_volume_worker.py
"""
avg_volume_worker — runs once daily at market open (09:35 ET).
Fetches 50 trading days of daily bars from Alpaca for all watchlist tickers.
Computes avg_volume_20d and sma_50d (50-day simple moving average of close).
Signal engine reads from here instead of using prev-day proxy.
§4.1: avg_volume_20d is a hard filter input — accuracy matters.
sma_50d used as trend filter in scorer — price below sma_50d = −2 penalty.
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


def _fetch_bars() -> dict[str, dict]:
    """
    Fetch 70 calendar days of daily bars (gives ~50 trading days).
    Returns {ticker: {"avg_volume_20d": int, "sma_50d": float}}.
    """
    end   = datetime.now(timezone.utc).date()
    start = end - timedelta(days=70)  # buffer for weekends/holidays — need ~50 trading days

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
            "limit":     5000,
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

        # avg_volume_20d — last 20 trading days
        volumes = [b["v"] for b in bars[-20:]]
        avg_volume_20d = int(sum(volumes) / len(volumes)) if volumes else None

        # sma_50d — simple moving average of close, last 50 trading days
        closes = [b["c"] for b in bars[-50:]]
        sma_50d = round(sum(closes) / len(closes), 4) if len(closes) >= 20 else None
        # Note: require at least 20 bars for sma_50d to be meaningful.
        # Fewer than 50 bars means the average is over a shorter window — still
        # useful as a trend proxy but less reliable. Logged below.

        if avg_volume_20d:
            result[ticker] = {
                "avg_volume_20d": avg_volume_20d,
                "sma_50d":        sma_50d,
            }

        if sma_50d is None:
            logger.warning(
                "ticker=%s insufficient bars for sma_50d (%d bars available)",
                ticker, len(bars),
            )
        elif len(closes) < 50:
            logger.warning(
                "ticker=%s sma_50d computed from %d bars (fewer than 50) — treat as approximate",
                ticker, len(closes),
            )

    logger.info("avg_volume_worker computed avg for %d tickers", len(result))
    return result


def _write_to_db(data: dict[str, dict]) -> None:
    now = datetime.now(timezone.utc)
    with get_db() as db:
        for ticker, vals in data.items():
            db.execute(
                text("""
                    INSERT INTO avg_volume
                        (ticker, avg_volume_20d, sma_50d, computed_at)
                    VALUES
                        (:ticker, :avg_vol, :sma_50d, :now)
                    ON CONFLICT (ticker) DO UPDATE SET
                        avg_volume_20d = EXCLUDED.avg_volume_20d,
                        sma_50d        = EXCLUDED.sma_50d,
                        computed_at    = EXCLUDED.computed_at
                """),
                {
                    "ticker":  ticker,
                    "avg_vol": vals["avg_volume_20d"],
                    "sma_50d": vals["sma_50d"],
                    "now":     now,
                },
            )
    logger.info("avg_volume_worker wrote %d rows", len(data))


def run() -> None:
    logger.info("avg_volume_worker starting run")

    if not ALPACA_API_KEY or not ALPACA_API_SECRET:
        logger.warning("Alpaca credentials not set — avg_volume_worker skipped")
        return

    try:
        data = _fetch_bars()
        if data:
            _write_to_db(data)
            logger.info("avg_volume_worker completed successfully")
        else:
            logger.warning("avg_volume_worker — no data returned")
    except Exception as e:
        logger.error("avg_volume_worker failed: %s", e)
        mark_failure(SOURCE, str(e))