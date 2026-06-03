# signal_system/tasks.py
"""
Task functions called by the scheduler.
Plain Python — no Celery, no decorators.
All logic lives in the worker modules; these are thin wrappers with
the market-hours guard applied where needed.
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
    from .workers.political_worker import run  # stub — Week 2
    run()


def run_signal_engine():
    if not _is_market_hours():
        logger.debug("signal_engine skipped — outside market hours")
        return
    logger.info("signal_engine stub — Week 3")


def run_outcome_worker():
    logger.info("outcome_worker stub — Week 4")
