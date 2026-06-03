# signal_system/scheduler.py
"""
APScheduler setup — replaces Celery + Redis entirely.
Runs in-process; no broker, no extra services.

Start the scheduler:
    python -m signal_system.scheduler

Or import and call start() from a FastAPI lifespan / main entry point.
"""

import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

from .tasks import (
    run_market_worker,
    run_news_worker,
    run_political_worker,
    run_signal_engine,
    run_outcome_worker,
)

load_dotenv()
logger = logging.getLogger(__name__)


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="America/New_York")

    # market data — every 5 min
    scheduler.add_job(
        run_market_worker,
        trigger=IntervalTrigger(seconds=300),
        id="market_worker",
        name="Market data (yfinance)",
        max_instances=1,        # never overlap
        misfire_grace_time=60,  # if delayed up to 60s, still run
    )

    # news — every 15 min
    scheduler.add_job(
        run_news_worker,
        trigger=IntervalTrigger(seconds=900),
        id="news_worker",
        name="News RSS + spaCy NER",
        max_instances=1,
        misfire_grace_time=120,
    )

    # political / Quiver — every 6 hours
    scheduler.add_job(
        run_political_worker,
        trigger=IntervalTrigger(seconds=21600),
        id="political_worker",
        name="Quiver Quantitative",
        max_instances=1,
        misfire_grace_time=300,
    )

    # signal engine — every 5 min
    scheduler.add_job(
        run_signal_engine,
        trigger=IntervalTrigger(seconds=300),
        id="signal_engine",
        name="Signal engine",
        max_instances=1,
        misfire_grace_time=60,
    )

    # outcome worker — daily at 17:00 ET
    scheduler.add_job(
        run_outcome_worker,
        trigger=CronTrigger(hour=17, minute=0),
        id="outcome_worker",
        name="Outcome worker",
        max_instances=1,
    )

    return scheduler


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    logger.info("Starting scheduler")
    scheduler = build_scheduler()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
