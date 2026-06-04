# signal_system/tests/test_signal_engine.py
"""
Tests for signal engine logic that doesn't require DB or network.
Focuses on duplicate suppression and cooldown rules — §9.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock


class TestDuplicateSuppression:
    """§9 — 24h cooldown, exception if new score >= previous + 2."""

    def test_no_prior_signal_not_suppressed(self):
        from signal_system.engine.signal_engine import _should_suppress
        assert _should_suppress(
            ticker="NVDA",
            new_score=6,
            last_signal_time=None,
            last_signal_score=None,
        ) is False

    def test_within_cooldown_suppressed(self):
        from signal_system.engine.signal_engine import _should_suppress
        recent = datetime.now(timezone.utc) - timedelta(hours=12)
        assert _should_suppress(
            ticker="NVDA",
            new_score=6,
            last_signal_time=recent,
            last_signal_score=6,
        ) is True

    def test_outside_cooldown_not_suppressed(self):
        from signal_system.engine.signal_engine import _should_suppress
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        assert _should_suppress(
            ticker="NVDA",
            new_score=6,
            last_signal_time=old,
            last_signal_score=6,
        ) is False

    def test_score_jump_exception(self):
        """Score >= previous + 2 overrides cooldown — §9."""
        from signal_system.engine.signal_engine import _should_suppress
        recent = datetime.now(timezone.utc) - timedelta(hours=6)
        assert _should_suppress(
            ticker="NVDA",
            new_score=8,       # previous was 6 — jump of +2
            last_signal_time=recent,
            last_signal_score=6,
        ) is False

    def test_score_jump_below_exception_threshold(self):
        """Score jump of only +1 does NOT override cooldown."""
        from signal_system.engine.signal_engine import _should_suppress
        recent = datetime.now(timezone.utc) - timedelta(hours=6)
        assert _should_suppress(
            ticker="NVDA",
            new_score=7,       # previous was 6 — jump of only +1
            last_signal_time=recent,
            last_signal_score=6,
        ) is True


class TestMarketHoursGuard:
    def test_weekday_market_hours(self):
        from signal_system.tasks import _is_market_hours
        import pytz
        tz  = pytz.timezone("America/New_York")
        # Monday 10:30 AM ET
        dt  = tz.localize(datetime(2025, 1, 6, 10, 30))
        with patch("signal_system.tasks.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            assert _is_market_hours() is True

    def test_weekend_rejected(self):
        from signal_system.tasks import _is_market_hours
        import pytz
        tz  = pytz.timezone("America/New_York")
        # Saturday 10:30 AM ET
        dt  = tz.localize(datetime(2025, 1, 4, 10, 30))
        with patch("signal_system.tasks.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            assert _is_market_hours() is False

    def test_before_open_rejected(self):
        from signal_system.tasks import _is_market_hours
        import pytz
        tz  = pytz.timezone("America/New_York")
        # Monday 9:00 AM ET — before 9:30 open
        dt  = tz.localize(datetime(2025, 1, 6, 9, 0))
        with patch("signal_system.tasks.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            assert _is_market_hours() is False

    def test_after_close_rejected(self):
        from signal_system.tasks import _is_market_hours
        import pytz
        tz  = pytz.timezone("America/New_York")
        # Monday 4:01 PM ET — after close
        dt  = tz.localize(datetime(2025, 1, 6, 16, 1))
        with patch("signal_system.tasks.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            assert _is_market_hours() is False
