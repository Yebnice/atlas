from __future__ import annotations
from datetime import datetime, timezone
import time
import numpy as np
import pandas as pd


def _validate_ohlcv(df: pd.DataFrame, timeframe: str, reject_gaps: bool = True) -> pd.DataFrame:
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing OHLCV columns: {missing}")
    out = df[required].copy()
    out.index = pd.to_datetime(out.index, utc=True)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    if out.empty:
        raise RuntimeError("Market data is empty after cleaning")
    bad = (
        (out["open"] <= 0) | (out["high"] <= 0) | (out["low"] <= 0) | (out["close"] <= 0)
        | (out["high"] < out[["open", "close", "low"]].max(axis=1))
        | (out["low"] > out[["open", "close", "high"]].min(axis=1))
        | (out["volume"] < 0)
    )
    if bool(bad.any()):
        raise RuntimeError("Invalid OHLCV rows detected")
    if len(out) >= 3:
        try:
            tf_ms = int(pd.Timedelta(timeframe) / pd.Timedelta(milliseconds=1))
        except Exception:
            tf_ms = None
        if tf_ms:
            delta_ms = out.index.to_series().diff().dt.total_seconds().mul(1000)
            # Gaps can legitimately occur in FX weekends, so we only reject very large gaps
            # for an aggressively misconfigured crypto stream upstream.
            if reject_gaps and (delta_ms.dropna() > tf_ms * 3).sum() > max(1, len(out) // 100):
                raise RuntimeError("Market data contains excessive timestamp gaps")
    return out


def fetch_crypto(symbol: str, exchange: str = "bybit", timeframe: str = "1h", days: int = 365,
                 closed_only: bool = True) -> pd.DataFrame:
    import ccxt
    if exchange not in ccxt.exchanges:
        raise RuntimeError(f"Unsupported CCXT exchange: {exchange}")
    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    try:
        ex.load_markets()
        if symbol not in ex.markets:
            raise RuntimeError(f"Unknown symbol for {exchange}: {symbol}")
        now_ms = ex.milliseconds()
        tf_ms = ex.parse_timeframe(timeframe) * 1000
        since = now_ms - days * 86_400_000
        rows: list[list[float]] = []
        cursor = since
        while cursor < now_ms:
            batch = ex.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
            if not batch:
                break
            rows.extend(batch)
            next_cursor = int(batch[-1][0]) + tf_ms
            if next_cursor <= cursor:
                raise RuntimeError("Exchange returned non-advancing OHLCV timestamps")
            cursor = next_cursor
            if len(batch) < 1000:
                break
        if not rows:
            raise RuntimeError("No crypto OHLCV returned")
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.drop_duplicates("ts").set_index("ts").sort_index()
        if closed_only:
            cutoff = pd.Timestamp(datetime.fromtimestamp((now_ms - tf_ms) / 1000, tz=timezone.utc))
            df = df[df.index <= cutoff]
        return _validate_ohlcv(df, timeframe)
    finally:
        if hasattr(ex, "close") and callable(ex.close):
            ex.close()


def fetch_forex(symbol: str = "EURUSD", timeframe: str = "1h", days: int = 365) -> pd.DataFrame:
    import yfinance as yf
    yf_sym = symbol if "=X" in symbol else symbol + "=X"
    interval = timeframe if timeframe in {"1m", "5m", "15m", "30m", "1h", "1d"} else "1h"
    period = f"{min(days, 720)}d" if interval != "1d" else f"{days}d"
    raw = yf.download(yf_sym, period=period, interval=interval, auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("No FX data returned")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    raw = raw[["open", "high", "low", "close", "volume"]].dropna()
    raw.index = pd.to_datetime(raw.index, utc=True)
    return _validate_ohlcv(raw, timeframe, reject_gaps=False)


def fetch_forex_oanda(symbol: str = "EUR_USD", timeframe: str = "1h", days: int = 365) -> pd.DataFrame:
    """Fetch completed OANDA v20 mid candles for the configured practice/demo account only."""
    from .config import settings
    from .forex_oanda import OandaBroker, OandaConfig
    granularity = {"1m":"M1", "5m":"M5", "15m":"M15", "30m":"M30", "1h":"H1", "4h":"H4", "1d":"D"}.get(timeframe)
    if not granularity:
        raise RuntimeError(f"Unsupported OANDA timeframe: {timeframe}")
    if not settings.oanda_practice:
        raise RuntimeError("OANDA live mode is disabled in AtlasRisk; use practice/demo for learning and backtesting")
    broker = OandaBroker(OandaConfig(settings.oanda_account_id, settings.oanda_api_token, True, settings.oanda_timeout_seconds))
    try:
        count = min(5000, max(250, int(days * 24) if granularity == "H1" else int(days * 24 * 60 / max(1, int(timeframe[:-1])))))
        candles = broker.candles(symbol, granularity, count=count)
    finally:
        broker.close()
    rows = []
    for c in candles:
        if not c.get("complete"):
            continue
        m = c.get("mid") or {}
        rows.append([c.get("time"), float(m.get("o")), float(m.get("h")), float(m.get("l")), float(m.get("c")), float(c.get("volume") or 0)])
    if not rows:
        raise RuntimeError("No completed OANDA candles returned")
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return _validate_ohlcv(df.set_index("ts"), timeframe, reject_gaps=False)
