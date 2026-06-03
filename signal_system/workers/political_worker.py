# signal_system/workers/political_worker.py
"""
political_worker — runs every 6 hours.

Polls Quiver Quantitative free tier for:
  - Congressional trades
  - Government contracts
  - Lobbying activity

Writes raw events to political_events table.
Updates source_health on every run.

§4.2: Congressional trade disclosure lag is up to 45 days.
Use for sector bias and trend — NOT entry timing.

§5.1: 3 retries with exponential backoff.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential

from ..db import get_db
from ..health import mark_success, mark_failure
from ..config.watchlist import ALL_TICKERS, TICKER_SECTOR

logger = logging.getLogger(__name__)

SOURCE = "political"

QUIVER_BASE = "https://api.quiverquant.com/beta"
QUIVER_API_KEY = os.getenv("QUIVER_API_KEY", "")

# Endpoints available on Quiver free tier
ENDPOINTS: dict[str, str] = {
    "congress":  "/live/congresstrading",
    "contracts": "/live/govcontracts",
    "lobbying":  "/live/lobbying",
}

TICKER_SET = set(ALL_TICKERS)


def _headers() -> dict:
    return {
        "Accept": "application/json",
        "Authorization": f"Token {QUIVER_API_KEY}",
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    reraise=True,
)
def _fetch_endpoint(event_type: str, path: str) -> list[dict]:
    """
    Fetch one Quiver endpoint. Returns list of normalised event dicts.
    Only keeps rows where ticker is on our watchlist.
    """
    url = f"{QUIVER_BASE}{path}"
    resp = requests.get(url, headers=_headers(), timeout=15)

    if resp.status_code == 401:
        raise ValueError("Quiver API key invalid or missing — check QUIVER_API_KEY in .env")
    if resp.status_code == 429:
        raise ValueError("Quiver rate limit hit — free tier allows limited calls")

    resp.raise_for_status()

    raw   = resp.json()
    now   = datetime.now(timezone.utc)
    items = []

    for row in raw:
        ticker = (row.get("Ticker") or row.get("ticker") or "").upper().strip()

        # Only care about watchlist tickers
        if ticker not in TICKER_SET:
            continue

        # Normalise size value — field name varies by endpoint
        size_value = (
            row.get("Amount")
            or row.get("Amount_Low")
            or row.get("ContractAmount")
            or row.get("amount")
            or None
        )
        if size_value:
            try:
                size_value = float(str(size_value).replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                size_value = None

        # Reported/filed date — used for disclosure lag awareness
        reported_date = (
            row.get("TransactionDate")
            or row.get("Date")
            or row.get("ReportDate")
            or None
        )

        items.append({
            "ticker":        ticker,
            "sector":        TICKER_SECTOR.get(ticker),
            "event_type":    event_type,      # 'congress' | 'contracts' | 'lobbying'
            "size_value":    size_value,
            "reported_date": reported_date,
            "raw_json":      row,             # keep full row for debugging
            "ingested_at":   now,
        })

    logger.info("quiver endpoint=%s returned %d watchlist events", event_type, len(items))
    return items


def _write_to_db(items: list[dict]) -> None:
    if not items:
        return

    import json

    with get_db() as db:
        for item in items:
            db.execute(
                text("""
                    INSERT INTO political_events
                        (ticker, sector, event_type, size_value,
                         reported_date, raw_json, ingested_at)
                    VALUES
                        (:ticker, :sector, :event_type, :size_value,
                         :reported_date, :raw_json, :ingested_at)
                """),
                {
                    **item,
                    "raw_json": json.dumps(item["raw_json"]),
                },
            )

    logger.info("political_worker wrote %d events", len(items))


def run() -> None:
    """
    Entry point called by scheduler every 6 hours.
    Each endpoint is fetched independently — partial success is still useful.
    §4.2: data used for sector bias only, not entry timing.
    """
    if not QUIVER_API_KEY:
        logger.warning("QUIVER_API_KEY not set — political_worker skipped")
        mark_failure(SOURCE, "QUIVER_API_KEY not configured")
        return

    logger.info("political_worker starting run")
    all_items = []
    errors    = []

    for event_type, path in ENDPOINTS.items():
        try:
            items = _fetch_endpoint(event_type, path)
            all_items.extend(items)
        except Exception as e:
            logger.error("quiver endpoint=%s failed: %s", event_type, e)
            errors.append(f"{event_type}: {e}")

    if all_items:
        try:
            _write_to_db(all_items)
        except Exception as e:
            errors.append(f"db_write: {e}")
            logger.error("political_worker DB write failed: %s", e)

    if errors:
        mark_failure(SOURCE, "; ".join(errors))
    else:
        mark_success(SOURCE)
        logger.info("political_worker completed successfully")
