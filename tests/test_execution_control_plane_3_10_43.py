from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app/main.py").read_text()
EXEC = (ROOT / "app/execution.py").read_text()
LIVE = (ROOT / "app/live_execution.py").read_text()
MIG = (ROOT / "alembic/versions/0036_execution_control_plane.py").read_text()


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function {name} not found")


def test_deriv_live_customer_route_is_fail_closed():
    block = MAIN[MAIN.index('@app.post("/api/customer/deriv/execute")'):MAIN.index('@app.post("/api/admin/deriv/execute")')]
    assert 'raise HTTPException(409, "Deriv live execution is disabled' in block
    assert 'await broker.buy(' not in block


def test_deriv_live_admin_route_is_fail_closed():
    block = MAIN[MAIN.index('@app.post("/api/admin/deriv/execute")'):MAIN.index('@app.post("/api/admin/arbitrage/binance/live")')]
    assert 'require_role(claims, "OPERATIONS")' in block
    assert 'raise HTTPException(409, "Deriv live execution is disabled' in block
    assert 'await broker.buy(' not in block


def test_live_arbitrage_route_is_fail_closed():
    block = MAIN[MAIN.index('@app.post("/api/admin/arbitrage/binance/live")'):MAIN.index('@app.post("/api/customer/arbitrage/paper")')]
    assert 'require_role(claims, "RISK_OFFICER")' in block
    assert 'raise HTTPException(409, "Binance arbitrage live execution is disabled' in block
    assert 'execute_ioc_leg' not in block


def test_executor_uses_confirmed_fill_not_requested_slice():
    block = _function_source(MAIN, "_executor_controller_loop")
    assert 'actual_filled = float(execution.get("filled")' in block
    assert 'row.executed_quantity = min(float(row.target_quantity or 0), float(row.executed_quantity or 0) + actual_filled)' in block
    assert 'No live fill confirmed; executor did not advance progress' in block


def test_live_execution_gate_is_deny_by_default():
    block = _function_source(LIVE, "assert_live_system_enabled")
    assert 'if state.kill_switch or not state.live_enabled:' in block
    assert 'if not settings.live_trading_enabled or settings.paper_trading or settings.broker_sandbox:' in block
    assert 'if not profile or str(profile.status).upper() != "ACTIVE":' in block
    assert 'if not plan or not bool(plan.active) or not bool(plan.live_trading):' in block
    assert 'enable_withdrawals' in block
    assert 'universal_transfer' in block


def test_order_command_and_execution_lease_migration_exist():
    assert 'CREATE TABLE' not in MIG  # Alembic API used instead of raw SQL.
    assert 'order_commands' in MIG
    assert 'live_execution_lease' in MIG
    assert 'uq_order_command_idempotency' in MIG
    assert 'fencing_token' in MIG


def test_final_live_path_verifies_lease_before_exchange_call():
    idx = EXEC.index('await _verify_live_lease(lease_token)')
    broker_idx = EXEC.index('broker.market_order', idx)
    assert idx < broker_idx


def test_final_gate_releases_customer_reserve_when_blocked():
    block = EXEC[EXEC.index('except (LiveExecutionBlocked, RiskBlocked) as exc:'):EXEC.index('except Exception as exc:', EXEC.index('except (LiveExecutionBlocked, RiskBlocked) as exc:'))]
    assert 'reserved_cash > 0' in block
    assert 'await _release_unneeded_order_reserve(db, t)' in block


def test_protective_stop_verification_checks_exchange_response_and_open_orders():
    assert '([order] + (open_orders or []))' in EXEC
    assert 'o.get("stopLoss")' in EXEC
    assert 'broker.fetch_open_orders' in EXEC
    assert 'PROTECTIVE_STOP_MISSING' in EXEC


def test_emergency_stop_sweeps_customer_binance_accounts():
    block = EXEC[EXEC.index('async def emergency_stop'):]
    assert 'CustomerBinanceAccount.status == "VERIFIED"' in block
    assert 'build_customer_binance_broker' in block
    assert 'broker.cancel_all_orders' in block
    assert 'EMERGENCY_CANCEL_FAILED:CUSTOMER' in block


def test_readyz_requires_execution_fencing_not_single_worker_assumption():
    block = MAIN[MAIN.index('@app.get("/readyz")'):MAIN.index('@app.get("/metrics")')]
    assert 'checks["execution_fencing"]' in block
    assert 'checks["single_worker"] = True' in block


def test_production_live_payouts_require_external_signer():
    startup = MAIN[MAIN.index('@app.on_event("startup")'):MAIN.index('@app.get("/healthz")')]
    assert 'payout_live_enabled and not settings.external_custody_signer_required' in startup
    assert 'EXTERNAL_CUSTODY_SIGNER_REQUIRED=true is mandatory' in startup
