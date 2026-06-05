# signal_system/scheduler.py
"""
Entry point — runs the APScheduler and Flask dashboard in the same process.
Flask runs in a background thread; APScheduler runs on the main thread.

Start:
    python -m signal_system.scheduler
"""

import logging
import os
import threading

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

from .tasks import (
    run_market_worker,
    run_news_worker,
    run_political_worker,
    run_signal_engine,
    run_avg_volume_worker,
    run_outcome_worker,
)

load_dotenv()
logger = logging.getLogger(__name__)

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", 5000))


def _start_dashboard():
    """Run Flask in a daemon thread — exits when main process exits."""
    from .dashboard.app import create_app
    app = create_app()
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, use_reloader=False)


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="America/New_York")

    # Market data — every 5 min during market hours
    scheduler.add_job(
        run_market_worker,
        trigger=IntervalTrigger(seconds=300),
        id="market_worker",
        name="Market data (Alpaca)",
        max_instances=1,
        misfire_grace_time=60,
    )

    # News RSS — every 15 min during market hours
    scheduler.add_job(
        run_news_worker,
        trigger=IntervalTrigger(seconds=900),
        id="news_worker",
        name="News RSS + spaCy NER",
        max_instances=1,
        misfire_grace_time=120,
    )

    # Political — every 6 hours, any time
    scheduler.add_job(
        run_political_worker,
        trigger=IntervalTrigger(seconds=21600),
        id="political_worker",
        name="Political (EDGAR + USASpending)",
        max_instances=1,
        misfire_grace_time=300,
    )

    # Signal engine — every 5 min during market hours
    scheduler.add_job(
        run_signal_engine,
        trigger=IntervalTrigger(seconds=300),
        id="signal_engine",
        name="Signal engine",
        max_instances=1,
        misfire_grace_time=60,
    )

    # 20-day avg volume — once daily at 09:35 ET (just after open)
    scheduler.add_job(
        run_avg_volume_worker,
        trigger=CronTrigger(hour=9, minute=35, timezone="America/New_York"),
        id="avg_volume_worker",
        name="Avg volume (20d)",
        max_instances=1,
    )

    # Outcome worker — daily at 17:00 ET
    scheduler.add_job(
        run_outcome_worker,
        trigger=CronTrigger(hour=17, minute=0, timezone="America/New_York"),
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

    # Start dashboard in background thread
    dash_thread = threading.Thread(target=_start_dashboard, daemon=True)
    dash_thread.start()
    logger.info("Dashboard running on http://0.0.0.0:%d", DASHBOARD_PORT)

    # Start scheduler on main thread (blocking)
    logger.info("Starting scheduler")
    scheduler = build_scheduler()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
