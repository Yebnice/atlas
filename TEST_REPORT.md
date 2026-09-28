# Test Report — 3.2.0

## Strategy upgrade validation

| Check | Result | Notes |
|---|---|---|
| Python `compileall` | PASS | Application, tests and scripts compile successfully. |
| Full pytest suite | PASS | **20 passed, 1 skipped**. |
| Strategy engine tests | PASS | 3 new regression tests cover signal bounds, protective levels and finite/lagged backtest behavior. |
| Strategy live-market backtest | NOT RUN | No external market-data fetch was performed during packaging. Run with the target exchange data before relying on results. |
| Broker/payout E2E | NOT VERIFIED | Requires configured staging/testnet credentials and provider dependencies. |

## Validation boundary

The multi-strategy engine is implemented and unit-tested, but its profitability is **not** established by these tests. Out-of-sample performance must be measured on the target asset/timeframe with realistic fees, slippage, funding/carry, spread and execution assumptions.

## Existing release validation



| Check | Result | Notes |
|---|---|---|
| Python `compileall` | PASS | `app`, `tests`, and `scripts` compile successfully |
| Pytest regression/static suite | PASS | 17 passed, 1 skipped |
| API integration tests | SKIPPED | Requires `aiosqlite`; package installation was unavailable because outbound network access is disabled |
| Bandit local run | NOT AVAILABLE | `bandit` is not installed in the execution environment |
| pip-audit local run | NOT AVAILABLE | `pip-audit` is not installed in the execution environment |

## Important validation boundary

The code changes were applied to the supplied source archive and validated with the available local test suite. A full live broker, payout-provider, PostgreSQL, browser, and FastAPI/SQLite integration test was not possible in this environment because the missing `aiosqlite` package could not be downloaded.

Before production deployment, run the repository CI workflow, including dependency installation, `bandit`, `pip-audit`, the API integration suite, a staging PostgreSQL migration, and provider-specific testnet/practice acceptance tests.

## Regression tests added

- Withdrawal creation persists executable destination fields and the proposal digest.
- Release requires a stored proposal digest and validates it against the canonical payload.
- Dashboard/API withdrawal lifecycle states stay aligned.
- Dashboard untrusted display fields are escaped.
- Model artifact path construction sanitizes user-controlled components.


## 3.4.1 admin authenticator security
- `pytest -q`: 46 passed, 1 skipped.
- Production admin API path requires Supabase Auth AAL2 + verified Google Authenticator TOTP.
- Static admin token cannot bypass TOTP in production.
