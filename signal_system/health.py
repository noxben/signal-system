# signal_system/health.py
"""
Workers call mark_success() or mark_failure() on every run.
Dashboard reads source_health table directly.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from .db import get_db

logger = logging.getLogger(__name__)


def mark_success(source: str) -> None:
    """Reset failure count and stamp last_success_at."""
    with get_db() as db:
        db.execute(
            text("""
                UPDATE source_health
                SET status = 'healthy',
                    last_success_at = :now,
                    consecutive_failures = 0,
                    last_error = NULL
                WHERE source = :source
            """),
            {"source": source, "now": datetime.now(timezone.utc)},
        )


def mark_failure(source: str, error: str) -> None:
    """
    Increment failure count. After 3 consecutive failures,
    set status = 'degraded' per §5.1.
    """
    with get_db() as db:
        db.execute(
            text("""
                UPDATE source_health
                SET consecutive_failures = consecutive_failures + 1,
                    last_error = :error,
                    status = CASE
                        WHEN consecutive_failures + 1 >= 3 THEN 'degraded'
                        ELSE status
                    END
                WHERE source = :source
            """),
            {"source": source, "error": str(error)},
        )
    logger.warning("source=%s failure recorded: %s", source, error)


def get_source_statuses() -> dict[str, str]:
    """Returns {source: status} for all 4 sources. Used by signal engine."""
    with get_db() as db:
        rows = db.execute(
            text("SELECT source, status FROM source_health")
        ).fetchall()
    return {row.source: row.status for row in rows}


def any_degraded(statuses: dict[str, str]) -> bool:
    return any(v == "degraded" for v in statuses.values())
