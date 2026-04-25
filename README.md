# Agentic Day-Trade Scanner + 7:00 AM Email Alert + Daily Backtesting Tracker

This app scans heavily traded stocks and sends a **7:00 AM** email with an actionable intraday plan.

It uses an **agentic workflow graph** built on the popular GitHub repo **LangGraph** (`langchain-ai/langgraph`) with role-based nodes:

- **Market Analyst**
- **Risk Manager**
- **Execution Planner**
- **Backtesting Reporter**

> ⚠️ This is an engineering workflow and not financial advice.

## Agent graph

1. `fetch_symbols` (Yahoo most-active universe)
2. `fetch_quotes` (fresh quote details)
3. `market_analyst` (momentum + liquidity thesis)
4. `risk_manager` (spread/volume/risk filters)
5. `execution_planner` (entry/stop/target plan)
6. `backtesting_report` (daily tracking + win-rate summary)
7. `build_email` (report composition)
8. `send_email` (SendGrid delivery)

## Data flow / architecture

```text
Config (.env) ─┬─> Graph State (top_count, filters, email flags)
               │
               ├─> fetch_symbols ─> symbols[]
               ├─> fetch_quotes ─> quotes[]
               ├─> market_analyst ─> market_analysis[]
               ├─> risk_manager ─> risk_approved[]
               ├─> execution_planner ─> execution_plan[]
               ├─> backtesting_report ─> picks_history.csv + summary text
               ├─> build_email ─> subject/body
               └─> send_email (optional)
```

## Daily backtesting behavior

- Stores every daily pick in `reports/picks_history.csv`.
- On each run, attempts to close prior open picks using **next trading day close** from Yahoo chart candles.
- Computes ongoing metrics:
  - closed picks
  - wins/losses
  - win rate
  - average next-day return
- Includes this summary in the daily email.

## GitHub repos used

- LangGraph (agent orchestration): https://github.com/langchain-ai/langgraph
- APScheduler (scheduling): https://github.com/agronholm/apscheduler

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Environment variables

```dotenv
SENDGRID_API_KEY=...
ALERT_FROM_EMAIL=alerts@yourdomain.com
ALERT_TO_EMAIL=you@example.com

ALERT_TIMEZONE=America/New_York
ALERT_HOUR=7
ALERT_MINUTE=0

TOP_COUNT=10
MIN_PRICE=5
MIN_MARKET_CAP=2000000000
MIN_REL_VOLUME=1.1
MAX_SPREAD_PCT=1.0
BACKTEST_HISTORY_FILE=reports/picks_history.csv
ALLOW_SAMPLE_DATA_ON_FETCH_ERROR=true

RUN_MODE=schedule
SEND_EMAIL=true
```

## Run modes

### Run once (safe test)

```bash
RUN_MODE=once SEND_EMAIL=false python app/main.py
```

### Start scheduler

```bash
python app/main.py
```

## Free deployment (GitHub Actions)

This repo includes `.github/workflows/daily-scan.yml` for a free scheduled run approach.

### What it does

- Runs on weekdays via cron (`0 11 * * 1-5`).
- Executes `python app/main.py` in `RUN_MODE=once`.
- Sends email via SendGrid.
- Commits updated `reports/picks_history.csv` back to the repository for persistent backtest history.

### Required GitHub secrets

- `SENDGRID_API_KEY`
- `ALERT_FROM_EMAIL`
- `ALERT_TO_EMAIL`

### Optional GitHub repository variables

- `ALERT_TIMEZONE`
- `TOP_COUNT`
- `MIN_PRICE`
- `MIN_MARKET_CAP`
- `MIN_REL_VOLUME`
- `MAX_SPREAD_PCT`
