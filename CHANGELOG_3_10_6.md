# Atlas Trading OS 3.10.6 — Execution Optimization & Isolation Hardening

## Added
- Cost-aware execution planner with executable-depth VWAP, market impact, fee and latency buffers.
- Order-type planning: MARKET, IOC_LIMIT, LIMIT_MAKER, or NO_TRADE.
- Customer endpoint `POST /api/customer/execution-plan` for research-only execution planning.
- Explicit `execution_authority: false` on execution-plan responses.

## Hardened
- Customer crypto live execution can no longer fall back to platform-wide exchange credentials.
- Customer crypto live execution remains fail-closed until a verified isolated exchange/subaccount adapter exists.
- Paper-trading fees are charged to the customer trading account, not platform cash equity.
- Execution planning blocks insufficient executable depth and excessive modeled adverse cost.

## Validation
- Focused execution/research regression suite: 24 passed.
- `python -m py_compile app/*.py`: passed.
- Full pytest collection remains environment-blocked by missing `aiosqlite` in the current runtime.

## Research basis
- Binance documents maker/taker fees, LIMIT/IOC/FOK/MARKET order behavior, order filters, and execution-status fields.
- Optimal execution literature models the tradeoff between volatility risk and temporary/permanent market impact.
- Recent Binance-based microstructure research finds maker fill probability can be adversely selected and taker fees materially affect profitability.


## 3.10.7 — Adaptive FX Macro-Quant Research
- Added major-FX adaptive research engine covering price trend, breakout, volatility, carry, monetary-policy, macro, valuation and order-flow features.
- Added forward-only walk-forward scoring and explicit research-only execution authority.
- Added cost gate and high-volatility risk scaling.
- Added `POST /api/research/fx-model`; live execution remains disabled.
- Research defaults are hypotheses, not claimed universal winning parameters.
