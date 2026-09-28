
## Current release: 3.10.44

This release is a production-safety hardening candidate. Live trading and live payouts remain fail-closed until the external runtime verification gates are completed.
# Atlas Trading — customer USDT trading platform

This release turns the supplied `trader.py` prototype into a deployable trading platform foundation while preserving its central pipeline: market data → deterministic features → triple-barrier labels → purged walk-forward validation → LightGBM → cost-aware backtest → paper execution.


## Multi-strategy research engine (3.2)

The console now includes an explainable ensemble rather than relying on one AI model. It combines **trend following, time-series momentum, breakout confirmation, and regime-filtered mean reversion**, then applies volatility-targeted position sizing and ATR-based protective levels. The engine is available through `POST /api/strategy/signal` and `POST /api/strategy/backtest`.

The design is deliberately evidence-driven rather than marketed as a guaranteed “best strategy.” Long-run research has documented time-series momentum/trend-following across multiple asset classes and periods, while risk-parity/volatility-scaling research emphasizes controlling risk contributions and reducing exposure as volatility rises. citeturn0search0turn0search1turn0search13

The backtest shifts signals one bar before applying returns and charges transaction costs, reducing common look-ahead and friction omissions. Results remain research diagnostics and must be validated out of sample, with realistic venue-specific fees/slippage, before any live deployment.

## What is materially upgraded

The system now includes persistent trade/order lifecycle state, deterministic idempotency, portfolio-aware risk gating, position and P&L state, account reconciliation, CCXT exchange integration, precision checks, sandbox-first controls, attached protective-stop checks, fail-closed emergency stop behavior, structured audit events, Prometheus metrics, production readiness checks, an authenticated dashboard, and Docker/CI scaffolding.

## Run locally

```bash
cp .env.example .env
python -m venv .venv
# activate the virtualenv
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

In development, the dashboard can operate without an admin token. Outside development, set a strong `ADMIN_TOKEN` and `SECRET_KEY`.

## Paper-first operating mode

The default configuration is deliberately safe:

```text
PAPER_TRADING=true
LIVE_TRADING_ENABLED=false
BROKER_SANDBOX=true
```

Paper orders are recorded in the same persistent trade and position ledger used by the execution path, with modeled taker fees and slippage.

## AI workflow

Train:

```text
POST /api/train
```

Run an AI walk-forward backtest:

```text
POST /api/backtest
```

Get the latest signal:

```text
POST /api/signal
```

Execute one paper step:

```text
POST /api/paper/step
```

## Live trading gate

Live execution is blocked unless configuration explicitly allows it, the broker is non-sandbox, credentials exist, the process is single-worker, the operator supplies the live confirmation text, the exchange supports the required attached stop capability, and the kill switch is clear.

The live order path never trusts a caller-supplied price for risk sizing. It fetches the current broker quote and then validates quantity precision and limits before submission.

A transport timeout on order placement becomes `UNKNOWN`. Operators must reconcile broker state before any retry.

## CCXT version

The bundled requirements pin CCXT to `4.5.84`, verified against the CCXT GitHub releases page on September 24, 2026. https://github.com/ccxt/ccxt/releases

## Production database

SQLite is useful for local development. Production deployments should use PostgreSQL, backups, controlled migrations and managed secrets. The repository includes Alembic scaffolding and a migration helper for the shipped v2 SQLite schema.

## Security

### Admin MFA
Administrator access is protected separately from customer access. In production, admin APIs require a Supabase Auth access token belonging to an allow-listed administrator **and AAL2 verified with Google Authenticator/TOTP**. The legacy `ADMIN_TOKEN` is retained only for development compatibility; it cannot bypass admin TOTP in production. Configure `ADMIN_TOTP_REQUIRED=true` and `ADMIN_SUPABASE_USER_IDS` with the authorized Supabase Auth user UUIDs. Admin TOTP secrets are managed by Supabase Auth and are not stored in the Atlas trading database.

Admin authentication flow: **Supabase email/password → Google Authenticator 6-digit code → AAL2 admin session → sensitive admin action**. Withdrawal approval and payout release retain their separate administrator/release credentials and dual-approval controls.

### Customer MFA
Customer authentication uses Supabase Auth. Version 3.4.0 builds on native TOTP MFA compatible with Google Authenticator. Account access is gated on AAL2 after TOTP enrollment, and USDT withdrawals require both AAL2 TOTP and the existing fresh email/SMS step-up token. TOTP secrets are managed by Supabase Auth rather than stored in the trading database.


Do not commit `.env` files or exchange secrets. Exchange keys should have trading permission only, with withdrawals disabled and IP restrictions enabled where the venue supports them. Put HTTPS and an authenticated reverse proxy in front of the service before exposing it publicly.

## Testnet

Use the exchange's testnet/sandbox credentials, not mainnet credentials. CCXT requires sandbox mode to be selected immediately after exchange creation and before any other exchange call. Sandbox keys are not interchangeable with production keys.

## Important scope boundary

This application can be engineered for production reliability, but software hardening does not make a trading strategy profitable or guarantee against market losses. The AI backtest is a research diagnostic, not a promise of future returns.

## Operational references

- `REVIEW.md` — root bugs and the exact fixes applied.
- `LIVE_GATE.md` — pre-mainnet verification checklist.
- `RUNBOOK.md` — incident, timeout, restart and model-response procedures.
- `SECURITY.md` — security model and key handling.
- `ARCHITECTURE.md` — system and CCXT integration design.
- `scripts/smoke.py` — post-deployment HTTP smoke check.
- `scripts/migrate_v2_sqlite.py` — best-effort v2 SQLite migration helper; back up first.


## Admin withdrawal approvals
The console includes an admin withdrawal queue with pending/partial/approved/rejected states, masked destinations, risk score/flags, immutable audit events, amount limits, and configurable dual approval. In production, set `WITHDRAWAL_APPROVER_TOKENS` to distinct `admin-id:secret` pairs and require two different approvers. The approval service deliberately does **not** move funds; it marks a request `APPROVED` for a separate payout/release adapter. This separation prevents a dashboard approval bug from becoming an uncontrolled transfer mechanism.

API: `GET /api/admin/withdrawals`, `POST /api/admin/withdrawals`, `POST /api/admin/withdrawals/{id}/approve`, `POST /api/admin/withdrawals/{id}/reject`.

## Forex / OANDA practice integration

The platform now has a first-class OANDA v20 Forex adapter. OANDA documents a stable **fxTrade Practice** REST environment at `https://api-fxpractice.oanda.com` and a separate production environment at `https://api-fxtrade.oanda.com`. The practice environment is the default and is intended for testing. citeturn0search1

Configure the demo account in `.env`:

```text
FOREX_BROKER=oanda
OANDA_ACCOUNT_ID=your-practice-account-id
OANDA_API_TOKEN=your-practice-token
OANDA_PRACTICE=true
FOREX_DEMO_ENABLED=true
FOREX_LIVE_ENABLED=false
```

The adapter supports:

- account/NAV/margin state
- account-specific bid/ask pricing
- completed historical candles
- market orders
- attached stop-loss and take-profit on fill
- open-position retrieval
- position closeout
- OANDA transaction/order IDs
- timeout → `UNKNOWN` behavior

OANDA's v20 API supports real-time prices, historical pricing, order placement and account/trade state. citeturn0search0turn0search3

The platform's Forex demo endpoint is:

```text
POST /api/forex/demo/execute
```

It is locked unless `FOREX_DEMO_ENABLED=true` and `OANDA_PRACTICE=true`.

Run the read-only connectivity check:

```bash
python scripts/oanda_demo_check.py
```

It does **not** place an order. It verifies the practice account, retrieves account state, a live quote and instrument metadata.

OANDA recommends maintaining a complete account snapshot and updating it from account updates for a consistent view of pending orders, trades and positions; the production reconciliation layer should follow that pattern rather than treating a single order response as authoritative. citeturn0search7

### Forex symbol format

Use OANDA instrument names such as:

```text
EUR_USD
GBP_USD
USD_JPY
AUD_USD
USD_CAD
USD_CHF
NZD_USD
```

### Live Forex remains separately locked

Do **not** set `OANDA_PRACTICE=false` or `FOREX_LIVE_ENABLED=true` until the practice workflow has been validated end-to-end. The application keeps Forex live execution behind the existing global live confirmation and risk gates.

## Withdrawal execution architecture (v3)

Withdrawals use a four-stage control plane: **propose → dual approve → release → reconcile**. Approval never directly sends funds. A separate release operator must authenticate with `WITHDRAWAL_RELEASE_TOKENS`.

Production also supports an optional local Ed25519 signing gate. The server stores only the public key; the private key remains on the operator workstation. Generate a keypair with `python scripts/generate_signing_key.py`, configure `LOCAL_SIGNING_PUBLIC_KEY`, and sign the exact proposal digest with `python scripts/sign_withdrawal.py`.

For crypto/CEX execution, set `PAYOUT_PROVIDER=ccxt`, enable only the minimum exchange permissions required, use withdrawal whitelisting, and keep `PAYOUT_LIVE_ENABLED=false` until the exchange-specific testnet/sandbox acceptance test passes. For bank execution, configure the provider's exact signed HTTP contract and reconciliation endpoint; the app does not invent a bank API.

Destination whitelisting uses SHA-256 fingerprints generated with `python scripts/fingerprint_destination.py`. In production, a destination must be present in `WITHDRAWAL_DESTINATION_FINGERPRINTS`.

If a provider times out after submission, the withdrawal becomes `UNKNOWN` and must be reconciled. It is never blindly retried.

## Real USDT funding (3.3.2)

Customer funding now supports real **USDT on TRON / TRC-20**. Each customer receives a unique deposit address derived server-side from a master seed held in Google Secret Manager. Confirmed TRC-20 transfers are detected through TronGrid and credited once using an idempotent transaction reference. See `deploy/USDT_TRON.md`.

The official Tether TRON USDT contract is pinned to `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`. Customers must send only USDT over TRON / TRC-20 to the displayed address.

## Autonomous Daily Research
Atlas 3.6.0 can run a daily UTC research cycle. The cycle gathers configured Yahoo Finance historical market data and optional Alpha Vantage news/sentiment intelligence, backtests all strategy families plus the AI walk-forward model, produces an AI-assisted research brief, and updates paper/shadow candidates. It never enables real-money execution.

For production, use Redis for the distributed scheduler lock and keep all API keys in Secret Manager. Research-source freshness and licensing/entitlements must be validated for the intended commercial deployment.


## Trading discipline
Atlas applies deterministic discipline controls before new exposure is created: stop-distance risk budgeting, daily entry limits, entry cooldowns, daily-loss and peak-drawdown halts, portfolio exposure/leverage limits, stale-signal checks, spread/data gates, and protective-stop requirements for live exposure. AI cannot override these controls. See `RISK_MANAGEMENT_DISCIPLINE_3_10_35.md`.
