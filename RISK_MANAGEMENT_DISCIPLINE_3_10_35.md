# Atlas 3.10.35 — Risk Management & Trading Discipline Review

## Scope
This review separates established risk-management principles from strategy claims. Risk controls are deterministic; AI cannot override them. No risk rule is presented as a guarantee of profit or prevention of loss.

## Established resources used as methodology references
- CME Group Education — Risk Management / trading-plan education: position sizing, stop planning, leverage awareness and predefined risk limits.
- National Futures Association (NFA) — Investor resources and forex risk disclosures: leveraged trading can magnify losses and requires understanding of account-specific risks.
- U.S. Commodity Futures Trading Commission (CFTC) — Customer advisories on leveraged/forex trading: leverage can produce losses beyond expectations and disciplined risk controls matter.
- Basel Committee on Banking Supervision — *Supervisory guidance for managing risks associated with trading activities* (risk limits, independent controls and escalation principles).
- CFA Institute — portfolio risk and performance-measurement material: distinguish return from risk, use drawdown/volatility and avoid treating historical performance as a forecast.

These references are used for general risk-control principles, not as evidence that any Atlas strategy is profitable. External websites were not reachable from this isolated build environment, so URLs were not live-verified during this patch.

## Atlas discipline controls
1. **Per-trade risk cap:** new exposure is rejected when stop-distance × quantity exceeds the configured risk budget (with a small explicit tolerance).
2. **Protective stop:** live exposure requires an explicit stop and broker support for an attached stop.
3. **Daily loss halt:** account/platform trading is halted when the configured daily loss limit is reached.
4. **Peak drawdown halt:** trading is halted when maximum drawdown is reached.
5. **Daily entry limit:** prevents unlimited re-entry/overtrading.
6. **Entry cooldown:** prevents immediate repeated entries and discourages revenge-style re-entry.
7. **Portfolio exposure limit:** limits aggregate notional exposure and leverage.
8. **Position-count limit:** limits simultaneous positions.
9. **Stale-signal protection:** live signals cannot be older than the configured age.
10. **Data/spread gates:** poor market data or excessive spread blocks execution.
11. **AI separation:** AI proposes/reviews; deterministic controls authorize or reject execution.
12. **Paper-first/live gate:** live trading remains explicitly disabled unless all independent production gates pass.

## What Atlas deliberately does not claim
- A fixed 0.5% risk-per-trade value is not universally optimal.
- A 2R/2.5R target does not prove positive expectancy.
- A Sharpe threshold does not prove future performance.
- A stop-loss cannot guarantee the exact fill price during gaps or market disruption.
- Backtests cannot establish future profitability.

## Discipline policy
A new exposure must pass the risk budget, drawdown, daily loss, exposure, position-count, signal-age, data-quality, spread, and entry-frequency gates. Reducing/closing exposure is not blocked by the new-entry cooldown or daily-entry count.

## Validation requirement
Before live enablement, validate these controls against the actual broker/exchange in sandbox/practice mode, including gap-through stops, rejected protective orders, partial fills, stale quotes, margin changes, API timeouts, duplicate requests, and reconciliation failures.
