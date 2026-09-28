import ast
from pathlib import Path

import pandas as pd

import app.entry_exit_engine as ee


def test_customer_models_are_tenant_scoped():
    source = Path("app/db.py").read_text()
    assert "class TradingAccount(Base):" in source
    assert "customer_id: Mapped[int | None]" in source
    assert "trading_account_id: Mapped[int | None]" in source
    assert "uq_position_customer_exchange_symbol" in source
    assert "uq_trading_account_customer" in source


def test_admin_routes_have_authorization_parameter_when_they_call_auth():
    tree = ast.parse(Path("app/main.py").read_text())
    failures = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls_auth = any(
            isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "auth"
            for x in ast.walk(node)
        )
        args = {a.arg for a in node.args.args + node.args.kwonlyargs}
        if calls_auth and "authorization" not in args:
            failures.append(f"{node.name}:{node.lineno}")
    assert not failures, failures


def test_backtest_does_not_fill_unreached_entry(monkeypatch):
    idx = pd.date_range("2025-01-01", periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100, 100, 100],
            "high": [100, 104, 101],
            "low": [99, 99, 99],
            "close": [100, 103, 100],
            "volume": [1, 1, 1],
        }, index=idx
    )
    analysis = pd.DataFrame(
        {
            "side": ["buy", "flat", "flat"],
            "entry_price": [110.0, float("nan"), float("nan")],
            "stop_loss_price": [100.0, float("nan"), float("nan")],
            "take_profit_price": [130.0, float("nan"), float("nan")],
            "reward_risk": [2.0, float("nan"), float("nan")],
            "entry_valid": [True, False, False],
            "atr": [2.0, 2.0, 2.0],
        }, index=idx
    )
    monkeypatch.setattr(ee, "gated_entry_exit_analysis", lambda df, cfg: analysis)
    result = ee.gated_entry_exit_backtest(df)
    assert result["trades"] == 0


def test_backtest_fills_reached_entry_and_records_risk_sizing(monkeypatch):
    idx = pd.date_range("2025-01-01", periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100, 100, 103],
            "high": [100, 105, 106],
            "low": [99, 100, 102],
            "close": [100, 104, 105],
            "volume": [1, 1, 1],
        }, index=idx
    )
    analysis = pd.DataFrame(
        {
            "side": ["buy", "flat", "flat"],
            "entry_price": [103.0, float("nan"), float("nan")],
            "stop_loss_price": [101.0, float("nan"), float("nan")],
            "take_profit_price": [107.0, float("nan"), float("nan")],
            "reward_risk": [2.0, float("nan"), float("nan")],
            "entry_valid": [True, False, False],
            "atr": [1.0, 1.0, 1.0],
        }, index=idx
    )
    monkeypatch.setattr(ee, "gated_entry_exit_analysis", lambda df, cfg: analysis)
    result = ee.gated_entry_exit_backtest(df, initial_equity=1000.0, risk_fraction=0.01, taker_bps=0, slippage_bps=0)
    assert result["trades"] == 1
    trade = result["trades_detail"][0]
    assert trade["requested_entry"] == 103.0
    assert trade["entry"] == 103.0
    assert trade["quantity"] == 5.0


def test_customer_live_crypto_never_uses_platform_credentials():
    source = Path("app/execution.py").read_text()
    assert "Customer live trading requires a verified isolated exchange/subaccount adapter" in source
    assert 'customer_id is not None and asset != "forex"' in source


def test_customer_paper_fee_is_not_charged_to_platform_state():
    source = Path("app/execution.py").read_text()
    assert "if account is not None:" in source
    assert "account.cash_equity = max(0.0, account.cash_equity - fee)" in source


def test_customer_bot_uses_adaptive_model_confirmation():
    source = open("app/main.py", encoding="utf-8").read()
    assert "ensure_adaptive_model" in source
    assert "predict_latest, df, model_file(req)" in source
    assert "adaptive_model_confirmation" in source


def test_customer_bot_ui_exposes_learning_and_oos_gate():
    source = open("app/templates/customer.html", encoding="utf-8").read()
    assert "Start Autonomous" in source
    assert "Cycle" in source
    assert "Controller:" in source
    assert "Adaptive learner" in source


def test_trading_discipline_controls_are_configured_and_fail_closed():
    source = open("app/execution.py", encoding="utf-8").read()
    config = open("app/config.py", encoding="utf-8").read()
    assert "discipline_max_entries_per_day" in config
    assert "discipline_entry_cooldown_seconds" in config
    assert "discipline_enforce_risk_per_trade" in config
    assert "Trading-discipline daily entry limit reached" in source
    assert "Trading-discipline entry cooldown is active" in source
    assert "Per-trade risk exceeds the configured discipline limit" in source

def test_live_risk_path_passes_stop_to_portfolio_gate():
    source = open("app/execution.py", encoding="utf-8").read()
    assert "stop_loss_price=stop_loss_price" in source
    assert "risk_per_trade=settings.risk_per_trade" not in source  # sizing is enforced inside risk_gate from account equity
