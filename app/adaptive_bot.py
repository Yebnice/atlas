from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .trading_core import train_model, ai_walk_forward_backtest, load_model, build_features, FEATURE_COLUMNS
from .model_registry import backup_champion, verify_model_file
from .research_validation import oos_promotion_gate

import numpy as np


@dataclass(frozen=True)
class AdaptiveModelPolicy:
    max_age_hours: float = 24.0
    min_sharpe: float = 0.50
    max_drawdown: float = -0.25
    min_trades: int = 20
    min_total_return: float = 0.0
    max_champion_sharpe_drop: float = 0.10
    max_champion_drawdown_worsening: float = 0.05
    max_champion_return_drop: float = 0.10


def _meta_path(model_path: str | Path) -> Path:
    p = Path(model_path)
    return p.with_suffix(p.suffix + ".adaptive.json")


def _read_meta(model_path: str | Path) -> dict | None:
    p = _meta_path(model_path)
    if not p.exists():
        return None
    try:
        value = json.loads(p.read_text())
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# Only a subset of FEATURE_COLUMNS is eligible for PSI-based drift monitoring.
# FEATURE_COLUMNS includes several long rolling-window statistics (trend_50/200,
# vol_72, drawdown_72, range_z/vol_z/range_regime/vol_ratio_24_72, all built on a
# 72-200 bar lookback) plus pure calendar features (hour_sin/cos, dow). Empirically
# (synthetic no-drift walk-forward tests, 20 trials): comparing a short recent
# sample against a full-history baseline on those long-window features produced
# ALERT-level PSI on every single trial with *no* injected drift at all -- because
# a few hundred recent bars of a 72-200 bar rolling statistic are a handful of
# heavily overlapping, autocorrelated windows, not independent draws, so they
# routinely miss the baseline's outer deciles by chance alone. Calendar features
# have the same problem for an unrelated reason: a short window just doesn't cover
# a full day/week cycle, which looks like "drift" but isn't a market signal at all.
# Restricting monitoring to short-window, high-frequency features keeps the false
# alarm rate low while still catching genuine regime shifts (see compute_feature_drift).
DRIFT_MONITORED_FEATURES = [
    "ret_1", "ret_4", "ret_12", "ret_24",
    "vol_1", "vol_4", "vol_12", "vol_24",
    "range", "rsi_14", "atr_pct_14", "trend_slope_20", "volume_trend_24",
]


def _feature_baseline(features_df, bins: int = 6) -> dict:
    """Snapshot each drift-monitored feature's training-time distribution as bin edges.

    This is stored on the champion's metadata at promotion time and later compared
    against live data with `compute_feature_drift` (population stability index) so
    that "the model hasn't changed" and "the market it's scoring hasn't drifted" are
    two separately observable facts instead of being conflated into one age-based gate.
    """
    baseline: dict[str, dict] = {}
    quantiles = np.linspace(0, 1, bins + 1)
    for col in DRIFT_MONITORED_FEATURES:
        if col not in features_df.columns:
            continue
        series = features_df[col].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        if len(series) < bins * 5:
            continue
        edges = np.unique(np.quantile(series.to_numpy(), quantiles)).tolist()
        if len(edges) < 3:
            continue
        baseline[col] = {"edges": edges, "n": int(len(series))}
    return baseline


def _psi(edges: list[float], sample: "np.ndarray") -> float:
    """Population Stability Index of `sample` against the baseline bin edges.

    Baseline bin proportions are reconstructed as uniform (each bin held ~1/(len(edges)-1)
    of the training sample by construction, since edges are quantile cut points). PSI
    compares that to where the new sample's mass actually falls. PSI < 0.1: no material
    shift. 0.1-0.25: moderate. > 0.25: significant distribution shift.

    Uses additive (Laplace) smoothing on the observed bin counts rather than clipping
    proportions to a tiny epsilon floor. Many of these features are long rolling-window
    statistics (e.g. a 72-bar std), so a short recent sample is a handful of *overlapping,
    autocorrelated* windows, not independent draws -- it's common for it to simply miss the
    baseline's outer deciles by chance. A hard epsilon floor (e.g. 1e-4) turns that routine
    sampling gap into a multi-point PSI swing on its own, which produced ALERT-level scores
    on synthetic data with no injected drift at all. Laplace smoothing keeps a genuinely
    empty bin's contribution bounded instead of letting it dominate the score.
    """
    n_bins = len(edges) - 1
    if n_bins <= 0 or len(sample) == 0:
        return 0.0
    expected = np.full(n_bins, 1.0 / n_bins)
    bounded = np.clip(sample, edges[0], edges[-1])
    counts, _ = np.histogram(bounded, bins=edges)
    total = int(counts.sum())
    alpha = 1.0
    actual = (counts.astype(float) + alpha) / (total + alpha * n_bins)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def compute_feature_drift(df, baseline: dict | None, *, sample_bars: int = 300, min_samples_per_bin: int = 20) -> dict:
    """Compare the most recent `sample_bars` of live feature data against the champion's
    training-time baseline. Returns per-feature PSI plus an overall status.

    Deliberately independent of the retrain/promotion schedule: a model can be "fresh"
    (recently trained, within max_age_hours) while the market it scores has already
    drifted underneath it. This gives that a name instead of leaving it invisible until
    live performance quietly degrades.
    """
    if not baseline:
        return {"status": "NO_BASELINE", "reason": "Champion has no stored feature baseline (trained before drift tracking was added, or too little training data)."}
    try:
        features = build_features(df)
    except Exception as exc:
        return {"status": "ERROR", "reason": f"Could not build features for drift check: {exc}"}
    if features.empty:
        return {"status": "INSUFFICIENT_DATA"}
    recent = features.tail(sample_bars)
    per_feature: dict[str, float] = {}
    skipped_thin: list[str] = []
    for col, spec in baseline.items():
        if col not in recent.columns:
            continue
        sample = recent[col].astype(float).replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
        n_bins = max(len(spec["edges"]) - 1, 1)
        if len(sample) < n_bins * min_samples_per_bin:
            # Too few points per bin for PSI to be a meaningful signal rather than sampling
            # noise (see _psi docstring) -- skip this feature instead of reporting a number
            # that looks precise but isn't.
            skipped_thin.append(col)
            continue
        per_feature[col] = round(_psi(spec["edges"], sample), 4)
    if not per_feature:
        return {"status": "INSUFFICIENT_DATA", "skipped_thin_sample": skipped_thin}
    mean_psi = float(np.mean(list(per_feature.values())))
    max_psi = float(np.max(list(per_feature.values())))
    max_feature = max(per_feature, key=per_feature.get)
    # Status is driven by the MEAN PSI across the monitored feature set, not the max.
    # A single noisy feature spiking is common even with no real drift (see
    # DRIFT_MONITORED_FEATURES above); a genuine regime shift moves most of these
    # short-window features together. Empirically this separates cleanly: no-drift
    # trials landed at mean PSI ~0.02-0.10, an injected volatility-regime shift landed
    # at ~1.1+. max_psi/max_psi_feature are still reported for diagnosis of *which*
    # feature moved most, but they don't drive the alert.
    status = "ALERT" if mean_psi > 0.25 else ("WARN" if mean_psi > 0.10 else "OK")
    return {
        "status": status,
        "mean_psi": round(mean_psi, 4),
        "max_psi": round(max_psi, 4),
        "max_psi_feature": max_feature,
        "per_feature_psi": per_feature,
        "skipped_thin_sample": skipped_thin,
        "sample_bars": int(len(recent)),
        "thresholds": {"warn": 0.10, "alert": 0.25},
    }


def model_is_fresh(model_path: str | Path, policy: AdaptiveModelPolicy) -> bool:
    meta = _read_meta(model_path)
    if not meta or meta.get("status") != "CHAMPION":
        return False
    # A model trained with an older feature schema is never considered fresh.
    features = meta.get("features")
    # Champions written before 3.10.36 stored an int (a column *count*) here. Treat any
    # non-list as stale instead of raising, so those bots self-heal by retraining rather
    # than crash-looping until an operator deletes metadata by hand.
    if not isinstance(features, list) or features != list(FEATURE_COLUMNS):
        return False
    trained_at = meta.get("trained_at")
    try:
        dt = datetime.fromisoformat(str(trained_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt <= timedelta(hours=policy.max_age_hours)
    except Exception:
        return False


def ensure_adaptive_model(
    df,
    model_path: str,
    *,
    asset: str = "crypto",
    min_train: int = 800,
    folds: int = 5,
    threshold: float = 0.05,
    policy: AdaptiveModelPolicy | None = None,
) -> dict:
    """Auto-retrain, validate, and promote a model only after OOS gates pass.

    The previous champion remains untouched if the challenger fails validation.
    This is deliberately retrain-from-scratch rather than naive continual learning.
    """
    policy = policy or AdaptiveModelPolicy()
    model_path = Path(model_path)
    existing = _read_meta(model_path)
    if model_is_fresh(model_path, policy):
        return {
            "status": "CHAMPION_FRESH",
            "model_path": str(model_path),
            "model_version": existing.get("model_sha256", "") if existing else "",
            "trained_at": existing.get("trained_at") if existing else None,
            "promotion": "UNCHANGED",
            "policy": asdict(policy),
            "feature_drift": compute_feature_drift(df, (existing or {}).get("feature_baseline")),
        }

    # Run the exact same walk-forward evaluator used for research before training
    # a deployable candidate. This keeps model promotion tied to OOS evidence.
    wfo = ai_walk_forward_backtest(
        df, asset=asset, folds=folds, min_train=min_train, threshold=threshold
    )
    oos_gate = oos_promotion_gate(
        wfo, min_folds=5, min_total_return=policy.min_total_return,
        min_positive_fold_ratio=0.50, max_negative_fold_return=-0.20, require_last_fold_positive=True
    )
    absolute_pass = (
        wfo.get("sharpe", 0.0) >= policy.min_sharpe
        and wfo.get("max_drawdown", -1.0) >= policy.max_drawdown
        and wfo.get("trades", 0) >= policy.min_trades
        and wfo.get("total_return", -1.0) > policy.min_total_return
        and oos_gate.get("passed", False)
    )
    incumbent = (existing or {}).get("walk_forward_gate") or {}
    incumbent_exists = bool(existing and existing.get("status") == "CHAMPION" and incumbent)
    incumbent_pass = True
    incumbent_reason = "NO_INCUMBENT"
    if incumbent_exists:
        sharpe_floor = float(incumbent.get("sharpe", 0.0)) - policy.max_champion_sharpe_drop
        dd_floor = float(incumbent.get("max_drawdown", -1.0)) - policy.max_champion_drawdown_worsening
        return_floor = float(incumbent.get("total_return", 0.0)) - policy.max_champion_return_drop
        incumbent_pass = (
            float(wfo.get("sharpe", 0.0)) >= sharpe_floor
            and float(wfo.get("max_drawdown", -1.0)) >= dd_floor
            and float(wfo.get("total_return", -1.0)) >= return_floor
        )
        incumbent_reason = "WITHIN_CHAMPION_TOLERANCE" if incumbent_pass else "WORSE_THAN_CHAMPION"
    gate = {
        "status": "PASS" if absolute_pass and incumbent_pass else "FAIL",
        "absolute_pass": absolute_pass,
        "incumbent_exists": incumbent_exists,
        "incumbent_comparison": incumbent_reason,
        "sharpe": float(wfo.get("sharpe", 0.0)),
        "max_drawdown": float(wfo.get("max_drawdown", -1.0)),
        "trades": int(wfo.get("trades", 0)),
        "total_return": float(wfo.get("total_return", -1.0)),
        "oos_gate": oos_gate,
    }

    if gate["status"] != "PASS":
        return {
            "status": "CHALLENGER_REJECTED",
            "model_path": str(model_path),
            "promotion": "RETAIN_CHAMPION" if model_path.exists() else "NO_MODEL",
            "wfo": wfo,
            "gate": gate,
            "policy": asdict(policy),
            "feature_drift": compute_feature_drift(df, (existing or {}).get("feature_baseline")),
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = model_path.with_name(model_path.stem + f".candidate-{stamp}" + model_path.suffix)
    try:
        result = train_model(df, str(candidate), min_train=min_train, folds=folds, asset=asset)
        candidate_meta_path = candidate.with_suffix(candidate.suffix + ".meta.json")
        # train_model writes its own integrity metadata; retain it and add the
        # deployment-specific promotion record separately.
        if model_path.parent:
            model_path.parent.mkdir(parents=True, exist_ok=True)
        backup_champion(model_path)
        tmp_model = model_path.with_name(model_path.name + ".promoting")
        tmp_integrity = model_path.with_suffix(model_path.suffix + ".meta.json.promoting")
        shutil.copy2(candidate, tmp_model)
        shutil.copy2(candidate_meta_path, tmp_integrity)
        os.replace(tmp_model, model_path)
        os.replace(tmp_integrity, model_path.with_suffix(model_path.suffix + ".meta.json"))
        try:
            feature_baseline = _feature_baseline(build_features(df))
        except Exception:
            feature_baseline = {}
        champion_meta = {
            "status": "CHAMPION",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "model_sha256": result.get("model_sha256", ""),
            "asset": asset,
            # BUGFIX: result["features"] from train_model() is a *count* (len(FEATURE_COLUMNS)),
            # not the column list. Storing that int here made model_is_fresh()'s
            # `list(meta.get("features") or []) != list(FEATURE_COLUMNS)` check raise
            # TypeError: 'int' object is not iterable on every single freshness check
            # after the first successful promotion (24 is truthy, so `24 or []` is 24,
            # and list(24) is not iterable). That exception was never caught at this call
            # site, so it propagated up through the bot controller loop as a cycle failure;
            # after 3 consecutive failures the bot auto-stops itself (status="STOPPED").
            # In practice this meant every adaptive bot silently stopped shortly after its
            # first promoted champion. Store the actual column list instead.
            "features": list(FEATURE_COLUMNS),
            "feature_baseline": feature_baseline,
            "walk_forward_gate": gate,
            "wfo": wfo,
            "training": result,
            "policy": asdict(policy),
            "learning_mode": "RETRAIN_FROM_SCRATCH_WITH_OOS_PROMOTION",
        }
        _write_json_atomic(_meta_path(model_path), champion_meta)
        if not verify_model_file(model_path, str(result.get("model_sha256", ""))):
            raise RuntimeError("Promoted model failed post-write integrity verification")
        return {
            "status": "CHAMPION_PROMOTED",
            "model_path": str(model_path),
            "model_version": result.get("model_sha256", ""),
            "promotion": "PROMOTED",
            "gate": gate,
            "wfo": wfo,
            "training": result,
            "policy": asdict(policy),
            # Drift of the *outgoing* champion's baseline vs. the data that triggered this
            # retrain -- i.e. how far the market moved underneath the model being replaced.
            "feature_drift": compute_feature_drift(df, (existing or {}).get("feature_baseline")),
        }
    finally:
        for path in (candidate, candidate.with_suffix(candidate.suffix + ".meta.json")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def adaptive_model_status(model_path: str | Path, policy: AdaptiveModelPolicy | None = None) -> dict:
    policy = policy or AdaptiveModelPolicy()
    meta = _read_meta(model_path)
    return {
        "model_path": str(model_path),
        "status": meta.get("status", "MISSING") if meta else "MISSING",
        "fresh": model_is_fresh(model_path, policy),
        "trained_at": meta.get("trained_at") if meta else None,
        "model_version": meta.get("model_sha256", "") if meta else "",
        "walk_forward_gate": meta.get("walk_forward_gate") if meta else None,
        "learning_mode": meta.get("learning_mode") if meta else None,
        "has_feature_baseline": bool(meta.get("feature_baseline")) if meta else False,
        "policy": asdict(policy),
    }
