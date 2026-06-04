# signal_system/tests/test_outcome.py
"""
Tests for outcome labelling logic — §12.
No DB or network calls — pure unit tests on _compute_outcome.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone


def make_df(closes: list[float]) -> pd.DataFrame:
    """Build a minimal DataFrame with Close prices."""
    return pd.DataFrame({"Close": closes})


class TestOutcomeLabels:
    def test_hit_clean(self):
        """Price hits +3% on day 2 with no prior drawdown."""
        from signal_system.workers.outcome_worker import _compute_outcome
        entry = 100.0
        df    = make_df([101.0, 103.5, 102.0, 101.5, 100.5])
        label, mfe, dd = _compute_outcome(entry, df)
        assert label == "hit"

    def test_hit_blocked_by_drawdown(self):
        """Price hits +3% on day 2 but day 1 had -2% drawdown — should be mfe not hit."""
        from signal_system.workers.outcome_worker import _compute_outcome
        entry = 100.0
        df    = make_df([97.5, 103.5, 102.0, 101.0, 100.0])  # day1=-2.5%, day2=+3.5%
        label, mfe, dd = _compute_outcome(entry, df)
        assert label == "mfe"  # +3% reached but drawdown blocked 'hit'

    def test_mfe_after_3_days(self):
        """Price doesn't hit +3% in first 3 days but does on day 5."""
        from signal_system.workers.outcome_worker import _compute_outcome
        entry = 100.0
        df    = make_df([101.0, 101.5, 102.0, 102.5, 103.5])
        label, mfe, dd = _compute_outcome(entry, df)
        assert label == "mfe"

    def test_fail(self):
        """Price never reaches +3%."""
        from signal_system.workers.outcome_worker import _compute_outcome
        entry = 100.0
        df    = make_df([100.5, 101.0, 101.5, 101.0, 100.5])
        label, mfe, dd = _compute_outcome(entry, df)
        assert label == "fail"

    def test_mfe_value_computed(self):
        from signal_system.workers.outcome_worker import _compute_outcome
        entry = 100.0
        df    = make_df([101.0, 104.0, 103.0, 102.0, 101.0])
        _, mfe, _ = _compute_outcome(entry, df)
        assert abs(mfe - 4.0) < 0.01

    def test_max_drawdown_computed(self):
        from signal_system.workers.outcome_worker import _compute_outcome
        entry = 100.0
        df    = make_df([99.0, 97.0, 98.0, 100.0, 101.0])
        _, _, dd = _compute_outcome(entry, df)
        assert abs(dd - (-3.0)) < 0.01

    def test_empty_df_returns_none(self):
        from signal_system.workers.outcome_worker import _compute_outcome
        label, mfe, dd = _compute_outcome(100.0, make_df([]))
        assert label is None
        assert mfe == 0.0
        assert dd  == 0.0

    def test_zero_entry_price_returns_none(self):
        from signal_system.workers.outcome_worker import _compute_outcome
        df = make_df([100.0, 101.0, 102.0])
        label, mfe, dd = _compute_outcome(0.0, df)
        assert label is None
