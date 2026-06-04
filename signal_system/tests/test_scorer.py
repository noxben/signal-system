# signal_system/tests/test_scorer.py
"""
Tests for the scoring model — §7.
Verifies factor weights, pass threshold, and degraded-source zeroing.
"""

import pytest
from unittest.mock import patch


def make_factors(
    volume_spike=True,
    volume_ratio=3.0,
    sector_aligned=False,
    no_recent_news=False,
    repeat_spike=False,
    options_proxy=False,
    earnings_soon=False,
    late_entry=False,
    small_cap=False,
):
    return {
        "volume_spike":    volume_spike,
        "volume_ratio":    volume_ratio,
        "sector_aligned":  sector_aligned,
        "no_recent_news":  no_recent_news,
        "repeat_spike":    repeat_spike,
        "options_proxy":   options_proxy,
        "earnings_soon":   earnings_soon,
        "late_entry":      late_entry,
        "small_cap":       small_cap,
    }


def make_source_statuses(
    market="healthy", news="healthy",
    political="healthy", options_proxy="healthy"
):
    return {
        "market":        market,
        "news":          news,
        "political":     political,
        "options_proxy": options_proxy,
    }


class TestScoring:
    def test_volume_spike_only(self):
        from signal_system.engine.scorer import compute_score
        score, _ = compute_score(make_factors(), make_source_statuses())
        assert score == 2  # only volume spike

    def test_all_positive_factors(self):
        from signal_system.engine.scorer import compute_score
        factors = make_factors(
            sector_aligned=True,
            no_recent_news=True,
            repeat_spike=True,
            options_proxy=True,
        )
        score, _ = compute_score(factors, make_source_statuses())
        assert score == 9  # 2+2+2+2+1

    def test_earnings_penalty(self):
        from signal_system.engine.scorer import compute_score
        factors = make_factors(earnings_soon=True)
        score, _ = compute_score(factors, make_source_statuses())
        assert score == -1  # 2 - 3

    def test_late_entry_penalty(self):
        from signal_system.engine.scorer import compute_score
        factors = make_factors(late_entry=True)
        score, _ = compute_score(factors, make_source_statuses())
        assert score == 0   # 2 - 2

    def test_small_cap_penalty(self):
        from signal_system.engine.scorer import compute_score
        factors = make_factors(small_cap=True)
        score, _ = compute_score(factors, make_source_statuses())
        assert score == 1   # 2 - 1

    def test_pass_threshold(self):
        from signal_system.engine.scorer import compute_score, PASS_THRESHOLD
        # Need score >= 5 to surface to dashboard
        factors = make_factors(
            sector_aligned=True,
            no_recent_news=True,
        )
        score, _ = compute_score(factors, make_source_statuses())
        assert score >= PASS_THRESHOLD  # 2+2+2 = 6

    def test_degraded_news_zeroes_no_news_factor(self):
        """If news source is degraded, no_recent_news factor must be 0 — §5.1"""
        from signal_system.engine.scorer import compute_score
        factors  = make_factors(no_recent_news=True)
        statuses = make_source_statuses(news="degraded")
        score, breakdown = compute_score(factors, statuses)
        # no_recent_news should contribute 0, not +2
        assert breakdown.get("no_recent_news_contribution", 0) == 0
        assert score == 2  # only volume spike counts

    def test_degraded_political_zeroes_sector_factor(self):
        """If political source degraded, sector_aligned factor must be 0 — §5.1"""
        from signal_system.engine.scorer import compute_score
        factors  = make_factors(sector_aligned=True)
        statuses = make_source_statuses(political="degraded")
        score, breakdown = compute_score(factors, statuses)
        assert breakdown.get("sector_aligned_contribution", 0) == 0
        assert score == 2


class TestFactorsJson:
    def test_factors_json_contains_all_keys(self):
        """Every signal must record complete factors_json — §5"""
        from signal_system.engine.scorer import compute_score
        _, breakdown = compute_score(make_factors(), make_source_statuses())
        required_keys = {
            "volume_spike", "volume_ratio", "sector_aligned",
            "no_recent_news", "repeat_spike", "options_proxy",
            "earnings_soon", "late_entry", "small_cap",
        }
        assert required_keys.issubset(set(breakdown.keys()))
