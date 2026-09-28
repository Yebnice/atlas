"""Regression tests for experiment tracking, drift monitoring and the strategy-builder dead-end fix."""
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

try:  # lightgbm may be absent in minimal CI images; the drift math doesn't need it.
    import lightgbm  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("lightgbm")
    stub.LGBMClassifier = type("LGBMClassifier", (), {})
    sys.modules["lightgbm"] = stub


def _df(seed=0, shift_last=None, n=1500):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    log_ret = rng.normal(0, 0.004, n)
    spread = rng.uniform(0.001, 0.006, n)
    if shift_last:
        log_ret[-shift_last:] = rng.normal(0, 0.014, shift_last)
        spread[-shift_last:] = rng.uniform(0.004, 0.02, shift_last)
    close = 100 * np.exp(np.cumsum(log_ret))
    return pd.DataFrame({"open": close, "high": close * (1 + spread), "low": close * (1 - spread),
                         "close": close, "volume": rng.uniform(100, 200, n)}, index=idx)


def test_champion_features_metadata_is_a_list_not_a_count():
    """Regression: features was stored as len(FEATURE_COLUMNS) (an int) which made
    model_is_fresh() raise TypeError on every check after the first promotion."""
    src = (ROOT / "app" / "adaptive_bot.py").read_text()
    assert '"features": list(FEATURE_COLUMNS)' in src
    assert 'result.get("features")' not in src


def test_model_is_fresh_handles_fresh_champion_and_does_not_crash(tmp_path):
    from app.adaptive_bot import model_is_fresh, AdaptiveModelPolicy
    from app.trading_core import FEATURE_COLUMNS
    model = tmp_path / "m.joblib"
    meta = {"status": "CHAMPION", "trained_at": datetime.now(timezone.utc).isoformat(),
            "features": list(FEATURE_COLUMNS)}
    (tmp_path / "m.joblib.adaptive.json").write_text(json.dumps(meta))
    assert model_is_fresh(model, AdaptiveModelPolicy()) is True


def test_drift_no_baseline_and_thin_data_are_handled():
    from app.adaptive_bot import compute_feature_drift, _feature_baseline
    from app.trading_core import build_features
    assert compute_feature_drift(_df(), None)["status"] == "NO_BASELINE"
    baseline = _feature_baseline(build_features(_df()))
    assert compute_feature_drift(_df().tail(50), baseline)["status"] == "INSUFFICIENT_DATA"


def test_drift_low_false_alarm_rate_without_drift():
    from app.adaptive_bot import compute_feature_drift, _feature_baseline
    from app.trading_core import build_features
    alerts = 0
    for seed in range(8):
        df = _df(seed)
        d = compute_feature_drift(df, _feature_baseline(build_features(df)))
        alerts += d["status"] == "ALERT"
    assert alerts == 0


def test_drift_detects_volatility_regime_shift():
    from app.adaptive_bot import compute_feature_drift, _feature_baseline
    from app.trading_core import build_features
    for seed in range(4):
        baseline = _feature_baseline(build_features(_df(seed)))
        d = compute_feature_drift(_df(seed, shift_last=250), baseline)
        assert d["status"] == "ALERT"
        assert d["mean_psi"] > 0.25


def test_drift_monitored_features_exclude_long_window_and_calendar_features():
    from app.adaptive_bot import DRIFT_MONITORED_FEATURES
    for col in ("trend_200", "trend_50", "vol_72", "drawdown_72", "hour_sin", "hour_cos", "dow"):
        assert col not in DRIFT_MONITORED_FEATURES


def test_run_drift_comparison():
    from app.daily_research import compute_run_drift
    assert compute_run_drift(None, {"regime": "TREND_UP"})["status"] == "FIRST_RUN"
    prev = {"regime": "TREND_UP", "top_strategy": "trend", "sharpe": 1.2, "max_drawdown": -0.10, "total_return": 0.2}
    stable = compute_run_drift(prev, dict(prev))
    assert stable["status"] == "STABLE" and stable["flags"] == []
    cur = {"regime": "RANGE_OR_LOW_TREND", "top_strategy": "mean_reversion", "sharpe": 0.3, "max_drawdown": -0.25, "total_return": -0.05}
    flagged = compute_run_drift(prev, cur)
    assert flagged["status"] == "DRIFT_FLAGGED"
    assert set(flagged["flags"]) == {"REGIME_CHANGED", "TOP_STRATEGY_CHANGED", "SHARPE_DEGRADED", "DRAWDOWN_WORSENED"}


def test_summarize_research_tolerates_empty_and_nan():
    from app.daily_research import summarize_research
    assert summarize_research({})["top_strategy"] == ""
    out = summarize_research({"regime": {"regime": "TREND_UP"}, "research_order": ["trend"],
                              "strategies": [{"strategy": "trend", "sharpe": float("nan"), "max_drawdown": -0.1, "total_return": 0.3}]})
    assert out["sharpe"] == 0.0 and out["total_return"] == 0.3


def test_strategy_builder_is_no_longer_a_dead_end():
    src = (ROOT / "app" / "main.py").read_text()
    start = src.index('@app.post("/api/customer/strategy-builder")')
    end = src.index('@app.get("/api/customer/strategy-builder")')
    chunk = src[start:end]
    assert "create_strategy_candidate(" in chunk          # feeds the validatable lifecycle
    assert "StrategyDraft(" not in chunk                  # no new orphan rows
    assert '"/api/customer/strategy-builder/{draft_id}/promote"' in chunk  # legacy drafts rescued


def test_validation_attempts_are_persisted_not_overwritten():
    src = (ROOT / "app" / "main.py").read_text()
    assert "StrategyCandidateRun(candidate_id=candidate_id" in src
    assert '"/api/customer/strategy-lab/candidates/{candidate_id}/runs"' in src


def test_model_experiments_recorded_at_both_call_sites_and_migration_exists():
    src = (ROOT / "app" / "main.py").read_text()
    assert src.count("_record_model_experiment(") >= 3  # def + locked wrapper + customer bot start
    mig = (ROOT / "alembic" / "versions" / "0031_experiment_tracking_and_drift.py").read_text()
    for table in ("strategy_candidate_runs", "model_experiments", "research_runs"):
        assert table in mig
    assert 'down_revision = "0030_financial_precision_and_wallet_recovery"' in mig


def test_legacy_champion_with_int_features_is_stale_not_a_crash(tmp_path):
    """Champions written by the old code have features=24 on disk; they must self-heal."""
    from app.adaptive_bot import model_is_fresh, AdaptiveModelPolicy
    from app.trading_core import FEATURE_COLUMNS
    meta = {"status": "CHAMPION", "trained_at": datetime.now(timezone.utc).isoformat(),
            "features": len(FEATURE_COLUMNS)}
    (tmp_path / "m.joblib.adaptive.json").write_text(json.dumps(meta))
    assert model_is_fresh(tmp_path / "m.joblib", AdaptiveModelPolicy()) is False
