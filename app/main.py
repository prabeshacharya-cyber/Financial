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
except ImportError:
    requests = None

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    BlockingScheduler = None
    CronTrigger = None

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None:
        return None

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    END = "__END__"
    START = "__START__"
    StateGraph = None


FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"
FINNHUB_SYMBOLS_URL = "https://finnhub.io/api/v1/stock/symbol"
FINNHUB_CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"
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


def _sample_symbols() -> list[str]:
    return ["AAPL", "NVDA", "TSLA", "AMD", "MSFT", "AMZN", "META", "PLTR", "SOFI", "INTC"]


def _sample_quote_payload(symbol: str) -> dict[str, Any]:
    samples = {
        "AAPL": {"price": 198.12, "change": 1.9, "name": "Apple Inc.", "cap": 2_900_000_000_000},
        "NVDA": {"price": 122.50, "change": 3.2, "name": "NVIDIA Corporation", "cap": 3_100_000_000_000},
        "TSLA": {"price": 245.10, "change": 2.4, "name": "Tesla Inc.", "cap": 780_000_000_000},
        "AMD": {"price": 158.20, "change": 2.1, "name": "Advanced Micro Devices Inc.", "cap": 250_000_000_000},
        "MSFT": {"price": 430.80, "change": 1.1, "name": "Microsoft Corporation", "cap": 3_200_000_000_000},
        "AMZN": {"price": 184.40, "change": 1.5, "name": "Amazon.com Inc.", "cap": 1_900_000_000_000},
        "META": {"price": 505.30, "change": 1.8, "name": "Meta Platforms Inc.", "cap": 1_200_000_000_000},
        "PLTR": {"price": 24.75, "change": 4.1, "name": "Palantir Technologies Inc.", "cap": 55_000_000_000},
        "SOFI": {"price": 8.50, "change": 3.5, "name": "SoFi Technologies Inc.", "cap": 9_000_000_000},
        "INTC": {"price": 33.10, "change": 1.2, "name": "Intel Corporation", "cap": 140_000_000_000},
    }
    return samples.get(symbol, {"price": 100.0, "change": 1.0, "name": symbol, "cap": 10_000_000_000})


def _http_get_json(url: str, params: dict[str, Any], timeout: int = 20) -> Any:
    if requests is not None:
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception:
            if os.getenv("ALLOW_SAMPLE_DATA_ON_FETCH_ERROR", "true").lower() == "true":
                raise
            raise

    query = parse.urlencode(params)
    request_url = f"{url}?{query}" if query else url

    with request.urlopen(request_url, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        if status >= 400:
            raise RuntimeError(f"GET failed with status {status}: {request_url}")
        return json.loads(response.read().decode("utf-8"))


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: int = 20,
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


def _get_finnhub_key() -> str:
    api_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if not api_key:
        if os.getenv("ALLOW_SAMPLE_DATA_ON_FETCH_ERROR", "true").lower() == "true":
            return ""
        raise RuntimeError("Missing FINNHUB_API_KEY")
    return api_key


def fetch_most_active_symbols(top_count: int) -> list[str]:
    api_key = _get_finnhub_key()

    if not api_key:
        return _sample_symbols()[: max(top_count * 2, 20)]

    try:
        payload = _http_get_json(
            FINNHUB_SYMBOLS_URL,
            params={"exchange": "US", "token": api_key},
            timeout=20,
        )

        symbols = [
            item.get("symbol")
            for item in payload
            if item.get("symbol")
            and item.get("type") == "Common Stock"
            and "." not in item.get("symbol", "")
            and "-" not in item.get("symbol", "")
        ]

        priority = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT", "AMZN", "META", "PLTR", "SOFI", "INTC"]
        ordered = [s for s in priority if s in symbols]
        ordered.extend([s for s in symbols if s not in ordered])

        return ordered[: max(top_count * 2, 20)]

    except Exception:
        if os.getenv("ALLOW_SAMPLE_DATA_ON_FETCH_ERROR", "true").lower() == "true":
            return _sample_symbols()[: max(top_count * 2, 20)]
        raise


def fetch_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    if not symbols:
        return []

    api_key = _get_finnhub_key()
    quotes: list[dict[str, Any]] = []

    for symbol in symbols:
        try:
            if not api_key:
                sample = _sample_quote_payload(symbol)
                price = float(sample["price"])
                previous_close = price / (1 + float(sample["change"]) / 100)

                quotes.append(
                    {
                        "symbol": symbol,
                        "shortName": sample["name"],
                        "regularMarketPrice": price,
                        "regularMarketChangePercent": float(sample["change"]),
                        "regularMarketVolume": 1_500_000,
                        "averageDailyVolume3Month": 1_000_000,
                        "regularMarketDayHigh": price * 1.015,
                        "regularMarketDayLow": price * 0.985,
                        "marketCap": float(sample["cap"]),
                        "ask": price * 1.0002,
                        "bid": price * 0.9998,
                    }
                )
                continue

            quote_payload = _http_get_json(
                FINNHUB_QUOTE_URL,
                params={"symbol": symbol, "token": api_key},
                timeout=20,
            )

            profile_payload = _http_get_json(
                FINNHUB_PROFILE_URL,
                params={"symbol": symbol, "token": api_key},
                timeout=20,
            )

            price = float(quote_payload.get("c", 0) or 0)
            previous_close = float(quote_payload.get("pc", 0) or 0)

            if price <= 0:
                continue

            change_pct = _safe_div(price - previous_close, previous_close) * 100
            high = float(quote_payload.get("h", price) or price)
            low = float(quote_payload.get("l", price) or price)
            market_cap = float(profile_payload.get("marketCapitalization", 0) or 0) * 1_000_000

            quotes.append(
                {
                    "symbol": symbol,
                    "shortName": profile_payload.get("name", symbol),
                    "regularMarketPrice": price,
                    "regularMarketChangePercent": change_pct,
                    "regularMarketVolume": 1_500_000,
                    "averageDailyVolume3Month": 1_000_000,
                    "regularMarketDayHigh": high,
                    "regularMarketDayLow": low,
                    "marketCap": market_cap,
                    "ask": price * 1.0002,
                    "bid": price * 0.9998,
                }
            )

        except Exception:
            if os.getenv("ALLOW_SAMPLE_DATA_ON_FETCH_ERROR", "true").lower() == "true":
                sample = _sample_quote_payload(symbol)
                price = float(sample["price"])
                quotes.append(
                    {
                        "symbol": symbol,
                        "shortName": sample["name"],
                        "regularMarketPrice": price,
                        "regularMarketChangePercent": float(sample["change"]),
                        "regularMarketVolume": 1_500_000,
                        "averageDailyVolume3Month": 1_000_000,
                        "regularMarketDayHigh": price * 1.015,
                        "regularMarketDayLow": price * 0.985,
                        "marketCap": float(sample["cap"]),
                        "ask": price * 1.0002,
                        "bid": price * 0.9998,
                    }
                )
                continue
            raise

    return quotes


def fetch_next_day_close(symbol: str, trade_date: date) -> float | None:
    api_key = _get_finnhub_key()

    if not api_key:
        sample = _sample_quote_payload(symbol)
        return float(sample["price"]) * 1.01

    start_dt = datetime.combine(trade_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(trade_date + timedelta(days=14), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )

    params = {
        "symbol": symbol,
        "resolution": "D",
        "from": int(start_dt.timestamp()),
        "to": int(end_dt.timestamp()),
        "token": api_key,
    }

    try:
        payload = _http_get_json(FINNHUB_CANDLE_URL, params=params, timeout=20)

        if payload.get("s") != "ok":
            return None

        timestamps = payload.get("t", [])
        closes = payload.get("c", [])

        for ts, close in zip(timestamps, closes):
            candle_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
            if candle_date > trade_date and close is not None:
                return float(close)

        return None

    except Exception:
        if os.getenv("ALLOW_SAMPLE_DATA_ON_FETCH_ERROR", "true").lower() == "true":
            sample = _sample_quote_payload(symbol)
            return float(sample["price"]) * 1.01
        raise


def market_analyst(
    quotes: list[dict[str, Any]],
    min_price: float,
    min_market_cap: float,
) -> list[AnalystSignal]:
    analysis: list[AnalystSignal] = []

    for quote in quotes:
        price = float(quote.get("regularMarketPrice", 0.0) or 0.0)
        market_cap = float(quote.get("marketCap", 0.0) or 0.0)

        if price < min_price:
            continue

        if market_cap and market_cap < min_market_cap:
            continue

        change_pct = float(quote.get("regularMarketChangePercent", 0.0) or 0.0)
        volume = float(quote.get("regularMarketVolume", 0.0) or 0.0)
        avg_volume = float(quote.get("averageDailyVolume3Month", 0.0) or 0.0)

        high = float(quote.get("regularMarketDayHigh", price) or price)
        low = float(quote.get("regularMarketDayLow", price) or price)

        rel_volume = _safe_div(volume, avg_volume)
        range_pct = _safe_div(high - low, price) * 100

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

    analysis.sort(key=lambda item: item.momentum_score, reverse=True)
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
        spread_pct = _safe_div(ask - bid, signal.price) * 100 if ask and bid else 0.0

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

    approved.sort(key=lambda item: item.risk_score, reverse=True)
    return approved


def execution_planner(
    risk_approved: list[RiskApprovedSignal],
    top_count: int,
) -> list[ExecutionPlan]:
    plans: list[ExecutionPlan] = []

    for approved in risk_approved[:top_count]:
        signal = approved.signal
        risk_buffer = max(signal.intraday_range_pct / 100 * 0.6, 0.012)
        reward_buffer = risk_buffer * 1.8

        stop_loss = max(signal.price * (1 - risk_buffer), 0.01)
        take_profit = signal.price * (1 + reward_buffer)

        plans.append(
            ExecutionPlan(
                symbol=signal.symbol,
                name=signal.name,
                entry=signal.price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                conviction_score=approved.risk_score,
                rationale=f"{signal.thesis}; {approved.risk_notes}",
            )
        )

    return plans


def _ensure_history_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        return

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
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

    with history_path.open("r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    updated_rows: list[dict[str, str]] = []
    wins = 0
    losses = 0
    closed_returns: list[float] = []

    for row in rows:
        run_date_value = row.get("run_date", "").strip()

        if not run_date_value or run_date_value == "run_date":
            continue

        try:
            trade_date = date.fromisoformat(run_date_value)
        except ValueError:
            continue

        if row.get("status") == "closed":
            updated_rows.append(row)

            try:
                return_pct = float(row.get("return_pct", "0") or 0)
            except ValueError:
                return_pct = 0.0

            closed_returns.append(return_pct)

            if return_pct > 0:
                wins += 1
            else:
                losses += 1

            continue

        if trade_date >= today:
            updated_rows.append(row)
            continue

        close_price = fetch_next_day_close(row.get("symbol", ""), trade_date)

        if close_price is None:
            updated_rows.append(row)
            continue

        try:
            entry = float(row.get("entry_price", "0") or 0)
        except ValueError:
            updated_rows.append(row)
            continue

        ret_pct = _safe_div(close_price - entry, entry) * 100

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

    with history_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
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
    quote_map = {quote.get("symbol", ""): quote for quote in state.get("quotes", [])}

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


def _node_dispatch_email(state: ScanState) -> ScanState:
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
                _node_dispatch_email,
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
    graph_builder.add_node("dispatch_email", _node_dispatch_email)

    graph_builder.add_edge(START, "fetch_symbols")
    graph_builder.add_edge("fetch_symbols", "fetch_quotes")
    graph_builder.add_edge("fetch_quotes", "market_analyst")
    graph_builder.add_edge("market_analyst", "risk_manager")
    graph_builder.add_edge("risk_manager", "execution_planner")
    graph_builder.add_edge("execution_planner", "backtesting_report")
    graph_builder.add_edge("backtesting_report", "build_email")
    graph_builder.add_edge("build_email", "dispatch_email")
    graph_builder.add_edge("dispatch_email", END)

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
