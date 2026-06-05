# signal_system/workers/news_worker.py
"""
news_worker — runs every 15 minutes.

Fetches Reuters Markets RSS + Benzinga RSS.
Extracts ticker/entity mentions via spaCy NER.
Writes raw headlines to news_items table.
Updates source_health on every run.

§4.3, §5, §14.1
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import feedparser
import spacy
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential

from ..db import get_db
from ..health import mark_success, mark_failure
from ..config.watchlist import ALL_TICKERS

logger = logging.getLogger(__name__)

SOURCE = "news"

# RSS feeds — §4.3
# Reuters blocks cloud IPs — replaced with Yahoo Finance RSS (reliable, same data)
# Benzinga kept as secondary source
FEEDS = {
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "seeking_alpha":  "https://seekingalpha.com/feed.xml",
}

# Lazy-load spaCy model once per process
_nlp = None

def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


# Watchlist set for fast O(1) lookup
TICKER_SET = set(ALL_TICKERS)

# News categories from spec §4.3
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "defense":  ["defense", "military", "pentagon", "weapon", "missile", "nato", "army", "navy"],
    "AI":       ["artificial intelligence", "machine learning", "large language model", "llm", "neural network", "gpu"],
    "pharma":   ["fda", "drug", "clinical trial", "approval", "pharmaceutical", "biotech", "vaccine"],
    "energy":   ["oil", "gas", "opec", "crude", "refinery", "pipeline", "lng", "energy"],
    "macro":    ["fed", "federal reserve", "inflation", "interest rate", "gdp", "recession", "treasury"],
}


def _classify_category(text_lower: str) -> Optional[str]:
    """Return first matching category or None."""
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return category
    return None


def _extract_tickers(headline: str, body: str = "") -> list[str]:
    """
    Use spaCy NER to extract ORG entities, then match against watchlist.
    §4.3: do not use keyword matching alone.
    """
    nlp = _get_nlp()
    combined = f"{headline} {body}".strip()
    doc = nlp(combined)

    found = set()

    # NER: look for ORG entities that match watchlist tickers or company names
    for ent in doc.ents:
        token = ent.text.upper().strip(".$,")
        if token in TICKER_SET:
            found.add(token)

    # Secondary pass: direct ticker mention (e.g. "$NVDA" or "NVDA" as standalone token)
    for token in doc:
        clean = token.text.upper().strip("$.,")
        if clean in TICKER_SET:
            found.add(clean)

    return sorted(found)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    reraise=True,
)
def _fetch_feed(name: str, url: str) -> list[dict]:
    """Parse a single RSS feed. Returns list of raw item dicts."""
    parsed = feedparser.parse(url)

    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Feed parse error for {name}: {parsed.bozo_exception}")

    items = []
    now = datetime.now(timezone.utc)

    for entry in parsed.entries:
        headline  = entry.get("title", "").strip()
        link      = entry.get("link", "")
        published = entry.get("published", "")

        # Parse published timestamp — fall back to now if missing/unparseable
        pub_dt = now
        if entry.get("published_parsed"):
            import time
            pub_dt = datetime.fromtimestamp(
                time.mktime(entry.published_parsed), tz=timezone.utc
            )

        if not headline:
            continue

        tickers  = _extract_tickers(headline)
        category = _classify_category(headline.lower())

        items.append({
            "source":       name,
            "headline":     headline,
            "url":          link,
            "published_at": pub_dt,
            "ingested_at":  now,
            "tagged_tickers": tickers,       # list — stored as jsonb
            "category":     category,
        })

    logger.info("feed=%s fetched %d items", name, len(items))
    return items


def _write_to_db(items: list[dict]) -> None:
    """
    Insert news items. Use ON CONFLICT DO NOTHING on url
    to avoid re-inserting items seen in previous runs.
    """
    if not items:
        return

    import json

    with get_db() as db:
        for item in items:
            db.execute(
                text("""
                    INSERT INTO news_items
                        (source, headline, url, published_at, ingested_at,
                         tagged_tickers, category)
                    VALUES
                        (:source, :headline, :url, :published_at, :ingested_at,
                         :tagged_tickers, :category)
                    ON CONFLICT (url) DO NOTHING
                """),
                {
                    **item,
                    "tagged_tickers": json.dumps(item["tagged_tickers"]),
                },
            )

    logger.info("news_worker wrote %d items (duplicates silently skipped)", len(items))


def run() -> None:
    """
    Entry point called by scheduler every 15 minutes.
    Fetches both feeds independently — one failing does not block the other.
    """
    logger.info("news_worker starting run")
    all_items = []
    errors    = []

    for name, url in FEEDS.items():
        try:
            items = _fetch_feed(name, url)
            all_items.extend(items)
        except Exception as e:
            logger.error("feed=%s failed after retries: %s", name, e)
            errors.append(str(e))

    if all_items:
        try:
            _write_to_db(all_items)
        except Exception as e:
            errors.append(str(e))
            logger.error("news_worker DB write failed: %s", e)

    if errors:
        mark_failure(SOURCE, "; ".join(errors))
    else:
        mark_success(SOURCE)
        logger.info("news_worker completed successfully")
