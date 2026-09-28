from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import math
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WalkForwardFold:
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    purge: int
    embargo: int


def validate_ohlcv_frame(df: pd.DataFrame, require_volume: bool = False) -> dict:
    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(df.columns))
    issues: list[str] = []
    if missing:
        issues.append("missing_columns:" + ",".join(missing))
    if not isinstance(df.index, pd.DatetimeIndex):
        issues.append("index_not_datetime")
    else:
        if not df.index.is_monotonic_increasing:
            issues.append("index_not_monotonic")
        if df.index.has_duplicates:
            issues.append("duplicate_timestamps")
    if require_volume and "volume" not in df.columns:
        issues.append("missing_volume")
    if not missing:
        numeric = df[list(required)].apply(pd.to_numeric, errors="coerce")
        if numeric.isna().any().any():
            issues.append("non_numeric_or_nan_ohlc")
        # Some vendors reconstruct/open-adjust bars; enforce the core high/low/close
        # envelope while reporting open anomalies separately rather than rejecting
        # an otherwise usable series outright.
        bad_range = (numeric["high"] < numeric[["close", "low"]].max(axis=1)) | (numeric["low"] > numeric[["close", "high"]].min(axis=1))
        if bool(bad_range.fillna(False).any()):
            issues.append("invalid_ohlc_range")
        if bool((numeric <= 0).any().any()):
            issues.append("non_positive_ohlc")
    return {"valid": not issues, "issues": issues, "rows": int(len(df))}


def purged_walk_forward_splits(n: int, folds: int = 5, min_train: int = 800,
                               test_size: int | None = None, purge: int = 1,
                               embargo: int = 1) -> list[WalkForwardFold]:
    if n <= 0 or folds <= 0 or min_train <= 0:
        return []
    if test_size is None:
        remaining = max(0, n - min_train)
        test_size = max(1, remaining // folds) if remaining else 0
    if test_size <= 0:
        return []
    out: list[WalkForwardFold] = []
    train_end = min_train
    for _ in range(folds):
        test_start = train_end + max(0, purge)
        test_end = min(n, test_start + test_size)
        if test_end <= test_start:
            break
        out.append(WalkForwardFold(0, train_end, test_start, test_end, purge, embargo))
        train_end = min(n, test_end + max(0, embargo))
        if train_end >= n:
            break
    return out


def bootstrap_mean_ci(returns: Iterable[float], samples: int = 2000,
                      seed: int = 17, alpha: float = 0.05,
                      block_size: int = 1) -> dict:
    x = np.asarray(list(returns), dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 20:
        return {"status": "INSUFFICIENT_DATA", "n": int(len(x))}
    rng = np.random.default_rng(seed)
    if block_size <= 1:
        draws = rng.integers(0, len(x), size=(samples, len(x)))
        means = x[draws].mean(axis=1)
    else:
        blocks = [x[i:i + block_size] for i in range(0, len(x) - block_size + 1)]
        means = np.empty(samples, dtype=float)
        for j in range(samples):
            chosen = []
            while len(chosen) < len(x):
                chosen.extend(blocks[int(rng.integers(0, len(blocks)))])
            means[j] = np.mean(chosen[:len(x)])
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return {"status": "OK", "n": int(len(x)), "mean": float(x.mean()), "ci_low": float(lo), "ci_high": float(hi), "alpha": alpha}


def multiple_testing_sharpe_adjustment(sharpes: Iterable[float], trials: int) -> dict:
    s = np.asarray([x for x in sharpes if np.isfinite(x)], dtype=float)
    if len(s) == 0:
        return {"status": "INSUFFICIENT_DATA"}
    # Conservative benchmark: expected maximum of trials of N(0,1), scaled to the
    # observed Sharpe dispersion. This is a screening proxy, not a formal DSR.
    m = max(1, int(trials))
    expected_max = math.sqrt(2.0 * math.log(m)) if m > 1 else 0.0
    best = float(np.max(s))
    dispersion = float(np.std(s)) if len(s) > 1 else 1.0
    adjusted = best - expected_max * dispersion
    return {"status": "OK", "best_sharpe": best, "trials": m,
            "expected_null_max_proxy": expected_max, "adjusted_sharpe_proxy": float(adjusted),
            "note": "Screening proxy only; not a formal Deflated Sharpe Ratio."}


def cost_sensitivity(returns_gross: Iterable[float], turnover: Iterable[float],
                     cost_bps_grid: Iterable[float] = (2, 5, 10, 20, 40)) -> list[dict]:
    r = np.asarray(list(returns_gross), dtype=float)
    t = np.asarray(list(turnover), dtype=float)
    n = min(len(r), len(t))
    if n == 0:
        return []
    r, t = r[:n], t[:n]
    out = []
    for bps in cost_bps_grid:
        net = r - t * float(bps) / 10_000.0
        out.append({"cost_bps": float(bps), "total_return": float(np.prod(1 + net) - 1),
                    "mean_return": float(np.nanmean(net)), "positive_mean": bool(np.nanmean(net) > 0)})
    return out


def ohlc_trade_ambiguity(df: pd.DataFrame, stop: pd.Series, target: pd.Series,
                         side: pd.Series) -> dict:
    ambiguous = 0
    checked = 0
    for idx in df.index:
        try:
            lo, hi = float(df.at[idx, "low"]), float(df.at[idx, "high"])
            st, tp, s = float(stop.at[idx]), float(target.at[idx]), str(side.at[idx])
        except Exception:
            continue
        if s not in {"buy", "sell"} or not np.isfinite(st) or not np.isfinite(tp):
            continue
        checked += 1
        if s == "buy":
            hit_stop, hit_target = lo <= st, hi >= tp
        else:
            hit_stop, hit_target = hi >= st, lo <= tp
        if hit_stop and hit_target:
            ambiguous += 1
    return {"checked": checked, "ambiguous": ambiguous,
            "ambiguity_rate": float(ambiguous / checked) if checked else 0.0,
            "policy": "WORST_CASE" if ambiguous else "NONE"}


def fixed_signal_walk_forward_oos(df: pd.DataFrame, signal: pd.Series, costs_bps: float = 7.5,
                                 folds: int = 5, min_train: int = 800) -> dict:
    """Evaluate a fixed signal only on forward test windows.

    No parameter fitting occurs here; the split is used to make the evaluation
    boundary explicit and prevent accidentally reporting in-sample performance
    as out-of-sample evidence.
    """
    splits = purged_walk_forward_splits(len(df), folds=folds, min_train=min_train, purge=1, embargo=1)
    if not splits:
        return {"status": "INSUFFICIENT_DATA", "folds": []}
    s = pd.Series(signal, index=df.index).astype(float).fillna(0.0)
    ret = df["close"].pct_change().fillna(0.0)
    turnover = s.diff().abs().fillna(s.abs())
    net = s.shift(1).fillna(0.0) * ret - turnover * float(costs_bps) / 10000.0
    fold_rows = []
    oos = []
    for fold in splits:
        x = net.iloc[fold.test_start:fold.test_end]
        oos.append(x)
        fold_rows.append({
            "test_start": df.index[fold.test_start].isoformat(),
            "test_end": df.index[fold.test_end - 1].isoformat(),
            "bars": int(len(x)),
            "total_return": float(np.prod(1 + x.to_numpy()) - 1) if len(x) else 0.0,
            "mean_return": float(x.mean()) if len(x) else 0.0,
        })
    all_oos = pd.concat(oos) if oos else pd.Series(dtype=float)
    return {
        "status": "OK", "folds": fold_rows, "oos_bars": int(len(all_oos)),
        "oos_total_return": float(np.prod(1 + all_oos.to_numpy()) - 1) if len(all_oos) else 0.0,
        "oos_mean_return": float(all_oos.mean()) if len(all_oos) else 0.0,
        "costs_bps": float(costs_bps),
    }


def regime_conditioned_performance(df: pd.DataFrame, returns: pd.Series, asset: str = "crypto") -> dict:
    close = df["close"].astype(float)
    fast = close.ewm(span=50, adjust=False).mean()
    slow = close.ewm(span=200, adjust=False).mean()
    annual_factor = 365.25 if str(asset).lower() == "crypto" else 252.0
    vol = close.pct_change().rolling(20).std() * np.sqrt(annual_factor)
    regimes = pd.Series("RANGE", index=df.index)
    regimes = regimes.mask((fast > slow) & (vol < 0.60), "TREND_UP")
    regimes = regimes.mask((fast < slow) & (vol < 0.60), "TREND_DOWN")
    regimes = regimes.mask(vol >= 0.60, "HIGH_VOL")
    out = {}
    r = pd.Series(returns, index=df.index).fillna(0.0)
    for name in sorted(regimes.dropna().unique()):
        x = r[regimes == name]
        out[str(name)] = {"bars": int(len(x)), "mean_return": float(x.mean()) if len(x) else 0.0,
                          "total_return": float(np.prod(1 + x.to_numpy()) - 1) if len(x) else 0.0}
    return out


def oos_promotion_gate(oos: dict, *, min_folds: int = 5, min_total_return: float = 0.0, min_positive_fold_ratio: float = 0.5, max_negative_fold_return: float = -0.20, require_last_fold_positive: bool = True, min_sharpe: float | None = None, max_drawdown: float | None = None, min_trades: int | None = None) -> dict:
    folds = list(oos.get("folds") or [])
    returns = [float(f.get("total_return", 0.0)) for f in folds]
    positive_ratio = (sum(r > 0 for r in returns) / len(returns)) if returns else 0.0
    worst = min(returns) if returns else -1.0
    last_positive = bool(returns and returns[-1] > 0)
    sharpe = float(oos.get("sharpe", 0.0)) if "sharpe" in oos else None
    max_dd = float(oos.get("max_drawdown", -1.0)) if "max_drawdown" in oos else None
    trades = int(oos.get("trades", 0)) if "trades" in oos else None
    sharpe_ok = True if min_sharpe is None or sharpe is None else sharpe >= float(min_sharpe)
    dd_ok = True if max_drawdown is None or max_dd is None else max_dd >= float(max_drawdown)
    trades_ok = True if min_trades is None or trades is None else trades >= int(min_trades)
    passed = bool(
        str(oos.get("status", "OK")) == "OK" and len(returns) >= int(min_folds) and
        float(oos.get("oos_total_return", oos.get("total_return", -1.0))) >= float(min_total_return) and
        positive_ratio >= float(min_positive_fold_ratio) and worst >= float(max_negative_fold_return) and
        (last_positive if require_last_fold_positive else True) and sharpe_ok and dd_ok and trades_ok
    )
    return {"passed": passed, "folds": len(returns), "positive_fold_ratio": positive_ratio, "worst_fold_return": worst, "last_fold_positive": last_positive, "sharpe": sharpe, "max_drawdown": max_dd, "trades": trades, "sharpe_ok": sharpe_ok, "max_drawdown_ok": dd_ok, "min_trades_ok": trades_ok, "thresholds": {"min_folds": min_folds, "min_total_return": min_total_return, "min_positive_fold_ratio": min_positive_fold_ratio, "max_negative_fold_return": max_negative_fold_return, "require_last_fold_positive": require_last_fold_positive, "min_sharpe": min_sharpe, "max_drawdown": max_drawdown, "min_trades": min_trades}}

def monte_carlo_bootstrap(returns, *, trials: int = 2000, seed: int = 7, block_size: int = 5) -> dict:
    """Time-series-aware block bootstrap stress summary; research only, not a forecast."""
    arr=np.asarray(list(returns),dtype=float)
    arr=arr[np.isfinite(arr)]
    if len(arr)<20: return {"status":"INSUFFICIENT_DATA","observations":int(len(arr))}
    rng=np.random.default_rng(seed)
    n=len(arr); size=max(1,min(int(block_size),n))
    blocks=[arr[i:i+size] for i in range(0,n-size+1)]
    outcomes=np.empty(trials); max_dd=np.empty(trials)
    for i in range(trials):
        sample=[]
        while len(sample)<n:
            sample.extend(blocks[int(rng.integers(0,len(blocks)))].tolist())
        sample=np.asarray(sample[:n],dtype=float)
        equity=np.cumprod(1.0+sample)
        peak=np.maximum.accumulate(equity)
        dd=equity/peak-1.0
        outcomes[i]=equity[-1]-1.0; max_dd[i]=dd.min()
    return {"status":"OK","observations":int(n),"trials":int(trials),"block_size":int(size),"return_p05":float(np.quantile(outcomes,0.05)),"return_median":float(np.quantile(outcomes,0.50)),"return_p95":float(np.quantile(outcomes,0.95)),"drawdown_p05":float(np.quantile(max_dd,0.05)),"drawdown_median":float(np.quantile(max_dd,0.50)),"probability_negative_return":float(np.mean(outcomes<0))}

def parameter_plateau_score(results: dict, *, metric: str = "sharpe", tolerance: float = 0.20) -> dict:
    """Measure whether nearby parameter variants retain most of the best metric."""
    rows=results.get("variants") if isinstance(results,dict) else None
    if not rows: return {"status":"INSUFFICIENT_DATA"}
    vals=[float(r.get(metric,0.0)) for r in rows if np.isfinite(float(r.get(metric,0.0)))]
    if not vals: return {"status":"INSUFFICIENT_DATA"}
    best=max(vals); floor=best*(1.0-float(tolerance))
    plateau=sum(v>=floor for v in vals)/len(vals)
    return {"status":"OK","metric":metric,"best":best,"floor":floor,"plateau_ratio":plateau,"robust":plateau>=0.30,"variants":len(vals)}
