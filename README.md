# Event-Driven Trading Signal System

**MVP v1.1 · Free-tier · Human-in-the-loop · Paper trading only**

Detects early event-driven positioning signals across 37 watchlist equities.
Surfaces high-confidence candidates for manual review. Logs all outcomes for calibration.

> This system is intentionally biased toward under-trading.
> If it feels like it's missing opportunities — it's working correctly.

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| Task queue | Celery + Celery Beat |
| Broker | Redis 7 |
| Database | PostgreSQL 16 |
| Market data | yfinance |
| News NLP | spaCy (en_core_web_sm) |
| Political data | Quiver Quantitative (free tier) |
| Containerisation | Docker + Docker Compose |

---

## Project Structure

```
signal-system/
├── signal_system/          # Main Python package
│   ├── config/             # Watchlist, scoring constants
│   ├── workers/            # One module per data source worker
│   ├── engine/             # Signal detection + scoring logic
│   ├── dashboard/          # Flask app (Week 3)
│   └── tests/              # Unit + integration tests
├── scripts/                # One-off ops scripts (seed, backfill, health check)
├── sql/                    # All schema + migration SQL
├── logs/                   # Runtime logs (git-ignored)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md
```

---

## Quickstart

### Prerequisites
- Docker + Docker Compose
- Python 3.12 (for local dev outside Docker)

### 1. Clone and configure
```bash
git clone <repo-url>
cd signal-system
cp .env.example .env
# Edit .env — add your QUIVER_API_KEY at minimum
```

### 2. Start infrastructure
```bash
docker-compose up --build
```
This starts Postgres, Redis, the Celery worker, and Celery Beat.
Schema is applied automatically on first boot.

### 3. Verify
```bash
# Check DB is up and schema applied
docker-compose exec postgres psql -U signals_user -d signals_db -c "\dt"

# Check Celery workers registered
docker-compose exec celery-worker celery -A signal_system.celery_app inspect registered

# Manual health check
python scripts/healthcheck.py
```

### 4. Local dev (outside Docker)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m spacy download en_core_web_sm

# Run a worker manually
python -m signal_system.workers.market_worker
```

---

## Build Order (per spec §17)

| Week | Focus | Status |
|---|---|---|
| 1 | yfinance scanner · PostgreSQL schema · signal logging | 🔨 In progress |
| 2 | RSS ingestion · spaCy NER · Quiver polling · hard filters | ⏳ Pending |
| 3 | Scoring model · minimal dashboard · approve/reject | ⏳ Pending |
| 4 | TradingView charts · paper trade engine · options proxy | ⏳ Pending |

> Do not act on signals until 30+ are logged (§17).

---

## Calibration Gates

| Gate | Condition |
|---|---|
| First review | 30 signals logged (any status) |
| Weight adjustment | 60 signals with outcome data |
| Success target | ≥55% approved signals reach hit/MFE |

---

## Key Constraints (LOCKED — §2)

- Short-term momentum only · 1–3 day hold · hard max 5 days
- Equities only · no options until post-MVP
- Earnings trades hard-filtered out
- Watchlist capped at 37 tickers (max 50 before filter revalidation)
- Score threshold: ≥5 to surface to dashboard
