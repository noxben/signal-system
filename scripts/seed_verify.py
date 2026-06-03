#!/usr/bin/env python3
"""
scripts/seed_verify.py

Verifies all 37 watchlist tickers are reachable via yfinance
and meet the hard-filter minimums before the system goes live.

Run once at deploy time. Not part of the live pipeline.

Usage:
    python scripts/seed_verify.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
from signal_system.config.watchlist import WATCHLIST, ALL_TICKERS

MIN_MARKET_CAP   = int(os.getenv("MIN_MARKET_CAP",   2_000_000_000))
MIN_AVG_VOLUME   = int(os.getenv("MIN_AVG_DAILY_VOLUME", 500_000))

print(f"Verifying {len(ALL_TICKERS)} tickers...\n")

failures = []

for sector, tickers in WATCHLIST.items():
    print(f"  [{sector}]")
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            cap  = info.get("marketCap", 0) or 0
            vol  = info.get("averageVolume", 0) or 0
            name = info.get("shortName", ticker)

            issues = []
            if cap < MIN_MARKET_CAP:
                issues.append(f"market_cap={cap:,} < {MIN_MARKET_CAP:,}")
            if vol < MIN_AVG_VOLUME:
                issues.append(f"avg_volume={vol:,} < {MIN_AVG_VOLUME:,}")

            if issues:
                print(f"    ⚠  {ticker:6s} ({name}) — {'; '.join(issues)}")
                failures.append(ticker)
            else:
                print(f"    ✅ {ticker:6s} ({name})")

        except Exception as e:
            print(f"    ❌ {ticker:6s} — fetch error: {e}")
            failures.append(ticker)

print()
if failures:
    print(f"⚠  {len(failures)} ticker(s) flagged: {failures}")
    print("   Review before deploy — these may trip hard filters on every signal.")
    sys.exit(1)
else:
    print(f"✅  All {len(ALL_TICKERS)} tickers pass minimum thresholds")
    sys.exit(0)
