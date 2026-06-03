# Git Setup & Workflow

## First-time local setup

```bash
# 1. Create the repo on GitHub first (no README, no .gitignore — we have both)
#    Then locally:

git init
git remote add origin git@github.com:YOUR_USERNAME/signal-system.git

# 2. Stage everything
git add .

# 3. Verify .env is NOT staged (must show in .gitignore exclusions)
git status | grep .env
# Should show nothing — if it appears, stop and check .gitignore

# 4. First commit
git commit -m "feat: initial scaffold — schema, market worker, Celery, Docker"

# 5. Push
git branch -M main
git push -u origin main
```

---

## Branch strategy (lightweight for solo/small team)

```
main          — deployable at all times
dev           — active development, PRs merge here first
feat/*        — one branch per feature/worker
fix/*         — bug fixes
```

```bash
# Start a new piece of work
git checkout dev
git pull origin dev
git checkout -b feat/news-worker

# ... build ...

git add .
git commit -m "feat(news): RSS ingestion + spaCy NER worker"
git push origin feat/news-worker

# Open PR: feat/news-worker → dev
# After review/test: merge to dev
# When dev is stable: merge dev → main
```

---

## Commit message conventions

```
feat(scope):   new capability
fix(scope):    bug fix
chore(scope):  config, deps, tooling
docs(scope):   README, comments
refactor:      no behaviour change
test:          tests only

Examples:
  feat(market): add 20d avg volume calculation
  fix(health): degraded threshold off-by-one
  chore(deps): bump yfinance to 0.2.41
  feat(schema): add market_data retention index
```

---

## What to NEVER commit

Already in `.gitignore`, but worth repeating:

| File/dir | Why |
|---|---|
| `.env` | Contains DB password + API keys |
| `logs/` | Runtime output, not source |
| `__pycache__/` | Compiled bytecode |
| `celerybeat-schedule` | Runtime Beat state |
| `.venv/` | Virtualenv — reproducible from requirements.txt |
| `pgdata/` | Local Docker DB volume |

---

## Secrets management

**MVP (local/single server):**
- `.env` file, never committed
- Copy `.env.example` → `.env` on each new machine

**When you deploy to a server:**
- Use environment variables injected by your host (Railway, Render, Fly.io all support this)
- Or use Docker secrets if self-hosting
- Do NOT copy your `.env` file to the server via git

---

## Recommended GitHub repo settings

- **Default branch:** `main`
- **Branch protection on `main`:**
  - Require PR before merging
  - Require at least 1 approval (even if solo — forces review discipline)
- **Secrets:** Add `QUIVER_API_KEY` as a GitHub Actions secret if you add CI later
