# Atlas Trading 3.10.30 — Multi-Asset Execution & Root-Bug Audit

## Scope
Fresh extraction of Atlas 3.10.29 followed by implementation and adversarial validation of customer-isolated OANDA execution, Major FX/commodity autonomous trading, OANDA order precision/limits, UI asset selection, migration integrity, route uniqueness, runtime compilation, and regression tests.

## Confirmed root issues fixed
1. Customer live FX/commodity execution could use platform OANDA credentials. Fixed: customer live non-crypto orders require a verified `CustomerOandaAccount` and never fall back to platform credentials.
2. FX/commodity were not first-class autonomous asset classes. Fixed: `asset=forex|commodity`, OANDA market data, model paths, controller state, risk/execution routing, and UI markets.
3. OANDA order quantities were not validated against account-specific minimum/maximum units or precision. Fixed with instrument metadata validation before live execution.
4. OANDA stop-loss/take-profit prices were formatted to a fixed 10 decimals. OANDA can reject price precision above the instrument's allowed display precision. Fixed by instrument-specific price normalization.
5. Crypto liquidity checks were being conceptually applied to non-crypto data. Fixed: established-universe/24h-volume gate is crypto-specific; FX/commodity use explicit instrument allowlists and broker-side tradeability validation.
6. Customer autonomous FX/commodity market data could fall back to platform OANDA data. Fixed: customer controller loads candles from the verified customer OANDA account.
7. Customer bot UI hardcoded Binance even when selecting FX. Fixed: exchange automatically switches to OANDA for FX/commodities.

## Multi-asset capability
- Major FX universe: EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD, NZD/USD.
- Commodity universe: XAU/USD, XAG/USD, WTI, Brent, Natural Gas using configurable OANDA instrument names.
- OANDA account availability is authoritative: OANDA documents that tradeable instruments depend on the account's regulatory division. Atlas therefore verifies the connected account and instrument before execution.
- Customer OANDA API tokens are stored through the existing application-layer encrypted DB field.
- Customer OANDA account identity is verified against the account returned by OANDA before status becomes VERIFIED.

## External fact-check
OANDA's current developer documentation confirms:
- v20 supports market data and automated order placement.
- tradeable instruments are account/division dependent.
- market prices expose tradeability and bid/ask liquidity.
- instruments expose maximum order units, margin rate, and precision-related constraints.
- OANDA warns that excessive price precision can cause order rejection.

## Verification
- Non-billing regression: 212 passed, 1 skipped.
- Python compileall: PASS.
- API routes: 110 total / 110 unique / 0 duplicates.
- Alembic revisions: 25 / single head `0025_customer_oanda_accounts`.
- Customer JS `node --check`: PASS.
- Android version: 3.10.30 / versionCode 1030.
- Billing test remains skipped in this audit runtime because `aiosqlite` is unavailable; it remains declared in the application dependencies.

## Live-trading boundary
Atlas can execute Major FX and supported commodity instruments through a customer's verified OANDA account when the account actually permits the instrument and production live-trading gates are enabled. The Atlas USDT wallet is not itself an OANDA funding account; OANDA execution uses the connected OANDA account's own broker capital/margin. Paper mode remains the default.
