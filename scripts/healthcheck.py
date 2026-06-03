#!/usr/bin/env python3
"""
scripts/healthcheck.py

Quick operational check. Run manually or wire into CI.
Exits 0 if all systems are reachable, 1 if anything is wrong.

Usage:
    python scripts/healthcheck.py
"""

import sys
import os

# Allow running from project root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import redis
from sqlalchemy import text
from signal_system.db import engine

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

errors = []

# --- Postgres ---
print("Checking PostgreSQL...", end=" ")
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("OK")
except Exception as e:
    print(f"FAIL — {e}")
    errors.append("postgres")

# --- Schema tables present ---
print("Checking schema tables...", end=" ")
try:
    with engine.connect() as conn:
        tables = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )).fetchall()
        names = {r[0] for r in tables}
        required = {"signals", "paper_trades", "source_health", "market_data"}
        missing = required - names
        if missing:
            print(f"FAIL — missing tables: {missing}")
            errors.append("schema")
        else:
            print("OK")
except Exception as e:
    print(f"FAIL — {e}")
    errors.append("schema")

# --- source_health seeded ---
print("Checking source_health rows...", end=" ")
try:
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM source_health")).scalar()
        if count < 4:
            print(f"FAIL — only {count}/4 sources seeded")
            errors.append("source_health")
        else:
            print("OK")
except Exception as e:
    print(f"FAIL — {e}")
    errors.append("source_health")

# --- Redis ---
print("Checking Redis...", end=" ")
try:
    r = redis.from_url(REDIS_URL)
    r.ping()
    print("OK")
except Exception as e:
    print(f"FAIL — {e}")
    errors.append("redis")

# --- Summary ---
print()
if errors:
    print(f"❌  {len(errors)} check(s) failed: {', '.join(errors)}")
    sys.exit(1)
else:
    print("✅  All systems healthy")
    sys.exit(0)
