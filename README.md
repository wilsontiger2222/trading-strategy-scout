# Trading Strategy Scout

An autonomous multi-agent system that scans GitHub daily for new trading strategies, extracts the core logic in plain English (without copying code), assesses feasibility, and delivers a daily digest via Telegram.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Scout Agent │────▶│Analyst Agent │────▶│ Dedup Agent  │
│              │     │              │     │              │
│ GitHub API   │     │ README +     │     │ TF-IDF       │
│ search       │     │ file analysis│     │ similarity   │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                                                 ▼
                     ┌──────────────┐     ┌──────────────┐
                     │   Reporter   │◀────│ Feasibility  │
                     │   Agent      │     │   Agent      │
                     │              │     │              │
                     │ Telegram +   │     │ 5-dimension  │
                     │ Markdown     │     │ scoring      │
                     └──────────────┘     └──────────────┘
```

### Agent Descriptions

| Agent | Purpose |
|-------|---------|
| **Scout** | Searches GitHub for repos matching trading/quant keywords updated in the last N hours. Optional language allowlist + optional exclusions. |
| **Analyst** | Reads each repo's README and up to 3 core Python files to produce a plain-English strategy summary. Extracts concept, entry/exit logic, indicators, timeframe, asset class, **data requirements**, and **Hyperliquid compatibility tag**. Never stores code. |
| **Dedup** | Maintains a persistent strategy database. Uses TF-IDF cosine similarity to flag duplicates (>0.8), similar (0.5–0.8), and novel (<0.5) strategies. |
| **Feasibility** | Scores each strategy on 5 criteria (1–10). If an exclusion keyword is detected, it is **flagged but not removed**. |
| **Reporter** | Selects the top 5 strategies, generates a markdown digest, saves it to disk, and sends a summary via Telegram (includes blueprint + JSON schema). |
| **Weekly Review** | Generates `weekly_review/{date}_review.md` from forward-test data. |
| **Monthly Review** | Generates `monthly_reports/{month}_review.md` with rollups. |

### Data Flow

```
GitHub API
    │
    ▼
data/daily_scans/{date}.json          ← Scout output
    │
    ▼
[in-memory list with strategy_summary] ← Analyst output
    │
    ▼
data/strategy_db.json                  ← Dedup persistent DB
    │
    ▼
[in-memory list with feasibility]      ← Feasibility output
    │
    ▼
reports/{date}_digest.md               ← Reporter output
data/daily_scans/{date}_full.json      ← Full pipeline dump
logs/{date}.log                        ← Pipeline log
```

## Setup

### 1. Clone the repo

```bash
git clone <your-repo-url>
cd trading-strategy-scout
```

### 2. Create your .env file

```bash
cp .env.example .env
```

Edit `.env` and fill in:

- `GITHUB_TOKEN` — Optional but recommended. A [GitHub personal access token](https://github.com/settings/tokens) increases the API rate limit from 60 to 5,000 requests/hour.
- `MIN_STARS` — Minimum stars (default 2)
- `SINCE_HOURS` — Lookback window (default 24)
- `ALLOWED_LANGUAGES` — Comma‑separated allowlist (optional; blank = all)
- `EXCLUDE_KEYWORDS` — Comma‑separated exclusions (optional; blank = none)
- `BOT_TOKEN` — Get one from [@BotFather](https://t.me/BotFather) on Telegram.
- `CHAT_ID` — Get yours from [@userinfobot](https://t.me/userinfobot) on Telegram.

### 3. Run setup

```bash
chmod +x setup.sh
./setup.sh
```

This creates the runtime directories and installs Python dependencies.

## Usage

### Run manually

```bash
python orchestrator.py
```

### Run individual agents (for testing)

```bash
# Scout only
python -m agents.scout_agent

# Analyst (requires scout output)
python -m agents.analyst_agent data/daily_scans/2025-01-15.json

# Dedup (requires analyst output)
python -m agents.dedup_agent <input.json>

# Feasibility (requires dedup output)
python -m agents.feasibility_agent <input.json>

# Reporter (requires feasibility output)
python -m agents.reporter_agent <input.json>

# Weekly review
python -m agents.weekly_review_agent

# Monthly report
python -m agents.monthly_report_agent
```

### Automate with cron

Add a daily cron job (e.g., at 08:00 UTC):

```bash
crontab -e
```

```
0 8 * * * cd /path/to/trading-strategy-scout && /usr/bin/python3 orchestrator.py >> /dev/null 2>&1
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | No | GitHub PAT for higher API rate limits |
| `BOT_TOKEN` | Yes* | Telegram bot token from @BotFather |
| `CHAT_ID` | Yes* | Your Telegram chat ID |

*Required only if you want Telegram notifications. The pipeline runs fine without them and still saves reports to disk.

## Requirements

- Python 3.10+
- Dependencies: `requests`, `scikit-learn`, `python-telegram-bot`, `python-dotenv`

All listed in `requirements.txt`.

## File Structure

```
project-root/
├── agents/
│   ├── __init__.py
│   ├── scout_agent.py
│   ├── analyst_agent.py
│   ├── dedup_agent.py
│   ├── feasibility_agent.py
│   ├── reporter_agent.py
│   ├── weekly_review_agent.py
│   └── monthly_review_agent.py
├── orchestrator.py
├── requirements.txt
├── setup.sh
├── .env.example
├── .gitignore
└── README.md
```

Runtime directories (auto-created, git-ignored):

```
├── data/
│   ├── daily_scans/       # Daily scan JSONs
│   ├── strategy_db.json   # Persistent dedup database
│   └── active_strategies.json # Forward-test registry
├── reports/               # Daily markdown digests
├── weekly_reviews/        # Weekly reviews
├── monthly_reports/       # Monthly reports
└── logs/                  # Daily pipeline logs
```
