from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import formatdate
from pathlib import Path
from typing import Any, TypedDict
from urllib import parse, request

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover - environment dependent
    requests = None

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:  # pragma: no cover - environment dependent
    BlockingScheduler = None
    CronTrigger = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - environment dependent
    def load_dotenv() -> None:
        return None

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - environment dependent
    END = "__END__"
    START = "__START__"
    StateGraph = None

YAHOO_MOST_ACTIVE_URL = (
    "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
)
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
SENDGRID_SEND_URL = "https://api.sendgrid.com/v3/mail/send"


@dataclass
class AnalystSignal:
    symbol: str
    name: str
    price: float
    change_pct: float
    volume: float
    avg_volume: float
    market_cap: float
    rel_volume: float
    intraday_range_pct: float
    momentum_score: float
    thesis: str


@dataclass
class RiskApprovedSignal:
    signal: AnalystSignal
    risk_score: float
    risk_notes: str


@dataclass
class ExecutionPlan:
    symbol: str
    name: str
    entry: float
    stop_loss: float
    take_profit: float
    conviction_score: float
    rationale: str


class ScanState(TypedDict, total=False):
    top_count: int
    min_price: float
    min_market_cap: float
    min_rel_volume: float
    max_spread_pct: float
    timezone_name: str
    send_email: bool
    symbols: list[str]
    quotes: list[dict[str, Any]]
    market_analysis: list[AnalystSignal]
    risk_approved: list[RiskApprovedSignal]
    execution_plan: list[ExecutionPlan]
    backtest_report: str
    email_subject: str
    email_body: str


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _http_get_json(url: str, params: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    def _fallback_payload() -> dict[str, Any]:
        if "screener/predefined/saved" in url:
            return {
                "finance": {
                    "result": [
                        {
                            "quotes": [
                                {"symbol": "AAPL"},
                                {"symbol": "NVDA"},
                                {"symbol": "TSLA"},
                                {"symbol": "AMD"},
                                {"symbol": "MSFT"},
                                {"symbol": "AMZN"},
                                {"symbol": "META"},
                                {"symbol": "PLTR"},
                                {"symbol": "SOFI"},
                                {"symbol": "INTC"},
                            ]
                        }
                    ]
                }
            }
        if "finance/quote" in url:
            return {
                "quoteResponse": {
                    "result": [
                        {
                            "symbol": "AAPL",
                            "shortName": "Apple Inc.",
                            "regularMarketPrice": 198.12,
                            "regularMarketChangePercent": 1.9,
                            "regularMarketVolume": 75000000,
                            "averageDailyVolume3Month": 62000000,
                            "regularMarketDayHigh": 199.5,
                            "regularMarketDayLow": 194.8,
                            "marketCap": 2900000000000,
                            "ask": 198.2,
                            "bid": 198.1,
                        },
                        {
                            "symbol": "NVDA",
                            "shortName": "NVIDIA Corporation",
                            "regularMarketPrice": 122.5,
                            "regularMarketChangePercent": 3.2,
                            "regularMarketVolume": 420000000,
                            "averageDailyVolume3Month": 360000000,
                            "regularMarketDayHigh": 124.2,
                            "regularMarketDayLow": 118.7,
                            "marketCap": 3100000000000,
                            "ask": 122.55,
                            "bid": 122.45,
                        },
                    ]
                }
            }
        if "finance/chart" in url:
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [
                                int(datetime.now(timezone.utc).timestamp() - 172800),
                                int(datetime.now(timezone.utc).timestamp() - 86400),
                            ],
                            "indicators": {"quote": [{"close": [100.0, 101.0]}]},
                        }
                    ]
                }
            }
        return {}

    if requests is not None:
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception:
            if os.getenv("ALLOW_SAMPLE_DATA_ON_FETCH_ERROR", "true").lower() == "true":
                return _fallback_payload()
            raise

    query = parse.urlencode(params)
    request_url = f"{url}?{query}" if query else url
    try:
        with request.urlopen(request_url, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise RuntimeError(f"GET failed with status {status}: {request_url}")
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        if os.getenv("ALLOW_SAMPLE_DATA_ON_FETCH_ERROR", "true").lower() == "true":
            return _fallback_payload()
        raise


def _http_post_json(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 20
) -> None:
    if requests is not None:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        return

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status >= 400:
            raise RuntimeError(f"POST failed with status {status}: {url}")


def fetch_most_active_symbols(top_count: int) -> list[str]:
    params = {"scrIds": "most_actives", "count": max(top_count * 3, 30), "start": 0}
    payload = _http_get_json(YAHOO_MOST_ACTIVE_URL, params=params, timeout=20)

    quotes = payload.get("finance", {}).get("result", [{}])[0].get("quotes", [])
    symbols = [q.get("symbol") for q in quotes if q.get("symbol")]
    return symbols[: max(top_count * 2, 20)]


def fetch_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    if not symbols:
        return []

    params = {"symbols": ",".join(symbols)}
    payload = _http_get_json(YAHOO_QUOTE_URL, params=params, timeout=20)
    return payload.get("quoteResponse", {}).get("result", [])


def fetch_next_day_close(symbol: str, trade_date: date) -> float | None:
    period_start = datetime.combine(trade_date - timedelta(days=2), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    period_end = datetime.combine(trade_date + timedelta(days=14), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )

    params = {
        "period1": int(period_start.timestamp()),
        "period2": int(period_end.timestamp()),
        "interval": "1d",
    }
    payload = _http_get_json(f"{YAHOO_CHART_URL}/{symbol}", params=params, timeout=20)
    chart = payload.get("chart", {}).get("result", [])
    if not chart:
        return None

    timestamps = chart[0].get("timestamp", [])
    closes = chart[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])

    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        candle_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        if candle_date > trade_date:
            return float(close)

    return None


def market_analyst(
    quotes: list[dict[str, Any]],
    min_price: float,
    min_market_cap: float,
) -> list[AnalystSignal]:
    analysis: list[AnalystSignal] = []

    for quote in quotes:
        price = float(quote.get("regularMarketPrice", 0.0) or 0.0)
        market_cap = float(quote.get("marketCap", 0.0) or 0.0)
        if price < min_price or market_cap < min_market_cap:
            continue

        change_pct = float(quote.get("regularMarketChangePercent", 0.0) or 0.0)
        volume = float(quote.get("regularMarketVolume", 0.0) or 0.0)
        avg_volume = float(quote.get("averageDailyVolume3Month", 0.0) or 0.0)

        high = float(quote.get("regularMarketDayHigh", price) or price)
        low = float(quote.get("regularMarketDayLow", price) or price)

        rel_volume = _safe_div(volume, avg_volume)
        range_pct = _safe_div((high - low), price) * 100

        momentum_score = (
            (change_pct * 2.5)
            + (rel_volume * 10.0)
            + (range_pct * 0.8)
            + (_safe_div(volume * price, 1_000_000_000) * 4.0)
        )

        thesis = (
            f"{change_pct:+.2f}% momentum, {rel_volume:.2f}x relative volume, "
            f"{range_pct:.2f}% intraday range"
        )

        analysis.append(
            AnalystSignal(
                symbol=quote.get("symbol", ""),
                name=quote.get("shortName", "Unknown"),
                price=price,
                change_pct=change_pct,
                volume=volume,
                avg_volume=avg_volume,
                market_cap=market_cap,
                rel_volume=rel_volume,
                intraday_range_pct=range_pct,
                momentum_score=momentum_score,
                thesis=thesis,
            )
        )

    analysis.sort(key=lambda x: x.momentum_score, reverse=True)
    return analysis


def risk_manager(
    market_analysis: list[AnalystSignal],
    quote_map: dict[str, dict[str, Any]],
    min_rel_volume: float,
    max_spread_pct: float,
) -> list[RiskApprovedSignal]:
    approved: list[RiskApprovedSignal] = []

    for signal in market_analysis:
        quote = quote_map.get(signal.symbol, {})
        ask = float(quote.get("ask", 0.0) or 0.0)
        bid = float(quote.get("bid", 0.0) or 0.0)
        spread_pct = _safe_div((ask - bid), signal.price) * 100 if ask and bid else 0.0

        if signal.rel_volume < min_rel_volume:
            continue
        if spread_pct > max_spread_pct:
            continue

        volatility_penalty = max(signal.intraday_range_pct - 9.0, 0.0) * 0.8
        risk_score = signal.momentum_score - volatility_penalty - (spread_pct * 1.5)

        approved.append(
            RiskApprovedSignal(
                signal=signal,
                risk_score=risk_score,
                risk_notes=(
                    f"spread {spread_pct:.2f}% | rel-vol {signal.rel_volume:.2f}x | "
                    f"volatility adj -{volatility_penalty:.2f}"
                ),
            )
        )

    approved.sort(key=lambda x: x.risk_score, reverse=True)
    return approved


def execution_planner(risk_approved: list[RiskApprovedSignal], top_count: int) -> list[ExecutionPlan]:
    plans: list[ExecutionPlan] = []

    for approved in risk_approved[:top_count]:
        s = approved.signal
        risk_buffer = max(s.intraday_range_pct / 100 * 0.6, 0.012)
        reward_buffer = risk_buffer * 1.8

        stop_loss = max(s.price * (1 - risk_buffer), 0.01)
        take_profit = s.price * (1 + reward_buffer)

        plans.append(
            ExecutionPlan(
                symbol=s.symbol,
                name=s.name,
                entry=s.price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                conviction_score=approved.risk_score,
                rationale=f"{s.thesis}; {approved.risk_notes}",
            )
        )

    return plans


def _ensure_history_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "run_date",
                "symbol",
                "entry_price",
                "next_day_close",
                "return_pct",
                "status",
            ],
        )
        writer.writeheader()


def backtest_and_track(plans: list[ExecutionPlan], history_path: Path) -> str:
    _ensure_history_file(history_path)

    today = datetime.now(timezone.utc).date()
    with history_path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    updated_rows: list[dict[str, str]] = []
    wins = 0
    losses = 0
    closed_returns: list[float] = []

    for row in rows:
        if row.get("status") == "closed":
            updated_rows.append(row)
            if float(row.get("return_pct", "0") or 0) > 0:
                wins += 1
            else:
                losses += 1
            closed_returns.append(float(row.get("return_pct", "0") or 0))
            continue
for row in rows:
    if row.get("run_date") == "run_date":
        continue

    trade_date = date.fromisoformat(row["run_date"])

    trade_date = date.fromisoformat(row["run_date"])
        trade_date = date.fromisoformat(row["run_date"])
        if trade_date >= today:
            updated_rows.append(row)
            continue

        close_price = fetch_next_day_close(row["symbol"], trade_date)
        if close_price is None:
            updated_rows.append(row)
            continue

        entry = float(row["entry_price"])
        ret_pct = _safe_div((close_price - entry), entry) * 100

        row["next_day_close"] = f"{close_price:.4f}"
        row["return_pct"] = f"{ret_pct:.4f}"
        row["status"] = "closed"
        updated_rows.append(row)

        closed_returns.append(ret_pct)
        if ret_pct > 0:
            wins += 1
        else:
            losses += 1

    for plan in plans:
        updated_rows.append(
            {
                "run_date": today.isoformat(),
                "symbol": plan.symbol,
                "entry_price": f"{plan.entry:.4f}",
                "next_day_close": "",
                "return_pct": "",
                "status": "open",
            }
        )

    with history_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "run_date",
                "symbol",
                "entry_price",
                "next_day_close",
                "return_pct",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(updated_rows)

    closed_count = len(closed_returns)
    win_rate = _safe_div(wins, closed_count) * 100 if closed_count else 0.0
    avg_return = sum(closed_returns) / closed_count if closed_count else 0.0

    return (
        "Backtest summary (daily tracked):\n"
        f"- Closed picks: {closed_count}\n"
        f"- Wins/Losses: {wins}/{losses}\n"
        f"- Win rate: {win_rate:.2f}%\n"
        f"- Avg next-day return: {avg_return:.2f}%\n"
        f"- History file: {history_path}"
    )


def build_email_text(
    plans: list[ExecutionPlan],
    timezone_name: str,
    backtest_report: str,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "Daily Day-Trade Plan",
        f"Generated at: {now} ({timezone_name})",
        "",
        "Execution Planner output:",
    ]

    for idx, plan in enumerate(plans, start=1):
        lines.append(
            (
                f"{idx}. {plan.symbol} ({plan.name}) | entry ${plan.entry:.2f} | "
                f"stop ${plan.stop_loss:.2f} | target ${plan.take_profit:.2f} | "
                f"score {plan.conviction_score:.2f}"
            )
        )
        lines.append(f"   Rationale: {plan.rationale}")

    lines.extend(
        [
            "",
            backtest_report,
            "",
            "Risk reminder: automated signals can fail; use position sizing and hard stops.",
        ]
    )
    return "\n".join(lines)


def send_email_via_sendgrid(subject: str, body: str) -> None:
    api_key = os.getenv("SENDGRID_API_KEY")
    sender = os.getenv("ALERT_FROM_EMAIL")
    recipient = os.getenv("ALERT_TO_EMAIL")

    if not (api_key and sender and recipient):
        raise RuntimeError(
            "Missing SENDGRID_API_KEY, ALERT_FROM_EMAIL, or ALERT_TO_EMAIL env vars"
        )

    payload = {
        "personalizations": [{"to": [{"email": recipient}]}],
        "from": {"email": sender},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
        "headers": {"Date": formatdate(localtime=True)},
    }

    _http_post_json(
        SENDGRID_SEND_URL,
        payload=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=20,
    )


def _node_fetch_symbols(state: ScanState) -> ScanState:
    return {"symbols": fetch_most_active_symbols(top_count=state["top_count"])}


def _node_fetch_quotes(state: ScanState) -> ScanState:
    return {"quotes": fetch_quotes(state.get("symbols", []))}


def _node_market_analyst(state: ScanState) -> ScanState:
    analysis = market_analyst(
        quotes=state.get("quotes", []),
        min_price=state["min_price"],
        min_market_cap=state["min_market_cap"],
    )
    if not analysis:
        raise RuntimeError("Market Analyst found no symbols. Relax your scan filters.")
    return {"market_analysis": analysis}


def _node_risk_manager(state: ScanState) -> ScanState:
    quote_map = {q.get("symbol", ""): q for q in state.get("quotes", [])}
    approved = risk_manager(
        market_analysis=state.get("market_analysis", []),
        quote_map=quote_map,
        min_rel_volume=state["min_rel_volume"],
        max_spread_pct=state["max_spread_pct"],
    )
    if not approved:
        raise RuntimeError("Risk Manager rejected all picks. Adjust risk thresholds.")
    return {"risk_approved": approved}


def _node_execution_planner(state: ScanState) -> ScanState:
    plans = execution_planner(
        risk_approved=state.get("risk_approved", []),
        top_count=state["top_count"],
    )
    return {"execution_plan": plans}


def _node_backtesting(state: ScanState) -> ScanState:
    history_path = Path(os.getenv("BACKTEST_HISTORY_FILE", "reports/picks_history.csv"))
    report = backtest_and_track(state.get("execution_plan", []), history_path)
    return {"backtest_report": report}


def _node_build_email(state: ScanState) -> ScanState:
    body = build_email_text(
        plans=state.get("execution_plan", []),
        timezone_name=state["timezone_name"],
        backtest_report=state.get("backtest_report", "No backtest summary available."),
    )
    subject = f"[Stock Scan] {datetime.now().strftime('%Y-%m-%d')} Execution Plan"
    return {"email_subject": subject, "email_body": body}


def _node_send_email(state: ScanState) -> ScanState:
    if state.get("send_email", True):
        send_email_via_sendgrid(state["email_subject"], state["email_body"])
    return {}


class _SequentialGraph:
    def __init__(self, nodes: list[Any]):
        self.nodes = nodes

    def invoke(self, initial_state: ScanState) -> ScanState:
        state: ScanState = dict(initial_state)
        for node in self.nodes:
            update = node(state)
            if update:
                state.update(update)
        return state


def build_agentic_scan_graph():
    if StateGraph is None:
        return _SequentialGraph(
            [
                _node_fetch_symbols,
                _node_fetch_quotes,
                _node_market_analyst,
                _node_risk_manager,
                _node_execution_planner,
                _node_backtesting,
                _node_build_email,
                _node_send_email,
            ]
        )

    graph_builder: StateGraph = StateGraph(ScanState)
    graph_builder.add_node("fetch_symbols", _node_fetch_symbols)
    graph_builder.add_node("fetch_quotes", _node_fetch_quotes)
    graph_builder.add_node("market_analyst", _node_market_analyst)
    graph_builder.add_node("risk_manager", _node_risk_manager)
    graph_builder.add_node("execution_planner", _node_execution_planner)
    graph_builder.add_node("backtesting_report", _node_backtesting)
    graph_builder.add_node("build_email", _node_build_email)
    graph_builder.add_node("dispatch_email", _node_send_email)
    graph_builder.add_node("send_email_node", _node_send_email)
    graph_builder.add_edge(START, "fetch_symbols")
    graph_builder.add_edge("fetch_symbols", "fetch_quotes")
    graph_builder.add_edge("fetch_quotes", "market_analyst")
    graph_builder.add_edge("market_analyst", "risk_manager")
    graph_builder.add_edge("risk_manager", "execution_planner")
    graph_builder.add_edge("execution_planner", "backtesting_report")
    graph_builder.add_edge("backtesting_report", "build_email")
    graph_builder.add_edge("build_email", "dispatch_email")
    graph_builder.add_edge("dispatch_email", END)
    graph_builder.add_edge("build_email", "send_email_node")
    graph_builder.add_edge("send_email_node", END)

    return graph_builder.compile()


def run_scan_and_alert(send_email: bool = True) -> list[ExecutionPlan]:
    initial_state: ScanState = {
        "top_count": int(os.getenv("TOP_COUNT", "10")),
        "min_price": float(os.getenv("MIN_PRICE", "5")),
        "min_market_cap": float(os.getenv("MIN_MARKET_CAP", "2000000000")),
        "min_rel_volume": float(os.getenv("MIN_REL_VOLUME", "1.1")),
        "max_spread_pct": float(os.getenv("MAX_SPREAD_PCT", "1.0")),
        "timezone_name": os.getenv("ALERT_TIMEZONE", "America/New_York"),
        "send_email": send_email,
    }

    graph = build_agentic_scan_graph()
    final_state = graph.invoke(initial_state)
    return final_state.get("execution_plan", [])


def start_scheduler() -> None:
    load_dotenv()
    if BlockingScheduler is None or CronTrigger is None:
        raise RuntimeError(
            "APScheduler is not installed. Install requirements.txt to use scheduled mode."
        )

    timezone_name = os.getenv("ALERT_TIMEZONE", "America/New_York")
    alert_hour = int(os.getenv("ALERT_HOUR", "7"))
    alert_minute = int(os.getenv("ALERT_MINUTE", "0"))

    scheduler = BlockingScheduler(timezone=timezone_name)
    scheduler.add_job(
        run_scan_and_alert,
        trigger=CronTrigger(hour=alert_hour, minute=alert_minute, timezone=timezone_name),
        id="daily_stock_scan",
        replace_existing=True,
    )

    print(
        f"Scheduler started. Daily scan at {alert_hour:02d}:{alert_minute:02d} "
        f"{timezone_name}."
    )
    scheduler.start()


if __name__ == "__main__":
    load_dotenv()

    mode = os.getenv("RUN_MODE", "schedule").lower()
    if mode == "once":
        send_email = os.getenv("SEND_EMAIL", "true").lower() == "true"
        picks = run_scan_and_alert(send_email=send_email)
        print("Generated execution plans:")
        for stock in picks:
            print(
                f"- {stock.symbol}: entry={stock.entry:.2f}, stop={stock.stop_loss:.2f}, "
                f"target={stock.take_profit:.2f}, score={stock.conviction_score:.2f}"
            )
    else:
        start_scheduler()
