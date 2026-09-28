# AtlasRisk 3.10.44 — Adversarial Root-Bug / Endpoint Audit

## Scope
Second-pass review of the corrected 3.10.43 build. Focus: hidden state-machine defects, dead-end endpoints, customer isolation, money accounting, execution idempotency, worker races, reconciliation, auth boundaries, and product/API truthfulness.

## High-severity defects found and corrected

1. **Platform/customer position collision** — platform reconciliation selected positions by symbol without restricting `customer_id`. Fixed to platform-only positions.
2. **Orphan PENDING trade on reserve race** — a committed Trade could remain PENDING when customer balance reservation failed. Fixed by marking the trade REJECTED and recording the reason.
3. **Executor recovery dead-end** — duplicate Trade responses did not return persisted fill state, so a crashed DCA/TWAP worker could repeatedly fail to advance. Fixed by returning persisted fill/remaining quantities.
4. **OANDA demo endpoint after close** — `enable_forex_demo` used the broker after closing it. Fixed by taking the account snapshot before close.
5. **Deriv customer execution auth boundary** — disabled execution endpoint previously failed closed without first authenticating the customer. Now AAL2 is required before the 409 response.
6. **Unauthenticated research endpoints** — FX execution TCA/route endpoints lacked the admin role gate. Fixed.
7. **Cross-executor client-order collision** — autonomous bots/executors sharing symbol/timeframe/candle/side could derive the same idempotency ID. Bot ID, executor ID, and explicit request ID are now included in execution scope.
8. **Customer cash reserve under-collateralization** — requested price was used to reconstruct reserves. Added persisted `Trade.reserved_cash`, pre-submit slippage buffer, and terminal-only reserve release.
9. **Reserve deficit after adverse fill** — if actual filled notional exceeds stored reserve, Atlas now attempts a ledger top-up and opens a critical incident when the customer cannot cover the deficit instead of silently under-collateralizing.
10. **Worker lock expiry race** — adaptive/executor Redis locks could expire during long cycles. A pre-submit refresh now fails closed if the worker no longer owns its lease.
11. **FX/commodity live dead-end** — customer automation could be labelled LIVE although OANDA is permanently practice/demo-only. Non-crypto customer automation is now paper-only; executor live approval is blocked.
12. **Customer reconciliation dead-end** — background reconciliation followed only the platform default exchange, while customer live funds are isolated on Binance. Added a separate customer-Binance reconciliation pass using customer credentials.
13. **Reconciliation command-state drift** — resolved trades could remain `OrderCommand.UNKNOWN`; reconciliation now marks the command `RECONCILED`.
14. **Silent unresolved order state** — customer order-not-found conditions now create durable reconciliation incidents.

## Endpoints/features confirmed as dead-end or configuration-only

- `/api/customer/dca-bots/{bot_id}/action` START: no DCA execution controller existed. It now fails closed instead of pretending to run a bot.
- `/api/customer/grid-bots/{bot_id}/action` START: no Grid execution controller existed. It now fails closed.
- `/api/customer/alerts`: no evaluator/notification worker existed. New alerts are now `CONFIGURED` rather than falsely `ACTIVE`.
- `/api/webhooks/{endpoint_id}`: intentionally persists authenticated webhook events as `RECEIVED_ONLY`; no downstream action is claimed by the endpoint.
- Smart Trade creation is explicitly paper-plan creation and does not claim live execution.

## Security / route surface

The reviewed customer and admin mutation routes have explicit customer authentication, admin authentication/role checks, or dedicated signed-webhook authentication. Public endpoints observed are the portal/auth flows, plan discovery, health/readiness, Stripe webhook, funding webhook, and signed Atlas webhook receiver.

## Verification

- Targeted second-pass suite: **79 passed**.
- Python compilation: **passed**.
- Alembic graph: **37 revisions, 37 unique, 0 missing parents, 1 head (`0037_execution_reserve_hardening`)**.
- Full `pytest -q`: blocked during collection because `aiosqlite` is unavailable in the sandbox.
- `bandit`, `pip-audit`, `ruff`, and `pyflakes`: unavailable in the sandbox.
- Real PostgreSQL migration/concurrency, Redis multi-worker failover, Cloud Run instance failover, exchange-sandbox fills/stops, Secret Manager access, immutable Cloud Logging, and dependency-CVE scans still require staging/CI.

## Residual architectural risks

- Database fencing is logical; it is not a broker-native fencing token. A network partition can still create an ambiguous exchange outcome, which is why UNKNOWN/reconciliation remains essential.
- The customer Binance subaccount ledger is not a complete exchange-wallet solvency reconciliation model yet.
- Protective-stop verification is post-submit; an exchange-side race can still occur between fill and confirmation, so the kill/incident path remains a compensating control.
- The build cannot be certified “perfect”; the remaining production work is real-environment validation and exchange/custody reconciliation drills.
