from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _src(name: str) -> str:
    return (APP / name).read_text()


def test_reserve_trading_uses_stable_reference_not_timestamp():
    funds = _src("customer_funds.py")
    block = funds.split("async def reserve_trading", 1)[1].split("async def release_trading", 1)[0]
    assert "reference_id: str" in block
    assert "timestamp()" not in block
    assert 'idem = f"reserve:{reference_id}"' in block
    # duplicate check must come before the balance mutation
    assert block.index("idempotency_key == idem") < block.index("ledger.available =")


def test_release_trading_checks_idempotency_before_mutating_balances():
    block = _src("customer_funds.py").split("async def release_trading", 1)[1].split("async def ", 1)[0]
    assert block.index("idempotency_key == idem") < block.index("ledger.trading_reserved =")


def test_execution_callers_pass_stable_reserve_references():
    ex = _src("execution.py")
    assert 'reference_id=f"trade:{trade.id}:flip:' in ex
    assert 'reference_id=f"trade:{trade_id}:open-reserve"' in ex


def test_halted_account_can_still_place_capped_reduce_only_exit():
    ex = _src("execution.py")
    # early gate in execute_signal defers HALTED accounts to risk_gate
    assert 'account.status not in {"ACTIVE", "HALTED"}' in ex
    # risk_gate is the authority: HALTED only passes a capped reduce-only order
    assert 'account.status == "HALTED" and account_reduce_only' in ex
    assert "already_halted_exit" in ex


def test_oanda_bar_count_scales_with_timeframe():
    main = _src("main.py")
    assert "req.days * 24" not in main
    assert '"1m": 1440' in main and "req.days * bars_per_day" in main


def test_daily_research_distinguishes_missing_lock_backend():
    assert "SKIPPED_NO_DISTRIBUTED_LOCK_BACKEND" in _src("daily_research.py")
    assert "RESEARCH_DAILY_MISCONFIGURED" in _src("main.py")


def test_production_requires_redis_when_adaptive_controller_enabled():
    main = _src("main.py")
    assert "settings.adaptive_bot_controller_enabled and not settings.redis_url" in main
