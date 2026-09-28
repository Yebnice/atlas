#!/usr/bin/env bash
set -euo pipefail

# Run this from Cloud Shell/Compute against a disposable/staging PostgreSQL database.
# It does not enable live trading.
: "${DATABASE_URL:?Set DATABASE_URL to a PostgreSQL database}"
case "$DATABASE_URL" in
  postgresql*) ;;
  *) echo "DATABASE_URL must use PostgreSQL for this verification" >&2; exit 2;;
esac

export ENVIRONMENT=development
export PAPER_TRADING=true
export LIVE_TRADING_ENABLED=false
export BROKER_SANDBOX=true
export BACKGROUND_RECONCILIATION_ENABLED=false
export ATLAS_POSTGRES_URL="$DATABASE_URL"

python -m alembic upgrade head
python -m alembic check
DATABASE_URL="$DATABASE_URL" python deploy/validate-postgres-constraints.py
python -m pytest -q tests/test_postgres_concurrency_3_10_39.py
python -m pytest -q tests/test_live_money_hardening_3_10_38.py tests/test_live_money_static_3_10_38.py tests/test_execution_control_plane_3_10_43.py tests/test_research_validation.py tests/test_adaptive_strategy_router_3_10_41.py tests/test_trade_learning_3_10_42.py

if command -v bandit >/dev/null 2>&1; then
  python -m bandit -r app -lll
else
  echo "Bandit not installed; install requirements-dev.txt before production certification." >&2
fi
if command -v pip-audit >/dev/null 2>&1; then
  python -m pip_audit -r requirements.txt --strict
else
  echo "pip-audit not installed; install requirements-dev.txt before production certification." >&2
fi

echo
echo "POSTGRES RUNTIME VERIFICATION COMPLETED. Live trading remains disabled by this script."
