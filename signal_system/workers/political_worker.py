# signal_system/workers/political_worker.py
"""
political_worker — runs every 6 hours.

Replaces Quiver Quantitative (no longer free) with two genuinely
free, no-key-required public APIs:

  1. SEC EDGAR Form 4 — insider trades (filed by corporate insiders)
  2. USASpending.gov  — federal contract awards by company

§4.2 intent preserved: use for sector bias and trend, NOT entry timing.
Disclosure lag still applies — Form 4 must be filed within 2 business
days of trade; contract awards may post days after signing.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential

from ..db import get_db
from ..health import mark_success, mark_failure
from ..config.watchlist import ALL_TICKERS, TICKER_SECTOR

logger = logging.getLogger(__name__)

SOURCE    = "political"
TICKER_SET = set(ALL_TICKERS)

HEADERS = {"User-Agent": "signal-system research@example.com"}  # SEC requires User-Agent


# ----------------------------------------------------------------
# SEC EDGAR — Form 4 insider filings
# Free, no key. Rate limit: 10 req/sec — we stay well under that.
# ----------------------------------------------------------------

EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=16), reraise=True)
def _fetch_edgar_form4() -> list[dict]:
    """
    Fetch recent Form 4 filings for watchlist tickers.
    Queries EDGAR full-text search — filters to filings mentioning
    our tickers in the last 2 days.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    items  = []
    now    = datetime.now(timezone.utc)

    # Batch by ticker — EDGAR search handles one query at a time
    for ticker in ALL_TICKERS:
        try:
            resp = requests.get(
                EDGAR_SEARCH,
                params={
                    "q":          f'"{ticker}"',
                    "dateRange":  "custom",
                    "startdt":    cutoff,
                    "forms":      "4",
                    "_source":    "file_date,display_names,period_of_report",
                    "hits.hits.total.value": 1,
                },
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])

            for hit in hits:
                src = hit.get("_source", {})
                items.append({
                    "ticker":        ticker,
                    "sector":        TICKER_SECTOR.get(ticker),
                    "event_type":    "insider_trade",
                    "size_value":    None,           # Form 4 amount needs deeper parse
                    "reported_date": src.get("period_of_report"),
                    "raw_json":      src,
                    "ingested_at":   now,
                })

        except Exception as e:
            logger.warning("edgar ticker=%s error: %s", ticker, e)
            continue

    logger.info("edgar form4 returned %d filings", len(items))
    return items


# ----------------------------------------------------------------
# USASpending.gov — federal contract awards
# Free, no key required.
# ----------------------------------------------------------------

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Map our watchlist companies to their DUNS/name fragments
# Only defense + industrials are likely to appear in gov contracts
CONTRACT_SEARCH_TERMS: dict[str, str] = {
    "LMT":  "Lockheed Martin",
    "RTX":  "Raytheon",
    "NOC":  "Northrop Grumman",
    "GD":   "General Dynamics",
    "LHX":  "L3Harris",
    "BA":   "Boeing",
    "GE":   "GE Aerospace",
    "CAT":  "Caterpillar",
    "XOM":  "ExxonMobil",
    "CVX":  "Chevron",
}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=16), reraise=True)
def _fetch_usaspending() -> list[dict]:
    """
    Fetch recent federal contract awards for watchlist companies.
    Looks back 7 days — contracts post with a delay.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now    = datetime.now(timezone.utc)
    items  = []

    for ticker, company_name in CONTRACT_SEARCH_TERMS.items():
        try:
            payload = {
                "filters": {
                    "award_type_codes": ["A", "B", "C", "D"],  # contracts only
                    "time_period": [{"start_date": cutoff, "end_date": today}],
                    "keyword": company_name,
                },
                "fields": ["Award ID", "Recipient Name", "Award Amount", "Award Date"],
                "limit": 5,
                "page":  1,
            }

            resp = requests.post(
                USASPENDING_URL,
                json=payload,
                headers={**HEADERS, "Content-Type": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])

            for award in results:
                amount = award.get("Award Amount")
                try:
                    amount = float(amount) if amount else None
                except (ValueError, TypeError):
                    amount = None

                items.append({
                    "ticker":        ticker,
                    "sector":        TICKER_SECTOR.get(ticker),
                    "event_type":    "gov_contract",
                    "size_value":    amount,
                    "reported_date": award.get("Award Date"),
                    "raw_json":      award,
                    "ingested_at":   now,
                })

        except Exception as e:
            logger.warning("usaspending ticker=%s error: %s", ticker, e)
            continue

    logger.info("usaspending returned %d contract awards", len(items))
    return items


# ----------------------------------------------------------------
# DB write
# ----------------------------------------------------------------

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
                {**item, "raw_json": json.dumps(item["raw_json"])},
            )
    logger.info("political_worker wrote %d events", len(items))


# ----------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------

def run() -> None:
    """
    Runs every 6 hours. Each source fetched independently —
    one failing does not block the other.
    """
    logger.info("political_worker starting run")
    all_items = []
    errors    = []

    for label, fetch_fn in [("edgar", _fetch_edgar_form4), ("usaspending", _fetch_usaspending)]:
        try:
            items = fetch_fn()
            all_items.extend(items)
        except Exception as e:
            logger.error("political source=%s failed: %s", label, e)
            errors.append(f"{label}: {e}")

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
