from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
EXEC = (ROOT / "app/execution.py").read_text(encoding="utf-8")


def block_between(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end, source.index(start))]


def test_customer_deriv_disabled_route_still_authenticates_customer():
    block = block_between(
        MAIN,
        '@app.post("/api/customer/deriv/execute")',
        '@app.post("/api/admin/deriv/execute")',
    )
    assert "await customer_claims(authorization, require_aal2=True)" in block
    assert "raise HTTPException(409, \"Deriv live execution is disabled" in block
    assert "await broker.buy(" not in block


def test_strategy_builder_keeps_auth_via_candidate_creation_path():
    block = block_between(
        MAIN,
        '@app.post("/api/customer/strategy-builder")',
        '@app.post("/api/customer/strategy-builder/{draft_id}/promote")',
    )
    assert "await create_strategy_candidate(lab_req, authorization)" in block
    candidate = block_between(
        MAIN,
        '@app.post("/api/customer/strategy-lab/candidates")',
        '@app.post("/api/customer/strategy-lab/candidates/{candidate_id}/validate")',
    )
    assert "await get_customer(authorization,db,require_aal2=True)" in candidate


def test_platform_reconciliation_isolated_from_customer_positions():
    sync_fn = EXEC[EXEC.index("async def sync_live_account"):EXEC.index("async def reconcile", EXEC.index("async def sync_live_account"))]
    assert "Position.customer_id.is_(None)" in sync_fn
    assert "or_(Position.exchange == exchange, Position.exchange == \"\")" in sync_fn
    assert "pos.exchange = exchange" in sync_fn


def test_reservation_failure_terminalizes_precreated_trade():
    marker = "except ValueError as exc:\n                        # The trade row was created before the ledger reservation"
    assert marker in EXEC
    block = EXEC[EXEC.index(marker):EXEC.index("raise RiskBlocked(str(exc))", EXEC.index(marker)) + len("raise RiskBlocked(str(exc))")]
    assert 'reject_trade.status = "REJECTED"' in block
    assert "reject_trade.error = str(exc)[:2000]" in block
    assert "await reject_db.commit()" in block


def test_duplicate_trade_returns_fill_for_executor_recovery():
    duplicate = EXEC[EXEC.index('if not created:'):EXEC.index('reserved_cash = 0.0', EXEC.index('if not created:'))]
    assert '"filled": float(existing.filled_quantity or 0.0)' in duplicate
    assert '"remaining_quantity": float(existing.remaining_quantity or 0.0)' in duplicate
    assert '"average_fill_price": float(existing.average_fill_price or 0.0)' in duplicate


def test_forex_demo_enable_does_not_use_closed_broker():
    block = block_between(
        MAIN,
        '@app.post("/api/forex/demo/enable")',
        '@app.post("/api/forex/demo/execute")',
    )
    assert "account_snapshot = await asyncio.to_thread(broker.account)" in block
    assert 'finally:\n        broker.close()' in block
    # The only broker.account call must occur before the close in this route.
    assert block.index("account_snapshot = await asyncio.to_thread(broker.account)") < block.index("broker.close()")


def test_fx_research_endpoints_are_authenticated():
    tca = block_between(
        MAIN,
        '@app.post("/api/research/fx-execution-tca")',
        '@app.post("/api/research/fx-execution-route")',
    )
    route = MAIN[MAIN.index('@app.post("/api/research/fx-execution-route")'):]
    assert "claims = await auth(x_admin_token, authorization)" in tca
    assert 'await require_role(claims, "READ_ONLY")' in tca
    assert "claims = await auth(x_admin_token, authorization)" in route
    assert 'await require_role(claims, "READ_ONLY")' in route


def test_platform_reconcile_does_not_filter_customer_rows_as_platform_rows():
    # Guard against a regression to the pre-fix symbol-only Position lookup.
    sync_fn = EXEC[EXEC.index("async def sync_live_account"):EXEC.index("async def reconcile", EXEC.index("async def sync_live_account"))]
    bad = "select(Position).where(Position.symbol == symbol).with_for_update()"
    assert bad not in sync_fn


def test_execution_id_scope_separates_autonomous_bots_and_executors():
    src = (ROOT / "app" / "execution.py").read_text()
    assert 'signal.get("bot_id")' in src
    assert 'signal.get("executor_id")' in src
    assert 'signal.get("request_id")' in src


def test_trade_persists_exact_cash_reserve_and_slippage_buffer():
    dbsrc = (ROOT / "app" / "db.py").read_text()
    src = (ROOT / "app" / "execution.py").read_text()
    assert 'reserved_cash: Mapped[float]' in dbsrc
    assert 'reserve_buffer = max(0.0, float(settings.max_slippage_bps or 0.0)) / 10_000.0' in src
    assert 'reserved_trade.reserved_cash = reserved_cash' in src


def test_partial_orders_do_not_release_reserve_until_terminal_state():
    src = (ROOT / "app" / "execution.py").read_text()
    live_block = src[src.index('async def execute_signal'):src.index('async def _apply_broker_snapshot')]
    assert 'if t.status in {"FILLED", "CANCELED", "REJECTED"}:' in live_block


def test_dca_grid_start_is_fail_closed_when_no_controller_exists():
    src = (ROOT / "app" / "main.py").read_text()
    assert 'DCA execution controller is not enabled; this configuration is paper-only' in src
    assert 'Grid execution controller is not enabled; this configuration is paper-only' in src


def test_alert_endpoint_does_not_claim_automatic_evaluation():
    src = (ROOT / "app" / "main.py").read_text()
    assert 'Automatic alert evaluation is not currently enabled' in src


def test_noncrypto_customer_automation_is_paper_only():
    src = (ROOT / "app" / "main.py").read_text()
    assert 'or req.asset in {"forex", "commodity"}' in src
    assert 'OANDA customer automation is demo/paper-only; live Forex and commodities are disabled' in src


def test_alerts_are_not_advertised_as_active_without_an_evaluator():
    src = (ROOT / "app" / "main.py").read_text()
    assert 'status="CONFIGURED"' in src


def test_customer_live_reconciliation_is_not_tied_to_platform_default_exchange():
    src = (ROOT / "app" / "execution.py").read_text()
    main = (ROOT / "app" / "main.py").read_text()
    assert 'async def reconcile_customer_live_orders' in src
    assert 'Customer live reconciliation is only enabled for Binance isolation' in src
    assert 'reconcile_customer_live_orders(customer_exchanges)' in main


def test_reconciliation_updates_order_command_state():
    src = (ROOT / "app" / "execution.py").read_text()
    assert 'command_row.status = "RECONCILED"' in src
    assert 'select(OrderCommand).where(OrderCommand.trade_id == t.id).with_for_update()' in src


def test_unresolved_customer_orders_open_incidents():
    src = (ROOT / "app" / "execution.py").read_text()
    assert 'CUSTOMER_ORDER_UNRESOLVED:{trade_id}' in src
    assert 'category="RECONCILIATION"' in src


def test_live_customer_activation_preflights_final_authority():
    src = (ROOT / "app" / "main.py").read_text()
    assert 'await assert_live_system_enabled(' in src
    assert 'Live bot cannot be armed' in src
    assert 'Live bot cannot be started' in src
    assert 'Live executor cannot be armed' in src
    assert 'Live executor cannot be started' in src


def test_paper_only_product_endpoints_do_not_claim_live_authority():
    src = (ROOT / "app" / "main.py").read_text()
    assert 'A Smart Trade live execution controller is not enabled.' in src
    assert 'Automatic DCA execution is not enabled.' in src
    assert 'Automatic Grid live execution is not enabled.' in src
    assert '"execution_authority":bool(row.mode == "LIVE" and row.live_approved)' in src


def test_current_readme_does_not_retain_stale_release_heading():
    readme = (ROOT / "README.md").read_text()
    assert '# Atlas Trading 3.10.35' not in readme
    assert '## Current release: 3.10.45' in readme
