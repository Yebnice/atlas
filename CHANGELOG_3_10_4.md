# Atlas Trading OS 3.10.4 — Derivatives Stress Research Layer

## Evidence basis
- BIS research finds high crypto futures carry can precede crashes and that cash-and-carry positions can face severe margin/liquidation risk.
- 2026 research indicates liquidation precursors are event-dependent, so no single variable is treated as a crash predictor.
- Binance documents funding, basis, open-interest and order-book market-data primitives, plus WebSocket/user-data constraints for derivatives.

## Added
- `app/derivatives_risk.py`
- Funding/carry crowding score
- Open-interest expansion score
- Basis-stretch score
- Liquidation-pressure score (expects normalized input)
- Order-flow stress score
- Confidence based on available observations
- SEVERE/ELEVATED/WATCH/NORMAL states
- Explicit `BLOCK_NEW_RISK` / `REDUCE_RISK` / `MONITOR` research actions
- `execution_authority=false` and `directional_signal=false` hard boundaries
- Unit tests for missing-data safety and normalization

## Important
This layer is research/risk context only. Thresholds are conservative screening defaults and must be calibrated with venue-specific historical data before any live use. It does not authorize orders and does not claim to predict liquidations.
