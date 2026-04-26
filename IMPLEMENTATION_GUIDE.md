# Step-by-Step Implementation Guide (Beginner Friendly)

This guide is for non-experts and shows exactly how to run, verify, and deploy this project.

## 0) What this app does

- Scans heavily traded stocks.
- Builds day-trading execution plans (entry/stop/target).
- Adds simple news sentiment from Yahoo RSS headlines.
- Tracks picks in `reports/picks_history.csv`.
- Can send an email report via SendGrid.
- Can run daily via GitHub Actions for free.

---

## 1) Install prerequisites

You need:
- Python 3.10+
- A GitHub account
- (Optional) SendGrid account for email alerts

---

## 2) Download project and setup Python

```bash
git clone <your_repo_url>
cd Financial
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

---

## 3) Configure `.env`

Open `.env` and update:

- `SENDGRID_API_KEY` (if using email)
- `ALERT_FROM_EMAIL`
- `ALERT_TO_EMAIL`
- `TOP_COUNT`, `MIN_PRICE`, `MIN_MARKET_CAP` (optional tuning)

For first run:
- `RUN_MODE=once`
- `SEND_EMAIL=false`

---

## 4) Run local scanner once (safe test)

```bash
RUN_MODE=once SEND_EMAIL=false python app/main.py
```

Expected: terminal prints generated execution plans.

---

## 5) Run frontend app (interactive)

```bash
streamlit run app/frontend_app.py
```

In browser, click **Run Scan**.

Tabs:
- **Day Trading**: entry/stop/target table
- **Long-Term**: long-term ranking
- **Sentiment & News**: headline sentiment
- **Automation**: deployment hints

---

## 6) Turn on email alerts (optional)

Set in `.env`:

- `SEND_EMAIL=true`
- `SENDGRID_API_KEY`, `ALERT_FROM_EMAIL`, `ALERT_TO_EMAIL` must all be valid

Then run once:

```bash
RUN_MODE=once SEND_EMAIL=true python app/main.py
```

---

## 7) Free scheduled deployment (GitHub Actions)

1. Push code to GitHub.
2. In repo settings → **Secrets and variables** → **Actions**:
   - Add secrets:
     - `SENDGRID_API_KEY`
     - `ALERT_FROM_EMAIL`
     - `ALERT_TO_EMAIL`
3. (Optional) add variables for scanner tuning (`TOP_COUNT`, etc).
4. Open **Actions** tab, run **Daily Stock Scan** manually once.
5. Verify:
   - workflow succeeds
   - `reports/picks_history.csv` updates
   - you receive email (if enabled)

---

## 8) Troubleshooting

### "Module not found"
Run:
```bash
pip install -r requirements.txt
```

### No market data / network blocked
Leave:
```env
ALLOW_SAMPLE_DATA_ON_FETCH_ERROR=true
```
This lets local testing proceed with sample payloads.

### No email received
- Check SendGrid key is valid.
- Verify sender domain/address is allowed in SendGrid.
- Confirm recipient email is correct.

### Scheduler not working locally
Use GitHub Actions schedule or install APScheduler dependency from `requirements.txt`.

---

## 9) Minimal repeatable daily workflow

1. Use Streamlit to review picks.
2. Run scanner in once mode pre-market.
3. Log outcomes and monitor `reports/picks_history.csv`.
4. Tune filters weekly (`MIN_REL_VOLUME`, `MAX_SPREAD_PCT`, etc).

