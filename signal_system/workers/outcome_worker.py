# signal_system/workers/outcome_worker.py
"""
outcome_worker — runs daily at 17:00 ET.

For every approved signal with missing outcome data:
  1. Fetch price at 1d, 3d, 5d after entry using yfinance
  2. Compute MFE and max drawdown within 5d window
  3. Set outcome_label: 'hit' | 'mfe' | 'fail'
  4. Close any open paper trades that have hit exit conditions

§12 outcome definitions:
  hit  — price +3% within 3 days AND no -2% drawdown before reaching +3%
  mfe  — price reached +3% at any point within 5 days (even if not captured)
  fail — neither condition met within 5 days

§13.1 exit rules:
  take_profit — +5% gain
  stop_loss   — -3% loss
  time_exit   — market close day 3
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
import pandas as pd
from sqlalchemy import text

from ..db import get_db
from ..health import mark_success, mark_failure

logger = logging.getLogger(__name__)

SOURCE = "outcome"

TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", 5.0))
STOP_LOSS_PCT   = float(os.getenv("STOP_LOSS_PCT",   3.0))
MAX_HOLD_DAYS   = int(os.getenv("MAX_HOLD_DAYS",     3))
HIT_TARGET_PCT  = 3.0   # §12 — outcome hit threshold
HIT_DAYS        = 3     # §12 — must reach within 3 days
MFE_DAYS        = 5     # §12 — MFE window


def _fetch_price_history(ticker: str, entry_time: datetime) -> Optional[pd.DataFrame]:
    """
    Fetch daily bars from entry_time to entry_time + MFE_DAYS via Alpaca.
    Returns DataFrame with Close column or None on failure.
    """
    api_key    = os.getenv("ALPACA_API_KEY", "")
    api_secret = os.getenv("ALPACA_API_SECRET", "")
    if not api_key or not api_secret:
        logger.warning("Alpaca credentials not set — outcome worker cannot fetch prices")
        return None
    try:
        start = entry_time.date().isoformat()
        end   = (entry_time + timedelta(days=MFE_DAYS + 3)).date().isoformat()
        url   = f"https://data.alpaca.markets/v2/stocks/{ticker}/bars"
        resp  = requests.get(
            url,
            headers={
                "APCA-API-KEY-ID":     api_key,
                "APCA-API-SECRET-KEY": api_secret,
            },
            params={
                "start":     start,
                "end":       end,
                "timeframe": "1Day",
                "feed":      "iex",
            },
            timeout=15,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
        if not bars:
            logger.warning("ticker=%s no price history from Alpaca", ticker)
            return None
        closes = [b["c"] for b in bars]
        return pd.DataFrame({"Close": closes})
    except Exception as e:
        logger.error("ticker=%s price history fetch failed: %s", ticker, e)
        return None


def _nth_trading_day_price(df: pd.DataFrame, n: int) -> Optional[float]:
    """Return close price on the nth trading day (1-indexed). None if not enough data."""
    if len(df) >= n:
        return float(df.iloc[n - 1]["Close"])
    return None


def _compute_outcome(
    entry_price: float,
    df: pd.DataFrame,
) -> tuple[Optional[str], float, float]:
    """
    Returns (outcome_label, mfe_value, max_drawdown).
    §12 logic:
      hit  — close >= +3% within first 3 trading days AND
              no close <= -2% before that point
      mfe  — close >= +3% at any point in 5 trading days
      fail — neither
    """
    if df.empty or entry_price <= 0:
        return None, 0.0, 0.0

    closes      = df["Close"].values[:MFE_DAYS]
    pct_changes = [(c - entry_price) / entry_price * 100 for c in closes]

    mfe_pct      = max(pct_changes) if pct_changes else 0.0
    drawdown_pct = min(pct_changes) if pct_changes else 0.0

    # Hit: +3% within 3 days with no -2% drawdown before it
    hit = False
    for i, pct in enumerate(pct_changes[:HIT_DAYS]):
        prior_drawdown = min(pct_changes[:i]) if i > 0 else 0.0
        if pct >= HIT_TARGET_PCT and prior_drawdown > -2.0:
            hit = True
            break

    if hit:
        label = "hit"
    elif mfe_pct >= HIT_TARGET_PCT:
        label = "mfe"
    else:
        label = "fail"

    return label, round(mfe_pct, 4), round(drawdown_pct, 4)


def _close_paper_trade(
    trade_id: str,
    exit_price: float,
    exit_reason: str,
    entry_price: float,
    position_size: float,
    exit_time: datetime,
) -> None:
    """Compute PnL and close the trade row."""
    pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price else 0.0
    pnl_usd = position_size * (pnl_pct / 100)

    with get_db() as db:
        db.execute(
            text("""
                UPDATE paper_trades SET
                    exit_price  = :exit_price,
                    exit_time   = :exit_time,
                    exit_reason = :exit_reason,
                    pnl_usd     = :pnl_usd,
                    pnl_pct     = :pnl_pct,
                    status      = 'closed'
                WHERE trade_id = :trade_id
            """),
            {
                "exit_price":  exit_price,
                "exit_time":   exit_time,
                "exit_reason": exit_reason,
                "pnl_usd":     round(pnl_usd, 2),
                "pnl_pct":     round(pnl_pct, 4),
                "trade_id":    trade_id,
            },
        )
    logger.info(
        "trade=%s closed reason=%s pnl=%.2f%% ($%.2f)",
        trade_id, exit_reason, pnl_pct, pnl_usd,
    )


def _process_signal(signal: dict) -> None:
    """Process one approved signal — fill prices, set outcome, close trade."""
    ticker      = signal["ticker"]
    entry_price = float(signal["entry_price"])
    entry_time  = signal["approval_timestamp"]
    signal_id   = str(signal["signal_id"])

    if not entry_price or not entry_time:
        logger.warning("signal=%s missing entry_price or approval_timestamp — skipped", signal_id)
        return

    df = _fetch_price_history(ticker, entry_time)
    if df is None:
        return

    now = datetime.now(timezone.utc)

    # Price at 1d, 3d, 5d
    price_1d = _nth_trading_day_price(df, 1)
    price_3d = _nth_trading_day_price(df, 3)
    price_5d = _nth_trading_day_price(df, 5)

    # Only set outcome once we have enough days of data
    days_elapsed = (now - entry_time).days
    outcome_label, mfe_value, max_drawdown = None, 0.0, 0.0

    if days_elapsed >= MFE_DAYS and len(df) >= 3:
        outcome_label, mfe_value, max_drawdown = _compute_outcome(entry_price, df)

    # Update signal row
    with get_db() as db:
        db.execute(
            text("""
                UPDATE signals SET
                    price_1d      = :p1,
                    price_3d      = :p3,
                    price_5d      = :p5,
                    mfe_value     = :mfe,
                    max_drawdown  = :dd,
                    outcome_label = :label
                WHERE signal_id = :id
            """),
            {
                "p1":    price_1d,
                "p3":    price_3d,
                "p5":    price_5d,
                "mfe":   mfe_value,
                "dd":    max_drawdown,
                "label": outcome_label,
                "id":    signal_id,
            },
        )

    logger.info(
        "signal=%s ticker=%s outcome=%s mfe=%.2f%% drawdown=%.2f%%",
        signal_id, ticker, outcome_label, mfe_value, max_drawdown,
    )

    # Close open paper trade if conditions met — §13.1
    if not signal.get("paper_trade_id"):
        return

    with get_db() as db:
        trade = db.execute(
            text("""
                SELECT trade_id, entry_price, position_size_usd, status
                FROM paper_trades
                WHERE trade_id = :tid AND status = 'open'
            """),
            {"tid": str(signal["paper_trade_id"])},
        ).fetchone()

    if not trade:
        return  # already closed

    t_entry = float(trade.entry_price)
    size    = float(trade.position_size_usd)

    # Determine exit using daily closes in order
    closes = list(df["Close"].values[:MAX_HOLD_DAYS])
    exit_price  = None
    exit_reason = None
    exit_time   = now

    for i, close in enumerate(closes):
        pct = (close - t_entry) / t_entry * 100
        if pct >= TAKE_PROFIT_PCT:
            exit_price  = float(close)
            exit_reason = "take_profit"
            exit_time   = entry_time + timedelta(days=i + 1)
            break
        if pct <= -STOP_LOSS_PCT:
            exit_price  = float(close)
            exit_reason = "stop_loss"
            exit_time   = entry_time + timedelta(days=i + 1)
            break

    # Time exit — day 3 close if no other trigger
    if not exit_price and days_elapsed >= MAX_HOLD_DAYS and price_3d:
        exit_price  = price_3d
        exit_reason = "time_exit"
        exit_time   = entry_time + timedelta(days=MAX_HOLD_DAYS)

    if exit_price and exit_reason:
        _close_paper_trade(
            trade_id      = str(trade.trade_id),
            exit_price    = exit_price,
            exit_reason   = exit_reason,
            entry_price   = t_entry,
            position_size = size,
            exit_time     = exit_time,
        )


def run() -> None:
    """
    Entry point — called daily at 17:00 ET by scheduler.
    Processes all approved signals missing outcome data.
    """
    logger.info("outcome_worker starting run")
    errors = []

    try:
        with get_db() as db:
            rows = db.execute(
                text("""
                    SELECT
                        signal_id, ticker, entry_price,
                        approval_timestamp, paper_trade_id,
                        outcome_label
                    FROM signals
                    WHERE approved = true
                      AND entry_price IS NOT NULL
                      AND approval_timestamp IS NOT NULL
                      AND (
                          outcome_label IS NULL
                          OR price_5d IS NULL
                      )
                    ORDER BY approval_timestamp ASC
                """)
            ).fetchall()

        signals = [dict(r._mapping) for r in rows]
        logger.info("outcome_worker processing %d signals", len(signals))

        for signal in signals:
            try:
                _process_signal(signal)
            except Exception as e:
                logger.error("signal=%s processing error: %s", signal["signal_id"], e)
                errors.append(str(e))

    except Exception as e:
        logger.error("outcome_worker DB query failed: %s", e)
        errors.append(str(e))

    if errors:
        mark_failure(SOURCE, "; ".join(errors[:3]))  # log first 3 only
    else:
        mark_success(SOURCE)
        logger.info("outcome_worker completed successfully")
