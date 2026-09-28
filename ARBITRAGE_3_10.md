# Atlas 3.10 — Binance Arbitrage Research Engine

## Scope
This release adds a deterministic, customer-scoped, paper-only triangular arbitrage research engine. It does **not** place live orders.

### Flow
Binance market data (future adapter) -> normalized quotes -> deterministic spread calculation -> fee/slippage/safety buffers -> customer capital gate -> PAPER_CANDIDATE / NO_TRADE -> audit/research record.

AI providers are intentionally outside the critical execution path.

## Safety
- Live arbitrage is disabled.
- Capital is limited by customer trading equity and `ARBITRAGE_MAX_CAPITAL_USDT`.
- Net edge must exceed `ARBITRAGE_MIN_NET_EDGE_PCT`.
- Invalid/stale/missing quotes are non-executable.
- No automatic retries or order submission are implemented in 3.10.

## Binance integration next
3.11 should add the authenticated Binance Spot Testnet adapter, local order-book reconstruction, latency metrics, order-state handling, partial-fill simulation, and reconciliation. Binance's official documentation states Spot Testnet is API-only and documents WebSocket lifecycle/rate limits; those constraints must be enforced by the adapter.
