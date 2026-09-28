from __future__ import annotations
import asyncio
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from defusedxml import ElementTree as ET

import httpx
import pandas as pd


class MarketSourceError(RuntimeError):
    pass


# Public, research-grade sources. These are context sources only; exchange feeds remain
# authoritative for execution prices. URLs are configurable in deployment if a publisher
# changes its feed endpoint.
DEFAULT_NEWS_SOURCES: tuple[dict[str, str], ...] = (
    {"name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "tier": "official"},
    {"name": "ECB Market Information Dissemination", "url": "https://mid.ecb.europa.eu/rss/mid.xml", "tier": "official"},
)

RISK_TERMS = {
    "hawkish": ("hawkish", 1.0), "rate hike": ("rate_hike", 1.0), "higher for longer": ("higher_for_longer", 1.0),
    "inflation": ("inflation", 0.7), "recession": ("recession", 1.0), "credit stress": ("credit_stress", 1.2),
    "bank losses": ("financial_stress", 1.2), "geopolitical": ("geopolitical", 0.8), "war": ("geopolitical", 1.0),
    "oil": ("energy", 0.5), "bond selloff": ("rates_stress", 1.0), "yield": ("rates", 0.3),
}
POSITIVE_TERMS = {"dovish": 1.0, "rate cut": 0.9, "disinflation": 0.7, "soft landing": 0.6, "liquidity": 0.5}


def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise MarketSourceError("No market data returned")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [c[0] if isinstance(c, tuple) else c for c in frame.columns]
    rename = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"}
    frame = frame.rename(columns=rename)
    required = ["open", "high", "low", "close"]
    if not all(c in frame.columns for c in required):
        raise MarketSourceError("Yahoo Finance response is missing OHLC fields")
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, utc=True)
    for c in ["open", "high", "low", "close", "volume"]:
        if c in frame.columns:
            frame[c] = pd.to_numeric(frame[c], errors="coerce")
    return frame.dropna(subset=required).sort_index()


def yahoo_history(symbol: str, period: str = "3y", interval: str = "1d") -> pd.DataFrame:
    """Historical reference data. Never use Yahoo as the execution price source."""
    import yfinance as yf
    frame = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
    return _normalize_ohlcv(frame)


def _parse_feed_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            return None


def _xml_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def _parse_rss(xml_text: str, source: dict[str, str]) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:30]:
        title = _xml_text(item.find("title"))
        link = _xml_text(item.find("link"))
        desc = _xml_text(item.find("description"))
        published = _xml_text(item.find("pubDate")) or _xml_text(item.find("published"))
        items.append({
            "source": source["name"], "tier": source["tier"], "title": title,
            "url": link, "summary": desc[:1200], "published_at": _parse_feed_date(published),
        })
    return items


def fetch_public_news_sources(sources: tuple[dict[str, str], ...] = DEFAULT_NEWS_SOURCES, timeout: float = 8.0) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Fetch public macro feeds. Failures are recorded and never become trade signals."""
    articles: list[dict[str, Any]] = []
    failures: dict[str, str] = {}
    for source in sources:
        try:
            response = httpx.get(source["url"], timeout=timeout, follow_redirects=True, headers={"User-Agent": "AtlasTradingOS/3.10 market-research"})
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "xml" not in content_type and not response.text.lstrip().startswith("<"):
                raise MarketSourceError("source did not return XML/RSS")
            articles.extend(_parse_rss(response.text, source))
        except Exception as exc:
            failures[source["name"]] = str(exc)
    return articles, failures


def _trend_snapshot(frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"].astype(float).dropna()
    if len(close) < 60:
        return {"status": "INSUFFICIENT_DATA", "bars": len(close)}
    last = float(close.iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    ret20 = float(close.iloc[-1] / close.iloc[-21] - 1.0) if len(close) > 21 else 0.0
    vol20 = float(close.pct_change().rolling(20).std().iloc[-1] * (252 ** 0.5))
    peak = float(close.cummax().iloc[-1])
    drawdown = last / peak - 1.0 if peak else 0.0
    return {
        "status": "OK", "bars": len(close), "last": last,
        "ma20": ma20, "ma50": ma50, "return_20d": ret20,
        "volatility_annualized": vol20, "drawdown_from_peak": drawdown,
        "trend": "UP" if last > ma20 > ma50 else "DOWN" if last < ma20 < ma50 else "MIXED",
    }


def _headline_risk(articles: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, float] = {}
    positive = 0.0
    negative = 0.0
    for item in articles:
        text = f"{item.get('title','')} {item.get('summary','')}".lower()
        for term, (bucket, weight) in RISK_TERMS.items():
            if term in text:
                buckets[bucket] = buckets.get(bucket, 0.0) + weight
                negative += weight
        for term, weight in POSITIVE_TERMS.items():
            if term in text:
                positive += weight
    return {
        "risk_score": round(min(1.0, negative / max(5.0, len(articles))), 4),
        "supportive_score": round(min(1.0, positive / max(5.0, len(articles))), 4),
        "risk_themes": sorted(buckets.items(), key=lambda x: x[1], reverse=True)[:8],
    }


def summarize_news(items: list[dict[str, Any]]) -> dict[str, Any]:
    sentiments = []
    topics: dict[str, int] = {}
    for item in items:
        score = item.get("overall_sentiment_score")
        try:
            if score is not None:
                sentiments.append(float(score))
        except (TypeError, ValueError):
            pass
        for topic in item.get("topics", []) or []:
            label = topic.get("topic") if isinstance(topic, dict) else str(topic)
            if label:
                topics[label] = topics.get(label, 0) + 1
    return {
        "article_count": len(items),
        "average_sentiment": sum(sentiments) / len(sentiments) if sentiments else 0.0,
        "top_topics": sorted(topics.items(), key=lambda x: x[1], reverse=True)[:10],
        "headline_risk": _headline_risk(items),
    }


def alpha_vantage_news(api_key: str, tickers: list[str] | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not api_key:
        return []
    params = {"function": "NEWS_SENTIMENT", "apikey": api_key, "limit": str(min(max(limit, 1), 1000))}
    if tickers:
        params["tickers"] = ",".join(tickers[:50])
    response = httpx.get("https://www.alphavantage.co/query", params=params, timeout=20.0)
    response.raise_for_status()
    payload = response.json()
    return payload.get("feed", []) if isinstance(payload, dict) else []


async def gather_market_intelligence(symbols: list[str], yahoo_period: str = "3y",
                                     alpha_vantage_api_key: str = "") -> dict[str, Any]:
    def collect():
        histories = {}
        failures = {}
        snapshots = {}
        for symbol in symbols:
            try:
                histories[symbol] = yahoo_history(symbol, period=yahoo_period)
                snapshots[symbol] = _trend_snapshot(histories[symbol])
            except Exception as exc:
                failures[symbol] = str(exc)
        news = []
        news_error = ""
        try:
            news = alpha_vantage_news(alpha_vantage_api_key, symbols)
        except Exception as exc:
            news_error = str(exc)
        public_news, public_failures = fetch_public_news_sources()
        all_news = public_news + news
        news_summary = summarize_news(all_news)
        regime = {
            "risk_state": "ELEVATED" if news_summary["headline_risk"]["risk_score"] >= 0.35 else "NORMAL",
            "assets": snapshots,
            "source_count": len({x.get("source") for x in all_news if x.get("source")}),
        }
        return histories, failures, snapshots, all_news, news_error, public_failures, regime

    histories, failures, snapshots, news, news_error, public_failures, regime = await asyncio.to_thread(collect)
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "sources": ["yahoo_finance", "alpha_vantage_news", "federal_reserve", "ecb_market_information_dissemination"],
        "histories": histories,
        "trend_snapshots": snapshots,
        "failures": {**failures, **{f"news:{k}": v for k, v in public_failures.items()}},
        "news": news,
        "news_summary": summarize_news(news),
        "news_error": news_error,
        "macro_regime": regime,
        "freshness": {"collected_at": datetime.now(timezone.utc).isoformat(), "max_history_period": yahoo_period, "stale_data_is_not_executable": True},
        "execution_authority": False,
    }
