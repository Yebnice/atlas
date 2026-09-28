# CHANGELOG — AtlasRisk 3.10.44

## Second-pass root-bug hardening

- Added explicit per-trade customer cash reserve persistence and slippage-buffer reservation.
- Preserved reserve through partial fills; terminal release is based on actual fill cost.
- Added reserve-deficit incident handling.
- Added execution-instance scoping for client-order identity.
- Added Redis lease refresh/fail-closed behavior before adaptive/executor submission.
- Hardened DCA/Grid START endpoints to return a clear paper-only controller-unavailable response.
- Corrected Deriv verification-only semantics in API/UI.
- Corrected release metadata/documentation to 3.10.44.
- Preserved previous fail-closed Deriv/arbitrage controls and execution fencing.


## Final audit additions

- Customer-isolated Binance reconciliation is independent of the platform default exchange.
- Reconciled order commands now enter a durable `RECONCILED` state.
- Unresolved customer orders open reconciliation incidents.
- Non-crypto customer automation is forced to paper/demo-only.
- DCA/Grid UI and APIs no longer imply an unavailable execution controller.
- Alert records are explicit configuration-only state until an evaluator worker exists.

- Live customer bot/executor activation now performs the same server-side live-authority preflight as order submission.
