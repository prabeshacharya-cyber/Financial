from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from typing import Any
from urllib import parse, request
import xml.etree.ElementTree as ET


POSITIVE_WORDS = {
    "beat",
    "beats",
    "growth",
    "surge",
    "up",
    "upgrade",
    "bullish",
    "strong",
    "gain",
    "gains",
    "rally",
    "record",
    "profit",
    "profits",
}

NEGATIVE_WORDS = {
    "miss",
    "misses",
    "down",
    "downgrade",
    "bearish",
    "weak",
    "drop",
    "drops",
    "fall",
    "falls",
    "loss",
    "losses",
    "lawsuit",
    "probe",
}


@dataclass
class SentimentHeadline:
    symbol: str
    title: str
    link: str
    sentiment_score: float


def _score_text(text: str) -> float:
    words = [w.strip(".,:;!?()[]{}\"'`).-").lower() for w in text.split()]
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _fetch_symbol_rss(symbol: str) -> list[SentimentHeadline]:
    feed_url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline?"
        + parse.urlencode({"s": symbol, "region": "US", "lang": "en-US"})
    )

    with request.urlopen(feed_url, timeout=15) as resp:
        xml_bytes = resp.read()

    root = ET.fromstring(xml_bytes)
    headlines: list[SentimentHeadline] = []
    for item in root.findall(".//item")[:8]:
        title = unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        score = _score_text(title)
        headlines.append(
            SentimentHeadline(
                symbol=symbol,
                title=title,
                link=link,
                sentiment_score=score,
            )
        )

    return headlines


def get_news_sentiment(symbols: list[str]) -> dict[str, Any]:
    all_headlines: list[SentimentHeadline] = []

    for symbol in symbols:
        try:
            all_headlines.extend(_fetch_symbol_rss(symbol))
        except Exception:
            continue

    per_symbol: dict[str, list[float]] = {}
    for h in all_headlines:
        per_symbol.setdefault(h.symbol, []).append(h.sentiment_score)

    symbol_scores = {
        symbol: (sum(scores) / len(scores) if scores else 0.0)
        for symbol, scores in per_symbol.items()
    }

    top_positive = sorted(all_headlines, key=lambda x: x.sentiment_score, reverse=True)[:10]
    top_negative = sorted(all_headlines, key=lambda x: x.sentiment_score)[:10]

    return {
        "symbol_scores": symbol_scores,
        "top_positive": top_positive,
        "top_negative": top_negative,
    }
