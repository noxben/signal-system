# signal_system/tests/test_filters.py
"""
Tests for hard filters — §8.
These must pass before any signal reaches scoring.
"""

import pytest
from unittest.mock import patch, MagicMock


# ── Helpers ──────────────────────────────────────────────────

def make_market_row(
    ticker="NVDA",
    price=500.0,
    volume=5_000_000,
    avg_volume_20d=2_000_000,
    pct_change=1.0,
    market_cap=1_200_000_000_000,
):
    return {
        "ticker":        ticker,
        "price":         price,
        "volume":        volume,
        "avg_volume_20d": avg_volume_20d,
        "pct_change":    pct_change,
        "market_cap":    market_cap,
    }


# ── Tests ─────────────────────────────────────────────────────

class TestLiquidityFilter:
    def test_passes_high_volume(self):
        from signal_system.engine.filters import passes_liquidity
        assert passes_liquidity(make_market_row(avg_volume_20d=1_000_000)) is True

    def test_fails_low_volume(self):
        from signal_system.engine.filters import passes_liquidity
        assert passes_liquidity(make_market_row(avg_volume_20d=400_000)) is False

    def test_boundary_exactly_500k(self):
        from signal_system.engine.filters import passes_liquidity
        # 500k is the minimum — exactly at boundary should pass
        assert passes_liquidity(make_market_row(avg_volume_20d=500_000)) is True


class TestMarketCapFilter:
    def test_passes_large_cap(self):
        from signal_system.engine.filters import passes_market_cap
        assert passes_market_cap(make_market_row(market_cap=500_000_000_000)) is True

    def test_fails_small_cap(self):
        from signal_system.engine.filters import passes_market_cap
        assert passes_market_cap(make_market_row(market_cap=1_000_000_000)) is False

    def test_fails_none_market_cap(self):
        from signal_system.engine.filters import passes_market_cap
        row = make_market_row()
        row["market_cap"] = None
        assert passes_market_cap(row) is False


class TestLateEntryFilter:
    def test_passes_small_move(self):
        from signal_system.engine.filters import passes_late_entry
        assert passes_late_entry(make_market_row(pct_change=3.0)) is True

    def test_fails_large_move(self):
        from signal_system.engine.filters import passes_late_entry
        assert passes_late_entry(make_market_row(pct_change=6.0)) is False

    def test_passes_negative_move(self):
        from signal_system.engine.filters import passes_late_entry
        assert passes_late_entry(make_market_row(pct_change=-2.0)) is True


class TestEarningsSoonFilter:
    def test_no_earnings_passes(self):
        from signal_system.engine.filters import earnings_soon
        with patch("signal_system.engine.filters.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.calendar = {}
            assert earnings_soon("NVDA") is False

    def test_earnings_within_7_days_fails(self):
        from signal_system.engine.filters import earnings_soon
        from datetime import datetime, timedelta, timezone
        soon = datetime.now(timezone.utc) + timedelta(days=5)
        with patch("signal_system.engine.filters.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.calendar = {"Earnings Date": [soon]}
            assert earnings_soon("NVDA") is True

    def test_earnings_outside_window_passes(self):
        from signal_system.engine.filters import earnings_soon
        from datetime import datetime, timedelta, timezone
        far = datetime.now(timezone.utc) + timedelta(days=30)
        with patch("signal_system.engine.filters.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.calendar = {"Earnings Date": [far]}
            assert earnings_soon("NVDA") is False
