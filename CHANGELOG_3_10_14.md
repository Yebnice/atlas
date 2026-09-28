# Atlas Trading OS 3.10.14

## Deriv real-account adapter
- Added server-side Deriv v3 WebSocket adapter for authorize, balance, active symbols, proposal, buy, sell and open-contract status.
- Added customer read-only preflight plus admin-controlled real execution endpoint.
- Real execution is fail-closed unless `DERIV_LIVE_ENABLED=true` and server-side credentials are configured.
- Unknown transport state is never blindly retried.
- Added explicit Google-Authenticator/AAL2 requirement to customer real execution.

## Binance arbitrage
- Added dedicated Binance Spot triangular-arbitrage adapter.
- Live path uses Binance Spot LIMIT/IOC execution through the exchange adapter and never auto-retries ambiguous legs.
- Added explicit capital cap, edge threshold, symbol preflight and live confirmation gate.
- Non-atomic three-leg execution is explicitly reported as such; an unresolved leg halts the cycle.
- Live execution remains disabled by default.

## Safety
- Deriv and Binance credentials remain server-side.
- No customer-supplied API secrets are accepted in request bodies.
- Real-money paths require explicit configuration and confirmation.

- Platform-wide broker credentials are never exposed through customer live-trading endpoints; customer live execution remains blocked until verified isolated broker/subaccount credentials are configured.

## 3.10.14.x Binance arbitrage recovery hardening
- Added pre-order Binance symbol-filter validation for price, quantity and minimum notional.
- Added ambiguous-leg recovery using broker order ID/client-order ID lookup.
- Partial or unresolved legs cannot advance the triangular cycle.
- Added focused regression coverage for partial fills and filter validation.
