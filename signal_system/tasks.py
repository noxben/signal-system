# signal_system/tasks.py
"""
Task functions called by the scheduler.
Plain Python — no Celery, no decorators.

Market hours guard: Mon-Fri 09:30-16:00 ET only.
Political worker runs Mon-Fri any time (filings post outside market hours).
Avg volume + outcome workers run on cron — weekday-only via scheduler config.
"""

import logging
from datetime import datetime

import pytz

logger = logging.getLogger(__name__)

MARKET_TZ    = pytz.timezone("America/New_York")
MARKET_OPEN  = (9, 30)
MARKET_CLOSE = (16, 0)


def _is_market_hours() -> bool:
    """True only Mon-Fri 09:30-16:00 ET."""
    now = datetime.now(MARKET_TZ)
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return MARKET_OPEN <= t < MARKET_CLOSE


def _is_weekday() -> bool:
    """True Mon-Fri regardless of time."""
    return datetime.now(MARKET_TZ).weekday() < 5


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
    # Filings post any time but no point polling on weekends
    if not _is_weekday():
        logger.debug("political_worker skipped — weekend")
        return
    from .workers.political_worker import run
    run()


def run_signal_engine():
    if not _is_market_hours():
        logger.debug("signal_engine skipped — outside market hours")
        return
    from .engine.signal_engine import run
    run()


def run_avg_volume_worker():
    # Scheduler already uses cron Mon-Fri — guard here as safety net
    if not _is_weekday():
        logger.debug("avg_volume_worker skipped — weekend")
        return
    from .workers.avg_volume_worker import run
    run()


def run_outcome_worker():
    # Scheduler already uses cron Mon-Fri — guard here as safety net
    if not _is_weekday():
        logger.debug("outcome_worker skipped — weekend")
        return
    from .workers.outcome_worker import run
    run()
