# Atlas Trading 3.10.30

## Multi-asset execution and root-bug hardening
- Added customer-isolated OANDA credential mapping with encrypted API tokens.
- Added first-class autonomous Major FX and commodity asset classes.
- Added established-universe gates for Major FX and configurable commodity instruments.
- Customer live FX/commodity execution no longer falls back to platform OANDA credentials.
- Added OANDA account identity verification before enabling customer execution.
- Added OANDA instrument unit/price precision and min/max-order validation.
- Added customer OANDA connection endpoint and redesigned Adaptive AI Bot market selector.
- Preserved fail-closed paper/live controls and customer USDT ledger/risk gates.
- Added migration 0025_customer_oanda_accounts.
- Added regression tests for FX/commodity isolation and OANDA precision.

## Important operating boundary
OANDA availability is account/division dependent. Atlas verifies the connected account's actual tradable instrument list before execution; the configured commodity universe is not a guarantee that every OANDA account can trade every instrument.
