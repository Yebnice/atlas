#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:=postgresql+asyncpg://trader:${POSTGRES_PASSWORD:-trader_test}@127.0.0.1:5432/trading}"
export DATABASE_URL
export ENVIRONMENT=development
export PAPER_TRADING=true
export LIVE_TRADING_ENABLED=false
export BROKER_SANDBOX=true
export BACKGROUND_RECONCILIATION_ENABLED=false

python -m pytest -q tests/test_execution_control_plane_3_10_43.py tests/test_live_money_static_3_10_38.py tests/test_adaptive_strategy_router_3_10_41.py tests/test_trade_learning_3_10_42.py tests/test_research_validation.py
python -m alembic upgrade head
python -m alembic check

if [[ "${DATABASE_URL}" == postgresql* ]]; then
  export ATLAS_POSTGRES_URL="${DATABASE_URL}"
  python -m pytest -q tests/test_postgres_concurrency_3_10_39.py
fi
python -m bandit -r app -lll -f json -o bandit-report.json
python -m pip_audit -r requirements.txt --strict -f json -o pip-audit-report.json
