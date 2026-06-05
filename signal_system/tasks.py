# signal_system/tasks.py
"""
Task functions called by the scheduler.
Plain Python — no Celery, no decorators.
All logic lives in the worker/engine modules; these are thin
wrappers with the market-hours guard applied where needed.
"""

import logging
from datetime import datetime

import pytz

logger = logging.getLogger(__name__)

MARKET_TZ    = pytz.timezone("America/New_York")
MARKET_OPEN  = (9, 30)
MARKET_CLOSE = (16, 0)


def _is_market_hours() -> bool:
    now = datetime.now(MARKET_TZ)
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t < MARKET_CLOSE


def run_market_worker():
    if not _is_market_hours():
        logger.debug("market_worker skipped — outside market hours")
        return
    from .workers.market_worker import run
    run()


def run_news_worker():
    if not _is_market_hours():
        logger.debug("news_worker skipped — outside market hours")
        return
    from .workers.news_worker import run
    run()


def run_political_worker():
    # Runs every 6h regardless of market hours — contracts/filings post anytime
    from .workers.political_worker import run
    run()


def run_signal_engine():
    if not _is_market_hours():
        logger.debug("signal_engine skipped — outside market hours")
        return
    from .engine.signal_engine import run
    run()


def run_avg_volume_worker():
    from .workers.avg_volume_worker import run
    run()


def run_outcome_worker():
    from .workers.outcome_worker import run
    run()
